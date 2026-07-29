"""Application-facing helpers for alpha interface views."""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Protocol, TypedDict, TypeVar, cast

from apps.account.application.interface_services import find_user_by_id
from apps.alpha.application.repository_provider import get_alpha_score_cache_repository
from apps.alpha.application.services import AlphaService

TAlphaUser = TypeVar("TAlphaUser")


class AlphaCacheRecord(Protocol):
    """Persisted cache identity returned to the HTTP boundary."""

    @property
    def pk(self) -> int | None:
        """Return the cache primary key."""


class AlphaScoreUploadItem(TypedDict):
    """Canonical score item persisted in an uploaded Qlib cache."""

    code: str
    score: float
    rank: int
    factors: dict[str, float]
    confidence: float
    source: str


class AlphaUploadTarget(TypedDict):
    """Existing cache evidence exposed by the write-free preview."""

    id: int
    score_count: int
    asof_date: str | None
    model_id: str
    updated_at: str | None


class AlphaScoreUploadPreview(TypedDict):
    """Write-free description of one exact Alpha cache upsert."""

    operation: str
    scope: str
    universe_id: str
    asof_date: str
    intended_trade_date: str
    model_id: str
    model_artifact_hash: str
    incoming_score_count: int
    incoming_codes: list[str]
    existing: AlphaUploadTarget | None
    writes: list[str]


class FactorExposurePayload(TypedDict):
    """Validated factor exposure returned to the public Alpha API."""

    success: bool
    stock_code: str
    trade_date: str
    provider: str
    factors: dict[str, float]


def _bounded_identifier(
    value: object,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    """Normalize one bounded identifier and reject controls."""

    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        (not normalized and not allow_empty)
        or len(normalized) > maximum
        or any(character in normalized for character in "\r\n\x00")
    ):
        raise ValueError(f"{field_name} is invalid")
    return normalized


def _plain_date(value: object, *, field_name: str) -> date:
    """Require an exact date rather than strings, datetimes or dynamic values."""

    if not isinstance(value, date) or type(value) is not date:
        raise ValueError(f"{field_name} must be a plain date")
    return value


def _user(value: TAlphaUser | None, *, allow_none: bool) -> TAlphaUser | None:
    """Validate one persisted user identity without importing Django."""

    if value is None:
        if allow_none:
            return None
        raise ValueError("actor must be a persisted user")
    user_id = getattr(value, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user id must be a positive integer")
    return value


def _finite_number(value: object, *, field_name: str) -> float:
    """Return one finite numeric value while rejecting bool coercion."""

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be finite")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise ValueError(f"{field_name} must be finite")
    return normalized


def _normalize_scores(scores: object) -> list[AlphaScoreUploadItem]:
    """Validate, detach and rank-order one uploaded score collection."""

    if not isinstance(scores, list) or not 1 <= len(scores) <= 1_000:
        raise ValueError("scores must contain between 1 and 1000 items")
    expected_fields = {"code", "score", "rank", "factors", "confidence", "source"}
    normalized: list[AlphaScoreUploadItem] = []
    for index, item in enumerate(scores):
        if not isinstance(item, dict) or set(item) != expected_fields:
            raise ValueError(f"scores[{index}] does not match the canonical contract")
        code = _bounded_identifier(item["code"], field_name=f"scores[{index}].code", maximum=32)
        rank = item["rank"]
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise ValueError(f"scores[{index}].rank must be a positive integer")
        confidence = _finite_number(item["confidence"], field_name=f"scores[{index}].confidence")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"scores[{index}].confidence must be between 0 and 1")
        raw_factors = item["factors"]
        if not isinstance(raw_factors, dict) or len(raw_factors) > 100:
            raise ValueError(f"scores[{index}].factors must be a bounded object")
        factors: dict[str, float] = {}
        for raw_name, raw_value in raw_factors.items():
            name = _bounded_identifier(
                raw_name,
                field_name=f"scores[{index}].factor name",
                maximum=100,
            )
            if name in factors:
                raise ValueError(f"scores[{index}].factor names must be unique")
            factors[name] = _finite_number(raw_value, field_name=f"scores[{index}].factors[{name}]")
        normalized.append(
            {
                "code": code.upper(),
                "score": _finite_number(item["score"], field_name=f"scores[{index}].score"),
                "rank": rank,
                "factors": factors,
                "confidence": confidence,
                "source": _bounded_identifier(
                    item["source"], field_name=f"scores[{index}].source", maximum=64
                ),
            }
        )
    codes = [item["code"] for item in normalized]
    ranks = [item["rank"] for item in normalized]
    if len(codes) != len(set(codes)):
        raise ValueError("score codes must be unique")
    if len(ranks) != len(set(ranks)):
        raise ValueError("score ranks must be unique")
    return sorted(normalized, key=lambda item: (item["rank"], item["code"]))


