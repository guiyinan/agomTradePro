"""Owner-safe projection of held-security financial disclosure facts."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from apps.terminal.application.tui_holding_disclosure_result import (
    project_tui_holding_disclosure_result,
)
from apps.terminal.infrastructure.tui_metadata_runtime_injection_simulated_trading import (
    RUNTIME_SIMULATED_TRADING_ACTIONS,
)

_ACTION = "simulated-trading.holding-disclosures"
_AS_OF = "2026-11-10T08:00:00+08:00"
_READ_PARAMS = {"account_id": 41, "asset_code": "600000.SH"}


def _row(**overrides: object) -> dict[str, object]:
    """Build one disclosed fact with distinct source clocks."""

    row: dict[str, object] = {
        "asset_code": "600000.SH",
        "metric_code": "net_profit",
        "value": "1250000.00",
        "unit": "CNY",
        "period_end": "2025-12-31",
        "period_type": "annual",
        "report_date": "2026-03-28",
        "announced_at": "2026-03-28",
        "available_at": "2026-03-29T00:00:00+08:00",
        "fetched_at": "2026-03-29T02:15:30+08:00",
        "source": "eastmoney",
        "source_record_id": "private-record-41",
        "raw_payload_hash": "f" * 64,
    }
    row.update(overrides)
    return row


def _payload(**overrides: object) -> dict[str, object]:
    """Build one in-scope held-security response."""

    payload: dict[str, object] = {
        "account_id": 41,
        "asset_code": "600000.SH",
        "as_of": _AS_OF,
        "outcome": "partial",
        "scope": "simulation_only",
        "read_only": True,
        "must_not_use_for_decision": True,
        "must_not_execute": True,
        "coverage_note": "仅包含当前已发布的财务指标，不能代表完整披露覆盖。",
        "blocked_reason": None,
        "freshness": "unknown",
        "reliability": "unknown",
        "rows": [_row()],
    }
    payload.update(overrides)
    return payload


def _project(
    payload: object,
    *,
    params: dict[str, object] | None = _READ_PARAMS,
    http_status: int = 200,
) -> dict[str, Any]:
    """Project one response using the exact user-selected scope."""

    return project_tui_holding_disclosure_result(
        _ACTION,
        payload,
        http_status=http_status,
        requested_params=params,
    )


def _row_values(row: dict[str, Any]) -> dict[str, object]:
    """Read named fields from one section-table row."""

    return {str(field["key"]): field["value"] for field in row["fields"] if isinstance(field, dict)}


def test_projection_keeps_financial_source_dates_and_read_time_separate() -> None:
    result = _project(_payload())

    assert result["status"] == "已读取部分资料"
    assert "资料范围不完整" in result["business_summary"]
    assert "不用于投资决策" in result["business_summary"]
    assert "不会计算、分配或入账现金、股份及税费" in result["business_summary"]
    fields = {field["key"]: field["value"] for field in result["fields"]}
    assert fields["read_at"] == _AS_OF
    assert fields["freshness"] == "未知"
    assert fields["reliability"] == "未知"
    row_values = _row_values(result["sections"][0]["rows"][0])
    assert row_values["report_date"] == "2026-03-28"
    assert row_values["announced_at"] == "2026-03-28"
    assert row_values["available_at"] == "2026-03-29T00:00:00+08:00"
    assert row_values["fetched_at"] == "2026-03-29T02:15:30+08:00"
    assert row_values["value"] == "1250000.00"
    assert row_values["unit"] == "CNY"
    assert row_values["report_date"] != fields["read_at"]


def test_projection_hides_transport_evidence_identifiers_and_hashes() -> None:
    result = _project(_payload())

    rendered = repr(result)
    assert "private-record-41" not in rendered
    assert "f" * 64 not in rendered
    assert "source_record_id" not in rendered
    assert "raw_payload_hash" not in rendered
    assert "/api/" not in rendered


@pytest.mark.parametrize(
    "payload_overrides, params",
    [
        ({"account_id": 42}, _READ_PARAMS),
        ({"asset_code": "000001.SZ"}, _READ_PARAMS),
        ({"scope": "real"}, _READ_PARAMS),
        ({"read_only": False}, _READ_PARAMS),
        ({"must_not_use_for_decision": False}, _READ_PARAMS),
        ({"must_not_execute": False}, _READ_PARAMS),
        ({"outcome": "success"}, _READ_PARAMS),
        ({}, None),
    ],
)
def test_projection_clears_facts_when_scope_or_restriction_contract_fails(
    payload_overrides: dict[str, object],
    params: dict[str, object] | None,
) -> None:
    result = _project(_payload(**payload_overrides), params=params)

    assert result["outcome"] == "blocked"
    assert result["sections"] == []
    assert result["next_steps"] == []
    assert "未显示" in result["business_summary"] or "范围" in result["business_summary"]


def test_projection_marks_missing_source_clocks_without_filling_them_from_read_time() -> None:
    payload = _payload(rows=[_row(announced_at=None, available_at=None, fetched_at=None)])

    result = _project(payload)
    rows = [_row_values(row) for row in result["sections"][0]["rows"]]

    assert rows[0]["announced_at"] == "未提供"
    assert rows[0]["available_at"] == "未提供"
    assert rows[0]["fetched_at"] == "未提供"
    assert result["fields"][-1]["value"] == _AS_OF


def test_projection_preserves_date_only_values_and_unknown_freshness() -> None:
    payload = _payload(
        freshness="unknown",
        reliability="unknown",
        rows=[_row(report_date="2026-03-28", announced_at="2026-03-28")],
    )

    result = _project(payload)
    rows = [_row_values(row) for row in result["sections"][0]["rows"]]

    assert rows[0]["report_date"] == "2026-03-28"
    assert rows[0]["announced_at"] == "2026-03-28"
    assert rows[0]["available_at"] == "2026-03-29T00:00:00+08:00"


def test_projection_explains_empty_coverage_without_claiming_no_disclosure_exists() -> None:
    result = _project(_payload(rows=[]))

    assert result["outcome"] == "partial"
    assert result["sections"][0]["rows"] == []
    assert "不能据此判断证券没有相关披露" in result["empty_message"]
    assert "来源覆盖不完整" in result["business_summary"]


def test_projection_clears_facts_for_source_block_and_transport_failure() -> None:
    blocked_payload = _payload(outcome="blocked", rows=[], blocked_reason="source_unavailable")
    blocked = _project(blocked_payload)
    failed = _project(_payload(), http_status=503)

    assert blocked["outcome"] == "blocked"
    assert blocked["sections"] == []
    assert "财务资料来源当前受阻" in blocked["business_summary"]
    assert failed["outcome"] == "blocked"
    assert failed["sections"] == []
    assert "读取失败" in failed["business_summary"]


def test_projection_does_not_mutate_source_payload() -> None:
    payload = _payload()
    before = deepcopy(payload)

    _project(payload)

    assert payload == before


def test_workbench_uses_the_disclosure_projection_for_the_runtime_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful action run returns the typed disclosure view, not the raw payload."""

    from apps.terminal.application.tui_workbench import TuiWorkbenchService

    action = deepcopy(
        next(item for item in RUNTIME_SIMULATED_TRADING_ACTIONS if item["key"] == _ACTION)
    )
    service = TuiWorkbenchService(
        metadata_repository=SimpleNamespace(load_published=lambda: {}),
        action_executor=SimpleNamespace(
            execute=lambda **_kwargs: {"status_code": 200, "payload": _payload()}
        ),
    )
    monkeypatch.setattr(service, "_action_by_key", lambda *args, **kwargs: action)
    monkeypatch.setattr(service, "_allowed_runtime_risks", lambda _user: {"read"})
    monkeypatch.setattr(service, "_diagnostics_allowed", lambda _user: False)
    monkeypatch.setattr(service, "_ensure_tui_audit_sink", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_append_tui_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_field_payload", lambda field, **kwargs: dict(field))
    monkeypatch.setattr(service, "_action_payload", lambda *args, **kwargs: {"key": _ACTION})
    monkeypatch.setattr(service, "_metadata", lambda: {"screens": []})

    result = service.run_action(
        action_key=_ACTION,
        params=_READ_PARAMS,
        user=SimpleNamespace(pk=1, is_authenticated=True, is_active=True, is_staff=False),
    )

    assert result["outcome"] == "partial"
    assert result["debug"]["raw_response"] is None
    assert result["view_model"]["outcome"] == "partial"
    assert result["view_model"]["sections"][0]["rows"]
    assert "raw_payload_hash" not in repr(result["view_model"])
