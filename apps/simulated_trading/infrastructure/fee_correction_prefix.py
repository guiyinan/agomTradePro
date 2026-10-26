"""Canonical account-local prefix hashes for append-only fee correction events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

from core.exceptions import BusinessLogicError

_HEX = frozenset("0123456789abcdef")


def _digest(value: object) -> bool:
    """Return whether one value is a lowercase SHA-256 digest."""

    return type(value) is str and len(value) == 64 and all(character in _HEX for character in value)


def _utc_text(value: datetime) -> str:
    """Serialize one aware timestamp at UTC microsecond precision."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise BusinessLogicError(
            "费用更正前缀时间必须带时区",
            code="FEE_CORRECTION_HISTORY_INVALID",
        )
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def fee_correction_account_genesis_sha256(account_id: int) -> str:
    """Return the stable account-scoped empty correction-prefix digest."""

    if type(account_id) is not int or account_id <= 0:
        raise BusinessLogicError(
            "费用更正前缀账户身份无效",
            code="FEE_CORRECTION_HISTORY_INVALID",
        )
    payload: dict[str, object] = {
        "schema": "simulated-fee-correction-account-prefix-genesis.v1",
        "account_id": account_id,
    }
    return _sha256_json(payload)


def fee_correction_account_prefix_sha256(
    *,
    account_id: int,
    account_revision: int,
    predecessor_sha256: str,
    request_payload_sha256: str,
    cash_delta: Decimal,
    authority_snapshot_sha256: str,
    posted_at: datetime,
    posting_date: date,
) -> str:
    """Hash one immutable account-local event and its validated predecessor."""

    if (
        type(account_id) is not int
        or account_id <= 0
        or type(account_revision) is not int
        or account_revision <= 0
        or not _digest(predecessor_sha256)
        or not _digest(request_payload_sha256)
        or not _digest(authority_snapshot_sha256)
        or type(cash_delta) is not Decimal
        or not cash_delta.is_finite()
        or not _is_cent_denominated(cash_delta)
        or type(posting_date) is not date
    ):
        raise BusinessLogicError(
            "费用更正账户前缀字段无效",
            code="FEE_CORRECTION_HISTORY_INVALID",
        )
    payload: dict[str, object] = {
        "schema": "simulated-fee-correction-account-prefix.v1",
        "account_id": account_id,
        "account_revision": account_revision,
        "predecessor_sha256": predecessor_sha256,
        "request_payload_sha256": request_payload_sha256,
        "cash_delta": format(cash_delta, ".2f"),
        "authority_snapshot_sha256": authority_snapshot_sha256,
        "posted_at": _utc_text(posted_at),
        "posting_date": posting_date.isoformat(),
    }
    return _sha256_json(payload)


def _sha256_json(payload: dict[str, object]) -> str:
    """Serialize one typed canonical payload to lowercase SHA-256."""

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _is_cent_denominated(value: Decimal) -> bool:
    """Check sub-cent digits from the Decimal tuple without context rounding."""

    exponent = value.as_tuple().exponent
    if type(exponent) is not int:
        return False
    if exponent >= -2:
        return True
    discarded_places = -2 - exponent
    digits = value.as_tuple().digits
    return not any(digits[-discarded_places:])


__all__ = [
    "fee_correction_account_genesis_sha256",
    "fee_correction_account_prefix_sha256",
]
