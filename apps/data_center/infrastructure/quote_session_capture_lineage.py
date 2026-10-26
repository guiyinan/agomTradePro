"""Validate retained full-session quote captures before candidate staging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import TypeGuard

from django.db import connections

from apps.data_center.application.current_publication_candidate import (
    CurrentPublicationCandidateSnapshot,
)
from apps.data_center.application.full_market_task_support import asset_code_scope_sha256
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.application.quote_session_capture import (
    QuoteSessionCaptureOrigin,
    QuoteSessionRequestScope,
    quote_session_capture_evidence,
    validate_quote_session_capture_binding,
)
from apps.data_center.domain.entities import raw_audit_content_hash
from apps.data_center.domain.market_time import cn_market_session_close_utc
from apps.data_center.domain.raw_audit_manifest import (
    CandidateRawAuditManifest,
    CandidateRawAuditManifestError,
)
from apps.data_center.infrastructure.fact_and_operational_models import (
    RawAuditModel,
    RawPayloadModel,
    SyncExecutionIdentityModel,
)
from apps.data_center.infrastructure.models import QuoteSnapshotModel
from apps.data_center.infrastructure.provider_state_repositories import RawAuditRepository
from core.exceptions import DataFetchError

_QUOTE_DATASET = "equity.quote.snapshot"
_CAPTURE_KEY = "quote_session_capture"
_CAPTURE_SCHEMA = "quote-session-capture-v1"
_CAPTURE_FIELDS = frozenset(
    {
        "schema",
        "origin",
        "request_scope",
        "universe_sha256",
        "available_codes_sha256",
        "eligible_codes_sha256",
        "excluded_codes_sha256",
        "quote_rows_sha256",
        "response_completed_at",
        "payload_reference",
    }
)
_ORIGIN_FIELDS = frozenset(
    {
        "run_id",
        "ingested_run_id",
        "batch_id",
        "dataset_key",
        "provider_name",
        "identity_hash",
    }
)
_REQUEST_SCOPE_FIELDS = frozenset(
    {
        "provider_id",
        "provider_name",
        "dataset_key",
        "api_name",
        "target_trade_date",
        "asset_count",
        "universe_sha256",
    }
)
_RAW_REQUEST_FIELDS = frozenset(
    {
        "provider_id",
        "provider_name",
        "dataset_key",
        "api_name",
        "params",
        "quote_session_scope",
    }
)
_RAW_SCOPE_FIELDS = frozenset({"asset_codes", "asset_count", "universe_sha256"})
_DAILY_PARAMS_FIELDS = frozenset({"trade_date"})


@dataclass(frozen=True, slots=True)
class _ParsedCaptureEvidence:
    """Narrow one JSON capture binding after validating its immutable shape."""

    payload: dict[str, object]
    origin: dict[str, object]
    request_scope: dict[str, object]
    payload_reference: ProviderResponsePayloadReference
    quote_rows_sha256: str


def validate_quote_session_capture_lineage(
    candidate: CurrentPublicationCandidateSnapshot,
    manifest: CandidateRawAuditManifest,
    *,
    using: str = "default",
) -> None:
    """Lock and validate one complete retained quote capture inside staging UOW.

    Legacy quote candidates with no capture metadata are left on their existing
    lineage path. Once any fact or RawAudit advertises a capture, every member
    and audit must bind the same parent session and its complete request scope.
    """

    if using != "default":
        raise CandidateRawAuditManifestError(
            "quote capture lineage currently requires the default database"
        )
    if candidate.publication.dataset_key != _QUOTE_DATASET:
        return
    if not connections[using].in_atomic_block:
        raise CandidateRawAuditManifestError(
            "quote capture lineage validation requires the staging transaction"
        )

    audit_ids = tuple(int(reference.raw_audit_id) for reference in manifest.raw_audits)
    fact_ids = tuple(_fact_pk(member.fact_pk) for member in candidate.members)
    candidate_fact_ids = {str(fact_id) for fact_id in fact_ids}
    audit_extras = tuple(
        RawAuditModel._default_manager.using(using)
        .filter(pk__in=audit_ids)
        .order_by("pk")
        .values_list("extra", flat=True)
    )
    fact_extras = tuple(
        QuoteSnapshotModel._default_manager.using(using)
        .filter(pk__in=fact_ids)
        .order_by("pk")
        .values_list("extra", flat=True)
    )
    binding = require_consistent_quote_session_capture_bindings(
        audit_extras=audit_extras,
        fact_extras=fact_extras,
    )
    if binding is None:
        return

    audit_rows = list(
        RawAuditModel._default_manager.using(using)
        .select_for_update()
        .filter(pk__in=audit_ids)
        .order_by("pk")
    )
    fact_rows = list(
        QuoteSnapshotModel._default_manager.using(using)
        .select_for_update()
        .filter(pk__in=fact_ids)
        .order_by("pk")
    )
    reference_by_id = {reference.raw_audit_id: reference for reference in manifest.raw_audits}
    audit_rows_by_id = {str(audit_row.pk): audit_row for audit_row in audit_rows}
    fact_rows_by_id = {str(fact_row.pk): fact_row for fact_row in fact_rows}
    locked_binding = require_consistent_quote_session_capture_bindings(
        audit_extras=tuple(audit_row.extra for audit_row in audit_rows),
        fact_extras=tuple(fact_row.extra for fact_row in fact_rows),
    )
    if locked_binding is None or locked_binding != binding:
        raise CandidateRawAuditManifestError(
            "quote capture metadata changed while acquiring stage locks"
        )
    parsed = _parse_capture_evidence(locked_binding)

    if len(audit_rows) != len(audit_ids) or audit_rows_by_id.keys() != reference_by_id.keys():
        raise CandidateRawAuditManifestError(
            "quote capture RawAudit identities changed before candidate staging"
        )
    if len(fact_rows) != len(fact_ids) or fact_rows_by_id.keys() != candidate_fact_ids:
        raise CandidateRawAuditManifestError("quote capture facts changed before candidate staging")

    for raw_audit_id in sorted(reference_by_id, key=int):
        audit_row = audit_rows_by_id[raw_audit_id]
        reference = reference_by_id[raw_audit_id]
        audit = RawAuditRepository._from_model(audit_row)
        if (
            audit_row.content_hash != reference.content_hash
            or raw_audit_content_hash(audit) != reference.content_hash
            or str(audit_row.run_id or "") != reference.run_id
            or str(audit_row.ingested_run_id or "") != reference.ingested_run_id
            or audit_row.provider_name != reference.provider_name
            or audit_row.provider_name != parsed.payload_reference.provider_name
            or audit_row.capability != reference.capability
            or audit_row.status != "ok"
            or audit_row.row_count <= 0
        ):
            raise CandidateRawAuditManifestError(
                "quote capture RawAudit identity or content changed before staging"
            )
    source_types = {
        _string_value(_mapping(audit_row.extra, "child RawAudit extra"), "source_type")
        for audit_row in audit_rows
    }
    if len(source_types) != 1:
        raise CandidateRawAuditManifestError(
            "one quote capture session cannot mix child source types"
        )

    child_audits_by_ingested_run_id: dict[str, RawAuditModel] = {}
    facts_by_ingested_run_id: dict[str, list[QuoteSnapshotModel]] = {}
    for audit_row in audit_rows:
        ingested_run_id = str(audit_row.ingested_run_id or "")
        if not ingested_run_id or ingested_run_id in child_audits_by_ingested_run_id:
            raise CandidateRawAuditManifestError(
                "quote capture chunks require unique child ingestion identities"
            )
        child_audits_by_ingested_run_id[ingested_run_id] = audit_row
        facts_by_ingested_run_id[ingested_run_id] = []

    for fact_row in fact_rows:
        ingested_run_id = str(fact_row.ingested_run_id or "")
        child_audit = child_audits_by_ingested_run_id.get(ingested_run_id)
        if child_audit is None:
            raise CandidateRawAuditManifestError(
                "quote capture fact belongs to a missing child RawAudit"
            )
        if _capture_binding_from_extra(fact_row.extra) != parsed.payload:
            raise CandidateRawAuditManifestError(
                "quote capture fact binding differs from its child RawAudit"
            )
        facts_by_ingested_run_id[ingested_run_id].append(fact_row)

    for ingested_run_id, audit_row in child_audits_by_ingested_run_id.items():
        child_facts = facts_by_ingested_run_id[ingested_run_id]
        if len(child_facts) != audit_row.row_count:
            raise CandidateRawAuditManifestError(
                "quote capture child RawAudit row count differs from staged facts"
            )
        _validate_child_chunk_parameters(
            audit_row,
            child_facts,
            capture=parsed,
            request_scope=parsed.request_scope,
        )

    origin_values = parsed.origin
    identity_hash = _string_value(origin_values, "identity_hash")
    identity_rows = list(
        SyncExecutionIdentityModel._default_manager.using(using)
        .select_for_update()
        .filter(identity_hash=identity_hash)
        .order_by("identity_hash")
    )
    if len(identity_rows) != 1:
        raise CandidateRawAuditManifestError(
            "quote capture parent sync identity is missing or ambiguous"
        )
    identity_row = identity_rows[0]
    identity = identity_row.to_identity()
    capture_origin_payload = {
        "run_id": identity.run_id,
        "ingested_run_id": identity.ingested_run_id,
        "batch_id": identity.batch_id,
        "dataset_key": identity.dataset_key,
        "provider_name": identity.provider_name,
        "identity_hash": identity.identity_hash,
    }
    if capture_origin_payload != parsed.origin:
        raise CandidateRawAuditManifestError(
            "quote capture parent identity does not match its persisted server identity"
        )

    payload_hash = parsed.payload_reference.payload_hash
    payload_rows = list(
        RawPayloadModel._default_manager.using(using)
        .select_for_update()
        .filter(payload_hash=payload_hash)
        .order_by("payload_hash")
    )
    if len(payload_rows) != 1:
        raise CandidateRawAuditManifestError(
            "quote capture parent RawPayload is missing or ambiguous"
        )
    payload_row = payload_rows[0]
    raw_payload = payload_row.to_domain()
    request_scope = validate_quote_session_request_scope(
        binding_scope=parsed.request_scope,
        request_params=raw_payload.request_params,
    )
    try:
        capture_origin = QuoteSessionCaptureOrigin(
            identity=identity,
            request_scope=request_scope,
        )
        validate_quote_session_capture_binding(
            capture_origin,
            parsed.payload_reference,
            request_scope=request_scope,
        )
    except (DataFetchError, TypeError, ValueError) as error:
        raise CandidateRawAuditManifestError(
            "quote capture parent reference does not match its identity and scope"
        ) from error
    if not parsed.payload_reference.verifies(raw_payload):
        raise CandidateRawAuditManifestError(
            "quote capture parent RawPayload does not verify its retained response"
        )
    if (
        payload_row.run_id is None
        or str(payload_row.run_id) != identity.run_id
        or payload_row.dataset_key != identity.dataset_key
        or payload_row.provider_name != identity.provider_name
        or payload_row.fetched_at != parsed.payload_reference.response_completed_at
    ):
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload parent identity or completion time changed"
        )

    parent_identity_pair = (identity.run_id, identity.ingested_run_id)
    if any(
        parent_identity_pair
        == (str(child_audit_row.run_id or ""), str(child_audit_row.ingested_run_id or ""))
        for child_audit_row in audit_rows
    ):
        raise CandidateRawAuditManifestError(
            "quote capture parent identity cannot be reused as a child RawAudit identity"
        )
    if any(
        child_audit_row.response_payload_hash != parsed.payload_reference.payload_hash
        for child_audit_row in audit_rows
    ):
        raise CandidateRawAuditManifestError(
            "quote capture child RawAudit does not reference the retained parent payload"
        )

    fact_codes = tuple(sorted(fact_row.asset_code for fact_row in fact_rows))
    if len(fact_codes) != len(set(fact_codes)):
        raise CandidateRawAuditManifestError(
            "quote capture candidate must contain one fact per eligible asset"
        )
    excluded_codes = tuple(sorted(block.asset_code for block in candidate.publication.scope_blocks))
    if len(excluded_codes) != len(set(excluded_codes)) or set(fact_codes) & set(excluded_codes):
        raise CandidateRawAuditManifestError(
            "quote capture eligible and excluded asset sets overlap or contain duplicates"
        )
    requested_codes = request_scope.asset_codes
    if set(fact_codes) | set(excluded_codes) != set(requested_codes):
        raise CandidateRawAuditManifestError(
            "quote capture candidate does not cover its complete frozen request scope"
        )
    if (
        candidate.publication.coverage.requested_count != len(requested_codes)
        or candidate.publication.coverage.eligible_count != len(fact_codes)
        or candidate.publication.coverage.selected_count != len(fact_codes)
        or candidate.publication.coverage.missing_count != len(excluded_codes)
        or any(
            block.target_trade_date != request_scope.target_trade_date
            for block in candidate.publication.scope_blocks
        )
    ):
        raise CandidateRawAuditManifestError(
            "quote capture candidate coverage differs from its frozen request scope"
        )

    expected_observed_at = cn_market_session_close_utc(request_scope.target_trade_date)
    for fact_row in fact_rows:
        if (
            fact_row.raw_payload_hash != parsed.payload_reference.body_sha256
            or fact_row.fetched_at != parsed.payload_reference.response_completed_at
            or fact_row.snapshot_at != expected_observed_at
        ):
            raise CandidateRawAuditManifestError(
                "quote capture fact does not match its retained response identity"
            )

    try:
        expected_binding = quote_session_capture_evidence(
            capture_origin,
            parsed.payload_reference,
            available_codes=fact_codes,
            eligible_codes=fact_codes,
            excluded_codes=excluded_codes,
            quote_rows_sha256=parsed.quote_rows_sha256,
        )
    except (DataFetchError, TypeError, ValueError) as error:
        raise CandidateRawAuditManifestError(
            "quote capture scope cannot be reconstructed from persisted facts"
        ) from error
    if expected_binding != parsed.payload:
        raise CandidateRawAuditManifestError(
            "quote capture digest scope differs from persisted facts or exclusions"
        )


def require_consistent_quote_session_capture_bindings(
    *,
    audit_extras: Sequence[object],
    fact_extras: Sequence[object],
) -> dict[str, object] | None:
    """Return one exact binding, preserving legacy bundles with no capture key."""

    values: list[dict[str, object] | None] = [
        _capture_binding_from_extra(extra) for extra in (*audit_extras, *fact_extras)
    ]
    present = [value for value in values if value is not None]
    if not present:
        return None
    if len(present) != len(values):
        raise CandidateRawAuditManifestError(
            "quote capture metadata cannot be mixed with legacy facts or audits"
        )
    binding = present[0]
    if any(value != binding for value in present[1:]):
        raise CandidateRawAuditManifestError(
            "quote capture facts and child RawAudits do not share one parent session"
        )
    _parse_capture_evidence(binding)
    return binding


def validate_quote_session_request_scope(
    *,
    binding_scope: dict[str, object],
    request_params: object,
) -> QuoteSessionRequestScope:
    """Rebuild and compare the full frozen request scope from retained parameters."""

    raw = _mapping(request_params, "RawPayload request_params")
    if raw.keys() != _RAW_REQUEST_FIELDS:
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload request parameters are incomplete or unexpected"
        )
    raw_scope = _mapping(raw.get("quote_session_scope"), "quote_session_scope")
    if raw_scope.keys() != _RAW_SCOPE_FIELDS:
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload scope is incomplete or unexpected"
        )
    raw_params = _mapping(raw.get("params"), "provider daily parameters")
    if raw_params.keys() != _DAILY_PARAMS_FIELDS:
        raise CandidateRawAuditManifestError(
            "quote capture provider request must retain only the daily trade_date parameter"
        )
    asset_codes_value = raw_scope.get("asset_codes")
    if not _is_string_sequence(asset_codes_value):
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload does not retain the complete asset-code scope"
        )
    asset_codes = tuple(asset_codes_value)
    provider_id = _positive_int(raw.get("provider_id"), "provider_id")
    provider_name = _string_value(raw, "provider_name")
    dataset_key = _string_value(raw, "dataset_key")
    api_name = _string_value(raw, "api_name")
    trade_date_value = _string_value(raw_params, "trade_date")
    try:
        target_trade_date = date.fromisoformat(
            f"{trade_date_value[:4]}-{trade_date_value[4:6]}-{trade_date_value[6:8]}"
        )
    except (TypeError, ValueError) as error:
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload trade_date is invalid"
        ) from error
    if target_trade_date.strftime("%Y%m%d") != trade_date_value:
        raise CandidateRawAuditManifestError("quote capture RawPayload trade_date is not canonical")

    try:
        scope = QuoteSessionRequestScope(
            provider_id=provider_id,
            provider_name=provider_name,
            dataset_key=dataset_key,
            api_name=api_name,
            asset_codes=asset_codes,
            target_trade_date=target_trade_date,
        )
    except (TypeError, ValueError) as error:
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload request scope is invalid"
        ) from error
    if (
        raw_scope.get("asset_count") != len(asset_codes)
        or raw_scope.get("universe_sha256") != scope.universe_sha256
        or raw != scope.request_params()
        or binding_scope != scope.to_payload()
    ):
        raise CandidateRawAuditManifestError(
            "quote capture RawPayload and compact request scope disagree"
        )
    return scope


def _capture_binding_from_extra(extra: object) -> dict[str, object] | None:
    """Return the optional capture metadata after narrowing one JSON extra value."""

    if not _is_json_object(extra):
        raise CandidateRawAuditManifestError("quote capture fact or RawAudit extra is invalid")
    if _CAPTURE_KEY not in extra:
        return None
    return _mapping(extra[_CAPTURE_KEY], "quote_session_capture")


def _parse_capture_evidence(value: dict[str, object]) -> _ParsedCaptureEvidence:
    """Validate exact capture fields and rebuild the persisted payload reference."""

    if value.keys() != _CAPTURE_FIELDS or value.get("schema") != _CAPTURE_SCHEMA:
        raise CandidateRawAuditManifestError("quote session capture schema is invalid")
    origin = _mapping(value.get("origin"), "capture origin")
    scope = _mapping(value.get("request_scope"), "capture request scope")
    if origin.keys() != _ORIGIN_FIELDS or scope.keys() != _REQUEST_SCOPE_FIELDS:
        raise CandidateRawAuditManifestError("quote session capture identity fields are invalid")
    if (
        _string_value(origin, "dataset_key") != _QUOTE_DATASET
        or _string_value(scope, "dataset_key") != _QUOTE_DATASET
        or _string_value(scope, "api_name") != "daily"
        or _positive_int(scope.get("provider_id"), "provider_id") < 1
        or _positive_int(scope.get("asset_count"), "asset_count") < 1
    ):
        raise CandidateRawAuditManifestError("quote session capture request scope is invalid")
    for field_name in ("run_id", "ingested_run_id", "batch_id", "provider_name"):
        _string_value(origin, field_name)
    _require_sha256(_string_value(origin, "identity_hash"), "identity_hash")
    _string_value(scope, "provider_name")
    _string_value(scope, "target_trade_date")
    _require_sha256(_string_value(scope, "universe_sha256"), "universe_sha256")
    for field_name in (
        "universe_sha256",
        "available_codes_sha256",
        "eligible_codes_sha256",
        "excluded_codes_sha256",
        "quote_rows_sha256",
    ):
        _require_sha256(_string_value(value, field_name), field_name)
    payload_reference_value = _mapping(value.get("payload_reference"), "payload reference")
    try:
        payload_reference = ProviderResponsePayloadReference.from_payload(payload_reference_value)
    except (TypeError, ValueError) as error:
        raise CandidateRawAuditManifestError(
            "quote session capture payload reference is invalid"
        ) from error
    if payload_reference.to_payload() != payload_reference_value:
        raise CandidateRawAuditManifestError(
            "quote session capture payload reference is not canonical"
        )
    if (
        _string_value(value, "response_completed_at")
        != payload_reference.response_completed_at.isoformat()
        or payload_reference.provider_name != _string_value(scope, "provider_name")
        or payload_reference.dataset_key != _QUOTE_DATASET
        or payload_reference.run_id != _string_value(origin, "run_id")
    ):
        raise CandidateRawAuditManifestError(
            "quote session capture payload reference differs from its parent identity"
        )
    return _ParsedCaptureEvidence(
        payload=value,
        origin=origin,
        request_scope=scope,
        payload_reference=payload_reference,
        quote_rows_sha256=_string_value(value, "quote_rows_sha256"),
    )


def _validate_child_chunk_parameters(
    audit_row: RawAuditModel,
    fact_rows: Sequence[QuoteSnapshotModel],
    *,
    capture: _ParsedCaptureEvidence,
    request_scope: dict[str, object],
) -> None:
    """Bind one child audit's subset request to exactly its normalized fact rows."""

    request = _mapping(audit_row.request_params, "child RawAudit request_params")
    expected_fields = frozenset(
        {
            "asset_codes",
            "target_trade_date",
            "quote_session_universe_sha256",
            "quote_session_rows_sha256",
            "quote_session_response_completed_at",
            "quote_session_raw_response_sha256s",
            "quote_session_available_codes",
            "quote_session_eligible_codes",
            "quote_session_excluded_codes",
        }
    )
    if request.keys() != expected_fields:
        raise CandidateRawAuditManifestError(
            "quote capture child RawAudit request parameters are incomplete or unexpected"
        )

    child_codes = tuple(sorted(row.asset_code for row in fact_rows))
    requested_child_codes = _canonical_code_list(request.get("asset_codes"), "chunk asset_codes")
    if (
        requested_child_codes != child_codes
        or len(child_codes) != len(set(child_codes))
        or request.get("target_trade_date") != request_scope.get("target_trade_date")
        or request.get("quote_session_universe_sha256") != request_scope.get("universe_sha256")
        or request.get("quote_session_rows_sha256") != capture.payload.get("quote_rows_sha256")
        or request.get("quote_session_response_completed_at")
        != capture.payload.get("response_completed_at")
    ):
        raise CandidateRawAuditManifestError(
            "quote capture child RawAudit request differs from its fact rows or parent session"
        )

    raw_response_hashes = request.get("quote_session_raw_response_sha256s")
    if raw_response_hashes != [capture.payload_reference.body_sha256]:
        raise CandidateRawAuditManifestError(
            "quote capture child RawAudit response hashes differ from the parent body"
        )
    available_codes = _canonical_code_list(
        request.get("quote_session_available_codes"), "available codes"
    )
    eligible_codes = _canonical_code_list(
        request.get("quote_session_eligible_codes"), "eligible codes"
    )
    excluded_codes = _canonical_code_list(
        request.get("quote_session_excluded_codes"), "excluded codes", allow_empty=True
    )
    if (
        available_codes != eligible_codes
        or asset_code_scope_sha256(available_codes) != capture.payload.get("available_codes_sha256")
        or asset_code_scope_sha256(eligible_codes) != capture.payload.get("eligible_codes_sha256")
        or asset_code_scope_sha256(excluded_codes) != capture.payload.get("excluded_codes_sha256")
    ):
        raise CandidateRawAuditManifestError(
            "quote capture child RawAudit full-session asset scopes are inconsistent"
        )

    audit_extra = _mapping(audit_row.extra, "child RawAudit extra")
    source_type = _string_value(audit_extra, "source_type")
    expected_market_evidence: dict[str, object] = {
        "provider_id": request_scope.get("provider_id"),
        "provider_name": request_scope.get("provider_name"),
        "source_type": source_type,
        "target_trade_date": request_scope.get("target_trade_date"),
        "universe_sha256": capture.payload.get("universe_sha256"),
        "available_codes_sha256": capture.payload.get("available_codes_sha256"),
        "eligible_codes_sha256": capture.payload.get("eligible_codes_sha256"),
        "excluded_codes": list(excluded_codes),
        "excluded_count": len(excluded_codes),
        "excluded_codes_sha256": capture.payload.get("excluded_codes_sha256"),
        "quote_rows_sha256": capture.payload.get("quote_rows_sha256"),
        "response_completed_at": capture.payload.get("response_completed_at"),
        "raw_response_sha256s": [capture.payload_reference.body_sha256],
        "quote_session_capture": capture.payload,
    }
    for row in fact_rows:
        if row.source != source_type:
            raise CandidateRawAuditManifestError(
                "quote capture child fact source differs from its RawAudit"
            )
        fact_extra = _mapping(row.extra, "quote fact extra")
        if (
            fact_extra.get(_CAPTURE_KEY) != capture.payload
            or fact_extra.get("market_publication_quote_session") != expected_market_evidence
        ):
            raise CandidateRawAuditManifestError(
                "quote capture fact session evidence differs from its child RawAudit"
            )


