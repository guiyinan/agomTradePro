"""Compatibility wrapper for the governed scheduler bootstrap command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(arguments: list[str] | None = None) -> int:
    """Delegate database-backed schedule writes to the owning Django command."""

    root = Path(__file__).resolve().parents[1]
    command = [
        sys.executable,
        str(root / "manage.py"),
        "init_scheduler_defaults",
        *(arguments if arguments is not None else sys.argv[1:]),
    ]
    return int(subprocess.run(command, cwd=root, check=False).returncode)


if __name__ == "__main__":
    raise SystemExit(main())
