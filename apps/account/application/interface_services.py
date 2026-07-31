"""Application-facing orchestration helpers for account interface views."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from apps.account.application.rbac import ROLE_CHOICES
from apps.account.application.repository_provider import (
    AccountClassificationRepository,
    AccountInterfaceRepository,
    AccountRepository,
    AssetMetadataRepository,
    MacroSizingConfigRepository,
    PositionRepository,
)
from apps.account.application.use_cases import (
    CreatePositionFromBacktestInput,
    CreatePositionFromBacktestUseCase,
)
from apps.account.domain.services import (
    ExchangeRateFreshnessAssessment,
    assess_exchange_rate_freshness,
)


@dataclass(frozen=True)
class FlashOutcome:
    """User-facing outcome for template views."""

    level: str
    message: str
    redirect_to: str | None = None


@dataclass(frozen=True)
class TokenCreationOutcome:
    """Token creation result for template views."""

    level: str
    message: str
    payload: dict[str, str] | None = None
    username: str | None = None
    token_name: str | None = None


@dataclass(frozen=True)
class RegisteredUserOutcome:
    """Registration workflow result for template views."""

    user: Any
    approval_status: str
    display_name: str


@dataclass(frozen=True)
class LatestExchangeRateResult:
    """Latest stored FX record plus its current-decision freshness contract."""

    record: Any
    effective_date: date
    freshness_status: str
    staleness_days: int
    is_stale: bool
    must_not_use_for_decision: bool
    blocked_reason: str


class ExchangeRateDecisionBlockedError(ValueError):
    """Raised when an implicit-latest FX conversion is not decision-safe."""

    def __init__(self, assessment: ExchangeRateFreshnessAssessment) -> None:
        self.freshness_status = assessment.freshness_status
        self.staleness_days = assessment.staleness_days
        self.blocked_reason = assessment.blocked_reason
        if assessment.freshness_status == "future":
            message = "Latest exchange rate is future-dated and cannot be used"
        else:
            age = assessment.staleness_days
            message = f"Latest exchange rate is stale ({age} business days old)"
        super().__init__(message)


_interface_repo = AccountInterfaceRepository
_classification_repo = AccountClassificationRepository
_macro_sizing_repo = MacroSizingConfigRepository

TOKEN_ACCESS_LEVEL_READ_ONLY = "read_only"
TOKEN_ACCESS_LEVEL_READ_WRITE = "read_write"
TOKEN_ACCESS_LEVEL_CHOICES = (
    (TOKEN_ACCESS_LEVEL_READ_ONLY, "只读"),
    (TOKEN_ACCESS_LEVEL_READ_WRITE, "读写"),
)


def resolve_mcp_public_base_url(observed_base_url: str) -> str:
    """Return the canonical public origin used in MCP access artifacts.

    ``APP_BASE_URL`` is the production source of truth.  Falling back to the
    observed request origin keeps local development and tests convenient while
    preventing a request made through a bare VPS IP from poisoning copy-ready
    production endpoints.
    """

    configured_base_url = str(getattr(settings, "APP_BASE_URL", "") or "").strip()
    if not configured_base_url and not bool(getattr(settings, "DEBUG", False)):
        public_https_enabled = bool(getattr(settings, "PUBLIC_HTTPS_ENABLED", False))
        if public_https_enabled:
            for allowed_host in getattr(settings, "ALLOWED_HOSTS", []):
                host = str(allowed_host or "").strip().lstrip(".")
                if not host or host in {"*", "localhost", "web"}:
                    continue
                try:
                    ip_address(host)
                except ValueError:
                    if "." in host and ":" not in host:
                        configured_base_url = f"https://{host}"
                        break
    candidate = (configured_base_url or observed_base_url).strip().rstrip("/")
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("MCP public base URL must be an absolute HTTP(S) origin")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("MCP public base URL must not contain credentials, query, or fragment")
    if parsed.path not in {"", "/"}:
        raise ValueError("MCP public base URL must not contain a path")
    return candidate


def get_system_settings() -> Any:
    """Return the singleton system settings model."""

    return _interface_repo().get_system_settings()


def has_system_settings_singleton() -> bool:
    """Return whether the singleton settings row already exists."""

    return _interface_repo().has_system_settings_singleton()


def get_existing_system_settings() -> Any:
    """Return the existing singleton settings row without creating one."""

    return _interface_repo().get_existing_system_settings()


def get_active_access_token(key: str) -> Any:
    """Return one active access token when available."""

    return _interface_repo().get_active_access_token(key)


def list_investment_account_options(user_id: int) -> list[dict[str, Any]]:
    """Return selectable investment accounts for operator-facing forms."""

    options: list[dict[str, Any]] = []
    for account in AccountRepository().list_investment_accounts(user_id):
        account_id = account.get("id")
        if account_id in (None, ""):
            continue
        account_name = str(account.get("account_name") or f"账户 {account_id}").strip()
        account_type = str(account.get("account_type") or "").strip()
        label_parts = [account_name]
        if account_type:
            label_parts.append(account_type)
        label_parts.append(f"#{account_id}")
        options.append(
            {
                "value": account_id,
                "label": " · ".join(label_parts),
                "account_name": account_name,
            }
        )
    return options


def touch_access_token(token: Any) -> None:
    """Persist last-used metadata for one access token."""

    _interface_repo().touch_access_token(token)


def build_token_payload(
    *,
    username: str,
    token_name: str,
    token_value: str,
    access_level: str,
) -> dict[str, str] | None:
    """Build the session payload for newly created tokens when plaintext display is enabled."""

    settings_obj = get_system_settings()
    if not settings_obj.allow_token_plaintext_view:
        return None
    access_level_label = dict(TOKEN_ACCESS_LEVEL_CHOICES).get(access_level, access_level)
    return {
        "username": username,
        "token_name": token_name,
        "token": token_value,
        "access_level": access_level,
        "access_level_label": access_level_label,
        "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def normalize_token_access_level(raw_value: str | None) -> str:
    """Normalize one token access-level input into a supported value."""

    value = str(raw_value or "").strip().lower()
    if value == TOKEN_ACCESS_LEVEL_READ_ONLY:
        return TOKEN_ACCESS_LEVEL_READ_ONLY
    return TOKEN_ACCESS_LEVEL_READ_WRITE


def get_token_access_level_choices() -> tuple[tuple[str, str], ...]:
    """Expose token access-level choices for interface rendering."""

    return TOKEN_ACCESS_LEVEL_CHOICES


def provision_registered_user(
    *,
    user: Any,
    display_name: str,
    system_settings: Any,
    client_ip: str | None,
    approval_status: str,
    rbac_role: str,
) -> None:
    """Persist account scaffolding for a newly registered user."""

    _interface_repo().provision_registered_user(
        user=user,
        display_name=display_name,
        system_settings=system_settings,
        client_ip=client_ip,
        approval_status=approval_status,
        rbac_role=rbac_role,
    )


def username_exists(username: str) -> bool:
    """Return whether a username already exists."""

    return _interface_repo().username_exists(username)


def has_any_administrator(*, exclude_user_id: int | None = None) -> bool:
    """Return whether the system already has an admin/staff user."""

    return _interface_repo().has_any_administrator(exclude_user_id=exclude_user_id)


def register_user(
    *,
    username: str,
    email: str | None,
    password: str,
    display_name: str,
    client_ip: str | None,
) -> RegisteredUserOutcome:
    """Create a registered user and related account scaffolding."""

    result = _interface_repo().register_user_with_account_scaffolding(
        username=username,
        email=email,
        password=password,
        display_name=display_name,
        client_ip=client_ip,
    )
    return RegisteredUserOutcome(
        user=result["user"],
        approval_status=result["approval_status"],
        display_name=result["display_name"],
    )


def build_login_context() -> dict[str, Any]:
    """Build the login page context."""

    return {
        "has_admin": has_any_administrator(),
    }


def build_profile_context(user_id: int) -> dict[str, Any]:
    """Build the HTML profile page context."""

    return _interface_repo().build_profile_context(user_id)


def build_settings_context(user_id: int) -> dict[str, Any]:
    """Build the HTML settings page context."""

    return _interface_repo().build_settings_context(user_id)


def build_mcp_guide_context(user_id: int, *, base_url: str) -> dict[str, Any]:
    """Build the HTML MCP guide page context."""

    return _interface_repo().build_mcp_guide_context(user_id=user_id, base_url=base_url)


def build_self_mcp_api_payload(
    user_id: int,
    *,
    base_url: str,
    routing_available: bool = True,
    catalog_available: bool = True,
) -> dict[str, Any]:
    """Build a JSON-friendly MCP self-service payload for TUI/API consumers."""

    context = build_mcp_guide_context(user_id=user_id, base_url=base_url)
    profile = context["profile"]
    preferred_token = dict(context.get("preferred_token") or {})
    access_tokens = [dict(item) for item in context.get("visible_tokens", [])]
    normalized_base_url = str(context.get("base_url") or base_url).rstrip("/")
    route_endpoint = f"{normalized_base_url}/api/ai-capability/route/"
    web_endpoint = f"{normalized_base_url}/api/ai-capability/web/"
    capability_endpoint = f"{normalized_base_url}/api/ai-capability/capabilities/"
    prompt_payload = build_mcp_agent_prompt_payload(
        base_url=normalized_base_url,
        token_value=str(preferred_token.get("plaintext") or "").strip(),
        token_name=str(preferred_token.get("name") or "").strip(),
        access_level=str(preferred_token.get("access_level") or TOKEN_ACCESS_LEVEL_READ_ONLY),
        access_level_label=str(
            preferred_token.get("access_level_label")
            or dict(TOKEN_ACCESS_LEVEL_CHOICES).get(
                TOKEN_ACCESS_LEVEL_READ_ONLY,
                TOKEN_ACCESS_LEVEL_READ_ONLY,
            )
        ),
        default_account_id=context.get("default_account_id"),
    )
    recommended_token_id = preferred_token.get("id")
    token_history = [
        {
            "id": item.get("id"),
            "name": item.get("name") or "",
            "preview": item.get("preview") or "",
            "access_level": item.get("access_level") or "",
            "access_level_label": item.get("access_level_label") or "",
            "created_at": item.get("created_at"),
            "last_used_at": item.get("last_used_at"),
            "is_recommended": item.get("id") == recommended_token_id,
        }
        for item in access_tokens
    ]
    system_mcp_enabled = bool(context["system_settings"].default_mcp_enabled)
    user_mcp_enabled = bool(profile.mcp_enabled)
    if not system_mcp_enabled or not user_mcp_enabled:
        self_service_state = "disabled"
        self_service_blocking_reason = "mcp_disabled"
    elif not preferred_token:
        self_service_state = "no_token"
        self_service_blocking_reason = "no_token"
    elif not routing_available:
        self_service_state = "unavailable"
        self_service_blocking_reason = "routing_unavailable"
    elif not catalog_available:
        self_service_state = "unavailable"
        self_service_blocking_reason = "catalog_unavailable"
    elif not bool(context.get("token_plaintext_allowed")):
        self_service_state = "unavailable"
        self_service_blocking_reason = "token_plaintext_disabled"
    elif bool(context.get("token_decryption_failed")):
        self_service_state = "unavailable"
        self_service_blocking_reason = "token_decryption_failed"
    elif not str(preferred_token.get("plaintext") or "").strip():
        self_service_state = "unavailable"
        self_service_blocking_reason = "token_plaintext_unavailable"
    else:
        self_service_state = "ready"
        self_service_blocking_reason = ""

    parsed_base_url = urlparse(normalized_base_url)
    same_machine_only = parsed_base_url.hostname in {
        "127.0.0.1",
        "localhost",
        "::1",
        "testserver",
    }
    https_enabled = parsed_base_url.scheme == "https"
    if https_enabled:
        transport_security = "https"
        certificate_validation = "required"
        environment_statement = "当前为规范 HTTPS 地址；客户端必须校验域名与证书链。"
    elif same_machine_only:
        transport_security = "local_http"
        certificate_validation = "not_applicable"
        environment_statement = "当前地址仅能在同一台机器上使用；远程接入前必须配置 HTTPS 域名。"
    else:
        transport_security = "insecure_http"
        certificate_validation = "unavailable"
        environment_statement = (
            "当前为远程 HTTP 地址，不可用于 MCP 接入；请先配置可验证的 HTTPS 域名。"
        )

    if self_service_state == "ready" and not https_enabled and not same_machine_only:
        self_service_state = "unavailable"
        self_service_blocking_reason = "https_required"

    access_package = {
        "token": str(preferred_token.get("plaintext") or "").strip(),
        "token_preview": str(preferred_token.get("preview") or "").strip(),
        "route_endpoint": route_endpoint,
        "capability_catalog_endpoint": capability_endpoint,
        "agent_prompt": prompt_payload["agent_bootstrap_prompt"],
        "base_url": normalized_base_url,
        "same_machine_only": same_machine_only,
        "transport_security": transport_security,
        "certificate_validation": certificate_validation,
        "environment_statement": environment_statement,
    }
    return {
        "user_id": context["user"].id,
        "username": context["user"].username,
        "mcp_enabled": bool(profile.mcp_enabled),
        "rbac_role": str(getattr(profile, "rbac_role", "") or ""),
        "token_plaintext_allowed": bool(context.get("token_plaintext_allowed")),
        "active_token_count": len(access_tokens),
        "self_service_state": self_service_state,
        "self_service_blocking_reason": self_service_blocking_reason,
        "recommended_token_id": recommended_token_id,
        "account_count": int(context.get("account_count") or 0),
        "default_account_id": context.get("default_account_id"),
        "default_account_name": context.get("default_account_name") or "",
        "base_url": normalized_base_url,
        "api_root_endpoint": context.get("api_root_endpoint") or "",
        "route_endpoint": route_endpoint,
        "web_endpoint": web_endpoint,
        "capability_endpoint": capability_endpoint,
        "current_token_value": str(preferred_token.get("plaintext") or "").strip(),
        "current_token_display": str(
            preferred_token.get("display_token")
            or preferred_token.get("plaintext")
            or preferred_token.get("preview")
            or ""
        ).strip(),
        "preferred_token": preferred_token or None,
        "access_tokens": token_history,
        "access_package": access_package,
        **prompt_payload,
    }


def build_mcp_access_verification_payload(
    self_service: dict[str, Any],
    *,
    routing_available: bool,
    catalog_available: bool,
) -> dict[str, Any]:
    """Build a read-only MCP access verification result without exposing secrets."""

    token_ready = bool(
        self_service.get("recommended_token_id")
        and self_service.get("mcp_enabled")
        and self_service.get("self_service_state") != "disabled"
    )
    access_package = dict(self_service.get("access_package") or {})
    transport_security = str(access_package.get("transport_security") or "")
    transport_ready = transport_security in {"https", "local_http"}
    transport_detail = {
        "https": "正在使用规范 HTTPS 地址，客户端必须验证域名与证书链。",
        "local_http": "正在使用本机回环 HTTP，仅允许同机开发接入。",
    }.get(transport_security, "当前是远程 HTTP 地址，请先配置可验证的 HTTPS 域名。")
    checks = [
        {
            "key": "token",
            "label": "当前凭证",
            "status": "ready" if token_ready else "unavailable",
            "detail": "当前账号已有可用凭证。" if token_ready else "当前账号还没有可用凭证。",
        },
        {
            "key": "transport",
            "label": "HTTPS 与证书",
            "status": "ready" if transport_ready else "unavailable",
            "detail": transport_detail,
        },
        {
            "key": "routing",
            "label": "智能路由",
            "status": "ready" if routing_available else "unavailable",
            "detail": "路由服务已就绪。" if routing_available else "路由服务暂时不可用。",
        },
        {
            "key": "catalog",
            "label": "能力目录",
            "status": "ready" if catalog_available else "unavailable",
            "detail": "能力目录可读取。" if catalog_available else "能力目录暂时不可读取。",
        },
    ]
    return {
        "state": "ready" if all(item["status"] == "ready" for item in checks) else "unavailable",
        "checks": checks,
    }


def build_admin_mcp_users_payload(
    *,
    search_query: str = "",
    only_without_token: bool = False,
) -> dict[str, Any]:
    """Build one JSON-friendly MCP user-governance payload for admin APIs/TUI."""

    context = build_token_management_context(
        search_query=search_query,
        only_without_token=only_without_token,
    )
    rows = []
    for row in context["rows"]:
        user = row["user"]
        profile = row.get("profile")
        tokens = [
            {
                "id": token.id,
                "name": token.name,
                "preview": token.preview,
                "access_level": token.access_level,
                "access_level_label": token.get_access_level_display(),
                "created_at": token.created_at,
                "last_used_at": token.last_used_at,
            }
            for token in row.get("tokens", [])
        ]
        rows.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email or "",
                "approval_status": str(getattr(profile, "approval_status", "") or ""),
                "rbac_role": str(getattr(profile, "rbac_role", "") or ""),
                "mcp_enabled": bool(getattr(profile, "mcp_enabled", False)),
                "has_token": bool(row["has_token"]),
                "token_count": int(row["token_count"]),
                "read_only_token_count": int(row["read_only_token_count"]),
                "tokens": tokens,
            }
        )

    return {
        "search_query": context["search_query"],
        "only_without_token": bool(context["only_without_token"]),
        "total_users": int(context["total_users"]),
        "with_token_count": int(context["with_token_count"]),
        "without_token_count": int(context["without_token_count"]),
        "total_token_count": int(context["total_token_count"]),
        "rows": rows,
        "system_default_mcp_enabled": bool(context["system_settings"].default_mcp_enabled),
        "allow_token_plaintext_view": bool(context["system_settings"].allow_token_plaintext_view),
    }


def build_admin_mcp_user_detail_payload(target_user_id: int, *, base_url: str) -> dict[str, Any]:
    """Build one admin-facing MCP detail payload for a specific user."""

    detail = build_self_mcp_api_payload(target_user_id, base_url=base_url)
    user = find_user_by_id(target_user_id)
    if user is None:
        raise LookupError("用户不存在")
    detail["email"] = str(getattr(user, "email", "") or "")
    return detail


def build_mcp_agent_prompt_payload(
    *,
    base_url: str,
    token_value: str,
    token_name: str,
    access_level: str,
    access_level_label: str,
    default_account_id: Any | None,
) -> dict[str, Any]:
    """Build a copy-ready MCP bootstrap prompt for TUI/API consumers."""

    token_placeholder = token_value or "<请先生成一个新 Token>"
    account_hint = str(default_account_id) if default_account_id not in (None, "") else "可留空"
    normalized_base_url = base_url.rstrip("/")
    route_endpoint = f"{normalized_base_url}/api/ai-capability/route/"
    web_endpoint = f"{normalized_base_url}/api/ai-capability/web/"
    capability_endpoint = f"{normalized_base_url}/api/ai-capability/capabilities/"
    api_root_endpoint = f"{normalized_base_url}/api/"
    safety_line = (
        "- 当前 Token 为只读：只允许 GET/HEAD/OPTIONS，不要执行写入、删除、审批、交易或同步类动作。"
        if access_level == TOKEN_ACCESS_LEVEL_READ_ONLY
        else "- 当前 Token 为读写：仍受账号 RBAC、后端确认和风险控制约束，不要假设拥有管理员权限。"
    )
    prompt = "\n".join(
        [
            "请按以下信息接入 AgomTradePro：",
            f"- Base URL: {normalized_base_url}",
            f"- API Root: {api_root_endpoint}",
            f"- Route API: {route_endpoint}",
            f"- Web Chat API: {web_endpoint}",
            f"- Capability Catalog: {capability_endpoint}",
            f"- Authorization: Token {token_placeholder}",
            f"- Token name: {token_name or '未命名 Token'}",
            f"- Token access level: {access_level_label}",
            f"- Default account id: {account_hint}",
            "",
            "执行规则：",
            "- 优先调用 Route API，用自然语言请求让后端统一路由能力。",
            "- 需要兼容网页式对话时可调用 Web Chat API；需要排查能力覆盖时再读取 Capability Catalog。",
            safety_line,
            "- 不要先猜底层 MCP tool / terminal command 名称；先让后端完成能力选择。",
        ]
    )
    return {
        "agent_bootstrap_prompt": prompt,
        "agent_bootstrap_token_ready": bool(token_value),
        "agent_bootstrap_token_name": token_name,
        "agent_bootstrap_access_level": access_level,
        "agent_bootstrap_access_level_label": access_level_label,
    }


def get_active_portfolio_for_user(user_id: int) -> Any:
    """Return the user's active portfolio when available."""

    return _interface_repo().get_active_portfolio_for_user(user_id)


