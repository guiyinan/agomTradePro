"""
Application Layer - Use Cases for Policy Management

本层负责编排业务逻辑，通过依赖注入使用 Infrastructure 层。
"""

import logging
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Protocol

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

from ..domain.entities import (
    AuditStatus,
    InfoCategory,
    PolicyEvent,
    PolicyLevel,
    ProxyConfig,
    RiskImpact,
    RSSItem,
    RSSSourceConfig,
)
from ..domain.rules import (
    DEFAULT_KEYWORD_RULES,
    PolicyResponse,
    analyze_policy_transition,
    get_policy_response,
    get_recommendations_for_level,
    is_high_risk_level,
    should_trigger_alert,
    validate_policy_event,
)
from ..infrastructure.adapters import FeedparserAdapter, create_content_extractor
from ..infrastructure.adapters.content_extractor import ContentExtractorError
from ..infrastructure.repositories import DjangoPolicyRepository, RSSRepository, WorkbenchRepository

logger = logging.getLogger(__name__)


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
        except Exception as e:
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
        except Exception as e:
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
        except Exception as e:
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
            except Exception as e:
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


# ========== RSS 相关用例 ==========


@dataclass
class FetchRSSInput:
    """RSS抓取输入 DTO"""

    source_id: int | None = None  # None表示抓取所有启用的源
    force_refetch: bool = False  # 是否强制重新抓取（忽略去重）


@dataclass
class FetchRSSOutput:
    """RSS抓取输出 DTO"""

    success: bool
    sources_processed: int
    total_items: int
    new_policy_events: int
    errors: list[str]
    details: list[dict[str, Any]]

    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.details is None:
            self.details = []


@dataclass
class RSSSourceDetail:
    """单个RSS源的抓取详情"""

    source_name: str
    items_count: int
    new_events_count: int
    duration: float
    status: str
    error_message: str = ""


