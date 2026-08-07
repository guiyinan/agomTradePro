"""Strategy HTML page views and form-flow helpers.

Interface层:
- 承载策略列表/创建/详情/编辑/状态切换等页面端点
- 只做输入验证和输出格式化，禁止业务逻辑
"""

import json
import logging
from enum import Enum
from typing import Any, Protocol, cast

from django.apps import apps as django_apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, render
from rest_framework import serializers as drf_serializers
from rest_framework import status

from apps.strategy.application.interface_services import (
    build_strategy_list_context,
    delete_strategy_script_config,
    get_strategy_ai_config,
    get_strategy_position_rule,
    get_strategy_script_config,
    list_active_ai_providers_for_user,
    list_active_chain_configs,
    list_active_prompt_templates,
    replace_strategy_rule_conditions,
)
from apps.strategy.interface.serializers import (
    AIStrategyConfigSerializer,
    PositionManagementRuleSerializer,
    RuleConditionSerializer,
    ScriptConfigSerializer,
    StrategySerializer,
)
from core.exceptions import DuplicateResourceError, InvalidInputError

logger = logging.getLogger(__name__)

AIStrategyConfigModel = django_apps.get_model("strategy", "AIStrategyConfigModel")
ScriptConfigModel = django_apps.get_model("strategy", "ScriptConfigModel")
StrategyModel = django_apps.get_model("strategy", "StrategyModel")


class _AccountProfile(Protocol):
    """Persisted account profile required by owner-scoped strategy pages."""

    id: int


class _StrategyRecord(Protocol):
    """Minimal ORM record surface consumed by the page form workflow."""

    id: int
    strategy_type: str
    version: int
    is_active: bool
    rules: Any
    execution_logs: Any

    def save(self) -> None: ...


class _AIConfigRecord(Protocol):
    prompt_template_id: int | None
    chain_config_id: int | None
    ai_provider_id: int | None
    temperature: float
    max_tokens: int
    approval_mode: str
    confidence_threshold: float


class _PositionRuleRecord(Protocol):
    name: str
    description: str
    is_active: bool
    price_precision: int
    variables_schema: list[dict[str, Any]]
    buy_condition_expr: str
    sell_condition_expr: str
    buy_price_expr: str
    sell_price_expr: str
    stop_loss_expr: str
    take_profit_expr: str
    position_size_expr: str
    metadata: dict[str, Any]


class _ScriptConfigRecord(Protocol):
    version: str


class _Unset(Enum):
    TOKEN = "unset"


_UNSET = _Unset.TOKEN
DEFAULT_SCRIPT_ALLOWED_MODULES: list[str] = [
    "math",
    "datetime",
    "statistics",
    "pandas",
    "numpy",
]
DEFAULT_SCRIPT_SANDBOX_CONFIG: dict[str, str] = {"mode": "relaxed"}
VALID_STRATEGY_TYPES: set[str] = {
    str(choice[0]) for choice in (StrategyModel._meta.get_field("strategy_type").choices or ())
}
VALID_SCRIPT_LANGUAGES: set[str] = {
    str(choice[0])
    for choice in (ScriptConfigModel._meta.get_field("script_language").choices or ())
}
VALID_AI_APPROVAL_MODES: set[str] = {
    str(choice[0])
    for choice in (AIStrategyConfigModel._meta.get_field("approval_mode").choices or ())
}
DEFAULT_POSITION_RULE_VARIABLES: list[dict[str, Any]] = [
    {"name": "current_price", "type": "number", "required": True},
    {"name": "support_price", "type": "number", "required": True},
    {"name": "resistance_price", "type": "number", "required": True},
    {"name": "structure_low", "type": "number", "required": True},
    {"name": "atr", "type": "number", "required": True},
    {"name": "account_equity", "type": "number", "required": True},
    {"name": "risk_per_trade_pct", "type": "number", "required": True},
    {"name": "entry_buffer_pct", "type": "number", "required": False},
]
DEFAULT_POSITION_RULE_VALUES: dict[str, Any] = {
    "name": "ATR风险仓位规则",
    "description": "基于支撑位、阻力位和ATR计算买卖价格、止损止盈与下单仓位。",
    "is_active": True,
    "price_precision": 2,
    "variables_schema": DEFAULT_POSITION_RULE_VARIABLES,
    "buy_condition_expr": "current_price <= support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
    "sell_condition_expr": "current_price >= resistance_price",
    "buy_price_expr": "support_price * (1 + (entry_buffer_pct if entry_buffer_pct else 0))",
    "sell_price_expr": "resistance_price",
    "stop_loss_expr": "min(structure_low, buy_price - 2 * atr)",
    "take_profit_expr": "buy_price + 2 * abs(buy_price - stop_loss_price)",
    "position_size_expr": "(account_equity * risk_per_trade_pct) / abs(buy_price - stop_loss_price)",
    "metadata": {"template": "atr_risk"},
}


