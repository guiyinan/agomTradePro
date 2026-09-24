"""Serialize ingestion against concurrent publication and absent-key writers."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import connection, models
from django.db.transaction import TransactionManagementError


@contextmanager
def publication_fact_write_lock(model: type[models.Model]) -> Iterator[None]:
    """Bound PostgreSQL ingestion locks inside the caller's atomic transaction.

    Failures propagate to that transaction, which restores transaction-local
    settings on rollback. Successful callers retain their original timeout.
    """
    if not connection.in_atomic_block:
        raise TransactionManagementError(
            "Publication-safe ingestion requires an atomic transaction"
        )
    previous_timeout: int | None = None
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute("SELECT setting::bigint FROM pg_settings WHERE name = 'lock_timeout'")
            previous_timeout = int(cursor.fetchone()[0])
            timeout = min(previous_timeout, 5000) if previous_timeout > 0 else 5000
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [str(timeout)])
            table = connection.ops.quote_name(model._meta.db_table)
            cursor.execute(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE")
    yield
    if previous_timeout is not None:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('lock_timeout', %s, true)", [str(previous_timeout)])
