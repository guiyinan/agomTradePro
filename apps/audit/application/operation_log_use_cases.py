"""MCP/SDK operation audit-log use cases."""

import logging
from dataclasses import dataclass
from datetime import UTC, date

from apps.audit.application.attribution_use_cases import (
    RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS,
)
from apps.audit.application.repository_provider import (
    DjangoAuditRepository,
    record_audit_failure,
    record_audit_write_failure,
    record_audit_write_success,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ExportOperationLogsRequest",
    "ExportOperationLogsResponse",
    "ExportOperationLogsUseCase",
    "GetOperationLogDetailRequest",
    "GetOperationLogDetailResponse",
    "GetOperationLogDetailUseCase",
    "GetOperationStatsRequest",
    "GetOperationStatsResponse",
    "GetOperationStatsUseCase",
    "LogOperationRequest",
    "LogOperationResponse",
    "LogOperationUseCase",
    "QueryOperationLogsRequest",
    "QueryOperationLogsResponse",
    "QueryOperationLogsUseCase",
]


# ============ MCP/SDK 操作审计日志用例 ============


@dataclass(frozen=True)
class LogOperationRequest:
    """记录操作日志请求"""

    request_id: str
    delivery_id: str | None = None
    user_id: int | None = None
    username: str = "anonymous"
    source: str = "MCP"  # MCP/SDK/API
    operation_type: str = "MCP_CALL"  # MCP_CALL/API_ACCESS/DATA_MODIFY
    module: str = ""
    action: str = "READ"  # CREATE/READ/UPDATE/DELETE/EXECUTE
    mcp_tool_name: str | None = None
    request_params: dict[str, object] | None = None
    response_payload: object | None = None
    response_text: str = ""
    response_status: int = 200
    response_message: str = ""
    error_code: str = ""
    exception_traceback: str = ""
    duration_ms: int | None = None
    ip_address: str | None = None
    user_agent: str = ""
    client_id: str = ""
    resource_type: str = ""
    resource_id: str | None = None
    mcp_client_id: str = ""
    mcp_role: str = ""
    sdk_version: str = ""
    request_method: str = "MCP"
    request_path: str = ""


@dataclass(frozen=True)
class LogOperationResponse:
    """记录操作日志响应"""

    success: bool
    log_id: str | None = None
    error: str | None = None


