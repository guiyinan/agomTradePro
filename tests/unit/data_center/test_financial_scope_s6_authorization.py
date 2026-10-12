"""Contracts for the disposable S6 personal-system owner authorization builder."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.financial_scope_s6_authorization import (
    S6_PERSONAL_SYSTEM_RECORDER,
    build_s6_personal_system_authorization_record,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryError,
)


def _binding() -> FinancialScopeDiscoveryBinding:
    return FinancialScopeDiscoveryBinding(
        candidate_sha="a" * 40,
        provider_id=3,
        provider_name="akshare",
        provider_identity_sha256="b" * 64,
        contract_id="financial-contract",
        contract_version="v1",
        contract_sha256="c" * 64,
        parser_id="financial-parser",
        parser_sha256="d" * 64,
        deployment_region="unknown",
    )


def test_builder_binds_owner_universe_and_exact_request_ceiling() -> None:
    approved_at = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)

    authorization, payload = build_s6_personal_system_authorization_record(
        binding=_binding(),
        asset_codes=("000001.SZ", "600000.SH"),
        approved_by="admin",
        approval_id="s6-approval-1",
        event_id="s6-owner-event-1",
        approved_at=approved_at,
        expires_at=approved_at + timedelta(hours=1),
    )

    assert authorization.approved_by == "admin"
    assert authorization.recorded_by == S6_PERSONAL_SYSTEM_RECORDER
    assert authorization.maximum_logical_requests == 4
    assert authorization.maximum_physical_attempts == 8
    assert authorization.maximum_rows_per_asset == 200
    assert payload["approved"] is True
    assert payload["approval_receipt_sha256"] == authorization.receipt_sha256


def test_builder_rejects_owner_that_impersonates_operational_recorder() -> None:
    approved_at = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)

    with pytest.raises(
        FinancialScopeDiscoveryError,
        match="FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID",
    ):
        build_s6_personal_system_authorization_record(
            binding=_binding(),
            asset_codes=("000001.SZ",),
            approved_by=S6_PERSONAL_SYSTEM_RECORDER,
            approval_id="s6-approval-1",
            event_id="s6-owner-event-1",
            approved_at=approved_at,
            expires_at=approved_at + timedelta(hours=1),
        )
