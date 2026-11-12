"""Append-only ORM rows for calculated corporate-action tax assessments.

The module defines models and private exact-insert claims only. It adds no
migration, App registration, repository, policy activation, or write authority.
All monetary and allocation Decimals are lossless canonical text to prevent
backend DecimalField rounding.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import NoReturn, Self, TypeVar, cast

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections, models
from django.db.models.base import ModelBase

from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar("simulated_tax_assessment_uow", default=None)


class _InsertClaim:
    """Private capability for one exact, alias-bound assessment-row insert."""

    def __init__(
        self,
        *,
        token: object,
        using: str,
        model_type: type[models.Model],
        expected_values: tuple[tuple[str, object], ...],
    ) -> None:
        self.token = token
        self.using = using
        self.model_type = model_type
        self.expected_values = expected_values


_ACTIVE_CLAIM: ContextVar[_InsertClaim | None] = ContextVar(
    "simulated_tax_assessment_insert_claim", default=None
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


@contextmanager
def _activate_tax_assessment_uow() -> Iterator[object]:
    """Activate a non-nestable repository UOW for exact claimed inserts."""

    if _ACTIVE_UOW.get() is not None:
        raise ValidationError("Tax assessment UOWs may not be nested.")
    token = object()
    reset = _ACTIVE_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_tax_assessment_insert(
    *,
    token: object,
    using: str,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact unsaved assessment model inside the active transaction."""

    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("Tax assessment insert requires its private UOW.")
    if not connections[using].in_atomic_block:
        raise ValidationError("Tax assessment insert requires the UOW transaction.")
    if _ACTIVE_CLAIM.get() is not None:
        raise ValidationError("Tax assessment insert claims may not be nested.")
    claim = _InsertClaim(
        token=token,
        using=using,
        model_type=model_type,
        expected_values=tuple(sorted(expected_values.items())),
    )
    reset = _ACTIVE_CLAIM.set(claim)
    try:
        yield
    finally:
        _ACTIVE_CLAIM.reset(reset)


def _require_insert_claim(model: models.Model, *, using: str | None = None) -> None:
    """Require exact field values, model type, UOW token, and database alias."""

    claim = _ACTIVE_CLAIM.get()
    actual = tuple(
        sorted(
            (field.attname, getattr(model, field.attname))
            for field in model._meta.concrete_fields
            if field is not model._meta.auto_field
        )
    )
    if (
        claim is None
        or claim.token is not _ACTIVE_UOW.get()
        or (using is not None and using != claim.using)
        or not connections[claim.using].in_atomic_block
        or claim.model_type is not type(model)
        or claim.expected_values != actual
    ):
        raise ValidationError("Tax assessment insert requires an exact append claim.")


