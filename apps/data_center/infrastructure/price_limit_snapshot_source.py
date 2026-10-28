"""Strict RawPayload reference conversion and exact price-limit replay."""

from __future__ import annotations

from typing import cast

from apps.data_center.application.price_limit_capture import RetainedPriceLimitCapture
from apps.data_center.application.price_limit_response_capture import (
    ExactPriceLimitRequestScope,
    replay_exact_tushare_price_limit_values,
)
from apps.data_center.application.price_limit_snapshot import price_limit_candidate_from_capture
from apps.data_center.application.provider_response_payload import (
    ProviderResponsePayloadReference,
)
from apps.data_center.domain.price_limit_snapshot import (
    PriceLimitRawReference,
    PriceLimitSnapshotCandidate,
    PriceLimitSnapshotError,
)
from apps.data_center.domain.raw_landing import RawPayload
from core.exceptions import DataFetchError

_DATASET_KEY = "equity.price.limit"
_API_NAME = "stk_limit"


def price_limit_raw_reference_from_payload(value: object) -> PriceLimitRawReference:
    """Decode the exact persisted raw-reference schema and reject noncanonical JSON."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _corrupt_reference()
    payload = cast(dict[str, object], value)
    required = {
        "payload_id",
        "payload_hash",
        "record_digest",
        "body_sha256",
        "retained_content_sha256",
        "original_body_retained",
        "retained_content_encoding",
        "body_size_bytes",
        "response_completed_at",
        "provider_name",
        "dataset_key",
        "transport",
        "time_semantics",
        "request_scope_sha256",
    }
    fields = set(payload)
    if fields not in (required, required | {"run_id"}):
        raise _corrupt_reference()
    if payload.get("time_semantics") != "local_response_body_completion":
        raise _corrupt_reference()
    response_payload = {key: item for key, item in payload.items() if key != "request_scope_sha256"}
    try:
        response_reference = ProviderResponsePayloadReference.from_payload(response_payload)
        scope_hash = payload.get("request_scope_sha256")
        if type(scope_hash) is not str:
            raise _corrupt_reference()
        reference = PriceLimitRawReference(
            payload_id=response_reference.payload_id,
            payload_hash=response_reference.payload_hash,
            record_digest=response_reference.record_digest,
            body_sha256=response_reference.body_sha256,
            retained_content_sha256=response_reference.retained_content_sha256,
            original_body_retained=response_reference.original_body_retained,
            retained_content_encoding=response_reference.retained_content_encoding,
            body_size_bytes=response_reference.body_size_bytes,
            response_completed_at=response_reference.response_completed_at,
            provider_name=response_reference.provider_name,
            dataset_key=response_reference.dataset_key,
            transport=response_reference.transport,
            request_scope_sha256=scope_hash,
            run_id=response_reference.run_id,
        )
    except (TypeError, ValueError) as exc:
        raise _corrupt_reference() from exc
    if reference.to_payload() != payload:
        raise _corrupt_reference()
    return reference


def replay_price_limit_snapshot_candidate(
    raw_payload: RawPayload,
    candidate: PriceLimitSnapshotCandidate,
) -> PriceLimitSnapshotCandidate:
    """Rebuild one candidate from its original response and compare exact decimal text."""

    if type(raw_payload) is not RawPayload or type(candidate) is not PriceLimitSnapshotCandidate:
        raise DataFetchError(
            "Price-limit replay inputs are not typed",
            code="PRICE_LIMIT_SNAPSHOT_SOURCE_INVALID",
        )
    raw_reference = candidate.raw_reference
    try:
        response_reference = ProviderResponsePayloadReference.from_payload(
            {
                key: value
                for key, value in raw_reference.to_payload().items()
                if key != "request_scope_sha256"
            }
        )
        scope = ExactPriceLimitRequestScope(
            provider_id=candidate.provider_id,
            provider_name=candidate.provider_name,
            dataset_key=_DATASET_KEY,
            api_name=_API_NAME,
            asset_code=candidate.asset_code,
            trade_date=candidate.effective_trade_date,
        )
        values = replay_exact_tushare_price_limit_values(
            raw_payload,
            response_reference,
            scope=scope,
        )
        replayed = price_limit_candidate_from_capture(
            RetainedPriceLimitCapture(scope, values, response_reference)
        )
    except DataFetchError:
        raise
    except PriceLimitSnapshotError as exc:
        raise DataFetchError(str(exc), code=exc.code) from exc
    except (TypeError, ValueError) as exc:
        raise DataFetchError(
            "Price-limit retained response could not be reconstructed",
            code="PRICE_LIMIT_SNAPSHOT_SOURCE_INVALID",
        ) from exc
    if (
        replayed.content_hash != candidate.content_hash
        or replayed.to_content_payload() != candidate.to_content_payload()
        or str(replayed.lower_limit_price) != str(candidate.lower_limit_price)
        or str(replayed.upper_limit_price) != str(candidate.upper_limit_price)
    ):
        raise DataFetchError(
            "Price-limit candidate differs from its exact retained response",
            code="PRICE_LIMIT_SNAPSHOT_SOURCE_CONTENT_MISMATCH",
        )
    return replayed


def _corrupt_reference() -> DataFetchError:
    """Create the stable failure for malformed persisted raw-reference JSON."""

    return DataFetchError(
        "Persisted price-limit raw reference is invalid",
        code="PRICE_LIMIT_SNAPSHOT_RAW_REFERENCE_INVALID",
    )
