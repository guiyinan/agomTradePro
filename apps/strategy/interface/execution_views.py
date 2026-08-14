"""Strategy execution and sandbox-testing JSON endpoints.

Interface handlers validate caller-owned resources and bounded request payloads,
then delegate execution and financial calculations to Application/Domain services.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, cast

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.strategy.application.execution_preview import (
    ExecutionPreviewPolicy,
    ExecutionPreviewRequest,
    evaluate_execution_preview,
)
from apps.strategy.application.interface_services import (
    execute_strategy_for_assignments,
    get_strategy_queryset_for_owner,
)
from apps.strategy.application.script_engine import (
    MAX_SCRIPT_CODE_LENGTH,
    ScriptAPI,
    ScriptExecutionEnvironment,
    SecurityMode,
)
from apps.strategy.interface.serializers import (
    ExecutionEvaluateInputSerializer,
    ExecutionEvaluateOutputSerializer,
)

logger = logging.getLogger(__name__)

StrategyModel = django_apps.get_model("strategy", "StrategyModel")

_MAX_JSON_BODY_BYTES = 100_000


class _MockMacroProvider:
    """Deterministic macro provider used only by sandbox previews."""

    def get_indicator(self, code: str) -> float | None:
        return {
            "CN_PMI_MANUFACTURING": 50.8,
            "CN_CPI_YOY": 2.1,
            "CN_PPI_YOY": -2.8,
        }.get(code)

    def get_all_indicators(self) -> dict[str, float]:
        return {
            "CN_PMI_MANUFACTURING": 50.8,
            "CN_CPI_YOY": 2.1,
            "CN_PPI_YOY": -2.8,
        }


class _MockRegimeProvider:
    """Deterministic regime provider used only by sandbox previews."""

    def get_current_regime(self) -> dict[str, Any]:
        return {
            "dominant_regime": "HG",
            "confidence": 0.75,
            "growth_momentum_z": 1.2,
            "inflation_momentum_z": 0.8,
        }


class _MockAssetPoolProvider:
    """Empty asset-pool provider that cannot invent preview candidates."""

    def get_investable_assets(
        self,
        min_score: float = 60.0,
        limit: int = 50,
        include_degraded: bool = False,
    ) -> list[dict[str, Any]]:
        return []


class _MockSignalProvider:
    """Empty signal provider that cannot reuse production signals."""

    def get_valid_signals(self) -> list[dict[str, Any]]:
        return []


class _MockPortfolioProvider:
    """Deterministic portfolio provider used only by sandbox previews."""

    def get_positions(self, portfolio_id: int) -> list[dict[str, Any]]:
        return []

    def get_cash(self, portfolio_id: int) -> float:
        return 100_000.0


def _parse_json_object(
    request: HttpRequest,
    *,
    max_body_bytes: int = _MAX_JSON_BODY_BYTES,
) -> dict[str, Any]:
    """Decode a bounded JSON object from a request."""

    body = request.body
    if len(body) > max_body_bytes:
        raise ValueError(f"请求体不能超过 {max_body_bytes} 字节")
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("无效 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON 请求体必须是对象")
    return cast(dict[str, Any], payload)


def _account_profile_id(request: HttpRequest) -> int:
    """Return the authenticated caller's account-profile identifier."""

    profile_id = getattr(getattr(request.user, "account_profile", None), "id", None)
    if isinstance(profile_id, bool) or not isinstance(profile_id, int) or profile_id <= 0:
        raise PermissionDenied("当前用户缺少账户资料")
    return profile_id


