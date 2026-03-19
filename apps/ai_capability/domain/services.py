"""
AI Capability Catalog Domain Services.

Pure Python logic for capability retrieval, scoring, and decision.
"""

from dataclasses import dataclass
from typing import Any, Optional
import re

from .entities import (
    CapabilityDefinition,
    CapabilityDecision,
    RoutingContext,
    RoutingDecision,
    RouteGroup,
    SourceType,
)


@dataclass
class RetrievalScore:
    """Score for a retrieved capability"""

    capability: CapabilityDefinition
    score: float
    matched_fields: list[str]


class CapabilityRetrievalScorer:
    """Pure domain logic for scoring capability relevance.

    Uses deterministic scoring based on text matching.
    No embedding or ML models - just keyword and pattern matching.
    """

    FIELD_WEIGHTS = {
        "name": 10.0,
        "summary": 8.0,
        "tags": 6.0,
        "when_to_use": 5.0,
        "category": 4.0,
        "description": 3.0,
        "when_not_to_use": 2.0,
        "examples": 2.0,
    }

    def score_capability(
        self,
        capability: CapabilityDefinition,
        query: str,
    ) -> RetrievalScore:
        """Score a single capability against a query.

        Args:
            capability: The capability to score
            query: The user query string

        Returns:
            RetrievalScore with score and matched fields
        """
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))

        total_score = 0.0
        matched_fields = []

        field_values = {
            "name": [capability.name.lower()],
            "summary": [capability.summary.lower()],
            "description": [capability.description.lower()],
            "category": [capability.category.lower()],
            "tags": [t.lower() for t in capability.tags],
            "when_to_use": [w.lower() for w in capability.when_to_use],
            "when_not_to_use": [w.lower() for w in capability.when_not_to_use],
            "examples": [e.lower() for e in capability.examples],
        }

        for field_name, values in field_values.items():
            field_score = 0.0
            for value in values:
                field_score += self._compute_text_score(value, query_lower, query_words)

            if field_score > 0:
                total_score += field_score * self.FIELD_WEIGHTS.get(field_name, 1.0)
                matched_fields.append(field_name)

        total_score *= capability.priority_weight

        return RetrievalScore(
            capability=capability,
            score=total_score,
            matched_fields=matched_fields,
        )

    def _compute_text_score(
        self,
        text: str,
        query_lower: str,
        query_words: set[str],
    ) -> float:
        """Compute text matching score.

        Uses multiple matching strategies:
        1. Exact substring match
        2. Word overlap
        3. Fuzzy matching for key terms
        """
        score = 0.0

        if query_lower in text:
            score += 3.0

        text_words = set(re.findall(r"\w+", text))
        overlap = query_words & text_words
        if overlap:
            score += len(overlap) * 0.5

        key_patterns = [
            (r"status|状态|健康|health", "system_status"),
            (r"regime|市场环境|象限", "market_regime"),
            (r"pmi|cpi|ppi|m2|宏观|macro", "macro"),
            (r"policy|政策|档位", "policy"),
            (r"signal|信号", "signal"),
            (r"backtest|回测", "backtest"),
            (r"portfolio|持仓|账户", "portfolio"),
        ]

        for pattern, category in key_patterns:
            if re.search(pattern, query_lower) and re.search(pattern, text):
                score += 1.5
                break

        return score

    def retrieve_top_k(
        self,
        capabilities: list[CapabilityDefinition],
        query: str,
        k: int = 5,
        min_score: float = 0.5,
    ) -> list[RetrievalScore]:
        """Retrieve top-k capabilities for a query.

        Args:
            capabilities: List of capabilities to search
            query: User query string
            k: Number of top results to return
            min_score: Minimum score threshold

        Returns:
            List of RetrievalScore objects, sorted by score descending
        """
        scores = []
        for cap in capabilities:
            if not cap.enabled_for_routing:
                continue
            score = self.score_capability(cap, query)
            if score.score >= min_score:
                scores.append(score)

        scores.sort(key=lambda s: s.score, reverse=True)
        return scores[:k]


