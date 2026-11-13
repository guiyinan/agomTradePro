"""Lossless original operation material shared by journal and Audit verification.

Recorded origins are historical data. Only the active concrete scope verifier
may authorize a new financial append; loading this material grants no authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal, cast

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.simulated_trading.application.corporate_action_tax_liability import (
    TaxLiabilityEvidenceReference,
    TaxLiabilityFinancialSnapshot,
    TaxLiabilityWriteLease,
    _aware,
    _blocked,
)
from apps.simulated_trading.application.corporate_action_tax_liability_authority import (
    TaxLiabilityAuditOrigin,
)
from apps.simulated_trading.application.corporate_action_tax_payment_basis import (
    SimulatedDividendPaymentBasis,
)
from apps.simulated_trading.application.corporate_action_tax_qualification import (
    CurrentTaxAssessmentQualification,
)
from apps.simulated_trading.domain.corporate_action_tax_liability import (
    CorporateActionTaxLiabilityTransition,
    TaxLiabilityCashAction,
    TaxLiabilityOperationIdentity,
)
from apps.simulated_trading.domain.simulated_dividend_tax_policy_scope import (
    SimulatedDividendTaxCurrency,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_codec import (
    _integer,
    _money,
    _object,
    _read_document,
    _text,
    canonical_liability_json,
    tax_liability_scope_sha256,
)

_MATERIAL_FIELDS = frozenset(
    {
        "schema",
        "assessment_id",
        "identity_sha256",
        "state_sha256",
        "transition_sha256",
        "sequence",
        "predecessor_operation_sha256",
        "origin",
        "cash_snapshot",
        "cash_snapshot_provenance_json",
        "physical",
        "recorded_at",
    }
)


def _instant(value: datetime) -> str:
    """Preserve aware clocks as canonical UTC, without refreshing an observation."""
    return (
        _aware(value, field_name="stored financial clock")
        .astimezone(UTC)
        .isoformat(timespec="microseconds")
    )


def _clock(value: object) -> datetime:
    """Decode an exact original UTC clock without a naive-date fallback."""
    text = _text(value)
    result = datetime.fromisoformat(text)
    if _instant(result) != text:
        raise _blocked("stored financial clock is not canonical UTC")
    return result


def _decimal(value: Decimal) -> str:
    """Canonicalize bounded finite money without ambient Decimal context."""
    if type(value) is not Decimal or not value.is_finite():
        raise _blocked("stored financial money must be a finite exact Decimal")
    _, digits, exponent = value.as_tuple()
    if (
        type(exponent) is not int
        or exponent < -12
        or len(digits) > 80
        or (value != 0 and value.adjusted() > 67)
    ):
        raise _blocked("stored financial money exceeds supported exact precision")
    if value == 0:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _reference_payload(reference: TaxLiabilityEvidenceReference) -> dict[str, object]:
    """Retain one exact financial snapshot reference."""
    reference.__post_init__()
    return {
        "id": reference.reference_id,
        "version": reference.reference_version,
        "sha256": reference.content_sha256,
    }


def _qualification_payload(value: CurrentTaxAssessmentQualification) -> dict[str, object]:
    """Retain the actual verifier result and immutable runtime profile/snapshot pointers."""
    value.__post_init__()
    return {
        "assessment_semantic_sha256": value.assessment_semantic_sha256,
        "account_id": value.account_id,
        "owner_user_id": value.owner_user_id,
        "canonical_account_id": value.canonical_account_id,
        "environment": value.environment,
        "qualification_id": value.qualification_id,
        "qualification_sha256": value.qualification_sha256,
        "runtime_profile_id": value.runtime_profile_id,
        "runtime_profile_content_sha256": value.runtime_profile_content_sha256,
        "runtime_snapshot_id": value.runtime_snapshot_id,
        "runtime_snapshot_sha256": value.runtime_snapshot_sha256,
        "valid_until": _instant(value.valid_until),
    }


def _lease_payload(value: TaxLiabilityWriteLease) -> dict[str, object]:
    """Retain original authority facts; no stored lease becomes a live scope context."""
    value.__post_init__()
    return {
        "database_alias": value.database_alias,
        "actor_user_id": value.actor_user_id,
        "owner_user_id": value.owner_user_id,
        "physical_account_id": value.physical_account_id,
        "canonical_account_namespace": value.canonical_account_namespace,
        "canonical_account_id": value.canonical_account_id,
        "currency": value.currency.value,
        "currency_quantum": _decimal(value.currency_quantum),
        "assessment_revision_id": value.assessment_revision_id,
        "assessment_semantic_sha256": value.assessment_semantic_sha256,
        "operation_id": value.operation_id,
        "cash_action": None if value.cash_action is None else value.cash_action.value,
        "permission": value.permission,
        "grant_schema": value.grant_schema,
        "capabilities": [item.value for item in value.capabilities],
        "terms_version": value.terms_version,
        "terms_sha256": value.terms_sha256,
        "service_actor_id": value.service_actor_id,
        "authority_grant_id": value.authority_grant_id,
        "authority_grant_version": value.authority_grant_version,
        "authority_grant_content_sha256": value.authority_grant_content_sha256,
        "audit_tenant_id": value.audit_tenant_id,
        "audit_owner_id": value.audit_owner_id,
        "valid_until": _instant(value.valid_until),
    }


def _origin_payload(value: TaxLiabilityAuditOrigin) -> dict[str, object]:
    """Bind original account-source facts, qualification and actual financial grant."""
    value.__post_init__()
    payload: dict[str, object] = {
        "lease": _lease_payload(value.lease),
        "environment": value.environment,
        "account_source_id": value.account_source_id,
        "account_source_version": value.account_source_version,
        "account_source_sha256": value.account_source_sha256,
        "source_row_updated_at": _instant(value.source_row_updated_at),
        "qualification": _qualification_payload(value.qualification),
        "write_mode": value.write_mode,
    }
    if value.payment_basis is not None:
        payload["payment_basis"] = value.payment_basis.to_payload()
    return payload


@dataclass(frozen=True, slots=True)
class TaxLiabilityOperationMaterial:
    """Complete immutable context for one state/journal/Audit/Outbox operation."""

    assessment_id: int
    identity: TaxLiabilityOperationIdentity
    transition: CorporateActionTaxLiabilityTransition
    sequence: int
    predecessor_operation_sha256: str | None
    origin: TaxLiabilityAuditOrigin
    cash_snapshot: TaxLiabilityFinancialSnapshot | None
    cash_before: Decimal
    cash_after: Decimal
    physical_updated_before: datetime
    physical_updated_after: datetime
    recorded_at: datetime
    cash_snapshot_provenance_json: str | None = None

    def __post_init__(self) -> None:
        """Reject inconsistent money, identity, authority provenance or physical revision."""
        if type(self.assessment_id) is not int or self.assessment_id <= 0:
            raise _blocked("financial operation requires its actual stored assessment")
        if type(self.identity) is not TaxLiabilityOperationIdentity:
            raise _blocked("financial operation identity is untyped")
        self.identity.verify_integrity()
        if type(self.transition) is not CorporateActionTaxLiabilityTransition:
            raise _blocked("financial operation transition is untyped")
        self.transition.verify_integrity()
        if type(self.origin) is not TaxLiabilityAuditOrigin:
            raise _blocked("financial operation has no original Audit origin")
        self.origin.__post_init__()
        if type(self.sequence) is not int or self.sequence <= 0:
            raise _blocked("financial journal sequence is invalid")
        if (self.sequence == 1) != (self.predecessor_operation_sha256 is None):
            raise _blocked("financial journal predecessor and sequence differ")
        if self.predecessor_operation_sha256 is not None and (
            type(self.predecessor_operation_sha256) is not str
            or len(self.predecessor_operation_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.predecessor_operation_sha256)
        ):
            raise _blocked("financial journal predecessor seal is invalid")
        lease = self.origin.lease
        state = self.transition.state_after
        if (
            self.origin.write_mode != "append"
            or self.identity.scope != state.scope
            or lease.scope != state.scope
            or self.identity.operation_id != lease.operation_id
            or self.identity.cash_action is not lease.cash_action
            or self.identity.canonical_account_namespace != lease.canonical_account_namespace
            or self.identity.canonical_account_id != lease.canonical_account_id
            or self.identity.currency is not lease.currency
            or self.identity.assessment_revision_id != state.assessment_revision_id
            or self.identity.supersedes_assessment_revision_id
            != state.supersedes_assessment_revision_id
            or self.identity.assessment_semantic_sha256 != state.assessment_semantic_sha256
            or lease.assessment_revision_id != state.assessment_revision_id
            or lease.assessment_semantic_sha256 != state.assessment_semantic_sha256
            or lease.currency_quantum != state.currency_quantum
        ):
            raise _blocked("financial operation differs from its original exact scope")
        recorded = _aware(self.recorded_at, field_name="operation recorded_at")
        lease.assert_live(as_of=recorded)
        if self.origin.payment_basis is not None:
            if self.origin.payment_basis.grant_account_id != lease.canonical_account_id:
                raise _blocked("Original paid basis differs from the canonical account")
            self.origin.payment_basis.verify_scope(lease.scope, as_of=recorded)
        if recorded.astimezone(UTC) >= self.origin.qualification.valid_until.astimezone(UTC):
            raise _blocked("new financial operation was not qualified at its original clock")
        before = _aware(self.physical_updated_before, field_name="physical revision before")
        after = _aware(self.physical_updated_after, field_name="physical revision after")
        if before > after or after > recorded or self.origin.source_row_updated_at != before:
            raise _blocked("financial operation lacks its exact original physical source revision")
        changed = self.transition.cash_delta != 0 or self.transition.outstanding_delta != 0
        if after != (recorded if changed else before):
            raise _blocked(
                "financial operation physical revision does not match its actual effects"
            )
        for value in (self.cash_before, self.cash_after):
            if type(value) is not Decimal or not value.is_finite() or value < 0:
                raise _blocked("financial operation cash is unknown or negative")
            _decimal(value)
        with localcontext() as context:
            context.prec = 80
            if self.cash_after != self.cash_before + self.transition.cash_delta:
                raise _blocked("financial operation does not reconcile actual cash movement")
        request = self.transition.cash_request
        if self.identity.cash_action is None:
            if (
                self.cash_snapshot is not None
                or request is not None
                or self.cash_snapshot_provenance_json is not None
            ):
                raise _blocked("recognition cannot invent a cash request or snapshot")
        else:
            if type(self.cash_snapshot) is not TaxLiabilityFinancialSnapshot or request is None:
                raise _blocked("financial cash action lacks its original locked snapshot")
            self.cash_snapshot.verify_for(lease, as_of=recorded)
            if self.cash_snapshot.observed_at < before:
                raise _blocked("financial snapshot predates its physical account revision")
            self._verify_snapshot_provenance()
            if (
                request.action is not self.identity.cash_action
                or request.book_cash != self.cash_snapshot.book_cash
                or request.reserved_cash != self.cash_snapshot.reserved_cash
                or request.book_cash != self.cash_before
            ):
                raise _blocked(
                    "financial operation cash request differs from actual locked balances"
                )

    def _verify_snapshot_provenance(self) -> None:
        """Retain and verify the exact cash/hold snapshot bytes behind its reference."""
        snapshot = self.cash_snapshot
        if snapshot is None or type(self.cash_snapshot_provenance_json) is not str:
            raise _blocked("financial snapshot lacks its original full provenance")
        data = _object(
            _read_document(self.cash_snapshot_provenance_json, snapshot.evidence.content_sha256),
            frozenset(
                {
                    "schema",
                    "account_id",
                    "owner_user_id",
                    "canonical_account_namespace",
                    "canonical_account_id",
                    "currency",
                    "scope_sha256",
                    "book_cash",
                    "reserved_cash",
                    "physical_updated_at",
                    "observed_at",
                    "active_holds",
                }
            ),
        )
        if (
            data["schema"] != "simulated-tax-cash-snapshot.v1"
            or data["account_id"] != snapshot.physical_account_id
            or data["owner_user_id"] != snapshot.owner_user_id
            or data["canonical_account_namespace"] != snapshot.canonical_account_namespace
            or data["canonical_account_id"] != snapshot.canonical_account_id
            or data["currency"] != snapshot.currency.value
            or data["scope_sha256"] != tax_liability_scope_sha256(snapshot.scope)
            or _money(data["book_cash"]) != snapshot.book_cash
            or _money(data["reserved_cash"]) != snapshot.reserved_cash
            or _clock(data["physical_updated_at"]) != self.physical_updated_before
            or _clock(data["observed_at"]) != snapshot.observed_at
            or snapshot.evidence.reference_id
            != f"tax-cash-snapshot:{snapshot.evidence.content_sha256}"
            or snapshot.evidence.reference_version != "v1"
        ):
            raise _blocked("retained cash/hold snapshot differs from original physical facts")
        holds = data["active_holds"]
        if type(holds) is not list:
            raise _blocked("retained active hold membership is not an explicit list")
        previous = 0
        for item in cast(list[object], holds):
            row = _object(item, frozenset({"id", "key", "request_sha256", "updated_at"}))
            identifier = _integer(row["id"])
            digest = _text(row["request_sha256"])
            if (
                identifier <= previous
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or not _text(row["key"])
                or _clock(row["updated_at"]) > snapshot.observed_at
            ):
                raise _blocked("retained active hold identity or observation is inconsistent")
            previous = identifier

    def to_payload(self) -> dict[str, object]:
        """Retain original provenance without embedding circular Audit/Outbox hashes."""
        self.__post_init__()
        snapshot = self.cash_snapshot
        return {
            "schema": (
                "simulated-tax-liability-material.v1"
                if self.origin.payment_basis is None
                else "simulated-tax-liability-material.v2"
            ),
            "cash_snapshot_provenance_json": self.cash_snapshot_provenance_json,
            "assessment_id": self.assessment_id,
            "identity_sha256": self.identity.request_sha256,
            "state_sha256": self.transition.state_after.state_sha256,
            "transition_sha256": self.transition.transition_sha256,
            "sequence": self.sequence,
            "predecessor_operation_sha256": self.predecessor_operation_sha256,
            "origin": _origin_payload(self.origin),
            "cash_snapshot": (
                None
                if snapshot is None
                else {
                    "book_cash": _decimal(snapshot.book_cash),
                    "reserved_cash": _decimal(snapshot.reserved_cash),
                    "reference": _reference_payload(snapshot.evidence),
                    "observed_at": _instant(snapshot.observed_at),
                }
            ),
            "physical": {
                "cash_before": _decimal(self.cash_before),
                "cash_after": _decimal(self.cash_after),
                "updated_before": _instant(self.physical_updated_before),
                "updated_after": _instant(self.physical_updated_after),
            },
            "recorded_at": _instant(self.recorded_at),
        }

    @property
    def payload_json(self) -> str:
        """Return complete canonical immutable operation context."""
        return canonical_liability_json(self.to_payload())

    @property
    def content_sha256(self) -> str:
        """Seal financial context independently of state and transition component hashes."""
        return hashlib.sha256(self.payload_json.encode()).hexdigest()


def decode_operation_material(
    payload: str,
    expected_sha256: str,
    *,
    identity: TaxLiabilityOperationIdentity,
    transition: CorporateActionTaxLiabilityTransition,
) -> TaxLiabilityOperationMaterial:
    """Restore exact historical context without refreshing its original authority clocks."""
    try:
        fields = _object(_read_document(payload, expected_sha256), _MATERIAL_FIELDS)
        has_payment_basis = fields["schema"] == "simulated-tax-liability-material.v2"
        if (
            fields["schema"]
            not in {"simulated-tax-liability-material.v1", "simulated-tax-liability-material.v2"}
            or fields["identity_sha256"] != identity.request_sha256
            or fields["state_sha256"] != transition.state_after.state_sha256
            or fields["transition_sha256"] != transition.transition_sha256
        ):
            raise _blocked("stored financial material differs from original component seals")
        origin_fields = _object(
            fields["origin"],
            frozenset(
                {
                    "lease",
                    "environment",
                    "account_source_id",
                    "account_source_version",
                    "account_source_sha256",
                    "source_row_updated_at",
                    "qualification",
                    "write_mode",
                }
            )
            | (frozenset({"payment_basis"}) if has_payment_basis else frozenset()),
        )
        qualification_names = frozenset(
            {
                "assessment_semantic_sha256",
                "account_id",
                "owner_user_id",
                "canonical_account_id",
                "environment",
                "qualification_id",
                "qualification_sha256",
                "runtime_profile_id",
                "runtime_profile_content_sha256",
                "runtime_snapshot_id",
                "runtime_snapshot_sha256",
                "valid_until",
            }
        )
        q = _object(origin_fields["qualification"], qualification_names)
        qualification = CurrentTaxAssessmentQualification(
            assessment_semantic_sha256=_text(q["assessment_semantic_sha256"]),
            account_id=_integer(q["account_id"]),
            owner_user_id=_integer(q["owner_user_id"]),
            canonical_account_id=_text(q["canonical_account_id"]),
            environment=_text(q["environment"]),
            qualification_id=_text(q["qualification_id"]),
            qualification_sha256=_text(q["qualification_sha256"]),
            runtime_profile_id=_text(q["runtime_profile_id"]),
            runtime_profile_content_sha256=_text(q["runtime_profile_content_sha256"]),
            runtime_snapshot_id=_text(q["runtime_snapshot_id"]),
            runtime_snapshot_sha256=_text(q["runtime_snapshot_sha256"]),
            valid_until=_clock(q["valid_until"]),
        )
        lease_names = frozenset(
            {
                "database_alias",
                "actor_user_id",
                "owner_user_id",
                "physical_account_id",
                "canonical_account_namespace",
                "canonical_account_id",
                "currency",
                "currency_quantum",
                "assessment_revision_id",
                "assessment_semantic_sha256",
                "operation_id",
                "cash_action",
                "permission",
                "grant_schema",
                "capabilities",
                "terms_version",
                "terms_sha256",
                "service_actor_id",
                "authority_grant_id",
                "authority_grant_version",
                "authority_grant_content_sha256",
                "audit_tenant_id",
                "audit_owner_id",
                "valid_until",
            }
        )
        values = _object(origin_fields["lease"], lease_names)
        capabilities = values["capabilities"]
        if type(capabilities) is not list:
            raise _blocked("stored financial capabilities are not an exact list")
        action = values["cash_action"]
        lease = TaxLiabilityWriteLease(
            database_alias=_text(values["database_alias"]),
            actor_user_id=_integer(values["actor_user_id"]),
            owner_user_id=_integer(values["owner_user_id"]),
            physical_account_id=_integer(values["physical_account_id"]),
            scope=identity.scope,
            canonical_account_namespace=_text(values["canonical_account_namespace"]),
            canonical_account_id=_text(values["canonical_account_id"]),
            currency=SimulatedDividendTaxCurrency(_text(values["currency"])),
            currency_quantum=_money(values["currency_quantum"]),
            assessment_revision_id=_text(values["assessment_revision_id"]),
            assessment_semantic_sha256=_text(values["assessment_semantic_sha256"]),
            operation_id=_text(values["operation_id"]),
            cash_action=None if action is None else TaxLiabilityCashAction(_text(action)),
            permission=_text(values["permission"]),
            grant_schema=_text(values["grant_schema"]),
            capabilities=tuple(
                SimulatedCorporateActionWriteCapability(_text(item))
                for item in cast(list[object], capabilities)
            ),
            terms_version=_text(values["terms_version"]),
            terms_sha256=_text(values["terms_sha256"]),
            service_actor_id=_text(values["service_actor_id"]),
            authority_grant_id=_text(values["authority_grant_id"]),
            authority_grant_version=_text(values["authority_grant_version"]),
            authority_grant_content_sha256=_text(values["authority_grant_content_sha256"]),
            audit_tenant_id=_text(values["audit_tenant_id"]),
            audit_owner_id=_text(values["audit_owner_id"]),
            valid_until=_clock(values["valid_until"]),
        )
        mode = _text(origin_fields["write_mode"])
        if mode not in {"append", "exact_retry_only"}:
            raise _blocked("stored financial origin mode is unknown")
        origin = TaxLiabilityAuditOrigin(
            lease=lease,
            environment=_text(origin_fields["environment"]),
            account_source_id=_text(origin_fields["account_source_id"]),
            account_source_version=_text(origin_fields["account_source_version"]),
            account_source_sha256=_text(origin_fields["account_source_sha256"]),
            source_row_updated_at=_clock(origin_fields["source_row_updated_at"]),
            qualification=qualification,
            write_mode=cast(Literal["append", "exact_retry_only"], mode),
            payment_basis=(
                SimulatedDividendPaymentBasis.from_payload(origin_fields["payment_basis"])
                if has_payment_basis
                else None
            ),
        )
        snapshot_fields = fields["cash_snapshot"]
        snapshot: TaxLiabilityFinancialSnapshot | None = None
        if snapshot_fields is not None:
            data = _object(
                snapshot_fields,
                frozenset({"book_cash", "reserved_cash", "reference", "observed_at"}),
            )
            reference = _object(data["reference"], frozenset({"id", "version", "sha256"}))
            snapshot = TaxLiabilityFinancialSnapshot(
                physical_account_id=lease.physical_account_id,
                owner_user_id=lease.owner_user_id,
                scope=lease.scope,
                canonical_account_namespace=lease.canonical_account_namespace,
                canonical_account_id=lease.canonical_account_id,
                currency=lease.currency,
                book_cash=_money(data["book_cash"]),
                reserved_cash=_money(data["reserved_cash"]),
                evidence=TaxLiabilityEvidenceReference(
                    _text(reference["id"]), _text(reference["version"]), _text(reference["sha256"])
                ),
                observed_at=_clock(data["observed_at"]),
            )
        physical = _object(
            fields["physical"],
            frozenset({"cash_before", "cash_after", "updated_before", "updated_after"}),
        )
        predecessor = fields["predecessor_operation_sha256"]
        material = TaxLiabilityOperationMaterial(
            assessment_id=_integer(fields["assessment_id"]),
            identity=identity,
            transition=transition,
            sequence=_integer(fields["sequence"]),
            predecessor_operation_sha256=None if predecessor is None else _text(predecessor),
            origin=origin,
            cash_snapshot=snapshot,
            cash_before=_money(physical["cash_before"]),
            cash_after=_money(physical["cash_after"]),
            physical_updated_before=_clock(physical["updated_before"]),
            physical_updated_after=_clock(physical["updated_after"]),
            recorded_at=_clock(fields["recorded_at"]),
            cash_snapshot_provenance_json=(
                None
                if fields["cash_snapshot_provenance_json"] is None
                else _text(fields["cash_snapshot_provenance_json"])
            ),
        )
        if material.content_sha256 != expected_sha256:
            raise _blocked("stored financial material changed during typed reconstruction")
        return material
    except (ValueError, ArithmeticError) as error:
        raise _blocked("stored financial operation material failed validation") from error


__all__ = ["TaxLiabilityOperationMaterial", "decode_operation_material"]
