"""One-off: verify the takeover package extracts and tests cleanly."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"


def _latest_archive() -> Path:
    """Pick the newest snapshot so the script survives a rename or date bump."""
    candidates = sorted(DIST.glob("*.zip"), key=lambda item: item.stat().st_mtime)
    if not candidates:
        raise SystemExit(f"no snapshot archive in {DIST}; run build_snapshot.py first")
    return candidates[-1]


def main() -> None:
    """Extract, assert required files, then run the suite from the clean copy."""
    archive_path = _latest_archive()
    target = Path(tempfile.mkdtemp(prefix="takeover-check-"))
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        top_name = archive.namelist()[0].split("/", maxsplit=1)[0]
        archive.extractall(target)
    top = target / top_name

    for required in (
        "bootstrap.py",
        "AGENTS.md",
        "README.md",
        "交接说明-进度与续接.md",
        "00-个人日历项目-新机接手入口.md",
        "src/panorama_calendar/data/cn_holidays/2026.json",
        "src/panorama_calendar/pipelines/holidays.py",
        "src/panorama_calendar/services/guardrails.py",
    ):
        assert (top / required).is_file(), f"missing {required}"
    assert not (top / ".venv").exists(), "virtualenv leaked into archive"

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "tests", "-q"],
        cwd=top,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    print(result.stdout.strip().splitlines()[-1] if result.stdout else "")
    print(f"archive={archive_path.name}")
    print(f"returncode={result.returncode}")
    print(f"extracted={top}")
    if result.returncode != 0:
        print(result.stdout[-2000:])
        raise SystemExit(1)


if __name__ == "__main__":
    main()