class LogOperationUseCase:
    """记录操作日志用例"""

    def __init__(self, audit_repository: "DjangoAuditRepository"):
        self.audit_repo = audit_repository

    def execute(self, request: LogOperationRequest) -> LogOperationResponse:
        """
        记录操作日志

        此用例用于内部写入接口，审计失败不阻塞主流程。

        增强可观测性：
        - 失败时记录到专门的计数器
        - 记录 Prometheus 指标
        - 记录详细的错误上下文
        - 不影响主流程执行
        """
        import time

        start_time = time.time()

        try:
            from apps.audit.domain.services import OperationLogFactory

            # 创建日志实体 - 工厂函数会自动推断模块和动作
            log = OperationLogFactory.create_from_mcp_call(
                request_id=request.request_id,
                delivery_id=request.delivery_id,
                tool_name=request.mcp_tool_name or "unknown",
                user_id=request.user_id,
                username=request.username,
                source=request.source,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                request_params=request.request_params,
                response_payload=request.response_payload,
                response_text=request.response_text,
                response_status=request.response_status,
                response_message=request.response_message,
                error_code=request.error_code,
                exception_traceback=request.exception_traceback,
                duration_ms=request.duration_ms,
                ip_address=request.ip_address,
                user_agent=request.user_agent,
                client_id=request.client_id,
                mcp_role=request.mcp_role,
                sdk_version=request.sdk_version,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                mcp_client_id=request.mcp_client_id,
                request_method=request.request_method,
                request_path=request.request_path,
            )

            # 保存到数据库
            log_id = self.audit_repo.save_operation_log(log)

            # 计算延迟并记录 Prometheus 指标
            latency_seconds = time.time() - start_time
            try:
                record_audit_write_success(
                    module=request.module or "unknown",
                    action=request.action or "unknown",
                    source=(
                        request.source.value
                        if hasattr(request.source, "value")
                        else str(request.source)
                    ),
                    latency_seconds=latency_seconds,
                )
            except ImportError:
                pass  # Prometheus 指标模块不可用时跳过

            logger.info(f"操作日志已记录: log_id={log_id}, tool={request.mcp_tool_name}")

            return LogOperationResponse(
                success=True,
                log_id=log_id,
            )

        except Exception as exc:
            # 计算延迟
            latency_seconds = time.time() - start_time

            # 审计日志属于非阻断型旁路写入，这里保留边界级兜底，
            # 避免任意 repository/metrics 故障影响主业务流程。
            # 增强可观测性：记录到失败计数器
            try:
                # 判断失败组件类型
                component = "repository"
                error_name = type(exc).__name__.lower()
                if "database" in error_name or "connection" in error_name:
                    component = "database"
                elif "validation" in error_name:
                    component = "validation"
                elif "timeout" in error_name:
                    component = "timeout"

                record_audit_failure(
                    component=component,
                    reason=type(exc).__name__,
                    exc_info=False,  # 已在下面记录
                )
            except ImportError:
                # 如果计数器模块不可用，继续执行
                pass

            # 记录 Prometheus 失败指标
            try:
                record_audit_write_failure(
                    module=request.module or "unknown",
                    error_type=component if "component" in locals() else "unknown",
                    source=(
                        request.source.value
                        if hasattr(request.source, "value")
                        else str(request.source)
                    ),
                    latency_seconds=latency_seconds,
                )
            except ImportError:
                pass  # Prometheus 指标模块不可用时跳过

            logger.error(
                "记录操作日志失败: %s",
                type(exc).__name__,
                exc_info=False,
            )

            return LogOperationResponse(
                success=False,
                error="审计日志写入失败",
            )


@dataclass(frozen=True)
class QueryOperationLogsRequest:
    """查询操作日志请求"""

    user_id: int | None = None
    username: str | None = None
    operation_type: str | None = None
    module: str | None = None
    action: str | None = None
    mcp_tool_name: str | None = None
    mcp_client_id: str | None = None
    mcp_role: str | None = None
    response_status: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    resource_id: str | None = None
    source: str | None = None
    ordering: str = "-timestamp"
    page: int = 1
    page_size: int = 20
    # 权限控制
    is_admin: bool = False
    current_user_id: int | None = None


@dataclass(frozen=True)
class QueryOperationLogsResponse:
    """查询操作日志响应"""

    success: bool
    logs: list[dict[str, object]] | None = None
    total_count: int = 0
    page: int = 1
    page_size: int = 20
    error: str | None = None


