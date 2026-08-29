from apps.prompt.application.agent_authority import UnwiredAgentAuthorityGate
from apps.prompt.application.interface_services import build_agent_runtime


class _FakeContextBuilder:
    def __init__(self):
        self.providers = []

    def register_provider(self, provider):
        self.providers.append(provider)


def test_build_ai_tool_runtime_uses_strategy_prompt_providers(monkeypatch):
    expected_providers = (object(), object(), object())
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "apps.prompt.application.interface_services.build_macro_adapter",
        lambda: "macro-adapter",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.build_regime_adapter",
        lambda: "regime-adapter",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.build_prompt_strategy_providers",
        lambda: expected_providers,
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.create_agent_tool_registry",
        lambda **kwargs: captured.update(kwargs) or "tool-registry",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.get_ai_client_factory",
        lambda: "ai-client-factory",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.ContextBundleBuilder",
        _FakeContextBuilder,
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.AgentExecutionLogger",
        lambda execution_log_repository: "execution-logger",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.get_execution_log_repository",
        lambda: "execution-log-repository",
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.AgentRuntime",
        lambda **kwargs: kwargs,
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.MacroContextProvider",
        lambda adapter: ("macro", adapter),
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.RegimeContextProvider",
        lambda adapter: ("regime", adapter),
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.PortfolioContextProvider",
        lambda provider: ("portfolio", provider),
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.SignalContextProvider",
        lambda provider: ("signal", provider),
    )
    monkeypatch.setattr(
        "apps.prompt.application.interface_services.AssetPoolContextProvider",
        lambda provider: ("asset_pool", provider),
    )

    runtime = build_agent_runtime()

    assert captured["portfolio_provider"] is expected_providers[0]
    assert captured["signal_provider"] is expected_providers[1]
    assert captured["asset_pool_provider"] is expected_providers[2]
    assert runtime["tool_registry"] == "tool-registry"
    assert isinstance(runtime["authority_gate"], UnwiredAgentAuthorityGate)
