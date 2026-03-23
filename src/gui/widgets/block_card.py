from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Signal, Qt

from src.core.block import Block, Priority

_PRIORITY_COLOUR = {
    Priority.HIGH: "#e53935",
    Priority.MEDIUM: "#fb8c00",
    Priority.LOW: "#757575",
}

_PRIORITY_LABEL = {
    Priority.HIGH: "HIGH",
    Priority.MEDIUM: "MED",
    Priority.LOW: "LOW",
}


class BlockCard(QFrame):
    """Compact card displaying one Block with priority badge and action buttons."""

    edit_clicked = Signal()
    delete_clicked = Signal()
    duplicate_clicked = Signal()

    def __init__(self, block: Block, parent=None) -> None:
        super().__init__(parent)
        self._block = block
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self._build_ui()

    @property
    def block(self) -> Block:
        return self._block

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        # Priority badge
        colour = _PRIORITY_COLOUR[self._block.priority]
        badge = QLabel(_PRIORITY_LABEL[self._block.priority])
        badge.setFixedWidth(36)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(
            f"background: {colour}; color: white; border-radius: 3px;"
            " font-size: 10px; font-weight: bold;"
        )
        root.addWidget(badge)

        # Content preview + compress hint
        info = QVBoxLayout()
        info.setSpacing(2)
        preview = self._block.content[:90].replace("\n", " ")
        if len(self._block.content) > 90:
            preview += "…"
        content_label = QLabel(preview)
        content_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info.addWidget(content_label)
        if self._block.compress_hint:
            hint_label = QLabel(f"hint: {self._block.compress_hint}")
            hint_label.setStyleSheet("color: gray; font-size: 10px;")
            info.addWidget(hint_label)
        root.addLayout(info)

        # Token count
        tok_label = QLabel(f"{self._block.token_count} t")
        tok_label.setStyleSheet("color: gray; font-size: 11px;")
        tok_label.setFixedWidth(46)
        tok_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(tok_label)

        # Buttons
        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(40)
        edit_btn.clicked.connect(self.edit_clicked)
        root.addWidget(edit_btn)

        dup_btn = QPushButton("Dup")
        dup_btn.setFixedWidth(36)
        dup_btn.clicked.connect(self.duplicate_clicked)
        root.addWidget(dup_btn)

        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(36)
        del_btn.clicked.connect(self.delete_clicked)
        root.addWidget(del_btn)
