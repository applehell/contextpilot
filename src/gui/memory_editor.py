"""Memory Editor — GUI panel for CRUD operations on the MemoryStore."""
from __future__ import annotations

from typing import Dict, List, Optional

from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt, Signal

import time as _time

from src.storage.memory import Memory, MemoryStore
from src.core.block import Block, Priority
from src.core.assembler import Assembler
from src.core.token_budget import TokenBudget

_RECENT_SECONDS = 86400  # 24h
from src.importers.claude import import_claude_file
from src.importers.copilot import import_copilot_file
from src.importers.sqlite import detect_sqlite_type, import_memory_mcp, import_generic_sqlite


class _MemoryDialog(QDialog):
    """Dialog to create or edit a Memory."""

    def __init__(self, memory: Optional[Memory] = None, existing_tags: Optional[List[str]] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Memory" if memory else "New Memory")
        self.setMinimumWidth(460)
        self._editing = memory is not None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._key = QLineEdit()
        if memory:
            self._key.setText(memory.key)
            self._key.setReadOnly(True)
        else:
            self._key.setPlaceholderText("unique-key")
        form.addRow("Key:", self._key)

        self._value = QTextEdit()
        self._value.setPlainText(memory.value if memory else "")
        self._value.setMinimumHeight(120)
        form.addRow("Value:", self._value)

        self._tags = QLineEdit()
        self._tags.setPlaceholderText("tag1, tag2, tag3")
        if memory and memory.tags:
            self._tags.setText(", ".join(memory.tags))
        form.addRow("Tags:", self._tags)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_memory(self) -> Memory:
        tags = [t.strip() for t in self._tags.text().split(",") if t.strip()]
        return Memory(
            key=self._key.text().strip(),
            value=self._value.toPlainText(),
            tags=tags,
        )


class _MemoryCard(QFrame):
    """Compact card for displaying one Memory entry."""

    edit_clicked = Signal()
    delete_clicked = Signal()

    def __init__(self, memory: Memory, parent=None) -> None:
        super().__init__(parent)
        self._memory = memory
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self._build_ui()

    @property
    def memory(self) -> Memory:
        return self._memory

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(8)

        # Status badge (NEU / GEAENDERT)
        now = _time.time()
        is_new = (now - self._memory.created_at) < _RECENT_SECONDS
        is_modified = (
            not is_new
            and abs(self._memory.updated_at - self._memory.created_at) > 2
            and (now - self._memory.updated_at) < _RECENT_SECONDS
        )

        if is_new or is_modified:
            badge_text = "NEU" if is_new else "UPD"
            badge_color = "#a6e3a1" if is_new else "#f9e2af"
            badge = QLabel(badge_text)
            badge.setFixedWidth(32)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"color: #1e1e2e; background: {badge_color}; "
                "font-size: 9px; font-weight: bold; border-radius: 4px; padding: 1px 4px;"
            )
            root.addWidget(badge)

        info = QVBoxLayout()
        info.setSpacing(2)

        key_row = QHBoxLayout()
        key_row.setSpacing(6)
        key_label = QLabel(self._memory.key)
        key_label.setStyleSheet("font-weight: bold;")
        key_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        key_row.addWidget(key_label)
        key_row.addStretch()
        info.addLayout(key_row)

        preview = self._memory.value[:100].replace("\n", " ")
        if len(self._memory.value) > 100:
            preview += "..."
        val_label = QLabel(preview)
        val_label.setStyleSheet("color: #555;")
        val_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        info.addWidget(val_label)

        meta_parts = []
        if self._memory.tags:
            meta_parts.append(", ".join(self._memory.tags))
        # Show age
        age = now - self._memory.updated_at
        if age < 3600:
            meta_parts.append(f"vor {int(age / 60)} Min")
        elif age < 86400:
            meta_parts.append(f"vor {int(age / 3600)} Std")
        else:
            meta_parts.append(f"vor {int(age / 86400)} Tagen")

        if meta_parts:
            meta_label = QLabel(" | ".join(meta_parts))
            meta_label.setStyleSheet("color: gray; font-size: 10px;")
            info.addWidget(meta_label)

        root.addLayout(info)

        tok = TokenBudget.estimate(self._memory.value)
        tok_label = QLabel(f"{tok} t")
        tok_label.setStyleSheet("color: gray; font-size: 11px;")
        tok_label.setFixedWidth(46)
        tok_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(tok_label)

        edit_btn = QPushButton("Edit")
        edit_btn.setFixedWidth(40)
        edit_btn.clicked.connect(self.edit_clicked)
        root.addWidget(edit_btn)

        del_btn = QPushButton("Del")
        del_btn.setFixedWidth(36)
        del_btn.clicked.connect(self.delete_clicked)
        root.addWidget(del_btn)


