#!/usr/bin/env python3
"""Build installer for Context Pilot.

Builds portable single-file executables for the current platform using PyInstaller.

Usage:
    python scripts/build_installer.py              # Build CLI only
    python scripts/build_installer.py --gui        # Build GUI only
    python scripts/build_installer.py --all        # Build CLI + GUI
    python scripts/build_installer.py --clean      # Clean build artifacts first
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"

CLI_SPEC = ROOT / "context_pilot_cli.spec"
GUI_SPEC = ROOT / "context_pilot_gui.spec"


def check_prerequisites() -> None:
    errors: list[str] = []
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        errors.append("PyInstaller not installed — run: pip install pyinstaller")

    if platform.system() == "Linux":
        if shutil.which("objdump") is None:
            errors.append("objdump not found — install binutils: sudo apt-get install binutils")

    if errors:
        print("Missing prerequisites:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)


def run(cmd: list[str]) -> None:
    print(f"  → {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"ERROR: command failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def clean() -> None:
    print("Cleaning build artifacts...")
    for d in [BUILD, DIST / "context-pilot", DIST / "context-pilot-gui"]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  removed {d}")


def build_cli() -> None:
    print(f"\nBuilding CLI binary (platform: {platform.system()} {platform.machine()})...")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(CLI_SPEC)])
    binary = DIST / "context-pilot"
    if binary.exists():
        size_mb = binary.stat().st_size / (1024 * 1024)
        print(f"  CLI binary: {binary} ({size_mb:.1f} MB)")
    else:
        print("  WARNING: expected binary not found at", binary)


def build_gui() -> None:
    print(f"\nBuilding GUI binary (platform: {platform.system()} {platform.machine()})...")
    run([sys.executable, "-m", "PyInstaller", "--noconfirm", str(GUI_SPEC)])
    binary = DIST / "context-pilot-gui"
    if binary.exists():
        size_mb = binary.stat().st_size / (1024 * 1024)
        print(f"  GUI binary: {binary} ({size_mb:.1f} MB)")
    else:
        print("  WARNING: expected binary not found at", binary)


def smoke_test_cli() -> None:
    binary = DIST / "context-pilot"
    if not binary.exists():
        print("  Skipping smoke test — binary not found")
        return
    print("\nSmoke testing CLI...")
    result = subprocess.run([str(binary), "--help"], capture_output=True, text=True, timeout=30)
    if result.returncode == 0 and "Context Pilot" in result.stdout:
        print("  CLI smoke test PASSED")
    else:
        print(f"  CLI smoke test FAILED (rc={result.returncode})")
        if result.stderr:
            print(f"  stderr: {result.stderr[:500]}")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Context Pilot installers")
    parser.add_argument("--cli", action="store_true", default=True, help="Build CLI (default)")
    parser.add_argument("--gui", action="store_true", help="Build GUI")
    parser.add_argument("--all", action="store_true", help="Build CLI + GUI")
    parser.add_argument("--clean", action="store_true", help="Clean build artifacts first")
    parser.add_argument("--no-smoke", action="store_true", help="Skip smoke tests")
    args = parser.parse_args()

    check_prerequisites()

    if args.clean:
        clean()

    if args.all:
        build_cli()
        build_gui()
    elif args.gui:
        build_gui()
    else:
        build_cli()

    if not args.no_smoke:
        smoke_test_cli()

    print("\nDone.")


if __name__ == "__main__":
    main()
