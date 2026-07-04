from datetime import UTC, datetime
from types import SimpleNamespace

from apps.ai_capability.application import query_services


def test_ai_capability_surface_status_summarizes_mcp_and_terminal_sources(monkeypatch):
    repository = _FakeCapabilityRepository()
    sync_repository = _FakeSyncRepository()
    monkeypatch.setattr(
        query_services,
        "get_capability_repository",
        lambda: repository,
    )
    monkeypatch.setattr(
        query_services,
        "get_capability_sync_log_repository",
        lambda: sync_repository,
    )

    payload = query_services.get_ai_capability_surface_status_payload()

    assert payload["status"] == "ok"
    assert payload["catalog"]["total"] == 5
    assert payload["mcp_tools"]["total"] == 2
    assert payload["mcp_tools"]["routing_enabled"] == 1
    assert payload["mcp_tools"]["requires_confirmation"] == 1
    assert payload["terminal_capabilities"]["terminal_enabled"] == 1
    assert payload["terminal_capabilities"]["latest_sync_at"] == "2026-07-04T08:00:00+00:00"


class _FakeCapabilityRepository:
    def get_stats(self):
        return {
            "total": 5,
            "enabled": 3,
            "disabled": 2,
            "by_source": {
                "builtin": 1,
                "terminal_command": 2,
                "mcp_tool": 2,
                "api": 0,
            },
            "by_route_group": {},
        }

    def get_by_source_type(self, source_type):
        if source_type == "mcp_tool":
            return [
                SimpleNamespace(
                    enabled_for_routing=True,
                    enabled_for_terminal=True,
                    enabled_for_chat=True,
                    enabled_for_agent=True,
                    requires_confirmation=True,
                ),
                SimpleNamespace(
                    enabled_for_routing=False,
                    enabled_for_terminal=True,
                    enabled_for_chat=False,
                    enabled_for_agent=False,
                    requires_confirmation=False,
                ),
            ]
        return [
            SimpleNamespace(
                enabled_for_routing=True,
                enabled_for_terminal=True,
                enabled_for_chat=True,
                enabled_for_agent=True,
                requires_confirmation=False,
            ),
            SimpleNamespace(
                enabled_for_routing=True,
                enabled_for_terminal=False,
                enabled_for_chat=True,
                enabled_for_agent=True,
                requires_confirmation=False,
            ),
        ]


class _FakeSyncRepository:
    def get_latest(self, sync_type):
        return SimpleNamespace(
            finished_at=datetime(2026, 7, 4, 8, 0, tzinfo=UTC),
        )
