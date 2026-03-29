"""Usage tracking — records block inclusion in assemblies and user feedback."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .db import Database


def block_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class UsageRecord:
    block_hash: str
    project_name: Optional[str] = None
    context_name: Optional[str] = None
    skill_name: Optional[str] = None
    model_id: Optional[str] = None
    included: bool = True
    token_count: int = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class FeedbackRecord:
    assembly_id: str
    block_hash: str
    helpful: bool
    created_at: float = field(default_factory=time.time)


@dataclass
class BlockWeight:
    block_hash: str
    project_name: Optional[str]
    weight: float = 1.0
    usage_count: int = 0
    feedback_score: float = 0.0
    updated_at: float = field(default_factory=time.time)


class UsageStore:
    """SQLite-backed usage tracking for blocks, feedback, and weights."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Usage recording ──────────────────────────────────────────────

    def record_usage(self, records: List[UsageRecord]) -> None:
        self._db.conn.executemany(
            """INSERT INTO block_usage
               (block_hash, project_name, context_name, skill_name, model_id,
                included, token_count, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (r.block_hash, r.project_name, r.context_name, r.skill_name,
                 r.model_id, int(r.included), r.token_count, r.created_at)
                for r in records
            ],
        )
        self._db.conn.commit()

    def get_usage_counts(self, project_name: Optional[str] = None) -> Dict[str, int]:
        if project_name:
            rows = self._db.conn.execute(
                """SELECT block_hash, COUNT(*) as cnt FROM block_usage
                   WHERE included = 1 AND project_name = ?
                   GROUP BY block_hash""",
                (project_name,),
            ).fetchall()
        else:
            rows = self._db.conn.execute(
                """SELECT block_hash, COUNT(*) as cnt FROM block_usage
                   WHERE included = 1 GROUP BY block_hash"""
            ).fetchall()
        return {r["block_hash"]: r["cnt"] for r in rows}

    def get_inclusion_rate(self, bh: str, project_name: Optional[str] = None) -> float:
        if project_name:
            row = self._db.conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN included = 1 THEN 1 ELSE 0 END) as incl
                   FROM block_usage WHERE block_hash = ? AND project_name = ?""",
                (bh, project_name),
            ).fetchone()
        else:
            row = self._db.conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN included = 1 THEN 1 ELSE 0 END) as incl
                   FROM block_usage WHERE block_hash = ?""",
                (bh,),
            ).fetchone()
        total = row["total"]
        if total == 0:
            return 1.0
        return (row["incl"] or 0) / total

    # ── Feedback ─────────────────────────────────────────────────────

    def record_feedback(self, feedback: FeedbackRecord) -> None:
        self._db.conn.execute(
            """INSERT INTO assembly_feedback
               (assembly_id, block_hash, helpful, created_at)
               VALUES (?, ?, ?, ?)""",
            (feedback.assembly_id, feedback.block_hash,
             int(feedback.helpful), feedback.created_at),
        )
        self._db.conn.commit()

    def get_feedback_score(self, bh: str) -> float:
        row = self._db.conn.execute(
            """SELECT COUNT(*) as total,
                      SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END) as pos
               FROM assembly_feedback WHERE block_hash = ?""",
            (bh,),
        ).fetchone()
        total = row["total"]
        if total == 0:
            return 0.0
        return ((row["pos"] or 0) / total) * 2.0 - 1.0  # Range: -1.0 to 1.0

    def get_assembly_feedback(self, assembly_id: str) -> List[FeedbackRecord]:
        rows = self._db.conn.execute(
            """SELECT assembly_id, block_hash, helpful, created_at
               FROM assembly_feedback WHERE assembly_id = ?""",
            (assembly_id,),
        ).fetchall()
        return [
            FeedbackRecord(
                assembly_id=r["assembly_id"],
                block_hash=r["block_hash"],
                helpful=bool(r["helpful"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ── Block weights ────────────────────────────────────────────────

    def get_weight(self, bh: str, project_name: Optional[str] = None) -> Optional[BlockWeight]:
        pn = project_name or ""
        row = self._db.conn.execute(
            """SELECT block_hash, project_name, weight, usage_count,
                      feedback_score, updated_at
               FROM block_weights WHERE block_hash = ? AND project_name = ?""",
            (bh, pn),
        ).fetchone()
        if not row:
            return None
        return BlockWeight(
            block_hash=row["block_hash"],
            project_name=row["project_name"],
            weight=row["weight"],
            usage_count=row["usage_count"],
            feedback_score=row["feedback_score"],
            updated_at=row["updated_at"],
        )

    def save_weight(self, w: BlockWeight) -> None:
        pn = w.project_name or ""
        self._db.conn.execute(
            """INSERT INTO block_weights
               (block_hash, project_name, weight, usage_count, feedback_score, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(block_hash, project_name) DO UPDATE SET
                 weight = excluded.weight,
                 usage_count = excluded.usage_count,
                 feedback_score = excluded.feedback_score,
                 updated_at = excluded.updated_at""",
            (w.block_hash, pn, w.weight,
             w.usage_count, w.feedback_score, w.updated_at),
        )
        self._db.conn.commit()

    # ── Skill-Block Relevance ────────────────────────────────────────

    def record_skill_relevance(
        self, skill_name: str, block_hash: str, included: bool, feedback: float = 0.0,
    ) -> None:
        now = time.time()
        if included:
            self._db.conn.execute(
                """INSERT INTO skill_block_relevance
                   (skill_name, block_hash, score, included_count, dropped_count, feedback_sum, updated_at)
                   VALUES (?, ?, 0.5, 1, 0, ?, ?)
                   ON CONFLICT(skill_name, block_hash) DO UPDATE SET
                     included_count = included_count + 1,
                     feedback_sum = feedback_sum + ?,
                     updated_at = ?""",
                (skill_name, block_hash, feedback, now, feedback, now),
            )
        else:
            self._db.conn.execute(
                """INSERT INTO skill_block_relevance
                   (skill_name, block_hash, score, included_count, dropped_count, feedback_sum, updated_at)
                   VALUES (?, ?, 0.5, 0, 1, 0.0, ?)
                   ON CONFLICT(skill_name, block_hash) DO UPDATE SET
                     dropped_count = dropped_count + 1,
                     updated_at = ?""",
                (skill_name, block_hash, now, now),
            )
        self._db.conn.commit()

    def get_skill_relevance(self, skill_name: str) -> Dict[str, Any]:
        from ..core.relevance import SkillRelevanceProfile
        rows = self._db.conn.execute(
            """SELECT skill_name, block_hash, score, included_count, dropped_count,
                      feedback_sum, updated_at
               FROM skill_block_relevance WHERE skill_name = ?""",
            (skill_name,),
        ).fetchall()
        return {
            r["block_hash"]: SkillRelevanceProfile(
                skill_name=r["skill_name"],
                block_hash=r["block_hash"],
                score=r["score"],
                included_count=r["included_count"],
                dropped_count=r["dropped_count"],
                feedback_sum=r["feedback_sum"],
            )
            for r in rows
        }

    def update_skill_relevance_scores(self, skill_name: str) -> None:
        """Recompute relevance scores from inclusion/feedback data."""
        rows = self._db.conn.execute(
            """SELECT block_hash, included_count, dropped_count, feedback_sum
               FROM skill_block_relevance WHERE skill_name = ?""",
            (skill_name,),
        ).fetchall()
        now = time.time()
        for r in rows:
            total = r["included_count"] + r["dropped_count"]
            if total == 0:
                continue
            inclusion_rate = r["included_count"] / total
            feedback_avg = r["feedback_sum"] / max(1, r["included_count"])
            feedback_signal = (feedback_avg + 1.0) / 2.0
            score = inclusion_rate * 0.6 + feedback_signal * 0.4
            self._db.conn.execute(
                """UPDATE skill_block_relevance SET score = ?, updated_at = ?
                   WHERE skill_name = ? AND block_hash = ?""",
                (score, now, skill_name, r["block_hash"]),
            )
        self._db.conn.commit()

    def record_skill_feedback(
        self, skill_name: str, block_hash: str, helpful: bool,
    ) -> None:
        delta = 1.0 if helpful else -1.0
        now = time.time()
        self._db.conn.execute(
            """UPDATE skill_block_relevance
               SET feedback_sum = feedback_sum + ?, updated_at = ?
               WHERE skill_name = ? AND block_hash = ?""",
            (delta, now, skill_name, block_hash),
        )
        self._db.conn.commit()