def _json_error(message: str, status_code: int = status.HTTP_400_BAD_REQUEST) -> JsonResponse:
    """Return a consistent JSON error payload for HTML form endpoints."""
    return JsonResponse({"success": False, "error": message}, status=status_code)


def _format_validation_detail(detail: Any) -> str:
    """Flatten DRF validation details into a compact human-readable string."""
    if isinstance(detail, dict):
        parts = [f"{key}: {_format_validation_detail(value)}" for key, value in detail.items()]
        return "; ".join(parts)
    if isinstance(detail, list):
        return "; ".join(_format_validation_detail(item) for item in detail)
    return str(detail)


def _parse_rules_payload(
    raw_value: str | None,
    preserve_existing: bool = False,
) -> list[Any] | _Unset:
    """Parse rule payload JSON from the page form."""
    if raw_value is None:
        return _UNSET if preserve_existing else []

    try:
        rules_payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise InvalidInputError("规则配置格式无效，无法保存") from exc

    if not isinstance(rules_payload, list):
        raise InvalidInputError("规则配置必须是数组格式")
    return rules_payload


def _parse_script_payload(
    raw_value: str | None,
    preserve_existing: bool = False,
) -> str | _Unset:
    """Parse script payload from the page form."""
    if raw_value is None:
        return _UNSET if preserve_existing else ""
    return raw_value


def _parse_json_form_field(
    raw_value: str | None,
    field_label: str,
    default_value: Any,
) -> Any:
    """Parse JSON textarea values submitted from strategy forms."""
    if raw_value is None or not raw_value.strip():
        return json.loads(json.dumps(default_value))
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise InvalidInputError(f"{field_label} 必须是有效 JSON") from exc


def _parse_optional_int(raw_value: str | None, field_label: str) -> int | None:
    """Parse optional foreign-key ids from HTML form fields."""
    if raw_value is None or raw_value == "":
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError) as exc:
        raise InvalidInputError(f"{field_label} 选择无效") from exc


def _build_ai_config_form(
    ai_config: _AIConfigRecord | None = None,
) -> dict[str, Any]:
    """Build template-friendly AI config defaults."""
    return {
        "prompt_template_id": ai_config.prompt_template_id if ai_config else None,
        "chain_config_id": ai_config.chain_config_id if ai_config else None,
        "ai_provider_id": ai_config.ai_provider_id if ai_config else None,
        "temperature": ai_config.temperature if ai_config else 0.7,
        "max_tokens": ai_config.max_tokens if ai_config else 2000,
        "approval_mode": ai_config.approval_mode if ai_config else "conditional",
        "confidence_threshold": ai_config.confidence_threshold if ai_config else 0.8,
    }


