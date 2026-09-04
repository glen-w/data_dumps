"""Notebook smoke tests."""

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NOTEBOOKS = [
    ROOT / "notebooks" / "spotify.py",
    ROOT / "notebooks" / "telegram.py",
]


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda p: p.stem)
def test_marimo_check(notebook: Path):
    result = subprocess.run(
        [sys.executable, "-m", "marimo", "check", str(notebook)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("notebook", NOTEBOOKS, ids=lambda p: p.stem)
def test_notebook_module_importable(notebook: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"{notebook.stem}_nb", notebook)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert hasattr(module, "app")
