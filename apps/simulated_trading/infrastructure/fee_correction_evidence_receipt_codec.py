"""Canonical digest codec for immutable V4 fill-receipt identity fields."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol


class SimulatedFillReceiptSnapshotProtocol(Protocol):
    """Immutable V4 receipt fields used by the financial history seal."""

    pk: int
    reservation_id: int
    trade_id: int
    fill_sequence: int
    source_namespace: str
    source_version: str
    source_event_id: str
    event_kind: str
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    plan_snapshot_hash: str
    receipt_hash: str
    receipt_version: int


def receipt_snapshot_sha256(receipt: SimulatedFillReceiptSnapshotProtocol) -> str:
    """Hash the exact immutable V4 receipt locator and seal hashes.

    The schema intentionally mirrors the fee-correction history reader. The
    receipt's own hash remains separate from this row identity/content digest.
    """

    positive_ids = (
        receipt.pk,
        receipt.reservation_id,
        receipt.trade_id,
        receipt.fill_sequence,
        receipt.receipt_version,
    )
    if any(type(value) is not int or value <= 0 for value in positive_ids):
        raise ValueError("V4 receipt identifiers and version must be positive integers")
    if receipt.receipt_version not in (1, 2):
        raise ValueError("V4 receipt version is unsupported")
    text_fields = (
        receipt.source_namespace,
        receipt.source_version,
        receipt.source_event_id,
        receipt.event_kind,
    )
    if any(type(value) is not str or not value for value in text_fields):
        raise ValueError("V4 receipt locator fields must be nonempty text")
    digest_fields = (
        receipt.source_event_payload_hash,
        receipt.source_event_snapshot_hash,
        receipt.economic_request_hash,
        receipt.economics_snapshot_hash,
        receipt.plan_snapshot_hash,
        receipt.receipt_hash,
    )
    if any(not _is_lower_sha256(value) for value in digest_fields):
        raise ValueError("V4 receipt fields must carry lowercase SHA-256 digests")
    payload: dict[str, str | int] = {
        "receipt_id": receipt.pk,
        "reservation_id": receipt.reservation_id,
        "trade_id": receipt.trade_id,
        "fill_sequence": receipt.fill_sequence,
        "source_namespace": receipt.source_namespace,
        "source_version": receipt.source_version,
        "source_event_id": receipt.source_event_id,
        "event_kind": receipt.event_kind,
        "source_event_payload_hash": receipt.source_event_payload_hash,
        "source_event_snapshot_hash": receipt.source_event_snapshot_hash,
        "economic_request_hash": receipt.economic_request_hash,
        "economics_snapshot_hash": receipt.economics_snapshot_hash,
        "plan_snapshot_hash": receipt.plan_snapshot_hash,
        "receipt_hash": receipt.receipt_hash,
        "receipt_version": receipt.receipt_version,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_lower_sha256(value: object) -> bool:
    """Narrow a stored receipt digest to exact lowercase SHA-256 text."""

    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


__all__ = ["SimulatedFillReceiptSnapshotProtocol", "receipt_snapshot_sha256"]
