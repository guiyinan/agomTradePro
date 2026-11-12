"""Private exact-insert claims and immutable lossless per-disposition tax journals.

One row retains a liability-state component, financial transition and complete
operation provenance. Audit/Outbox are independent mandatory original evidence;
a public payload hash supplies no authority to write or repair missing records.
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

from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
)
from shared.infrastructure.django_append_only import AppendOnlyManager, AppendOnlyQuerySet

_MODEL_T = TypeVar("_MODEL_T", bound=models.Model)
_ACTIVE_UOW: ContextVar[object | None] = ContextVar("simulated_tax_liability_uow", default=None)


class _InsertClaim:
    """Private capability for one exact, alias-bound liability-operation-row insert."""

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
    "simulated_tax_liability_insert_claim", default=None
)
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECIMAL_TEXT = re.compile(r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")


@contextmanager
def _activate_tax_liability_uow() -> Iterator[object]:
    """Activate a non-nestable repository UOW for exact claimed inserts."""

    if _ACTIVE_UOW.get() is not None:
        raise ValidationError("Tax liability operation UOWs may not be nested.")
    token = object()
    reset = _ACTIVE_UOW.set(token)
    try:
        yield token
    finally:
        _ACTIVE_UOW.reset(reset)


@contextmanager
def _claim_tax_liability_insert(
    *,
    token: object,
    using: str,
    model_type: type[models.Model],
    expected_values: Mapping[str, object],
) -> Iterator[None]:
    """Claim one exact unsaved assessment model inside the active transaction."""

    if _ACTIVE_UOW.get() is not token:
        raise ValidationError("Tax liability operation insert requires its private UOW.")
    if not connections[using].in_atomic_block:
        raise ValidationError("Tax liability operation insert requires the UOW transaction.")
    if _ACTIVE_CLAIM.get() is not None:
        raise ValidationError("Tax liability operation insert claims may not be nested.")
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
        raise ValidationError("Tax liability operation insert requires an exact append claim.")


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
            ensure_ascii=True,
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


class _TaxLiabilityQuerySet(AppendOnlyQuerySet[_MODEL_T]):
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
        raise ValidationError("Tax liability operations require repository persistence.")

    def _update(self, values: object) -> NoReturn:
        """Block Django's internal bulk-update path."""

        del values
        raise ValidationError("Tax liability operations are append-only.")

    def _raw_delete(self, using: str | None) -> NoReturn:
        """Block Django's raw queryset deletion path."""

        del using
        raise ValidationError("Tax liability operations are append-only.")

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
            raise ValidationError("Tax liability operation insert shortcut is forbidden.")
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
        raise ValidationError("Tax liability operation bulk insertion is forbidden.")


class _TaxLiabilityManager(AppendOnlyManager[_MODEL_T]):
    """Guard read/query entry points and reject manager mutation shortcuts."""

    def get_queryset(self) -> _TaxLiabilityQuerySet[_MODEL_T]:
        """Return the append-only guarded queryset on this manager's alias."""

        return _TaxLiabilityQuerySet(self.model, using=self._db)

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
        raise ValidationError("Tax liability operations require repository persistence.")

    def bulk_update(
        self,
        objs: Iterable[_MODEL_T],
        fields: Iterable[str],
        batch_size: int | None = None,
    ) -> NoReturn:
        """Reject manager-level historical evidence mutation."""

        del objs, fields, batch_size
        raise ValidationError("Tax liability operations are append-only.")


class _TaxLiabilityImmutableModel(models.Model):
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
            raise ValidationError(
                "Tax liability operation rows are append-only and cannot be replaced."
            )
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
                "Tax liability operation raw save requires a new row without a primary key."
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
        raise ValidationError("Tax liability operation rows are retained permanently.")


