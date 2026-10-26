"""Pure contracts for staged full-session quote capture references."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import NAMESPACE_URL, uuid5

import pytest

from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.quote_session_capture import (
    QuoteSessionCaptureOrigin,
    QuoteSessionRequestScope,
    quote_session_capture_evidence,
)
from apps.data_center.application.sync_identity import build_sync_execution_identity
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.raw_audit_manifest import CandidateRawAuditManifestError
from apps.data_center.infrastructure.quote_session_capture_lineage import (
    require_consistent_quote_session_capture_bindings,
    validate_quote_session_request_scope,
)

_RESPONSE_COMPLETED_AT = datetime(2026, 10, 27, 8, 5, tzinfo=UTC)


def _capture_fixture() -> tuple[dict[str, object], QuoteSessionRequestScope]:
    """Build one structurally valid capture binding without Django or I/O."""

    identity = build_sync_execution_identity(
        run_id="a447d65f-60dc-4eb3-83f0-52c2c5a9d7e8",
        ingested_run_id="be4303d6-9b0e-4da0-b101-20f1b50b286c",
        batch_id="7d582a07-4384-44cb-8b16-8da3c4e7a5ee",
        dataset_key="equity.quote.snapshot",
        provider_name="Tushare Pro",
    )
    scope = QuoteSessionRequestScope(
        provider_id=19,
        provider_name="Tushare Pro",
        dataset_key="equity.quote.snapshot",
        api_name="daily",
        asset_codes=("000001.SZ", "600000.SH"),
        target_trade_date=date(2026, 10, 26),
    )
    payload_hash = f"sha256:{'a' * 64}"
    reference = ProviderResponsePayloadReference(
        payload_id=str(uuid5(NAMESPACE_URL, payload_hash)),
        payload_hash=payload_hash,
        record_digest=f"sha256:{'b' * 64}",
        body_sha256="c" * 64,
        retained_content_sha256="c" * 64,
        original_body_retained=True,
        retained_content_encoding="exact_original_utf8_json",
        body_size_bytes=128,
        response_completed_at=_RESPONSE_COMPLETED_AT,
        provider_name=scope.provider_name,
        dataset_key=scope.dataset_key,
        transport=ProviderResponseTransport.EGRESS,
        run_id=identity.run_id,
    )
    binding = quote_session_capture_evidence(
        QuoteSessionCaptureOrigin(identity=identity, request_scope=scope),
        reference,
        available_codes=("000001.SZ",),
        eligible_codes=("000001.SZ",),
        excluded_codes=("600000.SH",),
        quote_rows_sha256="d" * 64,
    )
    return binding, scope


def test_capture_binding_requires_one_exact_parent_across_audits_and_facts() -> None:
    binding, _scope = _capture_fixture()
    audit_extra = {"source_type": "tushare", "quote_session_capture": binding}
    fact_extra = {"source_type": "tushare", "quote_session_capture": binding}

    resolved = require_consistent_quote_session_capture_bindings(
        audit_extras=(audit_extra, audit_extra),
        fact_extras=(fact_extra,),
    )

    assert resolved == binding


def test_legacy_bundle_without_capture_binding_remains_compatible() -> None:
    resolved = require_consistent_quote_session_capture_bindings(
        audit_extras=({"source_type": "tushare"},),
        fact_extras=({"source_type": "tushare"},),
    )

    assert resolved is None


@pytest.mark.parametrize(
    ("audit_extras", "fact_extras"),
    [
        (({"quote_session_capture": {"schema": "quote-session-capture-v1"}},), ({},)),
        (({"quote_session_capture": {"schema": "quote-session-capture-v1"}},), ()),
    ],
)
def test_capture_and_legacy_metadata_cannot_be_mixed(
    audit_extras: tuple[object, ...],
    fact_extras: tuple[object, ...],
) -> None:
    with pytest.raises(CandidateRawAuditManifestError):
        require_consistent_quote_session_capture_bindings(
            audit_extras=audit_extras,
            fact_extras=fact_extras,
        )


def test_capture_facts_cannot_claim_different_session_scope_or_payload() -> None:
    binding, _scope = _capture_fixture()
    changed = dict(binding)
    changed["quote_rows_sha256"] = "e" * 64

    with pytest.raises(CandidateRawAuditManifestError, match="one parent session"):
        require_consistent_quote_session_capture_bindings(
            audit_extras=({"quote_session_capture": binding},),
            fact_extras=({"quote_session_capture": changed},),
        )


def test_raw_payload_scope_must_match_the_complete_capture_request() -> None:
    binding, scope = _capture_fixture()

    rebuilt = validate_quote_session_request_scope(
        binding_scope=binding["request_scope"],
        request_params=scope.request_params(),
    )

    assert rebuilt == scope


@pytest.mark.parametrize(
    "mutate",
    [
        "truncate_codes",
        "alter_asset_count",
        "add_security_filter",
        "change_trade_date",
    ],
)
def test_raw_payload_scope_rejects_truncation_and_parameter_drift(mutate: str) -> None:
    binding, scope = _capture_fixture()
    request_params = scope.request_params()
    scope_payload = request_params["quote_session_scope"]
    daily_params = request_params["params"]
    assert isinstance(scope_payload, dict)
    assert isinstance(daily_params, dict)
    if mutate == "truncate_codes":
        scope_payload["asset_codes"] = ["000001.SZ"]
    elif mutate == "alter_asset_count":
        scope_payload["asset_count"] = 1
    elif mutate == "add_security_filter":
        daily_params["ts_code"] = "000001.SZ"
    else:
        daily_params["trade_date"] = "20261027"

    with pytest.raises(CandidateRawAuditManifestError):
        validate_quote_session_request_scope(
            binding_scope=binding["request_scope"],
            request_params=request_params,
        )
