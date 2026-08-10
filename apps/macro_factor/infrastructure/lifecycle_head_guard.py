"""Repository-capability guard for the mutable R3 lifecycle head row."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, NoReturn, TypeVar, cast

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

_ModelT = TypeVar("_ModelT", bound=models.Model)
_HeadOperation = Literal["insert", "replace"]
_ACTIVE_HEAD_UOW: ContextVar[object | None] = ContextVar(
    "active_macro_factor_lifecycle_head_uow",
    default=None,
)


@dataclass(frozen=True)
class _LifecycleHeadClaim:
    token: object
    model_type: type[models.Model]
    operation: _HeadOperation
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_HEAD_CLAIM: ContextVar[_LifecycleHeadClaim | None] = ContextVar(
    "active_macro_factor_lifecycle_head_claim",
    default=None,
)


@contextmanager
def _activate_lifecycle_head_uow(token: object) -> Iterator[None]:
    reset = _ACTIVE_HEAD_UOW.set(token)
    try:
        yield
    finally:
        _ACTIVE_HEAD_UOW.reset(reset)


@contextmanager
def _claim_lifecycle_head_write(
    *,
    token: object,
    model_type: type[models.Model],
    operation: _HeadOperation,
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize one exact insert or replacement inside the repository UoW."""

    if _ACTIVE_HEAD_UOW.get() is not token:
        raise ValidationError("lifecycle head write requires its repository unit of work")
    claim = _LifecycleHeadClaim(
        token=token,
        model_type=model_type,
        operation=operation,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset = _ACTIVE_HEAD_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_HEAD_CLAIM.reset(reset)


def _require_lifecycle_head_claim(
    model: models.Model,
    operation: _HeadOperation,
) -> None:
    claim = _ACTIVE_HEAD_CLAIM.get()
    if (
        claim is None
        or claim.token is not _ACTIVE_HEAD_UOW.get()
        or claim.model_type is not type(model)
        or claim.operation != operation
        or any(
            getattr(model, field_name) != expected for field_name, expected in claim.expected_values
        )
    ):
        raise ValidationError("lifecycle head requires an exact repository write claim")


class LifecycleHeadQuerySet(models.QuerySet[_ModelT]):
    """Reject every public mutation path while permitting one claimed model save."""

    def update(self, **kwargs: object) -> NoReturn:
        raise ValidationError("lifecycle head cannot be publicly updated")

    def bulk_update(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        raise ValidationError("lifecycle head cannot be bulk updated")

    def delete(self) -> NoReturn:
        raise ValidationError("lifecycle head cannot be deleted")

    def get_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("lifecycle head get_or_create is forbidden")

    def update_or_create(
        self,
        defaults: Mapping[str, object] | None = None,
        create_defaults: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> NoReturn:
        raise ValidationError("lifecycle head update_or_create is forbidden")

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("lifecycle head bulk create is forbidden")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("lifecycle head cannot be deleted")

    def _update(self, values: object) -> int:
        claim = _ACTIVE_HEAD_CLAIM.get()
        if (
            claim is None
            or claim.token is not _ACTIVE_HEAD_UOW.get()
            or claim.model_type is not self.model
            or claim.operation != "replace"
        ):
            raise ValidationError("lifecycle head private update is forbidden")
        update = cast(Callable[[object], int], getattr(super(), "_update"))  # noqa: B009
        return update(values)

    def _insert(
        self,
        objs: Iterable[_ModelT],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("lifecycle head private insert is forbidden")
        _require_lifecycle_head_claim(items[0], "insert")
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009
        )
        return insert(
            items,
            fields,
            returning_fields=returning_fields,
            raw=False,
            using=using,
            on_conflict=None,
            update_fields=None,
            unique_fields=None,
        )

    def _batched_insert(
        self,
        objs: list[_ModelT],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        raise ValidationError("lifecycle head private bulk insert is forbidden")


class LifecycleHeadManager(models.Manager[_ModelT]):
    """Expose the same guarded QuerySet via default and base managers."""

    def get_queryset(self) -> LifecycleHeadQuerySet[_ModelT]:
        return LifecycleHeadQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        raise ValidationError("lifecycle head bulk create is forbidden")


class LifecycleHeadGuardedModel(models.Model):
    """Allow only an exact repository-claimed insert or replacement."""

    objects = LifecycleHeadManager()

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
        operation: _HeadOperation = "insert" if self._state.adding else "replace"
        _require_lifecycle_head_claim(self, operation)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if raw:
            raise ValidationError("lifecycle head raw save is forbidden")
        operation: _HeadOperation = "insert" if self._state.adding else "replace"
        _require_lifecycle_head_claim(self, operation)
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, *args: object, **kwargs: object) -> NoReturn:
        raise ValidationError("lifecycle head cannot be deleted")


__all__ = [
    "LifecycleHeadGuardedModel",
    "_activate_lifecycle_head_uow",
    "_claim_lifecycle_head_write",
]
