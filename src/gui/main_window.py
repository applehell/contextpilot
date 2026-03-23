from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QInputDialog, QLabel, QMainWindow,
    QMessageBox, QStackedWidget, QStatusBar, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QTimer

from src.core.assembler import Assembler
from src.core.block import Block, Priority
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.skill_registry import SkillRegistry
from src.storage.db import Database
from src.storage.memory import MemoryStore
from src.storage.memory_activity import MemoryActivityLog
from src.storage.project import ContextConfig, ProjectMeta, ProjectStore
from src.storage.settings import get_last_project, set_last_project
from src.storage.usage import UsageStore
from src.gui.block_editor import BlockEditor
from src.gui.memory_editor import MemoryEditor
from src.gui.skill_monitor import SkillMonitor
from src.gui.sidebar import Sidebar
from src.gui.pages.dashboard import DashboardPage
from src.gui.pages.servers import ServersPage
from src.gui.pages.assemble import AssemblePage
from src.gui.pages.knowledge_graph import KnowledgeGraphPage

_COMPRESSORS = [BulletExtractCompressor(), CodeCompactCompressor()]
_ICON_PATH = Path(__file__).parent / "assets" / "icon.png"

_PAGE_DASHBOARD = 0
_PAGE_BLOCKS = 1
_PAGE_MEMORIES = 2
_PAGE_SKILLS = 3
_PAGE_SERVERS = 4
_PAGE_ASSEMBLE = 5
_PAGE_GRAPH = 6


class MainWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Context Pilot")
        self.resize(1100, 750)
        if _ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(_ICON_PATH)))

        self._db: Optional[Database] = None
        self._store: Optional[ProjectStore] = None
        self._memory_store: Optional[MemoryStore] = None
        self._usage_store: Optional[UsageStore] = None
        self._activity_log: Optional[MemoryActivityLog] = None
        self._shared_activity_log: Optional[MemoryActivityLog] = None
        self._current_project: Optional[ProjectMeta] = None
        self._current_db_path: Optional[str] = None
        self._assembler = Assembler(_COMPRESSORS)
        self._last_assembly_info = ""

        self._build_menu()
        self._build_ui()
        self._refresh_dashboard()

        # Auto-refresh dashboard every 5s (picks up MCP skill changes)
        self._dashboard_timer = QTimer(self)
        self._dashboard_timer.timeout.connect(self._refresh_dashboard)
        self._dashboard_timer.start(5000)

        QTimer.singleShot(100, self._auto_open_last_project)

    # ── Menu ──────────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        mb = self.menuBar()
        file_menu = mb.addMenu("File")
        for label, shortcut, slot in [
            ("New Project…", "Ctrl+N", self._new_project),
            ("Open Project…", "Ctrl+O", self._open_project),
            ("Save Project", "Ctrl+S", self._save_project),
        ]:
            act = QAction(label, self)
            act.setShortcut(shortcut)
            act.triggered.connect(slot)
            file_menu.addAction(act)
        file_menu.addSeparator()
        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        help_menu = mb.addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(self._show_about)
        help_menu.addAction(about_act)

    # ── UI ────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._sidebar = Sidebar()
        self._sidebar.page_changed.connect(self._on_page_changed)
        root.addWidget(self._sidebar)

        self._stack = QStackedWidget()

        # 0: Dashboard
        self._dashboard = DashboardPage()
        self._dashboard.refresh_requested.connect(self._refresh_dashboard)
        self._stack.addWidget(self._dashboard)

        # 1: Blocks
        self._editor = BlockEditor()
        self._editor.blocks_changed.connect(self._on_data_changed)
        self._stack.addWidget(self._wrap_page("Blocks", self._editor))

        # 2: Memories
        self._memory_editor = MemoryEditor()
        self._stack.addWidget(self._wrap_page("Memories", self._memory_editor))

        # 3: Skills (live monitor — no hardcoded skills)
        self._skill_monitor = SkillMonitor()
        self._stack.addWidget(self._wrap_page("Connected Skills", self._skill_monitor))

        # 4: Servers
        self._servers_page = ServersPage()
        self._servers_page.server_state_changed.connect(self._refresh_dashboard)
        self._stack.addWidget(self._servers_page)

        # 5: Assemble
        self._assemble_page = AssemblePage()
        self._assemble_page.assemble_requested.connect(self._assemble)
        self._stack.addWidget(self._assemble_page)

        # 6: Knowledge Graph
        self._graph_page = KnowledgeGraphPage()
        self._stack.addWidget(self._graph_page)

        root.addWidget(self._stack, stretch=1)

        # Status bar
        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._skill_label = QLabel()
        self._skill_label.setStyleSheet("color: #a6adc8; font-size: 11px; padding: 0 8px;")
        self._status_bar.addPermanentWidget(self._skill_label)
        self._status_bar.showMessage("Ready — start MCP Server to accept skill connections")

    def _wrap_page(self, title: str, widget: QWidget) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        header = QLabel(title)
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)
        layout.addWidget(widget, stretch=1)
        return page

    # ── Navigation ────────────────────────────────────────────────────

    def _on_page_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        if index == _PAGE_DASHBOARD:
            self._refresh_dashboard()
        elif index == _PAGE_GRAPH:
            self._graph_page.refresh()

    # ── Data Changed ──────────────────────────────────────────────────

    def _on_data_changed(self, *_) -> None:
        self._refresh_dashboard()

    # ── Status Bar ────────────────────────────────────────────────────

    def _update_skill_label(self) -> None:
        registry = SkillRegistry.instance()
        parts = []
        for ext in registry.list_all():
            color = "#89b4fa" if ext.is_alive else "#f38ba8"
            parts.append(f"<span style='color:{color};'>{ext.name}</span>")
        if parts:
            self._skill_label.setText(f"MCP Skills: {' | '.join(parts)}")
        else:
            self._skill_label.setText("")

    # ── Dashboard ─────────────────────────────────────────────────────

    def _refresh_dashboard(self) -> None:
        blocks = self._editor.get_blocks() if hasattr(self, "_editor") else []
        budget = self._assemble_page.budget if hasattr(self, "_assemble_page") else 8000
        used = sum(b.token_count for b in blocks)

        memory_count = 0
        if self._memory_store:
            try:
                memory_count = len(self._memory_store.list())
            except Exception:
                pass

        # Memory activity feed (reads from shared DB used by MCP server)
        activity_html = ""
        try:
            log = self._get_or_create_activity_log()
            if log:
                entries = log.recent(15)
                if entries:
                    _OP_COLORS = {
                        "created": "#a6e3a1",
                        "updated": "#f9e2af",
                        "deleted": "#f38ba8",
                        "loaded": "#89b4fa",
                        "searched": "#cba6f7",
                    }
                    lines = []
                    for e in entries:
                        color = _OP_COLORS.get(e.operation, "#6c7086")
                        op_label = e.operation.upper()
                        detail = f" — {e.detail}" if e.detail else ""
                        lines.append(
                            f"<span style='color:{color};'>[{op_label}]</span> "
                            f"<b>{e.memory_key}</b>{detail} "
                            f"<span style='color:#585b70;'>{e.age_label}</span>"
                        )
                    activity_html = "<br>".join(lines)
        except Exception:
            pass

        registry = SkillRegistry.instance()
        all_ext = registry.list_all()
        alive_ext = registry.list_alive()

        skill_lines = []
        for ext in all_ext:
            color = "#89b4fa" if ext.is_alive else "#f38ba8"
            status = "CONNECTED" if ext.is_alive else "STALE"
            hints = ", ".join(ext.context_hints[:4]) if ext.context_hints else "—"
            blocks_info = f"{ext.blocks_served} blocks" if ext.blocks_served else "no blocks yet"
            skill_lines.append(
                f"<span style='color:{color};'>[{status}]</span> "
                f"<b>{ext.name}</b> — {ext.description[:50]} "
                f"<span style='color:#6c7086;'>({hints}) | {blocks_info}</span>"
            )

        mcp_running = self._servers_page.mcp_running if hasattr(self, "_servers_page") else False
        cli_running = self._servers_page.cli_running if hasattr(self, "_servers_page") else False

        self._dashboard.update_stats(
            block_count=len(blocks),
            token_used=used,
            token_budget=budget,
            skill_total=len(all_ext),
            skill_enabled=len(alive_ext),
            memory_count=memory_count,
            mcp_running=mcp_running,
            cli_running=cli_running,
            project_name=self._current_project.name if self._current_project else "",
            last_assembly=self._last_assembly_info,
            skill_details="<br>".join(skill_lines) if skill_lines else (
                "No skills connected — start MCP Server and register skills"
            ),
            activity_html=activity_html,
        )
        self._update_skill_label()

    def _get_or_create_activity_log(self) -> Optional[MemoryActivityLog]:
        """Return activity log from the shared MCP database.

        MCP server always writes to ~/.contextpilot/data.db, so we read
        activity from there regardless of which project DB is open.
        """
        if self._shared_activity_log is not None:
            return self._shared_activity_log
        shared_db_path = Path.home() / ".contextpilot" / "data.db"
        if shared_db_path.exists():
            try:
                shared_db = Database(shared_db_path, check_same_thread=False)
                self._shared_activity_log = MemoryActivityLog(shared_db)
                return self._shared_activity_log
            except Exception:
                pass
        return None

    # ── Assembly ──────────────────────────────────────────────────────

    def _assemble(self) -> None:
        """Assemble blocks within budget. Skills get context via MCP, not here."""
        blocks = self._editor.get_blocks() if hasattr(self, "_editor") else []
        budget = self._assemble_page.budget
        if not blocks:
            self._assemble_page.set_preview("(no blocks — add blocks or import memories)")
            return
        assembled = self._assembler.assemble(blocks, budget)
        self._assemble_page.set_preview("\n\n---\n\n".join(b.content for b in assembled))
        used = sum(b.token_count for b in assembled)
        self._assemble_page.update_budget_bar(used, budget)
        self._last_assembly_info = f"{len(assembled)}/{len(blocks)} blocks, {used:,}t"
        self._status_bar.showMessage(f"Assembled: {self._last_assembly_info}")
        self._refresh_dashboard()

    # ── Auto-open ─────────────────────────────────────────────────────

    def _auto_open_last_project(self) -> None:
        last_db = get_last_project()
        if last_db and Path(last_db).exists():
            try:
                self._open_db(Path(last_db))
            except Exception:
                pass

    # ── Project Actions ───────────────────────────────────────────────

    def _open_db(self, db_path: Path, project_name: Optional[str] = None) -> None:
        db = Database(db_path)
        store = ProjectStore(db)
        projects = store.list_projects()
        if not projects:
            db.close()
            return
        if project_name:
            name = project_name
        else:
            projects.sort(key=lambda p: p.last_used, reverse=True)
            name = projects[0].name

        meta, contexts = store.load(name)
        if self._db is not None:
            self._db.close()
        self._db = db
        self._store = store
        self._memory_store = MemoryStore(db)
        self._usage_store = UsageStore(db)
        self._activity_log = MemoryActivityLog(db)
        self._memory_editor.set_store(self._memory_store)
        self._graph_page.set_store(self._memory_store)
        self._current_project = meta
        self._current_db_path = str(db_path)

        blocks: List[Block] = []
        default_ctx = next((c for c in contexts if c.name == "default"), None)
        if default_ctx:
            for bd in default_ctx.blocks:
                try:
                    prio = Priority(bd.get("priority", "medium"))
                except ValueError:
                    prio = Priority.MEDIUM
                blocks.append(Block(
                    content=bd.get("content", ""), priority=prio,
                    compress_hint=bd.get("compress_hint"),
                ))
        self._editor.set_blocks(blocks)

        set_last_project(str(db_path))
        self.setWindowTitle(f"Context Pilot — {name}")
        self._status_bar.showMessage(f"Opened '{name}'")
        self._refresh_dashboard()

    def _new_project(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Directory for New Database")
        if not folder:
            return
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        db_path = Path(folder) / "contextpilot.db"
        db = Database(db_path)
        store = ProjectStore(db)
        try:
            store.create(ProjectMeta(name=name))
        except FileExistsError:
            QMessageBox.warning(self, "Error", f"Project '{name}' already exists.")
            db.close()
            return
        if self._db is not None:
            self._db.close()
        self._db = db
        self._store = store
        self._memory_store = MemoryStore(db)
        self._usage_store = UsageStore(db)
        self._activity_log = MemoryActivityLog(db)
        self._memory_editor.set_store(self._memory_store)
        self._graph_page.set_store(self._memory_store)
        self._current_project = ProjectMeta(name=name)
        self._current_db_path = str(db_path)
        self._editor.set_blocks([])
        set_last_project(str(db_path))
        self.setWindowTitle(f"Context Pilot — {name}")
        self._status_bar.showMessage(f"Created '{name}'")
        self._refresh_dashboard()

    def _open_project(self) -> None:
        db_file, _ = QFileDialog.getOpenFileName(
            self, "Open Context Pilot Database", "", "SQLite DB (*.db);;All files (*)",
        )
        if not db_file:
            return
        db = Database(Path(db_file))
        store = ProjectStore(db)
        projects = store.list_projects()
        if not projects:
            QMessageBox.information(self, "Open", "No projects in this database.")
            db.close()
            return
        names = [p.name for p in projects]
        name, ok = QInputDialog.getItem(self, "Open Project", "Select:", names, 0, False)
        if not ok:
            db.close()
            return
        db.close()
        self._open_db(Path(db_file), project_name=name)

    def _save_project(self) -> None:
        if not self._store or not self._current_project:
            QMessageBox.information(self, "Save", "No project open.")
            return
        blocks = self._editor.get_blocks()
        block_dicts = [{
            "content": b.content,
            "priority": b.priority.value if hasattr(b.priority, 'value') else str(b.priority),
            "compress_hint": b.compress_hint,
        } for b in blocks]
        ctx = ContextConfig(name="default", blocks=block_dicts)
        self._store.save(self._current_project, [ctx])
        self._status_bar.showMessage(f"Saved '{self._current_project.name}'")

    def closeEvent(self, event) -> None:
        self._dashboard_timer.stop()
        if hasattr(self, "_skill_monitor"):
            self._skill_monitor.stop_timer()
        if hasattr(self, "_servers_page"):
            self._servers_page.stop_all()
        if self._db is not None:
            self._db.close()
        super().closeEvent(event)

    def _show_about(self) -> None:
        QMessageBox.about(self, "About Context Pilot",
            "Context Pilot v2.0\n\n"
            "Context manager with MCP skill integration.\n"
            "Skills connect dynamically — no hardcoded plugins.\n\n"
            "Blocks + Memories → MCP Server → External Skills")