def update_account_settings(
    user_id: int,
    *,
    display_name: str,
    risk_tolerance: str,
    email: str,
    new_password: str,
) -> FlashOutcome:
    """Persist account settings edited from the template page."""

    password_updated = _interface_repo().update_account_settings(
        user_id,
        display_name=display_name,
        risk_tolerance=risk_tolerance,
        email=email,
        new_password=new_password,
    )
    if password_updated:
        return FlashOutcome(
            level="success",
            message="密码已修改，请重新登录",
            redirect_to="/account/login/",
        )
    return FlashOutcome(
        level="success",
        message="设置已保存",
        redirect_to="/account/settings/",
    )


def save_trading_cost_config(
    user_id: int,
    *,
    commission_rate: str,
    min_commission: str,
    stamp_duty_rate: str,
    transfer_fee_rate: str,
) -> FlashOutcome:
    """Persist trading cost settings for the user's active portfolio."""

    if not min_commission.strip():
        raise ValueError("最低佣金必须显式填写")

    context = build_settings_context(user_id)
    portfolio = context["portfolio"]
    if portfolio is None:
        return FlashOutcome(
            level="error",
            message="暂无可配置的投资组合",
            redirect_to="/account/settings/",
        )

    _interface_repo().save_trading_cost_config(
        portfolio_id=portfolio.id,
        commission_rate=float(commission_rate or 0.00025),
        min_commission=float(min_commission),
        stamp_duty_rate=float(stamp_duty_rate or 0.001),
        transfer_fee_rate=float(transfer_fee_rate or 0.00002),
    )
    return FlashOutcome(
        level="success",
        message="交易费率已保存",
        redirect_to="/account/settings/",
    )