def _build_position_rule_form(
    position_rule: _PositionRuleRecord | None = None,
) -> dict[str, Any]:
    """Build template-friendly position rule defaults."""
    if position_rule is None:
        values: dict[str, Any] = json.loads(
            json.dumps(DEFAULT_POSITION_RULE_VALUES, ensure_ascii=False)
        )
    else:
        values = {
            "name": position_rule.name,
            "description": position_rule.description,
            "is_active": position_rule.is_active,
            "price_precision": position_rule.price_precision,
            "variables_schema": position_rule.variables_schema,
            "buy_condition_expr": position_rule.buy_condition_expr,
            "sell_condition_expr": position_rule.sell_condition_expr,
            "buy_price_expr": position_rule.buy_price_expr,
            "sell_price_expr": position_rule.sell_price_expr,
            "stop_loss_expr": position_rule.stop_loss_expr,
            "take_profit_expr": position_rule.take_profit_expr,
            "position_size_expr": position_rule.position_size_expr,
            "metadata": position_rule.metadata,
        }

    values["variables_schema_json"] = json.dumps(
        values.get("variables_schema") or [],
        ensure_ascii=False,
        indent=2,
    )
    values["metadata_json"] = json.dumps(
        values.get("metadata") or {},
        ensure_ascii=False,
        indent=2,
    )
    return values


def _account_profile(request: HttpRequest) -> _AccountProfile:
    """Return the persisted owner profile required by strategy pages."""

    profile = getattr(request.user, "account_profile", None)
    if not isinstance(getattr(profile, "id", None), int):
        raise PermissionDenied("Authenticated user has no persisted account profile")
    return cast(_AccountProfile, profile)


def _authenticated_user_id(request: HttpRequest) -> int:
    """Return a persisted user ID for user-scoped configuration choices."""

    user = request.user
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int):
        raise PermissionDenied("Authenticated user has no persisted ID")
    return user_id


def _strategy_record(value: Any) -> _StrategyRecord:
    """Validate a serializer/ORM result before page workflow consumption."""

    if not isinstance(getattr(value, "id", None), int):
        raise InvalidInputError("策略记录未持久化")
    return cast(_StrategyRecord, value)


def _build_strategy_form_context(
    request: HttpRequest,
    strategy: _StrategyRecord | None = None,
) -> dict[str, Any]:
    """Build shared context for strategy create/edit/detail pages."""
    ai_config: _AIConfigRecord | None = (
        get_strategy_ai_config(strategy.id) if strategy is not None else None
    )
    position_rule: _PositionRuleRecord | None = (
        get_strategy_position_rule(strategy.id) if strategy is not None else None
    )
    context: dict[str, Any] = {
        "prompt_templates": list_active_prompt_templates(),
        "chain_configs": list_active_chain_configs(),
        "ai_providers": list_active_ai_providers_for_user(_authenticated_user_id(request)),
        "ai_config": ai_config,
        "ai_config_form": _build_ai_config_form(ai_config),
        "position_rule": position_rule,
        "position_rule_form": _build_position_rule_form(position_rule),
    }
    if strategy is not None:
        context["strategy"] = strategy
    return context


def _build_strategy_serializer(
    request: HttpRequest,
    existing_strategy: _StrategyRecord | None = None,
) -> StrategySerializer:
    """Build a validated serializer for strategy base fields."""
    name = (request.POST.get("name") or "").strip()
    if not name:
        raise InvalidInputError("策略名称不能为空")

    submitted_strategy_type = (request.POST.get("strategy_type") or "").strip()
    if existing_strategy is None:
        strategy_type = submitted_strategy_type
        if strategy_type not in VALID_STRATEGY_TYPES:
            raise InvalidInputError("策略类型无效")
        version = request.POST.get("version", 1)
    else:
        if submitted_strategy_type and submitted_strategy_type != existing_strategy.strategy_type:
            raise InvalidInputError("策略类型创建后不可修改")
        strategy_type = existing_strategy.strategy_type
        version = existing_strategy.version + 1

    serializer = StrategySerializer(
        existing_strategy,
        data={
            "name": name,
            "description": request.POST.get("description", ""),
            "strategy_type": strategy_type,
            "version": version,
            "is_active": existing_strategy.is_active if existing_strategy is not None else False,
            "max_position_pct": request.POST.get("max_position_pct", 20),
            "max_total_position_pct": request.POST.get("max_total_position_pct", 95),
            "stop_loss_pct": request.POST.get("stop_loss_pct") or None,
        },
    )
    serializer.is_valid(raise_exception=True)
    return serializer