class CapabilityFilter:
    """Pure domain logic for filtering capabilities by context."""

    def filter_by_context(
        self,
        capabilities: list[CapabilityDefinition],
        context: RoutingContext,
    ) -> list[CapabilityDefinition]:
        """Filter capabilities based on routing context.

        Args:
            capabilities: List of capabilities to filter
            context: Routing context with user and entrypoint info

        Returns:
            Filtered list of capabilities
        """
        filtered = []

        for cap in capabilities:
            if not self._is_enabled_for_entrypoint(cap, context.entrypoint):
                continue

            if cap.requires_mcp and not context.mcp_enabled:
                continue

            if not self._check_visibility(cap, context.user_is_admin):
                continue

            if cap.route_group == RouteGroup.UNSAFE_API and not context.user_is_admin:
                continue

            filtered.append(cap)

        return filtered

    def _is_enabled_for_entrypoint(
        self,
        capability: CapabilityDefinition,
        entrypoint: str,
    ) -> bool:
        """Check if capability is enabled for the given entrypoint."""
        entrypoint_flags = {
            "terminal": capability.enabled_for_terminal,
            "chat": capability.enabled_for_chat,
            "agent": capability.enabled_for_agent,
        }
        return entrypoint_flags.get(entrypoint, False)

    def _check_visibility(
        self,
        capability: CapabilityDefinition,
        user_is_admin: bool,
    ) -> bool:
        """Check if user can see this capability based on visibility."""
        from .entities import Visibility

        if capability.visibility == Visibility.PUBLIC:
            return True
        if capability.visibility == Visibility.INTERNAL:
            return True
        if capability.visibility in (Visibility.ADMIN, Visibility.HIDDEN):
            return user_is_admin
        return False


class BuiltinCapabilityRegistry:
    """Registry for builtin capabilities.

    These are hardcoded capabilities that don't come from
    external sources like MCP tools or API endpoints.
    """

    BUILTIN_CAPABILITIES = [
        {
            "capability_key": "builtin.system_status",
            "source_type": SourceType.BUILTIN,
            "source_ref": "terminal:system_status",
            "name": "System Status",
            "summary": "Check system health and readiness status",
            "description": "Returns current system health including database, Redis, Celery, and critical data status.",
            "route_group": RouteGroup.BUILTIN,
            "category": "system",
            "tags": ["status", "health", "system", "readiness"],
            "when_to_use": [
                "User asks about system status",
                "User wants to check if the system is healthy",
                "User asks about service availability",
            ],
            "when_not_to_use": [
                "User is asking about market data",
                "User wants to execute trades",
            ],
            "examples": [
                "目前系统是什么状态",
                "系统健康吗",
                "check system status",
                "系统就绪吗",
            ],
            "execution_kind": "sync",
            "execution_target": {"type": "builtin", "handler": "system_status"},
            "risk_level": "safe",
            "requires_mcp": False,
            "requires_confirmation": False,
            "enabled_for_routing": True,
            "enabled_for_terminal": True,
            "enabled_for_chat": True,
            "enabled_for_agent": True,
            "visibility": "public",
            "priority_weight": 10.0,
        },
        {
            "capability_key": "builtin.market_regime",
            "source_type": SourceType.BUILTIN,
            "source_ref": "terminal:market_regime",
            "name": "Market Regime",
            "summary": "Get current market regime and policy level",
            "description": "Returns the current macro regime (growth/inflation quadrant) and policy level.",
            "route_group": RouteGroup.BUILTIN,
            "category": "market",
            "tags": ["regime", "macro", "market", "policy"],
            "when_to_use": [
                "User asks about current market regime",
                "User wants to know the macro environment",
                "User asks about policy level",
            ],
            "when_not_to_use": [
                "User is asking about system health",
                "User wants to execute specific analysis",
            ],
            "examples": [
                "当前市场 regime",
                "市场环境如何",
                "current regime",
                "政策档位",
            ],
            "execution_kind": "sync",
            "execution_target": {"type": "builtin", "handler": "market_regime"},
            "risk_level": "safe",
            "requires_mcp": False,
            "requires_confirmation": False,
            "enabled_for_routing": True,
            "enabled_for_terminal": True,
            "enabled_for_chat": True,
            "enabled_for_agent": True,
            "visibility": "public",
            "priority_weight": 10.0,
        },
    ]

    @classmethod
    def get_all(cls) -> list[dict[str, Any]]:
        """Get all builtin capability definitions."""
        return cls.BUILTIN_CAPABILITIES.copy()

    @classmethod
    def get_by_key(cls, key: str) -> Optional[dict[str, Any]]:
        """Get a builtin capability by key."""
        for cap in cls.BUILTIN_CAPABILITIES:
            if cap["capability_key"] == key:
                return cap.copy()
        return None
