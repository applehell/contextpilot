"""Assembly page — assemble blocks within token budget."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTextEdit, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Signal

from src.gui.widgets.budget_bar import BudgetBar


class AssemblePage(QWidget):
    """Assembly page with budget control and preview.

    This assembles the local block pool. External skills get their context
    via the MCP Server's get_skill_context tool — not through this page.
    """

    assemble_requested = Signal()
    budget_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("Assemble Context")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        # Budget row
        budget_row = QHBoxLayout()
        budget_label = QLabel("Token Budget:")
        budget_label.setStyleSheet("font-weight: bold; color: #a6adc8;")
        budget_row.addWidget(budget_label)

        self._budget_bar = BudgetBar()
        budget_row.addWidget(self._budget_bar, stretch=1)

        self._budget_spin = QSpinBox()
        self._budget_spin.setRange(100, 200_000)
        self._budget_spin.setValue(8_000)
        self._budget_spin.setSuffix(" tokens")
        self._budget_spin.setSingleStep(1_000)
        self._budget_spin.valueChanged.connect(lambda v: self.budget_changed.emit(v))
        budget_row.addWidget(self._budget_spin)
        layout.addLayout(budget_row)

        # Assembly button
        assemble_btn = QPushButton("Assemble Context")
        assemble_btn.setObjectName("primary")
        assemble_btn.setMinimumHeight(40)
        assemble_btn.setToolTip(
            "Assemble all blocks within token budget "
            "(drop LOW → compress MEDIUM → truncate HIGH)"
        )
        assemble_btn.clicked.connect(self.assemble_requested)
        layout.addWidget(assemble_btn)

        # Info
        info = QLabel(
            "Assembles the local block pool within the token budget. "
            "External skills receive their context automatically via the MCP Server "
            "(get_skill_context) — they score and select relevant blocks based on their context hints."
        )
        info.setStyleSheet("color: #6c7086; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Preview
        preview_label = QLabel("Assembly Preview")
        preview_label.setStyleSheet("font-weight: bold; color: #a6adc8;")
        layout.addWidget(preview_label)

        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setPlaceholderText("Click 'Assemble Context' to preview...")
        self._preview.setStyleSheet(
            "background: #11111b; border: 1px solid #313244; border-radius: 6px; "
            "font-family: monospace; font-size: 12px;"
        )
        layout.addWidget(self._preview, stretch=1)

    @property
    def budget(self) -> int:
        return self._budget_spin.value()

    @budget.setter
    def budget(self, value: int) -> None:
        self._budget_spin.setValue(value)

    def update_budget_bar(self, used: int, total: int) -> None:
        self._budget_bar.update_budget(used, total)

    def set_preview(self, text: str) -> None:
        self._preview.setPlainText(text)