_SCAN_PATTERNS = {
    "CLAUDE.md": {
        "globs": ["**/CLAUDE.md", "**/.claude/CLAUDE.md"],
        "parser": "claude",
    },
    "copilot-instructions.md": {
        "globs": ["**/.github/copilot-instructions.md", "**/copilot-instructions.md"],
        "parser": "copilot",
    },
}

_SCAN_ROOTS = [
    Path.home(),
    Path.home() / "Documents",
    Path.home() / "Projects",
    Path.home() / ".claude",
]

_SQLITE_KNOWN_PATHS = [
    Path.home() / ".local" / "share" / "claude-memories" / "memory.db",
]


def _scan_for_memory_files() -> List[tuple]:
    """Scan common locations for importable memory files.

    Returns list of (path, file_type) tuples.
    """
    import glob as globmod

    found: dict[str, str] = {}

    for root in _SCAN_ROOTS:
        if not root.is_dir():
            continue
        for file_type, info in _SCAN_PATTERNS.items():
            for pattern in info["globs"]:
                for match in globmod.glob(str(root / pattern), recursive=True):
                    p = Path(match).resolve()
                    if p.is_file() and str(p) not in found:
                        found[str(p)] = info["parser"]

    for db_path in _SQLITE_KNOWN_PATHS:
        if db_path.is_file() and str(db_path.resolve()) not in found:
            db_type = detect_sqlite_type(db_path)
            if db_type:
                found[str(db_path.resolve())] = db_type

    return [(Path(p), t) for p, t in sorted(found.items())]


