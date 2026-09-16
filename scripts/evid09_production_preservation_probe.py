"""Collect exact EVID-09 production rowset digests without emitting row contents.

Run on the VPS host through trusted SSH as ``python3 -``. PostgreSQL work is
one REPEATABLE READ, READ ONLY transaction; neither source nor credentials are
written to the host filesystem by this probe.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from typing import cast

EXPECTED_LABELS = (
    "authority_roots",
    "authority_revocations",
    "publication_policies",
    "dataset_contracts",
    "provider_bindings",
    "owner_registrations",
    "news_current",
    "news_current_members",
)
EXPECTED_COUNTS = {
    "authority_roots": 4,
    "authority_revocations": 0,
    "publication_policies": 14,
    "dataset_contracts": 10,
    "provider_bindings": 15,
    "owner_registrations": 10,
    "news_current": 1,
    "news_current_members": 11,
}
EXPECTED_ROOT_CONTENT_HASHES = (
    "47d71a2f7e7aaea49a181d2db86a3375af330018a191a4e7fcf89b4f6e26acbb",
    "50d570281ddaab2e0f49a5e2240a07f3d3f681ae068f2810f02f77bb8a51efaa",
    "584dd04ec11bb1ff40284916a977725286fd40763841403c99fc2402ab82a1ae",
    "c6431aa9f724519e047b75a3ef292a953a288215c87127cf1a5b9d76fbcb061c",
)
EXPECTED_NEWS_ID = "584dfaa8-6f2b-596d-8866-4e5f1b2daa01"
EXPECTED_NEWS_HASH = "c71a4f36417f881883c11594f5e9b6cd2084f146dd17655d3822a43a29663e8f"

SQL = """\
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '35s';
SELECT 'authority_roots', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.content_hash)::text, '[]')
  FROM account_owner_tenant_authority_v3_ledger t;
SELECT 'authority_revocations', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.content_hash)::text, '[]')
  FROM account_owner_tenant_authority_v3_revocation_ledger t;
SELECT 'publication_policies', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.dataset_key, t.contract_version, t.schema_version, t.policy_version)::text, '[]')
  FROM data_center_dataset_publication_policy t;
SELECT 'dataset_contracts', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.dataset_key, t.contract_version, t.schema_version)::text, '[]')
  FROM data_center_dataset_contract t;
SELECT 'provider_bindings', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.dataset_key, t.contract_version, t.schema_version, t.provider, t.capability)::text, '[]')
  FROM data_center_dataset_provider_binding t;
SELECT 'owner_registrations', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.dataset_key)::text, '[]')
  FROM data_center_data_owner_registration t;
SELECT 'news_current', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.publication_id)::text, '[]')
  FROM data_center_canonical_publication t
 WHERE t.dataset_key = 'market.news' AND t.publication_key = 'current' AND t.state = 'published';
SELECT 'news_current_members', count(*), coalesce(jsonb_agg(to_jsonb(t) ORDER BY t.natural_key, t.member_id)::text, '[]')
  FROM data_center_publication_member t
 WHERE t.publication_id IN (
   SELECT publication_id FROM data_center_canonical_publication
    WHERE dataset_key = 'market.news' AND publication_key = 'current' AND state = 'published'
 );
