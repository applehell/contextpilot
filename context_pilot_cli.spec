# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Context Pilot CLI."""

import sys
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)

a = Analysis(
    [str(ROOT / "src" / "interfaces" / "cli.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        "click",
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
        "src.interfaces",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "src.gui"],
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
    name="context-pilot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    console=True,
)
