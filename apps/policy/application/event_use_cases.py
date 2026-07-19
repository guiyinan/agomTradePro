"""Policy event command and query use cases.

Owner module for policy-event lifecycle orchestration (create/update/delete,
current policy level, status, history). Also hosts the dependency-injection
protocols and the recoverable-exception tuple shared by the sibling owner
modules.
"""

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import DatabaseError, IntegrityError

from core.exceptions import (
    AIServiceError,
    BusinessLogicError,
    DataFetchError,
    DataValidationError,
    ExternalServiceError,
    InvalidInputError,
)
from core.metrics import record_exception

from ..domain.entities import PolicyEvent, PolicyLevel
from ..domain.rules import (
    PolicyResponse,
    analyze_policy_transition,
    get_policy_response,
    get_recommendations_for_level,
    is_high_risk_level,
    should_trigger_alert,
    validate_policy_event,
)
from .repository_provider import DjangoPolicyRepository

logger = logging.getLogger(__name__)

RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS = (
    AIServiceError,
    AttributeError,
    BusinessLogicError,
    ConnectionError,
    DataFetchError,
    DataValidationError,
    DatabaseError,
    DjangoValidationError,
    ExternalServiceError,
    ImportError,
    IntegrityError,
    InvalidInputError,
    LookupError,
    RuntimeError,
    TimeoutError,
    TypeError,
    ValueError,
)

__all__ = [
    "AlertServiceProtocol",
    "CreatePolicyEventInput",
    "CreatePolicyEventOutput",
    "CreatePolicyEventUseCase",
    "DeletePolicyEventUseCase",
    "EventStoreProtocol",
    "GetCurrentPolicyResponse",
    "GetCurrentPolicyUseCase",
    "GetPolicyHistoryUseCase",
    "GetPolicyStatusUseCase",
    "PolicyHistoryOutput",
    "PolicyStatusOutput",
    "RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS",
    "UpdatePolicyEventUseCase",
]


@dataclass
class GetCurrentPolicyResponse:
    """Backward-compatible response for current policy query."""

    success: bool
    policy_level: PolicyLevel | None = None
    error: str | None = None


class GetCurrentPolicyUseCase:
    """Backward-compatible use case: fetch current policy level."""

    def __init__(self, repository: DjangoPolicyRepository):
        self.repository = repository

    def execute(self) -> GetCurrentPolicyResponse:
        try:
            level = self.repository.get_current_policy_level(date.today())
            return GetCurrentPolicyResponse(success=True, policy_level=level)
        except (DataFetchError, ExternalServiceError) as e:
            # Known external/data errors - log warning and return error response
            logger.warning(f"GetCurrentPolicyUseCase: data fetch error: {e}")
            record_exception(e, module="policy", is_handled=True)
            return GetCurrentPolicyResponse(success=False, policy_level=None, error=str(e))
        except DatabaseError as e:
            # Database error - convert to DataFetchError
            logger.exception(f"GetCurrentPolicyUseCase: database error: {e}")
            exc = DataFetchError(f"Failed to fetch policy level from database: {e}")
            record_exception(exc, module="policy", is_handled=True)
            return GetCurrentPolicyResponse(success=False, policy_level=None, error=str(exc))
        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            # Unexpected error - log with full context
            logger.exception(f"GetCurrentPolicyUseCase: unexpected error: {e}")
            record_exception(e, module="policy", is_handled=False)
            return GetCurrentPolicyResponse(success=False, policy_level=None, error=str(e))


