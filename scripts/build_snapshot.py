"""One-off: build a clean project snapshot zip (excludes venv/caches)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STAMP = "2026-11-02"
TOP = f"个人日历项目-{STAMP}"
OUTPUT = ROOT / "dist" / f"个人日历项目-接手包-{STAMP}.zip"

EXCLUDE_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".hypothesis",
    ".mypy_cache",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db"}


def should_skip(path: Path) -> bool:
    """Skip caches, virtualenvs, compiled artefacts and prior snapshots."""
    if any(part in EXCLUDE_DIRS for part in path.parts):
        return True
    if path.resolve() == OUTPUT.resolve():
        return True
    if path.suffix == ".zip":
        return True
    return path.suffix in EXCLUDE_SUFFIXES or path.name in EXCLUDE_FILES


def main() -> None:
    """Collect every shipping file into one archive."""
    files = sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file() and not should_skip(path.relative_to(ROOT))
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, f"{TOP}/{path.relative_to(ROOT).as_posix()}")
    digest = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    print(f"archive={OUTPUT}")
    print(f"files={len(files)}")
    print(f"size={OUTPUT.stat().st_size}")
    print(f"sha256={digest}")
    for path in files:
        print(f"  {path.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