ROLLBACK;
"""


class PreservationProbeError(ValueError):
    """Reject incomplete or drifted preservation evidence."""


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PreservationProbeError("rowset member is not an object")
    return cast(dict[str, object], value)


def parse_psql_rows(output: str) -> dict[str, dict[str, object]]:
    """Parse only fixed-label rowset digests and discard raw row data."""

    result: dict[str, dict[str, object]] = {}
    for line in output.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3 or parts[0] not in EXPECTED_LABELS or parts[0] in result:
            raise PreservationProbeError("unexpected PostgreSQL snapshot output")
        label, raw_count, raw_rows = parts
        try:
            count = int(raw_count)
            parsed = json.loads(raw_rows)
        except (ValueError, json.JSONDecodeError) as exc:
            raise PreservationProbeError("invalid PostgreSQL snapshot rowset") from exc
        if not isinstance(parsed, list) or len(parsed) != count:
            raise PreservationProbeError("PostgreSQL row count does not match rowset")
        rows = [_object(item) for item in cast(list[object], parsed)]
        result[label] = {
            "count": count,
            "rowset_sha256": hashlib.sha256(raw_rows.encode("utf-8")).hexdigest(),
            "_rows": rows,
        }
    if tuple(result) != EXPECTED_LABELS:
        raise PreservationProbeError("PostgreSQL snapshot labels are incomplete or reordered")
    return result


def build_report(
    output: str,
    *,
    expected_news_id: str = EXPECTED_NEWS_ID,
    expected_news_hash: str = EXPECTED_NEWS_HASH,
    expected_news_member_count: int = 11,
) -> dict[str, object]:
    """Produce a secret-free report against an explicitly bound News head."""

    parsed = parse_psql_rows(output)
    roots = cast(list[dict[str, object]], parsed["authority_roots"]["_rows"])
    news = cast(list[dict[str, object]], parsed["news_current"]["_rows"])
    root_hashes = tuple(sorted(str(row.get("content_hash")) for row in roots))
    expected_counts = {**EXPECTED_COUNTS, "news_current_members": expected_news_member_count}
    counts_match = all(
        parsed[label]["count"] == expected for label, expected in expected_counts.items()
    )
    root_hashes_match = root_hashes == EXPECTED_ROOT_CONTENT_HASHES
    news_identity_match = (
        len(news) == 1
        and str(news[0].get("publication_id")) == expected_news_id
        and news[0].get("publication_hash") == expected_news_hash
        and news[0].get("member_count") == expected_news_member_count
    )
    news_identity: dict[str, object] = {
        "publication_id": str(news[0].get("publication_id")) if len(news) == 1 else None,
        "publication_hash": str(news[0].get("publication_hash")) if len(news) == 1 else None,
        "member_count": news[0].get("member_count") if len(news) == 1 else None,
        "published_at": news[0].get("published_at") if len(news) == 1 else None,
    }
    rows: dict[str, dict[str, object]] = {
        label: {
            "count": parsed[label]["count"],
            "rowset_sha256": parsed[label]["rowset_sha256"],
        }
        for label in EXPECTED_LABELS
    }
    return {
        "schema": "evid09.production-preservation-snapshot.v1",
        "observed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "transaction": "REPEATABLE READ READ ONLY; ROLLBACK",
        "candidate_commit": "891c40c5769897931b2b513e92df6f9ba72631ea",
        "target_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
        "rows": rows,
        "expected_counts_match": counts_match,
        "four_immutable_authority_root_hashes_match": root_hashes_match,
        "news_current_id_hash_and_member_count_match": news_identity_match,
        "expected_news_identity": {
            "publication_id": expected_news_id,
            "publication_hash": expected_news_hash,
            "member_count": expected_news_member_count,
        },
        "news_current_identity": news_identity,
        "decision": (
            "PASS_READ_ONLY"
            if counts_match and root_hashes_match and news_identity_match
            else "DENY_DRIFT"
        ),
        "raw_row_values_emitted": False,
        "business_dml_performed": False,
    }


def main() -> int:
    """Run the exact production PostgreSQL read-only query on the VPS host."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-news-id")
    parser.add_argument("--expected-news-hash")
    parser.add_argument("--expected-news-member-count", type=int)
    args = parser.parse_args()
    supplied = (
        args.expected_news_id,
        args.expected_news_hash,
        args.expected_news_member_count,
    )
    if any(value is not None for value in supplied):
        if (
            any(value is None for value in supplied)
            or not re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                args.expected_news_id,
            )
            or not re.fullmatch(r"[0-9a-f]{64}", args.expected_news_hash)
            or args.expected_news_member_count < 1
        ):
            parser.error("all three exact, valid News-head fields are required")
    expected_news_id = args.expected_news_id or EXPECTED_NEWS_ID
    expected_news_hash = args.expected_news_hash or EXPECTED_NEWS_HASH
    expected_news_member_count = args.expected_news_member_count or 11
    command = [
        "docker",
        "exec",
        "-i",
        "agomtradepro-postgres-1",
        "sh",
        "-lc",
        'exec psql -X -q -A -t -F "|" -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"',
    ]
    try:
        completed = subprocess.run(
            command, input=SQL, text=True, capture_output=True, timeout=90, check=False
        )
        if completed.returncode != 0:
            raise PreservationProbeError("production read-only PostgreSQL query failed")
        report = build_report(
            completed.stdout,
            expected_news_id=expected_news_id,
            expected_news_hash=expected_news_hash,
            expected_news_member_count=expected_news_member_count,
        )
    except (OSError, subprocess.TimeoutExpired, PreservationProbeError) as exc:
        print(f"DENY: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["decision"] == "PASS_READ_ONLY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
