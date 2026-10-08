"""Fake-provider contracts for the fresh S6 financial report producer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest

from apps.data_center import composition
from apps.data_center.application.financial_slice_sync import (
    FinancialSliceSyncBudget,
    FinancialSliceSyncResult,
)
from apps.data_center.domain.egress_routing import (
    EgressRequestContext,
    EgressRouteDecision,
    EgressRouteRule,
    EgressStrategy,
)
from apps.data_center.domain.entities import ProviderConfig, RawAudit
from apps.data_center.domain.financial_response_artifact import FinancialResponseArtifactRef
from apps.data_center.domain.financial_response_evidence import (
    FinancialRequestScope,
    FinancialResponseEvidence,
    FinancialResponseScope,
    FinancialResponseScopeBasis,
)
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.domain.financial_source_time_contract import (
    FINANCIAL_FACT_DATASET_KEY,
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
)
from apps.data_center.domain.financial_source_time_evidence import (
    FinancialSourceTimeArtifactRef,
    FinancialSourceTimeWitness,
)
from apps.data_center.infrastructure import akshare_financial_slice_rehearsal as rehearsal
from apps.data_center.infrastructure.financial_source_time_matchers import (
    akshare_notice_date_match_contract,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    rehearsal_identities_digest,
)
from core.exceptions import DataFetchError
from scripts import validate_release_rehearsal as release_validator


def _identities() -> tuple[RehearsalProviderIdentity, ...]:
    """Return a valid frozen identity set with an explicit financial route."""

    contract = akshare_notice_date_match_contract()
    return (
        RehearsalProviderIdentity("quote", 1, "tushare", "v1", "quote-route"),
        RehearsalProviderIdentity("valuation", 2, "tushare", "v1", "valuation-route"),
        RehearsalProviderIdentity(
            "akshare_financial_route:19",
            19,
            "akshare_financial",
            f"akshare-financial-v1-requests-2.32.5-contract-{contract.contract_sha256[:12]}",
            "akshare-financial-route-v1",
        ),
    )


def _verified_capture_pair() -> tuple[
    rehearsal._VerifiedFinancialFacts,
    RawAudit,
    RawAudit,
]:
    """Build one authenticated pair whose financial location is an opaque URI."""

    financial_capture_id = UUID("10000000-0000-4000-8000-000000000001")
    source_time_capture_id = UUID("20000000-0000-4000-8000-000000000002")
    response_body = b"financial-body"
    response_hash = hashlib.sha256(response_body).hexdigest()
    completed_at = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
    financial_reference = FinancialResponseArtifactRef(
        capture_id=financial_capture_id,
        location=f"financial-response:///v1/{financial_capture_id}.frb",
        evidence=FinancialResponseEvidence(
            body_sha256=response_hash,
            body_size_bytes=len(response_body),
            response_completed_at=completed_at,
            request_scope=FinancialRequestScope(
                provider_name="akshare",
                dataset_key=FINANCIAL_FACT_DATASET_KEY,
                asset_code="688266.SH",
                period_limit=8,
            ),
            response_scope=FinancialResponseScope(
                asset_codes=("688266.SH",),
                period_ends=(date(2026, 6, 30),),
                row_count=1,
            ),
            response_scope_basis=FinancialResponseScopeBasis.PROVIDER_BODY_VERIFIED,
        ),
        format_version="financial-response-body-fernet-v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    source_time_reference = FinancialSourceTimeArtifactRef(
        capture_id=source_time_capture_id,
        location=f"financial-source-time/v1/{source_time_capture_id}.bin",
        provider_name="akshare",
        dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
        requested_asset_code="688266.SH",
        requested_announcement_date=date(2026, 8, 1),
        body_sha256=response_hash,
        body_size_bytes=len(response_body),
        response_completed_at=completed_at,
        response_row_count=1,
        format_version="financial-source-time-artifact.v1",
        encryption_algorithm="fernet-aes128cbc-hmacsha256",
        encryption_key_ref="config/financial-key",
        encryption_key_version="v1",
    )
    verified = rehearsal._VerifiedFinancialFacts(
        facts=(cast(rehearsal.FinancialFactModel, SimpleNamespace()),),
        decision=cast(
            FinancialFactDecisionEvidence,
            SimpleNamespace(artifact_reference=financial_reference),
        ),
        source_time=cast(
            FinancialSourceTimeWitness,
            SimpleNamespace(artifact_reference=source_time_reference),
        ),
        verified_capture_ids=frozenset((financial_capture_id, source_time_capture_id)),
    )
    financial_audit = RawAudit(
        provider_name="akshare",
        capability="financial_fact",
        request_params={},
        status="ok",
        raw_audit_id="financial-audit",
        extra={"financial_response_artifact": {"provider_id": 19}},
    )
    source_time_audit = RawAudit(
        provider_name="akshare",
        capability="financial_source_time",
        request_params={},
        status="ok",
        raw_audit_id="source-time-audit",
        extra={"financial_source_time_artifact": {"provider_id": 19}},
    )
    return verified, financial_audit, source_time_audit


def test_capture_evidence_keeps_verified_artifact_locations_opaque(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A verified financial-response URI is never reinterpreted as a local path."""

    verified, financial_audit, source_time_audit = _verified_capture_pair()
    repository = SimpleNamespace(
        list_by_artifact_capture_id=lambda _capture_id: [financial_audit],
        list_by_source_time_artifact_capture_id=lambda _capture_id: [source_time_audit],
    )
    monkeypatch.setattr(rehearsal, "RawAuditRepository", lambda: repository)

    captures = rehearsal._capture_evidence(verified, provider_id=19)

    assert [capture["capture_id"] for capture in captures] == [
        "10000000-0000-4000-8000-000000000001",
        "20000000-0000-4000-8000-000000000002",
    ]


