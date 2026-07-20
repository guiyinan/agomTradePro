# ruff: noqa: F403, F405
"""Split tests from test_core_registry.py: owner_prompt."""

from .core_registry_support import *


@pytest.mark.parametrize(
    ("fallback_name", "capability_key", "payload", "expected_label"),
    [
        pytest.param(
            "list_prompt_templates",
            "prompt.read.template_catalog",
            {
                "templates": [
                    {
                        "id": 9,
                        "name": "Macro Weekly Brief",
                        "category": "report",
                        "version": "1.2",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Macro Weekly Brief",
            id="template-catalog",
        ),
        pytest.param(
            "list_prompt_chains",
            "prompt.read.chain_catalog",
            {
                "chains": [
                    {
                        "id": 21,
                        "name": "Macro Review Flow",
                        "category": "analysis",
                        "execution_mode": "serial",
                    }
                ],
                "total_count": 1,
                "source": "core-only-fallback",
            },
            "Macro Review Flow",
            id="chain-catalog",
        ),
    ],
)
def test_agom_capability_call_reads_prompt_catalog_in_core_only_mode(
    monkeypatch: pytest.MonkeyPatch,
    core_only_mcp_server,
    fallback_name: str,
    capability_key: str,
    payload: dict,
    expected_label: str,
) -> None:
    import agomtradepro_mcp.server as server_module

    monkeypatch.setitem(
        server_module.INTERNAL_LEGACY_TOOL_FALLBACKS,
        fallback_name,
        lambda **kwargs: payload,
    )

    result = asyncio.run(
        core_only_mcp_server.call_tool(
            "agom_capability_call",
            {
                "capability_key": capability_key,
                "arguments": {},
            },
        )
    )

    rendered = str(result)
    assert capability_key in rendered
    assert expected_label in rendered
    assert "core-only-fallback" in rendered


def test_prompt_create_template_capability_checks_name_before_staff_only_create(
    monkeypatch: pytest.MonkeyPatch,
):
    import agomtradepro_mcp.server as server_module

    captured_calls = []
    audit_events = _capture_governed_audit_events(
        monkeypatch,
        server_module.CORE_DISPATCHER,
    )

    class _FakePromptModule:
        @staticmethod
        def list_templates(*, name=None, include_inactive=False):
            assert name == "Governed Macro Brief"
            assert include_inactive is True
            return []

        @staticmethod
        def create_template(payload):
            captured_calls.append(dict(payload))
            return {"id": 81, **payload}

    class _FakeClient:
        prompt = _FakePromptModule()

    monkeypatch.setattr("agomtradepro.AgomTradeProClient", lambda: _FakeClient())

    manifest = CapabilityRegistryLoader().build_registry()["prompt.create.template"]
    assert manifest.required_roles == ("staff",)
    assert manifest.legacy_tool_names == ("create_prompt_template",)

    preview_response = server_module.CORE_DISPATCHER.call(
        capability_key="prompt.create.template",
        arguments={
            "name": "Governed Macro Brief",
            "category": "report",
            "template_content": "Summarize {{trade_date}}.",
            "placeholders": [
                {
                    "name": "trade_date",
                    "type": "simple",
                    "required": True,
                }
            ],
            "temperature": 0.2,
            "max_tokens": 900,
            "idempotency_key": "idem-prompt-template-create",
        },
    )

    assert preview_response["status"] == "confirmation_required"
    assert preview_response["preview_result"]["preview_only"] is True
    assert preview_response["preview_result"]["template_summary"]["placeholder_count"] == 1
    assert preview_response["preview_result"]["summary"]["duplicate_count"] == 0
    assert captured_calls == []

    resume_response = server_module.CORE_DISPATCHER.resume_confirmation(
        confirmation_token=preview_response["confirmation_token"],
        approve=True,
    )

    assert resume_response["status"] == "completed"
    assert resume_response["result"]["id"] == 81
    assert captured_calls[0]["name"] == "Governed Macro Brief"
    assert captured_calls[0]["category"] == "report"
    assert audit_events[0]["event_type"] == "preview_staged"
    assert audit_events[1]["event_type"] == "confirmation_completed"