def _canonical_code_list(
    value: object,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    """Require one complete, sorted, unique canonical asset-code list."""

    if not _is_string_sequence(value):
        raise CandidateRawAuditManifestError(f"quote capture {label} are invalid")
    codes = tuple(value)
    if (
        (not codes and not allow_empty)
        or any(not code or code != code.strip().upper() for code in codes)
        or codes != tuple(sorted(set(codes)))
    ):
        raise CandidateRawAuditManifestError(f"quote capture {label} are invalid")
    return codes


def _mapping(value: object, label: str) -> dict[str, object]:
    """Narrow a JSON mapping with string keys at the persistence boundary."""

    if not _is_json_object(value):
        raise CandidateRawAuditManifestError(f"{label} must be a JSON object")
    return value


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    """Return whether a value is a dictionary with string keys."""

    return isinstance(value, dict) and all(isinstance(key, str) for key in value)


def _is_string_sequence(value: object) -> TypeGuard[list[str] | tuple[str, ...]]:
    """Return whether JSON scope codes are a sequence of strings."""

    return (
        isinstance(value, (list, tuple))
        and not isinstance(value, (str, bytes))
        and all(isinstance(item, str) for item in value)
    )


def _string_value(payload: Mapping[str, object], field_name: str) -> str:
    """Read one required non-empty string from a JSON mapping."""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value:
        raise CandidateRawAuditManifestError(f"quote session {field_name} is invalid")
    return value


def _positive_int(value: object, field_name: str) -> int:
    """Read one positive integer while rejecting bool-as-int JSON values."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CandidateRawAuditManifestError(f"quote session {field_name} is invalid")
    return value


def _require_sha256(value: str, field_name: str) -> None:
    """Require one lower-case SHA-256 digest in its unprefixed representation."""

    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CandidateRawAuditManifestError(f"quote session {field_name} is invalid")


def _fact_pk(value: str) -> int:
    """Parse a canonical positive quote-fact primary key."""

    if not value or not value.isascii() or not value.isdecimal() or value.startswith("0"):
        raise CandidateRawAuditManifestError("quote capture fact primary key is invalid")
    result = int(value)
    if result < 1 or str(result) != value:
        raise CandidateRawAuditManifestError("quote capture fact primary key is invalid")
    return result


__all__ = [
    "require_consistent_quote_session_capture_bindings",
    "validate_quote_session_capture_lineage",
    "validate_quote_session_request_scope",
]