def test_capture_evidence_fails_closed_when_a_body_was_not_verified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Report production rejects a pair missing either body-store verification proof."""

    verified, financial_audit, source_time_audit = _verified_capture_pair()
    repository = SimpleNamespace(
        list_by_artifact_capture_id=lambda _capture_id: [financial_audit],
        list_by_source_time_artifact_capture_id=lambda _capture_id: [source_time_audit],
    )
    monkeypatch.setattr(rehearsal, "RawAuditRepository", lambda: repository)
    incomplete = replace(
        verified,
        verified_capture_ids=frozenset((verified.decision.artifact_reference.capture_id,)),
    )

    with pytest.raises(ValueError, match="REHEARSAL_FINANCIAL_SLICE_BODY_INVALID"):
        rehearsal._capture_evidence(incomplete, provider_id=19)


def test_seed_uses_available_at_as_untrusted_date_and_ignores_report_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legacy report date is never treated as the provider announcement date."""

    monkeypatch.setattr(rehearsal, "decode_financial_decision_evidence", lambda _value: None)
    monkeypatch.setattr(rehearsal, "source_evidence_from_model", lambda _row: None)
    available_at = datetime(2026, 9, 20, 18, 0, tzinfo=UTC)
    row = SimpleNamespace(
        asset_code="600000.SH",
        available_at=available_at,
        announced_at=None,
        report_date=date(1999, 1, 1),
        decision_evidence=None,
    )

    announcement_date, basis = rehearsal._seed_date(cast(rehearsal.FinancialFactModel, row))

    assert announcement_date == available_at.date()
    assert basis == "legacy_available_at_date_untrusted"


def test_provider_selection_uses_only_the_frozen_akshare_financial_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Tencent market-route identity cannot stand in for AKShare financial egress."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    filters: list[dict[str, object]] = []

    class _QuerySet:
        def order_by(self, *_fields: str) -> _QuerySet:
            return self

        def values_list(self, _field: str, *, flat: bool) -> tuple[int, ...]:
            assert flat is True
            return (19,)

    class _Manager:
        def filter(self, **kwargs: object) -> _QuerySet:
            filters.append(cast(dict[str, object], kwargs))
            return _QuerySet()

    class _Repository:
        def get_by_id(self, provider_id: int) -> ProviderConfig | None:
            return provider if provider_id == 19 else None

    monkeypatch.setattr(
        rehearsal,
        "ProviderConfigModel",
        SimpleNamespace(objects=_Manager()),
    )
    monkeypatch.setattr(composition, "get_provider_config_repository", lambda: _Repository())
    tencent_route = RehearsalProviderIdentity(
        "model_market_route:19", 19, "tencent", "tencent-v1", "tencent-route"
    )
    financial_route = _identities()[2]

    with pytest.raises(ValueError, match="REHEARSAL_FINANCIAL_SLICE_PROVIDER_IDENTITY_AMBIGUOUS"):
        rehearsal._select_provider((tencent_route,))
    assert filters == []

    selected_provider, selected_identity = rehearsal._select_provider(
        (tencent_route, financial_route)
    )

    assert selected_provider is provider
    assert selected_identity == financial_route
    assert filters == [{"pk": 19, "source_type": "akshare", "is_active": True}]


