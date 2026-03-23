"""Dashboard page — overview with status cards and quick stats."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, Signal


class _StatusCard(QFrame):
    """Compact status card with title, value, and optional detail."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; "
            "border-radius: 10px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; border: none;")
        layout.addWidget(self._title)

        self._value = QLabel("—")
        self._value.setStyleSheet("color: #cdd6f4; font-size: 22px; font-weight: bold; border: none;")
        layout.addWidget(self._value)

        self._detail = QLabel("")
        self._detail.setStyleSheet("color: #6c7086; font-size: 11px; border: none;")
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)

    def set_value(self, value: str) -> None:
        self._value.setText(value)

    def set_detail(self, detail: str) -> None:
        self._detail.setText(detail)

    def set_color(self, color: str) -> None:
        self._value.setStyleSheet(f"color: {color}; font-size: 22px; font-weight: bold; border: none;")


class DashboardPage(QWidget):
    """Dashboard with overview cards."""

    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)

        # Header with refresh
        header_row = QHBoxLayout()
        header = QLabel("Dashboard")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4;")
        header_row.addWidget(header)
        header_row.addStretch()
        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.setToolTip("Refresh dashboard stats")
        refresh_btn.clicked.connect(self.refresh_requested)
        header_row.addWidget(refresh_btn)
        layout.addLayout(header_row)

        # Cards grid
        grid = QGridLayout()
        grid.setSpacing(12)

        self._budget_card = _StatusCard("TOKEN BUDGET")
        grid.addWidget(self._budget_card, 0, 0)

        self._blocks_card = _StatusCard("BLOCKS")
        grid.addWidget(self._blocks_card, 0, 1)

        self._skills_card = _StatusCard("SKILLS")
        grid.addWidget(self._skills_card, 0, 2)

        self._memories_card = _StatusCard("MEMORIES")
        grid.addWidget(self._memories_card, 0, 3)

        self._server_card = _StatusCard("SERVERS")
        grid.addWidget(self._server_card, 1, 0)

        self._project_card = _StatusCard("PROJECT")
        grid.addWidget(self._project_card, 1, 1, 1, 2)

        self._assembly_card = _StatusCard("LAST ASSEMBLY")
        grid.addWidget(self._assembly_card, 1, 3)

        layout.addLayout(grid)

        # Budget bar
        budget_frame = QFrame()
        budget_frame.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; border-radius: 10px; }"
        )
        bf_layout = QVBoxLayout(budget_frame)
        bf_layout.setContentsMargins(14, 10, 14, 10)

        bl = QLabel("Token Budget Usage")
        bl.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; border: none;")
        bf_layout.addWidget(bl)

        self._budget_progress = QProgressBar()
        self._budget_progress.setRange(0, 100)
        self._budget_progress.setValue(0)
        self._budget_progress.setTextVisible(True)
        self._budget_progress.setFormat("%v% used")
        bf_layout.addWidget(self._budget_progress)

        self._budget_detail = QLabel("0 / 8,000 tokens")
        self._budget_detail.setStyleSheet("color: #6c7086; font-size: 11px; border: none;")
        bf_layout.addWidget(self._budget_detail)

        layout.addWidget(budget_frame)

        # Skill status list
        skills_frame = QFrame()
        skills_frame.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; border-radius: 10px; }"
        )
        sf_layout = QVBoxLayout(skills_frame)
        sf_layout.setContentsMargins(14, 10, 14, 10)

        sl = QLabel("Connected Skills")
        sl.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; border: none;")
        sf_layout.addWidget(sl)

        self._skills_list = QLabel("No skills connected")
        self._skills_list.setStyleSheet("color: #6c7086; font-size: 12px; border: none;")
        self._skills_list.setWordWrap(True)
        sf_layout.addWidget(self._skills_list)

        layout.addWidget(skills_frame)

        # Memory activity feed
        activity_frame = QFrame()
        activity_frame.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; border-radius: 10px; }"
        )
        af_layout = QVBoxLayout(activity_frame)
        af_layout.setContentsMargins(14, 10, 14, 10)

        al = QLabel("Memory Activity")
        al.setStyleSheet("color: #a6adc8; font-size: 11px; font-weight: bold; border: none;")
        af_layout.addWidget(al)

        self._activity_list = QLabel("Keine Aktivitaet")
        self._activity_list.setStyleSheet("color: #6c7086; font-size: 12px; border: none;")
        self._activity_list.setWordWrap(True)
        af_layout.addWidget(self._activity_list)

        layout.addWidget(activity_frame)
        layout.addStretch()

    def update_stats(
        self,
        block_count: int = 0,
        token_used: int = 0,
        token_budget: int = 8000,
        skill_total: int = 0,
        skill_enabled: int = 0,
        memory_count: int = 0,
        mcp_running: bool = False,
        cli_running: bool = False,
        project_name: str = "",
        last_assembly: str = "",
        skill_details: str = "",
        activity_html: str = "",
    ) -> None:
        # Budget
        pct = int(token_used / token_budget * 100) if token_budget else 0
        self._budget_card.set_value(f"{token_used:,}")
        self._budget_card.set_detail(f"of {token_budget:,} tokens ({pct}%)")
        if pct > 90:
            self._budget_card.set_color("#f38ba8")
        elif pct > 70:
            self._budget_card.set_color("#f9e2af")
        else:
            self._budget_card.set_color("#a6e3a1")

        self._budget_progress.setValue(min(pct, 100))
        self._budget_detail.setText(f"{token_used:,} / {token_budget:,} tokens")

        # Blocks
        self._blocks_card.set_value(str(block_count))
        self._blocks_card.set_detail("context blocks loaded")

        # Skills
        self._skills_card.set_value(f"{skill_enabled}/{skill_total}")
        self._skills_card.set_detail("skills enabled")
        if skill_enabled > 0:
            self._skills_card.set_color("#a6e3a1")
        else:
            self._skills_card.set_color("#6c7086")

        # Memories
        self._memories_card.set_value(str(memory_count))
        self._memories_card.set_detail("memories stored")

        # Servers
        parts = []
        if mcp_running:
            parts.append("MCP running")
        if cli_running:
            parts.append("CLI running")
        self._server_card.set_value(str(len(parts)))
        self._server_card.set_detail(", ".join(parts) if parts else "no servers running")
        if parts:
            self._server_card.set_color("#a6e3a1")
        else:
            self._server_card.set_color("#6c7086")

        # Project
        self._project_card.set_value(project_name or "No project")
        self._project_card.set_detail("open" if project_name else "File > Open/New to start")

        # Assembly
        self._assembly_card.set_value(last_assembly or "—")
        self._assembly_card.set_detail("")

        # Skills list
        self._skills_list.setText(skill_details or "No skills connected")

        # Activity feed
        self._activity_list.setText(activity_html or "Keine Aktivitaet")
