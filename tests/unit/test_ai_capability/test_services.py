"""
Tests for AI Capability Catalog domain services.
"""

import pytest

from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    RiskLevel,
    RouteGroup,
    RoutingContext,
    SourceType,
    Visibility,
)
from apps.ai_capability.domain.services import (
    BuiltinCapabilityRegistry,
    CapabilityFilter,
    CapabilityRetrievalScorer,
    RetrievalScore,
)


class TestCapabilityRetrievalScorer:
    """Tests for CapabilityRetrievalScorer."""

    @pytest.fixture
    def scorer(self):
        return CapabilityRetrievalScorer()

    @pytest.fixture
    def sample_capabilities(self):
        return [
            CapabilityDefinition(
                capability_key="builtin.system_status",
                source_type=SourceType.BUILTIN,
                source_ref="terminal:system_status",
                name="System Status",
                summary="Check system health and readiness status",
                tags=["status", "health", "system"],
                when_to_use=["User asks about system status"],
                examples=["目前系统是什么状态", "系统健康吗"],
                priority_weight=10.0,
            ),
            CapabilityDefinition(
                capability_key="builtin.market_regime",
                source_type=SourceType.BUILTIN,
                source_ref="terminal:market_regime",
                name="Market Regime",
                summary="Get current market regime and policy level",
                tags=["regime", "macro", "market"],
                when_to_use=["User asks about current market regime"],
                examples=["当前市场 regime", "市场环境如何"],
                priority_weight=10.0,
            ),
            CapabilityDefinition(
                capability_key="mcp_tool.get_macro_indicator",
                source_type=SourceType.MCP_TOOL,
                source_ref="get_macro_indicator",
                name="Get Macro Indicator",
                summary="Get the latest value of a macro indicator",
                tags=["macro", "indicator", "pmi", "cpi"],
                priority_weight=1.0,
            ),
        ]

    def test_score_capability_exact_match(self, scorer, sample_capabilities):
        """Test scoring with exact match in name."""
        cap = sample_capabilities[0]
        result = scorer.score_capability(cap, "system status")

        assert isinstance(result, RetrievalScore)
        assert result.capability == cap
        assert result.score > 0
        assert "name" in result.matched_fields

    def test_score_capability_chinese_query(self, scorer, sample_capabilities):
        """Test scoring with Chinese query."""
        cap = sample_capabilities[0]
        result = scorer.score_capability(cap, "目前系统是什么状态")

        assert result.score > 0
        assert "examples" in result.matched_fields

    def test_retrieve_top_k(self, scorer, sample_capabilities):
        """Test retrieving top-k candidates."""
        results = scorer.retrieve_top_k(
            sample_capabilities,
            "系统状态健康检查",
            k=2,
        )

        assert len(results) <= 2
        assert all(isinstance(r, RetrievalScore) for r in results)
        assert results[0].score >= results[-1].score

    def test_retrieve_top_k_respects_priority_weight(self, scorer):
        """Test that priority weight affects ranking."""
        low_priority = CapabilityDefinition(
            capability_key="low.priority",
            source_type=SourceType.API,
            source_ref="low",
            name="Low Priority Item",
            summary="status check",
            priority_weight=0.1,
        )
        high_priority = CapabilityDefinition(
            capability_key="high.priority",
            source_type=SourceType.BUILTIN,
            source_ref="high",
            name="High Priority Status",
            summary="status check",
            priority_weight=10.0,
        )

        results = scorer.retrieve_top_k(
            [low_priority, high_priority],
            "status check",
            k=2,
        )

        assert results[0].capability.capability_key == "high.priority"

    def test_retrieve_top_k_min_score(self, scorer, sample_capabilities):
        """Test minimum score filtering."""
        results = scorer.retrieve_top_k(
            sample_capabilities,
            "completely unrelated xyz123 query",
            k=5,
            min_score=100.0,
        )

        assert len(results) == 0


class TestCapabilityFilter:
    """Tests for CapabilityFilter."""

    @pytest.fixture
    def filter_service(self):
        return CapabilityFilter()

    @pytest.fixture
    def sample_capabilities(self):
        return [
            CapabilityDefinition(
                capability_key="builtin.system_status",
                source_type=SourceType.BUILTIN,
                source_ref="terminal:system_status",
                name="System Status",
                summary="Check system health",
                enabled_for_terminal=True,
                enabled_for_chat=True,
                enabled_for_agent=True,
                requires_mcp=False,
                visibility=Visibility.PUBLIC,
                route_group=RouteGroup.BUILTIN,
            ),
            CapabilityDefinition(
                capability_key="mcp_tool.get_macro",
                source_type=SourceType.MCP_TOOL,
                source_ref="get_macro",
                name="Get Macro",
                summary="Get macro data",
                enabled_for_terminal=True,
                requires_mcp=True,
                visibility=Visibility.PUBLIC,
                route_group=RouteGroup.TOOL,
            ),
            CapabilityDefinition(
                capability_key="api.admin.delete",
                source_type=SourceType.API,
                source_ref="DELETE /api/admin/",
                name="Admin Delete",
                summary="Admin delete endpoint",
                enabled_for_terminal=True,
                requires_mcp=False,
                visibility=Visibility.ADMIN,
                route_group=RouteGroup.UNSAFE_API,
            ),
        ]

    def test_filter_by_terminal_entrypoint(self, filter_service, sample_capabilities):
        """Test filtering for terminal entrypoint."""
        context = RoutingContext(
            entrypoint="terminal",
            session_id="test",
            mcp_enabled=True,
            user_is_admin=False,
        )

        results = filter_service.filter_by_context(sample_capabilities, context)

        assert len(results) == 2
        assert all(r.enabled_for_terminal for r in results)
        assert all(r.route_group != RouteGroup.UNSAFE_API for r in results)

    def test_filter_mcp_disabled(self, filter_service, sample_capabilities):
        """Test filtering when MCP is disabled."""
        context = RoutingContext(
            entrypoint="terminal",
            session_id="test",
            mcp_enabled=False,
            user_is_admin=False,
        )

        results = filter_service.filter_by_context(sample_capabilities, context)

        assert all(not r.requires_mcp for r in results)

    def test_filter_admin_visibility(self, filter_service, sample_capabilities):
        """Test filtering for admin users."""
        context_admin = RoutingContext(
            entrypoint="terminal",
            session_id="test",
            mcp_enabled=True,
            user_is_admin=True,
        )

        context_user = RoutingContext(
            entrypoint="terminal",
            session_id="test",
            mcp_enabled=True,
            user_is_admin=False,
        )

        admin_results = filter_service.filter_by_context(sample_capabilities, context_admin)
        user_results = filter_service.filter_by_context(sample_capabilities, context_user)

        assert len(admin_results) >= len(user_results)


class TestBuiltinCapabilityRegistry:
    """Tests for BuiltinCapabilityRegistry."""

    def test_get_all(self):
        """Test getting all builtin capabilities."""
        capabilities = BuiltinCapabilityRegistry.get_all()

        assert isinstance(capabilities, list)
        assert len(capabilities) >= 2
        assert all("capability_key" in cap for cap in capabilities)

    def test_get_by_key_existing(self):
        """Test getting an existing builtin capability."""
        cap = BuiltinCapabilityRegistry.get_by_key("builtin.system_status")

        assert cap is not None
        assert cap["name"] == "System Status"

    def test_get_by_key_nonexistent(self):
        """Test getting a non-existent builtin capability."""
        cap = BuiltinCapabilityRegistry.get_by_key("builtin.nonexistent")

        assert cap is None
