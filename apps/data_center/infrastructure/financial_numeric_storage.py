"""JSON object constraint used by the canonical numeric storage migration."""

from __future__ import annotations

from typing import Any

from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import BooleanField, Func
from django.db.models.sql.compiler import SQLCompiler


class IsFinancialNumericJSONObject(Func):
    """Require an actual JSON object on both SQLite and PostgreSQL."""

    function = "JSON_TYPE"
    template = "(%(function)s(%(expressions)s) = 'object')"
    output_field = BooleanField()

    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: Any,
    ) -> tuple[str, list[Any]]:
        """Use the PostgreSQL jsonb type inspection without accepting JSON null."""

        sql, parameters = self.as_sql(
            compiler, connection, function="jsonb_typeof", **extra_context
        )
        return sql, list(parameters)
