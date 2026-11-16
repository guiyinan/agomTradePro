"""Pure exact-storage identity contracts; all source values are synthetic."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from apps.data_center.domain.financial_next_session_witness import (
    FinancialNextSessionSourceTimeWitnessV3,
)
from apps.data_center.domain.financial_statutory_source_identity import (
    FinancialStatutorySourceIdentity,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceBodyReference
from apps.data_center.infrastructure.financial_next_session_witness_codec import (
    FinancialNextSessionWitnessCodecError,
    decode_financial_next_session_witness_v3,
    encode_financial_next_session_witness_v3,
)
from tests.unit.data_center.test_financial_next_session_witness import _witness


def _statutory_witness() -> FinancialNextSessionSourceTimeWitnessV3:
    """Replace only the storage-kind identity of an existing synthetic witness."""

    original = _witness()
    assert type(original) is FinancialNextSessionSourceTimeWitnessV3
    source = original.governance.official_source
    reference = StatutorySourceBodyReference(
        capture_id=source.capture_id,
        reference=f"statutory-source-body:///v1/{source.capture_id}.body",
        body_sha256=source.body_sha256,
        body_size_bytes=source.body_size_bytes,
    )
    identity = FinancialStatutorySourceIdentity(
        issuer="synthetic-exchange",
        document_id="synthetic-opening-rule",
        source_version="synthetic.v1",
        source_revision_sha256="b" * 64,
        source_uri=source.source_uri,
        body_reference=reference,
        first_seen_at=source.first_seen_at,
        revision_recorded_at=source.recorded_at,
        capture_observed_at=source.first_seen_at,
        recorded_at=source.recorded_at,
    )
    return replace(original, governance=replace(original.governance, official_source=identity))


def test_public_statutory_source_round_trips_without_encryption_fields() -> None:
    """Exact real-storage fields replace the formerly unrepresentable source kind."""

    witness = _statutory_witness()
    payload = encode_financial_next_session_witness_v3(witness)
    decoded = decode_financial_next_session_witness_v3(payload)
    assert decoded == witness
    source = witness.governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    assert all("encrypt" not in key and "key_ref" not in key for key in source.to_dict())
    assert witness.reference_only and witness.must_not_use_for_decision and witness.must_not_execute


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_schema",
        "unknown_schema",
        "extra_encryption",
        "null_body",
        "wrong_revision",
        "future_observation",
    ],
)
def test_statutory_storage_branch_rejects_downgrade_mixing_and_invalid_identity(
    mutation: str,
) -> None:
    """The explicit nested schema never falls through to encrypted legacy decoding."""

    payload = encode_financial_next_session_witness_v3(_statutory_witness())
    governance = cast(dict[str, object], payload["governance"])
    source = cast(dict[str, object], governance["official_source"])
    if mutation == "missing_schema":
        source.pop("schema")
    elif mutation == "unknown_schema":
        source["schema"] = "unknown"
    elif mutation == "extra_encryption":
        source["encryption_key_ref"] = "invented"
    elif mutation == "null_body":
        source["body_reference"] = None
    elif mutation == "wrong_revision":
        source["source_revision_sha256"] = "invalid"
    else:
        recorded = datetime.fromisoformat(cast(str, source["recorded_at"]))
        source["capture_observed_at"] = (recorded + timedelta(seconds=1)).isoformat()
    with pytest.raises((FinancialNextSessionWitnessCodecError, ValueError)):
        decode_financial_next_session_witness_v3(payload)


def test_original_encrypted_source_branch_keeps_its_exact_payload() -> None:
    """The new branch leaves the existing encrypted reference format untouched."""

    witness = _witness()
    assert type(witness) is FinancialNextSessionSourceTimeWitnessV3
    payload = encode_financial_next_session_witness_v3(witness)
    governance = cast(dict[str, object], payload["governance"])
    source = cast(dict[str, object], governance["official_source"])
    assert "schema" not in source
    assert source["encryption_algorithm"] == witness.governance.official_source.encryption_algorithm
    assert (
        encode_financial_next_session_witness_v3(decode_financial_next_session_witness_v3(payload))
        == payload
    )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("issuer", ""),
        ("document_id", " padded"),
        ("source_version", "v" * 121),
        ("source_uri", "http://example.test/rule"),
        ("source_uri", "https://user:password@example.test/rule"),
        ("source_uri", "https://example.test/rule#fragment"),
        ("source_revision_sha256", "invalid"),
        ("body_reference", object()),
        ("first_seen_at", datetime(2026, 1, 1)),
        ("revision_recorded_at", datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=8)))),
    ],
)
def test_statutory_source_identity_rejects_invalid_native_storage_and_clock_fields(
    field: str,
    replacement: object,
) -> None:
    """A typed reference still validates every external field before domain use."""

    source = _statutory_witness().governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    with pytest.raises((ValueError, TypeError)):
        replace(source, **{field: replacement})


@pytest.mark.parametrize("field", ["first_seen_at", "revision_recorded_at", "recorded_at"])
def test_statutory_source_identity_rejects_reversed_knowledge_clocks(field: str) -> None:
    """No caller can make a capture precede observation or revision recording."""

    source = _statutory_witness().governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    value = (
        source.capture_observed_at - timedelta(seconds=1)
        if field == "recorded_at"
        else source.recorded_at + timedelta(seconds=1)
    )
    with pytest.raises(ValueError):
        replace(source, **{field: value})


def test_statutory_capture_and_rule_configuration_keep_distinct_record_clocks() -> None:
    """A real source capture predates the later configuration row without rewriting either."""

    witness = _statutory_witness()
    source = witness.governance.official_source
    assert type(source) is FinancialStatutorySourceIdentity
    capture_recorded_at = source.recorded_at - timedelta(seconds=1)
    actual_source = replace(
        source,
        recorded_at=capture_recorded_at,
        revision_recorded_at=capture_recorded_at - timedelta(milliseconds=1),
    )
    bound = replace(witness, governance=replace(witness.governance, official_source=actual_source))
    decoded = decode_financial_next_session_witness_v3(
        encode_financial_next_session_witness_v3(bound)
    )
    assert decoded.governance.official_source.recorded_at == capture_recorded_at
    assert (
        decoded.availability.opening_rule.recorded_at
        == witness.availability.opening_rule.recorded_at
    )
    assert (
        decoded.governance.official_source.recorded_at
        < decoded.availability.opening_rule.recorded_at
    )
