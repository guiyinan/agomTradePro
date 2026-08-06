#!/usr/bin/env python
"""Compatibility wrapper for bounded canonical macro history synchronization."""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

LEGACY_DATA_CENTER_WRAPPER = "sync_macro_data"
_DEFAULT_HISTORICAL_INDICATORS = ("CN_PMI", "CN_CPI", "CN_PPI", "CN_M2")


def _translate_arguments(argv: Sequence[str]) -> list[str]:
    """Translate the legacy selector flags to the canonical command contract."""

    arguments = list(argv)
    if "--check" in arguments:
        raise SystemExit(
            "--check was retired; use `python manage.py test_data_connections` "
            "or the Data Center diagnostics surface."
        )

    select_all = False
    indicator: str | None = None
    forwarded: list[str] = []
    index = 0
    while index < len(arguments):
        item = arguments[index]
        if item == "--all":
            select_all = True
        elif item == "--indicator":
            if index + 1 >= len(arguments):
                raise SystemExit("--indicator requires one indicator code")
            indicator = arguments[index + 1]
            index += 1
        else:
            forwarded.append(item)
        index += 1

    if select_all and indicator:
        raise SystemExit("--all and --indicator cannot be used together")
    if select_all:
        forwarded.extend(["--indicators", *_DEFAULT_HISTORICAL_INDICATORS])
    elif indicator:
        forwarded.extend(["--indicators", indicator])
    elif "--list" not in forwarded:
        raise SystemExit("choose --all, --indicator CODE, or --list")
    return forwarded


def main(argv: Sequence[str] | None = None) -> None:
    """Delegate all data access to the canonical management command."""

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

    from django.core.management import execute_from_command_line

    arguments = _translate_arguments(sys.argv[1:] if argv is None else argv)
    execute_from_command_line(
        [str(project_root / "manage.py"), LEGACY_DATA_CENTER_WRAPPER, *arguments]
    )


if __name__ == "__main__":
    main()
