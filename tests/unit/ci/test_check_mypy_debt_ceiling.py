"""Contract tests for the full-production mypy debt ceiling."""

from __future__ import annotations

from collections import Counter

from scripts.check_mypy_debt_ceiling import (
    build_payload,
    find_count_changes,
    parse_error_counts,
    validate_payload,
)


def test_parse_error_counts_normalizes_paths_and_groups_codes() -> None:
    counts = parse_error_counts(
        "apps\\example.py:10: error: Missing annotation [no-untyped-def]\n"
        "apps/example.py:20:3: error: Missing generic [type-arg]\n"
    )

    assert counts == {"apps/example.py": Counter({"no-untyped-def": 1, "type-arg": 1})}


def test_find_count_changes_rejects_transfers_between_files() -> None:
    ceiling = {
        "apps/a.py": {"no-untyped-def": 2},
        "apps/b.py": {"type-arg": 1},
    }
    candidate = {
        "apps/a.py": {"no-untyped-def": 1},
        "apps/b.py": {"type-arg": 2},
    }

    increases, decreases = find_count_changes(candidate, ceiling)

    assert increases == ["apps/b.py: type-arg increased from 1 to 2"]
    assert decreases == ["apps/a.py: no-untyped-def decreased from 2 to 1"]


def test_build_payload_is_exact_and_self_consistent() -> None:
    payload = build_payload({"core/example.py": Counter({"no-any-return": 2, "arg-type": 1})})

    assert payload["summary"] == {"errors": 3, "files_with_errors": 1}
    assert validate_payload(payload) == []


def test_validate_payload_rejects_stale_summary() -> None:
    payload = build_payload({"core/example.py": Counter({"arg-type": 1})})
    payload["summary"]["errors"] = 2

    assert validate_payload(payload) == ["summary does not match per-file, per-code module counts"]