def get_macro_sizing_config_payload() -> dict[str, Any]:
    """Return the active macro sizing config for API/SDK/MCP consumers."""

    return _macro_sizing_repo().get_active_config_payload()


def save_macro_sizing_config_payload(*, validated_data: Mapping[str, Any]) -> dict[str, Any]:
    """Persist one new active macro sizing config version."""

    return _macro_sizing_repo().save_active_config_payload(validated_data=validated_data)


def get_api_profile(user_id: int) -> Any:
    """Return the account profile model for API serialization."""

    return _interface_repo().get_api_profile(user_id)


def update_api_profile(
    user_id: int,
    *,
    profile_data: Mapping[str, Any],
    email: str | None = None,
) -> Any:
    """Persist API profile updates and return the refreshed profile model."""

    return _interface_repo().update_api_profile(
        user_id,
        profile_data=profile_data,
        email=email,
    )


def change_api_password(
    user_id: int,
    *,
    current_password: str,
    new_password: str,
) -> None:
    """Change the current user's password after explicit re-authentication."""

    _interface_repo().change_api_password(
        user_id,
        current_password=current_password,
        new_password=new_password,
    )


def get_asset_category_queryset() -> Any:
    """Return active asset categories for API listing/retrieval."""

    return _classification_repo().list_active_asset_categories()


