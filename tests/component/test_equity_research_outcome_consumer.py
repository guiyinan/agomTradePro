"""Research owner outcomes survive real HTTP and existing TUI execution.

Only Data Center read ports and the display-name port are supplied; these are
contract inputs, not provider or admission evidence. The tests do not prove
real publication/readiness or publish a research action.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from copy import deepcopy
from typing import NoReturn
from unittest.mock import Mock

import pytest
from django.utils import timezone

from apps.config_center.infrastructure.decision_runtime_models import (
    DecisionRuntimeStateModel,
)
from apps.equity.application.research_snapshot import (
    EquityResearchSnapshotReader,
    EquityResearchSnapshotRequest,
    EquityResearchSnapshotUseCase,
)
from apps.terminal.application.tui_workbench import TuiWorkbenchService
from apps.terminal.infrastructure.tui_adapters import get_tui_action_executor

ENDPOINT = "/api/equity/research-snapshot/000001.SZ/"
SOURCE_TIME = "2026-10-16T07:00:00+00:00"


@pytest.fixture(autouse=True)
def _no_external_connections(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail even swallowed network attempts; the fixture needs only SQLite."""

    attempts: list[str] = []

    def deny_connect(_socket: socket.socket, address: object) -> NoReturn:
        attempts.append(repr(address))
        raise AssertionError("Unexpected network attempt in supplied-port contract")

    monkeypatch.setattr(socket.socket, "connect", deny_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", deny_connect)
    monkeypatch.setattr(
        "apps.terminal.application.tui_workbench.resolve_asset_names",
        lambda codes: dict.fromkeys(codes, "Fixture"),
    )
    yield
    assert attempts == []


@pytest.fixture(autouse=True)
def _admitted_contract_test_runtime(db: object) -> None:
    """Admit this isolated HTTP fixture; this is not strict data readiness proof."""

    DecisionRuntimeStateModel.objects.update_or_create(
        pk=1,
        defaults={
            "status": "active",
            "reason": "Isolated supplied-port outcome contract fixture",
            "changed_at": timezone.now(),
            "changed_by": "pytest:tux08a-outcome-contract",
        },
    )


class _ResearchMetadata:
    """Supply a test-only operation; no production metadata is published."""

    def load_published(self, registry_key: str = "default") -> dict[str, object]:
        return {
            "version": "tui-workbench.v2",
            "registry_key": registry_key,
            "default_screen": "research.asset-lab",
            "groups": [{"key": "research", "label": "研究"}],
            "modules": [{"key": "research", "group": "research", "label": "研究"}],
            "screens": [
                {
                    "key": "research.asset-lab",
                    "module_key": "research",
                    "group": "research",
                    "label": "资产研究",
                    "summary": "Test-only read consumer.",
                    "status": "online",
                    "view_type": "detail",
                    "default_action_key": "equity.research-snapshot",
                }
            ],
            "actions": [
                {
                    "key": "equity.research-snapshot",
                    "label": "研究快照",
                    "screen_key": "research.asset-lab",
                    "module_key": "research",
                    "intent": "research_snapshot",
                    "method": "GET",
                    "endpoint": "/api/equity/research-snapshot/<str:stock_code>/",
                    "risk": "read",
                    "view_type": "detail",
                    "source": "approved:test",
                    "raw_debug": False,
                    "fields": [
                        {
                            "key": "stock_code",
                            "binding": "path",
                            "input_type": "text",
                            "value_type": "string",
                            "required": True,
                        }
                    ],
                }
            ],
        }


def _owner_with_supplied_ports(case: str) -> EquityResearchSnapshotUseCase:
    reader = Mock(spec=EquityResearchSnapshotReader)
    reader.get_decision_readiness.return_value = {"must_not_use_for_decision": False}
    reader.resolve_asset.return_value = (
        None if case == "missing" else {"code": "000001.SZ", "name": "Fixture"}
    )
    reader.get_latest_quotes.return_value = {
        "results": [{"asset_code": "000001.SZ", "current_price": 12.3, "snapshot_at": SOURCE_TIME}],
        "observed_at": SOURCE_TIME,
        "fetched_at": "2026-10-16T07:01:00+00:00",
    }
    reader.get_price_history.return_value = {"rows": [{"bar_date": "2026-10-16"}]}
    reader.get_valuations.return_value = (
        {"rows": [], "freshness_status": "stale", "blocked_reason": "publication_stale"}
        if case == "blocked"
        else {"rows": [{"val_date": "2026-10-16", "pb": 1.2}]}
    )
    if case in {"financial_partial", "blocked"}:
        reader.get_financials.return_value = {
            "rows": [
                {
                    "asset_code": "000001.SZ",
                    "metric_code": "revenue",
                    "period_end": "2026-06-30",
                    "value": 123,
                    "unit": "CNY",
                    "available_at": None,
                    "source_evidence": None,
                }
            ],
            "publication_outcome": "partial",
            "coverage_requested_count": 4,
            "coverage_eligible_count": 3,
            "coverage_selected_count": 2,
            "coverage_missing_count": 1,
            "available_at": None,
            "observed_at": None,
        }
    else:
        reader.get_financials.return_value = {
            "rows": [{"period_end": "2026-06-30", "value": 123, "unit": "CNY"}]
        }
    reader.get_news.return_value = {"rows": [] if case == "partial" else [{"title": "Fixture"}]}
    reader.get_capital_flows.return_value = {
        "rows": [] if case == "partial" else [{"flow_date": "2026-10-16", "main_net": 1}]
    }
    return EquityResearchSnapshotUseCase(reader)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("case", "expected_status", "expected_outcome", "restricted"),
    [
        ("fresh", "fresh", "success", False),
        ("partial", "partial", "partial", False),
        ("financial_partial", "partial", "partial", False),
        ("blocked", "blocked", "blocked", True),
        ("missing", "missing", "blocked", True),
    ],
)
def test_research_outcome_reaches_real_http_and_existing_tui_executor(
    client,
    django_user_model,
    monkeypatch,
    case: str,
    expected_status: str,
    expected_outcome: str,
    restricted: bool,
) -> None:
    """A successful transport must preserve incomplete/blocked owner semantics."""

    owner = _owner_with_supplied_ports(case)
    before = deepcopy(owner.execute(EquityResearchSnapshotRequest("000001.SZ")).to_payload())
    monkeypatch.setattr(
        "apps.equity.interface.research_snapshot_views.make_equity_research_snapshot_use_case",
        lambda: owner,
    )
    user = django_user_model.objects.create_user(username=f"research-outcome-{case}")
    client.force_login(user)
    response = client.get(ENDPOINT)

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    payload = response.json()
    assert payload == before
    assert payload["status"] == expected_status
    assert payload["must_not_use_for_decision"] is restricted
    if case != "missing":
        quote = payload["sections"]["latest_quote"]["data"]
        assert quote["observed_at"] == SOURCE_TIME
        assert quote["results"][0]["snapshot_at"] == SOURCE_TIME
        assert quote["fetched_at"] == "2026-10-16T07:01:00+00:00"

    service = TuiWorkbenchService(
        metadata_repository=_ResearchMetadata(),
        action_executor=get_tui_action_executor(),
    )
    result = service.run_action(
        action_key="equity.research-snapshot", params={"stock_code": "000001.SZ"}, user=user
    )

    assert result["response"]["status_code"] == 200
    assert result["outcome"] == expected_outcome
    assert payload["outcome"] == expected_outcome
    assert result["view_model"]["owner_status"] == expected_status
    assert (
        result["view_model"]["status"]
        == {
            "fresh": "已返回",
            "partial": "部分返回",
            "blocked": "已阻断",
            "missing": "未找到",
        }[expected_status]
    )
    assert result["debug"] == {"raw_available": False, "raw_response": None}

    if case in {"financial_partial", "blocked"}:
        financial_payload = payload["sections"]["financials"]
        financial_data = financial_payload["data"]
        assert financial_payload["status"] == "partial"
        assert financial_data["publication_outcome"] == "partial"
        if case == "financial_partial":
            assert payload["missing_optional_sections"] == []
            for section_key in (
                "latest_quote",
                "price_history",
                "valuation",
                "news",
                "capital_flows",
            ):
                assert payload["sections"][section_key]["status"] == "fresh"
        assert {
            key: financial_data[key]
            for key in (
                "coverage_requested_count",
                "coverage_eligible_count",
                "coverage_selected_count",
                "coverage_missing_count",
            )
        } == {
            "coverage_requested_count": 4,
            "coverage_eligible_count": 3,
            "coverage_selected_count": 2,
            "coverage_missing_count": 1,
        }
        assert financial_data["available_at"] is None
        raw_row = financial_data["rows"][0]
        assert raw_row["value"] == 123
        assert raw_row["available_at"] is None
        assert raw_row["source_evidence"] is None

        view = result["view_model"]
        coverage = "本次财务发布范围：部分返回；请求：4；符合条件：3；" "已选入：2；缺失：1。"
        financial_section = next(item for item in view["sections"] if item["key"] == "financials")
        assert coverage in financial_section["restriction_message"]
        first_screen_fields = {item["key"]: item["value"] for item in view["fields"]}
        assert coverage in first_screen_fields["evidence_gaps"]
        displayed_rows = financial_section["rows"]
        assert len(displayed_rows) == 1
        displayed_values = {item["key"]: item["value"] for item in displayed_rows[0]["fields"]}
        assert displayed_values["value"] == "123"
        source_times = financial_section.get("source_times", [])
        assert not any(item["field"] == "available_at" for item in source_times)

        if case == "blocked":
            assert view["must_not_use_for_decision"] is True
            valuation_section = next(
                item for item in view["sections"] if item["key"] == "valuation"
            )
            assert valuation_section["upstream_freshness_status"] == "stale"
            assert "估值：上游数据过期" in first_screen_fields["evidence_gaps"]
