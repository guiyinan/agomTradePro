"""Build an owner-authorized scope-discovery record for one disposable S6 run."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from apps.data_center.application.financial_scope_discovery_governance import (
    parse_financial_scope_discovery_authorization,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    universe_sha256,
)

S6_PERSONAL_SYSTEM_RECORDER = "s6.personal-system-operator"
_AUTHORIZATION_SCHEMA = "data-center.financial-scope-discovery-authorization.v1"
_REQUESTS_PER_ASSET = 2
_PHYSICAL_ATTEMPTS_PER_REQUEST = 2
_MAXIMUM_ROWS_PER_ASSET = 200


def build_s6_personal_system_authorization_record(
    *,
    binding: FinancialScopeDiscoveryBinding,
    asset_codes: tuple[str, ...],
    approved_by: str,
    approval_id: str,
    event_id: str,
    approved_at: datetime,
    expires_at: datetime,
) -> tuple[FinancialScopeDiscoveryAuthorization, dict[str, object]]:
    """Build and parse one exact owner event with an explicit non-human recorder."""

    logical_requests = len(asset_codes) * _REQUESTS_PER_ASSET
    binding_payload: dict[str, object] = {
        "candidate_sha": binding.candidate_sha,
        "provider_id": binding.provider_id,
        "provider_name": binding.provider_name,
        "provider_identity_sha256": binding.provider_identity_sha256,
        "contract_id": binding.contract_id,
        "contract_version": binding.contract_version,
        "contract_sha256": binding.contract_sha256,
        "parser_id": binding.parser_id,
        "parser_sha256": binding.parser_sha256,
        "deployment_region": binding.deployment_region,
    }
    universe_payload: dict[str, object] = {
        "asset_count": len(asset_codes),
        "sha256": universe_sha256(asset_codes),
    }
    budget_payload: dict[str, object] = {
        "maximum_logical_requests": logical_requests,
        "maximum_physical_attempts": logical_requests * _PHYSICAL_ATTEMPTS_PER_REQUEST,
        "maximum_rows_per_asset": _MAXIMUM_ROWS_PER_ASSET,
    }
    intent: dict[str, object] = {
        "schema_version": _AUTHORIZATION_SCHEMA,
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approved_at": approved_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "approved": True,
        "recorded_by": S6_PERSONAL_SYSTEM_RECORDER,
        "event_id": event_id,
        "binding": binding_payload,
        "universe": universe_payload,
        "budget": budget_payload,
    }
    receipt_sha256 = hashlib.sha256(
        json.dumps(
            intent,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    payload = dict(intent)
    payload["approval_receipt_sha256"] = receipt_sha256
    authorization = parse_financial_scope_discovery_authorization(payload)
    authorization.validate(binding=binding, asset_codes=asset_codes, now=approved_at)
    return authorization, payload


__all__ = [
    "S6_PERSONAL_SYSTEM_RECORDER",
    "build_s6_personal_system_authorization_record",
]
