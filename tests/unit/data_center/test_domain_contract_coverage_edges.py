"""Failure-path coverage for provider-neutral Data Center domain contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest

from apps.data_center.domain import control_plane as control_plane_contracts
from apps.data_center.domain.contracts import (
    DataEnvelope,
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    FetchOutcome,
    FetchResult,
    NaturalKey,
    ObservationTime,
    ProviderBinding,
    PublicationDecision,
    PublicationPolicy,
    PublicationState,
    QualityAssessment,
    SourceEvidence,
    SyncOutcome,
)
from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationMember,
    PublicationRollback,
    QuarantineRecord,
    QuarantineResolution,
    SyncBatch,
    SyncCheckpoint,
    SyncItemState,
    SyncRun,
    SyncRunStatus,
)
from apps.data_center.domain.market_structure import (
    ActorStructureMetrics,
    MarketStructureAggregationPolicy,
    MarketStructureObservation,
    MarketStructurePeriodCalendar,
    MarketStructurePeriodCalendarRef,
    MarketStructureResearchRequest,
    MarketStructureSeriesDefinition,
    MarketStructureSeriesRef,
    MarketStructureSnapshot,
    PITMembershipSnapshot,
    SeriesPeriodCoverage,
    validate_series_against_flow_definition,
)
from apps.data_center.domain.market_structure_governance import (
    EmpiricalPercentileMethod,
    InvestorActorDefinition,
    MarketStructureMeasureConcept,
    MarketStructureResearchStatus,
    VersionedEvidenceReference,
)
from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.domain.research_data_foundation import (
    InvestorFlowDefinition,
    InvestorFlowMeasureKind,
)
from apps.data_center.domain.retention import (
    ArchiveArtifact,
    ArchiveManifest,
    ArchiveMember,
    ArchiveRestoreAudit,
    ArchiveRestoreOutcome,
    ArchiveState,
    RetentionMemberExecution,
    RetentionPlan,
    RetentionPlanDecision,
    RetentionPlanMember,
    RetentionPlanStatus,
    RetentionPolicy,
    RetentionRun,
    StorageHold,
    retention_plan_snapshot_digest,
)
from shared.domain.reliability import ReliabilityContract

NOW = datetime(2026, 8, 8, tzinfo=UTC)
DATASET = DatasetKey("equity.daily", "1.0", "1.0")
NATURAL_KEY = NaturalKey((("asset_code", "000001.SZ"),))
OBSERVATION = ObservationTime(NOW, NOW, NOW, NOW)
EVIDENCE = SourceEvidence.from_payload(
    source="test",
    source_capability="daily",
    payload={"close": 10},
)
GOOD_QUALITY = QualityAssessment(True, 1.0, True, True)
BAD_QUALITY = QualityAssessment(False, 0.0, False, False, issues=("invalid",))
FRESH = ReliabilityContract.fresh(observed_at=NOW, fetched_at=NOW, source="test")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"value": "", "contract_version": "1", "schema_version": "1"},
        {"value": "dataset", "contract_version": "", "schema_version": "1"},
        {"value": "dataset", "contract_version": "1", "schema_version": ""},
        {"value": "bad key", "contract_version": "1", "schema_version": "1"},
    ],
)
def test_dataset_key_rejects_invalid_identity(kwargs: dict[str, str]) -> None:
    with pytest.raises(ValueError):
        DatasetKey(**kwargs)


def test_natural_key_and_observation_time_reject_invalid_shapes() -> None:
    for values in ((), (("asset", "1"), ("asset", "2")), (("", "1"),)):
        with pytest.raises(ValueError):
            NaturalKey(values)

    valid = ObservationTime(NOW, NOW, NOW, NOW)
    for overrides in (
        {"fetched_at": datetime(2026, 8, 8)},
        {"observed_at": datetime(2026, 8, 8)},
        {"published_at": datetime(2026, 8, 8)},
        {"available_at": datetime(2026, 8, 8)},
        {"observed_at": NOW + timedelta(seconds=1)},
        {"published_at": NOW, "available_at": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            replace(valid, **overrides)


def test_source_evidence_and_quality_reject_invalid_evidence() -> None:
    for kwargs in (
        {"source": "", "source_capability": "daily", "payload_hash": "a" * 16},
        {"source": "test", "source_capability": "", "payload_hash": "a" * 16},
        {"source": "test", "source_capability": "daily", "payload_hash": "short"},
        {"source": "test", "source_capability": "daily", "payload_hash": "a" * 15 + " "},
        {
            "source": "test",
            "source_capability": "daily",
            "payload_hash": "a" * 16,
            "raw_audit_id": "",
        },
    ):
        with pytest.raises(ValueError):
            SourceEvidence(**kwargs)

    for kwargs in (
        {
            "schema_valid": True,
            "completeness_ratio": -0.1,
            "unit_valid": True,
            "natural_key_valid": True,
        },
        {
            "schema_valid": True,
            "completeness_ratio": 1.0,
            "unit_valid": True,
            "natural_key_valid": True,
            "issues": ("",),
        },
    ):
        with pytest.raises(ValueError):
            QualityAssessment(**kwargs)
    assert not QualityAssessment(True, 1.0, True, True, conflict=True).is_acceptable


def test_data_envelope_rejects_unsafe_publication_shapes() -> None:
    envelope = DataEnvelope(
        dataset=DATASET,
        natural_key=NATURAL_KEY,
        value=10,
        observation=OBSERVATION,
        evidence=EVIDENCE,
        quality=GOOD_QUALITY,
        reliability=FRESH,
    )
    for overrides in (
        {"unit": ""},
        {"original_unit": ""},
        {"is_current": True},
        {"quality": BAD_QUALITY},
        {"value": None},
    ):
        with pytest.raises(ValueError):
            replace(envelope, **overrides)
    assert envelope.to_dict()["observed_at"] == NOW.isoformat()


def test_fetch_result_rejects_incoherent_outcomes() -> None:
    result = FetchResult(
        outcome=FetchOutcome.SUCCESS,
        values=(10,),
        provider="test",
        dataset=DATASET,
        evidence=EVIDENCE,
        reliability=FRESH,
        quality=GOOD_QUALITY,
    )
    assert result.acceptable
    for overrides in (
        {"provider": ""},
        {"values": ()},
        {"outcome": FetchOutcome.FAILED, "values": (), "evidence": None},
        {"evidence": None},
    ):
        with pytest.raises(ValueError):
            replace(result, **overrides)
    assert not replace(result, quality=BAD_QUALITY).acceptable


def test_publication_decision_and_sync_outcome_reject_invalid_counts() -> None:
    decision = PublicationDecision(
        publication_id="publication-1",
        dataset=DATASET,
        state=PublicationState.DRAFT,
        selected_source=None,
        selected_member_hash=None,
        coverage_ratio=0.0,
        conflict_count=0,
    )
    for overrides in (
        {"publication_id": ""},
        {"coverage_ratio": 1.1},
        {"conflict_count": -1},
        {"state": PublicationState.PUBLISHED},
    ):
        with pytest.raises(ValueError):
            replace(decision, **overrides)

    outcome = SyncOutcome(FetchOutcome.PARTIAL, 2, 1, 1, 1, "run-1")
    for overrides in (
        {"run_id": ""},
        {"requested": -1},
        {"requested": 1, "succeeded": 1, "failed": 1},
        {"stored": 2},
        {"outcome": FetchOutcome.SUCCESS, "stored": 0},
    ):
        with pytest.raises(ValueError):
            replace(outcome, **overrides)


def test_catalog_contracts_reject_invalid_governance_metadata() -> None:
    field = DatasetFieldContract("close", "decimal", "元", False, True)
    for overrides in (
        {"name": ""},
        {"value_type": ""},
        {"minimum": 2.0, "maximum": 1.0},
    ):
        with pytest.raises(ValueError):
            replace(field, **overrides)

    contract = DatasetContract(DATASET, "data_center", "daily", True, (field,))
    for overrides in (
        {"owner": ""},
        {"frequency": ""},
        {"fields": ()},
        {"freshness_seconds": 0},
    ):
        with pytest.raises(ValueError):
            replace(contract, **overrides)

    registration = DataOwnerRegistration("equity.daily", "platform", "equity", "risk")
    for name in ("dataset_key", "data_platform_owner", "business_owner", "acceptance_owner"):
        with pytest.raises(ValueError):
            replace(registration, **{name: ""})

    binding = ProviderBinding(DATASET, "tushare", "daily", 1, 60, "daily-v1")
    for overrides in (
        {"provider": ""},
        {"capability": ""},
        {"priority": -1},
        {"freshness_seconds": 0},
        {"validator_key": ""},
    ):
        with pytest.raises(ValueError):
            replace(binding, **overrides)

    policy = PublicationPolicy(DATASET, 1.0, False, "block", ("checksum",), 30)
    for overrides in (
        {"minimum_coverage_ratio": 1.1},
        {"conflict_action": "ignore"},
        {"required_evidence": ()},
        {"retention_days": 0},
    ):
        with pytest.raises(ValueError):
            replace(policy, **overrides)


def test_publication_fact_reference_rejects_invalid_identity_and_time() -> None:
    reference = PublicationFactReference("natural", "source", "record", "facts", "1", NOW)
    for name in ("natural_key", "source", "source_record_id", "fact_table", "fact_pk"):
        with pytest.raises(ValueError):
            replace(reference, **{name: ""})
    for overrides in ({"observed_at": datetime(2026, 8, 8)}, {"revision_number": 0}):
        with pytest.raises(ValueError):
            replace(reference, **overrides)


def test_sync_run_rejects_invalid_lifecycle_evidence() -> None:
    run = SyncRun("run-1", "equity.daily", "manual", started_at=NOW)
    for overrides in (
        {"run_id": ""},
        {"dataset_key": ""},
        {"trigger": ""},
        {"started_at": datetime(2026, 8, 8)},
        {"finished_at": datetime(2026, 8, 8)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"requested": -1},
        {"outcome": "unknown"},
        {"outcome": "success"},
        {"status": SyncRunStatus.BLOCKED},
    ):
        with pytest.raises(ValueError):
            replace(run, **overrides)
    finished = replace(run, stored=1).finish(
        status=SyncRunStatus.STORED,
        outcome="success",
        finished_at=NOW,
    )
    assert finished.finished_at == NOW


def test_sync_batch_and_checkpoint_reject_invalid_boundaries() -> None:
    batch = SyncBatch("batch-1", "run-1", "equity.daily", "test", "idempotent")
    for name in ("batch_id", "run_id", "dataset_key", "provider_name", "idempotency_key"):
        with pytest.raises(ValueError):
            replace(batch, **{name: ""})
    for overrides in (
        {"window_start": date(2026, 8, 8), "window_end": date(2026, 8, 7)},
        {"requested": -1},
        {"started_at": datetime(2026, 8, 8)},
        {"finished_at": datetime(2026, 8, 8)},
        {"started_at": NOW, "finished_at": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            replace(batch, **overrides)

    checkpoint = SyncCheckpoint(
        "checkpoint-1", "run-1", "batch-1", "date", "20260808", recorded_at=NOW
    )
    for name in ("checkpoint_id", "run_id", "batch_id", "cursor_name", "cursor_value"):
        with pytest.raises(ValueError):
            replace(checkpoint, **{name: ""})
    for overrides in (
        {"recorded_at": datetime(2026, 8, 8)},
        {"processed": -1},
        {"failed": -1},
        {"state": SyncItemState.FAILED},
    ):
        with pytest.raises(ValueError):
            replace(checkpoint, **overrides)


def test_quarantine_coverage_and_publication_reject_invalid_state() -> None:
    quarantine = QuarantineRecord(
        "quarantine-1",
        "equity.daily",
        "test",
        "natural",
        "invalid",
        "invalid payload",
        "hash",
        "schema",
        {},
        quarantined_at=NOW,
    )
    for name in (
        "quarantine_id",
        "dataset_key",
        "provider_name",
        "natural_key",
        "reason_code",
        "reason",
        "payload_hash",
        "schema_fingerprint",
    ):
        with pytest.raises(ValueError):
            replace(quarantine, **{name: ""})
    for overrides in (
        {"quarantined_at": datetime(2026, 8, 8)},
        {"observed_at": datetime(2026, 8, 8)},
        {"resolved_at": datetime(2026, 8, 8)},
        {"resolved_at": NOW - timedelta(seconds=1)},
        {"resolution": QuarantineResolution.ACCEPTED},
    ):
        with pytest.raises(ValueError):
            replace(quarantine, **overrides)
    resolved_quarantine = replace(
        quarantine,
        resolution=QuarantineResolution.ACCEPTED,
        resolved_at=NOW + timedelta(seconds=1),
        resolved_by="reviewer",
    )
    assert resolved_quarantine.resolved_at > resolved_quarantine.quarantined_at

    coverage = CoverageSnapshot("coverage-1", "publication-1", 2, 2, 1, generated_at=NOW)
    assert coverage.coverage_ratio == 0.5
    for overrides in (
        {"requested_count": -1},
        {"selected_count": 3},
        {"requested_count": 1, "eligible_count": 2},
        {"generated_at": datetime(2026, 8, 8)},
    ):
        with pytest.raises(ValueError):
            replace(coverage, **overrides)

    publication = CanonicalPublication(
        "publication-1",
        "equity.daily",
        "current",
        "v1",
        control_plane_contracts.PublicationState.CANDIDATE,
        "",
        "hash",
        coverage,
    )
    for name in (
        "publication_id",
        "dataset_key",
        "publication_key",
        "policy_version",
        "publication_hash",
    ):
        with pytest.raises(ValueError):
            replace(publication, **{name: ""})
    for overrides in (
        {"member_count": -1},
        {"conflict_count": -1},
        {"as_of": datetime(2026, 8, 8)},
        {"published_at": datetime(2026, 8, 8)},
        {"superseded_at": datetime(2026, 8, 8)},
        {"reinstated_at": datetime(2026, 8, 8)},
        {"state": control_plane_contracts.PublicationState.PUBLISHED},
        {
            "state": control_plane_contracts.PublicationState.PUBLISHED,
            "selected_source": "test",
            "published_at": NOW,
            "must_not_use_for_decision": True,
            "member_count": 1,
        },
        {"state": control_plane_contracts.PublicationState.BLOCKED},
    ):
        with pytest.raises(ValueError):
            replace(publication, **overrides)


def test_publication_member_and_rollback_reject_invalid_evidence() -> None:
    member = PublicationMember(
        "member-1",
        "publication-1",
        "equity.daily",
        "natural",
        "test",
        "record",
        "facts",
        "1",
        NOW,
    )
    for name in (
        "member_id",
        "publication_id",
        "dataset_key",
        "natural_key",
        "source",
        "source_record_id",
        "fact_table",
        "fact_pk",
    ):
        with pytest.raises(ValueError):
            replace(member, **{name: ""})
    for overrides in ({"observed_at": datetime(2026, 8, 8)}, {"revision_number": 0}):
        with pytest.raises(ValueError):
            replace(member, **overrides)

    rollback = PublicationRollback("publication-1", "restore", "operator", NOW)
    for name in ("target_publication_id", "reason", "operator"):
        with pytest.raises(ValueError):
            replace(rollback, **{name: ""})
    with pytest.raises(ValueError):
        replace(rollback, observed_at=datetime(2026, 8, 8))


def test_retention_policy_hold_and_manifest_reject_invalid_boundaries() -> None:
    policy = RetentionPolicy("policy-1", "equity.daily", 1, 30, 10, 60)
    for overrides in (
        {"policy_id": ""},
        {"retention_days": 0},
        {"archive_after_days": 0},
        {"archive_after_days": 31},
        {"archive_retention_days": 30},
    ):
        with pytest.raises(ValueError):
            replace(policy, **overrides)

    hold = StorageHold("hold-1", "dataset", "equity.daily", "audit", "operator", NOW)
    for overrides in (
        {"hold_id": ""},
        {"created_at": datetime(2026, 8, 8)},
        {"expires_at": datetime(2026, 8, 9)},
        {"released_at": datetime(2026, 8, 9)},
        {"expires_at": NOW - timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            replace(hold, **overrides)

    manifest = ArchiveManifest(
        "archive-1", "equity.daily", 1, 10, "s3://archive", "checksum", created_at=NOW
    )
    for overrides in (
        {"archive_id": ""},
        {"object_count": -1},
        {"created_at": datetime(2026, 8, 8)},
        {"verified_at": datetime(2026, 8, 8)},
        {"retention_until": datetime(2026, 8, 8)},
        {"coverage_started_at": datetime(2026, 8, 8)},
        {"last_restored_at": datetime(2026, 8, 8)},
        {"coverage_started_at": NOW, "coverage_ended_at": NOW - timedelta(seconds=1)},
        {"state": ArchiveState.VERIFIED},
        {"restore_outcome": ArchiveRestoreOutcome.SUCCESS},
    ):
        with pytest.raises(ValueError):
            replace(manifest, **overrides)


def test_archive_member_artifact_and_restore_audit_reject_invalid_evidence() -> None:
    first = ArchiveMember("payload-1", "hash-1", "digest-1", "schema-1", NOW, 10)
    second = ArchiveMember(
        "payload-2",
        "hash-2",
        "digest-2",
        "schema-2",
        NOW + timedelta(seconds=1),
        20,
    )
    for overrides in (
        {"payload_id": ""},
        {"fetched_at": datetime(2026, 8, 8)},
        {"size_bytes": -1},
    ):
        with pytest.raises(ValueError):
            replace(first, **overrides)

    artifact = ArchiveArtifact(
        "archive-1",
        "equity.daily",
        "v1",
        "v1",
        "jsonl",
        "aes",
        "key",
        "1",
        "s3://archive",
        "checksum",
        2,
        30,
        NOW,
        first.fetched_at,
        second.fetched_at,
        (first, second),
    )
    for overrides in (
        {"archive_id": ""},
        {"object_count": 0},
        {"size_bytes": 0},
        {"created_at": datetime(2026, 8, 8)},
        {"coverage_started_at": datetime(2026, 8, 8)},
        {"coverage_ended_at": datetime(2026, 8, 8)},
        {"coverage_started_at": second.fetched_at, "coverage_ended_at": first.fetched_at},
        {"members": (first, replace(second, payload_id=first.payload_id))},
        {"coverage_started_at": first.fetched_at - timedelta(seconds=1)},
        {"coverage_ended_at": second.fetched_at + timedelta(seconds=1)},
    ):
        with pytest.raises(ValueError):
            replace(artifact, **overrides)

    manifest = ArchiveManifest(
        artifact.archive_id,
        artifact.dataset_key,
        artifact.object_count,
        artifact.size_bytes,
        artifact.location,
        artifact.checksum,
        created_at=artifact.created_at,
        contract_version=artifact.contract_version,
        schema_version=artifact.schema_version,
        format_version=artifact.format_version,
        encryption_algorithm=artifact.encryption_algorithm,
        encryption_key_ref=artifact.encryption_key_ref,
        encryption_key_version=artifact.encryption_key_version,
        coverage_started_at=artifact.coverage_started_at,
        coverage_ended_at=artifact.coverage_ended_at,
    )
    assert artifact.matches_manifest(manifest, artifact.members)
    assert not artifact.matches_manifest(replace(manifest, checksum="different"), artifact.members)

    audit = ArchiveRestoreAudit(
        "audit-1",
        "operation-1",
        "archive-1",
        ArchiveRestoreOutcome.FAILED,
        "",
        0,
        0,
        0,
        0,
        NOW,
        NOW,
    )
    for overrides in (
        {"audit_id": ""},
        {"outcome": ArchiveRestoreOutcome.NOT_TESTED},
        {"observed_object_count": -1},
        {"started_at": datetime(2026, 8, 8)},
        {"finished_at": datetime(2026, 8, 8)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"outcome": ArchiveRestoreOutcome.SUCCESS},
        {
            "outcome": ArchiveRestoreOutcome.SUCCESS,
            "observed_checksum": "checksum",
            "observed_object_count": 1,
            "restored_object_count": 0,
        },
        {
            "outcome": ArchiveRestoreOutcome.SUCCESS,
            "observed_checksum": "checksum",
            "observed_object_count": 1,
            "restored_object_count": 1,
            "observed_size_bytes": 1,
            "restored_bytes": 0,
        },
    ):
        with pytest.raises(ValueError):
            replace(audit, **overrides)


def test_retention_run_member_and_plan_reject_invalid_state() -> None:
    run = RetentionRun(
        "run-1", "equity.daily", 1, True, "noop", 1, 0, 0, 0, 0, 0, started_at=NOW, finished_at=NOW
    )
    for overrides in (
        {"run_id": ""},
        {"policy_version": 0},
        {"outcome": "unknown"},
        {"requested": -1},
        {"started_at": datetime(2026, 8, 8)},
        {"finished_at": datetime(2026, 8, 8)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"cutoff": datetime(2026, 8, 8)},
    ):
        with pytest.raises(ValueError):
            replace(run, **overrides)

    member = RetentionPlanMember(
        0,
        "payload-1",
        "hash",
        "digest",
        "schema",
        NOW,
        NOW + timedelta(days=30),
        10,
        RetentionPlanDecision.ELIGIBLE,
        archive_id="archive-1",
    )
    for overrides in (
        {"ordinal": -1},
        {"payload_id": ""},
        {"size_bytes": -1},
        {"fetched_at": datetime(2026, 8, 8)},
        {"retention_until": datetime(2026, 8, 8)},
        {"deleted_at": datetime(2026, 8, 8)},
        {"archive_id": None},
        {"decision": RetentionPlanDecision.HELD},
        {"execution": RetentionMemberExecution.DELETED},
        {"deleted_at": NOW},
    ):
        with pytest.raises(ValueError):
            replace(member, **overrides)
    assert member.snapshot_fields()["archive_id"] == "archive-1"
    with pytest.raises(ValueError):
        retention_plan_snapshot_digest(
            dataset_key="equity.daily",
            policy_id="policy-1",
            policy_version=1,
            cutoff=datetime(2026, 8, 8),
            members=(member,),
        )

    plan = RetentionPlan(
        "plan-1",
        "operation-1",
        "equity.daily",
        "policy-1",
        1,
        1,
        1,
        1,
        0,
        0,
        10,
        NOW,
        NOW,
        NOW + timedelta(hours=1),
        "digest",
        RetentionPlanStatus.READY,
    )
    for overrides in (
        {"plan_id": ""},
        {"policy_version": 0},
        {"requested": 0},
        {"candidates": -1},
        {"candidates": 2},
        {"cutoff": datetime(2026, 8, 8)},
        {"created_at": datetime(2026, 8, 8)},
        {"expires_at": datetime(2026, 8, 8)},
        {"expires_at": NOW},
        {"finished_at": datetime(2026, 8, 8)},
        {"finished_at": NOW - timedelta(seconds=1)},
        {"status": RetentionPlanStatus.READY, "planned": 0, "candidates": 0},
        {"status": RetentionPlanStatus.EMPTY},
        {"status": RetentionPlanStatus.BLOCKED},
        {"deleted": 2},
    ):
        with pytest.raises(ValueError):
            replace(plan, **overrides)


def _market_series() -> MarketStructureSeriesDefinition:
    return MarketStructureSeriesDefinition(
        series_code="SERIES_A",
        series_version=1,
        flow_code="FLOW_A",
        flow_definition_version=1,
        taxonomy_code="TAXONOMY",
        taxonomy_version=1,
        actor_code="ACTOR_A",
        measure_concept=MarketStructureMeasureConcept.FLOW,
        measure_kind=InvestorFlowMeasureKind.FUND_FLOW,
        canonical_unit="CNY",
        frequency="monthly",
        source="test",
        revision_policy_ref="policy://revision/v1",
        effective_at=NOW,
        is_proxy=False,
        available_at=NOW,
    )


def _market_policy() -> MarketStructureAggregationPolicy:
    return MarketStructureAggregationPolicy(
        "POLICY",
        1,
        3,
        2,
        Decimal("1"),
        EmpiricalPercentileMethod.WEAK_EMPIRICAL_CDF,
    )


def test_market_structure_series_calendar_and_policy_reject_invalid_semantics() -> None:
    series = _market_series()
    for overrides in (
        {"series_version": 0},
        {"measure_concept": cast(MarketStructureMeasureConcept, "invalid")},
        {"measure_kind": cast(InvestorFlowMeasureKind, "invalid")},
        {"measure_kind": InvestorFlowMeasureKind.HOLDING_CHANGE},
        {"available_at": NOW - timedelta(seconds=1)},
        {"expires_at": NOW},
        {"is_active": cast(bool, "yes")},
        {"proxy_target_actor_code": "ACTOR_B"},
    ):
        with pytest.raises(ValueError):
            replace(series, **overrides)
    with pytest.raises(ValueError):
        MarketStructureSeriesRef("SERIES_A", 0)

    calendar = MarketStructurePeriodCalendar(
        "CALENDAR",
        1,
        "monthly",
        "test",
        "policy://calendar/v1",
        NOW,
        (NOW, NOW + timedelta(days=30), NOW + timedelta(days=60)),
    )
    for overrides in (
        {"calendar_version": 0},
        {"expires_at": NOW},
        {"periods": ()},
        {"periods": (NOW, NOW)},
        {"is_active": cast(bool, "yes")},
    ):
        with pytest.raises(ValueError):
            replace(calendar, **overrides)
    with pytest.raises(ValueError):
        MarketStructurePeriodCalendarRef("CALENDAR", 0)

    policy = _market_policy()
    for overrides in (
        {"policy_version": 0},
        {"minimum_history_observations": 2},
        {"minimum_actor_count": 1},
        {"minimum_membership_coverage_ratio": Decimal("1.1")},
        {"percentile_method": cast(EmpiricalPercentileMethod, "invalid")},
    ):
        with pytest.raises(ValueError):
            replace(policy, **overrides)


def test_market_structure_series_rejects_flow_drift_and_actor_governance_edges() -> None:
    series = _market_series()
    flow = InvestorFlowDefinition(
        flow_code=series.flow_code,
        definition_version=series.flow_definition_version,
        actor_code=series.actor_code,
        actor_name="Actor A",
        measure_kind=series.measure_kind,
        canonical_unit=series.canonical_unit,
        frequency=series.frequency,
        source=series.source,
        effective_at=series.effective_at,
        is_proxy=False,
    )
    for invalid_flow in (
        replace(flow, actor_code="ACTOR_B"),
        replace(flow, is_active=False),
        replace(flow, effective_at=NOW + timedelta(seconds=1)),
    ):
        with pytest.raises(ValueError):
            validate_series_against_flow_definition(series, invalid_flow)

    with pytest.raises(ValueError):
        VersionedEvidenceReference("dataset", 0, "a" * 64)
    actor = InvestorActorDefinition(
        taxonomy_code="TAXONOMY",
        taxonomy_version=1,
        actor_code="ACTOR_A",
        actor_name="Actor A",
        source="test",
        revision_policy_ref="policy://actor/v1",
        effective_at=NOW,
        available_at=NOW,
    )
    for overrides in (
        {"taxonomy_version": 0},
        {"available_at": NOW - timedelta(seconds=1)},
        {"expires_at": NOW},
        {"parent_actor_code": "ACTOR_A"},
        {"is_active": cast(bool, "yes")},
    ):
        with pytest.raises(ValueError):
            replace(actor, **overrides)


def test_market_structure_request_observation_and_membership_reject_invalid_semantics() -> None:
    series_ref = MarketStructureSeriesRef("SERIES_A", 1)
    request = MarketStructureResearchRequest(
        "EVIDENCE",
        1,
        NOW,
        KnowledgeScope.PUBLIC,
        "GROUP",
        1,
        MarketStructurePeriodCalendarRef("CALENDAR", 1),
        "method-v1",
        (series_ref,),
        _market_policy(),
    )
    for overrides in (
        {"evidence_version": 0},
        {"knowledge_scope": cast(KnowledgeScope, "invalid")},
        {"group_revision": 0},
        {"period_calendar": cast(MarketStructurePeriodCalendarRef, "invalid")},
        {"series": ()},
        {"series": (series_ref, series_ref)},
    ):
        with pytest.raises(ValueError):
            replace(request, **overrides)

    observation = MarketStructureObservation(
        "SERIES_A",
        1,
        "ACTOR_A",
        "ASSET_A",
        MarketStructureMeasureConcept.FLOW,
        NOW,
        NOW,
        Decimal("1"),
        "CNY",
        "monthly",
        "test",
        0,
        False,
        VersionedEvidenceReference("dataset", 1, "a" * 64),
    )
    for overrides in (
        {"series_version": 0},
        {"measure_concept": cast(MarketStructureMeasureConcept, "invalid")},
        {"available_at": NOW - timedelta(seconds=1)},
        {"revision_number": -1},
        {"is_proxy": cast(bool, "yes")},
        {"proxy_target_actor_code": "ACTOR_B"},
    ):
        with pytest.raises(ValueError):
            replace(observation, **overrides)

    evidence = observation.evidence
    membership = PITMembershipSnapshot("GROUP", 1, NOW, NOW, ("ASSET_A",), (evidence,))
    for overrides in (
        {"group_revision": 0},
        {"knowledge_at": NOW - timedelta(seconds=1)},
        {"asset_codes": ("ASSET_A", "ASSET_A"), "evidence": (evidence, evidence)},
        {"evidence": ()},
    ):
        with pytest.raises(ValueError):
            replace(membership, **overrides)


def test_market_structure_coverage_and_snapshot_reject_invalid_publication() -> None:
    coverage = SeriesPeriodCoverage("SERIES_A", 1, NOW, ("A", "B"), ("A",), ("B",))
    for overrides in (
        {"series_version": 0},
        {"expected_asset_codes": ("A", "A")},
        {"observed_asset_codes": ("A", "A")},
        {"missing_asset_codes": ("B", "B")},
        {"observed_asset_codes": ("C",)},
    ):
        with pytest.raises(ValueError):
            replace(coverage, **overrides)
    assert SeriesPeriodCoverage("SERIES_A", 1, NOW, (), (), ()).coverage_ratio == Decimal("0")

    blocked = MarketStructureSnapshot(
        MarketStructureResearchStatus.BLOCKED,
        NOW,
        "method-v1",
        (),
        (),
        ("insufficient_history",),
        False,
        (),
    )
    for overrides in (
        {"research_only": False},
        {"deterministic_conclusion": cast(None, "buy")},
        {"interpretation_scope": "decision"},
        {"blocked_reasons": ()},
        {"actor_metrics": (cast(ActorStructureMetrics, object()),)},
        {"status": MarketStructureResearchStatus.AVAILABLE},
    ):
        with pytest.raises(ValueError):
            replace(blocked, **overrides)
