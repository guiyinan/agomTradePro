"""Extended module access tests for AgomTradePro SDK client."""

from agomtradepro import AgomTradeProClient


class TestAgomTradeProClientExtendedModules:
    def test_extended_module_properties(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

        assert client.ai_provider is not None
        assert client.prompt is not None
        assert client.audit is not None
        assert client.events is not None
        assert client.decision_rhythm is not None
        assert client.decision_workflow is not None
        assert client.beta_gate is not None
        assert client.alpha is not None
        assert client.alpha_trigger is not None
        assert client.dashboard is not None
        assert client.asset_analysis is not None
        assert client.sentiment is not None
        assert client.task_monitor is not None
        assert client.filter is not None

    def test_extended_module_singleton_behavior(self):
        client = AgomTradeProClient(base_url="http://test.com", api_token="test_token")

        assert client.prompt is client.prompt
        assert client.audit is client.audit
        assert client.events is client.events
        assert client.sentiment is client.sentiment
        assert client.alpha is client.alpha
        assert client.decision_workflow is client.decision_workflow