class FetchRSSUseCase:
    """
    RSS抓取用例（增强版 - 集成AI分类）

    流程：
    1. 获取启用的RSS源配置
    2. 调用适配器抓取RSS内容
    3. 去重（根据link或guid）
    4. AI分类和结构化提取（可选）
    5. 关键词匹配作为fallback
    6. 根据置信度决定审核状态
    7. 转换为PolicyEvent并保存
    8. 记录抓取日志
    """

    def __init__(
        self,
        rss_repository: RSSRepository,
        policy_repository: DjangoPolicyRepository,
        alert_service: AlertServiceProtocol | None = None,
        ai_classifier: Any | None = None,  # PolicyClassifierProtocol
    ):
        """
        初始化用例

        Args:
            rss_repository: RSS仓储
            policy_repository: 政策仓储
            alert_service: 告警服务（可选）
            ai_classifier: AI分类器（可选）
        """
        self.rss_repository = rss_repository
        self.policy_repository = policy_repository
        self.alert_service = alert_service
        self.ai_classifier = ai_classifier

        # 适配器工厂
        self._adapter_factory = {
            "feedparser": FeedparserAdapter(),
        }

        # 内容提取器工厂
        self._extractor_factory = {
            "readability": create_content_extractor("readability"),
            "beautifulsoup": create_content_extractor("beautifulsoup"),
            "hybrid": create_content_extractor("hybrid"),
        }

        # 导入档位匹配服务
        from .services import PolicyLevelMatcher

        self._matcher_class = PolicyLevelMatcher

    def execute(self, input: FetchRSSInput) -> FetchRSSOutput:
        """
        执行RSS抓取

        Args:
            input: 输入 DTO

        Returns:
            FetchRSSOutput: 输出 DTO
        """
        output = FetchRSSOutput(
            success=False,
            sources_processed=0,
            total_items=0,
            new_policy_events=0,
            errors=[],
            details=[],
        )

        # 获取要抓取的源
        if input.source_id:
            sources = [self.rss_repository.get_source_by_id(input.source_id)]
            if not sources[0]:
                output.errors.append(f"RSS源 {input.source_id} 不存在")
                return output
        else:
            sources = self.rss_repository.get_active_sources()

        if not sources:
            output.errors.append("没有启用的RSS源")
            return output

        # 遍历抓取
        for source in sources:
            try:
                detail = self._fetch_single_source(source, input.force_refetch)
                output.details.append(detail)
                output.sources_processed += 1
                output.total_items += detail.get("items_count", 0)
                output.new_policy_events += detail.get("new_events_count", 0)

            except (ExternalServiceError, DataFetchError) as e:
                error_msg = f"RSS源 {source.name} 抓取失败（外部服务）: {str(e)}"
                output.errors.append(error_msg)
                logger.error(error_msg, exc_info=True)
                record_exception(e, module="policy", is_handled=True, service_name="rss")
            except (ValueError, TypeError) as e:
                error_msg = f"RSS源 {source.name} 配置错误: {str(e)}"
                output.errors.append(error_msg)
                logger.error(error_msg, exc_info=True)
                record_exception(e, module="policy", is_handled=True)
            except Exception as e:
                error_msg = f"RSS源 {source.name} 抓取失败（未预期）: {str(e)}"
                output.errors.append(error_msg)
                logger.exception(error_msg)
                record_exception(e, module="policy", is_handled=False)

        output.success = output.sources_processed > 0
        return output

    def _fetch_single_source(
        self, source: Any, force_refetch: bool
    ) -> dict[str, Any]:
        """
        抓取单个RSS源（增强版 - 集成AI分类）

        Args:
            source: RSS源ORM对象
            force_refetch: 是否强制重新抓取

        Returns:
            Dict: 抓取详情
        """
        start_time = time.time()

        # 1. 转换为Domain实体
        source_config = self._orm_to_domain_config(source)

        # 2. 获取适配器
        adapter = self._adapter_factory.get(source.parser_type)
        if not adapter:
            raise ValueError(f"Unknown parser type: {source.parser_type}")

        # 3. 抓取RSS
        items = adapter.fetch(source_config)

        # 4. 获取关键词规则（作为fallback）
        keyword_rules = self.rss_repository.get_active_keyword_rules(category=source.category)
        if not keyword_rules:
            keyword_rules = DEFAULT_KEYWORD_RULES

        matcher = self._matcher_class(keyword_rules)

        # 5. 处理每个条目
        new_events_count = 0
        for item in items:
            policy_log_record = None
            try:
                # 去重检查
                if not force_refetch and self.rss_repository.is_item_exists(item.link, item.guid):
                    logger.debug(f"Item already exists, skipping: {item.link}")
                    continue

                # 阶段1：先落库原始记录，保证后续处理失败也不会丢数据
                policy_log_record = self.policy_repository.create_raw_rss_policy_log(
                    event_date=item.pub_date.date(),
                    title=item.title,
                    description=item.description or item.title,
                    evidence_url=item.link,
                    rss_source_id=source.id,
                    rss_item_guid=item.guid or item.link,
                )
                new_events_count += 1

                # ========== AI分类（新功能） ==========
                classification_result = None
                info_category = InfoCategory.OTHER
                audit_status = AuditStatus.PENDING_REVIEW
                ai_confidence = None
                structured_data = None
                risk_impact = RiskImpact.UNKNOWN

                # 尝试AI分类
                if self.ai_classifier:
                    try:
                        classification_result = self.ai_classifier.classify_rss_item(item)

                        if classification_result.success:
                            info_category = classification_result.info_category
                            audit_status = classification_result.audit_status
                            ai_confidence = classification_result.ai_confidence
                            structured_data = classification_result.structured_data
                            risk_impact = classification_result.risk_impact

                            logger.info(
                                f"AI classified {item.title}: "
                                f"category={info_category.value}, "
                                f"confidence={ai_confidence}, "
                                f"audit_status={audit_status.value}"
                            )
                        else:
                            logger.warning(
                                f"AI classification failed for {item.title}: "
                                f"{classification_result.error_message}"
                            )
                    except AIServiceError as e:
                        logger.warning(f"AI service error for {item.title}: {e}")
                        record_exception(
                            e, module="policy", is_handled=True, service_name="ai_classification"
                        )
                    except Exception as e:
                        logger.error(f"AI classification error for {item.title}: {e}")
                        record_exception(e, module="policy", is_handled=True)

                # ========== 确定政策档位 ==========
                level = None

                # 优先使用 AI 推荐的档位
                if (
                    classification_result
                    and classification_result.success
                    and classification_result.policy_level
                ):
                    level = classification_result.policy_level
                    logger.info(f"Using AI recommended level: {level.value} for: {item.title}")

                # AI 未推荐档位时，使用关键词匹配作为 fallback
                if not level:
                    level = matcher.match(item)
                    if level:
                        info_category = InfoCategory.MACRO  # 默认为宏观
                        audit_status = AuditStatus.PENDING_REVIEW
                        ai_confidence = 0.5  # 关键词匹配的默认置信度

                # 如果 AI 和关键词都没匹配到 level，使用默认值 PENDING（待分类，后续 AI 打标签）
                if not level:
                    level = PolicyLevel.PENDING
                    info_category = InfoCategory.OTHER
                    audit_status = AuditStatus.PENDING_REVIEW
                    ai_confidence = None
                    logger.info(
                        f"No policy level matched, using PENDING (unclassified) for: {item.title}"
                    )

                # 内容提取（如果启用）
                description = item.description or item.title
                extracted_content = None

                if source_config.extract_content:
                    try:
                        extractor = self._extractor_factory.get("hybrid")
                        if extractor:
                            extracted_content = extractor.extract(
                                url=item.link,
                                proxy_config=source_config.proxy_config,
                                timeout=source.timeout_seconds,
                            )
                            if extracted_content:
                                description = extracted_content[:5000]

                                # 如果AI提取失败但提取了内容，可以重试AI分类
                                if classification_result and not classification_result.success:
                                    try:
                                        classification_result = (
                                            self.ai_classifier.classify_rss_item(
                                                item, content=extracted_content
                                            )
                                        )
                                        if classification_result.success:
                                            info_category = classification_result.info_category
                                            audit_status = classification_result.audit_status
                                            ai_confidence = classification_result.ai_confidence
                                            structured_data = classification_result.structured_data
                                            risk_impact = classification_result.risk_impact
                                    except AIServiceError as e:
                                        logger.warning(
                                            f"AI classification failed (service error): {e}"
                                        )
                                        record_exception(
                                            e,
                                            module="policy",
                                            is_handled=True,
                                            service_name="ai_classification",
                                        )
                                    except Exception as e:
                                        logger.warning(
                                            f"AI classification failed (unexpected): {e}"
                                        )
                                        record_exception(e, module="policy", is_handled=True)
                    except ContentExtractorError as e:
                        logger.warning(f"Failed to extract content from {item.link}: {e}")

                # 转换结构化数据为字典（使用空字典而非 None）
                structured_data_dict = {}
                if structured_data:
                    structured_data_dict = asdict(structured_data)

                # 保存到PolicyLog（扩展版）
                # 准备额外字段
                extra_fields = {
                    "info_category": info_category.value,
                    "audit_status": audit_status.value,
                    "ai_confidence": ai_confidence,
                    "structured_data": structured_data_dict,
                    "rss_source_id": source.id,
                    "rss_item_guid": item.guid or item.link,
                    "risk_impact": risk_impact.value,
                    "processing_metadata": classification_result.processing_metadata
                    if classification_result
                    else {},
                }

                # 阶段2：处理完成后更新已落库记录
                self.policy_repository.update_policy_log_fields(
                    policy_log_record["id"],
                    level=level.value,
                    description=description,
                    info_category=extra_fields["info_category"],
                    audit_status=extra_fields["audit_status"],
                    ai_confidence=extra_fields["ai_confidence"],
                    structured_data=extra_fields["structured_data"],
                    risk_impact=extra_fields["risk_impact"],
                    processing_metadata={
                        **extra_fields["processing_metadata"],
                        "processing_stage": "processed",
                    },
                )

                # ========== 审核队列管理 ==========
                # 如果需要人工审核，加入审核队列（使用 get_or_create 避免重复）
                if audit_status == AuditStatus.PENDING_REVIEW and policy_log_record:
                    # 根据风险级别设置优先级
                    if level in [PolicyLevel.P2, PolicyLevel.P3]:
                        priority = "urgent"
                    elif risk_impact == RiskImpact.HIGH_RISK:
                        priority = "high"
                    else:
                        priority = "normal"

                    queue_result = self.policy_repository.ensure_audit_queue_item(
                        policy_log_id=policy_log_record["id"],
                        priority=priority,
                    )
                    if queue_result["created"]:
                        logger.info(
                            f"Added policy {policy_log_record['id']} to audit queue "
                            f"(priority: {priority})"
                        )

                logger.info(
                    f"Created policy event from RSS: {level.value} - {item.title} "
                    f"(category={info_category.value}, audit={audit_status.value})"
                )

                # 如果是P2/P3档位，发送告警
                if level in [PolicyLevel.P2, PolicyLevel.P3] and self.alert_service:
                    self._send_alert_for_rss_event_enhanced(
                        level=level,
                        title=item.title,
                        description=description[:200],
                        event_date=item.pub_date.date(),
                        evidence_url=item.link,
                        info_category=info_category,
                        risk_impact=risk_impact,
                        structured_data=structured_data_dict,
                    )

            except Exception as e:
                # Processing error - keep pending raw record and continue
                logger.warning(
                    f"Failed to process RSS item {item.link} (error): {e}, keeping pending raw record"
                )
                record_exception(e, module="policy", is_handled=True)
                try:
                    if policy_log_record:
                        self.policy_repository.append_policy_log_processing_metadata(
                            policy_log_record["id"],
                            {
                                "error": str(e),
                                "error_type": type(e).__name__,
                                "saved_as_pending": True,
                                "processing_stage": "failed",
                            },
                        )
                        logger.info(f"Kept pending RSS item (processing failed): {item.title}")
                    else:
                        self.policy_repository.create_raw_rss_policy_log(
                            event_date=item.pub_date.date(),
                            title=item.title,
                            description=item.description or item.title,
                            evidence_url=item.link,
                            rss_source_id=source.id,
                            rss_item_guid=item.guid or item.link,
                            processing_metadata={
                                "error": str(e),
                                "saved_as_pending": True,
                                "processing_stage": "failed",
                            },
                        )
                        new_events_count += 1
                        logger.info(f"Saved pending RSS item after early failure: {item.title}")
                except Exception as save_error:
                    logger.error(f"Failed to save pending RSS item {item.link}: {save_error}")
                continue

        # 6. 记录日志
        duration = time.time() - start_time

        # 确定抓取状态
        if len(items) == 0:
            # 没有抓取到任何条目 - 可能是RSS源问题
            fetch_status = "error"
            error_msg = "No entries found in RSS feed - feed may be invalid or inaccessible"
            logger.error(f"RSS源 {source.name} 抓取失败: {error_msg}")
        elif new_events_count == 0:
            # 抓取到了条目但都是重复的
            fetch_status = "partial"
            error_msg = f"Fetched {len(items)} items but all were duplicates"
            logger.info(f"RSS源 {source.name}: {error_msg}")
        else:
            fetch_status = "success"
            error_msg = None

        self.rss_repository.save_fetch_log(
            source_id=source.id,
            status=fetch_status,
            items_count=len(items),
            new_items_count=new_events_count,
            error_message=error_msg or "",
            duration=duration,
        )

        # 7. 更新源状态
        self.rss_repository.update_source_last_fetch(source.id, fetch_status, error_msg=error_msg)

        return {
            "source_name": source.name,
            "source_id": source.id,
            "items_count": len(items),
            "new_events_count": new_events_count,
            "duration": duration,
            "status": fetch_status,
            "error": error_msg,
        }

    def _orm_to_domain_config(self, orm_obj: Any) -> RSSSourceConfig:
        """ORM转Domain实体"""
        proxy_config = None
        if orm_obj.proxy_enabled:
            proxy_config = ProxyConfig(
                host=orm_obj.proxy_host,
                port=orm_obj.proxy_port,
                username=orm_obj.proxy_username or None,
                password=orm_obj.proxy_password or None,
                proxy_type=orm_obj.proxy_type,
            )

        return RSSSourceConfig(
            name=orm_obj.name,
            url=orm_obj.get_effective_url(),
            category=orm_obj.category,
            is_active=orm_obj.is_active,
            fetch_interval_hours=orm_obj.fetch_interval_hours,
            extract_content=orm_obj.extract_content,
            proxy_config=proxy_config,
            timeout_seconds=orm_obj.timeout_seconds,
            retry_times=orm_obj.retry_times,
            rsshub_enabled=orm_obj.rsshub_enabled,
            rsshub_route_path=orm_obj.rsshub_route_path or "",
            rsshub_use_global_config=orm_obj.rsshub_use_global_config,
            rsshub_custom_base_url=orm_obj.rsshub_custom_base_url or "",
            rsshub_custom_access_key=orm_obj.rsshub_custom_access_key or "",
            rsshub_format=orm_obj.rsshub_format or "",
        )

    def _send_alert_for_rss_event(self, event: PolicyEvent) -> bool:
        """为RSS触发的政策事件发送告警"""
        if not self.alert_service:
            return False

        response = get_policy_response(event.level)

        message = (
            f"**RSS检测到新政策事件**\n"
            f"\n"
            f"档位: {event.level.value} - {response.name}\n"
            f"标题: {event.title}\n"
            f"描述: {event.description}\n"
            f"日期: {event.event_date}\n"
            f"来源: {event.evidence_url}\n"
        )

        try:
            return self.alert_service.send_alert(
                level="warning" if event.level == PolicyLevel.P2 else "critical",
                title=f"RSS新政策事件: {event.level.value}",
                message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send alert for RSS event: {e}")
            return False

    def _send_alert_for_rss_event_enhanced(
        self,
        level: PolicyLevel,
        title: str,
        description: str,
        event_date: date,
        evidence_url: str,
        info_category: InfoCategory,
        risk_impact: RiskImpact,
        structured_data: dict[str, Any] | None = None,
    ) -> bool:
        """为RSS触发的政策事件发送增强告警"""
        if not self.alert_service:
            return False

        response = get_policy_response(level)

        message = f"""**RSS检测到新政策事件**

档位: {level.value} - {response.name}
分类: {info_category.value}
风险影响: {risk_impact.value}
AI置信度: N/A

标题: {title}
描述: {description}
日期: {event_date}
来源: {evidence_url}
"""

        # 如果有结构化数据，添加摘要信息
        if structured_data:
            message += "\n**结构化信息**:\n"
            if structured_data.get("summary"):
                message += f"摘要: {structured_data['summary']}\n"
            if structured_data.get("affected_sectors"):
                message += f"影响板块: {', '.join(structured_data['affected_sectors'])}\n"
            if structured_data.get("sentiment"):
                message += f"情绪倾向: {structured_data['sentiment']}\n"

        try:
            return self.alert_service.send_alert(
                level="warning" if level == PolicyLevel.P2 else "critical",
                title=f"RSS新政策事件: {level.value}",
                message=message,
            )
        except Exception as e:
            logger.error(f"Failed to send alert for RSS event: {e}")
            return False


# ========== 审核工作流用例 ==========


@dataclass
class ReviewPolicyItemInput:
    """审核政策条目的输入"""

    policy_log_id: int
    approved: bool
    reviewer: Any  # Django User model
    notes: str = ""
    modifications: dict[str, Any] | None = None  # 允许审核者修改AI提取的数据


@dataclass
class ReviewPolicyItemOutput:
    """审核政策条目的输出"""

    success: bool
    audit_status: AuditStatus
    message: str
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class GetAuditQueueUseCase:
    """获取审核队列用例"""

    def __init__(
        self,
        policy_repository: DjangoPolicyRepository,
        workbench_repo: WorkbenchRepository | None = None,
    ):
        """
        初始化用例

        Args:
            policy_repository: 政策仓储
        """
        self.policy_repository = policy_repository
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(
        self,
        user: Any,
        status: str = "pending_review",
        priority: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        获取待审核的政策列表

        Args:
            user: 当前用户
            status: 审核状态过滤
            priority: 优先级过滤
            limit: 返回数量限制

        Returns:
            List[Dict]: 待审核政策列表
        """
        return self.workbench_repo.list_audit_queue_items(
            assigned_user_id=user.id,
            status=status,
            priority=priority,
            limit=limit,
        )


class ReviewPolicyItemUseCase:
    """审核政策条目用例"""

    def __init__(
        self,
        policy_repository: DjangoPolicyRepository,
        alert_service: AlertServiceProtocol | None = None,
        workbench_repo: WorkbenchRepository | None = None,
    ):
        self.policy_repository = policy_repository
        self.alert_service = alert_service
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input: ReviewPolicyItemInput) -> ReviewPolicyItemOutput:
        """
        审核政策条目

        Args:
            input: 审核输入

        Returns:
            ReviewPolicyItemOutput: 审核结果
        """
        output = ReviewPolicyItemOutput(
            success=False, audit_status=AuditStatus.PENDING_REVIEW, message=""
        )

        try:
            review_result = self.workbench_repo.review_policy_item(
                policy_log_id=input.policy_log_id,
                approved=input.approved,
                reviewer_id=input.reviewer.id,
                notes=input.notes,
                modifications=input.modifications,
            )
            if review_result is None:
                output.errors.append(f"政策日志 {input.policy_log_id} 不存在")
                logger.error(f"Policy log {input.policy_log_id} not found")
                return output

            output.audit_status = AuditStatus(review_result["audit_status"])
            output.message = "政策已审核通过" if input.approved else "政策已拒绝"
            output.success = True

            logger.info(
                f"Policy {input.policy_log_id} "
                f"{'approved' if input.approved else 'rejected'} by {input.reviewer.username}"
            )

        except Exception as e:
            output.errors.append(f"审核失败: {str(e)}")
            logger.error(f"Failed to review policy {input.policy_log_id}: {e}", exc_info=True)

        return output


class BulkReviewUseCase:
    """批量审核用例"""

    def __init__(self, review_use_case: ReviewPolicyItemUseCase):
        self.review_use_case = review_use_case

    def execute(
        self, policy_log_ids: list[int], approved: bool, reviewer: Any, notes: str = ""
    ) -> dict[str, Any]:
        """
        批量审核政策条目

        Args:
            policy_log_ids: 政策日志ID列表
            approved: 是否通过
            reviewer: 审核人
            notes: 审核备注

        Returns:
            Dict: 批量审核结果统计
        """
        results = {"total": len(policy_log_ids), "success": 0, "failed": 0, "errors": []}

        for policy_log_id in policy_log_ids:
            input_dto = ReviewPolicyItemInput(
                policy_log_id=policy_log_id, approved=approved, reviewer=reviewer, notes=notes
            )

            output = self.review_use_case.execute(input_dto)

            if output.success:
                results["success"] += 1
            else:
                results["failed"] += 1
                results["errors"].extend(output.errors)

        return results


class AutoAssignAuditsUseCase:
    """自动分配审核任务用例"""

    def __init__(self, workbench_repo: WorkbenchRepository | None = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, max_per_user: int = 10) -> dict[str, Any]:
        """
        自动将待审核的政策分配给审核人员

        Args:
            max_per_user: 每个用户最多分配数量

        Returns:
            Dict: 分配结果统计
        """
        from django.utils import timezone

        unassigned_ids = self.workbench_repo.list_unassigned_audit_queue_ids()
        auditor_ids = self.workbench_repo.list_staff_auditor_ids()

        if not auditor_ids:
            logger.warning("No auditors found with staff privileges")
            return {"assigned": 0, "remaining": len(unassigned_ids)}

        assignment_counts = self.workbench_repo.get_pending_assignment_counts(auditor_ids)
        assigned_count = 0
        auditor_count = len(auditor_ids)
        for idx, queue_id in enumerate(unassigned_ids):
            assigned = False
            for offset in range(auditor_count):
                auditor_id = auditor_ids[(idx + offset) % auditor_count]
                current_assigned = assignment_counts.get(auditor_id, 0)
                if current_assigned >= max_per_user:
                    continue
                if self.workbench_repo.assign_audit_queue_item(
                    queue_id=queue_id,
                    auditor_id=auditor_id,
                    assigned_at=timezone.now(),
                ):
                    assignment_counts[auditor_id] = current_assigned + 1
                    assigned_count += 1
                assigned = True
                break
            if not assigned:
                logger.debug(f"No available auditor slot for queue item {queue_id}")

        logger.info(f"Auto-assigned {assigned_count} policy reviews to {auditor_count} auditors")

        return {
            "assigned": assigned_count,
            "remaining": len(unassigned_ids) - assigned_count,
            "auditors": auditor_count,
        }


# ============================================================
# 工作台 Use Cases
# ============================================================

from ..domain.entities import (
    EventType,
    GateLevel,
    HeatSentimentScore,
    IngestionConfig,
    SentimentGateThresholds,
    WorkbenchEvent,
    WorkbenchSummary,
)
from ..domain.rules import (
    calculate_gate_level,
    can_event_affect_policy_level,
    get_max_position_cap,
    is_sla_exceeded,
    should_auto_approve,
)
@dataclass
class WorkbenchSummaryInput:
    """工作台概览输入 DTO"""

    pass


@dataclass
class WorkbenchSummaryOutput:
    """工作台概览输出 DTO"""

    success: bool
    summary: WorkbenchSummary | None = None
    error: str | None = None


class GetWorkbenchSummaryUseCase:
    """获取工作台概览用例"""

    def __init__(
        self,
        workbench_repo: WorkbenchRepository | None = None,
        policy_repo: DjangoPolicyRepository | None = None,
    ):
        self.workbench_repo = workbench_repo or WorkbenchRepository()
        self.policy_repo = policy_repo or DjangoPolicyRepository()

    def execute(self, input_dto: WorkbenchSummaryInput = None) -> WorkbenchSummaryOutput:
        """
        获取工作台概览数据

        Returns:
            WorkbenchSummaryOutput: 包含双闸状态、待审核数、SLA超时数等
        """
        try:
            # 获取政策档位（仅已生效的政策事件）
            policy_level = self.policy_repo.get_current_policy_level()

            # 获取触发政策档位的事件
            latest_policy_event = self.workbench_repo.get_latest_effective_policy_title()

            # 获取全局热度与情绪
            global_heat, global_sentiment = self.workbench_repo.get_global_heat_sentiment()

            # 计算闸门等级
            gate_config = self.workbench_repo.get_gate_config("all")
            global_gate_level = None
            if gate_config and global_heat is not None:
                thresholds = SentimentGateThresholds(
                    heat_l1_threshold=gate_config.heat_l1_threshold,
                    heat_l2_threshold=gate_config.heat_l2_threshold,
                    heat_l3_threshold=gate_config.heat_l3_threshold,
                    sentiment_l1_threshold=gate_config.sentiment_l1_threshold,
                    sentiment_l2_threshold=gate_config.sentiment_l2_threshold,
                    sentiment_l3_threshold=gate_config.sentiment_l3_threshold,
                )
                global_gate_level = calculate_gate_level(global_heat, global_sentiment, thresholds)

            # 获取配置用于 SLA 计算
            ingestion_config = self.workbench_repo.get_ingestion_config()

            # 获取统计数
            pending_review_count = self.workbench_repo.get_pending_review_count()
            sla_exceeded_count = self.workbench_repo.get_sla_exceeded_count(
                p23_sla_hours=ingestion_config.p23_sla_hours,
                normal_sla_hours=ingestion_config.normal_sla_hours,
            )
            effective_today_count = self.workbench_repo.get_effective_today_count()

            # 获取最后抓取时间
            last_fetch_at = self.workbench_repo.get_last_fetch_at()

            summary = WorkbenchSummary(
                policy_level=policy_level,
                policy_level_event=latest_policy_event,
                global_heat_score=global_heat,
                global_sentiment_score=global_sentiment,
                global_gate_level=global_gate_level,
                pending_review_count=pending_review_count,
                sla_exceeded_count=sla_exceeded_count,
                effective_today_count=effective_today_count,
                last_fetch_at=last_fetch_at,
            )

            return WorkbenchSummaryOutput(success=True, summary=summary)

        except Exception as e:
            logger.exception(f"Failed to get workbench summary: {e}")
            return WorkbenchSummaryOutput(success=False, error=str(e))


@dataclass
class WorkbenchItemsInput:
    """工作台事件列表输入 DTO"""

    tab: str = "pending"  # pending, effective, all
    event_type: str | None = None
    level: str | None = None
    gate_level: str | None = None
    asset_class: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    search: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class WorkbenchItemsOutput:
    """工作台事件列表输出 DTO"""

    success: bool
    items: list[dict[str, Any]] = None
    total: int = 0
    error: str | None = None


class GetWorkbenchItemsUseCase:
    """获取工作台事件列表用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: WorkbenchItemsInput) -> WorkbenchItemsOutput:
        """
        获取工作台事件列表

        Args:
            input_dto: 筛选参数

        Returns:
            WorkbenchItemsOutput: 事件列表
        """
        try:
            result = self.workbench_repo.list_workbench_items(
                tab=input_dto.tab,
                event_type=input_dto.event_type,
                level=input_dto.level,
                gate_level=input_dto.gate_level,
                asset_class=input_dto.asset_class,
                start_date=input_dto.start_date,
                end_date=input_dto.end_date,
                search=input_dto.search,
                limit=input_dto.limit,
                offset=input_dto.offset,
            )
            return WorkbenchItemsOutput(
                success=True,
                items=result["items"],
                total=result["total"],
            )

        except Exception as e:
            logger.exception(f"Failed to get workbench items: {e}")
            return WorkbenchItemsOutput(success=False, error=str(e))


@dataclass
class ApproveEventInput:
    """审核通过输入 DTO"""

    event_id: int
    user_id: int
    reason: str = ""


@dataclass
class ApproveEventOutput:
    """审核通过输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class ApproveEventUseCase:
    """审核通过用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: ApproveEventInput) -> ApproveEventOutput:
        """
        审核通过事件

        Args:
            input_dto: 包含 event_id, user_id, reason

        Returns:
            ApproveEventOutput: 操作结果
        """
        try:
            event = self.workbench_repo.approve_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} approved by user {input_dto.user_id}")
                return ApproveEventOutput(success=True, event_id=event.id)
            else:
                return ApproveEventOutput(success=False, error="Event not found")

        except Exception as e:
            logger.exception(f"Failed to approve event: {e}")
            return ApproveEventOutput(success=False, error=str(e))


