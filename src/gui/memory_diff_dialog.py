"""Memory Diff Dialog — shows proposed memory changes from skills with accept/reject."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QFont

from src.storage.memory import Memory, MemoryStore


class MemoryChange:
    """Represents a proposed memory change from a skill."""

    def __init__(
        self,
        key: str,
        new_value: str,
        new_tags: List[str],
        skill_name: str,
        old_value: Optional[str] = None,
        old_tags: Optional[List[str]] = None,
    ) -> None:
        self.key = key
        self.new_value = new_value
        self.new_tags = new_tags
        self.skill_name = skill_name
        self.old_value = old_value
        self.old_tags = old_tags

    @property
    def is_new(self) -> bool:
        return self.old_value is None

    @property
    def is_modified(self) -> bool:
        return self.old_value is not None and self.old_value != self.new_value


def _compute_diff_lines(old: str, new: str) -> List[tuple]:
    """Simple line-by-line diff. Returns [(type, line), ...] where type is '+', '-', or ' '."""
    old_lines = old.splitlines() if old else []
    new_lines = new.splitlines()

    result: List[tuple] = []

    # Simple LCS-based diff
    m, n = len(old_lines), len(new_lines)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m):
        for j in range(n):
            if old_lines[i] == new_lines[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])

    i, j = m, n
    ops = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and old_lines[i - 1] == new_lines[j - 1]:
            ops.append((' ', old_lines[i - 1]))
            i -= 1
            j -= 1
        elif j > 0 and (i == 0 or dp[i][j - 1] >= dp[i - 1][j]):
            ops.append(('+', new_lines[j - 1]))
            j -= 1
        else:
            ops.append(('-', old_lines[i - 1]))
            i -= 1
    ops.reverse()
    return ops


class _ChangeCard(QWidget):
    """Single change card with diff view and accept checkbox."""

    def __init__(self, change: MemoryChange, parent=None) -> None:
        super().__init__(parent)
        self._change = change
        self._build_ui()

    @property
    def change(self) -> MemoryChange:
        return self._change

    @property
    def accepted(self) -> bool:
        return self._checkbox.isChecked()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Header
        header = QHBoxLayout()
        self._checkbox = QCheckBox()
        self._checkbox.setChecked(True)
        header.addWidget(self._checkbox)

        action = "NEW" if self._change.is_new else "MODIFIED"
        color = "#a6e3a1" if self._change.is_new else "#f9e2af"
        key_label = QLabel(
            f"<span style='color:{color};font-weight:bold;'>[{action}]</span> "
            f"<b>{self._change.key}</b> "
            f"<span style='color:#a6adc8;'>(from {self._change.skill_name})</span>"
        )
        header.addWidget(key_label, stretch=1)

        if self._change.new_tags:
            tags = ", ".join(self._change.new_tags)
            tag_label = QLabel(f"<span style='color:#a6adc8;font-size:11px;'>tags: {tags}</span>")
            header.addWidget(tag_label)
        layout.addLayout(header)

        # Diff view
        diff_view = QTextEdit()
        diff_view.setReadOnly(True)
        diff_view.setMaximumHeight(160)
        diff_view.setStyleSheet("background: #11111b; border: 1px solid #313244; border-radius: 4px;")

        if self._change.is_new:
            html = "<pre style='margin:4px;'>"
            for line in self._change.new_value.splitlines():
                html += f"<span style='color:#a6e3a1;'>+ {_esc(line)}</span>\n"
            html += "</pre>"
        else:
            diff = _compute_diff_lines(self._change.old_value or "", self._change.new_value)
            html = "<pre style='margin:4px;'>"
            for op, line in diff:
                if op == '+':
                    html += f"<span style='color:#a6e3a1;'>+ {_esc(line)}</span>\n"
                elif op == '-':
                    html += f"<span style='color:#f38ba8;'>- {_esc(line)}</span>\n"
                else:
                    html += f"<span style='color:#6c7086;'>  {_esc(line)}</span>\n"
            html += "</pre>"
        diff_view.setHtml(html)
        layout.addWidget(diff_view)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class MemoryDiffDialog(QDialog):
    """Dialog showing proposed memory changes with diffs."""

    def __init__(self, changes: List[MemoryChange], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Skill Memory Changes")
        self.setMinimumWidth(650)
        self.setMinimumHeight(450)

        layout = QVBoxLayout(self)

        new_count = sum(1 for c in changes if c.is_new)
        mod_count = sum(1 for c in changes if c.is_modified)
        summary = f"{len(changes)} change(s): {new_count} new, {mod_count} modified"
        layout.addWidget(QLabel(summary))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        cards_layout = QVBoxLayout(container)
        cards_layout.setSpacing(8)

        self._cards: List[_ChangeCard] = []
        for change in changes:
            card = _ChangeCard(change)
            self._cards.append(card)
            cards_layout.addWidget(card)

        cards_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Apply Selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accepted_changes(self) -> List[MemoryChange]:
        return [card.change for card in self._cards if card.accepted]
