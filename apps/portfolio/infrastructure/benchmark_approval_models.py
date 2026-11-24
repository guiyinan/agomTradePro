"""Append-only signed transitions for independently authorized benchmark snapshots."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn, Self, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_T = TypeVar("_T", bound=models.Model)
_claim: ContextVar[models.Model | None] = ContextVar("portfolio_benchmark_approval", default=None)


@contextmanager
def _claim_approval_event(row: models.Model) -> Iterator[None]:
    token = _claim.set(row)
    try:
        yield
    finally:
        _claim.reset(token)


class _ApprovalRows(AppendOnlyQuerySet[_T]):
    def bulk_create(
        self,
        objs: Iterable[_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject bulk insertions, including attempts with conflict handlers."""
        raise ValidationError("benchmark approval requires an authenticated decision")

    def _raw_delete(self, using: str | None) -> NoReturn:
        raise ValidationError("benchmark approvals are immutable")


class _ApprovalManager(AppendOnlyManager[_T]):
    def get_queryset(self) -> _ApprovalRows[_T]:
        """Always return the ledger's guarded query type."""
        return _ApprovalRows(self.model, using=self._db)


class BenchmarkApprovalEventModel(models.Model):
    """One signed submission, approval or withdrawal in a canonical account's chain."""

    objects: _ApprovalManager[Self] = _ApprovalManager()
    scope_key = models.CharField(max_length=64)
    sequence = models.PositiveBigIntegerField()
    request_id = models.UUIDField(db_index=True)
    action = models.CharField(max_length=16)
    account_namespace = models.CharField(max_length=192)
    account_id = models.CharField(max_length=192)
    owner_user_id = models.PositiveBigIntegerField()
    tenant_id = models.CharField(max_length=192)
    owner_id = models.CharField(max_length=192)
    valuation_id = models.UUIDField()
    valuation_version = models.PositiveBigIntegerField()
    source_seal = models.CharField(max_length=64)
    source_manifest = models.TextField()
    actor_user_id = models.PositiveBigIntegerField()
    actor_role = models.CharField(max_length=32)
    recorded_at = models.DateTimeField()
    valid_until = models.DateTimeField()
    previous_hash = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64, unique=True)
    signature = models.CharField(max_length=128)

    class Meta:
        app_label = "portfolio"
        db_table = "portfolio_benchmark_approval_event"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(fields=["scope_key", "sequence"], name="pf_bm_scope_seq_uq"),
            models.UniqueConstraint(
                fields=["request_id", "action"], name="pf_bm_request_action_uq"
            ),
            models.CheckConstraint(
                condition=models.Q(action__in=["submitted", "approved", "revoked"]),
                name="pf_bm_event_action_ck",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Require a newly signed append; never rewrite an existing transition."""
        if (
            _claim.get() is not self
            or self.pk is not None
            or force_insert is not True
            or force_update
            or update_fields is not None
        ):
            raise ValidationError("benchmark approvals are append-only")
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject fixture/raw writes and bind exactly one new row to the owner writer."""
        if (
            raw
            or force_update
            or update_fields is not None
            or self.pk is not None
            or _claim.get() is not self
        ):
            raise ValidationError("benchmark approval requires an authenticated decision")
        super().save_base(
            raw=raw,
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(self, using: str | None = None, keep_parents: bool = False) -> NoReturn:
        """Keep every historical submission, approval and withdrawal."""
        raise ValidationError("benchmark approvals are immutable")