def get_asset_category_roots() -> Any:
    """Return active root-level asset categories."""

    return _classification_repo().list_root_asset_categories()


def get_asset_category_tree_roots() -> Any:
    """Return active tree root categories."""

    return _classification_repo().list_tree_root_asset_categories()


def get_asset_category_children(*, category_id: int) -> Any:
    """Return active child categories for one category."""

    return _classification_repo().list_child_asset_categories(category_id)


def create_asset_category(*, validated_data: Mapping[str, Any]) -> Any:
    """Create one asset category from serializer-validated data."""

    return _classification_repo().create_asset_category(**dict(validated_data))


def update_asset_category(*, category_id: int, validated_data: Mapping[str, Any]) -> Any:
    """Update one asset category from serializer-validated data."""

    return _classification_repo().update_asset_category(
        category_id=category_id,
        **dict(validated_data),
    )


def delete_asset_category(*, category_id: int) -> None:
    """Delete one asset category."""

    _classification_repo().delete_asset_category(category_id=category_id)


def get_currency_queryset() -> Any:
    """Return active currencies for API listing/retrieval."""

    return _classification_repo().list_active_currencies()


def get_base_currency() -> Any:
    """Return the configured base currency model."""

    return _classification_repo().get_base_currency()


def get_exchange_rate_queryset() -> Any:
    """Return exchange rates for API listing/retrieval."""

    return _classification_repo().list_exchange_rates()


