"""Fail-closed routing helpers for evidence-backed financial fact queries."""

from __future__ import annotations

import re
from typing import Any

from apps.ai_capability.domain.entities import (
    CapabilityDecision,
    CapabilityDefinition,
    RoutingContext,
    RoutingDecision,
)
from apps.ai_capability.domain.services import RetrievalScore

EQUITY_RESEARCH_CAPABILITY_SUFFIX = "equity.read.research_snapshot"
_FINANCIAL_FACT_INTENT_RE = re.compile(
    r"股票|个股|证券|股价|行情|估值|财务|资金流|全部信息|所有信息|完整信息|全面分析",
    re.IGNORECASE,
)
_STOCK_CODE_RE = re.compile(r"\b\d{6}(?:\.(?:SH|SZ|BJ))?\b", re.IGNORECASE)
_ABOUT_EQUITY_RE = re.compile(
    r"关于\s*([\u4e00-\u9fffA-Za-z0-9]{2,20}?)(?:的)?(?:所有|全部|完整|全面|信息|资料|情况)",
    re.IGNORECASE,
)


def is_financial_fact_query(message: str) -> bool:
    """Return whether free-form generation could fabricate decision facts."""

    return _FINANCIAL_FACT_INTENT_RE.search(message) is not None


def _extract_equity_query_entity(message: str) -> str | None:
    """Extract a canonical code or an exact-name candidate from a user request."""

    code_match = _STOCK_CODE_RE.search(message)
    if code_match is not None:
        return code_match.group(0).upper()
    name_match = _ABOUT_EQUITY_RE.search(message)
    if name_match is None:
        return None
    value = name_match.group(1).strip()
    return value or None


def match_equity_research_capability(
    capabilities: list[CapabilityDefinition],
    message: str,
    context: RoutingContext,
) -> list[RetrievalScore]:
    """Deterministically match financial fact questions to the evidence read."""

    entity = _extract_equity_query_entity(message)
    if entity is None or not is_financial_fact_query(message):
        return []
    capability = next(
        (
            item
            for item in capabilities
            if item.capability_key.endswith(EQUITY_RESEARCH_CAPABILITY_SUFFIX)
        ),
        None,
    )
    if capability is None:
        return []
    supplied_params = dict(context.context.get("params", {}) or {})
    supplied_params.setdefault("stock_code", entity)
    context.context["params"] = supplied_params
    return [
        RetrievalScore(
            capability=capability,
            score=10.0,
            matched_fields=["financial_fact_intent", "equity_entity"],
        )
    ]


def build_financial_evidence_blocked_decision(
    *,
    candidates: list[dict[str, Any]],
    context: RoutingContext,
    reason: str,
    rejected_candidates: list[str],
    answer_chain: dict[str, Any],
) -> RoutingDecision:
    """Build a stable block instead of asking a model to invent financial facts."""

    block_reason = "未找到可执行的金融数据能力，无法提供可核验的证券事实。"
    return RoutingDecision(
        decision=CapabilityDecision.CHAT,
        selected_capability_key=None,
        confidence=0.0,
        candidate_capabilities=candidates,
        requires_confirmation=False,
        reply=block_reason,
        reason=reason or "Financial evidence capability is unavailable.",
        rejected_candidates=rejected_candidates,
        filled_params=context.context.get("params", {}) or {},
        metadata={
            "route": "financial_evidence_blocked",
            "provider": "capability-router",
            "model": "none",
        },
        answer_chain=answer_chain,
        result={
            "status": "missing",
            "must_not_use_for_decision": True,
            "block_reason_code": "financial_evidence_capability_unavailable",
            "block_reason": block_reason,
        },
    )
