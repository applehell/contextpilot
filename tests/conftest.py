"""Shared fixtures for the test suite."""
from __future__ import annotations

import os

# Keep the background scheduler out of TestClient startup events.
os.environ.setdefault("CONTEXTPILOT_DISABLE_AUTOSTART", "1")