def _verify_canonical_payload(payload: str, digest: str, *, field_name: str) -> None:
    """Require canonical JSON text and its matching SHA-256 before insert."""

    if (
        type(payload) is not str
        or not payload
        or type(digest) is not str
        or _HEX_SHA256.fullmatch(digest) is None
    ):
        raise ValidationError(f"{field_name} must include canonical JSON and SHA-256.")
    try:
        payload_bytes = payload.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValidationError(f"{field_name} JSON must be valid UTF-8.") from error
    try:
        parsed = json.loads(payload)
        if type(parsed) is not dict:
            raise ValueError("top-level payload must be an object")
        canonical = json.dumps(
            parsed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValidationError(f"{field_name} is not canonical JSON.") from error
    if canonical != payload or hashlib.sha256(payload_bytes).hexdigest() != digest:
        raise ValidationError(f"{field_name} JSON digest does not match.")


def _verify_decimal_text(value: str, *, field_name: str) -> None:
    """Require finite, non-exponent decimal text without backend numeric coercion."""

    if type(value) is not str or _DECIMAL_TEXT.fullmatch(value) is None:
        raise ValidationError(f"{field_name} must be canonical lossless decimal text.")


class _TaxAssessmentQuerySet(AppendOnlyQuerySet[_MODEL_T]):
    """Block all bulk update, insert, raw-delete, and delete shortcuts."""

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Require repository exact-identity checks for every assessment insert."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Tax assessments require repository persistence.")

    def _update(self, values: object) -> NoReturn:
        """Block Django's internal bulk-update path."""

        del values
        raise ValidationError("Tax assessments are append-only.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Block Django's raw queryset deletion path."""

        del using
        raise ValidationError("Tax assessments are append-only.")

    def _insert(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[object],
        returning_fields: Iterable[object] | None = None,
        raw: bool = False,
        using: str | None = None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> list[tuple[object, ...]]:
        """Allow only one insert bearing this model's exact active private claim."""

        items = list(objs)
        if (
            len(items) != 1
            or raw
            or on_conflict is not None
            or update_fields is not None
            or unique_fields is not None
            or (using is not None and using != self.db)
        ):
            raise ValidationError("Tax assessment insert shortcut is forbidden.")
        for item in items:
            _require_insert_claim(item, using=self.db)
        insert = cast(
            Callable[..., list[tuple[object, ...]]],
            getattr(super(), "_insert"),  # noqa: B009 -- typed Django private boundary
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
        objs: list[_MODEL_T],
        fields: list[object],
        batch_size: int | None,
        on_conflict: object | None = None,
        update_fields: Iterable[object] | None = None,
        unique_fields: Iterable[object] | None = None,
    ) -> NoReturn:
        """Reject batched insert paths, even when a caller batches one row."""

        del objs, fields, batch_size, on_conflict, update_fields, unique_fields
        raise ValidationError("Tax assessment bulk insertion is forbidden.")


class _TaxAssessmentManager(AppendOnlyManager[_MODEL_T]):
    """Guard read/query entry points and reject manager mutation shortcuts."""

    def get_queryset(self) -> _TaxAssessmentQuerySet[_MODEL_T]:
        """Return the append-only guarded queryset on this manager's alias."""

        return _TaxAssessmentQuerySet(self.model, using=self._db)

    def bulk_create(
        self,
        objs: Iterable[_MODEL_T],
        batch_size: int | None = None,
        ignore_conflicts: bool = False,
        update_conflicts: bool = False,
        update_fields: Collection[str] | None = None,
        unique_fields: Collection[str] | None = None,
    ) -> NoReturn:
        """Reject manager insertion shortcuts around the exact claim."""

        del objs, batch_size, ignore_conflicts, update_conflicts, update_fields, unique_fields
        raise ValidationError("Tax assessments require repository persistence.")

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level historical evidence mutation."""

        del objs, fields, batch_size
        raise ValidationError("Tax assessments are append-only.")


class _TaxAssessmentImmutableModel(models.Model):
    """Require exact repository claims for new rows and reject all later mutation."""

    recorded_at = models.DateTimeField()

    class Meta:
        abstract = True

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow only one new claimed row with a database-generated primary key."""

        del force_insert
        if (
            self.pk is not None
            or force_update
            or update_fields is not None
            or not self._state.adding
        ):
            raise ValidationError("Tax assessment rows are append-only and cannot be replaced.")
        _require_insert_claim(self, using=using)
        super().save(force_insert=True, using=using)

    def save_base(
        self,
        raw: bool = False,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Reject fixture/raw save paths and require the same exact insert claim."""

        del force_insert
        if (
            raw
            or self.pk is not None
            or force_update
            or update_fields is not None
            or not self._state.adding
        ):
            raise ValidationError(
                "Tax assessment raw save requires a new row without a primary key."
            )
        _require_insert_claim(self, using=using)
        super().save_base(
            raw=False,
            force_insert=True,
            force_update=False,
            using=using,
            update_fields=None,
        )

    def delete(self, using: str | None = None, keep_parents: bool = False) -> NoReturn:
        """Keep every recorded assessment and allocation permanently."""

        del using, keep_parents
        raise ValidationError("Tax assessment rows are retained permanently.")


class CorporateActionTaxAssessmentHeaderModel(_TaxAssessmentImmutableModel):
    """One immutable source-, policy-, history-, and owner-bound assessment revision."""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="corporate_action_tax_assessments",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="corporate_action_tax_assessments",
    )
    authority_grant_id = models.CharField(max_length=192)
    authority_grant_version = models.CharField(max_length=192)
    authority_grant_sha256 = models.CharField(max_length=64)
    audit_tenant_id = models.CharField(max_length=192)
    audit_owner_id = models.CharField(max_length=192)
    assessment_revision_id = models.CharField(max_length=192)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="successor_assessments",
        null=True,
        blank=True,
    )
    supersedes_assessment_revision_id = models.CharField(max_length=192, null=True, blank=True)
    asset_code = models.CharField(max_length=96)
    security_id = models.CharField(max_length=96)
    corporate_action_id = models.CharField(max_length=128)
    source_namespace = models.CharField(max_length=128)
    source_record_id = models.CharField(max_length=192)
    source_event_id = models.CharField(max_length=192)
    action_source_revision_id = models.CharField(max_length=192)
    action_source_revision_sha256 = models.CharField(max_length=64)
    action_source_payload_sha256 = models.CharField(max_length=64)
    settlement_source_revision_id = models.CharField(max_length=192)
    settlement_source_revision_sha256 = models.CharField(max_length=64)
    record_date = models.DateField()
    settlement_date = models.DateField()
    settlement_date_rule_id = models.CharField(max_length=192)
    settlement_date_rule_sha256 = models.CharField(max_length=64)
    settlement_calendar_id = models.CharField(max_length=192)
    settlement_calendar_sha256 = models.CharField(max_length=64)
    policy_id = models.CharField(max_length=96)
    policy_version = models.CharField(max_length=96)
    policy_source_identity = models.CharField(max_length=192)
    policy_source_sha256 = models.CharField(max_length=64)
    policy_sha256 = models.CharField(max_length=64)
    statutory_revision_set_sha256 = models.CharField(max_length=64)
    disposition_id = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=64)
    semantic_payload_json = models.TextField()
    semantic_sha256 = models.CharField(max_length=64)
    observation_manifest_json = models.TextField()
    observation_manifest_sha256 = models.CharField(max_length=64)
    calculation_payload_json = models.TextField()
    calculation_sha256 = models.CharField(max_length=64)
    gross_dividend_amount_text = models.CharField(max_length=128)
    taxable_dividend_amount_text = models.CharField(max_length=128)
    withholding_amount_text = models.CharField(max_length=128)
    objects: _TaxAssessmentManager[Self] = _TaxAssessmentManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        db_table = "sim_ca_tax_assessment"
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "account",
                    "source_event_id",
                    "action_source_revision_id",
                    "disposition_id",
                    "assessment_revision_id",
                ),
                name="sim_ca_tax_assessment_rev_uq",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(assessment_revision_id__gt="")
                    & models.Q(asset_code__gt="")
                    & models.Q(security_id__gt="")
                    & models.Q(corporate_action_id__gt="")
                    & models.Q(source_event_id__gt="")
                    & models.Q(action_source_revision_id__gt="")
                    & models.Q(settlement_source_revision_id__gt="")
                    & models.Q(disposition_id__gt="")
                    & models.Q(authority_grant_id__gt="")
                    & models.Q(authority_grant_version__gt="")
                    & models.Q(audit_tenant_id__gt="")
                    & models.Q(audit_owner_id__gt="")
                ),
                name="sim_ca_tax_assess_scope_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(supersedes__isnull=True)
                    & models.Q(supersedes_assessment_revision_id__isnull=True)
                )
                | (
                    models.Q(supersedes__isnull=False)
                    & models.Q(supersedes_assessment_revision_id__gt="")
                ),
                name="sim_ca_tax_assess_successor_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    action_source_revision_sha256__regex=r"^[0-9a-f]{64}$",
                    action_source_payload_sha256__regex=r"^[0-9a-f]{64}$",
                    settlement_source_revision_sha256__regex=r"^[0-9a-f]{64}$",
                    settlement_date_rule_sha256__regex=r"^[0-9a-f]{64}$",
                    settlement_calendar_sha256__regex=r"^[0-9a-f]{64}$",
                    policy_source_sha256__regex=r"^[0-9a-f]{64}$",
                    policy_sha256__regex=r"^[0-9a-f]{64}$",
                    statutory_revision_set_sha256__regex=r"^[0-9a-f]{64}$",
                    idempotency_key__regex=r"^[0-9a-f]{64}$",
                    semantic_sha256__regex=r"^[0-9a-f]{64}$",
                    observation_manifest_sha256__regex=r"^[0-9a-f]{64}$",
                    calculation_sha256__regex=r"^[0-9a-f]{64}$",
                    authority_grant_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="sim_ca_tax_assess_hash_ck",
            ),
        ]

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Validate canonical evidence and permit only a claimed immutable insert."""

        _verify_canonical_payload(
            self.semantic_payload_json,
            self.semantic_sha256,
            field_name="semantic payload",
        )
        _verify_canonical_payload(
            self.observation_manifest_json,
            self.observation_manifest_sha256,
            field_name="observation manifest",
        )
        _verify_canonical_payload(
            self.calculation_payload_json,
            self.calculation_sha256,
            field_name="calculation payload",
        )
        for value, field_name in (
            (self.gross_dividend_amount_text, "gross_dividend_amount_text"),
            (self.taxable_dividend_amount_text, "taxable_dividend_amount_text"),
            (self.withholding_amount_text, "withholding_amount_text"),
        ):
            _verify_decimal_text(value, field_name=field_name)
        supersedes_id = cast(int | None, self.__dict__.get("supersedes_id"))
        if (supersedes_id is None) != (self.supersedes_assessment_revision_id is None):
            raise ValidationError("Assessment successor reference and revision must be paired.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class CorporateActionTaxAssessmentAllocationModel(_TaxAssessmentImmutableModel):
    """One ordered lossless FIFO allocation row belonging to one assessment revision."""

    assessment = models.ForeignKey(
        CorporateActionTaxAssessmentHeaderModel,
        on_delete=models.PROTECT,
        related_name="allocations",
    )
    ordinal = models.PositiveIntegerField()
    lot_id = models.CharField(max_length=128)
    allocation_payload_json = models.TextField()
    allocation_sha256 = models.CharField(max_length=64)
    objects: _TaxAssessmentManager[Self] = _TaxAssessmentManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        db_table = "sim_ca_tax_assess_allocation"
        ordering = ("assessment_id", "ordinal")
        constraints = [
            models.UniqueConstraint(
                fields=("assessment", "ordinal"),
                name="sim_ca_tax_alloc_order_uq",
            ),
            models.UniqueConstraint(
                fields=("assessment", "lot_id"),
                name="sim_ca_tax_alloc_lot_uq",
            ),
            models.CheckConstraint(
                condition=models.Q(ordinal__gt=0) & models.Q(lot_id__gt=""),
                name="sim_ca_tax_alloc_identity_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(allocation_sha256__regex=r"^[0-9a-f]{64}$"),
                name="sim_ca_tax_alloc_hash_ck",
            ),
        ]

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Validate the canonical allocation payload and exact append claim."""

        _verify_canonical_payload(
            self.allocation_payload_json,
            self.allocation_sha256,
            field_name="allocation payload",
        )
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


__all__ = [
    "CorporateActionTaxAssessmentAllocationModel",
    "CorporateActionTaxAssessmentHeaderModel",
    "_activate_tax_assessment_uow",
    "_claim_tax_assessment_insert",
]