def test_financial_report_producer_emits_validator_compatible_fake_stage_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stage report binds N=1 counters, the route contract and official CI proofs."""

    identities = _identities()
    identity_digest = rehearsal_identities_digest(identities)
    identity_path = tmp_path / "provider-identities.json"
    identity_path.write_text(
        json.dumps([asdict(identity) for identity in identities]),
        encoding="utf-8",
    )
    provider = cast(ProviderConfig, SimpleNamespace(id=19, name="AKShare Financial"))
    route_identity = identities[-1]
    captures = [
        {
            "dataset_key": dataset,
            "capture_id": f"00000000-0000-4000-8000-{index:012d}",
            "raw_audit_id": str(index),
            "raw_audit_count": 1,
            "raw_audit_status": "ok",
            "raw_audit_provider_id": 19,
            "body_sha256": hashlib.sha256(dataset.encode()).hexdigest(),
            "raw_audit_body_sha256": hashlib.sha256(dataset.encode()).hexdigest(),
            "body_size_bytes": index,
            "typed_evidence_count": 3,
            "witness_coverage_count": 3,
        }
        for index, dataset in enumerate(
            (FINANCIAL_FACT_DATASET_KEY, FINANCIAL_SOURCE_TIME_DATASET_KEY),
            start=1,
        )
    ]
    failure_evidence: dict[str, object] = {
        "source": "candidate_regression_evidence",
        "failure_isolated_before_real_provider_egress": True,
        "zero_fact_write_test_cases": list(release_validator.FINANCIAL_ZERO_WRITE_PROOF_CASES),
        "junit_sha256": "f" * 64,
    }
    result = FinancialSliceSyncResult(
        outcome="success",
        source="akshare",
        provider_id=19,
        provider_name="AKShare Financial",
        requested=1,
        succeeded=1,
        failed=0,
        stored=3,
        planned_provider_requests=2,
        atomic_fact_write_count=1,
    )

    class _UseCase:
        def execute(self, request: object) -> FinancialSliceSyncResult:
            assert request.provider_id == 19
            assert request.source == "akshare"
            assert len(request.slices) == 1
            return result

    monkeypatch.setattr(rehearsal, "verify_configured_rehearsal_identities", lambda rows: rows)
    monkeypatch.setattr(
        rehearsal,
        "preflight_isolated_write_rehearsal",
        lambda **_kwargs: (
            "image_release_manifest",
            "sha256:" + "f" * 64,
            "a" * 64,
        ),
    )
    monkeypatch.setattr(rehearsal, "_verify_isolated_redis", lambda expected: expected)
    monkeypatch.setattr(
        rehearsal, "_verify_failure_evidence", lambda *_args, **_kwargs: failure_evidence
    )
    monkeypatch.setattr(
        rehearsal, "_select_provider", lambda _identities: (provider, route_identity)
    )
    monkeypatch.setattr(
        rehearsal,
        "_require_akshare_financial_egress_routes",
        lambda _provider: (
            {
                "dataset_key": FINANCIAL_FACT_DATASET_KEY,
                "rule_id": 10,
                "strategy": "direct",
                "matched_domain": "datacenter.eastmoney.com",
                "candidate_count": 1,
                "deployment_region": "unknown",
            },
            {
                "dataset_key": FINANCIAL_SOURCE_TIME_DATASET_KEY,
                "rule_id": 11,
                "strategy": "direct",
                "matched_domain": "datacenter.eastmoney.com",
                "candidate_count": 1,
                "deployment_region": "unknown",
            },
        ),
    )
    monkeypatch.setattr(
        rehearsal,
        "load_akshare_financial_slice_sync_budget",
        lambda: FinancialSliceSyncBudget(1, 2, 2, 200),
    )
    monkeypatch.setattr(
        rehearsal,
        "_select_request_seed",
        lambda **_kwargs: rehearsal._RequestSeed(
            "600000.SH",
            date(2026, 9, 23),
            "legacy_available_at_date_untrusted",
            "b" * 64,
            "c" * 64,
        ),
    )
    monkeypatch.setattr(
        rehearsal, "make_sync_akshare_financial_slices_use_case", lambda **_kwargs: _UseCase()
    )
    monkeypatch.setattr(
        rehearsal,
        "_verify_persisted_pair",
        lambda **_kwargs: SimpleNamespace(facts=(object(), object(), object())),
    )
    monkeypatch.setattr(rehearsal, "_capture_evidence", lambda *_args, **_kwargs: captures)
    output_dir = tmp_path / "output"

    report = rehearsal.collect_akshare_financial_slice_rehearsal(
        candidate_sha="a" * 40,
        target_trade_date=date(2026, 9, 24),
        universe_sha256="d" * 64,
        provider_identities_sha256=identity_digest,
        provider_identities_path=identity_path,
        expected_database_name="agom_release_rehearsal_test01",
        expected_database_host="agom-s6-postgres-test-01",
        expected_redis_host="agom-s6-redis-test-01",
        candidate_regression_evidence_path=tmp_path / "candidate-regression.json",
        output_dir=output_dir,
    )
    regression_report: dict[str, object] = {
        "required_tests": list(release_validator.FINANCIAL_ZERO_WRITE_PROOF_CASES),
        "junit_artifacts": [
            {
                "path": "financial-slice-sync-contracts.xml",
                "sha256": "f" * 64,
            }
        ],
    }

    release_validator._validate_akshare_financial_slice(
        report,
        regression_report=regression_report,
        expected_date="2026-09-24",
    )
    saved_report = json.loads((output_dir / "akshare-financial-slice.json").read_text())
    assert saved_report == report


def test_financial_route_preflight_requires_both_registered_datasets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real-provider stage stops before egress when either exact route is absent."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    seen: list[str] = []

    def preview(context: EgressRequestContext) -> EgressRouteDecision:
        dataset_key = context.dataset_key
        seen.append(dataset_key)
        return EgressRouteDecision(
            rule_id=91 if dataset_key == FINANCIAL_FACT_DATASET_KEY else None,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason=(
                "matched_rule" if dataset_key == FINANCIAL_FACT_DATASET_KEY else "no_matching_rule"
            ),
            matched_domain=(
                "datacenter.eastmoney.com" if dataset_key == FINANCIAL_FACT_DATASET_KEY else None
            ),
        )

    monkeypatch.setattr(rehearsal, "preview_route", preview)
    monkeypatch.setattr(
        rehearsal,
        "list_rules",
        lambda: (
            EgressRouteRule(
                rule_id=91,
                provider_id=19,
                dataset_key=FINANCIAL_FACT_DATASET_KEY,
                domain_pattern="datacenter.eastmoney.com",
                deployment_region="unknown",
                strategy=EgressStrategy.DIRECT,
                fixed_egress_id=None,
                priority=1,
                enabled=True,
            ),
        ),
    )
    monkeypatch.setattr(rehearsal, "akshare_financial_deployment_region", lambda: "unknown")

    with pytest.raises(DataFetchError) as caught:
        rehearsal._require_akshare_financial_egress_routes(provider)

    assert caught.value.code == "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED"
    assert seen == [FINANCIAL_FACT_DATASET_KEY, FINANCIAL_SOURCE_TIME_DATASET_KEY]


def _exact_financial_egress_rules(
    *, provider_id: int = 19, deployment_region: str = "isolated-test"
) -> tuple[EgressRouteRule, EgressRouteRule]:
    """Build both persisted exact-host financial routes for rehearsal tests."""

    return (
        EgressRouteRule(
            rule_id=91,
            provider_id=provider_id,
            dataset_key=FINANCIAL_FACT_DATASET_KEY,
            domain_pattern="datacenter.eastmoney.com",
            deployment_region=deployment_region,
            strategy=EgressStrategy.DIRECT,
            fixed_egress_id=None,
            priority=1,
            enabled=True,
        ),
        EgressRouteRule(
            rule_id=92,
            provider_id=provider_id,
            dataset_key=FINANCIAL_SOURCE_TIME_DATASET_KEY,
            domain_pattern="datacenter.eastmoney.com",
            deployment_region=deployment_region,
            strategy=EgressStrategy.DIRECT,
            fixed_egress_id=None,
            priority=1,
            enabled=True,
        ),
    )


def test_financial_route_preflight_accepts_exact_persisted_route_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The route evidence binds provider, dataset, host, and deployment region."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    rules = _exact_financial_egress_rules()
    contexts: list[EgressRequestContext] = []

    def preview(context: EgressRequestContext) -> EgressRouteDecision:
        contexts.append(context)
        rule = next(rule for rule in rules if rule.dataset_key == context.dataset_key)
        return EgressRouteDecision(
            rule_id=rule.rule_id,
            strategy=rule.strategy,
            candidates=(None,),
            reason="matched_rule",
            matched_domain="datacenter.eastmoney.com",
        )

    monkeypatch.setattr(rehearsal, "list_rules", lambda: rules)
    monkeypatch.setattr(rehearsal, "preview_route", preview)

    evidence = rehearsal.require_akshare_financial_egress_routes(
        provider,
        deployment_region="isolated-test",
    )

    assert tuple(item["rule_id"] for item in evidence) == (91, 92)
    assert tuple(context.dataset_key for context in contexts) == (
        FINANCIAL_FACT_DATASET_KEY,
        FINANCIAL_SOURCE_TIME_DATASET_KEY,
    )
    assert all(context.provider_id == 19 for context in contexts)
    assert all(context.deployment_region == "isolated-test" for context in contexts)
    assert all("datacenter.eastmoney.com" in context.target_url for context in contexts)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_id", 20),
        ("dataset_key", "*"),
        ("domain_pattern", "*.eastmoney.com"),
        ("domain_pattern", "other.example.test"),
        ("deployment_region", "*"),
        ("deployment_region", "other-region"),
        ("enabled", False),
    ),
)
def test_financial_route_preflight_rejects_non_exact_persisted_rule_dimensions(
    field: str,
    value: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wildcard or mismatched persisted dimensions cannot satisfy a financial route."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    exact_rules = list(_exact_financial_egress_rules())
    exact_rules[0] = replace(exact_rules[0], **{field: value})
    rules = tuple(exact_rules)

    def preview(context: EgressRequestContext) -> EgressRouteDecision:
        return EgressRouteDecision(
            rule_id=91 if context.dataset_key == FINANCIAL_FACT_DATASET_KEY else 92,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason="matched_rule",
            matched_domain="datacenter.eastmoney.com",
        )

    monkeypatch.setattr(rehearsal, "list_rules", lambda: rules)
    monkeypatch.setattr(rehearsal, "preview_route", preview)

    with pytest.raises(DataFetchError) as caught:
        rehearsal.require_akshare_financial_egress_routes(
            provider,
            deployment_region="isolated-test",
        )

    assert caught.value.code == "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED"


def test_financial_route_preflight_rejects_preview_without_persisted_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful-looking preview cannot substitute for the persistent route row."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    monkeypatch.setattr(rehearsal, "list_rules", lambda: ())
    monkeypatch.setattr(
        rehearsal,
        "preview_route",
        lambda _context: EgressRouteDecision(
            rule_id=91,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason="matched_rule",
            matched_domain="datacenter.eastmoney.com",
        ),
    )

    with pytest.raises(DataFetchError) as caught:
        rehearsal.require_akshare_financial_egress_routes(
            provider,
            deployment_region="isolated-test",
        )

    assert caught.value.code == "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED"


def test_financial_route_preflight_fails_closed_when_both_routes_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Multiple missing route dimensions still produce one stable blocker."""

    provider = ProviderConfig(
        id=19,
        name="AKShare Financial",
        source_type="akshare",
        is_active=True,
        priority=1,
        api_key="",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    contexts: list[EgressRequestContext] = []
    monkeypatch.setattr(rehearsal, "list_rules", lambda: ())
    monkeypatch.setattr(
        rehearsal,
        "preview_route",
        lambda context: contexts.append(context)
        or EgressRouteDecision(
            rule_id=None,
            strategy=EgressStrategy.DIRECT,
            candidates=(None,),
            reason="no_matching_rule",
        ),
    )

    with pytest.raises(DataFetchError) as caught:
        rehearsal.require_akshare_financial_egress_routes(
            provider,
            deployment_region="isolated-test",
        )

    assert caught.value.code == "REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED"
    assert tuple(context.dataset_key for context in contexts) == (FINANCIAL_FACT_DATASET_KEY,)


@pytest.mark.parametrize(
    ("failure_reason", "expected_code"),
    (
        (
            "owner_approved_capture_capability_unavailable",
            "REHEARSAL_FINANCIAL_SLICE_CAPTURE_UNAVAILABLE",
        ),
        (
            "akshare_provider_or_capture_failed",
            "REHEARSAL_FINANCIAL_SLICE_PROVIDER_OR_CAPTURE_FAILED",
        ),
        ("unknown_failure", "REHEARSAL_FINANCIAL_SLICE_SYNC_INVALID"),
    ),
)
def test_financial_sync_failure_keeps_a_stable_rehearsal_code(
    failure_reason: str,
    expected_code: str,
) -> None:
    """Safe business failures remain distinguishable at the S6 command boundary."""

    result = FinancialSliceSyncResult(
        outcome="blocked",
        source="akshare",
        provider_id=19,
        provider_name="AKShare Financial",
        requested=1,
        succeeded=0,
        failed=1,
        stored=0,
        planned_provider_requests=2,
        atomic_fact_write_count=0,
        failure_reason=failure_reason,
    )

    with pytest.raises(DataFetchError) as caught:
        rehearsal._require_successful_sync(result, 19)

    assert caught.value.code == expected_code