def create_exchange_rate(*, validated_data: Mapping[str, Any]) -> Any:
    """Create one exchange rate from serializer-validated data."""

    return _classification_repo().create_exchange_rate(**dict(validated_data))


def update_exchange_rate(*, exchange_rate_id: int, validated_data: Mapping[str, Any]) -> Any:
    """Update one exchange rate from serializer-validated data."""

    return _classification_repo().update_exchange_rate(
        exchange_rate_id=exchange_rate_id,
        **dict(validated_data),
    )


def delete_exchange_rate(*, exchange_rate_id: int) -> None:
    """Delete one exchange rate."""

    _classification_repo().delete_exchange_rate(exchange_rate_id=exchange_rate_id)


def get_latest_exchange_rate(
    *,
    from_code: str,
    to_code: str,
    as_of_date: date | None = None,
) -> LatestExchangeRateResult | None:
    """Return the latest FX record with current-decision freshness metadata."""

    record = _classification_repo().get_latest_exchange_rate(
        from_code=from_code,
        to_code=to_code,
    )
    if record is None:
        return None
    return _build_latest_exchange_rate_result(
        record,
        as_of_date=as_of_date or timezone.localdate(),
    )


def convert_currency_amount(
    *,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    date_value: date | None = None,
) -> dict[str, Any]:
    """Convert one amount, blocking unsafe implicit-latest FX observations."""

    repository = _classification_repo()
    return _convert_currency_amount_with_repository(
        repository=repository,
        amount=amount,
        from_currency=from_currency,
        to_currency=to_currency,
        date_value=date_value,
        as_of_date=timezone.localdate(),
    )


def _convert_currency_amount_with_repository(
    *,
    repository: Any,
    amount: Decimal,
    from_currency: str,
    to_currency: str,
    date_value: date | None,
    as_of_date: date,
) -> dict[str, Any]:
    """Convert with one repository while enforcing implicit-latest safety."""

    requested_codes = {from_currency, to_currency}
    if not repository.active_currency_codes_exist(requested_codes):
        raise ValueError("Currency must be active and registered")
    if from_currency == to_currency:
        return {
            "converted_amount": amount,
            "rate_used": Decimal("1"),
            "rate_date": date_value,
        }

    rate_model = repository.get_exchange_rate_for_conversion(
        from_code=from_currency,
        to_code=to_currency,
        date_value=date_value,
    )
    if rate_model is None:
        raise ValueError(f"No exchange rate found for {from_currency} -> {to_currency}")

    if date_value is None:
        latest = _build_latest_exchange_rate_result(
            rate_model,
            as_of_date=as_of_date,
        )
        if latest.must_not_use_for_decision:
            raise ExchangeRateDecisionBlockedError(
                ExchangeRateFreshnessAssessment(
                    freshness_status=latest.freshness_status,
                    staleness_days=latest.staleness_days,
                    is_stale=latest.is_stale,
                    must_not_use_for_decision=latest.must_not_use_for_decision,
                    blocked_reason=latest.blocked_reason,
                )
            )

    return {
        "converted_amount": rate_model.convert(amount),
        "rate_used": rate_model.rate,
        "rate_date": rate_model.effective_date,
    }