class QueryOperationLogsUseCase:
    """查询操作日志用例"""

    def __init__(self, audit_repository: "DjangoAuditRepository"):
        self.audit_repo = audit_repository

    def execute(self, request: QueryOperationLogsRequest) -> QueryOperationLogsResponse:
        """
        查询操作日志

        权限控制：
        - 管理员可查询全量日志
        - 普通用户仅可查询本人日志
        """
        try:
            # 权限控制：普通用户只能查看自己的日志
            user_id: int | None
            if not request.is_admin:
                if request.current_user_id is None:
                    return QueryOperationLogsResponse(
                        success=False,
                        error="需要有效用户身份",
                    )
                # 强制覆盖 user_id 为当前用户
                user_id = request.current_user_id
            else:
                user_id = request.user_id
            if request.ordering not in {"timestamp", "-timestamp", "duration_ms", "-duration_ms"}:
                return QueryOperationLogsResponse(
                    success=False,
                    error="不支持的排序字段",
                )
            if request.page <= 0 or request.page_size <= 0 or request.page_size > 100:
                return QueryOperationLogsResponse(
                    success=False,
                    error="分页参数超出允许范围",
                )

            # 查询日志
            logs, total_count = self.audit_repo.query_operation_logs(
                user_id=user_id,
                username=request.username,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                mcp_tool_name=request.mcp_tool_name,
                mcp_client_id=request.mcp_client_id,
                mcp_role=request.mcp_role,
                response_status=request.response_status,
                start_date=request.start_date,
                end_date=request.end_date,
                resource_id=request.resource_id,
                source=request.source,
                ordering=request.ordering,
                page=request.page,
                page_size=request.page_size,
            )

            return QueryOperationLogsResponse(
                success=True,
                logs=logs,
                total_count=total_count,
                page=request.page,
                page_size=request.page_size,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("查询操作日志失败: %s", type(exc).__name__)
            return QueryOperationLogsResponse(
                success=False,
                error="查询操作日志失败",
            )


@dataclass(frozen=True)
class GetOperationLogDetailRequest:
    """获取操作日志详情请求"""

    log_id: str
    current_user_id: int | None = None
    is_admin: bool = False


@dataclass(frozen=True)
class GetOperationLogDetailResponse:
    """获取操作日志详情响应"""

    success: bool
    log: dict[str, object] | None = None
    error: str | None = None


class GetOperationLogDetailUseCase:
    """获取操作日志详情用例"""

    def __init__(self, audit_repository: "DjangoAuditRepository"):
        self.audit_repo = audit_repository

    def execute(self, request: GetOperationLogDetailRequest) -> GetOperationLogDetailResponse:
        """
        获取操作日志详情

        权限控制：
        - 管理员可查看所有日志
        - 普通用户仅可查看本人日志
        """
        try:
            if not request.is_admin and request.current_user_id is None:
                return GetOperationLogDetailResponse(
                    success=False,
                    error="需要有效用户身份",
                )
            log = self.audit_repo.get_operation_log_by_id(request.log_id)

            if not log:
                return GetOperationLogDetailResponse(
                    success=False,
                    error="日志不存在",
                )

            # 权限检查
            if not request.is_admin:
                if log.get("user_id") != request.current_user_id:
                    return GetOperationLogDetailResponse(
                        success=False,
                        error="无权查看此日志",
                    )

            return GetOperationLogDetailResponse(
                success=True,
                log=log,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("获取操作日志详情失败: %s", type(exc).__name__)
            return GetOperationLogDetailResponse(
                success=False,
                error="获取操作日志详情失败",
            )


@dataclass(frozen=True)
class ExportOperationLogsRequest:
    """导出操作日志请求"""

    user_id: int | None = None
    username: str | None = None
    operation_type: str | None = None
    module: str | None = None
    action: str | None = None
    mcp_tool_name: str | None = None
    mcp_client_id: str | None = None
    response_status: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    resource_id: str | None = None
    source: str | None = None
    format: str = "csv"  # csv 或 json
    is_admin: bool = False
    # 导出限制
    max_rows: int = 10000
    max_days: int = 90


@dataclass(frozen=True)
class ExportOperationLogsResponse:
    """导出操作日志响应"""

    success: bool
    data: str | None = None  # CSV 或 JSON 字符串
    filename: str | None = None
    row_count: int = 0
    error: str | None = None


class ExportOperationLogsUseCase:
    """导出操作日志用例（仅管理员可用）"""

    def __init__(self, audit_repository: "DjangoAuditRepository"):
        self.audit_repo = audit_repository

    def execute(self, request: ExportOperationLogsRequest) -> ExportOperationLogsResponse:
        """
        导出操作日志

        限制：
        - 最多导出 max_rows 条（默认从 settings 读取）
        - 时间范围最多 max_days 天（默认从 settings 读取）
        """
        try:
            import json
            from datetime import datetime

            from django.conf import settings

            if not request.is_admin:
                return ExportOperationLogsResponse(
                    success=False,
                    error="仅管理员可导出操作日志",
                )
            if request.format not in {"csv", "json"}:
                return ExportOperationLogsResponse(
                    success=False,
                    error="导出格式必须是 csv 或 json",
                )
            if (
                request.max_rows <= 0
                or request.max_days <= 0
                or isinstance(request.max_rows, bool)
                or isinstance(request.max_days, bool)
            ):
                return ExportOperationLogsResponse(
                    success=False,
                    error="导出限制必须是正整数",
                )

            # 从 settings 读取配置
            max_rows = getattr(settings, "AUDIT_EXPORT_MAX_ROWS", 10000)
            max_days = getattr(settings, "AUDIT_EXPORT_MAX_DAYS", 90)

            # 使用请求中的值或配置默认值
            effective_max_rows = min(request.max_rows, max_rows) if request.max_rows else max_rows
            effective_max_days = min(request.max_days, max_days) if request.max_days else max_days

            # 检查时间范围限制
            if request.start_date and request.end_date:
                days_diff = (request.end_date - request.start_date).days
                if days_diff < 0:
                    return ExportOperationLogsResponse(
                        success=False,
                        error="start_date must not be after end_date",
                    )
                if days_diff > effective_max_days:
                    return ExportOperationLogsResponse(
                        success=False,
                        error=f"时间范围不能超过 {effective_max_days} 天",
                    )

            # 查询日志（不分页，但有上限）
            logs, total_count = self.audit_repo.query_operation_logs(
                user_id=request.user_id,
                username=request.username,
                operation_type=request.operation_type,
                module=request.module,
                action=request.action,
                mcp_tool_name=request.mcp_tool_name,
                mcp_client_id=request.mcp_client_id,
                response_status=request.response_status,
                start_date=request.start_date,
                end_date=request.end_date,
                resource_id=request.resource_id,
                source=request.source,
                ordering="-timestamp",
                page=1,
                page_size=effective_max_rows,
            )

            # 生成文件名
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"operation_logs_{timestamp}.{request.format}"

            # 格式化输出
            if request.format == "json":
                data = json.dumps(logs, ensure_ascii=False, indent=2, default=str)
            else:
                # CSV 格式
                import csv
                import io

                output = io.StringIO()
                if logs:
                    writer = csv.DictWriter(output, fieldnames=logs[0].keys())
                    writer.writeheader()
                    writer.writerows(logs)
                data = output.getvalue()

            logger.info(f"导出操作日志: {len(logs)} 条, format={request.format}")

            return ExportOperationLogsResponse(
                success=True,
                data=data,
                filename=filename,
                row_count=len(logs),
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("导出操作日志失败: %s", type(exc).__name__)
            return ExportOperationLogsResponse(
                success=False,
                error="导出操作日志失败",
            )


@dataclass(frozen=True)
class GetOperationStatsRequest:
    """获取操作统计请求"""

    start_date: date | None = None
    end_date: date | None = None
    group_by: str = "module"  # module/tool/user/status
    is_admin: bool = False


@dataclass(frozen=True)
class GetOperationStatsResponse:
    """获取操作统计响应"""

    success: bool
    stats: dict[str, object] | None = None
    error: str | None = None


class GetOperationStatsUseCase:
    """获取操作统计用例（仅管理员可用）"""

    def __init__(self, audit_repository: "DjangoAuditRepository"):
        self.audit_repo = audit_repository

    def execute(self, request: GetOperationStatsRequest) -> GetOperationStatsResponse:
        """
        获取操作统计

        统计内容：
        - 总量
        - 错误率
        - 平均耗时
        - Top 工具/模块
        """
        try:
            if not request.is_admin:
                return GetOperationStatsResponse(
                    success=False,
                    error="仅管理员可查看操作统计",
                )
            if request.group_by not in {"module", "tool", "user", "status"}:
                return GetOperationStatsResponse(
                    success=False,
                    error="不支持的统计分组",
                )
            if (
                request.start_date is not None
                and request.end_date is not None
                and request.start_date > request.end_date
            ):
                return GetOperationStatsResponse(
                    success=False,
                    error="start_date must not be after end_date",
                )
            stats = self.audit_repo.get_operation_stats(
                start_date=request.start_date,
                end_date=request.end_date,
                group_by=request.group_by,
            )

            return GetOperationStatsResponse(
                success=True,
                stats=stats,
            )

        except RECOVERABLE_AUDIT_USE_CASE_EXCEPTIONS as exc:
            logger.error("获取操作统计失败: %s", type(exc).__name__)
            return GetOperationStatsResponse(
                success=False,
                error="获取操作统计失败",
            )
