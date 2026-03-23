"""Servers page — start/stop MCP and CLI servers, see connections."""
from __future__ import annotations

import subprocess
import sys
import time
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTextEdit,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import QProcess, Qt, QTimer, Signal

from src.core.claude_config import register_mcp, deregister_mcp, remove_stdio_entry
from src.core.mcp_client import load_mcp_servers
from src.core.skill_registry import SkillRegistry


class _ServerCard(QFrame):
    """Card for a single server with start/stop controls."""

    started = Signal(str)
    stopped = Signal(str)

    def __init__(self, name: str, description: str, parent=None) -> None:
        super().__init__(parent)
        self._name = name
        self._process: Optional[QProcess] = None
        self.setStyleSheet(
            "QFrame { background: #313244; border: 1px solid #45475a; border-radius: 10px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"<b>{name}</b>")
        title.setStyleSheet("color: #cdd6f4; font-size: 14px; border: none;")
        header.addWidget(title)

        self._status = QLabel("stopped")
        self._status.setStyleSheet(
            "color: #f38ba8; font-size: 11px; font-weight: bold; border: none;"
        )
        header.addWidget(self._status)
        header.addStretch()

        self._start_btn = QPushButton("Start")
        self._start_btn.setFixedWidth(60)
        self._start_btn.clicked.connect(self._start)
        header.addWidget(self._start_btn)

        self._stop_btn = QPushButton("Stop")
        self._stop_btn.setFixedWidth(60)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._stop)
        header.addWidget(self._stop_btn)

        layout.addLayout(header)

        desc = QLabel(description)
        desc.setStyleSheet("color: #6c7086; font-size: 11px; border: none;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumHeight(100)
        self._log.setStyleSheet(
            "background: #11111b; color: #a6adc8; border: 1px solid #313244; "
            "border-radius: 4px; font-family: monospace; font-size: 11px;"
        )
        self._log.setPlaceholderText("Server log output...")
        layout.addWidget(self._log)

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.state() == QProcess.Running

    def _set_running(self, running: bool) -> None:
        self._start_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)
        if running:
            self._status.setText("running")
            self._status.setStyleSheet(
                "color: #a6e3a1; font-size: 11px; font-weight: bold; border: none;"
            )
        else:
            self._status.setText("stopped")
            self._status.setStyleSheet(
                "color: #f38ba8; font-size: 11px; font-weight: bold; border: none;"
            )

    def _start(self) -> None:
        """Override in subclass."""
        pass

    def _stop(self) -> None:
        if self._process and self._process.state() == QProcess.Running:
            self._process.terminate()
            self._process.waitForFinished(3000)
            if self._process.state() == QProcess.Running:
                self._process.kill()
        self._process = None
        self._set_running(False)
        self._log.append("[stopped]")
        self.stopped.emit(self._name)

    def _start_process(self, program: str, args: List[str]) -> None:
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.start(program, args)
        self._set_running(True)
        self._log.clear()
        self._log.append(f"[started] {program} {' '.join(args)}")
        self.started.emit(self._name)

    def _on_output(self) -> None:
        if self._process:
            data = self._process.readAllStandardOutput().data().decode(errors="replace")
            self._log.append(data.rstrip())

    def _on_finished(self, exit_code: int, status) -> None:
        self._set_running(False)
        self._log.append(f"[exited: {exit_code}]")
        self.stopped.emit(self._name)


