"""Fresh, source-bound EVID-09 pre-action gate tests without SSH mutation."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from scripts import evid09_live_image_preflight as gate


def _reports(
    now: datetime,
) -> tuple[dict[str, object], dict[str, object], dict[str, dict[str, object]]]:
    checkpoint = gate._read_sealed_json(gate.CHECKPOINT)
    news_evidence = gate._read_sealed_json(gate.NEWS_EVIDENCE)
    binding = cast(
        dict[str, object],
        cast(
            dict[str, object],
            cast(dict[str, object], checkpoint["collectors"])["production_preservation"],
        )["explicit_expected_news"],
    )
    rowsets = cast(
        dict[str, dict[str, object]],
        cast(dict[str, object], news_evidence["read_only_preservation"])["rowsets"],
    )
    rows = {
        label: {"count": item["count"], "rowset_sha256": item["sha256"]}
        for label, item in rowsets.items()
    }
    observed = now.isoformat().replace("+00:00", "Z")
    reports = {
        "preservation": {
            "decision": "PASS_READ_ONLY",
            "candidate_commit": "891c40c5769897931b2b513e92df6f9ba72631ea",
            "target_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
            "expected_news_identity": {
                "publication_id": binding["publication_id"],
                "publication_hash": binding["publication_hash"],
                "member_count": binding["member_count"],
            },
            "news_current_identity": {
                "publication_id": binding["publication_id"],
                "publication_hash": binding["publication_hash"],
                "member_count": binding["member_count"],
            },
            "expected_counts_match": True,
            "news_current_id_hash_and_member_count_match": True,
            "four_immutable_authority_root_hashes_match": True,
            "raw_row_values_emitted": False,
            "business_dml_performed": False,
            "rows": rows,
            "observed_at_utc": observed,
        },
        "https": {
            "decision": "PASS_READ_ONLY",
            "protected_query_unauthenticated_status": 401,
            "protected_query_authenticated_status": 200,
            "https_statuses": gate.REQUIRED_HTTPS_STATUSES,
            "tls_default_trust_used": True,
            "secret_values_emitted": False,
            "decision_gate_cleared": False,
            "retained_up_target": {
                "job": "agomtradepro",
                "instance": "web:8000",
                "value": 1,
                "sample_at_utc": observed,
            },
            "observed_at_utc": observed,
        },
        "compose": {
            "decision": "PASS_READ_ONLY",
            "normalized_difference_paths": [],
            "all_startup_mutation_flags_disabled": True,
            "compose_or_secret_values_emitted": False,
            "rendered_web_config_sha256": {
                "current": "0819d4dc97ff7408ad0319a767fc05f67f289ccd59cfe44bd122c3e1f48d68cb",
                "target": "0819d4dc97ff7408ad0319a767fc05f67f289ccd59cfe44bd122c3e1f48d68cb",
            },
        },
        "target_runtime": {
            "decision": "PASS_READ_ONLY",
            "target_source_commit": "6760c9aa1607c55e9ae0fd0bcb5435ca32080b0b",
            "news_current_publication_id": binding["publication_id"],
            "news_current_publication_hash": binding["publication_hash"],
            "news_current_selected_count": binding["member_count"],
            "four_strict_policies_present": True,
            "selected_rows_match_when_usable": True,
            "business_dml_performed": False,
            "observed_at_utc": observed,
        },
    }
    return checkpoint, news_evidence, reports


def test_exact_fresh_reports_pass_pre_action_only() -> None:
    now = datetime.now(UTC)
    checkpoint, news_evidence, reports = _reports(now)

    report = gate.validate_reports(checkpoint, news_evidence, reports, now=now)

    assert report["decision"] == "PASS_PRE_ACTION_ONLY"
    assert report["live_web_switch_performed"] is False
    assert report["tui02_observation_reset_performed"] is False


@pytest.mark.parametrize(
    ("name", "field", "value", "reason"),
    [
        ("preservation", "candidate_commit", "wrong", "preservation"),
        ("https", "protected_query_authenticated_status", 401, "HTTPS"),
        ("compose", "normalized_difference_paths", ["web.environment.DATABASE_URL"], "Compose"),
        ("target_runtime", "news_current_selected_count", 11, "target OCI"),
    ],
)
def test_identity_https_compose_or_target_drift_denies(
    name: str, field: str, value: object, reason: str
) -> None:
    now = datetime.now(UTC)
    checkpoint, news_evidence, reports = _reports(now)
    reports[name][field] = value

    with pytest.raises(gate.LiveImagePreflightError, match=reason):
        gate.validate_reports(checkpoint, news_evidence, reports, now=now)


def test_business_rowset_or_news_drifts_deny() -> None:
    now = datetime.now(UTC)
    checkpoint, news_evidence, reports = _reports(now)
    changed = copy.deepcopy(reports)
    rows = cast(dict[str, dict[str, object]], changed["preservation"]["rows"])
    rows["news_current_members"]["rowset_sha256"] = "drifted"
    with pytest.raises(gate.LiveImagePreflightError, match="rowset drift"):
        gate.validate_reports(checkpoint, news_evidence, changed, now=now)
    changed = copy.deepcopy(reports)
    identity = cast(dict[str, object], changed["preservation"]["expected_news_identity"])
    identity["member_count"] = 13
    with pytest.raises(gate.LiveImagePreflightError, match="preservation"):
        gate.validate_reports(checkpoint, news_evidence, changed, now=now)


def test_expired_or_future_remote_samples_deny() -> None:
    now = datetime.now(UTC)
    checkpoint, news_evidence, reports = _reports(now)
    reports["target_runtime"]["observed_at_utc"] = (now - timedelta(minutes=3)).isoformat()
    with pytest.raises(gate.LiveImagePreflightError, match="not fresh"):
        gate.validate_reports(checkpoint, news_evidence, reports, now=now)


def test_rejected_remote_exit_never_parses_a_passing_body() -> None:
    with pytest.raises(gate.LiveImagePreflightError, match="natural exit"):
        gate._report(gate.RemoteResult(1, json.dumps({"decision": "PASS_READ_ONLY"})), "test")
