"""MCP self-service application helpers split from account interface services."""

from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

from django.conf import settings

from apps.account.application.repository_provider import AccountInterfaceRepository


@dataclass(frozen=True)
class RegisteredUserOutcome:
    """Registration workflow result for template views."""

    user: Any
    approval_status: str
    display_name: str



_interface_repo = AccountInterfaceRepository

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
    user = _interface_repo().find_user_by_id(target_user_id)
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


