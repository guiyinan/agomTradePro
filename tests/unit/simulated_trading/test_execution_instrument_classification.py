"""Pure-domain contracts for sealed simulated-instrument classification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from apps.simulated_trading.domain.execution_current_reference import (
    CurrentReferenceSelectionV1,
    ExecutionInstrumentIdentityEvidenceV2,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    ExecutionCurrentReferenceSelectorItemV2,
    ExecutionCurrentReferenceSelectorV2,
    SimulatedInstrumentClassificationEvidenceV1,
    _canonical_hash,
)
from apps.simulated_trading.domain.execution_settlement_identity import (
    ExecutionInstrumentIdentityEvidenceV1,
    IdentityEvidenceValidationError,
)

_BASE = datetime(2026, 10, 18, 2, 0, tzinfo=UTC)
_SECURITY_ID = "risk-security-fixture-001"
_ASSET_CODE = "600000.SH"
_SOURCE_CODE = "600000.SH"
_SNAPSHOT_ID = UUID("11111111-1111-4111-8111-111111111111")
_MAPPING_RECORD_ID = UUID("22222222-2222-4222-8222-222222222222")
_OCCURRENCE_ID = UUID("33333333-3333-4333-8333-333333333333")


def _prefixed_hash(character: str) -> str:
    """Build one deterministic data-center SHA-256 pin."""

    return f"sha256:{character * 64}"


def _selector_item(*, asset_code: str = _ASSET_CODE) -> ExecutionCurrentReferenceSelectorItemV2:
    """Build one fully pinned explicit selector item."""

    return ExecutionCurrentReferenceSelectorItemV2(
        security_id=_SECURITY_ID,
        asset_code=asset_code,
        source_code=_SOURCE_CODE,
        snapshot_id=_SNAPSHOT_ID,
        snapshot_content_hash=_prefixed_hash("a"),
        snapshot_record_digest=_prefixed_hash("b"),
        mapping_record_id=_MAPPING_RECORD_ID,
        mapping_id="fixture-instrument-map",
        mapping_version="v1",
        mapping_content_hash=_prefixed_hash("c"),
        mapping_record_digest=_prefixed_hash("d"),
        simulated_asset_type="fixture_simulated_type_v7",
    )


def _selector(*, asset_code: str = _ASSET_CODE) -> ExecutionCurrentReferenceSelectorV2:
    """Build a v2 selector with one explicit source identity."""

    return ExecutionCurrentReferenceSelectorV2(
        purpose="normal_simulated_current_reference",
        max_local_reference_age_seconds=3600,
        items=(_selector_item(asset_code=asset_code),),
    )


def _selection(selector: ExecutionCurrentReferenceSelectorV2) -> CurrentReferenceSelectionV1:
    """Bind the exact selector hash to a bounded current-purpose selection."""

    return CurrentReferenceSelectionV1(
        purpose="normal_simulated_current_reference",
        profile_id="fixture-profile-id",
        profile_key="config_center.market.simulated_current_reference_selection",
        environment="simulated-test",
        profile_version=1,
        profile_content_hash="e" * 64,
        runtime_snapshot_id="fixture-runtime-snapshot",
        runtime_snapshot_hash="f" * 64,
        selector_content_hash=selector.content_hash,
        profile_activated_at=_BASE - timedelta(hours=5),
        runtime_snapshot_generated_at=_BASE - timedelta(hours=4),
        selected_at=_BASE,
        max_local_reference_age_seconds=selector.max_local_reference_age_seconds,
    )


def _identity(
    selector: ExecutionCurrentReferenceSelectorV2,
) -> ExecutionInstrumentIdentityEvidenceV2:
    """Build a local identity receipt while preserving unknown source clocks."""

    selection = _selection(selector)
    reference_at = _BASE - timedelta(minutes=10)
    snapshot_recorded_at = _BASE - timedelta(minutes=5)
    mapping_recorded_at = _BASE - timedelta(hours=1)
    source = ExecutionInstrumentIdentityEvidenceV1(
        security_id=_SECURITY_ID,
        asset_code=_ASSET_CODE,
        source_code=_SOURCE_CODE,
        source_exchange="SSE",
        source_market="FIXTURE_MAIN",
        rule_market="FIXTURE_SSE",
        board="FIXTURE_MAIN",
        snapshot_id=_SNAPSHOT_ID,
        snapshot_content_hash=_prefixed_hash("a"),
        snapshot_record_digest=_prefixed_hash("b"),
        first_seen_at=reference_at,
        snapshot_recorded_at=snapshot_recorded_at,
        mapping_record_id=_MAPPING_RECORD_ID,
        mapping_id="fixture-instrument-map",
        mapping_version="v1",
        mapping_content_hash=_prefixed_hash("c"),
        mapping_record_digest=_prefixed_hash("d"),
        mapping_recorded_at=mapping_recorded_at,
        response_completed_at=reference_at,
        source_observed_at=None,
        source_available_at=None,
        identity_valid_from=max(
            selection.profile_activated_at,
            snapshot_recorded_at,
            mapping_recorded_at,
        ),
        identity_valid_until=reference_at
        + timedelta(seconds=selection.max_local_reference_age_seconds),
        must_not_use_for_decision=True,
        must_not_execute=True,
    )
    return ExecutionInstrumentIdentityEvidenceV2(
        source_evidence=source,
        selection=selection,
        source_occurrence_id=_OCCURRENCE_ID,
        reference_response_completed_at=reference_at,
    )


def _classification(
    selector: ExecutionCurrentReferenceSelectorV2,
) -> SimulatedInstrumentClassificationEvidenceV1:
    """Build a classification sealed to the selector and local identity."""

    return SimulatedInstrumentClassificationEvidenceV1(
        selector=selector,
        identity_evidence=_identity(selector),
        read_at=_BASE,
    )


def _assert_code(error: IdentityEvidenceValidationError, code: str) -> None:
    """Assert the stable domain error code."""

    assert error.code == code


def test_canonical_hash_rejects_non_json_numeric_values() -> None:
    """Selector hashes must reject NaN instead of producing nonstandard JSON."""

    with pytest.raises(IdentityEvidenceValidationError) as error:
        _canonical_hash({"value": float("nan")})
    _assert_code(error.value, "CLASSIFICATION_JSON_INVALID")


def test_selector_item_rejects_non_uuid_source_pin() -> None:
    """A malformed source row ID cannot enter a typed selector item."""

    with pytest.raises(IdentityEvidenceValidationError) as error:
        replace(_selector_item(), snapshot_id="not-a-uuid")
    _assert_code(error.value, "CLASSIFICATION_SELECTOR_UUID_INVALID")


@pytest.mark.parametrize(
    ("purpose", "age", "items", "code"),
    [
        ("other-purpose", 3600, (_selector_item(),), "CLASSIFICATION_SELECTOR_PURPOSE_INVALID"),
        (
            "normal_simulated_current_reference",
            0,
            (_selector_item(),),
            "CLASSIFICATION_SELECTOR_AGE_INVALID",
        ),
        (
            "normal_simulated_current_reference",
            3600,
            [],
            "CLASSIFICATION_SELECTOR_ITEMS_INVALID",
        ),
        (
            "normal_simulated_current_reference",
            3600,
            (_selector_item(), _selector_item()),
            "CLASSIFICATION_SELECTOR_DUPLICATE_ITEM",
        ),
    ],
)
def test_selector_constructor_rejects_invalid_context(
    purpose: object,
    age: object,
    items: object,
    code: str,
) -> None:
    """Selector purpose, age, tuple shape, and uniqueness are enforced."""

    with pytest.raises(IdentityEvidenceValidationError) as error:
        ExecutionCurrentReferenceSelectorV2(
            purpose=cast(str, purpose),
            max_local_reference_age_seconds=cast(int, age),
            items=cast(tuple[ExecutionCurrentReferenceSelectorItemV2, ...], items),
        )
    _assert_code(error.value, code)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        (
            "schema",
            "normal-simulated-current-reference-selection.v1",
            "CLASSIFICATION_SELECTOR_SCHEMA_INVALID",
        ),
        ("purpose", True, "CLASSIFICATION_SELECTOR_PURPOSE_INVALID"),
        ("max_local_reference_age_seconds", True, "CLASSIFICATION_SELECTOR_AGE_INVALID"),
        ("items", {}, "CLASSIFICATION_SELECTOR_ITEMS_INVALID"),
    ],
)
def test_selector_payload_rejects_wrong_version_and_exact_field_types(
    field: str,
    value: object,
    code: str,
) -> None:
    """The wire parser does not coerce schema, purpose, age, or item shapes."""

    payload = _selector().to_payload()
    payload[field] = value
    with pytest.raises(IdentityEvidenceValidationError) as error:
        ExecutionCurrentReferenceSelectorV2.from_payload(payload)
    _assert_code(error.value, code)


def test_classification_requires_exact_selector_and_identity_types() -> None:
    """Arbitrary objects cannot stand in for the two sealed domain receipts."""

    selector = _selector()
    identity = _identity(selector)
    with pytest.raises(IdentityEvidenceValidationError) as selector_error:
        SimulatedInstrumentClassificationEvidenceV1(
            selector=cast(ExecutionCurrentReferenceSelectorV2, object()),
            identity_evidence=identity,
            read_at=_BASE,
        )
    _assert_code(selector_error.value, "CLASSIFICATION_SELECTOR_TYPE_INVALID")

    with pytest.raises(IdentityEvidenceValidationError) as identity_error:
        SimulatedInstrumentClassificationEvidenceV1(
            selector=selector,
            identity_evidence=cast(ExecutionInstrumentIdentityEvidenceV2, object()),
            read_at=_BASE,
        )
    _assert_code(identity_error.value, "CLASSIFICATION_IDENTITY_TYPE_INVALID")


def test_classification_rejects_selector_source_identity_mismatch() -> None:
    """A different asset row cannot borrow a valid identity's classification."""

    selector = _selector(asset_code="601000.SH")
    with pytest.raises(IdentityEvidenceValidationError) as error:
        SimulatedInstrumentClassificationEvidenceV1(
            selector=selector,
            identity_evidence=_identity(selector),
            read_at=_BASE,
        )
    _assert_code(error.value, "CLASSIFICATION_SOURCE_BINDING_MISMATCH")


