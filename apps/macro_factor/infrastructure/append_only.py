"""Strong default/base-manager guards for macro-factor evidence."""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any, NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)


class MacroFactorAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject Django conflict-update inserts in addition to update/delete."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Permit inserts while refusing ``ON CONFLICT DO UPDATE``."""

        if update_conflicts:
            raise ValidationError("Macro-factor evidence cannot update on conflict.")
        return super().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=False,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class MacroFactorAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose guarded QuerySets on both default and base manager paths."""

    def get_queryset(self) -> MacroFactorAppendOnlyQuerySet[_ModelT]:
        """Return the macro-factor-specific append-only QuerySet."""

        return MacroFactorAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> list[_ModelT]:
        """Delegate inserts to the conflict-update guard."""

        return self.get_queryset().bulk_create(
            objs,
            batch_size=batch_size,
            ignore_conflicts=ignore_conflicts,
            update_conflicts=update_conflicts,
            update_fields=update_fields,
            unique_fields=unique_fields,
        )


class MacroFactorAppendOnlyModel(models.Model):
    """Reject instance, default/base manager, and related mutation paths."""

    objects = MacroFactorAppendOnlyManager()

    class Meta:
        abstract = True
        base_manager_name = "objects"
        default_manager_name = "objects"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow insertion exactly once."""

        if self.pk and type(self)._default_manager.filter(pk=self.pk).exists():
            raise ValidationError("Macro-factor evidence is append-only.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, *args: Any, **kwargs: Any) -> NoReturn:
        """Reject destructive deletion."""

        raise ValidationError("Macro-factor evidence cannot be deleted.")


__all__ = [
    "MacroFactorAppendOnlyManager",
    "MacroFactorAppendOnlyModel",
    "MacroFactorAppendOnlyQuerySet",
]
