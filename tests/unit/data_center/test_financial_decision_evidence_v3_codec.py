"""Pure contract tests for the isolated decision-evidence v3 envelope."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from apps.data_center.domain.financial_next_session_witness import (
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_source_evidence import FinancialFactDecisionEvidence
from apps.data_center.infrastructure.financial_decision_evidence_codec import (
    FinancialDecisionEvidenceCodecError,
    decode_financial_decision_evidence,
    encode_financial_decision_evidence,
)
from core.exceptions import DataValidationError
from tests.unit.data_center.test_financial_decision_evidence_codec import (
    _evidence as _legacy_v2_evidence,
)
from tests.unit.data_center.test_financial_next_session_witness import (
    _witness as _source_time_v3_witness,
)

_LEGACY_V1_CANONICAL_SHA256 = "0aca57f19048f50a40b8e78bf22eb657eb61cb9cb6551a89da61678ce7e662bc"
_LEGACY_V2_CANONICAL_SHA256 = "51148fafc8dccb9f117469374b36cd31d37186a61c064c1784b5e0202a4bd44f"


def _canonical_sha256(payload: dict[str, object]) -> str:
    """Hash the canonical storage JSON used by the pinned legacy projections."""

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _v3_evidence() -> FinancialFactDecisionEvidence:
    """Build a v3 envelope using the repository's formal witness fixture."""

    witness = _source_time_v3_witness()
    assert type(witness) is FinancialNextSessionSourceTimeWitnessV3
    row = witness.financial_row
    return FinancialFactDecisionEvidence(
        artifact_reference=row.artifact_reference,
        native_asset_code=row.asset_code,
        native_period_end=row.period_end,
        native_row_id=row.native_row_id,
        source_time_witness_v3=witness,
    )


def test_v1_v2_canonical_storage_goldens_remain_unchanged() -> None:
    """The additive v3 branch preserves the exact previous v1/v2 JSON bytes."""

    v2_evidence = _legacy_v2_evidence()
    v1_evidence = FinancialFactDecisionEvidence(
        artifact_reference=v2_evidence.artifact_reference,
        native_asset_code=v2_evidence.native_asset_code,
        native_period_end=v2_evidence.native_period_end,
        native_row_id=v2_evidence.native_row_id,
    )

    v1_payload = encode_financial_decision_evidence(v1_evidence)
    v2_payload = encode_financial_decision_evidence(v2_evidence)

    assert v1_payload["schema"] == "financial-fact-decision-evidence.v1"
    assert v2_payload["schema"] == "financial-fact-decision-evidence.v2"
    assert _canonical_sha256(v1_payload) == _LEGACY_V1_CANONICAL_SHA256
    assert _canonical_sha256(v2_payload) == _LEGACY_V2_CANONICAL_SHA256
    assert decode_financial_decision_evidence(v1_payload) == v1_evidence
    assert decode_financial_decision_evidence(v2_payload) == v2_evidence


