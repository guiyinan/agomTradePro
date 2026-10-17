"""Research owner outcomes survive real HTTP and existing TUI execution.

Only Data Center read ports and the display-name port are supplied. These
tests do not prove real publication/readiness or publish a research action.
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
                    "default_action_key": "test.equity-research",
                }
            ],
            "actions": [
                {
                    "key": "test.equity-research",
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
    ("case", "expected_outcome", "restricted"),
    [
        ("fresh", "success", False),
        ("partial", "partial", False),
        ("blocked", "blocked", True),
        ("missing", "blocked", True),
    ],
)
def test_research_outcome_reaches_real_http_and_existing_tui_executor(
    client, django_user_model, monkeypatch, case: str, expected_outcome: str, restricted: bool
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
    assert payload["status"] == case
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
        action_key="test.equity-research", params={"stock_code": "000001.SZ"}, user=user
    )

    assert result["response"]["status_code"] == 200
    assert result["outcome"] == expected_outcome
    assert payload["outcome"] == expected_outcome
    assert (
        result["view_model"]["status"]
        == {
            "fresh": "已读取",
            "partial": "部分完成",
            "blocked": "不可用于决策",
            "missing": "不可用于决策",
        }[case]
    )
    assert result["debug"] == {"raw_available": False, "raw_response": None}
