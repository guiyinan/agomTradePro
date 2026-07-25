"""Operation audit-log persistence for Audit.

Owns ORM persistence for MCP/SDK/API operation logs, operation statistics,
retention cleanup, and decision-trace aggregation.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from apps.audit.domain.entities import (
    OperationLog,
    mask_sensitive_params,
    mask_sensitive_text,
)

if TYPE_CHECKING:
    from .models import OperationLogModel

logger = logging.getLogger(__name__)

__all__ = ["OperationLogRepositoryMixin"]


class OperationLogRepositoryMixin:
    """Operation audit log persistence and decision-trace aggregation."""

    def count_operation_logs(self) -> int:
        """统计操作审计日志总数。"""
        from .models import OperationLogModel

        return OperationLogModel._default_manager.count()

    def save_operation_log(self, log_entity: OperationLog) -> str:
        """
        保存操作日志

        增强可观测性：
        - 失败时记录到失败计数器
        - 记录详细错误日志
        - 不抛出异常（让上层决定如何处理）

        Args:
            log_entity: OperationLog 域实体

        Returns:
            str: 日志 ID
        """
        from .models import OperationLogModel

        try:
            model = OperationLogModel._default_manager.create(
                id=log_entity.id,
                request_id=log_entity.request_id,
                user_id=log_entity.user_id,
                username=log_entity.username,
                ip_address=log_entity.ip_address,
                user_agent=log_entity.user_agent,
                source=log_entity.source.value,
                client_id=log_entity.client_id,
                operation_type=log_entity.operation_type.value,
                module=log_entity.module,
                action=log_entity.action.value,
                resource_type=log_entity.resource_type,
                resource_id=log_entity.resource_id,
                mcp_tool_name=log_entity.mcp_tool_name,
                mcp_client_id=log_entity.mcp_client_id,
                mcp_role=log_entity.mcp_role,
                sdk_version=log_entity.sdk_version,
                request_method=log_entity.request_method,
                request_path=log_entity.request_path,
                request_params=log_entity.request_params,
                response_payload=log_entity.response_payload,
                response_text=log_entity.response_text,
                response_status=log_entity.response_status,
                response_message=log_entity.response_message,
                error_code=log_entity.error_code,
                exception_traceback=log_entity.exception_traceback,
                duration_ms=log_entity.duration_ms,
                checksum=log_entity.checksum,
            )
            logger.debug(
                f"操作日志保存成功: log_id={model.id}, "
                f"user={log_entity.username}, module={log_entity.module}"
            )
            return str(model.id)

        except Exception as exc:
            # 记录到失败计数器（增强可观测性）
            try:
                from .failure_counter import record_audit_failure

                record_audit_failure(
                    component="database",
                    reason=f"save_operation_log failed: {type(exc).__name__}",
                )
            except ImportError:
                pass

            # 记录详细错误日志
            logger.error(
                "保存操作日志失败: module=%s, action=%s, error_type=%s",
                log_entity.module,
                log_entity.action,
                type(exc).__name__,
                exc_info=False,
            )
            # 重新抛出异常，让上层用例处理
            raise

    def query_operation_logs(
        self,
        user_id: int | None = None,
        username: str | None = None,
        operation_type: str | None = None,
        module: str | None = None,
        action: str | None = None,
        mcp_tool_name: str | None = None,
        mcp_client_id: str | None = None,
        mcp_role: str | None = None,
        response_status: int | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        resource_id: str | None = None,
        source: str | None = None,
        ordering: str = "-timestamp",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, object]], int]:
        """
        查询操作日志

        Args:
            各种过滤条件
            ordering: 排序字段
            page: 页码
            page_size: 每页数量

        Returns:
            tuple: (logs_list, total_count)
        """

        from .models import OperationLogModel

        queryset = OperationLogModel._default_manager.all()

        # 应用过滤条件
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)
        if username:
            queryset = queryset.filter(username__icontains=username)
        if operation_type:
            queryset = queryset.filter(operation_type=operation_type)
        if module:
            queryset = queryset.filter(module=module)
        if action:
            queryset = queryset.filter(action=action)
        if mcp_tool_name:
            queryset = queryset.filter(mcp_tool_name__icontains=mcp_tool_name)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id__icontains=mcp_client_id)
        if mcp_role:
            queryset = queryset.filter(mcp_role=mcp_role)
        if response_status is not None:
            queryset = queryset.filter(response_status=response_status)
        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)
        if resource_id:
            queryset = queryset.filter(resource_id=resource_id)
        if source:
            queryset = queryset.filter(source=source)

        # 统计总数
        total_count = queryset.count()

        # 排序
        queryset = queryset.order_by(ordering)

        # 分页
        offset = (page - 1) * page_size
        queryset = queryset[offset : offset + page_size]

        # 序列化
        logs = [
            {
                "id": str(log.id),
                "request_id": log.request_id,
                "user_id": log.user_id,
                "username": log.username,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "source": log.source,
                "client_id": log.client_id,
                "operation_type": log.operation_type,
                "module": log.module,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "mcp_tool_name": log.mcp_tool_name,
                "mcp_client_id": log.mcp_client_id,
                "mcp_role": log.mcp_role,
                "sdk_version": log.sdk_version,
                "request_method": log.request_method,
                "request_path": mask_sensitive_text(log.request_path),
                "request_params": mask_sensitive_params(log.request_params),
                "response_payload": mask_sensitive_params(log.response_payload),
                "response_text": mask_sensitive_text(log.response_text),
                "response_status": log.response_status,
                "response_message": mask_sensitive_text(log.response_message),
                "error_code": log.error_code,
                "exception_traceback": mask_sensitive_text(log.exception_traceback),
                "timestamp": log.timestamp.isoformat(),
                "duration_ms": log.duration_ms,
                "checksum": log.checksum,
            }
            for log in queryset
        ]

        return logs, total_count

    def get_operation_log_by_id(self, log_id: str) -> dict[str, object] | None:
        """
        根据 ID 获取操作日志

        Args:
            log_id: 日志 ID

        Returns:
            Optional[dict]: 日志字典，不存在返回 None
        """
        from .models import OperationLogModel

        try:
            log = OperationLogModel._default_manager.get(id=log_id)
            return {
                "id": str(log.id),
                "request_id": log.request_id,
                "user_id": log.user_id,
                "username": log.username,
                "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "source": log.source,
                "client_id": log.client_id,
                "operation_type": log.operation_type,
                "module": log.module,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "mcp_tool_name": log.mcp_tool_name,
                "mcp_client_id": log.mcp_client_id,
                "mcp_role": log.mcp_role,
                "sdk_version": log.sdk_version,
                "request_method": log.request_method,
                "request_path": mask_sensitive_text(log.request_path),
                "request_params": mask_sensitive_params(log.request_params),
                "response_payload": mask_sensitive_params(log.response_payload),
                "response_text": mask_sensitive_text(log.response_text),
                "response_status": log.response_status,
                "response_message": mask_sensitive_text(log.response_message),
                "error_code": log.error_code,
                "exception_traceback": mask_sensitive_text(log.exception_traceback),
                "timestamp": log.timestamp.isoformat(),
                "duration_ms": log.duration_ms,
                "checksum": log.checksum,
            }
        except (OperationLogModel.DoesNotExist, ValueError):
            return None

    def get_operation_stats(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        group_by: str = "module",
    ) -> dict[str, object]:
        """
        获取操作统计

        Args:
            start_date: 起始日期
            end_date: 结束日期
            group_by: 分组维度 (module/tool/user/status)

        Returns:
            dict: 统计结果
        """
        from django.db.models import Avg, Count

        from .models import OperationLogModel

        queryset = OperationLogModel._default_manager.all()

        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)

        # 基础统计
        total_count = queryset.count()
        error_count = queryset.filter(response_status__gte=400).count()
        avg_duration = queryset.aggregate(avg=Avg("duration_ms"))["avg"]

        stats: dict[str, object] = {
            "total_count": total_count,
            "error_count": error_count,
            "error_rate": error_count / total_count if total_count > 0 else 0,
            "avg_duration_ms": round(avg_duration, 2) if avg_duration else None,
            "period": {
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            },
        }

        # 按维度分组统计
        if group_by == "module":
            stats["by_module"] = list(
                queryset.values("module").annotate(count=Count("id")).order_by("-count")[:10]
            )

        elif group_by == "tool":
            stats["by_tool"] = list(
                queryset.values("mcp_tool_name").annotate(count=Count("id")).order_by("-count")[:10]
            )

        elif group_by == "user":
            stats["by_user"] = list(
                queryset.values("user_id", "username")
                .annotate(count=Count("id"))
                .order_by("-count")[:10]
            )

        elif group_by == "status":
            stats["by_status"] = list(
                queryset.values("response_status").annotate(count=Count("id")).order_by("-count")
            )

        return stats

    def cleanup_old_operation_logs(self, days: int = 90, dry_run: bool = False) -> int:
        """
        清理旧的操作日志

        Args:
            days: 保留天数
            dry_run: 是否只模拟运行

        Returns:
            int: 删除的记录数
        """
        from datetime import timedelta

        from django.utils import timezone

        from .models import OperationLogModel

        cutoff_date = timezone.now() - timedelta(days=days)
        queryset = OperationLogModel._default_manager.filter(timestamp__lt=cutoff_date)

        if dry_run:
            return queryset.count()

        count, _ = queryset.delete()
        return count

    def list_decision_traces(
        self,
        current_user_id: int | None = None,
        is_admin: bool = False,
        mcp_client_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, object]], int]:
        """按 request_id 聚合 MCP/SDK 调用，生成决策链列表。"""
        from django.db.models import Count, Max, Min

        from .models import OperationLogModel

        queryset = OperationLogModel._default_manager.exclude(request_id="")
        if not is_admin:
            if current_user_id is None:
                return [], 0
            queryset = queryset.filter(user_id=current_user_id)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id__icontains=mcp_client_id)

        grouped = (
            queryset.values("request_id", "mcp_client_id")
            .annotate(
                started_at=Min("timestamp"),
                finished_at=Max("timestamp"),
                step_count=Count("id"),
                last_status=Max("response_status"),
            )
            .order_by("-finished_at")
        )

        total_count = grouped.count()
        offset = (page - 1) * page_size
        rows = list(grouped[offset : offset + page_size])
        trace_keys = [(row["request_id"], row["mcp_client_id"] or "") for row in rows]
        trace_ids = [row["request_id"] for row in rows]
        if not trace_keys:
            return [], total_count

        sample_logs = queryset.filter(request_id__in=trace_ids).order_by("request_id", "timestamp")
        samples_by_request: dict[tuple[str, str], list[OperationLogModel]] = {}
        for log in sample_logs:
            samples_by_request.setdefault((log.request_id, log.mcp_client_id or ""), []).append(log)

        traces: list[dict[str, object]] = []
        for row in rows:
            request_id = row["request_id"]
            client_key = row["mcp_client_id"] or ""
            logs = samples_by_request.get((request_id, client_key), [])
            first_log = logs[0] if logs else None
            last_log = logs[-1] if logs else None
            traces.append(
                {
                    "request_id": request_id,
                    "mcp_client_id": client_key,
                    "username": first_log.username if first_log else "anonymous",
                    "user_id": first_log.user_id if first_log else None,
                    "source": first_log.source if first_log else "MCP",
                    "started_at": row["started_at"].isoformat() if row["started_at"] else None,
                    "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
                    "step_count": row["step_count"],
                    "status": (
                        "failed" if (last_log and last_log.response_status >= 400) else "success"
                    ),
                    "last_status": last_log.response_status if last_log else 200,
                    "modules": list(dict.fromkeys(log.module for log in logs if log.module)),
                    "tools": [log.mcp_tool_name or log.operation_type for log in logs],
                    "summary": self._build_decision_trace_summary(logs),
                }
            )

        return traces, total_count

    def get_decision_trace(
        self,
        request_id: str,
        mcp_client_id: str | None = None,
        current_user_id: int | None = None,
        is_admin: bool = False,
    ) -> dict[str, object] | None:
        """获取单条决策链详情。"""
        from .models import OperationLogModel

        queryset = OperationLogModel._default_manager.filter(request_id=request_id).order_by(
            "timestamp"
        )
        if not is_admin:
            if current_user_id is None:
                return None
            queryset = queryset.filter(user_id=current_user_id)
        if mcp_client_id:
            queryset = queryset.filter(mcp_client_id=mcp_client_id)

        logs = list(queryset)
        if not logs:
            return None

        steps: list[dict[str, object]] = []
        for index, log in enumerate(logs, start=1):
            steps.append(
                {
                    "step_index": index,
                    "log_id": str(log.id),
                    "timestamp": log.timestamp.isoformat(),
                    "tool_name": log.mcp_tool_name or log.operation_type,
                    "module": log.module,
                    "action": log.action,
                    "request_path": mask_sensitive_text(log.request_path),
                    "response_status": log.response_status,
                    "duration_ms": log.duration_ms,
                    "summary": self._build_step_summary(log),
                    "response_message": mask_sensitive_text(log.response_message),
                }
            )

        first_log = logs[0]
        last_log = logs[-1]
        return {
            "request_id": request_id,
            "mcp_client_id": first_log.mcp_client_id,
            "username": first_log.username,
            "user_id": first_log.user_id,
            "source": first_log.source,
            "started_at": first_log.timestamp.isoformat(),
            "finished_at": last_log.timestamp.isoformat(),
            "step_count": len(steps),
            "status": "failed" if last_log.response_status >= 400 else "success",
            "final_summary": self._build_step_summary(last_log),
            "steps": steps,
            "logs": [
                {
                    "id": str(log.id),
                    "timestamp": log.timestamp.isoformat(),
                    "mcp_tool_name": log.mcp_tool_name,
                    "module": log.module,
                    "action": log.action,
                    "request_path": mask_sensitive_text(log.request_path),
                    "request_params": mask_sensitive_params(log.request_params),
                    "response_payload": mask_sensitive_params(log.response_payload),
                    "response_text": mask_sensitive_text(log.response_text),
                    "response_status": log.response_status,
                    "response_message": mask_sensitive_text(log.response_message),
                    "error_code": log.error_code,
                    "exception_traceback": mask_sensitive_text(log.exception_traceback),
                    "duration_ms": log.duration_ms,
                    "checksum": log.checksum,
                }
                for log in logs
            ],
        }

    @staticmethod
    def _build_decision_trace_summary(logs: list[OperationLogModel]) -> str:
        """构建决策链摘要。"""
        if not logs:
            return ""
        final_log = logs[-1]
        if final_log.response_status >= 400:
            return (
                f"{final_log.mcp_tool_name or final_log.operation_type} failed: "
                f"{mask_sensitive_text(final_log.response_message) or final_log.error_code}"
            )
        return OperationLogRepositoryMixin._build_step_summary(final_log)

    @staticmethod
    def _build_step_summary(log: OperationLogModel) -> str:
        """从单条日志提炼步骤摘要。"""
        payload = mask_sensitive_params(log.response_payload)
        if isinstance(payload, dict):
            for key in ("summary", "message", "decision", "status", "result", "recommendation"):
                value = payload.get(key)
                if value:
                    return mask_sensitive_text(str(value))
        if log.response_message:
            return mask_sensitive_text(log.response_message)
        if log.response_text:
            return mask_sensitive_text(log.response_text)[:160]
        return log.mcp_tool_name or log.operation_type
