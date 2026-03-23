"""Sidebar navigation with icon buttons."""
from __future__ import annotations

from typing import List

from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget, QLabel
from PySide6.QtCore import Signal, Qt, QSize


class SidebarButton(QPushButton):
    """Icon-style sidebar button with label underneath."""

    def __init__(self, icon_char: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(72, 56)
        self._label = label
        self._icon_char = icon_char
        self.setText(f"{icon_char}\n{label}")
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #6c7086;
                border: none;
                border-radius: 8px;
                font-size: 11px;
                padding: 4px;
            }
            QPushButton:hover {
                background: #313244;
                color: #cdd6f4;
            }
            QPushButton:checked {
                background: #45475a;
                color: #ff8f40;
                font-weight: bold;
            }
        """)


class Sidebar(QWidget):
    """Vertical sidebar with navigation buttons."""

    page_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedWidth(80)
        self.setStyleSheet("background: #11111b; border-right: 1px solid #313244;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)

        # Logo
        logo = QLabel("CP")
        logo.setAlignment(Qt.AlignCenter)
        logo.setFixedHeight(36)
        logo.setStyleSheet(
            "color: #ff6b2c; font-size: 18px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        layout.addWidget(logo)
        layout.addSpacing(8)

        self._buttons: List[SidebarButton] = []
        pages = [
            ("\u2302", "Dashboard"),   # ⌂
            ("\u25A6", "Blocks"),       # ▦
            ("\u2691", "Memories"),     # ⚑
            ("\u2699", "Skills"),       # ⚙
            ("\u21C4", "Servers"),      # ⇄
            ("\u25B6", "Assemble"),     # ▶
            ("\u2B95", "Graph"),        # ⮕
        ]

        for i, (icon, label) in enumerate(pages):
            btn = SidebarButton(icon, label)
            btn.clicked.connect(lambda checked, idx=i: self._on_clicked(idx))
            self._buttons.append(btn)
            layout.addWidget(btn, alignment=Qt.AlignHCenter)

        layout.addStretch()

        # Select first by default
        if self._buttons:
            self._buttons[0].setChecked(True)

    def _on_clicked(self, index: int) -> None:
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
        self.page_changed.emit(index)

    def set_page(self, index: int) -> None:
        self._on_clicked(index)
