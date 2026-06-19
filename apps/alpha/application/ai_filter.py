"""AI second-pass filtering for Alpha recommendation candidates."""

from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any

from apps.ai_provider.application.chat_completion import generate_chat_completion
from apps.alpha.domain.entities import AlphaResult, StockScore
from apps.data_center.application.query_services import (
    get_latest_market_thermometer_snapshot_payload,
)
from apps.equity.application.query_services import get_stock_context_map

logger = logging.getLogger(__name__)

MIN_AI_FILTER_CONFIDENCE = 0.60
AI_FILTER_VERDICTS_TO_KEEP = {"buy", "watch"}
AI_FILTER_MAX_INPUT_COUNT = 50
AI_FILTER_MIN_INPUT_COUNT = 20


def get_ai_filter_candidate_limit(top_n: int) -> int:
    """Return the expanded candidate count used before AI filtering."""

    safe_top_n = max(int(top_n or 1), 1)
    return min(AI_FILTER_MAX_INPUT_COUNT, max(safe_top_n * 2, AI_FILTER_MIN_INPUT_COUNT))


class AlphaAISecondPassFilterService:
    """Apply an optional AI review over Alpha-ranked candidates."""

    def apply(
        self,
        result: AlphaResult,
        *,
        top_n: int,
        user: Any | None = None,
        trade_date: date | None = None,
    ) -> AlphaResult:
        """Return an AI-filtered result or the original top-N result on failure."""

        requested_top_n = max(int(top_n or 1), 1)
        candidate_scores = list(result.scores[: get_ai_filter_candidate_limit(requested_top_n)])
        if not result.success or not candidate_scores:
            return self._with_ai_filter_metadata(
                self._truncate_result(result, requested_top_n),
                status="skipped",
                input_count=len(candidate_scores),
                kept_count=len(result.scores[:requested_top_n]),
                decisions_by_code={},
                failure_reason=result.error_message or "alpha_result_unavailable",
            )

        try:
            stock_context = self._load_stock_context(candidate_scores)
            market_context = self._load_market_context()
            messages = self._build_messages(
                result=result,
                candidate_scores=candidate_scores,
                stock_context=stock_context,
                market_context=market_context,
                trade_date=trade_date,
            )
            ai_response = generate_chat_completion(
                messages=messages,
                temperature=0.1,
                max_tokens=1800,
                user=user,
            )
            decisions_by_code = self._parse_ai_response(ai_response, candidate_scores)
            filtered_scores = self._filter_and_rerank(
                candidate_scores,
                decisions_by_code=decisions_by_code,
                top_n=requested_top_n,
            )
        except Exception as exc:
            logger.warning("Alpha AI second-pass filter failed: %s", exc)
            return self._with_ai_filter_metadata(
                self._truncate_result(result, requested_top_n),
                status="failed",
                input_count=len(candidate_scores),
                kept_count=len(result.scores[:requested_top_n]),
                decisions_by_code={},
                failure_reason=str(exc),
            )

        filtered = AlphaResult(
            success=result.success,
            scores=filtered_scores,
            source=result.source,
            timestamp=result.timestamp,
            error_message=result.error_message,
            status=result.status,
            latency_ms=result.latency_ms,
            staleness_days=result.staleness_days,
            invalidation_conditions=list(result.invalidation_conditions),
            metadata=dict(result.metadata or {}),
        )
        return self._with_ai_filter_metadata(
            filtered,
            status="applied",
            input_count=len(candidate_scores),
            kept_count=len(filtered_scores),
            decisions_by_code=decisions_by_code,
        )

    def _load_stock_context(self, scores: list[StockScore]) -> dict[str, dict[str, Any]]:
        """Load stock context through the equity application boundary."""

        try:
            return get_stock_context_map([score.code for score in scores])
        except Exception as exc:
            logger.warning("Alpha AI filter stock context unavailable: %s", exc)
            return {}

    def _load_market_context(self) -> dict[str, Any]:
        """Load market risk context through the data-center query boundary."""

        try:
            return get_latest_market_thermometer_snapshot_payload() or {}
        except Exception as exc:
            logger.warning("Alpha AI filter market context unavailable: %s", exc)
            return {}

    def _build_messages(
        self,
        *,
        result: AlphaResult,
        candidate_scores: list[StockScore],
        stock_context: dict[str, dict[str, Any]],
        market_context: dict[str, Any],
        trade_date: date | None,
    ) -> list[dict[str, str]]:
        """Build a strict JSON-only AI filtering request."""

        payload = {
            "requested_trade_date": trade_date.isoformat() if trade_date else None,
            "alpha_metadata": self._json_safe(result.metadata or {}),
            "market_context": self._json_safe(
                {
                    "observed_at": market_context.get("observed_at"),
                    "score": market_context.get("score"),
                    "band": market_context.get("band"),
                    "change_5d": market_context.get("change_5d"),
                    "change_20d": market_context.get("change_20d"),
                    "must_not_use_for_decision": market_context.get("must_not_use_for_decision"),
                    "blocked_reason": market_context.get("blocked_reason"),
                    "valid_component_count": market_context.get("valid_component_count"),
                }
            ),
            "candidates": [
                self._build_candidate_payload(score, stock_context.get(score.code, {}))
                for score in candidate_scores
            ],
        }
        return [
            {
                "role": "system",
                "content": (
                    "你是一个股票 Alpha 推荐二次筛选器。只能返回 JSON，不要返回 Markdown。"
                    "verdict 只能是 buy、watch、avoid。confidence 和 ai_filter_score 必须在 0 到 1。"
                    "必须为输入中的每个 code 返回一条 decision。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请根据 Alpha 排名、行情、财务估值和市场风险上下文做二次筛选。"
                    "输出格式必须为："
                    '{"decisions":[{"code":"000001.SZ","verdict":"buy","confidence":0.72,'
                    '"ai_filter_score":0.68,"buy_reasons":["..."],'
                    '"no_buy_reasons":["..."],"invalidation_summary":"..."}]}'
                    "\n输入："
                    + json.dumps(payload, ensure_ascii=False, default=str)
                ),
            },
        ]

    def _build_candidate_payload(
        self,
        score: StockScore,
        stock_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Build one compact candidate row for the AI prompt."""

        return self._json_safe(
            {
                "code": score.code,
                "rank": score.rank,
                "alpha_score": score.score,
                "confidence": score.confidence,
                "source": score.source,
                "factors": score.factors,
                "asof_date": score.asof_date,
                "name": stock_context.get("name"),
                "sector": stock_context.get("sector"),
                "market": stock_context.get("market"),
                "close": stock_context.get("close"),
                "volume": stock_context.get("volume"),
                "trade_date": stock_context.get("trade_date"),
                "pe": stock_context.get("pe"),
                "pb": stock_context.get("pb"),
                "ps": stock_context.get("ps"),
                "roe": stock_context.get("roe"),
                "debt_ratio": stock_context.get("debt_ratio"),
                "revenue_growth": stock_context.get("revenue_growth"),
                "profit_growth": stock_context.get("profit_growth"),
                "report_date": stock_context.get("report_date"),
                "valuation_trade_date": stock_context.get("valuation_trade_date"),
            }
        )

    def _parse_ai_response(
        self,
        ai_response: dict[str, Any],
        candidate_scores: list[StockScore],
    ) -> dict[str, dict[str, Any]]:
        """Parse and validate the model JSON response."""

        if ai_response.get("status") not in (None, "success"):
            raise ValueError(ai_response.get("error_message") or "ai_provider_error")
        raw_content = ai_response.get("content")
        if not raw_content:
            raise ValueError("ai_response_empty")

        try:
            payload = json.loads(self._strip_json_fence(str(raw_content)))
        except json.JSONDecodeError as exc:
            raise ValueError(f"ai_response_invalid_json: {exc}") from exc

        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list) or not raw_decisions:
            raise ValueError("ai_response_missing_decisions")

        expected_codes = {score.code.upper() for score in candidate_scores}
        decisions_by_code: dict[str, dict[str, Any]] = {}
        for item in raw_decisions:
            if not isinstance(item, dict):
                raise ValueError("ai_response_decision_not_object")
            code = str(item.get("code") or "").strip().upper()
            if code not in expected_codes:
                raise ValueError(f"ai_response_unknown_code: {code}")
            if code in decisions_by_code:
                raise ValueError(f"ai_response_duplicate_code: {code}")
            verdict = str(item.get("verdict") or "").strip().lower()
            if verdict not in {"buy", "watch", "avoid"}:
                raise ValueError(f"ai_response_invalid_verdict: {code}")
            confidence = self._require_probability(item.get("confidence"), f"{code}.confidence")
            ai_filter_score = self._require_probability(
                item.get("ai_filter_score", confidence),
                f"{code}.ai_filter_score",
            )
            decisions_by_code[code] = {
                "code": code,
                "verdict": verdict,
                "confidence": confidence,
                "ai_filter_score": ai_filter_score,
                "buy_reasons": self._string_list(item.get("buy_reasons")),
                "no_buy_reasons": self._string_list(item.get("no_buy_reasons")),
                "invalidation_summary": str(item.get("invalidation_summary") or ""),
            }

        missing_codes = expected_codes - set(decisions_by_code)
        if missing_codes:
            raise ValueError("ai_response_missing_codes: " + ",".join(sorted(missing_codes)))
        return decisions_by_code

    def _filter_and_rerank(
        self,
        candidate_scores: list[StockScore],
        *,
        decisions_by_code: dict[str, dict[str, Any]],
        top_n: int,
    ) -> list[StockScore]:
        """Keep accepted candidates in original Alpha order and re-rank them."""

        kept: list[StockScore] = []
        for score in candidate_scores:
            decision = decisions_by_code[score.code.upper()]
            if (
                decision["verdict"] not in AI_FILTER_VERDICTS_TO_KEEP
                or decision["confidence"] < MIN_AI_FILTER_CONFIDENCE
            ):
                continue
            factors = dict(score.factors or {})
            factors["ai_filter_score"] = float(decision["ai_filter_score"])
            kept.append(
                StockScore(
                    code=score.code,
                    score=score.score,
                    rank=len(kept) + 1,
                    factors=factors,
                    source=score.source,
                    confidence=score.confidence,
                    model_id=score.model_id,
                    model_artifact_hash=score.model_artifact_hash,
                    asof_date=score.asof_date,
                    intended_trade_date=score.intended_trade_date,
                    universe_id=score.universe_id,
                    feature_set_id=score.feature_set_id,
                    label_id=score.label_id,
                    data_version=score.data_version,
                )
            )
            if len(kept) >= top_n:
                break
        return kept

    def _truncate_result(self, result: AlphaResult, top_n: int) -> AlphaResult:
        """Return a top-N copy of an Alpha result."""

        return AlphaResult(
            success=result.success,
            scores=list(result.scores[:top_n]),
            source=result.source,
            timestamp=result.timestamp,
            error_message=result.error_message,
            status=result.status,
            latency_ms=result.latency_ms,
            staleness_days=result.staleness_days,
            invalidation_conditions=list(result.invalidation_conditions),
            metadata=dict(result.metadata or {}),
        )

    def _with_ai_filter_metadata(
        self,
        result: AlphaResult,
        *,
        status: str,
        input_count: int,
        kept_count: int,
        decisions_by_code: dict[str, dict[str, Any]],
        failure_reason: str = "",
    ) -> AlphaResult:
        """Attach AI filter metadata to the result."""

        metadata = dict(result.metadata or {})
        ai_filter_meta = {
            "enabled": True,
            "status": status,
            "input_count": input_count,
            "kept_count": kept_count,
            "min_ai_confidence": MIN_AI_FILTER_CONFIDENCE,
            "decisions_by_code": decisions_by_code,
        }
        if failure_reason:
            ai_filter_meta["failure_reason"] = failure_reason
        metadata["ai_filter"] = ai_filter_meta
        result.metadata = metadata
        return result

    def _strip_json_fence(self, raw_content: str) -> str:
        """Remove a Markdown JSON fence when a provider ignores the prompt."""

        content = raw_content.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.DOTALL)
        return match.group(1).strip() if match else content

    def _require_probability(self, value: Any, label: str) -> float:
        """Parse a probability value and reject impossible numbers."""

        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"ai_response_invalid_probability: {label}") from exc
        if parsed < 0.0 or parsed > 1.0:
            raise ValueError(f"ai_response_probability_out_of_range: {label}")
        return parsed

    def _string_list(self, value: Any) -> list[str]:
        """Normalize AI reason arrays."""

        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item).strip()]

    def _json_safe(self, value: Any) -> Any:
        """Convert dates and nested structures into JSON-safe primitives."""

        if hasattr(value, "isoformat"):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._json_safe(item) for item in value]
        return value
