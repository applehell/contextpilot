# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Context Pilot GUI."""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "src" / "gui" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        "PySide6",
        "PySide6.QtWidgets",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "src",
        "src.core",
        "src.core.assembler",
        "src.core.block",
        "src.core.token_budget",
        "src.core.context",
        "src.core.weight_adjuster",
        "src.core.skill_connector",
        "src.core.compressors",
        "src.core.compressors.base",
        "src.core.compressors.bullet_extract",
        "src.core.compressors.code_compact",
        "src.core.compressors.dedup_cross",
        "src.core.compressors.mermaid",
        "src.core.compressors.table",
        "src.core.compressors.yaml_struct",
        "src.storage",
        "src.storage.db",
        "src.storage.memory",
        "src.storage.project",
        "src.storage.usage",
        "src.gui",
        "src.gui.main_window",
        "src.gui.block_editor",
        "src.gui.memory_editor",
        "src.gui.widgets",
        "src.gui.widgets.block_card",
        "src.gui.widgets.budget_bar",
        "src.gui.widgets.simulation_panel",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="context-pilot-gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=False,
)
