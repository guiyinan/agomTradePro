"""
AI Capability Catalog Domain Services.

Pure Python logic for capability retrieval, scoring, and decision.
"""

import re
from dataclasses import dataclass
from typing import Any

from .entities import (
    CapabilityDefinition,
    RouteGroup,
    RoutingContext,
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
        "capability_key": 20.0,
        "name": 10.0,
        "summary": 8.0,
        "tags": 6.0,
        "when_to_use": 5.0,
        "category": 4.0,
        "description": 3.0,
        "examples": 2.0,
    }

    INTENT_ALIASES = {
        "market_temperature": (
            "market_temperature",
            "market temperature",
            "market thermometer",
            "sentiment temperature",
            "市场温度",
            "市场温度计",
            "市场热度",
            "市场过热",
            "过热风险",
        ),
        "fund_ranking": (
            "fund ranking",
            "fund rank",
            "fund.read.ranking",
            "基金排名",
            "基金排行",
        ),
    }
    SYSTEM_STATUS_INTENT_RE = re.compile(
        r"(?:系统.{0,6}(?:状态|健康|就绪|可用)|服务.{0,4}(?:状态|健康|可用)|"
        r"数据库|redis|celery|worker|system\s+(?:status|health)|"
        r"health\s*check|readiness)",
        re.IGNORECASE,
    )

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
        query_lower = self._normalize_text(query)
        query_words = set(re.findall(r"\w+", query_lower))

        if (
            capability.capability_key == "builtin.system_status"
            and not self.SYSTEM_STATUS_INTENT_RE.search(query_lower)
        ):
            return RetrievalScore(capability=capability, score=0.0, matched_fields=[])

        total_score = 0.0
        matched_fields = []

        field_values = {
            "capability_key": [self._normalize_text(capability.capability_key)],
            "name": [capability.name.lower()],
            "summary": [capability.summary.lower()],
            "description": [capability.description.lower()],
            "category": [capability.category.lower()],
            "tags": [t.lower() for t in capability.tags],
            "when_to_use": [w.lower() for w in capability.when_to_use],
            "examples": [e.lower() for e in capability.examples],
        }

        for field_name, values in field_values.items():
            field_score = 0.0
            for value in values:
                field_score += self._compute_text_score(value, query_lower, query_words)

            if field_score > 0:
                total_score += field_score * self.FIELD_WEIGHTS.get(field_name, 1.0)
                matched_fields.append(field_name)

        negative_score = sum(
            self._compute_text_score(
                self._normalize_text(value),
                query_lower,
                query_words,
            )
            for value in capability.when_not_to_use
        )
        if negative_score > 0:
            total_score -= negative_score * 6.0
            matched_fields.append("when_not_to_use")

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

        text = self._normalize_text(text)
        if query_lower in text:
            score += 3.0

        text_words = set(re.findall(r"\w+", text))
        overlap = query_words & text_words
        if overlap:
            score += len(overlap) * 0.5

        key_patterns = [
            (r"regime|市场环境|象限", "market_regime"),
            (r"温度|热度|过热|接盘|散户热度|市场温度|市场热度", "market_temperature"),
            (r"pmi|cpi|ppi|m2|宏观|macro", "macro"),
            (r"policy|政策|档位", "policy"),
            (r"signal|信号", "signal"),
            (r"backtest|回测", "backtest"),
            (r"portfolio|持仓|账户", "portfolio"),
        ]

        if self.SYSTEM_STATUS_INTENT_RE.search(query_lower) and re.search(
            r"system|health|readiness|状态|健康|数据库|redis|celery|worker",
            text,
            re.IGNORECASE,
        ):
            score += 2.0

        for pattern, _category in key_patterns:
            if re.search(pattern, query_lower) and re.search(pattern, text):
                score += 1.5
                break

        for aliases in self.INTENT_ALIASES.values():
            if self._contains_alias(query_lower, aliases) and self._contains_alias(text, aliases):
                score += 3.0

        return score

    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = str(value or "").strip().lower().replace("_", " ").replace(".", " ")
        return re.sub(r"\s+", " ", normalized)

    @staticmethod
    def _contains_alias(text: str, aliases: tuple[str, ...]) -> bool:
        normalized_text = text.replace("_", " ").replace(".", " ")
        return any(
            alias.replace("_", " ").replace(".", " ") in normalized_text for alias in aliases
        )

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


