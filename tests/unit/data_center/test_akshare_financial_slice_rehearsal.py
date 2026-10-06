"""Fake-provider contracts for the fresh S6 financial report producer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from apps.data_center import composition
from apps.data_center.application.financial_slice_sync import (
    FinancialSliceSyncBudget,
    FinancialSliceSyncResult,
)
from apps.data_center.domain.entities import ProviderConfig
from apps.data_center.domain.financial_source_time_contract import (
    FINANCIAL_FACT_DATASET_KEY,
    FINANCIAL_SOURCE_TIME_DATASET_KEY,
)
from apps.data_center.infrastructure import akshare_financial_slice_rehearsal as rehearsal
from apps.data_center.infrastructure.financial_source_time_matchers import (
    akshare_notice_date_match_contract,
)
from apps.data_center.infrastructure.rehearsal_identity import (
    RehearsalProviderIdentity,
    rehearsal_identities_digest,
)
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
