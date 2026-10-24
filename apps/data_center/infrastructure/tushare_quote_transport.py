"""Validate response-level Tushare quote provenance at its boundary."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .tushare_client import TushareResponseEvidence


def _optional_quote_transport_extra(quote: object) -> dict[str, Any]:
    """Read optional quote provenance without inventing response evidence."""

    raw_extra = getattr(quote, "extra", None)
    if not isinstance(raw_extra, Mapping):
        return {}

    extra = {key: value for key, value in raw_extra.items() if isinstance(key, str)}
    extra.pop("actual_source", None)
    evidence_keys = (
        "raw_payload_hash",
        "raw_payload_scope",
        "response_completed_at",
        "source_record_id",
    )
    if not any(key in extra for key in evidence_keys):
        return extra

    raw_payload_hash = extra.get("raw_payload_hash")
    raw_payload_scope = extra.get("raw_payload_scope")
    completed_at_text = extra.get("response_completed_at")
    try:
        if (
            not isinstance(raw_payload_hash, str)
            or raw_payload_scope != "batch_response_body"
            or not isinstance(completed_at_text, str)
        ):
            raise ValueError("incomplete Tushare quote response evidence")
        completed_at = datetime.fromisoformat(completed_at_text.replace("Z", "+00:00"))
        TushareResponseEvidence(
            body_sha256=raw_payload_hash,
            response_completed_at=completed_at,
            raw_payload_scope=raw_payload_scope,
        )
    except (TypeError, ValueError):
        for key in evidence_keys:
            extra.pop(key, None)
    source_record_id = extra.get("source_record_id")
    if "source_record_id" in extra and (
        not isinstance(source_record_id, str)
        or not source_record_id.strip()
        or len(source_record_id) > 200
    ):
        extra.pop("source_record_id", None)
    return extra
