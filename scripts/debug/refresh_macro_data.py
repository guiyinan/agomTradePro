#!/usr/bin/env python
"""Compatibility wrapper for the canonical macro synchronization command."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

LEGACY_DATA_CENTER_WRAPPER = "sync_macro_data"


def main(argv: Sequence[str] | None = None) -> None:
    """Delegate the historical five-year refresh to ``sync_macro_data``."""

    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

    from django.core.management import execute_from_command_line

    arguments = list(sys.argv[1:] if argv is None else argv)
    execute_from_command_line(
        [
            str(project_root / "manage.py"),
            LEGACY_DATA_CENTER_WRAPPER,
            "--source",
            "akshare",
            "--years",
            "5",
            *arguments,
        ]
    )


if __name__ == "__main__":
    main()
