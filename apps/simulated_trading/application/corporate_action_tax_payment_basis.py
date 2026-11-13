"""Typed proof that a simulated cash dividend was fully paid and audited.

The value binds one account-wide record-date entitlement and payment. It is
deliberately independent of any one disposition so the same payment can
support multiple partial-sale tax assessments.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any, NoReturn, cast
from uuid import UUID
from zoneinfo import ZoneInfo

from apps.simulated_trading.domain.corporate_action_deferred_tax import (
    DeferredDividendTaxValidationError,
)
from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import TaxLiabilityScope
from core.exceptions import BusinessLogicError

_SCHEMA = "simulated-dividend-payment-basis.v1"
_INVALID_CODE = "SIMULATED_DIVIDEND_PAYMENT_BASIS_BLOCKED"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CENT = Decimal("0.01")
_DIGEST_CHARACTERS = frozenset("0123456789abcdef")
_DATE_FIELDS = frozenset({"record_date", "effective_date", "payment_date"})
_DECIMAL_FIELDS = frozenset({"dividend_per_share", "eligible_quantity", "gross_entitlement_amount"})
_DATETIME_FIELDS = frozenset(
    {
        "ownership_snapshot_observed_at",
        "entitlement_source_observed_at",
        "entitlement_qualified_at",
        "entitlement_posted_at",
        "entitlement_row_created_at",
        "entitlement_audit_recorded_at",
        "entitlement_audit_persisted_at",
        "entitlement_outbox_created_at",
        "payment_source_observed_at",
        "payment_qualified_at",
        "payment_posted_at",
        "payment_row_created_at",
        "payment_audit_recorded_at",
        "payment_audit_persisted_at",
        "payment_outbox_created_at",
    }
)
_INTEGER_FIELDS = frozenset(
    {
        "account_id",
        "owner_user_id",
        "entitlement_entry_id",
        "entitlement_account_revision",
        "entitlement_audit_sequence_no",
        "payment_entry_id",
        "payment_account_revision",
        "payment_audit_sequence_no",
    }
)
_PAYLOAD_FIELDS = (
    "account_id",
    "owner_user_id",
    "security_id",
    "asset_code",
    "asset_name",
    "corporate_action_id",
    "source_namespace",
    "source_record_id",
    "source_event_id",
    "source_revision_id",
    "source_revision_sha256",
    "source_payload_sha256",
    "record_date",
    "effective_date",
    "payment_date",
    "dividend_per_share",
    "eligible_quantity",
    "gross_entitlement_amount",
    "tax_treatment",
    "qualification_sha256",
    "qualifier_identity",
    "ownership_snapshot_id",
    "ownership_snapshot_sha256",
    "ownership_snapshot_observed_at",
    "entitlement_calculation_sha256",
    "grant_account_namespace",
    "grant_account_id",
    "entitlement_entry_id",
    "entitlement_account_revision",
    "entitlement_request_payload_sha256",
    "entitlement_stage_date",
    "entitlement_source_observed_at",
    "entitlement_qualified_at",
    "entitlement_posted_at",
    "entitlement_row_created_at",
    "entitlement_audit_event_id",
    "entitlement_audit_event_version",
    "entitlement_audit_event_sha256",
    "entitlement_audit_recorded_at",
    "entitlement_audit_persisted_at",
    "entitlement_audit_sequence_no",
    "entitlement_audit_predecessor_hash",
    "entitlement_outbox_record_id",
    "entitlement_outbox_payload_sha256",
    "entitlement_outbox_created_at",
    "entitlement_grant_id",
    "entitlement_grant_version",
    "entitlement_grant_content_sha256",
    "payment_entry_id",
    "payment_account_revision",
    "payment_request_payload_sha256",
    "payment_stage_date",
    "payment_source_observed_at",
    "payment_qualified_at",
    "payment_posted_at",
    "payment_row_created_at",
    "payment_audit_event_id",
    "payment_audit_event_version",
    "payment_audit_event_sha256",
    "payment_audit_recorded_at",
    "payment_audit_persisted_at",
    "payment_audit_sequence_no",
    "payment_audit_predecessor_hash",
    "payment_outbox_record_id",
    "payment_outbox_payload_sha256",
    "payment_outbox_created_at",
    "payment_grant_id",
    "payment_grant_version",
    "payment_grant_content_sha256",
)


def _blocked(message: str) -> NoReturn:
    """Raise one stable Application-level denial for invalid paid-basis evidence."""

    raise BusinessLogicError(message, code=_INVALID_CODE)


def _token(value: object, *, field_name: str, limit: int = 192) -> str:
    """Validate a bounded stable identifier without whitespace or bad UTF-8."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > limit
        or any(character.isspace() for character in value)
    ):
        _blocked(f"{field_name} is invalid")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BusinessLogicError(f"{field_name} is invalid", code=_INVALID_CODE) from error
    return value