def test_v3_envelope_round_trips_date_only_witness_without_legacy_timestamp() -> None:
    """The v3 envelope keeps next-session timing separate from v1/v2 fields."""

    evidence = _v3_evidence()
    payload = encode_financial_decision_evidence(evidence)

    assert payload["schema"] == "financial-fact-decision-evidence.v3"
    assert "source_time_witness_v3" in payload
    assert "source_time_witness" not in payload
    assert "announced_at" not in repr(payload)
    nested = payload["source_time_witness_v3"]
    assert isinstance(nested, dict)
    assert nested["schema"] == "financial-next-session-source-time-witness.v3"
    assert isinstance(nested["financial_row"], dict)
    assert isinstance(nested["financial_row"]["notice_date"], str)
    assert isinstance(nested["financial_row"]["period_end"], str)
    assert "announced_at" not in nested["financial_row"]

    decoded = decode_financial_decision_evidence(payload)

    assert decoded == evidence
    assert decoded is not None
    assert type(decoded.source_time_witness_v3) is FinancialNextSessionSourceTimeWitnessV3
    assert decoded.source_time_witness is None
    assert encode_financial_decision_evidence(decoded) == payload
    assert decoded.source_time_witness_v3 is not None
    assert decoded.source_time_witness_v3.reference_only is True
    assert decoded.source_time_witness_v3.must_not_use_for_decision is True
    assert decoded.source_time_witness_v3.must_not_execute is True


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update({"source_time_witness": {}}),
        lambda payload: payload.__setitem__("schema", "financial-fact-decision-evidence.v2"),
        lambda payload: payload.__setitem__("schema", "financial-fact-decision-evidence.v1"),
        lambda payload: payload.pop("source_time_witness_v3"),
        lambda payload: payload.__setitem__(
            "source_time_witness", payload.pop("source_time_witness_v3")
        ),
    ],
)
def test_v3_envelope_rejects_legacy_mixing_and_schema_downgrade(mutation) -> None:
    """A legacy schema cannot silently carry or absorb the date-only witness."""

    payload = encode_financial_decision_evidence(_v3_evidence())
    mutation(payload)

    with pytest.raises((FinancialDecisionEvidenceCodecError, ValueError)):
        decode_financial_decision_evidence(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["artifact_reference"].__setitem__(
            "capture_id", "20000000-0000-4000-8000-000000000099"
        ),
        lambda payload: payload["artifact_reference"].__setitem__("body_sha256", "f" * 64),
        lambda payload: payload["artifact_reference"]["request_scope"].__setitem__(
            "provider_name", "provider-other"
        ),
        lambda payload: payload.__setitem__("native_asset_code", "000002.SZ"),
        lambda payload: payload.__setitem__("native_period_end", "2026-03-31"),
        lambda payload: payload.__setitem__("native_row_id", "provider-row:other"),
    ],
)
def test_v3_envelope_rejects_outer_artifact_and_native_row_rebinding(mutation) -> None:
    """Capture, body, provider, security, period and row identities stay bound."""

    payload = encode_financial_decision_evidence(_v3_evidence())
    mutation(payload)

    with pytest.raises((FinancialDecisionEvidenceCodecError, ValueError)):
        decode_financial_decision_evidence(payload)


def test_domain_rejects_mixing_v2_and_v3_witness_fields() -> None:
    """The typed envelope cannot carry both source-time generations at once."""

    v2 = _legacy_v2_evidence()
    v3 = _source_time_v3_witness()

    with pytest.raises(ValueError, match="cannot mix"):
        FinancialFactDecisionEvidence(
            artifact_reference=v2.artifact_reference,
            native_asset_code=v2.native_asset_code,
            native_period_end=v2.native_period_end,
            native_row_id=v2.native_row_id,
            source_time_witness=v2.source_time_witness,
            source_time_witness_v3=v3,
        )


def test_domain_rejects_v3_row_capture_rebinding() -> None:
    """A v3 row must identify the same response capture as its outer envelope."""

    evidence = _v3_evidence()
    assert evidence.source_time_witness_v3 is not None
    witness = evidence.source_time_witness_v3
    wrong_capture = replace(
        witness.financial_row.artifact_reference,
        capture_id=UUID("20000000-0000-4000-8000-000000000099"),
    )
    wrong_row = replace(witness.financial_row, artifact_reference=wrong_capture)
    wrong_witness = replace(witness, financial_row=wrong_row)

    with pytest.raises(ValueError, match="dimensions do not match"):
        replace(evidence, source_time_witness_v3=wrong_witness)


def test_v3_encoder_rechecks_mutated_frozen_outer_envelope() -> None:
    """The new branch revalidates v3 bindings even after unsafe mutation."""

    evidence = _v3_evidence()
    legacy = _legacy_v2_evidence()
    object.__setattr__(evidence, "source_time_witness", legacy.source_time_witness)

    with pytest.raises(ValueError, match="cannot mix"):
        encode_financial_decision_evidence(evidence)


@pytest.mark.parametrize(
    "mutation",
    ["missing_schema", "null_v3", "legacy_extra_null", "null_notice_date", "unknown_nested_schema"],
)
def test_v3_envelope_malformed_boundaries_raise_identifiable_validation_errors(
    mutation: str,
) -> None:
    """Malformed persisted JSON cannot silently lose v3 or leak a missing-key error."""

    payload = encode_financial_decision_evidence(_v3_evidence())
    if mutation == "missing_schema":
        payload.pop("schema")
    elif mutation == "null_v3":
        payload["source_time_witness_v3"] = None
    elif mutation == "legacy_extra_null":
        payload = encode_financial_decision_evidence(_legacy_v2_evidence())
        payload["source_time_witness_v3"] = None
    else:
        nested = payload["source_time_witness_v3"]
        assert isinstance(nested, dict)
        if mutation == "null_notice_date":
            row = nested["financial_row"]
            assert isinstance(row, dict)
            row["notice_date"] = None
        else:
            nested["schema"] = "unknown"
    with pytest.raises(DataValidationError):
        decode_financial_decision_evidence(payload)
