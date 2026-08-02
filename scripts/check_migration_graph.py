"""Fail when the configured database is not at the current migration leaves."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import django

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    """Verify every migration graph leaf is applied to the configured database."""

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    if not os.environ.get("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL must be set for migration graph verification")
    django.setup()

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    unapplied = sorted(f"{migration.app_label}.{migration.name}" for migration, _backwards in plan)
    if unapplied:
        print(f"Unapplied migrations: {len(unapplied)}")
        print("\n".join(unapplied))
        return 1
    print("Migration graph verified: unapplied=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
