"""
Tests for AI Capability Catalog domain entities.
"""

import pytest
from datetime import datetime, timezone

from apps.ai_capability.domain.entities import (
    CapabilityDefinition,
    CapabilityDecision,
    CapabilityRoutingLog,
    CapabilitySyncLog,
    ExecutionKind,
    ReviewStatus,
    RiskLevel,
    RouteGroup,
    SourceType,
    Visibility,
    RoutingContext,
    RoutingDecision,
)


class TestCapabilityDefinition:
    """Tests for CapabilityDefinition entity."""

    def test_create_capability_minimal(self):
        """Test creating a capability with minimal fields."""
        cap = CapabilityDefinition(
            capability_key="test.capability",
            source_type=SourceType.BUILTIN,
            source_ref="test:ref",
            name="Test Capability",
            summary="A test capability",
        )

        assert cap.capability_key == "test.capability"
        assert cap.source_type == SourceType.BUILTIN
        assert cap.name == "Test Capability"
        assert cap.summary == "A test capability"
        assert cap.route_group == RouteGroup.TOOL
        assert cap.risk_level == RiskLevel.SAFE
        assert cap.enabled_for_routing is True

    def test_create_capability_full(self):
        """Test creating a capability with all fields."""
        cap = CapabilityDefinition(
            capability_key="api.get.regime",
            source_type=SourceType.API,
            source_ref="GET /api/regime/",
            name="Get Regime",
            summary="Get current market regime",
            description="Detailed description",
            route_group=RouteGroup.READ_API,
            category="market",
            tags=["regime", "market"],
            when_to_use=["User asks about regime"],
            when_not_to_use=["User asks about system status"],
            examples=["current regime", "market regime"],
            input_schema={"type": "object"},
            execution_kind=ExecutionKind.SYNC,
            execution_target={"type": "api", "method": "GET", "path": "/api/regime/"},
            risk_level=RiskLevel.SAFE,
            requires_mcp=False,
            requires_confirmation=False,
            enabled_for_routing=True,
            visibility=Visibility.PUBLIC,
            auto_collected=True,
            review_status=ReviewStatus.AUTO,
            priority_weight=5.0,
        )

        assert cap.capability_key == "api.get.regime"
        assert cap.route_group == RouteGroup.READ_API
        assert cap.tags == ["regime", "market"]
        assert cap.priority_weight == 5.0

    def test_capability_to_dict(self):
        """Test converting capability to dict."""
        cap = CapabilityDefinition(
            capability_key="test.cap",
            source_type=SourceType.BUILTIN,
            source_ref="test:ref",
            name="Test",
            summary="Test summary",
        )

        d = cap.to_dict()

        assert d["capability_key"] == "test.cap"
        assert d["source_type"] == "builtin"
        assert d["name"] == "Test"

    def test_capability_from_dict(self):
        """Test creating capability from dict."""
        d = {
            "capability_key": "test.cap",
            "source_type": "api",
            "source_ref": "test:ref",
            "name": "Test",
            "summary": "Test summary",
            "route_group": "read_api",
            "risk_level": "low",
        }

        cap = CapabilityDefinition.from_dict(d)

        assert cap.capability_key == "test.cap"
        assert cap.source_type == SourceType.API
        assert cap.route_group == RouteGroup.READ_API
        assert cap.risk_level == RiskLevel.LOW

    def test_capability_to_summary_dict(self):
        """Test converting capability to summary dict."""
        cap = CapabilityDefinition(
            capability_key="test.cap",
            source_type=SourceType.BUILTIN,
            source_ref="test:ref",
            name="Test",
            summary="Test summary",
            risk_level=RiskLevel.HIGH,
            requires_confirmation=True,
        )

        summary = cap.to_summary_dict()

        assert summary["capability_key"] == "test.cap"
        assert summary["name"] == "Test"
        assert summary["risk_level"] == "high"
        assert summary["requires_confirmation"] is True


class TestRoutingContext:
    """Tests for RoutingContext entity."""

    def test_create_routing_context(self):
        """Test creating a routing context."""
        ctx = RoutingContext(
            entrypoint="terminal",
            session_id="test-session",
            user_id=1,
            user_is_admin=True,
            mcp_enabled=True,
        )

        assert ctx.entrypoint == "terminal"
        assert ctx.session_id == "test-session"
        assert ctx.user_is_admin is True


class TestRoutingDecision:
    """Tests for RoutingDecision entity."""

    def test_create_capability_decision(self):
        """Test creating a capability decision."""
        decision = RoutingDecision(
            decision=CapabilityDecision.CAPABILITY,
            selected_capability_key="builtin.system_status",
            confidence=0.95,
            reply="System is healthy",
            metadata={"route": "capability"},
        )

        assert decision.decision == CapabilityDecision.CAPABILITY
        assert decision.confidence == 0.95

    def test_routing_decision_to_response_dict(self):
        """Test converting decision to response dict."""
        decision = RoutingDecision(
            decision=CapabilityDecision.CHAT,
            confidence=0.0,
            reply="Hello!",
            metadata={"route": "chat"},
        )

        d = decision.to_response_dict()

        assert d["decision"] == "chat"
        assert d["reply"] == "Hello!"


class TestCapabilityRoutingLog:
    """Tests for CapabilityRoutingLog entity."""

    def test_create_routing_log(self):
        """Test creating a routing log."""
        log = CapabilityRoutingLog(
            entrypoint="terminal",
            user_id=1,
            session_id="test-session",
            raw_message="What is the system status?",
            retrieved_candidates=["builtin.system_status"],
            selected_capability_key="builtin.system_status",
            confidence=0.95,
            decision=CapabilityDecision.CAPABILITY,
        )

        assert log.entrypoint == "terminal"
        assert log.decision == CapabilityDecision.CAPABILITY


class TestCapabilitySyncLog:
    """Tests for CapabilitySyncLog entity."""

    def test_create_sync_log(self):
        """Test creating a sync log."""
        now = datetime.now(timezone.utc)
        log = CapabilitySyncLog(
            sync_type="full",
            started_at=now,
            finished_at=now,
            total_discovered=100,
            created_count=50,
            updated_count=30,
            disabled_count=5,
            error_count=0,
        )

        assert log.sync_type == "full"
        assert log.total_discovered == 100
        assert log.created_count == 50


class TestEnums:
    """Tests for enum types."""

    def test_source_type_enum(self):
        """Test SourceType enum values."""
        assert SourceType.BUILTIN.value == "builtin"
        assert SourceType.TERMINAL_COMMAND.value == "terminal_command"
        assert SourceType.MCP_TOOL.value == "mcp_tool"
        assert SourceType.API.value == "api"

    def test_route_group_enum(self):
        """Test RouteGroup enum values."""
        assert RouteGroup.BUILTIN.value == "builtin"
        assert RouteGroup.TOOL.value == "tool"
        assert RouteGroup.READ_API.value == "read_api"
        assert RouteGroup.WRITE_API.value == "write_api"
        assert RouteGroup.UNSAFE_API.value == "unsafe_api"

    def test_risk_level_enum(self):
        """Test RiskLevel enum values."""
        assert RiskLevel.SAFE.value == "safe"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_capability_decision_enum(self):
        """Test CapabilityDecision enum values."""
        assert CapabilityDecision.CAPABILITY.value == "capability"
        assert CapabilityDecision.ASK_CONFIRMATION.value == "ask_confirmation"
        assert CapabilityDecision.CHAT.value == "chat"
        assert CapabilityDecision.FALLBACK.value == "fallback"
