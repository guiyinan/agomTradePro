"""Parse exact, externally reviewed capacity ceiling records at input boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from apps.data_center.application.financial_capacity_contracts import (
    FinancialCapacityBinding,
    FinancialCapacityWorkflowError,
    GovernedFinancialCapacityRehearsalCeiling,
    GovernedFinancialProductionCeiling,
    GovernedFinancialQualificationCeiling,
)

_BINDING_KEYS = frozenset(
    {
        "environment",
        "candidate_sha",
        "provider_id",
        "provider_name",
        "provider_source",
        "provider_identity_sha256",
        "contract_id",
        "contract_version",
        "contract_sha256",
        "parser_id",
        "parser_sha256",
        "deployment_region",
        "publication_policy_version",
        "publication_policy_sha256",
        "isolation_attestation_sha256",
    }
)
_ISOLATED_KEYS = frozenset(
    {
        "approval_id",
        "approved_by",
        "approved_at",
        "approval_receipt_sha256",
        "binding",
        "manifest_sha256",
        "maximum_slices",
        "maximum_provider_requests",
        "expires_at",
        "approved",
    }
)
_PRODUCTION_KEYS = frozenset(
    {
        "approval_id",
        "approved_by",
        "approved_at",
        "approval_receipt_sha256",
        "receipt_sha256",
        "binding",
        "manifest_sha256",
        "maximum_slices",
        "maximum_provider_requests",
        "expires_at",
        "approved",
    }
)


def parse_financial_capacity_governance_record(
    *,
    stage: Literal["qualification", "capacity_rehearsal", "production"],
    record: object,
) -> (
    GovernedFinancialQualificationCeiling
    | GovernedFinancialCapacityRehearsalCeiling
    | GovernedFinancialProductionCeiling
):
    """Validate a complete, already approved governance record into an exact ceiling."""

    if not isinstance(record, Mapping):
        raise FinancialCapacityWorkflowError("governed capacity record must be an object")
    expected_keys = _ISOLATED_KEYS if stage != "production" else _PRODUCTION_KEYS
    if set(record) != expected_keys:
        raise FinancialCapacityWorkflowError("governed capacity record shape is invalid")
    binding = _parse_binding(record.get("binding"))
    expected_environment = "production" if stage == "production" else "isolated"
    if binding.environment != expected_environment:
        raise FinancialCapacityWorkflowError("governed capacity record stage is invalid")
    raw_approved = record.get("approved")
    if raw_approved is not True:
        raise FinancialCapacityWorkflowError("governed capacity record is not approved")
    raw_expiry = _string(record, "expires_at")
    try:
        expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialCapacityWorkflowError("governed capacity expiry is invalid") from exc
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        raise FinancialCapacityWorkflowError("governed capacity expires_at must include UTC")
    approval_id = _string(record, "approval_id")
    approved_by = _string(record, "approved_by")
    approved_at = _datetime(record, "approved_at")
    approval_receipt_sha256 = _string(record, "approval_receipt_sha256")
    manifest_sha256 = _string(record, "manifest_sha256")
    maximum_slices = _positive_int(record, "maximum_slices")
    maximum_provider_requests = _positive_int(record, "maximum_provider_requests")
    if stage != "production":
        ceiling_type = (
            GovernedFinancialQualificationCeiling
            if stage == "qualification"
            else GovernedFinancialCapacityRehearsalCeiling
        )
        return ceiling_type(
            approval_id=approval_id,
            approved_by=approved_by,
            approved_at=approved_at,
            approval_receipt_sha256=approval_receipt_sha256,
            binding=binding,
            manifest_sha256=manifest_sha256,
            maximum_slices=maximum_slices,
            maximum_provider_requests=maximum_provider_requests,
            expires_at=expires_at,
            approved=True,
        )
    return GovernedFinancialProductionCeiling(
        receipt_sha256=_string(record, "receipt_sha256"),
        approval_id=approval_id,
        approved_by=approved_by,
        approved_at=approved_at,
        approval_receipt_sha256=approval_receipt_sha256,
        binding=binding,
        manifest_sha256=manifest_sha256,
        maximum_slices=maximum_slices,
        maximum_provider_requests=maximum_provider_requests,
        expires_at=expires_at,
        approved=True,
    )


def _parse_binding(raw_binding: object) -> FinancialCapacityBinding:
    """Narrow the provider, contract, parser, policy, and environment identity."""

    if not isinstance(raw_binding, Mapping) or set(raw_binding) != _BINDING_KEYS:
        raise FinancialCapacityWorkflowError("governed capacity binding shape is invalid")
    return FinancialCapacityBinding(
        environment=_string(raw_binding, "environment"),
        candidate_sha=_string(raw_binding, "candidate_sha"),
        provider_id=_positive_int(raw_binding, "provider_id"),
        provider_name=_string(raw_binding, "provider_name"),
        provider_source=_string(raw_binding, "provider_source"),
        provider_identity_sha256=_string(raw_binding, "provider_identity_sha256"),
        contract_id=_string(raw_binding, "contract_id"),
        contract_version=_string(raw_binding, "contract_version"),
        contract_sha256=_string(raw_binding, "contract_sha256"),
        parser_id=_string(raw_binding, "parser_id"),
        parser_sha256=_string(raw_binding, "parser_sha256"),
        deployment_region=_string(raw_binding, "deployment_region"),
        publication_policy_version=_string(raw_binding, "publication_policy_version"),
        publication_policy_sha256=_string(raw_binding, "publication_policy_sha256"),
        isolation_attestation_sha256=_string(raw_binding, "isolation_attestation_sha256"),
    )


def _string(payload: Mapping[str, object], name: str) -> str:
    """Require one exact string field without coercion."""

    value = payload.get(name)
    if type(value) is not str:
        raise FinancialCapacityWorkflowError(f"governed capacity {name} is invalid")
    return value


def _positive_int(payload: Mapping[str, object], name: str) -> int:
    """Require one positive integer, explicitly rejecting bool values."""

    value = payload.get(name)
    if type(value) is not int or value <= 0:
        raise FinancialCapacityWorkflowError(f"governed capacity {name} is invalid")
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    """Parse one explicit timestamp; ceiling validation enforces its UTC offset."""

    value = _string(payload, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FinancialCapacityWorkflowError(f"governed capacity {name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FinancialCapacityWorkflowError(f"governed capacity {name} must include UTC")
    return parsed


__all__ = ["parse_financial_capacity_governance_record"]