def _build_latest_exchange_rate_result(
    record: Any,
    *,
    as_of_date: date,
) -> LatestExchangeRateResult:
    """Build application output without laundering the source effective date."""

    effective_date = getattr(record, "effective_date", None)
    if type(effective_date) is not date:
        raise ValueError("Exchange rate effective_date must be a date")
    assessment = assess_exchange_rate_freshness(
        effective_date,
        as_of_date=as_of_date,
    )
    return LatestExchangeRateResult(
        record=record,
        effective_date=effective_date,
        freshness_status=assessment.freshness_status,
        staleness_days=assessment.staleness_days,
        is_stale=assessment.is_stale,
        must_not_use_for_decision=assessment.must_not_use_for_decision,
        blocked_reason=assessment.blocked_reason,
    )


def get_portfolio_allocation_payload(
    *,
    portfolio_id: int,
    user_id: int,
    dimension: str,
) -> dict[str, Any] | None:
    """Return category/currency allocation payload for one owned portfolio."""

    repository = _classification_repo()
    portfolio = repository.get_portfolio_for_user(portfolio_id=portfolio_id, user_id=user_id)
    if portfolio is None:
        return None

    rows = repository.list_portfolio_allocation_rows(portfolio_id=portfolio.id)
    if dimension == "currency":
        base_currency = portfolio.base_currency or repository.get_base_currency()
        base_currency_code = getattr(base_currency, "code", "CNY")
        currency_totals: dict[str, dict[str, Any]] = {}
        total_value_base = Decimal("0")

        for row in rows:
            currency_code = row["currency_code"]
            amount = row["amount"]
            bucket = currency_totals.setdefault(
                currency_code,
                {
                    "currency_code": currency_code,
                    "currency_name": row["currency_name"],
                    "amount": Decimal("0"),
                    "amount_base": Decimal("0"),
                },
            )
            bucket["amount"] += amount
            conversion = _convert_currency_amount_with_repository(
                repository=repository,
                amount=amount,
                from_currency=currency_code,
                to_currency=base_currency_code,
                date_value=None,
                as_of_date=timezone.localdate(),
            )
            amount_base = conversion["converted_amount"]
            bucket["amount_base"] += amount_base
            total_value_base += amount_base

        data = [
            {
                **item,
                "percentage": (
                    float(item["amount_base"] / total_value_base * 100)
                    if total_value_base > 0
                    else 0
                ),
            }
            for item in currency_totals.values()
        ]
        return {
            "dimension": "currency",
            "base_currency": base_currency_code,
            "total_value_base": total_value_base,
            "data": data,
        }

    category_totals: dict[str, Decimal] = {}
    total_value = Decimal("0")
    for row in rows:
        category_path = row["category_path"]
        amount = row["amount"]
        category_totals[category_path] = category_totals.get(category_path, Decimal("0")) + amount
        total_value += amount

    data = [
        {
            "category_path": category_path,
            "amount": amount,
            "percentage": float(amount / total_value * 100) if total_value > 0 else 0,
        }
        for category_path, amount in category_totals.items()
    ]
    return {
        "dimension": "category",
        "total_value": total_value,
        "data": data,
    }


def create_self_token(
    user_id: int,
    *,
    token_name: str,
    access_level: str,
) -> TokenCreationOutcome:
    """Create a token for the current user."""

    settings_context = _interface_repo().build_settings_context(user_id)
    profile = settings_context["profile"]
    if not profile.mcp_enabled:
        raise PermissionError("管理员已关闭您的 MCP/SDK 权限，暂时不能创建 Token")

    token, raw_key = _interface_repo().create_access_token(
        target_user_id=user_id,
        created_by_user_id=user_id,
        token_name=token_name,
        access_level=normalize_token_access_level(access_level),
    )
    payload = build_token_payload(
        username=token.user.username,
        token_name=token.name,
        token_value=raw_key,
        access_level=token.access_level,
    )
    if payload:
        message = f"已创建 Token：{token.name}"
    else:
        message = f"已创建 Token：{token.name}。当前系统禁止查看明文，请自行妥善管理。"
    return TokenCreationOutcome(
        level="success",
        message=message,
        payload=payload,
        username=token.user.username,
        token_name=token.name,
    )


def revoke_self_token(user_id: int, token_id: int) -> FlashOutcome:
    """Revoke one token owned by the current user."""

    try:
        token_name = _interface_repo().revoke_access_token_for_user(
            target_user_id=user_id,
            token_id=token_id,
        )
    except Exception as exc:
        if "DoesNotExist" in exc.__class__.__name__:
            raise LookupError("Token 不存在或已失效") from exc
        raise
    return FlashOutcome(level="success", message=f"已撤销 Token：{token_name}")


def create_capital_flow(
    user_id: int,
    *,
    flow_type: str,
    amount: Decimal,
    flow_date: Any,
    notes: str,
) -> FlashOutcome:
    """Create a capital flow entry for the current user."""

    _interface_repo().create_capital_flow(
        user_id=user_id,
        flow_type=flow_type,
        amount=amount,
        flow_date=flow_date,
        notes=notes,
    )
    action_text = "入金" if flow_type == "deposit" else "出金"
    return FlashOutcome(level="success", message=f"{action_text}记录已添加：¥{amount:.2f}")


