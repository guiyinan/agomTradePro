"""Unit coverage for canonical R4 rolling persistence payloads and records."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.portfolio.application.r4_rolling_research_record import (
    R4RollingResearchDraft,
    R4RollingResearchRecord,
)
from apps.portfolio.infrastructure.r4_rolling_research_payload_codec import (
    artifact_from_payload,
    artifact_to_payload,
    promotion_from_payload,
    promotion_to_payload,
    study_from_payload,
    study_to_payload,
)
from tests.unit.portfolio.macro_risk_rolling_factories import (
    build_study,
    promotion_attestation,
)

EVALUATED_AT = datetime(2026, 3, 15, tzinfo=UTC)
RECORDED_AT = EVALUATED_AT + timedelta(minutes=1)
VALID_UNTIL = datetime(2026, 3, 31, tzinfo=UTC)
DEPENDENCY_LOCK_HASH = "a" * 64


def _draft() -> R4RollingResearchDraft:
    return R4RollingResearchDraft(
        study=build_study(),
        promotion_attestation=promotion_attestation(),
        evaluated_at=EVALUATED_AT,
        producer_code_version="git:r4-code-v1",
        dependency_lock_hash=DEPENDENCY_LOCK_HASH,
        valid_until=VALID_UNTIL,
    )


def _record() -> R4RollingResearchRecord:
    return R4RollingResearchRecord.from_server_clock(
        draft=_draft(),
        server_recorded_at=RECORDED_AT,
    )


def test_canonical_payloads_restore_exact_typed_graph_and_factory_output() -> None:
    record = _record()

    restored_study = study_from_payload(study_to_payload(record.study))
    restored_attestation = promotion_from_payload(
        promotion_to_payload(record.promotion_attestation)
    )
    restored_artifact = artifact_from_payload(
        artifact_to_payload(record.artifact),
        study=restored_study,
        promotion_attestation=restored_attestation,
    )
    restored_record = R4RollingResearchRecord.from_server_clock(
        draft=R4RollingResearchDraft(
            study=restored_study,
            promotion_attestation=restored_attestation,
            evaluated_at=restored_artifact.evaluated_at,
            producer_code_version=record.producer_code_version,
            dependency_lock_hash=record.dependency_lock_hash,
            valid_until=record.valid_until,
        ),
        server_recorded_at=record.recorded_at,
    )

    assert restored_study == record.study
    assert restored_attestation == record.promotion_attestation
    assert restored_artifact == record.artifact
    assert restored_record == record
    assert restored_study.windows[0].asset_covariance.condition_number.is_finite()
    assert restored_study.windows[0].asset_covariance.matrix_rank == 2
    assert restored_study.windows[0].asset_covariance.expected_observation_count == 30
    assert restored_study.windows[0].asset_covariance.missing_observation_count == 0
    assert (
        restored_study.windows[0].asset_covariance.missing_value_policy_version
        == "complete-case.v1"
    )
    assert record.split_contract_hash == record.study.split_contract_hash
    assert len(record.subhashes) == len({label for label, _ in record.subhashes})


def test_nested_covariance_or_artifact_tamper_is_rejected_by_factory_recompute() -> None:
    record = _record()
    study_payload = deepcopy(study_to_payload(record.study))
    study_data = study_payload["data"]
    assert isinstance(study_data, dict)
    windows = study_data["windows"]
    assert isinstance(windows, list)
    first_window = windows[0]
    assert isinstance(first_window, dict)
    covariance = first_window["asset_covariance"]
    assert isinstance(covariance, dict)
    covariance["condition_number"] = "10"

    with pytest.raises(ValueError, match="canonical payload mismatch"):
        study_from_payload(study_payload)

    artifact_payload = deepcopy(artifact_to_payload(record.artifact))
    artifact_data = artifact_payload["data"]
    assert isinstance(artifact_data, dict)
    artifact_data["artifact_hash"] = "b" * 64
    with pytest.raises(ValueError, match="canonical payload mismatch"):
        artifact_from_payload(
            artifact_payload,
            study=record.study,
            promotion_attestation=record.promotion_attestation,
        )


def test_equivalent_non_utc_datetime_text_is_rejected_as_payload_tamper() -> None:
    payload = deepcopy(study_to_payload(_record().study))
    data = payload["data"]
    assert isinstance(data, dict)
    windows = data["windows"]
    assert isinstance(windows, list)
    first_window = windows[0]
    assert isinstance(first_window, dict)
    first_window["selection_as_of"] = "2026-02-11T20:00:00+08:00"

    with pytest.raises(ValueError, match="canonical UTC text"):
        study_from_payload(payload)


def test_record_time_is_not_caller_input_and_must_be_inside_validity_window() -> None:
    assert "recorded_at" not in {field.name for field in fields(R4RollingResearchDraft)}
    draft = _draft()

    with pytest.raises(ValueError, match="cannot precede evaluated_at"):
        R4RollingResearchRecord.from_server_clock(
            draft=draft,
            server_recorded_at=EVALUATED_AT - timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="must precede valid_until"):
        R4RollingResearchRecord.from_server_clock(
            draft=draft,
            server_recorded_at=VALID_UNTIL,
        )


def test_record_hash_binds_producer_dependency_clock_and_every_subhash() -> None:
    record = _record()

    with pytest.raises(ValueError, match="identity mismatch"):
        replace(record, producer_code_version="git:different")
    with pytest.raises(ValueError, match="subhash ledger"):
        replace(record, subhashes=record.subhashes[:-1])
    with pytest.raises(ValueError, match="record_hash mismatch"):
        replace(record, recorded_at=record.recorded_at + timedelta(seconds=1))
