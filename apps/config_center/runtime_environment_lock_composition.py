"""Expose the activation fence to same-alias transactional consumers."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.db import DEFAULT_DB_ALIAS, connection

from apps.config_center.infrastructure.runtime_config_repositories import _lock_runtime_environment
from core.exceptions import BusinessLogicError


@contextmanager
def locked_runtime_environment(*, environment: str, using: str) -> Iterator[None]:
    """Hold the owner activation lock until outer commit; reject unprotected aliases."""
    if (
        type(environment) is not str
        or not environment
        or any(character.isspace() for character in environment)
        or using != DEFAULT_DB_ALIAS
        or connection.vendor != "postgresql"
        or not connection.in_atomic_block
        or connection.get_autocommit()
    ):
        raise BusinessLogicError("runtime environment fence requires its owning PostgreSQL UOW")
    _lock_runtime_environment(environment)
    yield
