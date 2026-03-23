"""Skill Monitor — live dashboard for MCP-connected external skills."""
from __future__ import annotations

import time
from typing import List, Optional

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QTimer, Signal

from src.core.skill_registry import SkillRegistry, ExternalSkill


class _SkillCard(QFrame):
    """Live status card for one connected skill."""

    def __init__(self, skill: ExternalSkill, parent=None) -> None:
        super().__init__(parent)
        self._skill = skill
        self.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; border-radius: 8px; }"
        )
        self._build_ui()

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(12)

        # Status indicator
        alive = self._skill.is_alive
        color = "#a6e3a1" if alive else "#f38ba8"
        dot = QLabel("\u25CF")
        dot.setStyleSheet(f"color: {color}; font-size: 20px; border: none;")
        dot.setFixedWidth(24)
        dot.setAlignment(Qt.AlignCenter)
        root.addWidget(dot)

        # Info column
        info = QVBoxLayout()
        info.setSpacing(3)

        name_label = QLabel(f"<b>{self._skill.name}</b>")
        name_label.setStyleSheet("color: #cdd6f4; font-size: 14px; border: none;")
        info.addWidget(name_label)

        desc = QLabel(self._skill.description)
        desc.setStyleSheet("color: #a6adc8; font-size: 12px; border: none;")
        desc.setWordWrap(True)
        info.addWidget(desc)

        if self._skill.context_hints:
            hints = ", ".join(self._skill.context_hints[:6])
            hints_lbl = QLabel(f"context hints: {hints}")
            hints_lbl.setStyleSheet("color: #6c7086; font-size: 11px; border: none;")
            info.addWidget(hints_lbl)

        root.addLayout(info, stretch=1)

        # Stats column
        stats = QVBoxLayout()
        stats.setSpacing(3)
        stats.setAlignment(Qt.AlignRight | Qt.AlignTop)

        status_text = "CONNECTED" if alive else "STALE"
        status_lbl = QLabel(status_text)
        status_lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold; border: none;"
        )
        status_lbl.setAlignment(Qt.AlignRight)
        stats.addWidget(status_lbl)

        blocks_lbl = QLabel(f"{self._skill.blocks_served} blocks served")
        blocks_lbl.setStyleSheet("color: #a6adc8; font-size: 11px; border: none;")
        blocks_lbl.setAlignment(Qt.AlignRight)
        stats.addWidget(blocks_lbl)

        ago = int(time.time() - self._skill.last_seen)
        if ago < 60:
            seen = f"{ago}s ago"
        elif ago < 3600:
            seen = f"{ago // 60}m ago"
        else:
            seen = f"{ago // 3600}h ago"
        seen_lbl = QLabel(f"last seen: {seen}")
        seen_lbl.setStyleSheet("color: #6c7086; font-size: 10px; border: none;")
        seen_lbl.setAlignment(Qt.AlignRight)
        stats.addWidget(seen_lbl)

        root.addLayout(stats)


class SkillMonitor(QWidget):
    """Live monitor for MCP-connected skills.

    Auto-refreshes every 3 seconds to show current connections.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(3000)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Toolbar
        toolbar = QHBoxLayout()

        self._status_label = QLabel("No skills connected")
        self._status_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        toolbar.addWidget(self._status_label)

        toolbar.addStretch()

        cleanup_btn = QPushButton("Cleanup Stale")
        cleanup_btn.setMinimumHeight(28)
        cleanup_btn.setToolTip("Remove skills that haven't sent a heartbeat in 2+ minutes")
        cleanup_btn.clicked.connect(self._cleanup)
        toolbar.addWidget(cleanup_btn)

        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)

        layout.addLayout(toolbar)

        # Skill list
        self._list = QListWidget()
        self._list.setStyleSheet("QListWidget { border: none; background: transparent; }")
        layout.addWidget(self._list)

        # Empty state
        self._empty_label = QLabel(
            "No external skills connected.\n\n"
            "Skills connect via the Context Pilot MCP Server.\n"
            "Start the MCP Server on the Servers page, then from any MCP client:\n\n"
            "  1. register_skill(name, description, context_hints)\n"
            "  2. get_skill_context(name, token_budget)\n"
            "  3. memory_list() / memory_get() / memory_set()\n"
            "  4. heartbeat(name)  — every 60s to stay connected"
        )
        self._empty_label.setStyleSheet(
            "color: #6c7086; font-size: 12px; padding: 20px; "
            "background: #1e1e2e; border: 1px dashed #45475a; border-radius: 8px;"
        )
        self._empty_label.setWordWrap(True)
        self._empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._empty_label)

        # Log area
        log_label = QLabel("Activity Log")
        log_label.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold;")
        layout.addWidget(log_label)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(120)
        self._log.setStyleSheet(
            "background: #11111b; border: 1px solid #313244; border-radius: 4px; "
            "font-family: monospace; font-size: 11px; color: #a6adc8;"
        )
        self._log.setPlaceholderText("Skill activity will appear here...")
        layout.addWidget(self._log)

        self._last_skill_names: set = set()
        self._refresh()

    def _refresh(self) -> None:
        registry = SkillRegistry.instance()
        skills = registry.list_all()

        # Update status label
        alive = [s for s in skills if s.is_alive]
        stale = [s for s in skills if not s.is_alive]
        parts = []
        if alive:
            parts.append(f"<span style='color:#a6e3a1;'>{len(alive)} connected</span>")
        if stale:
            parts.append(f"<span style='color:#f38ba8;'>{len(stale)} stale</span>")
        if parts:
            self._status_label.setText(" | ".join(parts))
        else:
            self._status_label.setText("No skills connected")

        # Toggle empty state vs list
        self._empty_label.setVisible(not skills)
        self._list.setVisible(bool(skills))

        # Rebuild cards
        self._list.clear()
        for skill in sorted(skills, key=lambda s: (not s.is_alive, s.name)):
            item = QListWidgetItem()
            card = _SkillCard(skill)
            item.setSizeHint(card.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

        # Log new connections / disconnections
        current_names = {s.name for s in skills}
        new_skills = current_names - self._last_skill_names
        gone_skills = self._last_skill_names - current_names
        for name in new_skills:
            self._log_msg(f"[+] {name} connected")
        for name in gone_skills:
            self._log_msg(f"[-] {name} disconnected")
        self._last_skill_names = current_names

    def _cleanup(self) -> None:
        registry = SkillRegistry.instance()
        removed = registry.cleanup_stale()
        if removed:
            self._log_msg(f"Cleaned up {removed} stale skill(s)")
        self._refresh()

    def _log_msg(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._log.append(f"[{ts}] {msg}")

    def stop_timer(self) -> None:
        self._timer.stop()
