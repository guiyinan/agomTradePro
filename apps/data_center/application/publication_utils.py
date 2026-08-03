"""Shared deterministic helpers for canonical publication writers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from apps.data_center.domain.control_plane import PublicationFactReference


def publication_hash(references: Sequence[PublicationFactReference]) -> str:
    """Return a stable hash for an ordered set of publication references."""

    payload = [
        {
            "natural_key": reference.natural_key,
            "source": reference.source,
            "fact_table": reference.fact_table,
            "fact_pk": reference.fact_pk,
            "observed_at": reference.observed_at.isoformat(),
            "raw_payload_hash": reference.raw_payload_hash,
            "quality_status": reference.quality_status,
            "revision_number": reference.revision_number,
        }
        for reference in references
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()
