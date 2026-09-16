"""Exact read-only preservation digest parser and drift tests."""

from __future__ import annotations

import json

import pytest

from scripts.evid09_production_preservation_probe import (
    EXPECTED_COUNTS,
    EXPECTED_LABELS,
    EXPECTED_NEWS_HASH,
    EXPECTED_NEWS_ID,
    EXPECTED_ROOT_CONTENT_HASHES,
    PreservationProbeError,
    build_report,
    parse_psql_rows,
)


def _output(*, root_drift: bool = False, news_drift: bool = False, news_members: int = 11) -> str:
    payloads: dict[str, list[dict[str, object]]] = {
        label: [{"row": index, "secret": "must_not_emit"} for index in range(count)]
        for label, count in EXPECTED_COUNTS.items()
    }
    payloads["authority_roots"] = [
        {"content_hash": content_hash, "canonical_payload": "must_not_emit"}
        for content_hash in EXPECTED_ROOT_CONTENT_HASHES
    ]
    if root_drift:
        payloads["authority_roots"][0]["content_hash"] = "drifted"
    payloads["news_current"] = [
        {
            "publication_id": "drifted" if news_drift else EXPECTED_NEWS_ID,
            "publication_hash": EXPECTED_NEWS_HASH,
            "member_count": news_members,
        }
    ]
    payloads["news_current_members"] = [
        {"row": index, "secret": "must_not_emit"} for index in range(news_members)
    ]
    return "\n".join(
        f"{label}|{len(payloads[label])}|{json.dumps(payloads[label], sort_keys=True)}"
        for label in EXPECTED_LABELS
    )


def test_exact_report_hashes_rows_without_exposing_values() -> None:
    report = build_report(_output())

    assert report["decision"] == "PASS_READ_ONLY"
    assert report["four_immutable_authority_root_hashes_match"] is True
    assert report["news_current_id_hash_and_member_count_match"] is True
    assert report["raw_row_values_emitted"] is False
    assert "must_not_emit" not in json.dumps(report)
    assert report["rows"]["authority_roots"]["count"] == 4
    assert report["news_current_identity"]["publication_id"] == EXPECTED_NEWS_ID


@pytest.mark.parametrize(
    ("root_drift", "news_drift"),
    [(True, False), (False, True)],
)
def test_current_authority_or_news_drift_denies(root_drift: bool, news_drift: bool) -> None:
    assert (
        build_report(_output(root_drift=root_drift, news_drift=news_drift))["decision"]
        == "DENY_DRIFT"
    )


def test_new_verified_news_head_passes_only_with_exact_explicit_binding() -> None:
    new_id = "5713bdc5-0810-54ea-a043-119e724d773d"
    new_hash = "aed230f1d3c4e6b322e9533f594421badabe1f52fa513580ef217d2089725375"
    output = (
        _output(news_members=12)
        .replace(EXPECTED_NEWS_ID, new_id)
        .replace(EXPECTED_NEWS_HASH, new_hash)
    )

    assert build_report(output)["decision"] == "DENY_DRIFT"
    report = build_report(
        output,
        expected_news_id=new_id,
        expected_news_hash=new_hash,
        expected_news_member_count=12,
    )
    assert report["decision"] == "PASS_READ_ONLY"
    assert report["rows"]["news_current_members"]["count"] == 12
    assert report["expected_news_identity"]["publication_hash"] == new_hash
    assert (
        build_report(
            output,
            expected_news_id=new_id,
            expected_news_hash=new_hash,
            expected_news_member_count=11,
        )["decision"]
        == "DENY_DRIFT"
    )


def test_missing_label_and_count_mismatch_fail_closed() -> None:
    lines = _output().splitlines()
    with pytest.raises(PreservationProbeError, match="incomplete"):
        parse_psql_rows("\n".join(lines[:-1]))
    with pytest.raises(PreservationProbeError, match="count"):
        parse_psql_rows(lines[0].replace("|4|", "|5|", 1) + "\n" + "\n".join(lines[1:]))


def test_duplicate_or_reordered_label_denies() -> None:
    lines = _output().splitlines()
    with pytest.raises(PreservationProbeError, match="unexpected"):
        parse_psql_rows("\n".join([lines[0], lines[0], *lines[2:]]))
    with pytest.raises(PreservationProbeError, match="reordered"):
        parse_psql_rows("\n".join([lines[1], lines[0], *lines[2:]]))
