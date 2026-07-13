"""Governed Alpha capability handlers."""

from __future__ import annotations

import math
from datetime import date
from typing import Any


def _normalize_scores(scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(scores, list) or not scores:
        raise ValueError("scores must be a non-empty list")
    if len(scores) > 1000:
        raise ValueError("scores must contain at most 1000 items")

    normalized: list[dict[str, Any]] = []
    codes: set[str] = set()
    ranks: set[int] = set()
    allowed_fields = {"code", "score", "rank", "factors", "confidence", "source"}
    for item in scores:
        if not isinstance(item, dict):
            raise ValueError("each score must be an object")
        unknown_fields = set(item) - allowed_fields
        if unknown_fields:
            raise ValueError(f"unknown score fields: {sorted(unknown_fields)}")

        code = str(item.get("code") or "").strip().upper()
        if not code or len(code) > 32:
            raise ValueError("score code must contain 1 to 32 characters")
        try:
            score = float(item["score"])
            rank = int(item["rank"])
            confidence = float(item.get("confidence", 1.0))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("score, rank and confidence must be valid numbers") from exc
        if not math.isfinite(score) or not math.isfinite(confidence):
            raise ValueError("score and confidence must be finite")
        if rank < 1 or not 0.0 <= confidence <= 1.0:
            raise ValueError("rank must be positive and confidence must be between 0 and 1")

        raw_factors = item.get("factors", {})
        if not isinstance(raw_factors, dict):
            raise ValueError("factors must be an object")
        try:
            factors = {str(key): float(value) for key, value in raw_factors.items()}
        except (TypeError, ValueError) as exc:
            raise ValueError("factor values must be numbers") from exc
        if any(not math.isfinite(value) for value in factors.values()):
            raise ValueError("factor values must be finite")

        source = str(item.get("source", "local_qlib") or "").strip()
        if not source or len(source) > 64:
            raise ValueError("source must contain 1 to 64 characters")
        if code in codes or rank in ranks:
            raise ValueError("score codes and ranks must each be unique")
        codes.add(code)
        ranks.add(rank)
        normalized.append(
            {
                "code": code,
                "score": score,
                "rank": rank,
                "factors": factors,
                "confidence": confidence,
                "source": source,
            }
        )
    return normalized


def import_score_cache(
    universe_id: str,
    asof_date: str,
    intended_trade_date: str,
    scores: list[dict[str, Any]],
    model_id: str = "local_qlib",
    model_artifact_hash: str = "",
    scope: str = "user",
    preview_only: bool = False,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Preview or import one exact Alpha score-cache target through the SDK."""

    from agomtradepro import AgomTradeProClient

    normalized_universe = str(universe_id or "").strip()
    normalized_model = str(model_id or "").strip()
    normalized_hash = str(model_artifact_hash or "").strip()
    normalized_scope = str(scope or "").strip().lower()
    if not normalized_universe or len(normalized_universe) > 100:
        raise ValueError("universe_id must contain 1 to 100 characters")
    if not normalized_model or len(normalized_model) > 100:
        raise ValueError("model_id must contain 1 to 100 characters")
    if len(normalized_hash) > 64:
        raise ValueError("model_artifact_hash must contain at most 64 characters")
    if normalized_scope not in {"user", "system"}:
        raise ValueError("scope must be user or system")
    try:
        parsed_asof = date.fromisoformat(str(asof_date or "").strip())
        parsed_trade = date.fromisoformat(str(intended_trade_date or "").strip())
    except ValueError as exc:
        raise ValueError("dates must use YYYY-MM-DD format") from exc
    if parsed_asof > parsed_trade:
        raise ValueError("asof_date must not be after intended_trade_date")

    payload = {
        "scores": _normalize_scores(scores),
        "universe_id": normalized_universe,
        "asof_date": parsed_asof.isoformat(),
        "intended_trade_date": parsed_trade.isoformat(),
        "model_id": normalized_model,
        "model_artifact_hash": normalized_hash,
        "scope": normalized_scope,
    }
    client = AgomTradeProClient()
    if preview_only:
        response = client.alpha.preview_score_upload(**payload)
        preview = response.get("preview", response)
        return {
            "success": True,
            "preview_only": True,
            "preview": preview,
            "summary": {
                "operation": preview.get("operation"),
                "scope": preview.get("scope", normalized_scope),
                "universe_id": preview.get("universe_id", normalized_universe),
                "intended_trade_date": preview.get("intended_trade_date", parsed_trade.isoformat()),
                "incoming_score_count": preview.get("incoming_score_count", len(payload["scores"])),
                "existing": preview.get("existing"),
                "writes": preview.get("writes", []),
            },
            "message": "Preview generated without changing Alpha score-cache records.",
        }
    return client.alpha.upload_scores(**payload)
