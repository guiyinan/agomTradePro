"""Compatibility entry point for the canonical ``init_equity_config`` command.

Prefer::

    python manage.py init_equity_config

Use ``--force`` only when matching database rows must be reset to bootstrap
defaults. This wrapper intentionally contains no duplicate business defaults.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    """Initialize Django and delegate to the canonical management command."""

    project_root = Path(__file__).resolve().parent.parent
    project_root_text = str(project_root)
    if project_root_text not in sys.path:
        sys.path.insert(0, project_root_text)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.base")

    import django
    from django.core.management import call_command

    django.setup()
    call_command("init_equity_config")


if __name__ == "__main__":
    main()