def apply_backtest_results(
    user_id: int,
    *,
    backtest_id: int,
    scale_factor: float,
) -> dict[str, Any]:
    """Apply backtest positions into the user's account."""

    use_case = CreatePositionFromBacktestUseCase(
        position_repo=PositionRepository(),
        account_repo=AccountRepository(),
        asset_meta_repo=AssetMetadataRepository(),
    )
    input_dto = CreatePositionFromBacktestInput(
        user_id=user_id,
        backtest_id=backtest_id,
        scale_factor=scale_factor,
    )
    result = use_case.execute(input_dto)
    return {
        "total_positions": result.total_positions,
        "total_value": result.total_value,
        "backtest_name": result.backtest_name,
    }


def build_user_management_context(status_filter: str, search_query: str) -> dict[str, Any]:
    """Build the admin user management page context."""

    context = _interface_repo().build_user_management_context(
        status_filter=status_filter,
        search_query=search_query,
    )
    context["role_choices"] = ROLE_CHOICES
    return context


def build_token_management_context(search_query: str, only_without_token: bool) -> dict[str, Any]:
    """Build the admin token management page context."""

    return _interface_repo().build_token_management_context(
        search_query=search_query,
        only_without_token=only_without_token,
    )


def rotate_user_token(
    *,
    actor_user_id: int,
    target_user_id: int,
    token_name: str,
    access_level: str,
) -> TokenCreationOutcome:
    """Create a token for another user as an administrator."""

    profile = _interface_repo().build_profile_context(target_user_id)["profile"]
    if not profile.mcp_enabled:
        raise PermissionError(f"用户 {profile.user.username} 的 MCP/SDK 权限已关闭，请先开启")

    token, raw_key = _interface_repo().create_access_token(
        target_user_id=target_user_id,
        created_by_user_id=actor_user_id,
        token_name=token_name,
        access_level=normalize_token_access_level(access_level),
    )
    payload = build_token_payload(
        username=token.user.username,
        token_name=token.name,
        token_value=raw_key,
        access_level=token.access_level,
    )
    if payload:
        message = f"已为用户 {token.user.username} 创建 Token：{token.name}"
    else:
        message = f"已为用户 {token.user.username} 创建 Token：{token.name}。当前系统禁止查看明文。"
    return TokenCreationOutcome(
        level="success",
        message=message,
        payload=payload,
        username=token.user.username,
        token_name=token.name,
    )


def revoke_user_tokens(target_user_id: int) -> dict[str, Any]:
    """Revoke all active tokens for a user."""

    result = _interface_repo().revoke_all_access_tokens_for_user(target_user_id=target_user_id)
    if result["deleted_count"] > 0:
        return {
            "level": "success",
            "message": f"已撤销用户 {result['username']} 的全部 Token",
            **result,
        }
    return {
        "level": "warning",
        "message": f"用户 {result['username']} 当前没有可撤销的 Token",
        **result,
    }


def revoke_access_token(token_id: int) -> FlashOutcome:
    """Revoke one token by id."""

    try:
        result = _interface_repo().revoke_access_token_by_id(token_id)
    except Exception as exc:
        if "DoesNotExist" in exc.__class__.__name__:
            raise LookupError("Token 不存在或已失效") from exc
        raise
    return FlashOutcome(
        level="success",
        message=f"已撤销 {result['username']} 的 Token：{result['token_name']}",
    )


def toggle_user_mcp(target_user_id: int) -> FlashOutcome:
    """Toggle a user's MCP permission."""

    result = _interface_repo().toggle_user_mcp(target_user_id)
    state = "开启" if result["mcp_enabled"] else "关闭"
    default_state = "开启" if result["default_mcp_enabled"] else "关闭"
    return FlashOutcome(
        level="success",
        message=f"已{state}用户 {result['username']} 的 MCP/SDK 权限（系统默认：{default_state}）",
    )


