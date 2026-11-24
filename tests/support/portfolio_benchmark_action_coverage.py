"""An independent test publisher with a key pinned into the approved methodology."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.portfolio.infrastructure.benchmark_action_coverage import (
    COVERAGE_BASIS,
    REPORT_SCHEMA,
    SOURCE_SCHEMA,
)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def make_action_source(ref):
    """Create an isolated publisher and a source-ref for the real approval ledger."""
    key = Ed25519PrivateKey.generate()
    definition = {
        "schema": SOURCE_SCHEMA,
        "owner": ref.owner,
        "artifact_type": ref.artifact_type,
        "artifact_id": ref.artifact_id,
        "artifact_version": ref.artifact_version,
        "coverage_basis": COVERAGE_BASIS,
        "public_key": base64.b64encode(key.public_key().public_bytes_raw()).decode(),
    }
    resolved = replace(
        ref, ordinal=0, content_hash=hashlib.sha256(canonical(definition)).hexdigest()
    )
    return resolved, definition, key


def action_coverage_member(
    ref, definition, key, *, asset, covered_from, cutoff, issued_at, **changes
):
    """Return the signed action-coverage.json member; signing authority stays outside the application."""
    statement = {
        "schema": REPORT_SCHEMA,
        "source_content_hash": ref.content_hash,
        "asset": asset,
        "covered_from": covered_from.astimezone(UTC).isoformat(),
        "cutoff": cutoff.astimezone(UTC).isoformat(),
        "issued_at": issued_at.astimezone(UTC).isoformat(),
        "revision_id": uuid4().hex,
        "complete": True,
        "event_count": 0,
    }
    statement.update(changes)
    return canonical(
        {
            "source_definition": definition,
            "statement": statement,
            "signature": base64.b64encode(key.sign(canonical(statement))).decode(),
        }
    )
