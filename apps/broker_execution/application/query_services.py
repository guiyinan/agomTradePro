"""Strict persisted-only broker execution queries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from apps.broker_execution.domain.entities import LiveOrderStatus

from .audit_projection import project_broker_audit_event
from .authorization import action_permissions, require_action
from .connection_status import project_connection_status
from .order_catalog import project_broker_order_catalog_item
from .order_detail_evidence import project_broker_order_detail
from .overview_status import OverviewRawFacts, project_broker_overview
from .ports import BrokerExecutionRepositoryProtocol
from .reconciliation_projection import project_broker_reconciliation
from .repository_provider import get_broker_execution_repository
from .use_case_errors import (
    BrokerExecutionNotFoundError,
    BrokerExecutionValidationError,
)

_MAX_QUERY_LIMIT = 500


def _server_address(value: str) -> str:
    """Return a safe public server address for the Windows setup template."""

    normalized = str(value or "").strip().rstrip("/")
    if not normalized or len(normalized) > 2048:
        raise BrokerExecutionValidationError("server_address is invalid")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise BrokerExecutionValidationError("server_address is invalid")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _windows_install_command(server_address: str) -> str:
    """Build the copyable Windows Agent installation command template."""

    return "\n".join(
        [
            "powershell -NoProfile -ExecutionPolicy Bypass -File .\\Install.ps1 `",
            '  -PythonExe "C:\\Python311\\python.exe" `',
            '  -QmtRoot "D:\\qmt" `',
            f'  -ServerUrl "{server_address}" `',
            "  -SystemAccountId <系统账户 ID> `",
            '  -AgentId "qmt-home-01" `',
            "  -RegisterTask `",
            "  -RunReadProbe",
        ]
    )


def _setup_guide() -> str:
    """Return the user-facing QMT setup sequence used by every TUI client."""

    return "\n".join(
        [
            "一、准备执行端：使用 64 位 Windows、Python 3.11，并确认券商已开通外部 XtQuant 查询、委托和撤单权限。",
            "二、绑定账户：先预览再确认“Agent 与账户绑定”；系统账户 ID 与券商资金账号不是同一个编号。",
            "三、设置门禁：填写单笔/单日金额上限、持仓上限、快照时效、交易时段和标的白名单，自动执行保持关闭。",
            "四、创建凭证：为 Agent 选择允许访问的系统账户，确认后立即复制一次性 Token；离开结果页后不会再次显示。",
            "五、安装 Agent：在 Windows 解压安装包，复制本屏安装命令并替换系统账户 ID、Python 和 QMT 路径。",
            "六、保存 Token：使用 Set-AgentToken.ps1 通过 Windows DPAPI 保存，不要写进配置、日志或启动参数。",
            "七、只读验收：保持 QMT 已登录，运行 Test-Connection.ps1 -ReadProbe；只有 ready 为 true 才继续仿真。",
            "八、分级启用：依次完成 Shadow、Dry-run、QMT 仿真和小额人工确认，禁止直接开启自动实盘。",
        ]
    )


def _bounded_limit(value: int) -> int:
    """Validate a query limit before it reaches persistence."""

    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_QUERY_LIMIT:
        raise BrokerExecutionValidationError(f"limit must be between 1 and {_MAX_QUERY_LIMIT}")
    return value


def _optional_account_id(value: int | None) -> int | None:
    """Validate an optional persisted account identifier."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BrokerExecutionValidationError("account_id must be a positive integer")
    return value


def _optional_status(value: str | None) -> str | None:
    """Normalize an optional canonical order status."""

    if value is None:
        return None
    normalized = value.strip()
    try:
        return LiveOrderStatus(normalized).value
    except (AttributeError, ValueError):
        raise BrokerExecutionValidationError("status is invalid")


def _client_order_id(value: str | UUID) -> str:
    """Return one canonical UUID client-order identifier."""

    if isinstance(value, UUID):
        return str(value)
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise BrokerExecutionValidationError("client_order_id is invalid") from exc