def _digest(value: object, *, field_name: str, optional: bool = False) -> str | None:
    """Validate an exact lowercase SHA-256 digest or an explicitly optional link."""

    if optional and value is None:
        return None
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in _DIGEST_CHARACTERS for character in value)
    ):
        _blocked(f"{field_name} is not a lowercase SHA-256 digest")
    return value


def _aware(value: object, *, field_name: str) -> datetime:
    """Require one exact aware datetime which is representable in UTC."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        _blocked(f"{field_name} must be timezone-aware")
    try:
        value.astimezone(UTC)
    except (OverflowError, ValueError) as error:
        raise BusinessLogicError(f"{field_name} is out of range", code=_INVALID_CODE) from error
    return value


def _datetime_text(value: datetime) -> str:
    """Serialize one aware event clock to a stable UTC timestamp."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decimal_text(value: Decimal) -> str:
    """Serialize a finite Decimal without exponent notation or context rounding."""

    if type(value) is not Decimal or not value.is_finite():
        _blocked("payment-basis decimal is invalid")
    return format(value, "f")


def _decimal_exponent(value: Decimal, *, field_name: str) -> int:
    """Return a finite Decimal exponent after rejecting special encodings."""

    exponent = value.as_tuple().exponent
    if type(exponent) is not int:
        _blocked(f"{field_name} has a non-finite decimal encoding")
    return exponent


