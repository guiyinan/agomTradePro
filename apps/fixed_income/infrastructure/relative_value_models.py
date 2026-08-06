"""Strict append-only ORM ledger for R5 relative-value audit evidence."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import NoReturn, TypeVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase

from apps.fixed_income.domain.relative_value_assessment import R5RelativeValueStatus
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_ModelT = TypeVar("_ModelT", bound=models.Model)
_ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK: ContextVar[object | None] = ContextVar(
    "active_r5_relative_value_unit_of_work",
    default=None,
)


@dataclass(frozen=True)
class _R5RelativeValueInsertClaim:
    unit_of_work_token: object
    command_hash: str
    draft_hash: str
    model_type: type[models.Model]
    expected_values: tuple[tuple[str, object], ...]


_ACTIVE_R5_RELATIVE_VALUE_INSERT_CLAIM: ContextVar[_R5RelativeValueInsertClaim | None] = ContextVar(
    "active_r5_relative_value_insert_claim",
    default=None,
)


@dataclass(frozen=True)
class _R5OwnerGraphAuthorization:
    unit_of_work_token: object
    command_hash: str
    draft_hash: str


_ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION: ContextVar[_R5OwnerGraphAuthorization | None] = ContextVar(
    "active_r5_owner_graph_authorization",
    default=None,
)


@contextmanager
def _activate_r5_relative_value_unit_of_work(token: object) -> Iterator[None]:
    """Activate one private repository-owned persistence boundary."""

    reset_token = _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.set(token)
    try:
        yield
    finally:
        _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.reset(reset_token)


def _r5_relative_value_unit_of_work_is_active(token: object) -> bool:
    """Return whether ``token`` owns the active repository boundary."""

    return _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.get() is token


def _r5_owner_graph_append_is_authorized(
    *,
    token: object,
    command_hash: str,
    draft_hash: str,
) -> bool:
    """Return whether the active authorization matches every opaque digest."""

    authorization = _ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION.get()
    return (
        authorization is not None
        and authorization.unit_of_work_token is token
        and authorization.command_hash == command_hash
        and authorization.draft_hash == draft_hash
    )


@contextmanager
def _authorize_r5_owner_graph_append(
    *,
    token: object,
    command_hash: str,
    draft_hash: str,
) -> Iterator[None]:
    """Bind one verified owner graph to one command and draft digest."""

    if _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.get() is not token:
        raise ValidationError("R5 owner graph authorization requires its repository unit of work.")
    authorization = _R5OwnerGraphAuthorization(
        unit_of_work_token=token,
        command_hash=command_hash,
        draft_hash=draft_hash,
    )
    reset_token = _ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION.set(authorization)
    try:
        yield
    finally:
        _ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION.reset(reset_token)


@contextmanager
def _claim_r5_relative_value_insert(
    *,
    token: object,
    command_hash: str,
    draft_hash: str,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Authorize exactly one model/value insert inside the active UoW."""

    if _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.get() is not token:
        raise ValidationError(
            "R5 relative-value insert claim requires its repository unit of work."
        )
    authorization = _ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION.get()
    if (
        authorization is None
        or authorization.unit_of_work_token is not token
        or authorization.command_hash != command_hash
        or authorization.draft_hash != draft_hash
    ):
        raise ValidationError("R5 relative-value insert claim requires exact owner authorization.")
    claim = _R5RelativeValueInsertClaim(
        unit_of_work_token=token,
        command_hash=command_hash,
        draft_hash=draft_hash,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items(), key=lambda item: item[0])),
    )
    reset_token = _ACTIVE_R5_RELATIVE_VALUE_INSERT_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_R5_RELATIVE_VALUE_INSERT_CLAIM.reset(reset_token)


class R5RelativeValueAppendOnlyQuerySet(AppendOnlyQuerySet[_ModelT]):
    """Reject all bulk insertion shortcuts for exact R5 evidence."""

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject plain and conflict-aware bulk insertion."""

        raise ValidationError("R5 relative-value evidence requires exact append operations.")


class R5RelativeValueAppendOnlyManager(AppendOnlyManager[_ModelT]):
    """Expose identical write guards through default/base/related managers."""

    def get_queryset(self) -> R5RelativeValueAppendOnlyQuerySet[_ModelT]:
        """Return the R5-specific guarded QuerySet."""

        return R5RelativeValueAppendOnlyQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_ModelT],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager-level bulk insertion and conflict modes."""

        raise ValidationError("R5 relative-value evidence requires exact append operations.")


