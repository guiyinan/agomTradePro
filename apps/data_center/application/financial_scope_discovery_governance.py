"""Parse externally reviewed full-scope discovery approvals."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryError,
    FinancialScopeManifestReview,
)

_AUTHORIZATION_SCHEMA = "data-center.financial-scope-discovery-authorization.v1"
_REVIEW_SCHEMA = "data-center.financial-scope-manifest-review.v1"
_AUTHORIZATION_KEYS = frozenset(
    {
        "schema_version",
        "approval_id",
        "approved_by",
        "approved_at",
        "approval_receipt_sha256",
        "expires_at",
        "approved",
        "recorded_by",
        "event_id",
        "binding",
        "universe",
        "budget",
    }
)
_REVIEW_KEYS = frozenset(
    {
        "schema_version",
        "candidate_sha",
        "manifest_sha256",
        "universe_sha256",
        "provider_identity_sha256",
        "contract_sha256",
        "deployment_region",
        "approval_id",
        "approved_by",
        "recorded_by",
        "event_id",
        "approval_receipt_sha256",
        "role",
        "environment",
        "report_sha256",
        "approved_at",
        "expires_at",
    }
)
_BINDING_KEYS = frozenset(
    {
        "candidate_sha",
        "provider_id",
        "provider_name",
        "provider_identity_sha256",
        "contract_id",
        "contract_version",
        "contract_sha256",
        "parser_id",
        "parser_sha256",
        "deployment_region",
    }
)
_UNIVERSE_KEYS = frozenset({"asset_count", "sha256"})
_BUDGET_KEYS = frozenset(
    {"maximum_logical_requests", "maximum_physical_attempts", "maximum_rows_per_asset"}
)


def parse_financial_scope_discovery_authorization(
    record: object,
) -> FinancialScopeDiscoveryAuthorization:
    """Narrow one exact externally approved record into a trusted domain value."""

    payload = _mapping(record)
    if (
        set(payload) != _AUTHORIZATION_KEYS
        or payload.get("schema_version") != _AUTHORIZATION_SCHEMA
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
    if payload.get("approved") is not True:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
    raw_binding = _mapping(payload.get("binding"))
    raw_universe = _mapping(payload.get("universe"))
    raw_budget = _mapping(payload.get("budget"))
    if (
        set(raw_binding) != _BINDING_KEYS
        or set(raw_universe) != _UNIVERSE_KEYS
        or set(raw_budget) != _BUDGET_KEYS
    ):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
    try:
        binding = FinancialScopeDiscoveryBinding(
            candidate_sha=_text(raw_binding, "candidate_sha"),
            provider_id=_positive_int(raw_binding, "provider_id"),
            provider_name=_text(raw_binding, "provider_name"),
            provider_identity_sha256=_text(raw_binding, "provider_identity_sha256"),
            contract_id=_text(raw_binding, "contract_id"),
            contract_version=_text(raw_binding, "contract_version"),
            contract_sha256=_text(raw_binding, "contract_sha256"),
            parser_id=_text(raw_binding, "parser_id"),
            parser_sha256=_text(raw_binding, "parser_sha256"),
            deployment_region=_text(raw_binding, "deployment_region"),
        )
        universe_count = _positive_int(raw_universe, "asset_count")
        authorization = FinancialScopeDiscoveryAuthorization(
            approval_id=_text(payload, "approval_id"),
            candidate_sha=binding.candidate_sha,
            approved_by=_text(payload, "approved_by"),
            recorded_by=_text(payload, "recorded_by"),
            event_id=_text(payload, "event_id"),
            receipt_sha256=_text(payload, "approval_receipt_sha256"),
            provider_id=binding.provider_id,
            provider_identity_sha256=binding.provider_identity_sha256,
            contract_id=binding.contract_id,
            contract_sha256=binding.contract_sha256,
            deployment_region=binding.deployment_region,
            universe_count=universe_count,
            universe_sha256=_text(raw_universe, "sha256"),
            maximum_logical_requests=_positive_int(raw_budget, "maximum_logical_requests"),
            maximum_physical_attempts=_positive_int(raw_budget, "maximum_physical_attempts"),
            maximum_rows_per_asset=_positive_int(raw_budget, "maximum_rows_per_asset"),
            approved_at=_datetime(payload, "approved_at"),
            expires_at=_datetime(payload, "expires_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FinancialScopeDiscoveryError):
            raise
        raise FinancialScopeDiscoveryError(
            "FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID"
        ) from None
    return authorization


def parse_financial_scope_manifest_review(record: object) -> FinancialScopeManifestReview:
    """Narrow one independently approved manifest review event payload."""

    payload = _mapping(record)
    if set(payload) != _REVIEW_KEYS or payload.get("schema_version") != _REVIEW_SCHEMA:
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID")
    try:
        role_text = _text(payload, "role")
        if role_text == "data_owner":
            role: Literal["data_owner", "independent_reviewer"] = "data_owner"
        elif role_text == "independent_reviewer":
            role = "independent_reviewer"
        else:
            raise ValueError
        environment_text = _text(payload, "environment")
        if environment_text == "isolated":
            environment: Literal["isolated", "production"] = "isolated"
        elif environment_text == "production":
            environment = "production"
        else:
            raise ValueError
        return FinancialScopeManifestReview(
            candidate_sha=_text(payload, "candidate_sha"),
            manifest_sha256=_text(payload, "manifest_sha256"),
            universe_sha256=_text(payload, "universe_sha256"),
            provider_identity_sha256=_text(payload, "provider_identity_sha256"),
            contract_sha256=_text(payload, "contract_sha256"),
            deployment_region=_text(payload, "deployment_region"),
            approval_id=_text(payload, "approval_id"),
            approved_by=_text(payload, "approved_by"),
            recorded_by=_text(payload, "recorded_by"),
            event_id=_text(payload, "event_id"),
            receipt_sha256=_text(payload, "approval_receipt_sha256"),
            role=role,
            environment=environment,
            report_sha256=_text(payload, "report_sha256"),
            approved_at=_datetime(payload, "approved_at"),
            expires_at=_datetime(payload, "expires_at"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, FinancialScopeDiscoveryError):
            raise
        raise FinancialScopeDiscoveryError(
            "FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID"
        ) from None


def _mapping(value: object) -> Mapping[str, object]:
    """Require one string-keyed JSON object."""

    if not isinstance(value, Mapping) or any(type(key) is not str for key in value):
        raise FinancialScopeDiscoveryError("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID")
    return value


def _text(payload: Mapping[str, object], name: str) -> str:
    """Read one canonical non-empty token without coercion."""

    value = payload.get(name)
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(name)
    return value


def _positive_int(payload: Mapping[str, object], name: str) -> int:
    """Read one positive integer, rejecting bool values."""

    value = payload.get(name)
    if type(value) is not int or value <= 0:
        raise ValueError(name)
    return value


def _datetime(payload: Mapping[str, object], name: str) -> datetime:
    """Parse one explicitly timezone-aware ISO timestamp."""

    value = _text(payload, name)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(name) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(name)
    return parsed


__all__ = [
    "parse_financial_scope_discovery_authorization",
    "parse_financial_scope_manifest_review",
]
