"""Fail-closed contract tests for provider-native scope manifest bootstrap."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from apps.data_center.application.egress_service import FinancialResponseAttemptBudget
from apps.data_center.application.financial_scope_manifest_bootstrap import (
    FinancialScopeDiscoveryUseCase,
    ScopeDiscoveryRequest,
)
from apps.data_center.domain.financial_scope_discovery import (
    FinancialScopeDiscoveryAuthorization,
    FinancialScopeDiscoveryBinding,
    FinancialScopeDiscoveryCapture,
    FinancialScopeDiscoveryError,
    FinancialScopeDiscoveryRow,
    FinancialScopeManifestReview,
)


def _binding() -> FinancialScopeDiscoveryBinding:
    return FinancialScopeDiscoveryBinding(
        candidate_sha="1" * 40,
        provider_id=3,
        provider_name="akshare",
        provider_identity_sha256="a" * 64,
        contract_id="akshare.financial-scope.latest-notice",
        contract_version="2026-10-09.v1",
        contract_sha256="b" * 64,
        parser_id="akshare.financial-scope-parser.v1",
        parser_sha256="c" * 64,
        deployment_region="isolated-test",
    )


def _authorization(
    assets: tuple[str, ...], *, expires_at: datetime | None = None
) -> FinancialScopeDiscoveryAuthorization:
    return FinancialScopeDiscoveryAuthorization.for_universe(
        binding=_binding(),
        asset_codes=assets,
        approval_id="discovery-owner-approval-1",
        approved_by="owner",
        recorded_by="operator",
        event_id="owner-event-1",
        receipt_sha256="d" * 64,
        approved_at=datetime(2026, 10, 9, 1, tzinfo=UTC),
        expires_at=expires_at or datetime(2026, 10, 9, 5, tzinfo=UTC),
        maximum_logical_requests=len(assets) * 2,
        maximum_rows_per_asset=200,
    )


def _capture(
    asset_code: str,
    *,
    rows: tuple[FinancialScopeDiscoveryRow, ...] | None = None,
    capture_index: int = 0,
) -> FinancialScopeDiscoveryCapture:
    binding = _binding()
    return FinancialScopeDiscoveryCapture(
        asset_code=asset_code,
        provider_id=binding.provider_id,
        provider_identity_sha256=binding.provider_identity_sha256,
        candidate_sha=binding.candidate_sha,
        contract_id=binding.contract_id,
        contract_version=binding.contract_version,
        contract_sha256=binding.contract_sha256,
        parser_id=binding.parser_id,
        parser_sha256=binding.parser_sha256,
        deployment_region=binding.deployment_region,
        capture_id=str(uuid4()),
        body_sha256=f"{capture_index + 1:064x}",
        raw_audit_id=100 + capture_index,
        dataset_key=(
            "equity.financial.fact" if capture_index % 2 == 0 else "equity.financial.source-time"
        ),
        response_completed_at=datetime(2026, 10, 8, 8 + capture_index, tzinfo=UTC),
        rows=rows
        or (
            FinancialScopeDiscoveryRow(
                asset_code=asset_code,
                period_end=date(2026, 6, 30),
                announcement_date=date(2026, 8, 30),
            ),
            FinancialScopeDiscoveryRow(
                asset_code=asset_code,
                period_end=date(2026, 3, 31),
                announcement_date=date(2026, 4, 25),
            ),
        ),
        physical_request_attempts=1,
    )


class _Reader:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failures: dict[str, str] = {}
        self.capture_overrides: dict[str, tuple[FinancialScopeDiscoveryCapture, ...]] = {}

    def preflight(self, *, binding: FinancialScopeDiscoveryBinding) -> None:
        assert binding == _binding()

    def capture_pair(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_code: str,
        maximum_rows: int,
        attempt_budget: FinancialResponseAttemptBudget,
    ) -> tuple[FinancialScopeDiscoveryCapture, FinancialScopeDiscoveryCapture]:
        assert binding == _binding()
        assert maximum_rows == 200
        self.calls.append(asset_code)
        assert attempt_budget.reserve() is True
        assert attempt_budget.reserve() is True
        if asset_code in self.failures:
            raise FinancialScopeDiscoveryError(self.failures[asset_code])
        captures = self.capture_overrides.get(
            asset_code,
            (_capture(asset_code, capture_index=0), _capture(asset_code, capture_index=1)),
        )
        return captures[0], captures[1]


class _AuthorizationSource:
    def __init__(self, authorization: FinancialScopeDiscoveryAuthorization | None) -> None:
        self.authorization = authorization
        self.calls = 0

    def get(
        self,
        *,
        binding: FinancialScopeDiscoveryBinding,
        asset_codes: tuple[str, ...],
        now: datetime,
    ) -> FinancialScopeDiscoveryAuthorization | None:
        self.calls += 1
        return self.authorization


class _UniverseSource:
    def __init__(
        self, values: tuple[str, ...], *, final_values: tuple[str, ...] | None = None
    ) -> None:
        self.values = values
        self.final_values = final_values
        self.reads = 0

    def get_active_asset_codes(self) -> tuple[str, ...]:
        self.reads += 1
        if self.reads > 1 and self.final_values is not None:
            return self.final_values
        return self.values


def _request(assets: tuple[str, ...]) -> ScopeDiscoveryRequest:
    return ScopeDiscoveryRequest(
        environment="isolated",
        asset_codes=assets,
        binding=_binding(),
        now=datetime(2026, 10, 9, 2, tzinfo=UTC),
    )


def test_discovers_dynamic_scope_from_two_provider_native_captures_per_asset() -> None:
    assets = ("000001.SZ", "430001.BJ", "600000.SH")
    reader = _Reader()

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.outcome == "success"
    assert result.candidate is not None
    assert result.candidate.asset_codes == assets
    assert result.candidate.coverage_count == len(assets)
    assert result.candidate.logical_request_count == 2 * len(assets)
    assert len(reader.calls) == len(assets)
    assert tuple(item.announcement_date for item in result.candidate.items) == (
        date(2026, 8, 30),
        date(2026, 8, 30),
        date(2026, 8, 30),
    )
    assert all(
        item.financial_body_sha256 != item.source_time_body_sha256
        for item in result.candidate.items
    )
    assert result.candidate.manifest_sha256 == result.candidate.calculate_sha256()


def test_requires_exact_owner_bound_request_budget_before_provider_access() -> None:
    assets = ("000001.SZ", "600000.SH")
    reader = _Reader()
    reader = _Reader()
    authorization = _authorization(("000001.SZ",))
    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(authorization),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.error_codes == ("FINANCIAL_SCOPE_DISCOVERY_AUTHORIZATION_INVALID",)
    assert reader.calls == []


def test_rejects_production_environment_before_provider_access() -> None:
    assets = ("000001.SZ",)
    reader = _Reader()

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(replace(_request(assets), environment="production"))

    assert result.error_codes == ("FINANCIAL_SCOPE_DISCOVERY_ENVIRONMENT_FORBIDDEN",)
    assert reader.calls == []


def test_rejects_universe_mismatch_before_provider_access() -> None:
    assets = ("000001.SZ", "600000.SH")
    reader = _Reader()

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(("000001.SZ",)),
    ).execute(_request(assets))

    assert result.outcome == "blocked"
    assert result.error_codes == ("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_DRIFT",)
    assert reader.calls == []


def test_rejects_universe_drift_after_provider_reads_without_candidate() -> None:
    assets = ("000001.SZ", "600000.SH")
    reader = _Reader()

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(
            assets,
            final_values=("000001.SZ", "600000.SH", "688001.SH"),
        ),
    ).execute(_request(assets))

    assert result.outcome == "blocked"
    assert result.candidate is None
    assert result.error_codes == ("FINANCIAL_SCOPE_DISCOVERY_UNIVERSE_DRIFT",)
    assert len(reader.calls) == len(assets)


def test_reports_all_missing_assets_and_provider_failures_in_one_result() -> None:
    assets = ("000001.SZ", "430001.BJ", "600000.SH")
    reader = _Reader()
    reader.failures = {
        "000001.SZ": "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
        "430001.BJ": "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
    }

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.outcome == "blocked"
    assert result.candidate is None
    assert result.missing_count == 2
    assert result.failed_capture_count == 2
    assert result.error_codes == (
        "FINANCIAL_SCOPE_DISCOVERY_COVERAGE_INCOMPLETE",
        "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED",
    )
    assert len(reader.calls) == len(assets)


def test_rejects_capture_pair_scope_drift_and_reports_conflicting_asset() -> None:
    assets = ("000001.SZ", "600000.SH")
    reader = _Reader()
    first = _capture("600000.SH", capture_index=0)
    conflicting = replace(
        _capture("600000.SH", capture_index=1),
        rows=(
            FinancialScopeDiscoveryRow(
                asset_code="600000.SH",
                period_end=date(2026, 6, 30),
                announcement_date=date(2026, 9, 1),
            ),
        ),
    )
    reader.capture_overrides["600000.SH"] = (first, conflicting)

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.outcome == "blocked"
    assert result.candidate is None
    assert result.conflict_count == 1
    assert "FINANCIAL_SCOPE_DISCOVERY_CAPTURE_CONFLICT" in result.error_codes


def test_rejects_duplicate_native_rows_and_reports_stats_without_partial_manifest() -> None:
    assets = ("000001.SZ",)
    reader = _Reader()
    duplicate = FinancialScopeDiscoveryRow(
        asset_code="000001.SZ",
        period_end=date(2026, 6, 30),
        announcement_date=date(2026, 8, 30),
    )
    reader.capture_overrides["000001.SZ"] = (
        _capture("000001.SZ", rows=(duplicate, duplicate), capture_index=0),
        _capture("000001.SZ", rows=(duplicate, duplicate), capture_index=1),
    )

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.outcome == "blocked"
    assert result.candidate is None
    assert result.duplicate_count == 1
    assert "FINANCIAL_SCOPE_DISCOVERY_DUPLICATE_NATIVE_ROW" in result.error_codes


def test_review_requires_independent_owner_and_reviewer_bound_to_exact_manifest() -> None:
    assets = ("000001.SZ",)
    candidate = (
        FinancialScopeDiscoveryUseCase(
            reader=_Reader(),
            authorization_source=_AuthorizationSource(_authorization(assets)),
            universe_source=_UniverseSource(assets),
        )
        .execute(_request(assets))
        .candidate
    )
    assert candidate is not None
    owner = FinancialScopeManifestReview(
        candidate_sha=candidate.binding.candidate_sha,
        manifest_sha256=candidate.manifest_sha256,
        universe_sha256=candidate.universe_sha256,
        provider_identity_sha256=candidate.binding.provider_identity_sha256,
        contract_sha256=candidate.binding.contract_sha256,
        deployment_region=candidate.binding.deployment_region,
        approval_id="owner-review-1",
        approved_by="data-owner",
        recorded_by="operator",
        event_id="event-owner-1",
        receipt_sha256="e" * 64,
        role="data_owner",
        environment="isolated",
        report_sha256="9" * 64,
        approved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        expires_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
    )
    reviewer = replace(
        owner,
        approval_id="reviewer-1",
        approved_by="independent-reviewer",
        event_id="event-reviewer-1",
        receipt_sha256="f" * 64,
        role="independent_reviewer",
    )

    reviewed = candidate.approve(
        owner=owner,
        reviewer=reviewer,
        environment="isolated",
        report_sha256="9" * 64,
        now=datetime(2026, 10, 9, 3, tzinfo=UTC),
    )

    assert reviewed.review_status == "approved"
    assert reviewed.owner_approval_id == owner.approval_id
    assert reviewed.reviewer_approval_id == reviewer.approval_id


@pytest.mark.parametrize(
    "bad_field",
    ("manifest_sha256", "universe_sha256", "deployment_region", "report_sha256", "environment"),
)
def test_manifest_review_rejects_stale_or_misbound_approval(bad_field: str) -> None:
    assets = ("000001.SZ",)
    candidate = (
        FinancialScopeDiscoveryUseCase(
            reader=_Reader(),
            authorization_source=_AuthorizationSource(_authorization(assets)),
            universe_source=_UniverseSource(assets),
        )
        .execute(_request(assets))
        .candidate
    )
    assert candidate is not None
    approval = FinancialScopeManifestReview(
        candidate_sha=candidate.binding.candidate_sha,
        manifest_sha256=candidate.manifest_sha256,
        universe_sha256=candidate.universe_sha256,
        provider_identity_sha256=candidate.binding.provider_identity_sha256,
        contract_sha256=candidate.binding.contract_sha256,
        deployment_region=candidate.binding.deployment_region,
        approval_id="review-1",
        approved_by="owner",
        recorded_by="operator",
        event_id="event-1",
        receipt_sha256="e" * 64,
        role="data_owner",
        environment="isolated",
        report_sha256="9" * 64,
        approved_at=datetime(2026, 10, 9, 2, tzinfo=UTC),
        expires_at=datetime(2026, 10, 10, 2, tzinfo=UTC),
    )
    approval = replace(
        approval,
        **{
            bad_field: (
                "production"
                if bad_field == "environment"
                else ("0" * 64 if bad_field != "deployment_region" else "other")
            )
        },
    )
    reviewer = replace(
        approval,
        approval_id="reviewer-1",
        approved_by="reviewer",
        event_id="reviewer-event-1",
        receipt_sha256="f" * 64,
        role="independent_reviewer",
    )

    with pytest.raises(FinancialScopeDiscoveryError) as caught:
        candidate.approve(
            owner=approval,
            reviewer=reviewer,
            environment="isolated",
            report_sha256="9" * 64,
            now=datetime(2026, 10, 9, 3, tzinfo=UTC),
        )

    assert caught.value.code == "FINANCIAL_SCOPE_DISCOVERY_APPROVAL_BINDING_INVALID"


def test_failed_bootstrap_never_returns_partial_candidate_for_zero_business_writes() -> None:
    assets = ("000001.SZ", "600000.SH")
    reader = _Reader()
    reader.failures["600000.SH"] = "FINANCIAL_SCOPE_DISCOVERY_PROVIDER_CAPTURE_FAILED"

    result = FinancialScopeDiscoveryUseCase(
        reader=reader,
        authorization_source=_AuthorizationSource(_authorization(assets)),
        universe_source=_UniverseSource(assets),
    ).execute(_request(assets))

    assert result.candidate is None
    assert result.missing_count == 1
    assert result.observed_count == 1
    assert result.fact_write_count == 0
    assert result.publication_write_count == 0