class BrokerExecutionQueryService:
    """Expose user-scoped, side-effect-free execution projections."""

    def __init__(
        self,
        repository: BrokerExecutionRepositoryProtocol | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = (
            repository if repository is not None else get_broker_execution_repository()
        )
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        """Return one trusted, timezone-aware evaluation clock."""

        now = self.clock()
        if now.tzinfo is None:
            raise BrokerExecutionValidationError("evaluation clock must be timezone-aware")
        return now.astimezone(UTC)

    def overview(self, *, actor: Any) -> dict[str, Any]:
        """Return the current user's execution readiness overview."""

        user_id, _role, is_admin = require_action(actor, "view")
        overview = self.repository.build_overview(user_id=user_id, is_admin=is_admin)
        rows = self.repository.list_connections(user_id=user_id, is_admin=is_admin)
        now = self._now()
        connections = [project_connection_status(row, evaluated_at=now) for row in rows]
        overview["connections"] = connections
        return cast(
            dict[str, Any],
            project_broker_overview(
                cast(OverviewRawFacts, overview),
                evaluated_at=now,
            ),
        )

    def orders(
        self,
        *,
        actor: Any,
        account_id: int | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return a scoped, actor-aware, display-only order catalog."""

        user_id, _role, is_admin = require_action(actor, "view")
        normalized_account_id = _optional_account_id(account_id)
        rows = self.repository.list_orders(
            user_id=user_id,
            is_admin=is_admin,
            account_id=normalized_account_id,
            status=_optional_status(status),
            limit=_bounded_limit(limit),
        )
        now = self._now()
        role_permissions = action_permissions(actor)
        access_cache: dict[tuple[int, str], bool] = {}
        orders: list[dict[str, object]] = []
        for row in rows:
            raw_account_id = row.get("account_id")
            valid_account_id = (
                raw_account_id if type(raw_account_id) is int and raw_account_id > 0 else None
            )
            actor_authorization: dict[str, bool] = {}
            for action in ("approve", "reject", "cancel"):
                cache_key = (valid_account_id or 0, action)
                if valid_account_id is None or not bool(role_permissions.get(action)):
                    actor_authorization[action] = False
                    continue
                if cache_key not in access_cache:
                    access_cache[cache_key] = self.repository.has_account_access(
                        user_id=user_id,
                        is_admin=is_admin,
                        account_id=valid_account_id,
                        action=action,
                    )
                actor_authorization[action] = access_cache[cache_key]
            orders.append(
                project_broker_order_catalog_item(
                    row,
                    evaluated_at=now,
                    actor_authorization=actor_authorization,
                ).to_payload()
            )
        return {
            "evaluated_at": now.isoformat(),
            "orders": orders,
            "total_count": len(orders),
            "permission": "display_only",
            "blocker_codes": ["broker_order_catalog_display_only"],
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }

    def order_detail(
        self,
        *,
        actor: Any,
        client_order_id: str | UUID,
    ) -> dict[str, Any]:
        """Return one scoped order and its execution timeline."""

        user_id, _role, is_admin = require_action(actor, "view")
        order = self.repository.get_order(
            user_id=user_id,
            is_admin=is_admin,
            client_order_id=_client_order_id(client_order_id),
        )
        if order is None:
            raise BrokerExecutionNotFoundError("Live order does not exist")
        role_permissions = action_permissions(actor)
        account_id = _optional_account_id(cast(int | None, order.get("account_id")))
        if account_id is None:
            raise BrokerExecutionValidationError("order account_id is missing")
        actor_authorization = {
            action: bool(role_permissions.get(action))
            and self.repository.has_account_access(
                user_id=user_id,
                is_admin=is_admin,
                account_id=account_id,
                action=action,
            )
            for action in ("approve", "reject", "cancel")
        }
        return project_broker_order_detail(
            order,
            evaluated_at=self._now(),
            actor_authorization=actor_authorization,
        ).to_payload()

    def connections(self, *, actor: Any) -> dict[str, Any]:
        """Return source-time-preserving, freshness-derived connection health."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_connections(user_id=user_id, is_admin=is_admin)
        now = self._now()
        connections = [project_connection_status(row, evaluated_at=now) for row in rows]
        any_connected = any(bool(item["qmt_connected"]) for item in connections)
        return {
            "evaluated_at": now.isoformat(),
            "connections": connections,
            "total_count": len(connections),
            "must_not_use_for_decision": not any_connected,
            "must_not_execute": not any_connected,
        }

    def qmt_onboarding(
        self,
        *,
        actor: Any,
        server_address: str,
    ) -> dict[str, Any]:
        """Return administrator-only QMT setup guidance and persisted settings."""

        actor_id, _role, is_admin = require_action(actor, "manage_binding")
        normalized_server_address = _server_address(server_address)
        persisted = self.repository.list_connections(user_id=actor_id, is_admin=is_admin)
        now = self._now()
        connections: list[dict[str, Any]] = []
        settings: list[dict[str, Any]] = []
        for agent in persisted:
            raw_bindings = agent.get("bindings")
            bindings = raw_bindings if isinstance(raw_bindings, list) else []
            active_bindings = [
                binding
                for binding in bindings
                if isinstance(binding, dict) and bool(binding.get("is_active"))
            ]
            connection = project_connection_status(agent, evaluated_at=now)
            qmt_connected = bool(connection["qmt_connected"])
            connections.append(
                {
                    "agent_id": str(agent.get("agent_id") or ""),
                    "display_name": str(agent.get("display_name") or ""),
                    "status": str(agent.get("status") or ""),
                    "qmt_connected": qmt_connected,
                    "reported_qmt_connected": connection["reported_qmt_connected"],
                    "agent_version": str(agent.get("agent_version") or ""),
                    "source_observed_at": connection["source_observed_at"],
                    "received_at": connection["received_at"],
                    "last_heartbeat_at": connection["last_heartbeat_at"],
                    "heartbeat_fresh": connection["heartbeat_fresh"],
                    "freshness_status": connection["freshness_status"],
                    "blocker_codes": connection["blocker_codes"],
                    "must_not_use_for_decision": connection["must_not_use_for_decision"],
                    "must_not_execute": connection["must_not_execute"],
                    "blocking_reason": (
                        "" if qmt_connected else "QMT 未连接或 Agent 心跳已超过 90 秒"
                    ),
                    "binding_count": len(active_bindings),
                    "account_ids": [binding.get("account_id") for binding in active_bindings],
                }
            )
            for binding in active_bindings:
                settings.append(
                    {
                        "account_id": binding.get("account_id"),
                        "agent_id": str(agent.get("agent_id") or ""),
                        "broker_account_mask": str(binding.get("broker_account_mask") or ""),
                        "auto_execution_enabled": bool(binding.get("auto_execution_enabled")),
                        "max_single_order_amount": binding.get("max_single_order_amount"),
                        "daily_order_amount_limit": binding.get("daily_order_amount_limit"),
                        "max_position_count": binding.get("max_position_count"),
                        "max_snapshot_age_seconds": binding.get("max_snapshot_age_seconds"),
                        "price_deviation_limit_pct": binding.get("price_deviation_limit_pct"),
                        "allowed_trading_windows": binding.get("allowed_trading_windows") or [],
                        "enforce_trading_session": bool(binding.get("enforce_trading_session")),
                        "allowed_symbols": binding.get("allowed_symbols") or [],
                    }
                )
        connected_agent_count = sum(1 for item in connections if bool(item.get("qmt_connected")))
        if not settings:
            setup_state = "尚未绑定账户"
            summary = "先完成 Agent 与系统账户绑定，再创建一次性凭证。"
            next_step = "打开“Agent 与账户绑定”，填写资料后先预览再确认。"
        elif connected_agent_count == 0:
            setup_state = "等待本地 Agent 连接"
            summary = "服务端配置已存在，但尚未收到 QMT 已连接状态。"
            next_step = "安装 Agent、保存一次性 Token，并运行只读连接测试。"
        else:
            setup_state = "QMT 已连接"
            summary = "至少一个本地 Agent 已报告 QMT 连接，继续核对门禁并完成仿真。"
            next_step = "保持自动执行关闭，完成只读探针和 QMT 仿真验收。"
        return {
            "setup_state": setup_state,
            "summary": summary,
            "next_step": next_step,
            "server_address": normalized_server_address,
            "setup_guide": _setup_guide(),
            "package_build_command": (
                "powershell -NoProfile -ExecutionPolicy Bypass "
                "-File .\\scripts\\build_qmt_agent_package.ps1"
            ),
            "windows_install_command": _windows_install_command(normalized_server_address),
            "token_setup_command": (
                "powershell -NoProfile -ExecutionPolicy Bypass "
                "-File .\\Set-AgentToken.ps1 -StartTask"
            ),
            "verification_command": (
                "powershell -NoProfile -ExecutionPolicy Bypass "
                "-File .\\Test-Connection.ps1 -ReadProbe"
            ),
            "safety_notice": (
                "自动执行保持关闭；Token 只显示一次且必须由 Windows DPAPI 保存；"
                "只读探针、仿真和小额人工确认未完成前不得启用自动实盘。"
            ),
            "agent_count": len(connections),
            "connected_agent_count": connected_agent_count,
            "bound_account_count": len(settings),
            "connections": connections,
            "settings": settings,
        }

    def account_access_grants(self, *, actor: Any) -> dict[str, Any]:
        """Return administrator-visible account grants."""

        actor_id, _role, _is_admin = require_action(actor, "manage_access")
        rows = self.repository.list_account_access_grants(actor_id=actor_id)
        return {"access_grants": rows, "access_grant_count": len(rows)}

    def reconciliations(self, *, actor: Any, limit: int = 100) -> dict[str, Any]:
        """Return typed, current, display-only reconciliation evidence."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_reconciliations(
            user_id=user_id,
            is_admin=is_admin,
            limit=_bounded_limit(limit),
        )
        now = self._now()
        runs = [project_broker_reconciliation(row, evaluated_at=now).to_payload() for row in rows]
        return {
            "evaluated_at": now.isoformat(),
            "runs": runs,
            "total_count": len(runs),
            "permission": "display_only",
            "must_not_use_for_decision": True,
            "must_not_execute": True,
        }

    def audits(self, *, actor: Any, limit: int = 100) -> dict[str, Any]:
        """Return typed, redacted, display-only execution audit events."""

        user_id, _role, is_admin = require_action(actor, "view")
        rows = self.repository.list_audits(
            user_id=user_id,
            is_admin=is_admin,
            limit=_bounded_limit(limit),
        )
        now = self._now()
        events = [project_broker_audit_event(row, evaluated_at=now).to_payload() for row in rows]
        return {
            "evaluated_at": now.isoformat(),
            "events": events,
            "total_count": len(events),
            "permission": "display_only",
            "must_not_execute": True,
            "must_not_use_for_decision": True,
        }
