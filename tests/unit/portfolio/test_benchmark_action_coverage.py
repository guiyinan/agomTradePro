"""A Portfolio reviewer cannot replace the approved independent source or extend its scope."""

import json
from datetime import UTC, datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apps.portfolio.domain.policy_benchmark_corporate_action import (
    PolicyBenchmarkCorporateActionSourceRef,
)
from apps.portfolio.domain.policy_benchmark_daily_valuation import BenchmarkDayUnavailable
from apps.portfolio.infrastructure.benchmark_action_coverage import verify_no_action_coverage
from tests.support.portfolio_benchmark_action_coverage import (
    action_coverage_member,
    make_action_source,
)


def _packet(member):
    out = BytesIO()
    with ZipFile(out, "w") as archive:
        archive.writestr("action-coverage.json", member)
    return out.getvalue()


@pytest.mark.parametrize(
    "variant",
    [
        "exact",
        "unapproved_key",
        "different_asset",
        "different_interval",
        "incomplete",
        "event_present",
        "bool_count",
        "after_read",
        "signature_edit",
        "source_edit",
    ],
)
def test_only_exact_independently_signed_no_action_coverage_is_eligible(variant):
    now = datetime(2026, 11, 24, 8, tzinfo=UTC)
    cutoff = now - timedelta(minutes=5)
    start = cutoff - timedelta(days=1)
    template = PolicyBenchmarkCorporateActionSourceRef(
        owner="portfolio",
        artifact_type="benchmark_corporate_action_source_definition",
        artifact_id="registrar-entitlements",
        artifact_version="v1",
        content_hash="a" * 64,
        ordinal=0,
        recorded_at=start - timedelta(days=2),
        valid_until=now + timedelta(days=2),
    )
    ref, definition, key = make_action_source(template)
    content = action_coverage_member(
        ref,
        definition,
        Ed25519PrivateKey.generate() if variant == "unapproved_key" else key,
        asset="000001.SZ" if variant == "different_asset" else "600000.SH",
        covered_from=start + timedelta(seconds=1) if variant == "different_interval" else start,
        cutoff=cutoff,
        issued_at=now + timedelta(seconds=1) if variant == "after_read" else now,
        event_count={"event_present": 1, "bool_count": False}.get(variant, 0),
        complete=variant != "incomplete",
    )
    if variant in {"signature_edit", "source_edit"}:
        doc = json.loads(content)
        if variant == "signature_edit":
            doc["statement"]["revision_id"] = "modified"
        else:
            doc["source_definition"]["artifact_version"] = "other"
        content = json.dumps(doc).encode()
    inputs = {
        "raw_packet": _packet(content),
        "source_ref": ref,
        "asset": "600000.SH",
        "covered_from": start,
        "cutoff": cutoff,
        "as_of": now,
    }
    if variant == "exact":
        assert len(verify_no_action_coverage(**inputs)) == 64
    else:
        with pytest.raises(BenchmarkDayUnavailable, match="coverage unavailable"):
            verify_no_action_coverage(**inputs)