@dataclass
class RejectEventInput:
    """审核拒绝输入 DTO"""

    event_id: int
    user_id: int
    reason: str


@dataclass
class RejectEventOutput:
    """审核拒绝输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class RejectEventUseCase:
    """审核拒绝用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: RejectEventInput) -> RejectEventOutput:
        """
        审核拒绝事件

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）

        Returns:
            RejectEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return RejectEventOutput(success=False, error="拒绝原因不能为空")

        try:
            event = self.workbench_repo.reject_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} rejected by user {input_dto.user_id}")
                return RejectEventOutput(success=True, event_id=event.id)
            else:
                return RejectEventOutput(success=False, error="Event not found")

        except Exception as e:
            logger.exception(f"Failed to reject event: {e}")
            return RejectEventOutput(success=False, error=str(e))


@dataclass
class RollbackEventInput:
    """回滚生效输入 DTO"""

    event_id: int
    user_id: int
    reason: str


@dataclass
class RollbackEventOutput:
    """回滚生效输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class RollbackEventUseCase:
    """回滚生效用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: RollbackEventInput) -> RollbackEventOutput:
        """
        回滚事件生效状态

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）

        Returns:
            RollbackEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return RollbackEventOutput(success=False, error="回滚原因不能为空")

        try:
            event = self.workbench_repo.rollback_event(
                event_id=input_dto.event_id, user_id=input_dto.user_id, reason=input_dto.reason
            )

            if event:
                logger.info(f"Event {input_dto.event_id} rolled back by user {input_dto.user_id}")
                return RollbackEventOutput(success=True, event_id=event.id)
            else:
                return RollbackEventOutput(success=False, error="Event not found")

        except Exception as e:
            logger.exception(f"Failed to rollback event: {e}")
            return RollbackEventOutput(success=False, error=str(e))


