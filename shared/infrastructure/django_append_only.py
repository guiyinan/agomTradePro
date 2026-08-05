"""Reusable Django guards for append-only evidence models."""

from __future__ import annotations

from collections.abc import Iterable
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models

_ModelT = TypeVar("_ModelT", bound=models.Model)


class AppendOnlyQuerySet(models.QuerySet[_ModelT]):
    """Reject every QuerySet operation that mutates or deletes existing rows."""

    def update(self, **kwargs: object) -> NoReturn:
        """Reject bulk field mutation of append-only rows."""

        raise ValidationError("Append-only evidence cannot be updated.")

    def bulk_update(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject Django's bulk-update path for append-only rows."""

        raise ValidationError("Append-only evidence cannot be bulk updated.")

    def delete(self) -> NoReturn:
        """Reject QuerySet deletion of append-only rows."""

        raise ValidationError("Append-only evidence cannot be deleted.")


class AppendOnlyManager(models.Manager[_ModelT]):
    """Manager exposing guarded QuerySets while preserving insert operations."""

    def get_queryset(self) -> AppendOnlyQuerySet[_ModelT]:
        """Return the guarded QuerySet for this model and database alias."""

        return AppendOnlyQuerySet(self.model, using=self._db)

    def bulk_update(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk mutation explicitly."""

        raise ValidationError("Append-only evidence cannot be bulk updated.")


__all__ = ["AppendOnlyManager", "AppendOnlyQuerySet"]
