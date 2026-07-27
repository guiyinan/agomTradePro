"""Compatibility entry point for the governed Prompt bootstrap command."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _setup_django() -> None:
    """Initialize Django only when the compatibility script is executed."""

    repository_root = Path(__file__).resolve().parents[1]
    repository_path = str(repository_root)
    if repository_path not in sys.path:
        sys.path.insert(0, repository_path)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    import django

    django.setup()


def main() -> None:
    """Delegate force initialization to the sole management-command implementation."""

    _setup_django()
    from django.core.management import call_command

    call_command("init_prompt_templates", force=True)


if __name__ == "__main__":
    main()