@dataclass
class OverrideEventInput:
    """临时豁免输入 DTO"""

    event_id: int
    user_id: int
    reason: str
    new_level: str | None = None


@dataclass
class OverrideEventOutput:
    """临时豁免输出 DTO"""

    success: bool
    event_id: int | None = None
    error: str | None = None


class OverrideEventUseCase:
    """临时豁免用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: OverrideEventInput) -> OverrideEventOutput:
        """
        临时豁免事件

        Args:
            input_dto: 包含 event_id, user_id, reason（必填）, new_level（可选）

        Returns:
            OverrideEventOutput: 操作结果
        """
        if not input_dto.reason or not input_dto.reason.strip():
            return OverrideEventOutput(success=False, error="豁免原因不能为空")

        try:
            event = self.workbench_repo.override_event(
                event_id=input_dto.event_id,
                user_id=input_dto.user_id,
                reason=input_dto.reason,
                new_level=input_dto.new_level,
            )

            if event:
                logger.info(f"Event {input_dto.event_id} overridden by user {input_dto.user_id}")
                return OverrideEventOutput(success=True, event_id=event.id)
            else:
                return OverrideEventOutput(success=False, error="Event not found")

        except Exception as e:
            logger.exception(f"Failed to override event: {e}")
            return OverrideEventOutput(success=False, error=str(e))


@dataclass
class SentimentGateStateInput:
    """热点情绪闸门状态输入 DTO"""

    asset_class: str = "all"


@dataclass
class SentimentGateStateOutput:
    """热点情绪闸门状态输出 DTO"""

    success: bool
    asset_class: str | None = None
    gate_level: str | None = None
    heat_score: float | None = None
    sentiment_score: float | None = None
    max_position_cap: float | None = None
    thresholds: dict[str, float] | None = None
    error: str | None = None


class GetSentimentGateStateUseCase:
    """获取热点情绪闸门状态用例"""

    def __init__(self, workbench_repo: WorkbenchRepository = None):
        self.workbench_repo = workbench_repo or WorkbenchRepository()

    def execute(self, input_dto: SentimentGateStateInput) -> SentimentGateStateOutput:
        """
        获取指定资产类的闸门状态

        Args:
            input_dto: 包含 asset_class

        Returns:
            SentimentGateStateOutput: 闸门状态
        """
        try:
            # 获取闸门配置
            gate_config = self.workbench_repo.get_gate_config(input_dto.asset_class)
            if not gate_config:
                return SentimentGateStateOutput(
                    success=False,
                    error=f"No gate config found for asset class: {input_dto.asset_class}",
                )

            # 获取该资产类的热度与情绪（简化：使用全局数据）
            global_heat, global_sentiment = self.workbench_repo.get_global_heat_sentiment()

            # 计算闸门等级
            thresholds = SentimentGateThresholds(
                heat_l1_threshold=gate_config.heat_l1_threshold,
                heat_l2_threshold=gate_config.heat_l2_threshold,
                heat_l3_threshold=gate_config.heat_l3_threshold,
                sentiment_l1_threshold=gate_config.sentiment_l1_threshold,
                sentiment_l2_threshold=gate_config.sentiment_l2_threshold,
                sentiment_l3_threshold=gate_config.sentiment_l3_threshold,
            )
            gate_level = calculate_gate_level(global_heat, global_sentiment, thresholds)

            # 获取仓位上限
            cap_config = {
                "max_position_cap_l2": gate_config.max_position_cap_l2,
                "max_position_cap_l3": gate_config.max_position_cap_l3,
            }
            max_cap = get_max_position_cap(gate_level, cap_config)

            return SentimentGateStateOutput(
                success=True,
                asset_class=input_dto.asset_class,
                gate_level=gate_level.value if gate_level else None,
                heat_score=global_heat,
                sentiment_score=global_sentiment,
                max_position_cap=max_cap,
                thresholds={
                    "heat_l1": gate_config.heat_l1_threshold,
                    "heat_l2": gate_config.heat_l2_threshold,
                    "heat_l3": gate_config.heat_l3_threshold,
                    "sentiment_l1": gate_config.sentiment_l1_threshold,
                    "sentiment_l2": gate_config.sentiment_l2_threshold,
                    "sentiment_l3": gate_config.sentiment_l3_threshold,
                },
            )

        except Exception as e:
            logger.exception(f"Failed to get sentiment gate state: {e}")
            return SentimentGateStateOutput(success=False, error=str(e))
