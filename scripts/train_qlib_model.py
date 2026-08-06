#!/usr/bin/env python
"""Compatibility wrapper for the canonical governed Qlib training command.

The historical script trained through ``SystemSettingsModel`` directly.  It is
kept as a thin CLI alias so existing operators are redirected to the same
Config Center runtime gate, task contract, and artifact registry as Django
management users.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> None:
    """Delegate all arguments to ``manage.py train_qlib_model``."""

    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")

    from django.core.management import execute_from_command_line

    arguments = list(sys.argv[1:] if argv is None else argv)
    execute_from_command_line(
        [str(project_root / "manage.py"), "train_qlib_model", *arguments]
    )


if __name__ == "__main__":
    main()