class R5RelativeValueAppendOnlyModel(models.Model):
    """Permit only a claimed database-assigned-primary-key insert."""

    objects = R5RelativeValueAppendOnlyManager()

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
        """Reject every unclaimed insert and every update path."""

        if force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 relative-value evidence is append-only.")
        self._require_exact_insert_claim()
        super().save(force_insert=force_insert, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Guard raw and direct instance ``save_base`` mutation paths.

        Explicit calls to Django's unbound ``models.Model.save_base`` are an
        internal-API boundary.  Exact repository restoration still detects any
        semantic header mutation performed beyond this guard.
        """

        if raw or force_update or update_fields is not None or self.pk is not None:
            raise ValidationError("R5 relative-value evidence is append-only.")
        self._require_exact_insert_claim()
        super().save_base(
            raw=False,
            force_insert=force_insert,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def _require_exact_insert_claim(self) -> None:
        """Fail unless the active claim matches this exact model and payload."""

        claim = _ACTIVE_R5_RELATIVE_VALUE_INSERT_CLAIM.get()
        authorization = _ACTIVE_R5_OWNER_GRAPH_AUTHORIZATION.get()
        if (
            claim is None
            or authorization is None
            or claim.unit_of_work_token is not _ACTIVE_R5_RELATIVE_VALUE_UNIT_OF_WORK.get()
            or authorization.unit_of_work_token is not claim.unit_of_work_token
            or authorization.command_hash != claim.command_hash
            or authorization.draft_hash != claim.draft_hash
            or claim.model_type is not type(self)
            or any(
                getattr(self, field_name) != value for field_name, value in claim.expected_values
            )
        ):
            raise ValidationError(
                "R5 relative-value evidence requires an exact repository insert claim."
            )

    def delete(
        self,
        using: object | None = None,
        keep_parents: bool = False,
    ) -> tuple[int, dict[str, int]]:
        """Reject instance deletion of audit evidence."""

        raise ValidationError("R5 relative-value evidence cannot be deleted.")


class FixedIncomeR5InputReceiptModel(R5RelativeValueAppendOnlyModel):
    """Complete Phase-A input/policy graph and server knowledge receipt."""

    receipt_id = models.CharField(max_length=192)
    receipt_version = models.CharField(max_length=96)
    owner = models.CharField(max_length=32, default="fixed_income")
    command_hash = models.CharField(max_length=64)
    assessment_id = models.CharField(max_length=160, unique=True)
    input_set_id = models.CharField(max_length=160)
    input_set_version = models.CharField(max_length=160)
    input_set_hash = models.CharField(max_length=64)
    policy_set_id = models.CharField(max_length=160)
    policy_set_version = models.CharField(max_length=160)
    policy_set_hash = models.CharField(max_length=64)
    evaluated_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    evidence_clock_graph_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    # Non-semantic ORM metadata; ``recorded_at`` is the sealed knowledge clock.
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "fixed_income"
        db_table = "fixed_income_r5_input_receipt"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["receipt_id", "receipt_version"],
                name="fi_r5_receipt_identity_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(evaluated_at__lte=models.F("recorded_at")),
                name="fi_r5_receipt_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="fixed_income",
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="fi_r5_receipt_safety_ck",
            ),
        ]


class FixedIncomeR5ResultModel(R5RelativeValueAppendOnlyModel):
    """Complete four-child composite linked to one protected input receipt."""

    result_id = models.CharField(max_length=192)
    result_version = models.CharField(max_length=96)
    owner = models.CharField(max_length=32, default="fixed_income")
    command_hash = models.CharField(max_length=64)
    receipt = models.ForeignKey(
        FixedIncomeR5InputReceiptModel,
        on_delete=models.PROTECT,
        related_name="relative_value_results",
    )
    assessment_id = models.CharField(max_length=160, unique=True)
    input_set_hash = models.CharField(max_length=64)
    policy_set_hash = models.CharField(max_length=64)
    input_hash = models.CharField(max_length=64)
    output_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=16,
        choices=[(status.value, status.value) for status in R5RelativeValueStatus],
    )
    evaluated_at = models.DateTimeField(db_index=True)
    recorded_at = models.DateTimeField(db_index=True)
    evidence_clock_graph_hash = models.CharField(max_length=64)
    canonical_payload = models.JSONField()
    content_hash = models.CharField(max_length=64, unique=True)
    research_only = models.BooleanField(default=True)
    must_not_execute = models.BooleanField(default=True)
    must_not_use_for_decision = models.BooleanField(default=True)
    # Non-semantic ORM metadata; ``recorded_at`` is the sealed knowledge clock.
    persisted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "fixed_income"
        db_table = "fixed_income_r5_result"
        base_manager_name = "objects"
        default_manager_name = "objects"
        constraints = [
            models.UniqueConstraint(
                fields=["result_id", "result_version"],
                name="fi_r5_result_identity_uq",
            ),
            models.UniqueConstraint(
                fields=["receipt"],
                name="fi_r5_result_receipt_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(evaluated_at__lte=models.F("recorded_at")),
                name="fi_r5_result_clock_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    owner="fixed_income",
                    research_only=True,
                    must_not_execute=True,
                    must_not_use_for_decision=True,
                ),
                name="fi_r5_result_safety_ck",
            ),
        ]


__all__ = [
    "FixedIncomeR5InputReceiptModel",
    "FixedIncomeR5ResultModel",
]