def _optional_positive_int(value: object, *, field_name: str) -> int | None:
    """Validate an optional positive integer JSON field."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} 必须是正整数")
    return value


def _build_preview_script_api(portfolio_id: int) -> ScriptAPI:
    """Build a deterministic, side-effect-free Script API."""

    return ScriptAPI(
        macro_provider=_MockMacroProvider(),
        regime_provider=_MockRegimeProvider(),
        asset_pool_provider=_MockAssetPoolProvider(),
        signal_provider=_MockSignalProvider(),
        portfolio_provider=_MockPortfolioProvider(),
        portfolio_id=portfolio_id,
    )


@login_required
def strategy_execute(request: HttpRequest, strategy_id: int) -> JsonResponse:
    """Execute one owned strategy for its active portfolio assignments."""

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "只支持 POST 请求"}, status=405)

    owner_profile_id = _account_profile_id(request)
    strategy = get_object_or_404(
        get_strategy_queryset_for_owner(owner_profile_id),
        id=strategy_id,
    )

    try:
        data = _parse_json_object(request)
        unknown_fields = set(data) - {"portfolio_id"}
        if unknown_fields:
            raise ValueError(f"不支持的参数: {', '.join(sorted(unknown_fields))}")
        portfolio_id = _optional_positive_int(
            data.get("portfolio_id"),
            field_name="portfolio_id",
        )
        result = execute_strategy_for_assignments(
            strategy_id=cast(int, strategy.id),
            portfolio_id=portfolio_id,
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception:
        logger.exception("Strategy execution failed for strategy_id=%s", strategy_id)
        return JsonResponse(
            {
                "success": False,
                "error": "策略执行失败",
                "execution_id": None,
                "generated_signals": 0,
                "signals_count": 0,
                "failed_rules": [{"error": "策略执行失败"}],
                "duration_ms": 0,
                "executed_portfolios": 0,
            },
            status=500,
        )

    result["message"] = f"策略执行完成，生成 {result['generated_signals']} 个信号"
    return JsonResponse(result)


@login_required
def execution_evaluate(request: HttpRequest) -> JsonResponse:
    """Return a decision/sizing/risk preview without submitting an order."""

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "只支持 POST 请求"}, status=405)

    try:
        payload = _parse_json_object(request)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)

    input_serializer = ExecutionEvaluateInputSerializer(data=payload)
    if not input_serializer.is_valid():
        return JsonResponse(
            {"success": False, "errors": input_serializer.errors},
            status=400,
        )

    data = cast(dict[str, Any], input_serializer.validated_data)
    policy = ExecutionPreviewPolicy(
        signal_threshold=float(getattr(settings, "DECISION_SIGNAL_THRESHOLD", 0.6)),
        confidence_threshold=float(getattr(settings, "DECISION_CONFIDENCE_THRESHOLD", 0.7)),
        regime_alignment_required=bool(
            getattr(settings, "DECISION_REGIME_ALIGNMENT_REQUIRED", True)
        ),
        max_daily_loss_pct=float(getattr(settings, "RISK_MAX_DAILY_LOSS_PCT", 5.0)),
        max_daily_trades=int(getattr(settings, "RISK_MAX_DAILY_TRADES", 10)),
        sizing_method=str(getattr(settings, "SIZING_DEFAULT_METHOD", "fixed_fraction")),
        risk_per_trade_pct=float(getattr(settings, "SIZING_RISK_PER_TRADE_PCT", 1.0)),
        sizing_max_position_pct=float(getattr(settings, "SIZING_MAX_POSITION_PCT", 20.0)),
        risk_max_single_position_pct=float(getattr(settings, "RISK_MAX_SINGLE_POSITION_PCT", 20.0)),
        min_qty=int(getattr(settings, "SIZING_MIN_QTY", 1)),
        min_volume=int(getattr(settings, "RISK_MIN_VOLUME", 100_000)),
        market_max_age_seconds=int(
            getattr(settings, "EXECUTION_PREVIEW_MARKET_MAX_AGE_SECONDS", 300)
        ),
        signal_max_age_seconds=int(
            getattr(settings, "EXECUTION_PREVIEW_SIGNAL_MAX_AGE_SECONDS", 900)
        ),
        regime_max_age_seconds=int(
            getattr(settings, "EXECUTION_PREVIEW_REGIME_MAX_AGE_SECONDS", 86_400)
        ),
        account_max_age_seconds=int(
            getattr(settings, "EXECUTION_PREVIEW_ACCOUNT_MAX_AGE_SECONDS", 300)
        ),
    )
    try:
        output = evaluate_execution_preview(
            ExecutionPreviewRequest(
                symbol=data["symbol"],
                side=data["side"],
                current_price=data["current_price"],
                signal_strength=data["signal_strength"],
                signal_direction=data["signal_direction"],
                signal_confidence=data["signal_confidence"],
                current_regime=data["current_regime"],
                regime_confidence=data["regime_confidence"],
                account_equity=data["account_equity"],
                current_position_value=data["current_position_value"],
                daily_pnl_pct=data["daily_pnl_pct"],
                daily_trade_count=data["daily_trade_count"],
                market_observed_at=data["market_observed_at"],
                signal_observed_at=data["signal_observed_at"],
                regime_observed_at=data["regime_observed_at"],
                account_observed_at=data["account_observed_at"],
                stop_loss_price=data.get("stop_loss_price"),
                atr=data.get("atr"),
                target_regime=data.get("target_regime"),
                volatility_z=data.get("volatility_z"),
                avg_volume=data.get("avg_volume"),
                sizing_method=data.get("sizing_method"),
            ),
            policy=policy,
            evaluated_at=timezone.now(),
        ).to_payload()
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    output_serializer = ExecutionEvaluateOutputSerializer(data=output)
    output_serializer.is_valid(raise_exception=True)
    return JsonResponse(
        {
            "success": True,
            "data": cast(dict[str, Any], output_serializer.validated_data),
        }
    )


@login_required
def test_script(request: HttpRequest) -> JsonResponse:
    """Execute a bounded script against deterministic preview providers."""

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "只支持 POST 请求"}, status=405)

    try:
        data = _parse_json_object(request)
        unknown_fields = set(data) - {"script_code"}
        if unknown_fields:
            raise ValueError(f"不支持的参数: {', '.join(sorted(unknown_fields))}")
        script_code = data.get("script_code")
        if not isinstance(script_code, str) or not script_code.strip():
            raise ValueError("脚本代码不能为空")
        if len(script_code) > MAX_SCRIPT_CODE_LENGTH:
            raise ValueError(f"脚本代码不能超过 {MAX_SCRIPT_CODE_LENGTH} 个字符")

        started_at = time.perf_counter()
        signals = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED).execute(
            script_code=script_code,
            script_api=_build_preview_script_api(portfolio_id=1),
            script_name="<test>",
        )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception:
        logger.exception("Strategy preview script execution failed")
        return JsonResponse(
            {"success": False, "error": "脚本执行失败"},
            status=500,
        )

    execution_time = int((time.perf_counter() - started_at) * 1000)
    return JsonResponse(
        {
            "success": True,
            "execution_time": execution_time,
            "signals_count": len(signals),
            "signals": signals,
            "output": f"脚本执行成功，生成 {len(signals)} 个信号",
        }
    )


@login_required
def test_strategy(request: HttpRequest, strategy_id: int) -> JsonResponse:
    """Preview an owned strategy with deterministic, non-production data."""

    if request.method != "POST":
        return JsonResponse({"success": False, "error": "只支持 POST 请求"}, status=405)

    owner_profile_id = _account_profile_id(request)
    strategy = get_object_or_404(
        get_strategy_queryset_for_owner(owner_profile_id),
        id=strategy_id,
    )

    try:
        data = _parse_json_object(request)
        unknown_fields = set(data) - {"portfolio_id"}
        if unknown_fields:
            raise ValueError(f"不支持的参数: {', '.join(sorted(unknown_fields))}")
        portfolio_id = _optional_positive_int(
            data.get("portfolio_id"),
            field_name="portfolio_id",
        )
        if portfolio_id is None:
            raise ValueError("缺少 portfolio_id 参数")

        started_at = time.perf_counter()
        signals: list[dict[str, Any]] = []
        if strategy.strategy_type in {"script_based", "hybrid"} and strategy.script_config:
            script_code = strategy.script_config.script_code
            if not isinstance(script_code, str) or len(script_code) > MAX_SCRIPT_CODE_LENGTH:
                raise ValueError("策略脚本无效或过长")
            signals = ScriptExecutionEnvironment(security_mode=SecurityMode.RELAXED).execute(
                script_code=script_code,
                script_api=_build_preview_script_api(portfolio_id),
                script_name=f"test_{strategy.id}",
            )
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception:
        logger.exception("Strategy preview failed for strategy_id=%s", strategy_id)
        return JsonResponse(
            {"success": False, "error": "策略测试失败"},
            status=500,
        )

    return JsonResponse(
        {
            "success": True,
            "execution_time": int((time.perf_counter() - started_at) * 1000),
            "signals_count": len(signals),
            "signals": signals,
        }
    )


__all__ = [
    "execution_evaluate",
    "strategy_execute",
    "test_script",
    "test_strategy",
]
