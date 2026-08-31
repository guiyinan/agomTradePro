"""Contracts for the provider-free historical DATA-02 simulator."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.data02_isolated_simulation import (
    Data02HistoricalDatabaseSnapshot,
    Data02HistoricalDatasetSnapshot,
    Data02HistoricalFactReference,
    Data02HistoricalPublicationSnapshot,
    Data02IsolatedSimulationCandidate,
    Data02IsolatedSimulationRequest,
    RunData02IsolatedSimulationUseCase,
    serialize_data02_isolated_simulation_report,
)

AS_OF = datetime(2026, 8, 29, 17, 15, 23, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 8, 31, 15, 0, tzinfo=UTC)
CANDIDATE = Data02IsolatedSimulationCandidate(
    commit="a" * 40,
    version="3.4.0",
    source_tree_sha256="b" * 64,
)
DATASET_TABLES = {
    "equity.financial.fact": "data_center_financial_fact",
    "equity.price.bar": "data_center_price_bar",
    "equity.quote.snapshot": "data_center_quote_snapshot",
    "equity.valuation.fact": "data_center_valuation_fact",
}


def _reference(
    natural_key: str,
    *,
    fact_pk: str,
    observed_at: datetime = AS_OF - timedelta(hours=1),
    quality_status: str = "accepted",
) -> Data02HistoricalFactReference:
    asset_code = natural_key.split(":", 1)[0]
    return Data02HistoricalFactReference(
        natural_key=natural_key,
        asset_code=asset_code,
        fact_table="data_center_quote_snapshot",
        fact_pk=fact_pk,
        source="historical-source",
        observed_at=observed_at,
        quality_status=quality_status,
    )


def _snapshot(
    *,
    facts: tuple[Data02HistoricalFactReference, ...],
    members: tuple[Data02HistoricalFactReference, ...],
    freshness_seconds: int | None = 172_800,
) -> Data02HistoricalDatabaseSnapshot:
    datasets: list[Data02HistoricalDatasetSnapshot] = []
    for dataset_key, fact_table in DATASET_TABLES.items():
        dataset_facts = (
            facts
            if dataset_key == "equity.quote.snapshot"
            else tuple(replace(reference, fact_table=fact_table) for reference in facts)
        )
        dataset_members = (
            members
            if dataset_key == "equity.quote.snapshot"
            else tuple(replace(reference, fact_table=fact_table) for reference in members)
        )
        datasets.append(
            Data02HistoricalDatasetSnapshot(
                dataset_key=dataset_key,
                fact_table=fact_table,
                fact_row_count=9,
                freshness_seconds=freshness_seconds,
                facts=dataset_facts,
                publication=Data02HistoricalPublicationSnapshot(
                    publication_id="11111111-1111-1111-1111-111111111111",
                    publication_hash="c" * 64,
                    state="published",
                    must_not_use_for_decision=False,
                    blocked_reason="",
                    members=dataset_members,
                ),
            )
        )
    return Data02HistoricalDatabaseSnapshot(
        database_name="agom_data02_sim_deadbeef",
        captured_at=CAPTURED_AT,
        transaction_read_only=True,
        data_center_migrations=("0071_syncexecutionidentitymodel",),
        universe_id="active_a_share",
        universe_codes=("000001.SZ", "600000.SH"),
        datasets=tuple(datasets),
    )


def _quote_dataset(payload: dict[str, object]) -> dict[str, object]:
    datasets = payload["datasets"]
    assert isinstance(datasets, list)
    return next(
        dataset
        for dataset in datasets
        if isinstance(dataset, dict) and dataset["dataset_key"] == "equity.quote.snapshot"
    )


class _SnapshotPort:
    def __init__(self, snapshot: Data02HistoricalDatabaseSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def collect(self) -> Data02HistoricalDatabaseSnapshot:
        self.calls += 1
        return self.snapshot


def _request() -> Data02IsolatedSimulationRequest:
    return Data02IsolatedSimulationRequest(
        candidate=CANDIDATE,
        dump_sha256="d" * 64,
        dump_size=146_743_609,
        dump_name="postgres-20260829T171523Z.dump",
        restored_database="agom_data02_sim_deadbeef",
        as_of=AS_OF,
    )


def test_report_is_candidate_bound_deterministic_and_never_production_ready() -> None:
    facts = (
        _reference("000001.SZ:2026-08-29T16:00:00+00:00:historical-source", fact_pk="1"),
        _reference("600000.SH:2026-08-29T16:00:00+00:00:historical-source", fact_pk="2"),
    )
    port = _SnapshotPort(_snapshot(facts=facts, members=facts))

    report = RunData02IsolatedSimulationUseCase(snapshot_port=port).execute(_request())
    payload = report.to_dict()

    assert port.calls == 1
    assert payload["schema_version"] == "data02-isolated-simulation.v1"
    assert payload["candidate"] == CANDIDATE.to_dict()
    assert payload["production_claim"] is False
    assert payload["production_ready"] is False
    assert payload["runtime_enablement"] == "not_authorized"
    assert payload["simulation_outcome"] == "completed"
    assert payload["historical_data_gate"] == "ALLOW"
    dataset = _quote_dataset(payload)
    assert dataset["source_only_count"] == 0
    assert dataset["target_only_count"] == 0
    assert dataset["exact_match_count"] == 2
    assert dataset["missing_asset_count"] == 0
    assert dataset["freshness_status"] == "fresh"
    assert dataset["max_age_seconds"] == 172_800
    assert len(payload["analysis_sha256"]) == 64
    assert serialize_data02_isolated_simulation_report(report) == (
        serialize_data02_isolated_simulation_report(report)
    )


def test_report_preserves_missing_reference_quality_and_future_blockers() -> None:
    source_a = _reference(
        "000001.SZ:2026-08-29T18:00:00+00:00:historical-source",
        fact_pk="1",
        observed_at=AS_OF + timedelta(minutes=45),
    )
    target_a = _reference(
        source_a.natural_key,
        fact_pk="99",
        observed_at=AS_OF - timedelta(hours=2),
        quality_status="degraded",
    )
    target_b = _reference(
        "600000.SH:2026-08-28T16:00:00+00:00:historical-source",
        fact_pk="2",
    )
    port = _SnapshotPort(_snapshot(facts=(source_a,), members=(target_a, target_b)))

    report = RunData02IsolatedSimulationUseCase(snapshot_port=port).execute(_request())
    dataset = _quote_dataset(report.to_dict())

    assert report.to_dict()["historical_data_gate"] == "DENY"
    assert dataset["missing_asset_count"] == 1
    assert dataset["future_observation_count"] == 1
    assert dataset["fact_reference_mismatch_count"] == 1
    assert dataset["timestamp_mismatch_count"] == 1
    assert dataset["quality_mismatch_count"] == 1
    assert dataset["target_only_count"] == 1


def test_use_case_rejects_database_substitution() -> None:
    facts = (_reference("000001.SZ:2026-08-29T16:00:00+00:00:historical-source", fact_pk="1"),)
    snapshot = _snapshot(facts=facts, members=facts)
    substituted = Data02HistoricalDatabaseSnapshot(
        database_name="agom_data02_sim_other",
        captured_at=snapshot.captured_at,
        transaction_read_only=True,
        data_center_migrations=snapshot.data_center_migrations,
        universe_id=snapshot.universe_id,
        universe_codes=snapshot.universe_codes,
        datasets=snapshot.datasets,
    )

    with pytest.raises(ValueError, match="database identity"):
        RunData02IsolatedSimulationUseCase(snapshot_port=_SnapshotPort(substituted)).execute(
            _request()
        )


def test_request_rejects_naive_time_and_invalid_candidate_identity() -> None:
    with pytest.raises(ValueError, match="as_of"):
        Data02IsolatedSimulationRequest(
            candidate=CANDIDATE,
            dump_sha256="d" * 64,
            dump_size=1,
            dump_name="postgres.dump",
            restored_database="agom_data02_sim_deadbeef",
            as_of=datetime(2026, 8, 29, 17, 15, 23),
        )

    with pytest.raises(ValueError, match="commit"):
        Data02IsolatedSimulationCandidate(
            commit="not-a-commit",
            version="3.4.0",
            source_tree_sha256="b" * 64,
        )


def test_report_denies_stale_or_unconfigured_freshness() -> None:
    stale = (
        _reference(
            "000001.SZ:2026-08-20T16:00:00+00:00:historical-source",
            fact_pk="1",
            observed_at=AS_OF - timedelta(days=9),
        ),
        _reference(
            "600000.SH:2026-08-20T16:00:00+00:00:historical-source",
            fact_pk="2",
            observed_at=AS_OF - timedelta(days=9),
        ),
    )

    stale_report = RunData02IsolatedSimulationUseCase(
        snapshot_port=_SnapshotPort(_snapshot(facts=stale, members=stale))
    ).execute(_request())
    stale_dataset = _quote_dataset(stale_report.to_dict())
    assert stale_report.to_dict()["historical_data_gate"] == "DENY"
    assert stale_dataset["freshness_status"] == "stale"
    assert stale_dataset["stale_observation_count"] == 2

    unconfigured_report = RunData02IsolatedSimulationUseCase(
        snapshot_port=_SnapshotPort(_snapshot(facts=stale, members=stale, freshness_seconds=None))
    ).execute(_request())
    assert _quote_dataset(unconfigured_report.to_dict())["freshness_status"] == "unverified"