def test_classification_round_trip_and_cutoff_preserve_context() -> None:
    """A sealed classification is readable only at or after its read cutoff."""

    classification = _classification(_selector())
    assert classification.simulated_asset_type == "fixture_simulated_type_v7"
    assert classification.validate_at(as_of=_BASE) is None
    assert (
        SimulatedInstrumentClassificationEvidenceV1.from_payload(classification.to_payload())
        == classification
    )
    assert classification.content_hash == _canonical_hash(classification.to_payload())

    with pytest.raises(IdentityEvidenceValidationError) as error:
        classification.validate_at(as_of=_BASE - timedelta(microseconds=1))
    _assert_code(error.value, "CLASSIFICATION_NOT_KNOWN_AT_CUTOFF")


def test_classification_rejects_naive_read_clock() -> None:
    """A naive datetime cannot be interpreted as a classification cutoff."""

    with pytest.raises(IdentityEvidenceValidationError) as error:
        replace(_classification(_selector()), read_at=_BASE.replace(tzinfo=None))
    _assert_code(error.value, "IDENTITY_EVIDENCE_TIME_INVALID")


def test_classification_rejects_selector_hash_tampering() -> None:
    """Changing the explicit type invalidates the selector hash sealed in identity."""

    payload = _classification(_selector()).to_payload()
    selector_payload = payload["selector"]
    assert type(selector_payload) is dict
    raw_items = selector_payload["items"]
    assert type(raw_items) is list
    item = raw_items[0]
    assert type(item) is dict
    item["simulated_asset_type"] = "tampered_simulated_type"

    with pytest.raises(IdentityEvidenceValidationError) as error:
        SimulatedInstrumentClassificationEvidenceV1.from_payload(payload)
    _assert_code(error.value, "CLASSIFICATION_SELECTOR_BINDING_MISMATCH")


def test_classification_parser_rejects_wrong_envelope_schema() -> None:
    """A different classification version cannot be decoded as v1."""

    payload = _classification(_selector()).to_payload()
    payload["schema"] = "simulated-instrument-classification-evidence.v2"
    with pytest.raises(IdentityEvidenceValidationError) as error:
        SimulatedInstrumentClassificationEvidenceV1.from_payload(payload)
    _assert_code(error.value, "CLASSIFICATION_SCHEMA_INVALID")