class _ScanResultDialog(QDialog):
    """Dialog showing discovered memory files with checkboxes for selection."""

    def __init__(self, results: List[tuple], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scan Results")
        self.setMinimumWidth(600)
        self.setMinimumHeight(350)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Found {len(results)} importable file(s):"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        self._checks_layout = QVBoxLayout(container)
        self._checks_layout.setContentsMargins(4, 4, 4, 4)

        self._checkboxes: List[tuple] = []
        for path, parser_type in results:
            label = f"[{parser_type}]  {path}"
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._checks_layout.addWidget(cb)
            self._checkboxes.append((cb, path, parser_type))

        self._checks_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        btn_row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_all.clicked.connect(lambda: self._toggle_all(True))
        btn_row.addWidget(select_all)
        select_none = QPushButton("Select None")
        select_none.clicked.connect(lambda: self._toggle_all(False))
        btn_row.addWidget(select_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _toggle_all(self, state: bool) -> None:
        for cb, _, _ in self._checkboxes:
            cb.setChecked(state)

    def selected_files(self) -> List[tuple]:
        return [(p, t) for cb, p, t in self._checkboxes if cb.isChecked()]


class _SqliteMapDialog(QDialog):
    """Dialog to map SQLite table columns to memory fields."""

    def __init__(self, tables: List[str], columns_by_table: Dict[str, List[str]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SQLite Column Mapping")
        self.setMinimumWidth(420)
        self._columns_by_table = columns_by_table

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Map database columns to memory fields:"))

        form = QFormLayout()

        self._table_combo = QComboBox()
        self._table_combo.addItems(tables)
        self._table_combo.currentTextChanged.connect(self._on_table_changed)
        form.addRow("Table:", self._table_combo)

        self._key_combo = QComboBox()
        form.addRow("Key column:", self._key_combo)

        self._value_combo = QComboBox()
        form.addRow("Value column:", self._value_combo)

        self._tag_combo = QComboBox()
        self._tag_combo.addItem("(none)")
        form.addRow("Tags column (optional):", self._tag_combo)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if tables:
            self._on_table_changed(tables[0])

    def _on_table_changed(self, table: str) -> None:
        cols = self._columns_by_table.get(table, [])
        for combo in (self._key_combo, self._value_combo):
            combo.clear()
            combo.addItems(cols)
        self._tag_combo.clear()
        self._tag_combo.addItem("(none)")
        self._tag_combo.addItems(cols)
        if len(cols) >= 2:
            self._key_combo.setCurrentIndex(0)
            self._value_combo.setCurrentIndex(1)

    def result_mapping(self) -> tuple:
        table = self._table_combo.currentText()
        key_col = self._key_combo.currentText()
        value_col = self._value_combo.currentText()
        tag_col = self._tag_combo.currentText()
        if tag_col == "(none)":
            tag_col = None
        return table, key_col, value_col, tag_col


class MemoryEditor(QWidget):
    """Full memory management panel with search, filter, CRUD, and context preview.

    Signals:
        memories_changed: emitted whenever memories are modified.
    """

    memories_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._store: Optional[MemoryStore] = None
        self._build_ui()

    def set_store(self, store: MemoryStore) -> None:
        self._store = store
        self._refresh_tags()
        self._refresh_list()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Search + filter row
        search_row = QHBoxLayout()
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search memories...")
        self._search.textChanged.connect(self._refresh_list)
        search_row.addWidget(self._search, stretch=1)

        self._tag_filter = QComboBox()
        self._tag_filter.addItem("All tags")
        self._tag_filter.setMinimumWidth(120)
        self._tag_filter.currentIndexChanged.connect(self._refresh_list)
        search_row.addWidget(self._tag_filter)

        layout.addLayout(search_row)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ New Memory")
        add_btn.setMinimumHeight(28)
        add_btn.clicked.connect(self._add_memory)
        toolbar.addWidget(add_btn)

        import_btn = QPushButton("Import...")
        import_btn.setMinimumHeight(28)
        import_menu = QMenu(self)
        import_menu.addAction("CLAUDE.md...", self._import_claude)
        import_menu.addAction("copilot-instructions.md...", self._import_copilot)
        import_menu.addSeparator()
        import_menu.addAction("memory-mcp Database...", self._import_memory_mcp)
        import_menu.addAction("SQLite Database...", self._import_generic_sqlite)
        import_menu.addSeparator()
        import_menu.addAction("Scan local machine...", self._scan_and_import)
        import_btn.setMenu(import_menu)
        toolbar.addWidget(import_btn)

        preview_btn = QPushButton("Preview as Context")
        preview_btn.setMinimumHeight(28)
        preview_btn.clicked.connect(self._preview_context)
        toolbar.addWidget(preview_btn)

        refresh_btn = QPushButton("\u21BB Refresh")
        refresh_btn.setMinimumHeight(28)
        refresh_btn.setToolTip("Reload memory list")
        refresh_btn.clicked.connect(self._do_refresh)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch()

        self._mem_count = QLabel("")
        self._mem_count.setStyleSheet("color: #a6adc8; font-size: 12px;")
        toolbar.addWidget(self._mem_count)
        layout.addLayout(toolbar)

        # Memory list
        self._list = QListWidget()
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self._list)

        # Preview area
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(150)
        self._preview.setPlaceholderText("Select 'Preview as Context' to see how memories assemble...")
        layout.addWidget(self._preview)

    def _refresh_tags(self) -> None:
        self._tag_filter.blockSignals(True)
        current = self._tag_filter.currentText()
        self._tag_filter.clear()
        self._tag_filter.addItem("All tags")
        if self._store:
            for tag in self._store.tags():
                self._tag_filter.addItem(tag)
        idx = self._tag_filter.findText(current)
        if idx >= 0:
            self._tag_filter.setCurrentIndex(idx)
        self._tag_filter.blockSignals(False)

    def _do_refresh(self) -> None:
        self._refresh_tags()
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        if self._store is None:
            if hasattr(self, "_mem_count"):
                self._mem_count.setText("")
            return

        query = self._search.text().strip()
        tag_text = self._tag_filter.currentText()
        tags = [tag_text] if tag_text != "All tags" else None

        if query or tags:
            memories = self._store.search(query or "", tags=tags)
        else:
            memories = self._store.list()

        if hasattr(self, "_mem_count"):
            self._mem_count.setText(f"{len(memories)} memories")

        for mem in memories:
            item = QListWidgetItem()
            card = _MemoryCard(mem)
            card.edit_clicked.connect(lambda m=mem: self._edit_memory(m))
            card.delete_clicked.connect(lambda m=mem: self._delete_memory(m))
            item.setSizeHint(card.sizeHint())
            self._list.addItem(item)
            self._list.setItemWidget(item, card)

    def _add_memory(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Memory", "No database open. Open a project first.")
            return
        existing_tags = self._store.tags()
        dlg = _MemoryDialog(existing_tags=existing_tags, parent=self)
        if dlg.exec() == QDialog.Accepted:
            mem = dlg.result_memory()
            if not mem.key:
                QMessageBox.warning(self, "Error", "Key cannot be empty.")
                return
            self._store.set(mem)
            self._refresh_tags()
            self._refresh_list()
            self.memories_changed.emit()

    def _edit_memory(self, memory: Memory) -> None:
        if self._store is None:
            return
        existing_tags = self._store.tags()
        dlg = _MemoryDialog(memory=memory, existing_tags=existing_tags, parent=self)
        if dlg.exec() == QDialog.Accepted:
            updated = dlg.result_memory()
            self._store.set(updated)
            self._refresh_tags()
            self._refresh_list()
            self.memories_changed.emit()

    def _delete_memory(self, memory: Memory) -> None:
        if self._store is None:
            return
        reply = QMessageBox.question(
            self, "Delete Memory",
            f"Delete memory '{memory.key}'?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            try:
                self._store.delete(memory.key)
            except KeyError:
                pass
            self._refresh_tags()
            self._refresh_list()
            self.memories_changed.emit()

    def _context_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        widget = self._list.itemWidget(item)
        if not isinstance(widget, _MemoryCard):
            return
        mem = widget.memory
        menu = QMenu(self)
        menu.addAction("Edit", lambda: self._edit_memory(mem))
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete_memory(mem))
        menu.exec(self._list.mapToGlobal(pos))

    def _scan_and_import(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Scan", "No database open. Open a project first.")
            return

        progress = QProgressDialog("Scanning for memory files...", "Cancel", 0, 0, self)
        progress.setWindowTitle("Scanning")
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()

        results = _scan_for_memory_files()
        progress.close()

        if not results:
            QMessageBox.information(self, "Scan", "No importable files found.")
            return

        dlg = _ScanResultDialog(results, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return

        selected = dlg.selected_files()
        if not selected:
            return

        parsers = {
            "claude": import_claude_file,
            "copilot": import_copilot_file,
            "memory-mcp": import_memory_mcp,
        }
        total = 0
        errors = []
        for path, parser_type in selected:
            parser = parsers.get(parser_type)
            if not parser:
                continue
            try:
                memories = parser(path)
                for mem in memories:
                    self._store.set(mem)
                    total += 1
            except Exception as exc:
                errors.append(f"{path}: {exc}")

        self._refresh_tags()
        self._refresh_list()
        self.memories_changed.emit()

        msg = f"{total} memories imported from {len(selected)} file(s)."
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)
        QMessageBox.information(self, "Import", msg)

    def _import_claude(self) -> None:
        self._import_file(
            "Import CLAUDE.md",
            "Markdown (CLAUDE.md *.md);;All files (*)",
            import_claude_file,
        )

    def _import_copilot(self) -> None:
        self._import_file(
            "Import copilot-instructions.md",
            "Markdown (*.md);;All files (*)",
            import_copilot_file,
        )

    def _import_memory_mcp(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Import", "No database open. Open a project first.")
            return
        default_path = str(Path.home() / ".local" / "share" / "claude-memories")
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import memory-mcp Database", default_path,
            "SQLite DB (*.db);;All files (*)",
        )
        if not file_path:
            return
        db_type = detect_sqlite_type(Path(file_path))
        if db_type != "memory-mcp":
            reply = QMessageBox.question(
                self, "Import",
                "This does not look like a memory-mcp database. Import anyway?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        try:
            memories = import_memory_mcp(Path(file_path))
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return
        if not memories:
            QMessageBox.information(self, "Import", "No memories found in database.")
            return
        count = 0
        for mem in memories:
            self._store.set(mem)
            count += 1
        self._refresh_tags()
        self._refresh_list()
        self.memories_changed.emit()
        QMessageBox.information(self, "Import", f"{count} memories imported from memory-mcp.")

    def _import_generic_sqlite(self) -> None:
        if self._store is None:
            QMessageBox.information(self, "Import", "No database open. Open a project first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import SQLite Database", "",
            "SQLite DB (*.db *.sqlite *.sqlite3);;All files (*)",
        )
        if not file_path:
            return

        import sqlite3 as _sqlite3
        try:
            conn = _sqlite3.connect(file_path)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts%'"
            ).fetchall()]
            if not tables:
                QMessageBox.information(self, "Import", "No tables found in database.")
                conn.close()
                return
            columns_by_table = {}
            for t in tables:
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info([{t}])").fetchall()]
                columns_by_table[t] = cols
            conn.close()
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", f"Cannot read database: {exc}")
            return

        dlg = _SqliteMapDialog(tables, columns_by_table, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return

        table, key_col, value_col, tag_col = dlg.result_mapping()
        try:
            memories = import_generic_sqlite(Path(file_path), table, key_col, value_col, tag_col)
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return
        if not memories:
            QMessageBox.information(self, "Import", "No memories found.")
            return
        count = 0
        for mem in memories:
            self._store.set(mem)
            count += 1
        self._refresh_tags()
        self._refresh_list()
        self.memories_changed.emit()
        QMessageBox.information(self, "Import", f"{count} memories imported from SQLite.")

    def _import_file(self, title: str, file_filter: str, parser) -> None:
        if self._store is None:
            QMessageBox.information(self, "Import", "No database open. Open a project first.")
            return
        file_path, _ = QFileDialog.getOpenFileName(self, title, "", file_filter)
        if not file_path:
            return
        try:
            memories = parser(Path(file_path))
        except Exception as exc:
            QMessageBox.critical(self, "Import Error", str(exc))
            return
        if not memories:
            QMessageBox.information(self, "Import", "No memories found in file.")
            return
        count = 0
        for mem in memories:
            self._store.set(mem)
            count += 1
        self._refresh_tags()
        self._refresh_list()
        self.memories_changed.emit()
        QMessageBox.information(self, "Import", f"{count} memories imported.")

    def _preview_context(self) -> None:
        if self._store is None:
            self._preview.setPlainText("(no database open)")
            return
        memories = self._store.list()
        if not memories:
            self._preview.setPlainText("(no memories stored)")
            return
        blocks = [
            Block(content=f"[{m.key}] {m.value}", priority=Priority.MEDIUM)
            for m in memories
        ]
        total_tokens = sum(b.token_count for b in blocks)
        lines = [f"Memories: {len(memories)} entries, {total_tokens:,} tokens total", ""]
        for m in memories:
            tok = TokenBudget.estimate(m.value)
            tags = f" [{', '.join(m.tags)}]" if m.tags else ""
            lines.append(f"  {m.key}{tags}: {tok} tokens")
        self._preview.setPlainText("\n".join(lines))
