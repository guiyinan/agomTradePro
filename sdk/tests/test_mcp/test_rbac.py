import pytest

from agomtradepro_mcp import rbac


@pytest.mark.parametrize(
    ("role", "tool_name", "expected_allowed"),
    [
        ("admin", "import_positions_csv", True),
        ("owner", "import_positions_csv", True),
        ("owner", "set_system_settings", False),
        ("analyst", "get_positions_detailed", True),
        ("analyst", "import_transactions_csv", False),
        ("investment_manager", "import_transactions_csv", True),
        ("trader", "import_transactions_csv", True),
        ("trader", "update_risk_policy", False),
        ("risk", "update_risk_policy", True),
        ("risk", "import_positions_csv", False),
        ("read_only", "get_portfolio_statistics", True),
        ("read_only", "import_capital_flows_csv", False),
        ("analyst", "publish_event", False),
        ("analyst", "submit_decision_request", False),
        ("read_only", "replay_events", False),
        ("read_only", "toggle_ai_provider", False),
        ("investment_manager", "publish_event", True),
        ("investment_manager", "submit_decision_request", True),
        ("owner", "toggle_ai_provider", True),
        ("risk", "submit_decision_request", False),
        ("read_only", "trigger_alpha_ops_inference", False),
        ("read_only", "refresh_alpha_qlib_data", False),
        ("analyst", "get_alpha_ops_inference_overview", True),
    ],
)
def test_role_tool_matrix_enforcement(
    monkeypatch: pytest.MonkeyPatch, role: str, tool_name: str, expected_allowed: bool
) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENFORCE_RBAC", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", role)

    if expected_allowed:
        rbac.enforce_tool_access(tool_name)
        return

    with pytest.raises(PermissionError):
        rbac.enforce_tool_access(tool_name)


@pytest.mark.parametrize(
    ("role", "resource_uri", "expected_allowed"),
    [
        ("admin", "agomtradepro://account/summary", True),
        ("owner", "agomtradepro://account/summary", True),
        ("analyst", "agomtradepro://account/summary", False),
        ("read_only", "agomtradepro://regime/current", True),
    ],
)
def test_role_resource_access(
    monkeypatch: pytest.MonkeyPatch, role: str, resource_uri: str, expected_allowed: bool
) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENFORCE_RBAC", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", role)

    if expected_allowed:
        rbac.enforce_resource_access(resource_uri)
        return

    with pytest.raises(PermissionError):
        rbac.enforce_resource_access(resource_uri)


@pytest.mark.parametrize(
    ("role", "prompt_name", "expected_allowed"),
    [
        ("read_only", "check_signal_eligibility", False),
        ("read_only", "analyze_macro_environment", True),
        ("trader", "check_signal_eligibility", True),
    ],
)
def test_role_prompt_access(
    monkeypatch: pytest.MonkeyPatch, role: str, prompt_name: str, expected_allowed: bool
) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENFORCE_RBAC", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", role)

    if expected_allowed:
        rbac.enforce_prompt_access(prompt_name)
        return

    with pytest.raises(PermissionError):
        rbac.enforce_prompt_access(prompt_name)


def test_rbac_allow_list_overrides_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ENFORCE_RBAC", "true")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", "admin")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ALLOWED_TOOLS", "get_positions_detailed")

    rbac.enforce_tool_access("get_positions_detailed")
    with pytest.raises(PermissionError):
        rbac.enforce_tool_access("import_positions_csv")


def test_role_resolves_from_backend_when_env_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGOMTRADEPRO_MCP_ROLE", raising=False)
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE_SOURCE", "backend")
    monkeypatch.setattr(rbac, "_get_role_from_backend", lambda: "trader")

    assert rbac._role() == "trader"


def test_env_role_overrides_backend_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE", "read_only")
    monkeypatch.setenv("AGOMTRADEPRO_MCP_ROLE_SOURCE", "backend")
    monkeypatch.setattr(rbac, "_get_role_from_backend", lambda: "admin")

    assert rbac._role() == "read_only"
