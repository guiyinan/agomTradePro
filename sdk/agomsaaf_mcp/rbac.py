"""RBAC for AgomSAAF MCP server."""

from __future__ import annotations

import os
from typing import Callable


def _split_csv_env(name: str) -> set[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _rbac_enabled() -> bool:
    return os.getenv("AGOMSAAF_MCP_ENFORCE_RBAC", "false").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_role(raw: str | None) -> str:
    aliases = {
        "管理员": "admin",
        "admin": "admin",
        "owner": "owner",
        "所有者": "owner",
        "analyst": "analyst",
        "分析师": "analyst",
        "investment_manager": "investment_manager",
        "投资经理": "investment_manager",
        "trader": "trader",
        "交易员": "trader",
        "risk": "risk",
        "risk_manager": "risk",
        "风控": "risk",
        "readonly": "read_only",
        "read_only": "read_only",
        "viewer": "read_only",
        "只读用户": "read_only",
    }
    if not raw:
        return "read_only"
    value = raw.strip().lower()
    return aliases.get(value, value)


_BACKEND_ROLE_CACHE: str | None = None


def _get_role_from_backend() -> str | None:
    global _BACKEND_ROLE_CACHE
    if _BACKEND_ROLE_CACHE:
        return _BACKEND_ROLE_CACHE

    try:
        from agomsaaf import AgomSAAFClient

        client = AgomSAAFClient()
        payload = client.get("account/api/profile/")
        role = _normalize_role(payload.get("rbac_role") if isinstance(payload, dict) else None)
        _BACKEND_ROLE_CACHE = role
        return role
    except Exception:
        return None


def _role() -> str:
    # Explicit env role has highest priority (useful for emergency override).
    env_role = os.getenv("AGOMSAAF_MCP_ROLE")
    if env_role and env_role.strip():
        return _normalize_role(env_role)

    source = os.getenv("AGOMSAAF_MCP_ROLE_SOURCE", "backend").strip().lower()
    if source in {"backend", "api", "profile"}:
        backend_role = _get_role_from_backend()
        if backend_role:
            return backend_role

    return _normalize_role(os.getenv("AGOMSAAF_MCP_DEFAULT_ROLE", "read_only"))


def _classify_tool_level(tool_name: str) -> str:
    name = tool_name.lower()

    admin_keywords = {
        "user",
        "token",
        "settings",
        "revoke",
        "rotate",
        "system",
    }
    if any(k in name for k in admin_keywords):
        return "admin"

    admin_prefixes = ("set_", "init_", "train_", "activate_", "rollback_")
    if name.startswith(admin_prefixes):
        return "admin"

    # 决策执行工具需要特殊权限（仅 admin/owner/investment_manager）
    execute_only_tools = {"decision_execute_request"}
    if name in execute_only_tools:
        return "execute_only"

    write_prefixes = (
        "create_",
        "update_",
        "delete_",
        "import_",
        "approve_",
        "reject_",
        "invalidate_",
        "execute_",
        "close_",
        "reset_",
        "bind_",
        "unbind_",
        "toggle_",
        "publish_",
        "submit_",
        "replay_",
    )
    if name.startswith(write_prefixes):
        return "write"

    return "read"


def _classify_tool_domain(tool_name: str) -> str:
    name = tool_name.lower()

    system_keywords = {
        "user",
        "token",
        "settings",
        "system",
        "init_",
        "train_",
        "activate_",
        "rollback_",
    }
    if any(k in name for k in system_keywords):
        return "system"

    trading_keywords = {
        "portfolio",
        "position",
        "account",
        "simulated",
        "trade",
        "transaction",
        "capital_flow",
        "rebalance",
    }
    if any(k in name for k in trading_keywords):
        return "trading"

    risk_keywords = {
        "risk",
        "stop_loss",
        "volatility",
        "hedge",
        "policy",
        "invalidate",
        "eligibility",
        "regime",
    }
    if any(k in name for k in risk_keywords):
        return "risk"

    strategy_keywords = {"strategy", "signal", "backtest", "alpha", "rotation", "factor", "sector"}
    if any(k in name for k in strategy_keywords):
        return "strategy"

    return "general"


def _role_allows(level: str, role: str) -> bool:
    # backward-compatible fallback (unused by new matrix path)
    if role in {"admin", "owner", "investment_manager", "trader", "risk"}:
        return True if level in {"read", "write", "admin"} else False
    return level == "read"


def _role_allows_by_matrix(role: str, level: str, domain: str) -> bool:
    """
    Role matrix:
    - admin: all
    - owner: all except system/admin
    - analyst: read-only (cannot execute decision requests)
    - investment_manager: read + write on trading/strategy/risk/general, can execute decisions
    - trader: read + write on trading, read others, no system/admin
    - risk: read all + write only on risk domain, no system/admin
    - read_only: read-only
    """
    if role == "admin":
        return True

    if level == "admin" or domain == "system":
        return False

    # 决策执行权限：仅 admin、owner、investment_manager 可执行
    if level == "execute_only":
        return role in {"owner", "investment_manager"}

    if role == "owner":
        return level in {"read", "write", "execute_only"}

    if role == "analyst":
        return level == "read"

    if role == "investment_manager":
        if level == "read":
            return True
        return domain in {"trading", "strategy", "risk", "general"}

    if role == "trader":
        if level == "read":
            return True
        return domain == "trading"

    if role == "risk":
        if level == "read":
            return True
        return domain == "risk"

    if role == "read_only":
        return level == "read"

    return False


def enforce_tool_access(tool_name: str) -> None:
    if not _rbac_enabled():
        return

    allowed = _split_csv_env("AGOMSAAF_MCP_ALLOWED_TOOLS")
    denied = _split_csv_env("AGOMSAAF_MCP_DENIED_TOOLS")
    if tool_name in denied:
        raise PermissionError(f"RBAC deny: tool '{tool_name}' is explicitly denied")
    if allowed and tool_name not in allowed:
        raise PermissionError(f"RBAC deny: tool '{tool_name}' not in allowed list")

    role = _role()
    level = _classify_tool_level(tool_name)
    domain = _classify_tool_domain(tool_name)
    if not _role_allows_by_matrix(role, level, domain):
        raise PermissionError(
            f"RBAC deny: role '{role}' cannot execute '{tool_name}' (level={level}, domain={domain})"
        )


def enforce_resource_access(resource_uri: str) -> None:
    if not _rbac_enabled():
        return

    allowed = _split_csv_env("AGOMSAAF_MCP_ALLOWED_RESOURCES")
    denied = _split_csv_env("AGOMSAAF_MCP_DENIED_RESOURCES")
    if resource_uri in denied:
        raise PermissionError(f"RBAC deny: resource '{resource_uri}' is explicitly denied")
    if allowed and resource_uri not in allowed:
        raise PermissionError(f"RBAC deny: resource '{resource_uri}' not in allowed list")

    role = _role()
    if role == "admin":
        return
    # account resources include sensitive portfolio details
    if resource_uri.startswith("agomsaaf://account/") and role not in {"owner", "investment_manager", "trader", "risk"}:
        raise PermissionError(f"RBAC deny: role '{role}' cannot access account resource '{resource_uri}'")


def enforce_prompt_access(prompt_name: str) -> None:
    if not _rbac_enabled():
        return

    allowed = _split_csv_env("AGOMSAAF_MCP_ALLOWED_PROMPTS")
    denied = _split_csv_env("AGOMSAAF_MCP_DENIED_PROMPTS")
    if prompt_name in denied:
        raise PermissionError(f"RBAC deny: prompt '{prompt_name}' is explicitly denied")
    if allowed and prompt_name not in allowed:
        raise PermissionError(f"RBAC deny: prompt '{prompt_name}' not in allowed list")

    role = _role()
    if role == "read_only" and prompt_name == "check_signal_eligibility":
        # prompt implies action suggestion flow; keep read-only stricter by default
        raise PermissionError(f"RBAC deny: role '{role}' cannot use prompt '{prompt_name}'")


def wrap_tool_with_rbac(name: str, fn: Callable) -> Callable:
    def _wrapped(*args, **kwargs):
        enforce_tool_access(name)
        return fn(*args, **kwargs)

    return _wrapped


def wrap_tool_with_rbac_and_audit(name: str, fn: Callable) -> Callable:
    """
    Wrap a tool with RBAC enforcement and audit logging.

    This wrapper:
    1. Creates audit context before execution
    2. Enforces RBAC checks
    3. Executes the tool
    4. Logs the result to the audit backend
    5. Returns the original result (audit failures don't block)

    Args:
        name: Tool name
        fn: Original tool function

    Returns:
        Wrapped function with RBAC and audit logging
    """
    def _wrapped(*args, **kwargs):
        import time
        from .audit import get_audit_logger, AuditContext

        # 创建审计上下文
        context = AuditContext.create(
            user_id=_get_user_id(),
            username=_get_username(),
            mcp_role=_role(),
        )

        audit_logger = get_audit_logger()
        error = None
        result = None

        try:
            # 执行 RBAC 检查
            enforce_tool_access(name)

            # 执行原始工具
            result = fn(*args, **kwargs)
            return result

        except PermissionError as e:
            error = e
            raise
        except Exception as e:
            error = e
            raise
        finally:
            # 异步记录审计日志（不阻塞主流程）
            try:
                audit_logger.log_mcp_call(
                    tool_name=name,
                    params={
                        "args": list(args),
                        "kwargs": kwargs,
                    },
                    result=result,
                    error=error,
                    context=context,
                )
            except Exception as audit_error:
                # 审计失败不阻塞主流程
                import logging
                logging.warning(f"审计日志记录失败: {audit_error}")

    return _wrapped


def _get_user_id() -> int | None:
    """获取当前用户 ID（从后端 API 获取）"""
    try:
        from agomsaaf import AgomSAAFClient
        client = AgomSAAFClient()
        payload = client.get("account/api/profile/")
        if isinstance(payload, dict):
            return payload.get("id")
    except Exception:
        pass
    return None


def _get_username() -> str:
    """获取当前用户名（从后端 API 获取）"""
    try:
        from agomsaaf import AgomSAAFClient
        client = AgomSAAFClient()
        payload = client.get("account/api/profile/")
        if isinstance(payload, dict):
            return payload.get("username", "anonymous")
    except Exception:
        pass
    return "anonymous"