def _replace_rule_conditions(
    strategy: _StrategyRecord,
    rules_payload: list[Any] | _Unset,
) -> None:
    """Replace strategy rule conditions after validating the submitted payload."""
    if rules_payload is _UNSET:
        return

    validated_rules: list[dict[str, Any]] = []
    for index, rule_data in enumerate(rules_payload, start=1):
        if not isinstance(rule_data, dict):
            raise InvalidInputError(f"第 {index} 条规则格式无效")

        rule_name = str(rule_data.get("rule_name", "")).strip()
        if not rule_name:
            continue

        serializer = RuleConditionSerializer(
            data={
                "strategy": strategy.id,
                "rule_name": rule_name,
                "rule_type": rule_data.get("rule_type", "macro"),
                "condition_json": rule_data.get("condition_json", {}),
                "action": str(rule_data.get("action", "buy")).lower(),
                "weight": rule_data.get("weight", 0.1),
                "target_assets": rule_data.get("target_assets", []),
                "priority": rule_data.get("priority", 10),
                "is_enabled": rule_data.get("is_enabled", True),
            }
        )
        try:
            serializer.is_valid(raise_exception=True)
        except drf_serializers.ValidationError as exc:
            raise InvalidInputError(
                f"第 {index} 条规则校验失败: {_format_validation_detail(exc.detail)}"
            ) from exc
        validated_rules.append(serializer.validated_data)

    replace_strategy_rule_conditions(strategy.id, validated_rules)