@dataclass(frozen=True, slots=True)
class SimulatedDividendPaymentBasis:
    """One complete same-alias audited simulated cash-dividend payment proof.

    This DTO establishes the original payment evidence and its immutable
    references. It grants no new authority; callers still check the current
    owner grant before issuing a financial operation.
    """

    account_id: int
    owner_user_id: int
    security_id: str
    asset_code: str
    asset_name: str
    corporate_action_id: str
    source_namespace: str
    source_record_id: str
    source_event_id: str
    source_revision_id: str
    source_revision_sha256: str
    source_payload_sha256: str
    record_date: date
    effective_date: date
    payment_date: date
    dividend_per_share: Decimal
    eligible_quantity: Decimal
    gross_entitlement_amount: Decimal
    tax_treatment: str
    qualification_sha256: str
    qualifier_identity: str
    ownership_snapshot_id: str
    ownership_snapshot_sha256: str
    ownership_snapshot_observed_at: datetime
    entitlement_calculation_sha256: str
    grant_account_namespace: str
    grant_account_id: str
    entitlement_entry_id: int
    entitlement_account_revision: int
    entitlement_request_payload_sha256: str
    entitlement_stage_date: date
    entitlement_source_observed_at: datetime
    entitlement_qualified_at: datetime
    entitlement_posted_at: datetime
    entitlement_row_created_at: datetime
    entitlement_audit_event_id: str
    entitlement_audit_event_version: str
    entitlement_audit_event_sha256: str
    entitlement_audit_recorded_at: datetime
    entitlement_audit_persisted_at: datetime
    entitlement_audit_sequence_no: int
    entitlement_audit_predecessor_hash: str | None
    entitlement_outbox_record_id: str
    entitlement_outbox_payload_sha256: str
    entitlement_outbox_created_at: datetime
    entitlement_grant_id: str
    entitlement_grant_version: str
    entitlement_grant_content_sha256: str
    payment_entry_id: int
    payment_account_revision: int
    payment_request_payload_sha256: str
    payment_stage_date: date
    payment_source_observed_at: datetime
    payment_qualified_at: datetime
    payment_posted_at: datetime
    payment_row_created_at: datetime
    payment_audit_event_id: str
    payment_audit_event_version: str
    payment_audit_event_sha256: str
    payment_audit_recorded_at: datetime
    payment_audit_persisted_at: datetime
    payment_audit_sequence_no: int
    payment_audit_predecessor_hash: str | None
    payment_outbox_record_id: str
    payment_outbox_payload_sha256: str
    payment_outbox_created_at: datetime
    payment_grant_id: str
    payment_grant_version: str
    payment_grant_content_sha256: str

    def __post_init__(self) -> None:
        """Reject incomplete identities, clocks, links, or inexact cash economics."""

        for name in ("account_id", "owner_user_id", "entitlement_entry_id", "payment_entry_id"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                _blocked(f"{name} must be a positive exact integer")
        for name in ("entitlement_account_revision", "payment_account_revision"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                _blocked(f"{name} must be positive")
        if self.entitlement_entry_id == self.payment_entry_id:
            _blocked("entitlement and payment must be distinct immutable ledger entries")
        for name, limit in (
            ("security_id", 96),
            ("asset_code", 32),
            ("corporate_action_id", 128),
            ("source_namespace", 128),
            ("source_record_id", 192),
            ("source_event_id", 192),
            ("source_revision_id", 192),
            ("qualifier_identity", 128),
            ("ownership_snapshot_id", 192),
            ("grant_account_namespace", 32),
            ("grant_account_id", 192),
            ("entitlement_audit_event_id", 128),
            ("entitlement_audit_event_version", 64),
            ("entitlement_outbox_record_id", 36),
            ("entitlement_grant_id", 192),
            ("entitlement_grant_version", 192),
            ("payment_audit_event_id", 128),
            ("payment_audit_event_version", 64),
            ("payment_outbox_record_id", 36),
            ("payment_grant_id", 192),
            ("payment_grant_version", 192),
        ):
            _token(getattr(self, name), field_name=name, limit=limit)
        if (
            type(self.asset_name) is not str
            or not self.asset_name
            or self.asset_name != self.asset_name.strip()
            or len(self.asset_name) > 128
        ):
            _blocked("asset_name is invalid")
        try:
            self.asset_name.encode("utf-8")
        except UnicodeEncodeError as error:
            raise BusinessLogicError("asset_name is invalid UTF-8", code=_INVALID_CODE) from error
        for name in (
            "source_revision_sha256",
            "source_payload_sha256",
            "qualification_sha256",
            "ownership_snapshot_sha256",
            "entitlement_request_payload_sha256",
            "entitlement_audit_event_sha256",
            "entitlement_outbox_payload_sha256",
            "entitlement_grant_content_sha256",
            "payment_request_payload_sha256",
            "payment_audit_event_sha256",
            "payment_outbox_payload_sha256",
            "payment_grant_content_sha256",
        ):
            _digest(getattr(self, name), field_name=name)
        _digest(self.entitlement_calculation_sha256, field_name="entitlement_calculation_sha256")
        if self.grant_account_namespace != "simulated":
            _blocked("payment grant account namespace is unsupported")
        try:
            for name in ("entitlement_outbox_record_id", "payment_outbox_record_id"):
                if str(UUID(getattr(self, name))) != getattr(self, name):
                    _blocked(f"{name} is not a canonical UUID")
        except (TypeError, ValueError) as error:
            raise BusinessLogicError(
                "payment outbox identity is invalid", code=_INVALID_CODE
            ) from error

        for name in (
            "record_date",
            "effective_date",
            "payment_date",
            "entitlement_stage_date",
            "payment_stage_date",
        ):
            if type(getattr(self, name)) is not date:
                _blocked(f"{name} must be an exact calendar date")
        if self.payment_date <= self.record_date:
            _blocked("qualified payment date must follow the record date")
        if (
            self.entitlement_stage_date < self.record_date
            or self.payment_stage_date < self.payment_date
        ):
            _blocked("cash stages predate their qualified dates")

        for name in _DATETIME_FIELDS:
            _aware(getattr(self, name), field_name=name)
        if not (
            self.entitlement_source_observed_at
            <= self.entitlement_qualified_at
            <= self.entitlement_posted_at
            and self.payment_source_observed_at
            <= self.payment_qualified_at
            <= self.payment_posted_at
            and self.entitlement_source_observed_at == self.payment_source_observed_at
            and self.entitlement_posted_at <= self.entitlement_audit_recorded_at
            and self.payment_posted_at <= self.payment_audit_recorded_at
            and self.entitlement_audit_recorded_at <= self.entitlement_audit_persisted_at
            and self.payment_audit_recorded_at <= self.payment_audit_persisted_at
        ):
            _blocked("payment-basis clocks are out of order")
        if (
            self.entitlement_row_created_at > self.entitlement_audit_persisted_at
            or self.payment_row_created_at > self.payment_audit_persisted_at
            or self.entitlement_audit_persisted_at > self.entitlement_outbox_created_at
            or self.payment_audit_persisted_at > self.payment_outbox_created_at
        ):
            _blocked("ledger, Audit, and Outbox creation clocks are out of order")
        for name in ("entitlement_audit_sequence_no", "payment_audit_sequence_no"):
            if type(getattr(self, name)) is not int or getattr(self, name) <= 0:
                _blocked(f"{name} must be positive")
        for name in ("entitlement_audit_predecessor_hash", "payment_audit_predecessor_hash"):
            _digest(getattr(self, name), field_name=name, optional=True)
        for sequence_no, predecessor_hash in (
            (self.entitlement_audit_sequence_no, self.entitlement_audit_predecessor_hash),
            (self.payment_audit_sequence_no, self.payment_audit_predecessor_hash),
        ):
            if (sequence_no == 1) != (predecessor_hash is None):
                _blocked("Audit stream predecessor link is inconsistent")
        if self.payment_audit_sequence_no <= self.entitlement_audit_sequence_no:
            _blocked("payment Audit event does not follow its entitlement event")
        for name in ("tax_treatment",):
            if getattr(self, name) not in {"not_applicable", "deferred_withholding"}:
                _blocked(f"{name} is unsupported")
        dividend_per_share = self.dividend_per_share
        eligible_quantity = self.eligible_quantity
        gross_amount = self.gross_entitlement_amount
        for name, value in (
            ("dividend_per_share", dividend_per_share),
            ("eligible_quantity", eligible_quantity),
            ("gross_entitlement_amount", gross_amount),
        ):
            if type(value) is not Decimal or not value.is_finite() or value <= 0:
                _blocked(f"{name} must be a positive finite Decimal")
        dividend_exponent = _decimal_exponent(dividend_per_share, field_name="dividend_per_share")
        quantity_exponent = _decimal_exponent(eligible_quantity, field_name="eligible_quantity")
        gross_exponent = _decimal_exponent(gross_amount, field_name="gross_entitlement_amount")
        if dividend_exponent < -12 or dividend_exponent > 17 or dividend_per_share.adjusted() >= 18:
            _blocked("dividend_per_share exceeds supported exact precision")
        if quantity_exponent < -6 or quantity_exponent > 17 or eligible_quantity.adjusted() >= 18:
            _blocked("eligible_quantity exceeds retained share precision")
        if gross_exponent < -2 or gross_amount.adjusted() >= 13:
            _blocked("gross entitlement must be exact to cents")
        with localcontext() as context:
            context.prec = 80
            unrounded = eligible_quantity * dividend_per_share
            try:
                exact_cent_amount = unrounded.quantize(_CENT)
            except InvalidOperation as error:
                raise BusinessLogicError(
                    "gross entitlement is outside exact cash precision", code=_INVALID_CODE
                ) from error
        if exact_cent_amount != unrounded or gross_amount != unrounded:
            _blocked("gross entitlement is not the exact supported cent amount")
        if self.entitlement_grant_id != self.entitlement_grant_id.strip():
            _blocked("entitlement grant identity is invalid")
        if self.payment_grant_id != self.payment_grant_id.strip():
            _blocked("payment grant identity is invalid")

    @property
    def payload_json(self) -> str:
        """Return the exact canonical JSON representation persisted in financial material."""

        payload = self.to_payload()
        return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    @property
    def content_sha256(self) -> str:
        """Return the stable digest of this complete paid-basis proof."""

        return hashlib.sha256(self.payload_json.encode("utf-8")).hexdigest()

    def to_payload(self) -> dict[str, object]:
        """Encode every stable payment, ledger, Audit, Outbox, and grant reference."""

        self.__post_init__()
        payload: dict[str, object] = {"schema": _SCHEMA}
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is datetime:
                payload[field.name] = _datetime_text(value)
            elif type(value) is date:
                payload[field.name] = value.isoformat()
            elif type(value) is Decimal:
                payload[field.name] = _decimal_text(value)
            else:
                payload[field.name] = value
        return payload

    @classmethod
    def from_payload(cls, value: object) -> SimulatedDividendPaymentBasis:
        """Strictly restore one exact canonical paid-basis DTO from untrusted JSON."""

        if type(value) is not dict or set(value) != {"schema", *_PAYLOAD_FIELDS}:
            _blocked("payment-basis payload fields are missing or unsupported")
        if value.get("schema") != _SCHEMA:
            _blocked("payment-basis schema is unsupported")
        parsed: dict[str, object] = {}
        for name in _PAYLOAD_FIELDS:
            raw = value[name]
            try:
                if name in _DATE_FIELDS or name.endswith("_stage_date"):
                    if type(raw) is not str:
                        _blocked(f"{name} must be canonical date text")
                    decoded_date = date.fromisoformat(raw)
                    if decoded_date.isoformat() != raw:
                        _blocked(f"{name} must be canonical date text")
                    decoded_value: object = decoded_date
                elif name in _DATETIME_FIELDS:
                    if type(raw) is not str:
                        _blocked(f"{name} must be canonical datetime text")
                    decoded_datetime = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    if _datetime_text(decoded_datetime) != raw:
                        _blocked(f"{name} must be canonical UTC datetime text")
                    decoded_value = decoded_datetime
                elif name in _DECIMAL_FIELDS:
                    if type(raw) is not str or len(raw) > 64:
                        _blocked(f"{name} must be canonical decimal text")
                    decoded_decimal = Decimal(raw)
                    if not decoded_decimal.is_finite():
                        _blocked(f"{name} must be canonical decimal text")
                    exponent = _decimal_exponent(decoded_decimal, field_name=name)
                    if name == "dividend_per_share" and (
                        exponent < -12 or exponent > 17 or decoded_decimal.adjusted() >= 18
                    ):
                        _blocked(f"{name} exceeds supported exact precision")
                    if name == "eligible_quantity" and (
                        exponent < -6 or exponent > 17 or decoded_decimal.adjusted() >= 18
                    ):
                        _blocked(f"{name} exceeds supported share precision")
                    if name == "gross_entitlement_amount" and (
                        exponent < -2 or decoded_decimal.adjusted() >= 13
                    ):
                        _blocked(f"{name} exceeds supported cash precision")
                    if format(decoded_decimal, "f") != raw:
                        _blocked(f"{name} must be canonical decimal text")
                    decoded_value = decoded_decimal
                elif name in _INTEGER_FIELDS:
                    if type(raw) is not int:
                        _blocked(f"{name} must be an exact integer")
                    decoded_value = raw
                elif name.endswith("_predecessor_hash"):
                    if raw is not None and type(raw) is not str:
                        _blocked(f"{name} must be a digest or null")
                    decoded_value = raw
                else:
                    if type(raw) is not str:
                        _blocked(f"{name} must be text")
                    decoded_value = raw
            except (InvalidOperation, OverflowError, ValueError) as error:
                raise BusinessLogicError(f"{name} is malformed", code=_INVALID_CODE) from error
            parsed[name] = decoded_value
        basis = cls(**cast(Any, parsed))
        if basis.to_payload() != value:
            _blocked("payment-basis payload is not in canonical form")
        return basis

    def verify_scope(self, scope: TaxLiabilityScope, *, as_of: datetime) -> None:
        """Bind this account-wide payment to one disposition's shared action scope."""

        self.__post_init__()
        if type(scope) is not TaxLiabilityScope:
            _blocked("an exact tax-liability scope is required")
        try:
            scope.__post_init__()
        except (DeferredDividendTaxValidationError, TypeError, ValueError) as error:
            raise BusinessLogicError(
                "tax-liability scope is invalid", code=_INVALID_CODE
            ) from error
        cutoff = _aware(as_of, field_name="as_of")
        if (
            scope.account_id != self.account_id
            or scope.owner_user_id != self.owner_user_id
            or scope.security_id != self.security_id
            or scope.asset_code != self.asset_code
            or scope.corporate_action_id != self.corporate_action_id
            or scope.source_namespace != self.source_namespace
            or scope.logical_source_event_id != self.source_event_id
            or scope.record_date != self.record_date
        ):
            _blocked("payment basis differs from the exact account/action scope")
        operation_date = cutoff.astimezone(_SHANGHAI).date()
        if operation_date < self.payment_date:
            _blocked("qualified simulated dividend payment date has not been reached")
        if operation_date < self.entitlement_stage_date or operation_date < self.payment_stage_date:
            _blocked("qualified cash stage date has not been reached")
        known_clocks = (
            self.ownership_snapshot_observed_at,
            self.entitlement_source_observed_at,
            self.entitlement_qualified_at,
            self.entitlement_posted_at,
            self.entitlement_row_created_at,
            self.entitlement_audit_recorded_at,
            self.entitlement_audit_persisted_at,
            self.entitlement_outbox_created_at,
            self.payment_source_observed_at,
            self.payment_qualified_at,
            self.payment_posted_at,
            self.payment_row_created_at,
            self.payment_audit_recorded_at,
            self.payment_audit_persisted_at,
            self.payment_outbox_created_at,
        )
        cutoff_utc = cutoff.astimezone(UTC)
        if any(clock.astimezone(UTC) > cutoff_utc for clock in known_clocks):
            _blocked("payment-basis evidence was recorded after the operation cutoff")

    def verify_for(
        self,
        assessment: CorporateActionTaxAssessment,
        *,
        as_of: datetime,
    ) -> None:
        """Bind the original full account payment to one integrity-verified assessment."""

        self.__post_init__()
        if type(assessment) is not CorporateActionTaxAssessment:
            _blocked("an exact tax assessment is required")
        try:
            assessment.verify_integrity()
        except (DeferredDividendTaxValidationError, TypeError, ValueError) as error:
            raise BusinessLogicError(
                "tax assessment integrity is invalid", code=_INVALID_CODE
            ) from error
        action = assessment.action
        history = assessment.history
        scope = TaxLiabilityScope(
            account_id=assessment.account_id,
            owner_user_id=assessment.owner_user_id,
            security_id=assessment.security_id,
            asset_code=assessment.asset_code,
            corporate_action_id=action.corporate_action_id,
            source_namespace=action.source_namespace,
            logical_source_event_id=action.source_event_id,
            target_disposition_id=assessment.bridge.request.target_disposition_id,
            record_date=history.record_date,
            target_settlement_date=assessment.target_settlement_date,
        )
        self.verify_scope(scope, as_of=as_of)
        full_quantity = history.record_date_entitlement.qualified_total_quantity
        with localcontext() as context:
            context.prec = 80
            gross = full_quantity * action.dividend_per_share
        if (
            self.source_record_id != action.source_record_id
            or self.source_revision_id != action.source_revision_id
            or self.source_revision_sha256 != action.source_revision_sha256
            or self.source_payload_sha256 != action.source_payload_sha256
            or self.effective_date != action.effective_date
            or self.dividend_per_share != action.dividend_per_share
            or self.eligible_quantity != full_quantity
            or self.gross_entitlement_amount != gross
        ):
            _blocked("paid basis differs from exact qualified source revision or full entitlement")


__all__ = ("SimulatedDividendPaymentBasis",)