class CapabilityCatalogSearch:
    """Rank catalog results with phrase aliases and multi-token OR matching."""

    FIELD_WEIGHTS = (8.0, 6.0, 4.0, 3.0, 2.0, 2.0)

    def search(
        self,
        capabilities: list[CapabilityDefinition],
        query: str,
    ) -> list[CapabilityDefinition]:
        """Return matching capabilities ordered by deterministic relevance."""

        scorer = CapabilityRetrievalScorer()
        normalized_query = scorer._normalize_text(query)
        query_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", normalized_query))
        ranked: list[tuple[float, CapabilityDefinition]] = []

        for capability in capabilities:
            fields = (
                scorer._normalize_text(capability.capability_key),
                scorer._normalize_text(capability.name),
                scorer._normalize_text(capability.summary),
                scorer._normalize_text(capability.description),
                scorer._normalize_text(" ".join(capability.tags)),
                scorer._normalize_text(" ".join(capability.examples)),
            )
            score = 0.0
            for weight, field in zip(self.FIELD_WEIGHTS, fields, strict=True):
                if normalized_query == field:
                    score += weight * 10
                elif normalized_query and normalized_query in field:
                    score += weight * 3
                field_tokens = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", field))
                score += weight * len(query_tokens & field_tokens)

            for aliases in scorer.INTENT_ALIASES.values():
                if scorer._contains_alias(normalized_query, aliases) and any(
                    scorer._contains_alias(field, aliases) for field in fields
                ):
                    score += 100.0

            if score > 0:
                ranked.append((score, capability))

        ranked.sort(key=lambda item: (-item[0], item[1].capability_key))
        return [capability for _, capability in ranked]


class CapabilityParameterPolicy:
    """Normalize parameters against the selected capability contract."""

    PATH_PARAM_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")

    def normalize(
        self,
        capability: CapabilityDefinition,
        supplied_params: dict[str, Any] | None,
        *,
        default_account_id: Any = None,
    ) -> dict[str, Any]:
        """Filter unsupported values and apply the default account only when declared."""

        params = dict(supplied_params or {})
        schema = dict(capability.input_schema or {})
        properties = set((schema.get("properties") or {}).keys())
        path_params = set(
            self.PATH_PARAM_RE.findall(str(capability.execution_target.get("path") or ""))
        )
        allowed = properties | path_params

        if allowed or schema.get("additionalProperties") is False:
            params = {key: value for key, value in params.items() if key in allowed}

        if default_account_id is not None and "account_id" in allowed:
            params.setdefault("account_id", default_account_id)
        return params


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
            "web": capability.enabled_for_chat,
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
            return user_is_admin
        if capability.visibility in (Visibility.ADMIN, Visibility.HIDDEN):
            return user_is_admin
        return False


class CapabilitySemanticDeduper:
    """Deduplicate capabilities that represent the same business semantic."""

    def deduplicate(
        self,
        capabilities: list[CapabilityDefinition],
        *,
        entrypoint: str,
    ) -> list[CapabilityDefinition]:
        grouped: dict[str, list[CapabilityDefinition]] = {}
        passthrough: list[CapabilityDefinition] = []

        for capability in capabilities:
            semantic_key = capability.semantic_key.strip()
            if not semantic_key:
                passthrough.append(capability)
                continue
            grouped.setdefault(semantic_key, []).append(capability)

        deduped = list(passthrough)
        for semantic_key in sorted(grouped):
            selected = self._select_for_entrypoint(grouped[semantic_key], entrypoint=entrypoint)
            deduped.extend(selected)
        return deduped

    def _select_for_entrypoint(
        self,
        candidates: list[CapabilityDefinition],
        *,
        entrypoint: str,
    ) -> list[CapabilityDefinition]:
        ordered = sorted(
            candidates,
            key=lambda capability: (
                self._source_rank(capability.source_type, entrypoint=entrypoint),
                -capability.priority_weight,
                capability.capability_key,
            ),
        )

        if entrypoint in {"web", "chat"}:
            preferred = [cap for cap in ordered if cap.source_type != SourceType.MCP_TOOL]
            if preferred:
                return preferred[:1]
            return []

        return ordered[:1]

    def _source_rank(self, source_type: SourceType, *, entrypoint: str) -> int:
        if entrypoint in {"terminal", "agent"}:
            order = {
                SourceType.BUILTIN: 0,
                SourceType.TERMINAL_COMMAND: 1,
                SourceType.MCP_TOOL: 2,
                SourceType.API: 3,
            }
        else:
            order = {
                SourceType.BUILTIN: 0,
                SourceType.TERMINAL_COMMAND: 1,
                SourceType.API: 2,
                SourceType.MCP_TOOL: 3,
            }
        return order.get(source_type, 99)


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
            "semantic_key": "system.status",
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
            "semantic_key": "market.regime",
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
    def get_by_key(cls, key: str) -> dict[str, Any] | None:
        """Get a builtin capability by key."""
        for cap in cls.BUILTIN_CAPABILITIES:
            if cap["capability_key"] == key:
                return cap.copy()
        return None
