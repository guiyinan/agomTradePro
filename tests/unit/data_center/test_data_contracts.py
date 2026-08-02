"""Unit tests for the canonical data-center evidence contracts."""

from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.domain.contracts import (
    DataEnvelope,
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
from shared.domain.reliability import ReliabilityContract, ReliabilityStatus


def _dataset() -> DatasetKey:
    return DatasetKey("equity.quote.snapshot", "1.0", "1.0")


def _quality() -> QualityAssessment:
    return QualityAssessment(
        schema_valid=True,
        completeness_ratio=1.0,
        unit_valid=True,
        natural_key_valid=True,
    )


def _evidence() -> SourceEvidence:
    return SourceEvidence.from_payload(
        source="test-provider",
        source_capability="equity.quote.snapshot",
        payload={"close": 12.3},
    )


def _fresh() -> ReliabilityContract:
    observed = datetime(2026, 8, 1, 7, tzinfo=UTC)
    return ReliabilityContract.fresh(
        observed_at=observed,
        fetched_at=observed + timedelta(minutes=1),
        source="test-provider",
    )


def test_envelope_preserves_source_times_and_publication() -> None:
    observed = datetime(2026, 8, 1, 7, tzinfo=UTC)
    envelope = DataEnvelope(
        dataset=_dataset(),
        natural_key=NaturalKey((("asset_code", "000001.SZ"),)),
        value={"close": 12.3},
        observation=ObservationTime(
            observed_at=observed,
            published_at=None,
            available_at=observed,
            fetched_at=observed + timedelta(minutes=1),
        ),
        evidence=_evidence(),
        quality=_quality(),
        reliability=_fresh(),
        unit="CNY",
        publication_id="pub-1",
        is_current=True,
    )

    payload = envelope.to_dict()
    assert payload["observed_at"] == observed.isoformat()
    assert payload["fetched_at"] != payload["observed_at"]
    assert payload["publication_id"] == "pub-1"


def test_envelope_rejects_missing_value_without_fail_closed_contract() -> None:
    blocked = ReliabilityContract.blocked(
        status=ReliabilityStatus.MISSING,
        source="test-provider",
        reason_code="missing_quote",
        reason="quote is unavailable",
    )
    with pytest.raises(ValueError, match="missing DataEnvelope"):
        DataEnvelope(
            dataset=_dataset(),
            natural_key=NaturalKey((("asset_code", "000001.SZ"),)),
            value=None,
            observation=ObservationTime(
                observed_at=None,
                published_at=None,
                available_at=None,
                fetched_at=datetime.now(UTC),
            ),
            evidence=_evidence(),
            quality=_quality(),
            reliability=ReliabilityContract.fresh(
                observed_at=datetime.now(UTC),
                fetched_at=datetime.now(UTC),
                source="test-provider",
            ),
        )
    assert blocked.must_not_use_for_decision is True


def test_fetch_result_rejects_success_without_evidence() -> None:
    with pytest.raises(ValueError, match="source evidence"):
        FetchResult(
            outcome=FetchOutcome.SUCCESS,
            values=(1,),
            provider="test-provider",
            dataset=_dataset(),
            evidence=None,
            reliability=_fresh(),
            quality=_quality(),
        )


def test_sync_outcome_rejects_zero_stored_success() -> None:
    with pytest.raises(ValueError, match="zero stored"):
        SyncOutcome(
            outcome=FetchOutcome.SUCCESS,
            requested=1,
            succeeded=1,
            failed=0,
            stored=0,
            run_id="run-1",
        )


def test_publication_decision_requires_source_when_published() -> None:
    with pytest.raises(ValueError, match="selected_source"):
        PublicationDecision(
            publication_id="pub-1",
            dataset=_dataset(),
            state=PublicationState.PUBLISHED,
            selected_source=None,
            selected_member_hash=None,
            coverage_ratio=1.0,
            conflict_count=0,
        )


def test_dataset_contract_rejects_reversed_field_range() -> None:
    with pytest.raises(ValueError, match="minimum"):
        DatasetContract(
            key=_dataset(),
            owner="data-platform",
            frequency="daily",
            decision_critical=True,
            fields=(
                DatasetFieldContract(
                    name="close",
                    value_type="decimal",
                    unit="CNY",
                    nullable=False,
                    zero_allowed=False,
                    minimum=10.0,
                    maximum=1.0,
                ),
            ),
        )


def test_provider_binding_and_publication_policy_fail_closed() -> None:
    dataset = _dataset()
    binding = ProviderBinding(
        dataset=dataset,
        provider="tushare",
        capability="quote_snapshot",
        priority=10,
        freshness_seconds=86400,
        validator_key="equity.quote.snapshot",
    )
    policy = PublicationPolicy(
        dataset=dataset,
        minimum_coverage_ratio=0.99,
        allow_partial=False,
        conflict_action="block",
        required_evidence=("payload_hash", "observed_at", "source"),
        retention_days=365,
    )
    assert binding.enabled
    assert policy.conflict_action == "block"