def _upload_inputs(
    *,
    write_user: object | None,
    universe_id: object,
    asof_date: object,
    intended_trade_date: object,
    model_id: object,
    model_artifact_hash: object,
    scores: object,
) -> tuple[object | None, str, date, date, str, str, list[AlphaScoreUploadItem]]:
    """Normalize the shared preview/commit upload contract."""

    normalized_asof = _plain_date(asof_date, field_name="asof_date")
    normalized_trade = _plain_date(intended_trade_date, field_name="intended_trade_date")
    if normalized_asof > normalized_trade:
        raise ValueError("asof_date must not be after intended_trade_date")
    return (
        _user(write_user, allow_none=True),
        _bounded_identifier(universe_id, field_name="universe_id", maximum=100),
        normalized_asof,
        normalized_trade,
        _bounded_identifier(model_id, field_name="model_id", maximum=100),
        _bounded_identifier(
            model_artifact_hash,
            field_name="model_artifact_hash",
            maximum=64,
            allow_empty=True,
        ),
        _normalize_scores(scores),
    )


def _existing_target(value: object) -> AlphaUploadTarget | None:
    """Validate and detach the repository's preview evidence."""

    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "id",
        "score_count",
        "asof_date",
        "model_id",
        "updated_at",
    }:
        raise RuntimeError("alpha_upload_target_invalid")
    target_id = value["id"]
    score_count = value["score_count"]
    if (
        isinstance(target_id, bool)
        or not isinstance(target_id, int)
        or target_id <= 0
        or isinstance(score_count, bool)
        or not isinstance(score_count, int)
        or score_count < 0
    ):
        raise RuntimeError("alpha_upload_target_invalid")
    asof_value = value["asof_date"]
    updated_value = value["updated_at"]
    if (asof_value is not None and not isinstance(asof_value, str)) or (
        updated_value is not None and not isinstance(updated_value, str)
    ):
        raise RuntimeError("alpha_upload_target_invalid")
    try:
        model_id = _bounded_identifier(value["model_id"], field_name="model_id", maximum=100)
    except ValueError as exc:
        raise RuntimeError("alpha_upload_target_invalid") from exc
    return {
        "id": target_id,
        "score_count": score_count,
        "asof_date": asof_value,
        "model_id": model_id,
        "updated_at": updated_value,
    }


def resolve_requested_alpha_user(
    *, actor: TAlphaUser, requested_user_id: int | None
) -> TAlphaUser | None:
    """Resolve the user whose alpha scores should be queried."""

    normalized_actor = _user(actor, allow_none=False)
    if requested_user_id is None:
        return normalized_actor
    if (
        isinstance(requested_user_id, bool)
        or not isinstance(requested_user_id, int)
        or requested_user_id <= 0
    ):
        raise ValueError("requested_user_id must be a positive integer")
    resolved = _user(find_user_by_id(requested_user_id), allow_none=True)
    return cast(TAlphaUser | None, resolved)


