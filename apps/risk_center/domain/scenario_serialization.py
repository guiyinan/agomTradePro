"""Legacy Scenario hashing and paired evidence snapshot encoding.

The legacy UTC and Decimal normalization semantics intentionally remain unchanged.
New portfolio-risk snapshots use their separate lossless serializer.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum


def canonical_scenario_snapshot_json(payload: Mapping[str, object]) -> str:
    """Serialize typed scenario evidence as immutable, sorted JSON text."""

    return json.dumps(
        _json_value(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_content_hash(payload: Mapping[str, object]) -> str:
    """Return the canonical SHA-256 digest for JSON-safe business content."""

    encoded = canonical_scenario_snapshot_json(payload).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def scenario_run_snapshot_hash(
    *,
    input_snapshot_json: str,
    result_snapshot_json: str,
) -> str:
    """Bind the complete immutable input and result snapshots into run identity."""

    return stable_content_hash(
        {
            "input_snapshot_json": input_snapshot_json,
            "result_snapshot_json": result_snapshot_json,
        }
    )


def _json_value(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value