def _save_script_config(
    strategy: _StrategyRecord,
    script_code_payload: str | _Unset,
    script_language: str,
) -> None:
    """Create, update, or delete script config based on submitted form data."""
    if script_code_payload is _UNSET:
        return

    existing_config: _ScriptConfigRecord | None = get_strategy_script_config(strategy.id)
    script_code = script_code_payload.strip()

    if not script_code:
        if existing_config is not None:
            delete_strategy_script_config(strategy.id)
        return

    if script_language not in VALID_SCRIPT_LANGUAGES:
        raise InvalidInputError("脚本语言无效")

    serializer = ScriptConfigSerializer(
        existing_config,
        data={
            "strategy": strategy.id,
            "script_language": script_language,
            "script_code": script_code,
            "sandbox_config": DEFAULT_SCRIPT_SANDBOX_CONFIG,
            "allowed_modules": DEFAULT_SCRIPT_ALLOWED_MODULES,
            "version": existing_config.version if existing_config is not None else "1.0",
            "is_active": True,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(
            f"脚本配置校验失败: {_format_validation_detail(exc.detail)}"
        ) from exc
    serializer.save()


def _save_ai_config(strategy: _StrategyRecord, post_data: QueryDict) -> None:
    """Create or update AI strategy config for AI-driven strategies."""
    if strategy.strategy_type != "ai_driven":
        return

    approval_mode = (post_data.get("ai_approval_mode") or "conditional").strip()
    if approval_mode not in VALID_AI_APPROVAL_MODES:
        raise InvalidInputError("AI 审核模式无效")

    existing_config: _AIConfigRecord | None = get_strategy_ai_config(strategy.id)
    serializer = AIStrategyConfigSerializer(
        existing_config,
        data={
            "strategy": strategy.id,
            "prompt_template": _parse_optional_int(
                post_data.get("ai_prompt_template"), "Prompt 模板"
            ),
            "chain_config": _parse_optional_int(post_data.get("ai_chain_config"), "Chain 配置"),
            "ai_provider": _parse_optional_int(post_data.get("ai_provider"), "AI 服务商"),
            "temperature": post_data.get("ai_temperature") or 0.7,
            "max_tokens": post_data.get("ai_max_tokens") or 2000,
            "approval_mode": approval_mode,
            "confidence_threshold": post_data.get("ai_confidence_threshold") or 0.8,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(
            f"AI 配置校验失败: {_format_validation_detail(exc.detail)}"
        ) from exc
    serializer.save()


def _save_position_rule(
    strategy: _StrategyRecord,
    post_data: QueryDict,
) -> None:
    """Create or update the visual position-management rule submitted by the page."""
    if "position_rule_name" not in post_data:
        return

    rule_name = (post_data.get("position_rule_name") or "").strip()
    if not rule_name:
        return

    variables_schema = _parse_json_form_field(
        post_data.get("position_rule_variables_schema"),
        "仓位规则变量定义",
        DEFAULT_POSITION_RULE_VARIABLES,
    )
    metadata = _parse_json_form_field(
        post_data.get("position_rule_metadata"),
        "仓位规则元数据",
        {},
    )
    if not isinstance(variables_schema, list):
        raise InvalidInputError("仓位规则变量定义必须是数组 JSON")
    if not isinstance(metadata, dict):
        raise InvalidInputError("仓位规则元数据必须是对象 JSON")

    existing_rule: _PositionRuleRecord | None = get_strategy_position_rule(strategy.id)
    serializer = PositionManagementRuleSerializer(
        existing_rule,
        data={
            "strategy": strategy.id,
            "name": rule_name,
            "description": post_data.get("position_rule_description", ""),
            "is_active": post_data.get("position_rule_is_active") == "on",
            "price_precision": post_data.get("position_rule_price_precision") or 2,
            "variables_schema": variables_schema,
            "buy_condition_expr": post_data.get("position_rule_buy_condition_expr", ""),
            "sell_condition_expr": post_data.get("position_rule_sell_condition_expr", ""),
            "buy_price_expr": post_data.get("position_rule_buy_price_expr", ""),
            "sell_price_expr": post_data.get("position_rule_sell_price_expr", ""),
            "stop_loss_expr": post_data.get("position_rule_stop_loss_expr", ""),
            "take_profit_expr": post_data.get("position_rule_take_profit_expr", ""),
            "position_size_expr": post_data.get("position_rule_position_size_expr", ""),
            "metadata": metadata,
        },
    )
    try:
        serializer.is_valid(raise_exception=True)
    except drf_serializers.ValidationError as exc:
        raise InvalidInputError(
            f"仓位规则校验失败: {_format_validation_detail(exc.detail)}"
        ) from exc
    serializer.save()


# ========================================================================
# Django HTML Views (Frontend Pages)
# ========================================================================


@login_required
def strategy_list(request: HttpRequest) -> HttpResponse:
    """策略列表页面"""
    context = build_strategy_list_context(_account_profile(request).id)
    return render(request, "strategy/list.html", context)


@login_required
def strategy_create(request: HttpRequest) -> HttpResponse:
    """创建策略页面"""
    if request.method == "POST":
        try:
            strategy_serializer = _build_strategy_serializer(request)
            rules_payload = _parse_rules_payload(request.POST.get("rules_data"))
            script_code_payload = _parse_script_payload(request.POST.get("script_code"))
            script_language = (request.POST.get("script_language") or "python").strip()

            with transaction.atomic():
                strategy = _strategy_record(
                    strategy_serializer.save(created_by=_account_profile(request))
                )
                _replace_rule_conditions(strategy, rules_payload)
                _save_script_config(strategy, script_code_payload, script_language)
                _save_ai_config(strategy, request.POST)
                _save_position_rule(strategy, request.POST)

            return JsonResponse({"success": True, "id": strategy.id})
        except InvalidInputError as exc:
            return _json_error(exc.message, exc.status_code)
        except IntegrityError as exc:
            logger.warning("Strategy create failed due to integrity error: %s", exc)
            duplicate_error = DuplicateResourceError("同名策略版本或脚本配置已存在")
            return _json_error(duplicate_error.message, duplicate_error.status_code)
        except drf_serializers.ValidationError as exc:
            return _json_error(_format_validation_detail(exc.detail))
        except Exception:
            logger.exception("Unexpected error while creating strategy")
            return _json_error("创建策略失败，请稍后重试", status.HTTP_500_INTERNAL_SERVER_ERROR)

    return render(request, "strategy/create.html", _build_strategy_form_context(request))


@login_required
def strategy_detail(request: HttpRequest, strategy_id: int) -> HttpResponse:
    """策略详情页面"""
    strategy = _strategy_record(
        get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by=_account_profile(request),
        )
    )
    rules = strategy.rules.all().order_by("-priority", "-created_at")
    execution_logs = strategy.execution_logs.all()[:20]
    context = _build_strategy_form_context(request, strategy)
    context.update(
        {
            "rules": rules,
            "execution_logs": execution_logs,
        }
    )

    return render(request, "strategy/detail.html", context)


@login_required
def strategy_edit(request: HttpRequest, strategy_id: int) -> HttpResponse:
    """编辑策略页面"""
    strategy = _strategy_record(
        get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by=_account_profile(request),
        )
    )

    if request.method == "POST":
        try:
            strategy_serializer = _build_strategy_serializer(request, existing_strategy=strategy)
            rules_payload = _parse_rules_payload(
                request.POST.get("rules_data"),
                preserve_existing=True,
            )
            script_code_payload = _parse_script_payload(
                request.POST.get("script_code"),
                preserve_existing=True,
            )
            script_language = (request.POST.get("script_language") or "python").strip()

            with transaction.atomic():
                strategy = _strategy_record(strategy_serializer.save())
                _replace_rule_conditions(strategy, rules_payload)
                _save_script_config(strategy, script_code_payload, script_language)
                _save_ai_config(strategy, request.POST)
                _save_position_rule(strategy, request.POST)

            return JsonResponse({"success": True, "id": strategy.id})
        except InvalidInputError as exc:
            return _json_error(exc.message, exc.status_code)
        except IntegrityError as exc:
            logger.warning("Strategy edit failed due to integrity error: %s", exc)
            duplicate_error = DuplicateResourceError("策略保存失败，存在重复版本或脚本配置冲突")
            return _json_error(duplicate_error.message, duplicate_error.status_code)
        except drf_serializers.ValidationError as exc:
            return _json_error(_format_validation_detail(exc.detail))
        except Exception:
            logger.exception("Unexpected error while editing strategy %s", strategy_id)
            return _json_error("保存策略失败，请稍后重试", status.HTTP_500_INTERNAL_SERVER_ERROR)

    # GET 请求 - 渲染编辑页面
    return render(request, "strategy/edit.html", _build_strategy_form_context(request, strategy))


@login_required
def strategy_toggle_status(request: HttpRequest, strategy_id: int) -> HttpResponse:
    """切换策略状态"""
    if request.method != "POST":
        return JsonResponse({"success": False, "error": "只支持 POST 请求"})

    strategy = _strategy_record(
        get_object_or_404(
            StrategyModel,
            id=strategy_id,
            created_by=_account_profile(request),
        )
    )
    action = request.POST.get("action")

    if action == "activate":
        strategy.is_active = True
    elif action == "deactivate":
        strategy.is_active = False
    else:
        return JsonResponse({"success": False, "error": "无效的操作"})

    strategy.save()
    return JsonResponse({"success": True})


__all__ = [
    "strategy_create",
    "strategy_detail",
    "strategy_edit",
    "strategy_list",
    "strategy_toggle_status",
]
