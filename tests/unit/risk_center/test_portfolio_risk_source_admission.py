"""Focused contracts for explicit ASH-07 source admission and RawPayload reuse."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import replace
from datetime import timedelta
from io import StringIO
from pathlib import Path
from typing import Any, cast

import pytest
from django.core.management import call_command

from apps.data_center.application.raw_landing_public import configure_raw_landing_writer
from apps.data_center.domain.raw_landing import RawPayload
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskRawPayloadWriter,
    PortfolioRiskSourceAdmissionRequest,
    PortfolioRiskSourceAdmissionUseCase,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.infrastructure.portfolio_risk_source_admission_codec import (
    RetainedPortfolioRiskAdmissionManifestCodec,
)
from apps.risk_center.management.commands import admit_portfolio_risk_source as admission_command

_BODY = b"%PDF-1.7\x00official-public-source"


class _RecordingWriter:
    """In-memory write boundary for dry-run and explicit-write unit tests."""

    def __init__(self) -> None:
        self.calls: list[RawPayload] = []

    def land(self, payload: RawPayload) -> RawPayload:
        self.calls.append(payload)
        return payload


def _document() -> dict[str, object]:
    """Return a synthetic request with explicit unknown clocks and safe facts."""

    return {
        "schema_version": "ash07.source_admission_request.v1",
        "kind": "valuation",
        "asset_code": "510050.SH",
        "security_id": "security-510050",
        "source_record_id": "record-2026q3",
        "original_url": "https://source.example.test/report.pdf",
        "captured_at": "2026-11-03T10:02:03+08:00",
        "source_evidence": {
            "source_id": "official_public_site",
            "source_record_id": "record-2026q3",
            "original_payload_sha256": None,
            "observation_precision": "unknown",
            "observed_at": None,
            "observed_on": None,
            "available_at": None,
            "known_at": None,
            "valid_until": None,
            "source_purpose": "public_official",
            "allowed_purposes": ["simulated_portfolio_risk"],
            "restrictions": ["research_only"],
            "must_not_use_for_decision": True,
            "coverage": {
                "status": "unknown",
                "precision_basis": "source_does_not_state_coverage",
                "reported_weight_fraction": None,
                "expected_item_count": None,
                "observed_item_count": None,
            },
            "effective_on": None,
            "effective_until": None,
        },
        "facts": {
            "price": "2.5000",
            "asset_kind": "etf",
            "quantity_unit": None,
            "price_unit": "CNY",
        },
    }


def _request(document: dict[str, object] | None = None) -> PortfolioRiskSourceAdmissionRequest:
    return parse_portfolio_risk_source_admission_request(
        document or _document(),
        original_body=_BODY,
    )


def _use_case(writer: PortfolioRiskRawPayloadWriter) -> PortfolioRiskSourceAdmissionUseCase:
    return PortfolioRiskSourceAdmissionUseCase(
        manifest_factory=RetainedPortfolioRiskAdmissionManifestCodec(),
        writer=writer,
    )


def _nested_mapping(payload: RawPayload, key: str) -> dict[str, Any]:
    value = payload.payload[key]
    assert isinstance(value, dict)
    return cast(dict[str, Any], value)


def test_manifest_hash_binds_explicit_facts_separately_from_original_bytes() -> None:
    request = _request()
    payload = RetainedPortfolioRiskAdmissionManifestCodec().build_payload(request)
    original_hash = hashlib.sha256(_BODY).hexdigest()
    manifest_bytes = json.dumps(
        payload.payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    manifest_hash = f"sha256:{hashlib.sha256(manifest_bytes).hexdigest()}"
    source_evidence = _nested_mapping(payload, "source_evidence")

    assert source_evidence["original_payload_sha256"] == original_hash
    assert payload.payload_hash == manifest_hash
    assert payload.payload_hash != f"sha256:{original_hash}"
    assert payload.fetched_at == request.captured_at
    assert payload.payload["facts"] == _document()["facts"]
    assert set(payload.payload) == {
        "schema_version",
        "kind",
        "asset_code",
        "security_id",
        "source_record_id",
        "original_body_base64",
        "original_url",
        "source_evidence",
        "facts",
    }
    original_body_base64 = payload.payload["original_body_base64"]
    assert isinstance(original_body_base64, str)
    assert base64.b64decode(original_body_base64, validate=True) == _BODY
    assert _nested_mapping(payload, "source_evidence")["known_at"] is None


def test_unknown_source_times_and_prohibition_markers_are_retained() -> None:
    payload = RetainedPortfolioRiskAdmissionManifestCodec().build_payload(_request())
    evidence = _nested_mapping(payload, "source_evidence")

    assert evidence["observation_precision"] == "unknown"
    assert evidence["observed_at"] is None
    assert evidence["observed_on"] is None
    assert evidence["available_at"] is None
    assert evidence["known_at"] is None
    assert evidence["valid_until"] is None
    assert evidence["must_not_use_for_decision"] is True
    assert evidence["restrictions"] == ["research_only"]


def test_default_execution_builds_candidate_without_calling_writer() -> None:
    writer = _RecordingWriter()
    result = _use_case(writer).execute(_request())

    assert result.stored is False
    assert result.payload.payload_hash.startswith("sha256:")
    assert writer.calls == []


def test_management_command_defaults_to_dry_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writer = _RecordingWriter()
    use_case = _use_case(writer)
    document_path = tmp_path / "request.json"
    body_path = tmp_path / "original.bin"
    document_path.write_text(json.dumps(_document()), encoding="utf-8")
    body_path.write_bytes(_BODY)
    monkeypatch.setattr(
        admission_command,
        "build_portfolio_risk_source_admission_use_case",
        lambda: use_case,
    )

    call_command(
        "admit_portfolio_risk_source",
        "--document",
        str(document_path),
        "--original-body",
        str(body_path),
        stdout=StringIO(),
    )

    assert writer.calls == []


def test_explicit_persist_calls_writer_once() -> None:
    writer = _RecordingWriter()
    result = _use_case(writer).execute(_request(), persist=True)

    assert result.stored is True
    assert writer.calls == [result.payload]


def test_mismatched_original_hash_is_rejected_before_write() -> None:
    writer = _RecordingWriter()
    document = _document()
    source_evidence = cast(dict[str, object], document["source_evidence"])
    source_evidence["original_payload_sha256"] = "0" * 64

    with pytest.raises(ValueError, match="risk_input_original_body_hash_mismatch"):
        _use_case(writer).execute(_request(document), persist=True)

    assert writer.calls == []


def test_unknown_taxonomy_is_rejected_instead_of_defaulted() -> None:
    writer = _RecordingWriter()
    document = _document()
    document["kind"] = "industry_membership"
    document["facts"] = {
        "taxonomy_id": None,
        "taxonomy_kind": None,
        "provider_id": "provider-a",
        "provider_version": "version-a",
        "industry_code": "J",
        "effective_from": None,
        "effective_end_state": "unknown",
        "effective_until": None,
    }

    with pytest.raises(ValueError):
        _use_case(writer).execute(_request(document), persist=True)

    assert writer.calls == []


@pytest.mark.django_db
def test_existing_raw_payload_store_replays_candidate_and_rejects_metadata_conflict() -> None:
    """Exercise the existing immutable store with the same hash-addressed row."""

    from apps.data_center.infrastructure.raw_landing_repositories import RawLandingRepository

    configure_raw_landing_writer(RawLandingRepository)
    use_case = _use_case(_PublicRawPayloadWriterProxy())
    request = _request()

    first = use_case.execute(request, persist=True)
    retry = use_case.execute(request, persist=True)
    conflicting_retry = replace(
        request,
        captured_at=request.captured_at + timedelta(seconds=1),
    )

    assert retry.payload == first.payload
    assert retry.payload.payload_hash == first.payload.payload_hash
    with pytest.raises(ValueError, match="raw_payload_immutable_conflict"):
        use_case.execute(conflicting_retry, persist=True)


class _PublicRawPayloadWriterProxy:
    """Expose the same public write function used by the production adapter."""

    def land(self, payload: RawPayload) -> RawPayload:
        from apps.risk_center.infrastructure.data_center_raw_payload_writer import (
            DataCenterRawPayloadWriter,
        )

        return DataCenterRawPayloadWriter().land(payload)