class MCPServerCard(_ServerCard):
    """Card for the Context Pilot MCP server."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "MCP Server",
            "Exposes Context Pilot assembler, blocks, and memories as MCP tools. "
            "Claude Code and other MCP clients can connect to use this data.",
            parent,
        )
        # Port config
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port:"))
        self._port = QSpinBox()
        self._port.setRange(1024, 65535)
        self._port.setValue(8400)
        port_row.addWidget(self._port)
        port_row.addStretch()
        self.layout().insertLayout(2, port_row)

    def _start(self) -> None:
        port = self._port.value()
        python = sys.executable
        self._start_process(python, [
            "-m", "src.interfaces.mcp_server",
            "--transport", "sse",
            "--port", str(port),
        ])
        register_mcp(port=port, transport="sse")
        self._log.append(f"[registered] SSE server on port {port} in ~/.claude.json")


    def _stop(self) -> None:
        deregister_mcp()
        self._log.append("[deregistered] Removed from ~/.claude.json")
        super()._stop()


class CLIServerCard(_ServerCard):
    """Card for the Context Pilot web/API server."""

    def __init__(self, parent=None) -> None:
        super().__init__(
            "Web API Server",
            "REST API for external tools, scripts, and CI/CD pipelines to interact "
            "with Context Pilot blocks, memories, and assembly.",
            parent,
        )
        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Host:"))
        self._host = QLineEdit("0.0.0.0")
        self._host.setFixedWidth(100)
        port_row.addWidget(self._host)
        port_row.addWidget(QLabel("Port:"))
        self._port = QSpinBox()
        self._port.setRange(1024, 65535)
        self._port.setValue(8401)
        port_row.addWidget(self._port)
        port_row.addStretch()
        self.layout().insertLayout(2, port_row)

    def _start(self) -> None:
        python = sys.executable
        self._start_process(python, [
            "-m", "src.web",
            "--host", self._host.text(),
            "--port", str(self._port.value()),
        ])


class _MCPConnectionCard(QFrame):
    """Shows a detected external MCP server from ~/.claude.json."""

    def __init__(self, name: str, config: Dict, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: #1e1e2e; border: 1px solid #313244; border-radius: 8px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)

        dot = QLabel("\u25CF")
        dot.setStyleSheet("color: #a6e3a1; font-size: 14px; border: none;")
        dot.setFixedWidth(20)
        layout.addWidget(dot)

        info = QVBoxLayout()
        info.setSpacing(2)
        title = QLabel(f"<b>{name}</b>")
        title.setStyleSheet("color: #cdd6f4; font-size: 12px; border: none;")
        info.addWidget(title)

        server_type = config.get("type", "unknown")
        url = config.get("url", config.get("command", ""))
        detail = QLabel(f"{server_type}: {url}")
        detail.setStyleSheet("color: #6c7086; font-size: 10px; border: none;")
        info.addWidget(detail)
        layout.addLayout(info, stretch=1)


class _ConnectedSkillCard(QFrame):
    """Card showing a connected external skill."""

    def __init__(self, skill, parent=None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "QFrame { background: #1e1e2e; border: 1px solid #313244; border-radius: 8px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)

        # Status dot
        is_alive = skill.is_alive
        color = "#a6e3a1" if is_alive else "#f38ba8"
        dot = QLabel("\u25CF")
        dot.setStyleSheet(f"color: {color}; font-size: 16px; border: none;")
        dot.setFixedWidth(20)
        layout.addWidget(dot)

        # Info
        info = QVBoxLayout()
        info.setSpacing(2)

        name_label = QLabel(f"<b>{skill.name}</b>")
        name_label.setStyleSheet("color: #cdd6f4; font-size: 13px; border: none;")
        info.addWidget(name_label)

        desc = QLabel(skill.description)
        desc.setStyleSheet("color: #a6adc8; font-size: 11px; border: none;")
        desc.setWordWrap(True)
        info.addWidget(desc)

        if skill.context_hints:
            hints = ", ".join(skill.context_hints[:6])
            hints_label = QLabel(f"hints: {hints}")
            hints_label.setStyleSheet("color: #6c7086; font-size: 10px; border: none;")
            info.addWidget(hints_label)

        layout.addLayout(info, stretch=1)

        # Stats
        stats = QVBoxLayout()
        stats.setSpacing(2)

        status_text = "connected" if is_alive else "stale"
        status_label = QLabel(status_text)
        status_label.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: bold; border: none;"
        )
        status_label.setAlignment(Qt.AlignRight)
        stats.addWidget(status_label)

        blocks_label = QLabel(f"{skill.blocks_served} blocks served")
        blocks_label.setStyleSheet("color: #6c7086; font-size: 10px; border: none;")
        blocks_label.setAlignment(Qt.AlignRight)
        stats.addWidget(blocks_label)

        ago = int(time.time() - skill.last_seen)
        if ago < 60:
            seen_text = f"{ago}s ago"
        elif ago < 3600:
            seen_text = f"{ago // 60}m ago"
        else:
            seen_text = f"{ago // 3600}h ago"
        seen_label = QLabel(f"seen {seen_text}")
        seen_label.setStyleSheet("color: #6c7086; font-size: 10px; border: none;")
        seen_label.setAlignment(Qt.AlignRight)
        stats.addWidget(seen_label)

        layout.addLayout(stats)


class ServersPage(QWidget):
    """Server management page."""

    server_state_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header = QLabel("Servers & Connections")
        header.setStyleSheet("font-size: 20px; font-weight: bold; color: #cdd6f4;")
        layout.addWidget(header)

        # Context Pilot servers
        section1 = QLabel("Context Pilot Servers")
        section1.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6adc8;")
        layout.addWidget(section1)

        self._mcp_card = MCPServerCard()
        self._mcp_card.started.connect(lambda: self.server_state_changed.emit())
        self._mcp_card.stopped.connect(lambda: self.server_state_changed.emit())
        layout.addWidget(self._mcp_card)

        self._cli_card = CLIServerCard()
        self._cli_card.started.connect(lambda: self.server_state_changed.emit())
        self._cli_card.stopped.connect(lambda: self.server_state_changed.emit())
        layout.addWidget(self._cli_card)

        # External MCP connections
        ext_row = QHBoxLayout()
        section2 = QLabel("External MCP Servers (from ~/.claude.json)")
        section2.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6adc8;")
        ext_row.addWidget(section2)
        ext_row.addStretch()
        refresh_ext = QPushButton("\u21BB Refresh")
        refresh_ext.setMinimumHeight(28)
        refresh_ext.clicked.connect(self._refresh_external)
        ext_row.addWidget(refresh_ext)
        layout.addLayout(ext_row)

        self._ext_container = QVBoxLayout()
        layout.addLayout(self._ext_container)
        self._refresh_external()

        # Connected external skills (via MCP registration)
        conn_row = QHBoxLayout()
        section3 = QLabel("Connected Skills (via MCP Registration)")
        section3.setStyleSheet("font-size: 13px; font-weight: bold; color: #a6adc8;")
        conn_row.addWidget(section3)
        conn_row.addStretch()
        refresh_conn = QPushButton("\u21BB Refresh")
        refresh_conn.setMinimumHeight(28)
        refresh_conn.clicked.connect(self._refresh_connected)
        conn_row.addWidget(refresh_conn)
        layout.addLayout(conn_row)

        self._conn_container = QVBoxLayout()
        layout.addLayout(self._conn_container)

        self._no_conn_label = QLabel(
            "No external skills registered. Skills can register via:\n"
            "  MCP tool: register_skill(name, description, context_hints)"
        )
        self._no_conn_label.setStyleSheet("color: #6c7086; font-size: 11px;")
        self._no_conn_label.setWordWrap(True)
        self._conn_container.addWidget(self._no_conn_label)

        layout.addStretch()

        # Auto-refresh connected skills every 5 seconds
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_connected)
        self._refresh_timer.start(5000)

    def _refresh_external(self) -> None:
        # Clear
        while self._ext_container.count():
            item = self._ext_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        servers = load_mcp_servers()
        if not servers:
            lbl = QLabel("No external MCP servers found in ~/.claude.json")
            lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
            self._ext_container.addWidget(lbl)
            return

        for name, config in servers.items():
            card = _MCPConnectionCard(name, config)
            self._ext_container.addWidget(card)

    def _refresh_connected(self) -> None:
        """Refresh the connected skills list from the shared registry."""
        # Clear existing
        while self._conn_container.count():
            item = self._conn_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        registry = SkillRegistry.instance()
        skills = registry.list_all()

        if not skills:
            lbl = QLabel(
                "No external skills registered. Skills can register via:\n"
                "  MCP tool: register_skill(name, description, context_hints)"
            )
            lbl.setStyleSheet("color: #6c7086; font-size: 11px;")
            lbl.setWordWrap(True)
            self._conn_container.addWidget(lbl)
            return

        for skill in skills:
            card = _ConnectedSkillCard(skill)
            self._conn_container.addWidget(card)

    @property
    def mcp_running(self) -> bool:
        return self._mcp_card.is_running

    @property
    def cli_running(self) -> bool:
        return self._cli_card.is_running

    @property
    def connected_skill_count(self) -> int:
        return len(SkillRegistry.instance().list_alive())

    def stop_all(self) -> None:
        self._refresh_timer.stop()
        self._mcp_card._stop()
        self._cli_card._stop()
        deregister_mcp()
