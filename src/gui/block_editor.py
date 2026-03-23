from __future__ import annotations

import copy
from typing import List

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

from src.core.block import Block, Priority
from src.gui.widgets.block_card import BlockCard


class _EditDialog(QDialog):
    """Dialog to create or edit a single Block."""

    def __init__(self, block: Block, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Block")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._content = QTextEdit()
        self._content.setPlainText(block.content)
        self._content.setMinimumHeight(130)
        form.addRow("Content:", self._content)

        self._priority = QComboBox()
        for p in Priority:
            self._priority.addItem(p.value, p)
        self._priority.setCurrentIndex(list(Priority).index(block.priority))
        form.addRow("Priority:", self._priority)

        self._hint = QLineEdit()
        self._hint.setText(block.compress_hint or "")
        self._hint.setPlaceholderText("e.g. bullet_extract, code_compact")
        form.addRow("Compress hint:", self._hint)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_block(self) -> Block:
        return Block(
            content=self._content.toPlainText(),
            priority=self._priority.currentData(),
            compress_hint=self._hint.text().strip() or None,
        )


class BlockEditor(QWidget):
    """Drag-and-drop block list editor.

    Signals:
        blocks_changed: emitted whenever the block list is modified;
                        carries the new list[Block].
    """

    blocks_changed = Signal(list)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._blocks: List[Block] = []
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_blocks(self, blocks: List[Block]) -> None:
        self._blocks = list(blocks)
        self._refresh()

    def get_blocks(self) -> List[Block]:
        return list(self._blocks)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ Add Block")
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._add_block)
        toolbar.addWidget(add_btn)

        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.setToolTip("Refresh block list")
        refresh_btn.clicked.connect(self._refresh)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #a6adc8; font-size: 12px;")
        toolbar.addWidget(self._count_label)
        layout.addLayout(toolbar)

        self._list = QListWidget()
        self._list.setDragDropMode(QAbstractItemView.InternalMove)
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        layout.addWidget(self._list)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        self._list.clear()
        total_tokens = sum(b.token_count for b in self._blocks)
        if hasattr(self, "_count_label"):
            self._count_label.setText(f"{len(self._blocks)} blocks, {total_tokens:,} tokens")
        for block in self._blocks:
            self._append_item(block)

    def _append_item(self, block: Block) -> None:
        item = QListWidgetItem()
        card = BlockCard(block)
        card.edit_clicked.connect(lambda b=block: self._edit_block(b))
        card.delete_clicked.connect(lambda b=block: self._delete_block(b))
        card.duplicate_clicked.connect(lambda b=block: self._duplicate_block(b))
        item.setSizeHint(card.sizeHint())
        self._list.addItem(item)
        self._list.setItemWidget(item, card)

    def _sync_blocks_from_list(self) -> None:
        """Re-read block order from the QListWidget (after drag-drop)."""
        new_blocks: List[Block] = []
        for row in range(self._list.count()):
            widget = self._list.itemWidget(self._list.item(row))
            if isinstance(widget, BlockCard):
                new_blocks.append(widget.block)
        self._blocks = new_blocks

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _add_block(self) -> None:
        dlg = _EditDialog(Block(content=""), self)
        if dlg.exec() == QDialog.Accepted:
            block = dlg.result_block()
            self._blocks.append(block)
            self._refresh()
            self.blocks_changed.emit(self._blocks)

    def _edit_block(self, block: Block) -> None:
        try:
            idx = self._blocks.index(block)
        except ValueError:
            return
        dlg = _EditDialog(block, self)
        if dlg.exec() == QDialog.Accepted:
            self._blocks[idx] = dlg.result_block()
            self._refresh()
            self.blocks_changed.emit(self._blocks)

    def _delete_block(self, block: Block) -> None:
        try:
            self._blocks.remove(block)
        except ValueError:
            return
        self._refresh()
        self.blocks_changed.emit(self._blocks)

    def _duplicate_block(self, block: Block) -> None:
        try:
            idx = self._blocks.index(block)
        except ValueError:
            return
        self._blocks.insert(idx + 1, copy.copy(block))
        self._refresh()
        self.blocks_changed.emit(self._blocks)

    def _test_compression(self, block: Block) -> None:
        from src.core.compressors.bullet_extract import BulletExtractCompressor
        from src.core.compressors.code_compact import CodeCompactCompressor

        registry = {
            "bullet_extract": BulletExtractCompressor(),
            "code_compact": CodeCompactCompressor(),
        }
        hint = block.compress_hint or ""
        compressor = registry.get(hint)
        if compressor is None:
            QMessageBox.information(
                self,
                "Test Compression",
                f"No compressor registered for hint '{hint}'.\n"
                "Supported: bullet_extract, code_compact",
            )
            return
        compressed = compressor.compress(block)
        savings = block.token_count - compressed.token_count
        QMessageBox.information(
            self,
            "Test Compression",
            f"Original: {block.token_count} tokens\n"
            f"Compressed: {compressed.token_count} tokens\n"
            f"Savings: {savings} tokens\n\n"
            f"Preview:\n{compressed.content[:300]}",
        )

    # ------------------------------------------------------------------
    # Signals / events
    # ------------------------------------------------------------------

    def _context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        row = self._list.row(item)
        if row < 0 or row >= len(self._blocks):
            return
        block = self._blocks[row]
        menu = QMenu(self)
        menu.addAction("Edit", lambda: self._edit_block(block))
        menu.addAction("Duplicate", lambda: self._duplicate_block(block))
        menu.addAction("Test Compression", lambda: self._test_compression(block))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete_block(block))
        menu.exec(self._list.mapToGlobal(pos))

    def _on_rows_moved(self, *_) -> None:
        self._sync_blocks_from_list()
        self.blocks_changed.emit(self._blocks)
