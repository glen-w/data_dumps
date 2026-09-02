"""Notebook smoke tests."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK = ROOT / "notebooks" / "spotify.py"


def test_marimo_check():
    result = subprocess.run(
        [sys.executable, "-m", "marimo", "check", str(NOTEBOOK)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_notebook_module_importable():
    import importlib.util

    spec = importlib.util.spec_from_file_location("spotify_nb", NOTEBOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "app")