def upload_alpha_scores(
    *,
    write_user: object | None,
    universe_id: str,
    asof_date: date,
    intended_trade_date: date,
    model_id: str,
    model_artifact_hash: str,
    scores: list[dict[str, Any]],
) -> tuple[AlphaCacheRecord, bool]:
    """Upsert uploaded alpha scores into the cache store."""

    user, universe, normalized_asof, trade_date, model, artifact_hash, normalized_scores = (
        _upload_inputs(
            write_user=write_user,
            universe_id=universe_id,
            asof_date=asof_date,
            intended_trade_date=intended_trade_date,
            model_id=model_id,
            model_artifact_hash=model_artifact_hash,
            scores=scores,
        )
    )
    result = get_alpha_score_cache_repository().upsert_qlib_cache(
        user=user,
        universe_id=universe,
        asof_date=normalized_asof,
        intended_trade_date=trade_date,
        model_id=model,
        model_artifact_hash=artifact_hash,
        scores=cast(list[dict[str, Any]], normalized_scores),
    )
    if not isinstance(result, tuple) or len(result) != 2 or not isinstance(result[1], bool):
        raise RuntimeError("alpha_score_cache_write_invalid")
    cache_record = result[0]
    cache_id = getattr(cache_record, "pk", None)
    if isinstance(cache_id, bool) or not isinstance(cache_id, int) or cache_id <= 0:
        raise RuntimeError("alpha_score_cache_write_invalid")
    return cast(AlphaCacheRecord, cache_record), result[1]


def preview_alpha_score_upload(
    *,
    write_user: object | None,
    universe_id: str,
    asof_date: date,
    intended_trade_date: date,
    model_id: str,
    model_artifact_hash: str,
    scores: list[dict[str, Any]],
) -> AlphaScoreUploadPreview:
    """Read the exact upload target and describe the pending upsert."""

    user, universe, normalized_asof, trade_date, model, artifact_hash, normalized_scores = (
        _upload_inputs(
            write_user=write_user,
            universe_id=universe_id,
            asof_date=asof_date,
            intended_trade_date=intended_trade_date,
            model_id=model_id,
            model_artifact_hash=model_artifact_hash,
            scores=scores,
        )
    )
    existing = _existing_target(
        get_alpha_score_cache_repository().get_upload_target(
            user=user,
            universe_id=universe,
            intended_trade_date=trade_date,
            model_artifact_hash=artifact_hash,
        )
    )
    return {
        "operation": "update" if existing else "create",
        "scope": "system" if user is None else "user",
        "universe_id": universe,
        "asof_date": normalized_asof.isoformat(),
        "intended_trade_date": trade_date.isoformat(),
        "model_id": model,
        "model_artifact_hash": artifact_hash,
        "incoming_score_count": len(normalized_scores),
        "incoming_codes": [item["code"] for item in normalized_scores],
        "existing": existing,
        "writes": ["alpha_score_cache"],
    }


def get_factor_exposure_payload(
    *,
    stock_code: str,
    trade_date: date,
    provider: str,
) -> FactorExposurePayload:
    """Return one stock's factor exposure through the Alpha service boundary."""

    normalized_code = _bounded_identifier(stock_code, field_name="stock_code", maximum=32).upper()
    normalized_date = _plain_date(trade_date, field_name="trade_date")
    normalized_provider = _bounded_identifier(provider, field_name="provider", maximum=64)
    factors = AlphaService().get_factor_exposure(
        stock_code=normalized_code,
        trade_date=normalized_date,
        provider_name=normalized_provider,
    )
    if not isinstance(factors, dict) or len(factors) > 500:
        raise RuntimeError("alpha_factor_exposure_invalid")
    normalized_factors: dict[str, float] = {}
    for raw_name, raw_value in factors.items():
        try:
            name = _bounded_identifier(raw_name, field_name="factor name", maximum=100)
            normalized_factors[name] = _finite_number(raw_value, field_name=f"factor[{name}]")
        except ValueError as exc:
            raise RuntimeError("alpha_factor_exposure_invalid") from exc
    return {
        "success": True,
        "stock_code": normalized_code,
        "trade_date": normalized_date.isoformat(),
        "provider": normalized_provider,
        "factors": normalized_factors,
    }