# Protocol 定义 - 用于依赖注入
class AlertServiceProtocol(Protocol):
    """告警服务协议"""

    def send_alert(
        self, level: str, title: str, message: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        """发送告警"""
        ...


class EventStoreProtocol(Protocol):
    """事件存储协议"""

    def save_event(self, event: PolicyEvent) -> PolicyEvent:
        """保存事件"""
        ...

    def get_latest_event(self, before_date: date | None = None) -> PolicyEvent | None:
        """获取最新事件"""
        ...


@dataclass
class CreatePolicyEventInput:
    """创建政策事件的输入 DTO"""

    event_date: date
    level: PolicyLevel
    title: str
    description: str
    evidence_url: str


@dataclass
class CreatePolicyEventOutput:
    """创建政策事件的输出 DTO"""

    success: bool
    event: PolicyEvent | None = None
    errors: list[str] = None
    warnings: list[str] = None
    alert_triggered: bool = False

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []


@dataclass
class PolicyStatusOutput:
    """政策状态输出 DTO"""

    current_level: PolicyLevel
    level_name: str
    response_config: PolicyResponse
    latest_event: PolicyEvent | None
    is_intervention_active: bool
    is_crisis_mode: bool
    recommendations: list[str]
    as_of_date: date


@dataclass
class PolicyHistoryOutput:
    """政策历史输出 DTO"""

    events: list[PolicyEvent]
    total_count: int
    level_stats: dict[str, Any]
    start_date: date
    end_date: date


class CreatePolicyEventUseCase:
    """
    创建政策事件用例

    功能：
    1. 验证事件有效性
    2. 保存事件到数据库
    3. 分析档位变更
    4. 触发告警（如需要）
    """

    def __init__(
        self, event_store: EventStoreProtocol, alert_service: AlertServiceProtocol | None = None
    ):
        """
        初始化用例

        Args:
            event_store: 事件存储仓储
            alert_service: 告警服务（可选）
        """
        self.event_store = event_store
        self.alert_service = alert_service

    def execute(self, input: CreatePolicyEventInput) -> CreatePolicyEventOutput:
        """
        执行用例

        Args:
            input: 输入 DTO

        Returns:
            CreatePolicyEventOutput: 输出 DTO
        """
        output = CreatePolicyEventOutput(success=False)
        alert_triggered = False

        try:
            # 1. 验证事件
            is_valid, errors = validate_policy_event(
                level=input.level,
                title=input.title,
                description=input.description,
                evidence_url=input.evidence_url,
            )

            if not is_valid:
                output.errors = errors
                logger.warning(f"Policy event validation failed: {errors}")
                return output

            # 2. 创建事件实体
            event = PolicyEvent(
                event_date=input.event_date,
                level=input.level,
                title=input.title,
                description=input.description,
                evidence_url=input.evidence_url,
            )

            # 3. 获取之前的档位
            previous_event = self.event_store.get_latest_event(before_date=input.event_date)
            previous_level = previous_event.level if previous_event else None

            # 4. 保存事件
            saved_event = self.event_store.save_event(event)
            output.event = saved_event

            # 5. 分析档位变更
            if previous_level != input.level:
                transition = analyze_policy_transition(previous_level, input.level)
                output.warnings.append(
                    f"政策档位变更: {transition.from_level or '无'} -> {transition.to_level}"
                )
                output.warnings.append(f"变更时间: {transition.transition_date}")
                if transition.is_upgrade:
                    output.warnings.append("⚠️ 档位升级，请注意风险")

            # 6. 触发告警（如需要）
            if should_trigger_alert(input.level):
                alert_triggered = self._send_alert(event=saved_event, previous_level=previous_level)

            # 7. 添加建议
            recommendations = get_recommendations_for_level(input.level)
            output.warnings.extend(recommendations)

            output.success = True
            output.alert_triggered = alert_triggered

            logger.info(f"Policy event created successfully: {input.level.value} - {input.title}")

        except (DataFetchError, DataValidationError) as e:
            # Known data/validation errors - record and continue
            output.errors.append(f"数据处理错误: {str(e)}")
            logger.error(f"Data error creating policy event: {e}", exc_info=True)
            record_exception(e, module="policy", is_handled=True)
        except IntegrityError as e:
            # Database integrity error
            output.errors.append("数据一致性错误: 事件可能已存在")
            logger.error(f"Integrity error creating policy event: {e}", exc_info=True)
            record_exception(e, module="policy", is_handled=True)
        except DatabaseError as e:
            # General database error
            output.errors.append(f"数据库错误: {str(e)}")
            logger.error(f"Database error creating policy event: {e}", exc_info=True)
            record_exception(e, module="policy", is_handled=True)
        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            # Unexpected error
            output.errors.append(f"系统错误: {str(e)}")
            logger.exception(f"Unexpected error creating policy event: {e}")
            record_exception(e, module="policy", is_handled=False)

        return output

    def _send_alert(self, event: PolicyEvent, previous_level: PolicyLevel | None) -> bool:
        """
        发送告警

        Args:
            event: 政策事件
            previous_level: 之前的档位

        Returns:
            bool: 是否成功发送
        """
        if not self.alert_service:
            logger.warning("Alert service not configured, skipping alert")
            return False

        response = get_policy_response(event.level)

        # 构建告警消息
        message_parts = [
            "**政策档位变更通知**",
            "",
            f"档位: {event.level.value} - {response.name}",
            f"标题: {event.title}",
            f"描述: {event.description}",
            f"日期: {event.event_date}",
            f"证据: {event.evidence_url}",
        ]

        if previous_level and previous_level != event.level:
            message_parts.append(f"上一次档位: {previous_level.value}")

        message_parts.append("")
        message_parts.append(f"**响应措施**: {response.market_action.value}")
        message_parts.append(f"现金调整: +{response.cash_adjustment}%")

        if response.signal_pause_hours:
            message_parts.append(f"信号暂停: {response.signal_pause_hours} 小时")

        message = "\n".join(message_parts)

        # 发送告警
        try:
            success = self.alert_service.send_alert(
                level="warning" if event.level == PolicyLevel.P2 else "critical",
                title=f"政策档位变更: {event.level.value}",
                message=message,
                metadata={
                    "event_date": event.event_date.isoformat(),
                    "level": event.level.value,
                    "title": event.title,
                    "evidence_url": event.evidence_url,
                },
            )
            if success:
                logger.info(f"Alert sent for policy level {event.level.value}")
            return success
        except ExternalServiceError as e:
            logger.warning(f"External service error sending alert: {e}")
            record_exception(e, module="policy", is_handled=True, service_name="alert")
            return False
        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.error(f"Failed to send alert: {e}")
            record_exception(e, module="policy", is_handled=True)
            return False


class GetPolicyStatusUseCase:
    """
    获取当前政策状态用例

    功能：
    1. 获取当前档位
    2. 获取响应配置
    3. 获取最新事件
    4. 提供操作建议
    """

    def __init__(self, event_store: EventStoreProtocol):
        """
        初始化用例

        Args:
            event_store: 事件存储仓储
        """
        self.event_store = event_store

    def execute(self, as_of_date: date | None = None) -> PolicyStatusOutput:
        """
        执行用例

        Args:
            as_of_date: 截止日期（None 表示最新）

        Returns:
            PolicyStatusOutput: 政策状态
        """
        if as_of_date is None:
            as_of_date = date.today()

        # 获取仓储实例以获取当前档位
        repo = self.event_store
        if isinstance(repo, DjangoPolicyRepository):
            current_level = repo.get_current_policy_level(as_of_date)
            is_intervention = repo.is_intervention_active(as_of_date)
            is_crisis = repo.is_crisis_mode(as_of_date)
        else:
            # 通用仓储，获取最新事件
            latest = self.event_store.get_latest_event(as_of_date)
            current_level = latest.level if latest else PolicyLevel.P0
            is_intervention = is_high_risk_level(current_level)
            is_crisis = current_level == PolicyLevel.P3

        # 获取响应配置
        response_config = get_policy_response(current_level)

        # 获取最新事件
        latest_event = self.event_store.get_latest_event(as_of_date)

        # 获取建议
        recommendations = get_recommendations_for_level(current_level)

        return PolicyStatusOutput(
            current_level=current_level,
            level_name=response_config.name,
            response_config=response_config,
            latest_event=latest_event,
            is_intervention_active=is_intervention,
            is_crisis_mode=is_crisis,
            recommendations=recommendations,
            as_of_date=as_of_date,
        )


class GetPolicyHistoryUseCase:
    """
    获取政策历史用例

    功能：
    1. 获取日期范围内的事件
    2. 统计各档位分布
    """

    def __init__(self, event_store: EventStoreProtocol):
        """
        初始化用例

        Args:
            event_store: 事件存储仓储
        """
        self.event_store = event_store

    def execute(
        self, start_date: date, end_date: date, level: PolicyLevel | None = None
    ) -> PolicyHistoryOutput:
        """
        执行用例

        Args:
            start_date: 起始日期
            end_date: 结束日期
            level: 筛选档位（可选）

        Returns:
            PolicyHistoryOutput: 历史数据
        """
        repo = self.event_store

        # 获取事件
        if level and isinstance(repo, DjangoPolicyRepository):
            events = repo.get_events_by_level(level, start_date, end_date)
        elif isinstance(repo, DjangoPolicyRepository):
            events = repo.get_events_in_range(start_date, end_date)
        else:
            # 通用仓储
            all_events = []
            # 注意：这里需要仓储支持范围查询，否则需要遍历
            events = all_events

        # 获取统计
        if isinstance(repo, DjangoPolicyRepository):
            stats = repo.get_policy_level_stats(start_date, end_date)
        else:
            stats = {"total": len(events), "by_level": {}}

        return PolicyHistoryOutput(
            events=events,
            total_count=len(events),
            level_stats=stats,
            start_date=start_date,
            end_date=end_date,
        )


class UpdatePolicyEventUseCase:
    """
    更新政策事件用例

    允许修改已记录的政策事件（需谨慎使用）
    """

    def __init__(
        self, event_store: EventStoreProtocol, alert_service: AlertServiceProtocol | None = None
    ):
        self.event_store = event_store
        self.alert_service = alert_service

    def execute(
        self,
        event_date: date,
        level: PolicyLevel,
        title: str,
        description: str,
        evidence_url: str,
        event_id: int | None = None,
    ) -> CreatePolicyEventOutput:
        """
        执行用例

        Args:
            event_date: 要更新的事件日期
            level: 新的档位
            title: 新的标题
            description: 新的描述
            evidence_url: 新的证据 URL
            event_id: 要更新的事件 ID（推荐，精确更新）

        Returns:
            CreatePolicyEventOutput: 输出结果
        """
        # 对 Django 仓储走明确更新路径，避免与”同日多事件”安全策略冲突
        if isinstance(self.event_store, DjangoPolicyRepository):
            output = CreatePolicyEventOutput(success=False, errors=[], warnings=[])
            try:
                # 使用 Repository 方法而非直接 ORM 访问
                existing = self.event_store.get_existing_for_update(
                    event_id=event_id, event_date=event_date
                )

                if existing:
                    if event_id is not None and existing["event_date"] != event_date:
                        output.errors.append(f"event_id={event_id} 与路径日期 {event_date} 不匹配")
                        return output
                else:
                    if event_id is not None:
                        output.errors.append(f"未找到 ID={event_id} 的事件")
                    else:
                        output.errors.append(f"未找到日期为 {event_date} 的事件")
                    return output

                updated_event = PolicyEvent(
                    event_date=event_date,
                    level=level,
                    title=title,
                    description=description,
                    evidence_url=evidence_url,
                )
                saved = self.event_store.save_event(updated_event, _update_id=existing["id"])
                output.success = True
                output.event = saved
                output.warnings.append("⚠️ 政策事件已更新")
                return output
            except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
                output.errors.append(f"更新失败: {str(e)}")
                logger.error(f"Failed to update policy event on {event_date}: {e}", exc_info=True)
                return output

        # 非 Django 仓储保持原流程
        create_input = CreatePolicyEventInput(
            event_date=event_date,
            level=level,
            title=title,
            description=description,
            evidence_url=evidence_url,
        )
        create_use_case = CreatePolicyEventUseCase(
            event_store=self.event_store, alert_service=self.alert_service
        )
        output = create_use_case.execute(create_input)
        if output.success:
            output.warnings.insert(0, "⚠️ 政策事件已更新")
        return output


class DeletePolicyEventUseCase:
    """
    删除政策事件用例

    谨慎使用！仅用于删除错误记录的事件。
    优先使用 event_id 删除单个事件，避免误删同日其他事件。
    """

    def __init__(self, event_store: EventStoreProtocol):
        self.event_store = event_store

    def execute(
        self, event_date: date | None = None, event_id: int | None = None
    ) -> tuple[bool, str]:
        """
        执行用例

        Args:
            event_date: 要删除的事件日期（会删除该日期所有事件，不推荐）
            event_id: 要删除的事件 ID（推荐，精确删除单个事件）

        Returns:
            tuple[bool, str]: (是否成功, 消息)
        """
        if isinstance(self.event_store, DjangoPolicyRepository):
            # 优先使用 ID 删除
            if event_id is not None:
                success = self.event_store.delete_event_by_id(event_id)
                if success:
                    return True, f"事件 ID={event_id} 已删除"
                else:
                    return False, f"未找到 ID={event_id} 的事件"
            elif event_date is not None:
                # 警告：按日期删除会删除同日所有事件
                events = self.event_store.get_events_by_date(event_date)
                count = len(events)
                success = self.event_store.delete_event(event_date)
                if success:
                    return True, f"已删除 {event_date} 的 {count} 个事件（警告：按日期删除）"
                else:
                    return False, f"未找到日期为 {event_date} 的事件"
            else:
                return False, "必须提供 event_date 或 event_id"
        else:
            return False, "当前仓储不支持删除操作"