def approve_user(*, actor_user_id: int, target_user_id: int) -> FlashOutcome:
    """Approve a user and return the UI message."""

    result = _interface_repo().approve_user(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def reject_user(*, actor_user_id: int, target_user_id: int, rejection_reason: str) -> FlashOutcome:
    """Reject a user and return the UI message."""

    result = _interface_repo().reject_user(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        rejection_reason=rejection_reason,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def set_user_role(*, target_user_id: int, raw_role: str) -> FlashOutcome:
    """Update a user's role after interface validation."""

    valid_values = {value for value, _ in ROLE_CHOICES}
    if raw_role not in valid_values:
        return FlashOutcome(level="error", message="无效的角色")
    result = _interface_repo().set_user_role(target_user_id=target_user_id, rbac_role=raw_role)
    return FlashOutcome(level=result["level"], message=result["message"])


def reset_user_status(*, actor_user_id: int, target_user_id: int) -> FlashOutcome:
    """Reset a user's approval status."""

    result = _interface_repo().reset_user_status(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
    )
    return FlashOutcome(level=result["level"], message=result["message"])


def build_system_settings_context() -> dict[str, Any]:
    """Build the admin system settings context."""

    return _interface_repo().build_system_settings_context()


def update_system_settings(data: Mapping[str, Any]) -> FlashOutcome:
    """Persist system settings from a form mapping."""

    _interface_repo().update_system_settings_from_mapping(data)
    return FlashOutcome(
        level="success",
        message="系统配置已更新",
        redirect_to="/account/admin/settings/",
    )


def build_collaboration_context(user_id: int) -> dict[str, Any]:
    """Build the collaboration page context."""

    return {
        "grant_count": _interface_repo().count_owned_active_observer_grants(user_id),
        "max_grants": 10,
    }


def build_observer_portal_context(user_id: int) -> dict[str, Any]:
    """Build the observer portal page context."""

    return {
        "observable_count": _interface_repo().count_observable_active_grants(user_id),
    }


def find_user_by_username(username: str) -> Any:
    """Return one user by username when available."""

    return _interface_repo().find_user_by_username(username)


def find_user_by_id(user_id: int) -> Any:
    """Return one user by id when available."""

    return _interface_repo().find_user_by_id(user_id)


def get_unified_account_id_for_portfolio(portfolio_id: int) -> int | None:
    """Return the unified account id mapped from one account portfolio id."""

    return _interface_repo().get_unified_account_id_for_portfolio(portfolio_id)


def get_active_observer_grant(*, owner_user_id: int, observer_user_id: int) -> Any:
    """Return one active observer grant for the owner/observer pair."""

    return _interface_repo().get_active_observer_grant(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
    )


def count_owned_active_observer_grants(user_id: int) -> int:
    """Count active observer grants granted by the user."""

    return _interface_repo().count_owned_active_observer_grants(user_id)


def create_observer_grant_record(
    *,
    owner_user_id: int,
    observer_user_id: int,
    created_by_user_id: int,
    expires_at: Any,
) -> Any:
    """Create one observer grant record."""

    return _interface_repo().create_observer_grant(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
        created_by_user_id=created_by_user_id,
        expires_at=expires_at,
    )


def has_active_observer_access(*, owner_user_id: int, observer_user_id: int) -> bool:
    """Return whether an observer currently has a valid portfolio-read grant."""

    return _interface_repo().has_active_observer_access(
        owner_user_id=owner_user_id,
        observer_user_id=observer_user_id,
    )


def get_accessible_portfolios_queryset(user_id: int) -> Any:
    """Return the portfolio queryset accessible to the given user."""

    return _interface_repo().get_accessible_portfolios_queryset(user_id)


def get_asset_metadata_queryset() -> Any:
    """Return the asset metadata queryset for API listing/retrieval."""

    return _interface_repo().get_asset_metadata_queryset()


def get_user_transaction_queryset(user_id: int) -> Any:
    """Return transactions scoped to portfolios owned by the user."""

    return _interface_repo().get_user_transaction_queryset(user_id)


def get_user_capital_flow_queryset(user_id: int) -> Any:
    """Return capital flows scoped to portfolios owned by the user."""

    return _interface_repo().get_user_capital_flow_queryset(user_id)


def get_user_portfolio(*, user_id: int, portfolio_id: int) -> Any:
    """Return one owned portfolio when available."""

    return _interface_repo().get_user_portfolio(
        user_id=user_id,
        portfolio_id=portfolio_id,
    )


def get_account_health_payload(user_id: int) -> dict[str, Any]:
    """Return the account API health summary for one user."""

    return _interface_repo().get_account_health_payload(user_id)


def search_observer_candidates(*, owner_user_id: int, query: str) -> list[dict[str, Any]]:
    """Search active users for collaboration grants."""

    return _interface_repo().search_observer_candidates(
        owner_user_id=owner_user_id,
        query=query,
    )


def get_trading_cost_config_queryset(user_id: int) -> Any:
    """Return trading cost configs for portfolios owned by the user."""

    return _interface_repo().get_trading_cost_config_queryset(user_id)


def save_api_trading_cost_config(
    *,
    actor_user_id: int,
    portfolio_id: int,
    validated_data: Mapping[str, Any],
) -> Any:
    """Create or update one trading cost config from validated API data."""

    return _interface_repo().save_api_trading_cost_config(
        actor_user_id=actor_user_id,
        portfolio_id=portfolio_id,
        commission_rate=float(validated_data["commission_rate"]),
        min_commission=float(validated_data["min_commission"]),
        stamp_duty_rate=float(validated_data["stamp_duty_rate"]),
        transfer_fee_rate=float(validated_data["transfer_fee_rate"]),
        is_active=bool(validated_data.get("is_active", True)),
    )


def list_observer_grants_queryset(
    *,
    user_id: int,
    as_observer: bool,
    status_filter: str | None = None,
) -> Any:
    """Return observer grants scoped to the current owner or observer view."""

    return _interface_repo().list_observer_grants_queryset(
        user_id=user_id,
        as_observer=as_observer,
        status_filter=status_filter,
    )


def get_observer_grant_by_id(grant_id: Any) -> Any:
    """Return one observer grant with related users when available."""

    return _interface_repo().get_observer_grant_by_id(grant_id)


def build_observer_positions_payload(owner_user_id: int) -> dict[str, Any]:
    """Return the active portfolio positions payload for observer access."""

    return _interface_repo().build_observer_positions_payload(owner_user_id)


def update_observer_grant(*, grant_id: Any, expires_at: Any) -> Any:
    """Persist a grant expiry update and return the refreshed model."""

    return _interface_repo().update_observer_grant(
        grant_id=grant_id,
        expires_at=expires_at,
    )


def revoke_observer_grant(*, grant_id: Any, revoked_by_user_id: int) -> Any:
    """Revoke one observer grant and return the refreshed model."""

    return _interface_repo().revoke_observer_grant(
        grant_id=grant_id,
        revoked_by_user_id=revoked_by_user_id,
    )


def build_backup_download_payload(token: str) -> dict[str, Any]:
    """Validate a backup token and return the generated archive payload."""

    return _interface_repo().build_backup_download_payload(token)