class CorporateActionTaxLiabilityOperationModel(_TaxLiabilityImmutableModel):
    """One immutable operation with separate state/journal component identities."""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.PROTECT,
        related_name="corporate_action_tax_operations",
    )
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="corporate_action_tax_operations",
    )
    assessment = models.ForeignKey(
        CorporateActionTaxAssessmentHeaderModel,
        on_delete=models.PROTECT,
        related_name="liability_operations",
    )
    operation_id = models.CharField(max_length=192)
    operation_request_sha256 = models.CharField(max_length=64)
    scope_sha256 = models.CharField(max_length=64)
    sequence = models.PositiveBigIntegerField()
    predecessor = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="successor_operations",
        null=True,
        blank=True,
    )
    canonical_account_namespace = models.CharField(max_length=32)
    canonical_account_id = models.CharField(max_length=192)
    currency = models.CharField(max_length=3)
    state_payload_json = models.TextField()
    state_sha256 = models.CharField(max_length=64)
    transition_payload_json = models.TextField()
    transition_sha256 = models.CharField(max_length=64)
    operation_payload_json = models.TextField()
    operation_sha256 = models.CharField(max_length=64)
    assessed_amount_text = models.CharField(max_length=128)
    net_collected_amount_text = models.CharField(max_length=128)
    outstanding_amount_text = models.CharField(max_length=128)
    tax_due_delta_text = models.CharField(max_length=128)
    collected_delta_text = models.CharField(max_length=128)
    outstanding_delta_text = models.CharField(max_length=128)
    cash_delta_text = models.CharField(max_length=128)
    audit_event_id = models.CharField(max_length=192)
    audit_event_version = models.CharField(max_length=128)
    audit_event_sha256 = models.CharField(max_length=64)
    outbox_record_id = models.CharField(max_length=192)
    outbox_payload_sha256 = models.CharField(max_length=64)
    objects: _TaxLiabilityManager[Self] = _TaxLiabilityManager()

    class Meta:
        base_manager_name = "objects"
        default_manager_name = "objects"
        db_table = "sim_ca_tax_liability_operation"
        ordering = ("account_id", "scope_sha256", "sequence")
        constraints = [
            models.UniqueConstraint(
                fields=("account", "operation_id"), name="sim_ca_tax_liability_op_uq"
            ),
            models.UniqueConstraint(
                fields=("account", "scope_sha256", "sequence"), name="sim_ca_tax_liability_seq_uq"
            ),
            models.UniqueConstraint(
                fields=("predecessor",),
                condition=models.Q(predecessor__isnull=False),
                name="sim_ca_tax_liability_next_uq",
            ),
            models.CheckConstraint(
                condition=~models.Q(predecessor=models.F("id")),
                name="sim_ca_tax_liability_self_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sequence=1, predecessor__isnull=True)
                    | models.Q(sequence__gt=1, predecessor__isnull=False)
                ),
                name="sim_ca_tax_liability_chain_ck",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        operation_id__gt="",
                        canonical_account_namespace="account",
                        canonical_account_id__gt="",
                        currency="CNY",
                        audit_event_id__gt="",
                        audit_event_version__gt="",
                        outbox_record_id__gt="",
                    )
                ),
                name="sim_ca_tax_liability_scope_ck",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    operation_request_sha256__regex=r"^[0-9a-f]{64}$",
                    scope_sha256__regex=r"^[0-9a-f]{64}$",
                    state_sha256__regex=r"^[0-9a-f]{64}$",
                    transition_sha256__regex=r"^[0-9a-f]{64}$",
                    operation_sha256__regex=r"^[0-9a-f]{64}$",
                    audit_event_sha256__regex=r"^[0-9a-f]{64}$",
                    outbox_payload_sha256__regex=r"^[0-9a-f]{64}$",
                ),
                name="sim_ca_tax_liability_hash_ck",
            ),
        ]

    def save(
        self,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Check component byte seals and exact immutable append capability."""
        for payload, digest, label in (
            (self.state_payload_json, self.state_sha256, "liability state"),
            (self.transition_payload_json, self.transition_sha256, "financial transition"),
            (self.operation_payload_json, self.operation_sha256, "operation provenance"),
        ):
            _verify_canonical_payload(payload, digest, field_name=label)
        for name in (
            "assessed_amount_text",
            "net_collected_amount_text",
            "outstanding_amount_text",
            "tax_due_delta_text",
            "collected_delta_text",
            "outstanding_delta_text",
            "cash_delta_text",
        ):
            _verify_decimal_text(getattr(self, name), field_name=name)
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


__all__ = ["CorporateActionTaxLiabilityOperationModel"]
