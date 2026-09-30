#!/usr/bin/env python3
"""Run Django schema migrations through the isolated deployment role."""

from __future__ import annotations

import os
import sys
from typing import cast

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.production")

import django

django.setup()

from django.core.management import execute_from_command_line
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created

_OWNER_ROLE = "agomtradepro_owner"
_MIGRATOR_ROLE = "agomtradepro_migrator"
_ALLOWED_COMMANDS = frozenset({"migrate", "flush", "loaddata"})


def _set_owner_role(
    sender: type[BaseDatabaseWrapper],
    connection: BaseDatabaseWrapper,
    **kwargs: object,
) -> None:
    """Set the owner role on each migrator database connection."""

    del sender, kwargs
    if connection.alias != "default":
        return
    if connection.vendor != "postgresql":
        raise RuntimeError("the deployment migrator requires PostgreSQL")
    with connection.cursor() as cursor:
        cursor.execute("SET ROLE agomtradepro_owner")
        cursor.execute("SELECT session_user, current_user")
        session_user, current_user = cast(tuple[str, str], cursor.fetchone())
    if session_user != _MIGRATOR_ROLE or current_user != _OWNER_ROLE:
        raise RuntimeError("migrator database role identity did not match the deployment contract")


def main(argv: list[str] | None = None) -> int:
    """Run an allow-listed deployment migration or snapshot restore command."""

    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in _ALLOWED_COMMANDS:
        allowed = ", ".join(sorted(_ALLOWED_COMMANDS))
        raise SystemExit(f"only these deployment database commands are allowed: {allowed}")

    connection_created.connect(_set_owner_role, weak=False)
    connections["default"].ensure_connection()
    execute_from_command_line(["manage.py", *arguments])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
