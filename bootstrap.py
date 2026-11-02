#!/usr/bin/env python3
"""One-command recovery for the personal panorama calendar project.

Creates a virtual environment, installs the project with dev extras, then
verifies the toolchain end to end (tests, lint, and a demo ICS). Designed to be
the only command a fresh machine needs to run.

Usage:
    python bootstrap.py            # full setup + verification
    python bootstrap.py --verify   # skip install, only verify an existing venv
    python bootstrap.py --offline  # skip install and skip anything needing network

Exit codes:
    0  environment is ready and every check passed
    1  a check failed (details printed above)
    2  unsupported Python version or no usable interpreter
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
VENV_DIR = PROJECT_ROOT / ".venv"
MIN_PYTHON = (3, 12)
DEV_EXTRA = f"{PROJECT_ROOT}[dev]"


def _configure_console() -> None:
    """Force UTF-8 output so Chinese log lines survive legacy Windows consoles."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def _venv_python() -> Path:
    """Return the interpreter path inside the project virtual environment."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _run(label: str, command: list[str], *, check: bool = True) -> bool:
    """Run one subprocess step and report whether it succeeded."""
    printable = " ".join(str(part) for part in command)
    print(f"\n== {label} ==")
    print(f"$ {printable}")
    result = subprocess.run(command, cwd=PROJECT_ROOT, check=False)  # noqa: S603
    if result.returncode != 0:
        print(f"[FAIL] {label} exited with {result.returncode}")
        if check:
            return False
    else:
        print(f"[OK] {label}")
    return result.returncode == 0


def _ensure_venv() -> bool:
    """Create the virtual environment when it is missing."""
    interpreter = _venv_python()
    if interpreter.exists():
        print(f"[OK] virtual environment already present: {VENV_DIR}")
        return True
    print(f"== creating virtual environment ==\n$ {sys.executable} -m venv {VENV_DIR}")
    venv.EnvBuilder(with_pip=True, clear=False, upgrade_deps=False).create(VENV_DIR)
    if not interpreter.exists():
        print("[FAIL] virtual environment was created but no interpreter was found")
        return False
    print(f"[OK] virtual environment created: {VENV_DIR}")
    return True


def main() -> int:
    """Drive the whole recovery flow and return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verify",
        action="store_true",
        help="skip dependency installation and only run the verification suite",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="imply --verify and skip the demo generation step",
    )
    args = parser.parse_args()
    _configure_console()

    if sys.version_info < MIN_PYTHON:
        found = sys.version.split()[0]
        print(f"[FAIL] Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, got {found}")
        return 2
    print(f"[OK] interpreter {sys.version.split()[0]}")

    skip_install = args.verify or args.offline
    if not skip_install:
        if not _ensure_venv():
            return 1
        interpreter = _venv_python()
        if not _run(
            "install project with dev extras",
            [
                str(interpreter),
                "-m",
                "pip",
                "install",
                "--timeout",
                "60",
                "-e",
                DEV_EXTRA,
            ],
        ):
            print("\n[hint] installation needs network access to PyPI.")
            print("[hint] re-run with --verify to reuse an already-installed environment.")
            return 1
    else:
        interpreter = _venv_python()
        if not interpreter.exists():
            print(f"[FAIL] no virtual environment at {VENV_DIR}; run without --verify first")
            return 2

    checks = [
        ("pytest", [str(interpreter), "-m", "pytest", "tests"]),
        ("ruff", [str(interpreter), "-m", "ruff", "check", "src", "tests"]),
    ]
    # The smoke artifact keeps a fixed date AND its own filename: a fixed date keeps
    # the check reproducible, and a separate filename keeps this run from overwriting
    # dist/valarm-ios-test.ics, which must stay dated near "today" for a real iPhone.
    if not args.offline:
        checks.append(
            (
                "demo ICS",
                [
                    str(interpreter),
                    "-m",
                    "panorama_calendar",
                    "demo",
                    "--workday",
                    "2026-12-15",
                    "--output",
                    str(PROJECT_ROOT / "dist" / "valarm-selfcheck.ics"),
                ],
            )
        )

    failures = [label for label, command in checks if not _run(label, command)]

    print("\n" + "=" * 60)
    if failures:
        print(f"RESULT: NOT READY — failed checks: {', '.join(failures)}")
        return 1
    print("RESULT: READY")
    print("Next steps for the incoming engineer or agent:")
    print("  1. Read AGENTS.md (agent playbook) and 交接说明-进度与续接.md (status).")
    print("  2. Continue from the first unfinished item in 交接说明 section 7.")
    print("  3. Keep the hard constraints in AGENTS.md — do not regress them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
