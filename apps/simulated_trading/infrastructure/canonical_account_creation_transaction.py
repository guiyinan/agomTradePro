"""PostgreSQL user-row serialization for the complete creation/replay transaction."""

from collections.abc import Iterator
from contextlib import contextmanager

from django.contrib.auth.models import User
from django.db import DatabaseError, connections, transaction
from django.utils.connection import ConnectionDoesNotExist

from apps.simulated_trading.application.canonical_account_creation_row import (
    CanonicalAccountCreationRowInvalid,
    CanonicalAccountCreationRowUnavailable,
)


@contextmanager
def canonical_account_creation_transaction(*, using: str, user_id: int) -> Iterator[None]:
    """Serialize one user's creation and replay work until the outer commit.

    READ COMMITTED makes a waiting request observe the previous request's
    committed winner. The same user lock also protects name checks across
    different request keys. An enclosing transaction retains the lock beyond
    this context, following normal PostgreSQL transaction semantics.
    """

    if type(using) is not str or not using or any(character.isspace() for character in using):
        raise CanonicalAccountCreationRowInvalid("using must be an explicit database alias")
    if type(user_id) is not int or user_id <= 0:
        raise CanonicalAccountCreationRowInvalid("user_id must be an exact positive integer")
    try:
        connection = connections[using]
    except (ConnectionDoesNotExist, KeyError) as error:
        raise CanonicalAccountCreationRowUnavailable("creation database is unavailable") from error
    if connection.vendor != "postgresql":
        raise CanonicalAccountCreationRowUnavailable("creation serialization requires PostgreSQL")
    try:
        with transaction.atomic(using=using):
            with connection.cursor() as cursor:
                cursor.execute("SHOW transaction_isolation")
                isolation = cursor.fetchone()
            if isolation != ("read committed",):
                raise CanonicalAccountCreationRowUnavailable(
                    "creation serialization requires READ COMMITTED"
                )
            user = User.objects.using(using).select_for_update().filter(pk=user_id).first()
            if user is None or user.pk != user_id or user.is_active is not True:
                raise CanonicalAccountCreationRowUnavailable("creation user is unavailable")
            yield
    except DatabaseError as error:
        raise CanonicalAccountCreationRowUnavailable("creation transaction failed") from error


__all__ = ["canonical_account_creation_transaction"]
