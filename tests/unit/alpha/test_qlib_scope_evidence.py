"""Suspension exclusions must be tied to a successful build date and scope."""

from datetime import date

from apps.alpha.infrastructure.qlib_scope_evidence import (
    read_scope_suspensions,
    write_scope_evidence,
)

DAY = date(2026, 9, 18)
CODES = ["000001.SZ", "000002.SZ"]


def test_evidence_is_date_and_scope_bound(tmp_path):
    write_scope_evidence(tmp_path, DAY, CODES, {CODES[1]: date(2026, 9, 17)})
    assert read_scope_suspensions(str(tmp_path), DAY, CODES) == {CODES[1]: "2026-09-17"}
    assert read_scope_suspensions(str(tmp_path), date(2026, 9, 21), CODES) == {}
    assert read_scope_suspensions(str(tmp_path), DAY, [*CODES, "000003.SZ"]) == {}
    assert read_scope_suspensions(str(tmp_path), DAY, [CODES[0]]) == {}


def test_invalid_or_missing_suspension_evidence_fails_closed(tmp_path):
    assert read_scope_suspensions(str(tmp_path), DAY, CODES) == {}
    write_scope_evidence(tmp_path, DAY, CODES, {CODES[1]: DAY})
    assert read_scope_suspensions(str(tmp_path), DAY, CODES) == {}
    (tmp_path / "build_evidence" / f"{DAY}.json").write_text("broken")
    assert read_scope_suspensions(str(tmp_path), DAY, CODES) == {}


def test_later_build_replaces_old_exclusions(tmp_path):
    write_scope_evidence(tmp_path, DAY, CODES, {CODES[1]: date(2026, 9, 17)})
    write_scope_evidence(tmp_path, DAY, CODES, {})
    assert read_scope_suspensions(str(tmp_path), DAY, CODES) == {}
