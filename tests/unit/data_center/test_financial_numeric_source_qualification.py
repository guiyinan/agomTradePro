"""Pure-Domain tests for hash-bound financial source-context qualifications."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from apps.data_center.domain.financial_numeric_evidence import FinancialMetricSourceContract
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceContextRequirement,
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)


def _contract(**changes: object) -> FinancialMetricSourceContract:
    """Build a synthetic native metric contract without business unit defaults."""

    values: dict[str, object] = {
        "provider": "provider.sample",
        "dataset_key": "dataset.sample",
        "metric_code": "metric.sample",
        "source_field": "SOURCE_VALUE",
        "source_unit": "unit.native.sample",
        "canonical_unit": "unit.canonical.sample",
        "scale_numerator": 1,
        "scale_denominator": 1,
        "contract_version": "sample.v1",
        "origin": "native",
    }
    values.update(changes)
    return FinancialMetricSourceContract(**values)  # type: ignore[arg-type]


def _document(**changes: object) -> FinancialNumericSourceDocumentCaptureReference:
    """Build a synthetic capture reference without inventing a publisher version."""

    values: dict[str, object] = {
        "capture_id": UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        "document_id": "document.sample",
        "issuer": "publisher.sample",
        "canonical_url": "https://docs.example.test/financial-api.html",
        "body_sha256": "a" * 64,
        "body_size_bytes": 1024,
        "captured_at": datetime(2026, 1, 2, tzinfo=UTC),
        "content_type": "text/html; charset=utf-8",
    }
    values.update(changes)
    return FinancialNumericSourceDocumentCaptureReference(**values)  # type: ignore[arg-type]


def _qualification(**changes: object) -> FinancialNumericSourceQualification:
    """Build one synthetic unapproved source-context candidate."""

    values: dict[str, object] = {
        "contract": _contract(),
        "endpoint": "api.example.test/financial/main?format=json",
        "source_applicability": "native_financial_metric_row",
        "document_capture": _document(),
        "context_requirements": (
            FinancialNumericSourceContextRequirement(
                field_name="CURRENCY_LABEL",
                expected_value="unit.context.sample",
            ),
        ),
        "effective_from": datetime(2026, 1, 2, 1, tzinfo=UTC),
        "effective_until": None,
    }
    values.update(changes)
    return FinancialNumericSourceQualification(**values)  # type: ignore[arg-type]


def test_qualification_hash_binds_metric_endpoint_context_capture_and_effective_window() -> None:
    candidate = _qualification()
    original_hash = candidate.content_hash

    assert candidate.identity == f"financial-metric-source-qualification.v1:{original_hash}"
    assert replace(candidate, endpoint="api.example.test/financial/alternate").content_hash != (
        original_hash
    )
    assert replace(candidate, source_applicability="other_row_kind").content_hash != original_hash
    assert replace(candidate, contract=_contract(metric_code="metric.other")).content_hash != (
        original_hash
    )
    assert replace(candidate, document_capture=_document(body_sha256="b" * 64)).content_hash != (
        original_hash
    )
    assert (
        replace(
            candidate,
            context_requirements=(
                FinancialNumericSourceContextRequirement(
                    field_name="CURRENCY_LABEL",
                    expected_value="unit.context.other",
                ),
            ),
        ).content_hash
        != original_hash
    )
    assert replace(candidate, effective_from=datetime(2026, 1, 3, 1, tzinfo=UTC)).content_hash != (
        original_hash
    )
    assert candidate.to_dict()["production_ready"] is False
    assert candidate.to_dict()["must_not_use_for_decision"] is True


def test_versioned_payload_round_trips_and_rejects_unknown_or_typed_identity_drift() -> None:
    candidate = _qualification()
    payload = candidate.to_dict()

    assert FinancialNumericSourceQualification.from_payload(payload) == candidate

    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload({**payload, "unexpected": True})

    changed_contract = dict(payload["contract"])
    changed_contract["metric_code"] = "metric.changed"
    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload({**payload, "contract": changed_contract})

    requirements = list(payload["context_requirements"])
    requirements[0] = {**requirements[0], "expected_value": 1}
    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload(
            {**payload, "context_requirements": requirements}
        )


def test_context_requires_every_explicit_typed_value_without_cleaning_or_defaulting() -> None:
    candidate = _qualification(
        context_requirements=(
            FinancialNumericSourceContextRequirement(
                field_name="CURRENCY_LABEL", expected_value="unit.context.sample"
            ),
            FinancialNumericSourceContextRequirement(field_name="STATEMENT_KIND", expected_value=2),
            FinancialNumericSourceContextRequirement(
                field_name="IS_CONSOLIDATED", expected_value=True
            ),
        )
    )

    assert candidate.matches_source_context(
        {
            "CURRENCY_LABEL": "unit.context.sample",
            "STATEMENT_KIND": 2,
            "IS_CONSOLIDATED": True,
            "UNRELATED_SOURCE_FIELD": "preserved but not interpreted",
        }
    )
    assert not candidate.matches_source_context(
        {"CURRENCY_LABEL": "unit.context.sample", "STATEMENT_KIND": 2}
    )
    assert not candidate.matches_source_context(
        {
            "CURRENCY_LABEL": "unit.context.sample",
            "STATEMENT_KIND": True,
            "IS_CONSOLIDATED": True,
        }
    )
    assert not candidate.matches_source_context(
        {
            "CURRENCY_LABEL": "unit.context.sample ",
            "STATEMENT_KIND": 2,
            "IS_CONSOLIDATED": True,
        }
    )
    assert not candidate.matches_source_context(None)
    assert not candidate.matches_source_context({1: "unit.context.sample"})


@pytest.mark.parametrize("invalid_value", [None, 1.25, [], {"value": "unknown"}])
def test_context_requirement_rejects_missing_mixed_or_untyped_values(invalid_value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        FinancialNumericSourceContextRequirement(
            field_name="CONTEXT_FIELD",
            expected_value=invalid_value,
        )


@pytest.mark.parametrize("invalid_value", ["", "bad\u0001value", "\ud800", 1 << 500])
def test_context_requirement_rejects_invalid_text_and_unbounded_integer(
    invalid_value: object,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        FinancialNumericSourceContextRequirement(
            field_name="CONTEXT_FIELD",
            expected_value=invalid_value,
        )


def test_context_rules_must_be_nonempty_unique_and_exactly_typed() -> None:
    requirement = FinancialNumericSourceContextRequirement(
        field_name="CONTEXT_FIELD", expected_value="explicit-value"
    )
    with pytest.raises(ValueError):
        _qualification(context_requirements=())
    with pytest.raises(ValueError):
        _qualification(context_requirements=(requirement, requirement))
    with pytest.raises(TypeError):
        _qualification(context_requirements=(object(),))
    with pytest.raises(ValueError):
        FinancialNumericSourceContextRequirement(field_name="", expected_value="value")
    with pytest.raises(ValueError):
        FinancialNumericSourceContextRequirement.from_payload({1: "not-a-string-key"})
    with pytest.raises(ValueError):
        FinancialNumericSourceContextRequirement.from_payload(
            {
                "field_name": "CONTEXT_FIELD",
                "expected_value": 1,
                "value_type": "boolean",
            }
        )


def test_document_capture_ref_binds_exact_bytes_without_fabricated_source_version() -> None:
    document = _document()
    payload = document.to_dict()

    assert payload["capture_id"] == str(document.capture_id)
    assert payload["body_sha256"] == document.body_sha256
    assert "source_version" not in payload
    assert document.identity

    with pytest.raises(ValueError):
        _document(body_sha256="not-a-digest")
    with pytest.raises(ValueError):
        _document(body_size_bytes=0)
    with pytest.raises(ValueError):
        _document(body_size_bytes=sys.maxsize)
    with pytest.raises(ValueError):
        _document(canonical_url="http://docs.example.test/financial-api.html")
    with pytest.raises(ValueError):
        _document(captured_at=datetime(2026, 1, 2))
    with pytest.raises(ValueError):
        _document(captured_at=datetime(2026, 1, 2, tzinfo=timezone(timedelta(hours=1))))
    with pytest.raises(ValueError):
        _document(captured_at=datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))))
    with pytest.raises(TypeError):
        _document(capture_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    with pytest.raises(ValueError):
        _document(body_size_bytes=False)
    with pytest.raises(ValueError):
        _document(canonical_url="https://docs.example.test:443/financial-api.html")
    with pytest.raises(ValueError):
        _document(canonical_url="https://docs.example.test/financial api.html")
    assert _document(canonical_url="https://docs.example.test:8443/financial-api.html")


def test_document_capture_url_round_trips_up_to_the_declared_bound() -> None:
    """A retained document address must use the same constructor and wire bounds."""
    prefix = "https://docs.example.test/"
    document = _document(canonical_url=prefix + "a" * (4096 - len(prefix)))
    assert FinancialNumericSourceDocumentCaptureReference.from_payload(document.to_dict()) == (
        document
    )
    with pytest.raises(ValueError):
        _document(canonical_url=document.canonical_url + "a")


def test_response_effective_window_and_knowledge_clocks_are_independent() -> None:
    candidate = _qualification(
        effective_from=datetime(2026, 1, 2, 1, tzinfo=UTC),
        effective_until=datetime(2026, 1, 4, 1, tzinfo=UTC),
    )
    source_response_completed_at = datetime(2026, 1, 2, 1, 2, tzinfo=UTC)
    database_recorded_at = datetime(2026, 1, 2, 1, 1, tzinfo=UTC)
    approved_at = datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC)

    assert candidate.is_eligible_at(
        known_at=datetime(2026, 1, 2, 1, 3, tzinfo=UTC),
        source_response_completed_at=source_response_completed_at,
        recorded_at=database_recorded_at,
        approved_at=approved_at,
    )
    assert not candidate.is_eligible_at(
        known_at=datetime(2026, 1, 2, 1, 1, 15, tzinfo=UTC),
        source_response_completed_at=source_response_completed_at,
        recorded_at=database_recorded_at,
        approved_at=approved_at,
    )
    assert candidate.is_eligible_at(
        known_at=datetime(2026, 1, 4, 1, tzinfo=UTC),
        source_response_completed_at=source_response_completed_at,
        recorded_at=database_recorded_at,
        approved_at=approved_at,
    )
    assert not candidate.is_eligible_at(
        known_at=datetime(2026, 1, 2, 1, 3, tzinfo=UTC),
        source_response_completed_at=source_response_completed_at,
        recorded_at=database_recorded_at,
        approved_at=approved_at,
        revoked_at=datetime(2026, 1, 2, 1, 2, 30, tzinfo=UTC),
    )


def test_missing_or_naive_clocks_and_future_capture_fail_closed() -> None:
    candidate = _qualification()
    known_at = datetime(2026, 1, 2, 2, tzinfo=UTC)
    recorded_at = datetime(2026, 1, 2, 1, 1, tzinfo=UTC)
    source_response_completed_at = datetime(2026, 1, 2, 1, 30, tzinfo=UTC)

    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=source_response_completed_at,
        recorded_at=recorded_at,
        approved_at=None,
    )
    assert not candidate.is_eligible_at(
        known_at=datetime(2026, 1, 2, 2),
        source_response_completed_at=source_response_completed_at,
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 1, 1, 30),
    )
    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=None,
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC),
    )
    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=datetime(2026, 1, 2, 1, 30),
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC),
    )
    future_capture = _document(captured_at=known_at + timedelta(seconds=1))
    future_candidate = _qualification(
        document_capture=future_capture,
        effective_from=known_at + timedelta(seconds=1),
    )
    assert not future_candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=known_at + timedelta(seconds=1),
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC),
    )
    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=source_response_completed_at,
        recorded_at=datetime(2026, 1, 2, 2, 1, tzinfo=UTC),
        approved_at=datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC),
    )
    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=source_response_completed_at,
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 2, 1, tzinfo=UTC),
    )
    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=source_response_completed_at,
        recorded_at=recorded_at,
        approved_at=datetime(2026, 1, 2, 1, 1, 30, tzinfo=UTC),
        revoked_at=datetime(2026, 1, 2, 1, 1),
    )


def test_response_clock_applies_effective_half_open_window_not_later_knowledge_cutoff() -> None:
    starts_at = datetime(2026, 1, 2, 1, tzinfo=UTC)
    ends_at = datetime(2026, 1, 3, tzinfo=UTC)
    candidate = _qualification(effective_from=starts_at, effective_until=ends_at)
    recorded_at = datetime(2026, 1, 2, 1, 1, tzinfo=UTC)
    approved_at = datetime(2026, 1, 2, 1, 2, tzinfo=UTC)

    assert candidate.is_eligible_at(
        known_at=datetime(2026, 1, 4, tzinfo=UTC),
        source_response_completed_at=starts_at,
        recorded_at=recorded_at,
        approved_at=approved_at,
    )
    assert not candidate.is_eligible_at(
        known_at=datetime(2026, 1, 4, tzinfo=UTC),
        source_response_completed_at=ends_at,
        recorded_at=recorded_at,
        approved_at=approved_at,
    )


def test_old_response_cannot_use_later_document_but_fresh_response_can() -> None:
    document_captured_at = datetime(2026, 1, 2, 1, 59, tzinfo=UTC)
    effective_from = datetime(2026, 1, 2, 2, tzinfo=UTC)
    candidate = _qualification(
        document_capture=_document(captured_at=document_captured_at),
        effective_from=effective_from,
        effective_until=datetime(2026, 1, 3, tzinfo=UTC),
    )
    known_at = datetime(2026, 1, 4, tzinfo=UTC)
    recorded_at = datetime(2026, 1, 2, 2, 1, tzinfo=UTC)
    approved_at = datetime(2026, 1, 2, 2, 2, tzinfo=UTC)

    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=datetime(2026, 1, 2, 1, 58, tzinfo=UTC),
        recorded_at=recorded_at,
        approved_at=approved_at,
    )
    assert candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=effective_from,
        recorded_at=recorded_at,
        approved_at=approved_at,
    )


def test_response_completed_after_knowledge_cutoff_is_rejected() -> None:
    candidate = _qualification()
    known_at = datetime(2026, 1, 2, 1, 30, tzinfo=UTC)

    assert not candidate.is_eligible_at(
        known_at=known_at,
        source_response_completed_at=known_at + timedelta(seconds=1),
        recorded_at=datetime(2026, 1, 2, 1, 1, tzinfo=UTC),
        approved_at=datetime(2026, 1, 2, 1, 2, tzinfo=UTC),
    )


def test_candidate_rejects_unknown_shapes_and_invalid_effective_interval() -> None:
    candidate = _qualification()

    with pytest.raises(TypeError):
        _qualification(contract=object())
    with pytest.raises(TypeError):
        _qualification(document_capture=object())
    with pytest.raises(ValueError):
        _qualification(endpoint="api.example.test/financial main")
    with pytest.raises(ValueError):
        _qualification(source_applicability="")
    with pytest.raises(ValueError):
        replace(
            candidate,
            effective_until=datetime(2026, 1, 2, 1, tzinfo=UTC),
        )
    with pytest.raises(ValueError):
        _qualification(document_capture=_document(captured_at=datetime(2026, 1, 2, 2, tzinfo=UTC)))
    with pytest.raises(ValueError):
        _qualification(effective_from=datetime.max.replace(tzinfo=timezone(timedelta(hours=-1))))


def test_versioned_decoder_rejects_bad_schema_and_noncanonical_timestamps() -> None:
    candidate = _qualification()
    payload = candidate.to_dict()

    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload({**payload, "schema": "future.v9"})
    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload(
            {**payload, "effective_from": "2026-01-02T01:00:00Z"}
        )
    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload(
            {**payload, "effective_from": "2026-01-02T01:00:00"}
        )
    with pytest.raises(ValueError):
        FinancialNumericSourceQualification.from_payload({**payload, "production_ready": True})
