"""Shared fixtures and marks for the test suite."""
from __future__ import annotations

import os
import sys
import pytest

# ---------------------------------------------------------------------------
# Qt / PySide6 availability detection
# ---------------------------------------------------------------------------
# Set offscreen platform *before* any Qt import so widget tests run headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_QT_AVAILABLE = False
_QT_SKIP_REASON = ""

try:
    from PySide6.QtWidgets import QApplication  # noqa: F401
    _QT_AVAILABLE = True
except ImportError as exc:
    _QT_SKIP_REASON = f"PySide6 not importable: {exc}"
except Exception as exc:
    _QT_SKIP_REASON = f"Qt init failed: {exc}"

requires_qt = pytest.mark.skipif(not _QT_AVAILABLE, reason=_QT_SKIP_REASON)


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication — created once, reused across all GUI tests."""
    if not _QT_AVAILABLE:
        pytest.skip(_QT_SKIP_REASON)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
