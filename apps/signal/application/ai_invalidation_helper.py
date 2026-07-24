"""Application facade for parsing natural-language invalidation rules."""

from __future__ import annotations

from typing import TypedDict

from apps.signal.domain.parser import InvalidationLogicParser


class ParsedInvalidationPayload(TypedDict, total=False):
    """JSON-safe result returned to the signal interface."""

    conditions: list[dict[str, object]]
    logic: str
    explanation: str
    confidence: float
    error: str
    suggestions: list[str]


def ai_parse_invalidation_logic(user_input: str) -> ParsedInvalidationPayload:
    """Parse an invalidation sentence through the deterministic domain parser.

    The facade keeps parsing semantics in Domain while presenting a stable
    JSON payload to the HTTP interface. The name is retained for API
    compatibility with the existing endpoint.
    """

    result = InvalidationLogicParser().parse(user_input)
    if not result.success or result.rule is None:
        suggestions = [
            "请使用明确指标、比较符和阈值，例如“PMI 跌破 50”",
        ]
        suggestions.extend(result.warnings)
        return {
            "error": result.error or "无法解析证伪逻辑",
            "suggestions": suggestions,
        }

    rule_payload = result.rule.to_dict()
    return {
        "conditions": rule_payload["conditions"],
        "logic": str(rule_payload["logic"]),
        "explanation": result.rule.human_readable,
        "confidence": 1.0 if not result.warnings else 0.8,
    }
