from types import SimpleNamespace

from apps.terminal.application import query_services


def test_terminal_surface_status_summarizes_commands_and_tui_metadata(monkeypatch):
    monkeypatch.setattr(
        query_services,
        "get_terminal_command_repository",
        lambda: _FakeTerminalCommandRepository(),
    )
    monkeypatch.setattr(
        query_services,
        "get_tui_metadata_repository",
        lambda: _FakeTuiMetadataRepository(),
    )

    payload = query_services.get_terminal_surface_status_payload()

    assert payload["status"] == "ok"
    assert payload["terminal_commands"]["active"] == 3
    assert payload["terminal_commands"]["terminal_enabled"] == 2
    assert payload["terminal_commands"]["requires_mcp"] == 1
    assert payload["terminal_commands"]["api_type"] == 1
    assert payload["terminal_commands"]["prompt_type"] == 1
    assert payload["tui_metadata"]["screens"] == 2
    assert payload["tui_metadata"]["actions"] == 3


class _FakeTerminalCommandRepository:
    def get_all_active(self):
        return [
            SimpleNamespace(
                enabled_in_terminal=True,
                requires_mcp=True,
                is_api_type=True,
                is_prompt_type=False,
            ),
            SimpleNamespace(
                enabled_in_terminal=True,
                requires_mcp=False,
                is_api_type=False,
                is_prompt_type=True,
            ),
            SimpleNamespace(
                enabled_in_terminal=False,
                requires_mcp=True,
                is_api_type=True,
                is_prompt_type=False,
            ),
        ]


class _FakeTuiMetadataRepository:
    def load_published(self):
        return {
            "version": "2026.07",
            "schema_version": "tui-metadata.v3",
            "modules": [{"key": "ops"}],
            "screens": [{"key": "a"}, {"key": "b"}],
            "actions": [{"key": "a1"}, {"key": "a2"}, {"key": "a3"}],
            "default_screen": "a",
            "coverage_summary": {"runtime_injected_cli_metadata": 1},
        }
