"""
Application Layer - Use Cases for Policy Management

本层负责编排业务逻辑，通过依赖注入使用 Infrastructure 层。
"""

from dataclasses import dataclass, asdict
from datetime import date, datetime
from typing import List, Optional, Protocol, Dict, Any
import logging
import time

from ..domain.entities import (
    PolicyEvent, PolicyLevel, RSSItem, RSSSourceConfig, ProxyConfig,
    InfoCategory, AuditStatus, RiskImpact
)
from ..domain.rules import (
    validate_policy_event,
    should_trigger_alert,
    get_policy_response,
    analyze_policy_transition,
    get_recommendations_for_level,
    is_high_risk_level,
    DEFAULT_KEYWORD_RULES,
    PolicyResponse,
)
from ..infrastructure.repositories import DjangoPolicyRepository, RSSRepository
from ..infrastructure.models import RSSSourceConfigModel, PolicyAuditQueue, PolicyLog
from ..infrastructure.adapters import FeedparserAdapter, create_content_extractor
from ..infrastructure.adapters.content_extractor import ContentExtractorError

logger = logging.getLogger(__name__)


@dataclass
class GetCurrentPolicyResponse:
    """Backward-compatible response for current policy query."""
    success: bool
    policy_level: Optional[PolicyLevel] = None
    error: Optional[str] = None


class GetCurrentPolicyUseCase:
    """Backward-compatible use case: fetch current policy level."""

    def __init__(self, repository: DjangoPolicyRepository):
        self.repository = repository

    def execute(self) -> GetCurrentPolicyResponse:
        try:
            level = self.repository.get_current_policy_level(date.today())
            return GetCurrentPolicyResponse(success=True, policy_level=level)
        except Exception as e:
            logger.error("GetCurrentPolicyUseCase failed: %s", e, exc_info=True)
            return GetCurrentPolicyResponse(success=False, policy_level=None, error=str(e))


# Protocol 定义 - 用于依赖注入
class AlertServiceProtocol(Protocol):
    """告警服务协议"""

    def send_alert(
        self,
        level: str,
        title: str,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """发送告警"""
        ...


class EventStoreProtocol(Protocol):
    """事件存储协议"""

    def save_event(self, event: PolicyEvent) -> PolicyEvent:
        """保存事件"""
        ...

    def get_latest_event(self, before_date: Optional[date] = None) -> Optional[PolicyEvent]:
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
    event: Optional[PolicyEvent] = None
    errors: List[str] = None
    warnings: List[str] = None
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
    latest_event: Optional[PolicyEvent]
    is_intervention_active: bool
    is_crisis_mode: bool
    recommendations: List[str]
    as_of_date: date


@dataclass
class PolicyHistoryOutput:
    """政策历史输出 DTO"""
    events: List[PolicyEvent]
    total_count: int
    level_stats: Dict[str, Any]
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
        self,
        event_store: EventStoreProtocol,
        alert_service: Optional[AlertServiceProtocol] = None
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
                evidence_url=input.evidence_url
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
                evidence_url=input.evidence_url
            )

            # 3. 获取之前的档位
            previous_event = self.event_store.get_latest_event(
                before_date=input.event_date
            )
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
                alert_triggered = self._send_alert(
                    event=saved_event,
                    previous_level=previous_level
                )

            # 7. 添加建议
            recommendations = get_recommendations_for_level(input.level)
            output.warnings.extend(recommendations)

            output.success = True
            output.alert_triggered = alert_triggered

            logger.info(
                f"Policy event created successfully: {input.level.value} - {input.title}"
            )

        except Exception as e:
            output.errors.append(f"系统错误: {str(e)}")
            logger.error(f"Failed to create policy event: {e}", exc_info=True)

        return output

    def _send_alert(
        self,
        event: PolicyEvent,
        previous_level: Optional[PolicyLevel]
    ) -> bool:
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
            f"**政策档位变更通知**",
            f"",
            f"档位: {event.level.value} - {response.name}",
            f"标题: {event.title}",
            f"描述: {event.description}",
            f"日期: {event.event_date}",
            f"证据: {event.evidence_url}",
        ]

        if previous_level and previous_level != event.level:
            message_parts.append(f"上一次档位: {previous_level.value}")

        message_parts.append(f"")
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
                }
            )
            if success:
                logger.info(f"Alert sent for policy level {event.level.value}")
            return success
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")
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

    def execute(self, as_of_date: Optional[date] = None) -> PolicyStatusOutput:
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
            as_of_date=as_of_date
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
        self,
        start_date: date,
        end_date: date,
        level: Optional[PolicyLevel] = None
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
            end_date=end_date
        )


class UpdatePolicyEventUseCase:
    """
    更新政策事件用例

    允许修改已记录的政策事件（需谨慎使用）
    """

    def __init__(
        self,
        event_store: EventStoreProtocol,
        alert_service: Optional[AlertServiceProtocol] = None
    ):
        self.event_store = event_store
        self.alert_service = alert_service

    def execute(
        self,
        event_date: date,
        level: PolicyLevel,
        title: str,
        description: str,
        evidence_url: str
    ) -> CreatePolicyEventOutput:
        """
        执行用例

        Args:
            event_date: 要更新的事件日期
            level: 新的档位
            title: 新的标题
            description: 新的描述
            evidence_url: 新的证据 URL

        Returns:
            CreatePolicyEventOutput: 输出结果
        """
        # 对 Django 仓储走明确更新路径，避免与“同日多事件”安全策略冲突
        if isinstance(self.event_store, DjangoPolicyRepository):
            output = CreatePolicyEventOutput(success=False, errors=[], warnings=[])
            try:
                existing = self.event_store._model.objects.filter(event_date=event_date).first()
                if not existing:
                    output.errors.append(f"未找到日期为 {event_date} 的事件")
                    return output

                updated_event = PolicyEvent(
                    event_date=event_date,
                    level=level,
                    title=title,
                    description=description,
                    evidence_url=evidence_url
                )
                saved = self.event_store.save_event(
                    updated_event,
                    _update_id=existing.id
                )
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
            evidence_url=evidence_url
        )
        create_use_case = CreatePolicyEventUseCase(
            event_store=self.event_store,
            alert_service=self.alert_service
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

    def execute(self, event_date: Optional[date] = None, event_id: Optional[int] = None) -> tuple[bool, str]:
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
    source_id: Optional[int] = None  # None表示抓取所有启用的源
    force_refetch: bool = False  # 是否强制重新抓取（忽略去重）


@dataclass
class FetchRSSOutput:
    """RSS抓取输出 DTO"""
    success: bool
    sources_processed: int
    total_items: int
    new_policy_events: int
    errors: List[str]
    details: List[Dict[str, Any]]

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
        alert_service: Optional[AlertServiceProtocol] = None,
        ai_classifier: Optional[Any] = None  # PolicyClassifierProtocol
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
            'feedparser': FeedparserAdapter(),
        }

        # 内容提取器工厂
        self._extractor_factory = {
            'readability': create_content_extractor('readability'),
            'beautifulsoup': create_content_extractor('beautifulsoup'),
            'hybrid': create_content_extractor('hybrid'),
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
            details=[]
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
                output.total_items += detail.get('items_count', 0)
                output.new_policy_events += detail.get('new_events_count', 0)

            except Exception as e:
                error_msg = f"RSS源 {source.name} 抓取失败: {str(e)}"
                output.errors.append(error_msg)
                logger.error(error_msg, exc_info=True)

        output.success = output.sources_processed > 0
        return output

    def _fetch_single_source(
        self,
        source: RSSSourceConfigModel,
        force_refetch: bool
    ) -> Dict[str, Any]:
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
        keyword_rules = self.rss_repository.get_active_keyword_rules(
            category=source.category
        )
        if not keyword_rules:
            keyword_rules = DEFAULT_KEYWORD_RULES

        matcher = self._matcher_class(keyword_rules)

        # 5. 处理每个条目
        new_events_count = 0
        for item in items:
            policy_log_orm = None
            try:
                # 去重检查
                if not force_refetch and self.rss_repository.is_item_exists(item.link, item.guid):
                    logger.debug(f"Item already exists, skipping: {item.link}")
                    continue

                # 阶段1：先落库原始记录，保证后续处理失败也不会丢数据
                policy_log_orm = PolicyLog._default_manager.create(
                    event_date=item.pub_date.date(),
                    level='PX',  # 待分类
                    title=item.title,
                    description=item.description or item.title,
                    evidence_url=item.link,
                    info_category='other',
                    audit_status='pending_review',
                    ai_confidence=None,
                    structured_data={},
                    risk_impact='unknown',
                    rss_source_id=source.id,
                    rss_item_guid=item.guid or item.link,
                    processing_metadata={'processing_stage': 'raw_ingested'}
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
                    except Exception as e:
                        logger.error(f"AI classification error for {item.title}: {e}")

                # ========== 确定政策档位 ==========
                level = None

                # 优先使用 AI 推荐的档位
                if classification_result and classification_result.success and classification_result.policy_level:
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
                    logger.info(f"No policy level matched, using PENDING (unclassified) for: {item.title}")

                # 内容提取（如果启用）
                description = item.description or item.title
                extracted_content = None

                if source_config.extract_content:
                    try:
                        extractor = self._extractor_factory.get('hybrid')
                        if extractor:
                            extracted_content = extractor.extract(
                                url=item.link,
                                proxy_config=source_config.proxy_config,
                                timeout=source.timeout_seconds
                            )
                            if extracted_content:
                                description = extracted_content[:5000]

                                # 如果AI提取失败但提取了内容，可以重试AI分类
                                if classification_result and not classification_result.success:
                                    try:
                                        classification_result = self.ai_classifier.classify_rss_item(
                                            item, content=extracted_content
                                        )
                                        if classification_result.success:
                                            info_category = classification_result.info_category
                                            audit_status = classification_result.audit_status
                                            ai_confidence = classification_result.ai_confidence
                                            structured_data = classification_result.structured_data
                                            risk_impact = classification_result.risk_impact
                                    except Exception as e:
                                        logger.warning(f"AI classification failed: {e}")
                    except ContentExtractorError as e:
                        logger.warning(f"Failed to extract content from {item.link}: {e}")

                # 转换结构化数据为字典（使用空字典而非 None）
                structured_data_dict = {}
                if structured_data:
                    structured_data_dict = asdict(structured_data)

                # 保存到PolicyLog（扩展版）
                # 准备额外字段
                extra_fields = {
                    'info_category': info_category.value,
                    'audit_status': audit_status.value,
                    'ai_confidence': ai_confidence,
                    'structured_data': structured_data_dict,
                    'rss_source_id': source.id,
                    'rss_item_guid': item.guid or item.link,
                    'risk_impact': risk_impact.value,
                    'processing_metadata': classification_result.processing_metadata if classification_result else {}
                }

                # 阶段2：处理完成后更新已落库记录
                policy_log_orm.level = level.value
                policy_log_orm.description = description
                policy_log_orm.info_category = extra_fields['info_category']
                policy_log_orm.audit_status = extra_fields['audit_status']
                policy_log_orm.ai_confidence = extra_fields['ai_confidence']
                policy_log_orm.structured_data = extra_fields['structured_data']
                policy_log_orm.risk_impact = extra_fields['risk_impact']
                policy_log_orm.processing_metadata = {
                    **extra_fields['processing_metadata'],
                    'processing_stage': 'processed'
                }
                policy_log_orm.save(update_fields=[
                    'level',
                    'description',
                    'info_category',
                    'audit_status',
                    'ai_confidence',
                    'structured_data',
                    'risk_impact',
                    'processing_metadata'
                ])

                # ========== 审核队列管理 ==========
                # 如果需要人工审核，加入审核队列（使用 get_or_create 避免重复）
                if audit_status == AuditStatus.PENDING_REVIEW and policy_log_orm:
                    # 根据风险级别设置优先级
                    if level in [PolicyLevel.P2, PolicyLevel.P3]:
                        priority = 'urgent'
                    elif risk_impact == RiskImpact.HIGH_RISK:
                        priority = 'high'
                    else:
                        priority = 'normal'

                    _, created = PolicyAuditQueue._default_manager.get_or_create(
                        policy_log=policy_log_orm,
                        defaults={'priority': priority}
                    )
                    if created:
                        logger.info(f"Added policy {policy_log_orm.id} to audit queue (priority: {priority})")

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
                        structured_data=structured_data_dict
                    )

            except Exception as e:
                # 处理失败时保留原始记录，避免数据丢失
                logger.warning(f"Failed to process RSS item {item.link}: {e}, keeping pending raw record")
                try:
                    if policy_log_orm:
                        policy_log_orm.processing_metadata = {
                            **(policy_log_orm.processing_metadata or {}),
                            'error': str(e),
                            'saved_as_pending': True,
                            'processing_stage': 'failed'
                        }
                        policy_log_orm.save(update_fields=['processing_metadata'])
                        logger.info(f"Kept pending RSS item (processing failed): {item.title}")
                    else:
                        PolicyLog._default_manager.create(
                            event_date=item.pub_date.date(),
                            level='PX',
                            title=item.title,
                            description=item.description or item.title,
                            evidence_url=item.link,
                            info_category='other',
                            audit_status='pending_review',
                            ai_confidence=None,
                            structured_data={},
                            risk_impact='unknown',
                            rss_source_id=source.id,
                            rss_item_guid=item.guid or item.link,
                            processing_metadata={
                                'error': str(e),
                                'saved_as_pending': True,
                                'processing_stage': 'failed'
                            }
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
            fetch_status = 'error'
            error_msg = 'No entries found in RSS feed - feed may be invalid or inaccessible'
            logger.error(f"RSS源 {source.name} 抓取失败: {error_msg}")
        elif new_events_count == 0:
            # 抓取到了条目但都是重复的
            fetch_status = 'partial'
            error_msg = f'Fetched {len(items)} items but all were duplicates'
            logger.info(f"RSS源 {source.name}: {error_msg}")
        else:
            fetch_status = 'success'
            error_msg = None

        self.rss_repository.save_fetch_log(
            source_id=source.id,
            status=fetch_status,
            items_count=len(items),
            new_items_count=new_events_count,
            error_message=error_msg or '',
            duration=duration
        )

        # 7. 更新源状态
        self.rss_repository.update_source_last_fetch(
            source.id,
            fetch_status,
            error_msg=error_msg
        )

        return {
            'source_name': source.name,
            'source_id': source.id,
            'items_count': len(items),
            'new_events_count': new_events_count,
            'duration': duration,
            'status': fetch_status,
            'error': error_msg
        }

    def _orm_to_domain_config(self, orm_obj: RSSSourceConfigModel) -> RSSSourceConfig:
        """ORM转Domain实体"""
        proxy_config = None
        if orm_obj.proxy_enabled:
            proxy_config = ProxyConfig(
                host=orm_obj.proxy_host,
                port=orm_obj.proxy_port,
                username=orm_obj.proxy_username or None,
                password=orm_obj.proxy_password or None,
                proxy_type=orm_obj.proxy_type
            )

        return RSSSourceConfig(
            name=orm_obj.name,
            url=orm_obj.get_effective_url(),  # 使用有效 URL（RSSHub 模式下自动构建）
            category=orm_obj.category,
            is_active=orm_obj.is_active,
            fetch_interval_hours=orm_obj.fetch_interval_hours,
            extract_content=orm_obj.extract_content,
            proxy_config=proxy_config,
            # RSSHub 配置
            rsshub_enabled=orm_obj.rsshub_enabled,
            rsshub_route_path=orm_obj.rsshub_route_path or '',
            rsshub_use_global_config=orm_obj.rsshub_use_global_config,
            rsshub_custom_base_url=orm_obj.rsshub_custom_base_url or '',
            rsshub_custom_access_key=orm_obj.rsshub_custom_access_key or '',
            rsshub_format=orm_obj.rsshub_format or ''
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
                message=message
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
        structured_data: Optional[Dict[str, Any]] = None
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
            if structured_data.get('summary'):
                message += f"摘要: {structured_data['summary']}\n"
            if structured_data.get('affected_sectors'):
                message += f"影响板块: {', '.join(structured_data['affected_sectors'])}\n"
            if structured_data.get('sentiment'):
                message += f"情绪倾向: {structured_data['sentiment']}\n"

        try:
            return self.alert_service.send_alert(
                level="warning" if level == PolicyLevel.P2 else "critical",
                title=f"RSS新政策事件: {level.value}",
                message=message
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
    modifications: Optional[Dict[str, Any]] = None  # 允许审核者修改AI提取的数据


@dataclass
class ReviewPolicyItemOutput:
    """审核政策条目的输出"""
    success: bool
    audit_status: AuditStatus
    message: str
    errors: List[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


class GetAuditQueueUseCase:
    """获取审核队列用例"""

    def __init__(self, policy_repository: DjangoPolicyRepository):
        """
        初始化用例

        Args:
            policy_repository: 政策仓储
        """
        self.policy_repository = policy_repository

    def execute(
        self,
        user: Any,
        status: str = 'pending_review',
        priority: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
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
        from ..infrastructure.models import PolicyAuditQueue

        queryset = PolicyAuditQueue._default_manager.filter(
            policy_log__audit_status=status
        ).select_related('policy_log', 'assigned_to')

        if priority:
            queryset = queryset.filter(priority=priority)

        # 如果指定了用户，只返回分配给该用户的
        queryset = queryset.filter(assigned_to=user)

        # 优先级排序
        priority_order = {'urgent': 0, 'high': 1, 'normal': 2, 'low': 3}
        results = list(queryset[:limit])
        results.sort(key=lambda x: priority_order.get(x.priority, 99))

        return [
            {
                'id': item.policy_log.id,
                'title': item.policy_log.title,
                'description': item.policy_log.description[:200] + '...' if len(item.policy_log.description) > 200 else item.policy_log.description,
                'level': item.policy_log.level,
                'info_category': item.policy_log.info_category,
                'ai_confidence': item.policy_log.ai_confidence,
                'structured_data': item.policy_log.structured_data,
                'priority': item.priority,
                'created_at': item.policy_log.created_at.isoformat(),
                'assigned_at': item.assigned_at.isoformat() if item.assigned_at else None,
                'rss_source': item.policy_log.rss_source.name if item.policy_log.rss_source else None
            }
            for item in results
        ]


class ReviewPolicyItemUseCase:
    """审核政策条目用例"""

    def __init__(
        self,
        policy_repository: DjangoPolicyRepository,
        alert_service: Optional[AlertServiceProtocol] = None
    ):
        self.policy_repository = policy_repository
        self.alert_service = alert_service

    def execute(self, input: ReviewPolicyItemInput) -> ReviewPolicyItemOutput:
        """
        审核政策条目

        Args:
            input: 审核输入

        Returns:
            ReviewPolicyItemOutput: 审核结果
        """
        from ..infrastructure.models import PolicyLog, PolicyAuditQueue
        from django.utils import timezone

        output = ReviewPolicyItemOutput(
            success=False,
            audit_status=AuditStatus.PENDING_REVIEW,
            message=""
        )

        try:
            # 获取政策日志
            policy_log = PolicyLog._default_manager.get(id=input.policy_log_id)

            # 更新审核状态
            if input.approved:
                policy_log.audit_status = AuditStatus.MANUAL_APPROVED.value
                policy_log.reviewed_by = input.reviewer
                policy_log.reviewed_at = timezone.now()
                policy_log.review_notes = input.notes

                # 如果审核者提供了修改，更新结构化数据
                if input.modifications:
                    if policy_log.structured_data is None:
                        policy_log.structured_data = {}
                    policy_log.structured_data.update(input.modifications)

                policy_log.save()

                # 从审核队列中移除
                PolicyAuditQueue._default_manager.filter(policy_log=policy_log).delete()

                output.audit_status = AuditStatus.MANUAL_APPROVED
                output.message = "政策已审核通过"
                output.success = True

                logger.info(f"Policy {policy_log.id} approved by {input.reviewer.username}")

            else:
                # 拒绝
                policy_log.audit_status = AuditStatus.REJECTED.value
                policy_log.reviewed_by = input.reviewer
                policy_log.reviewed_at = timezone.now()
                policy_log.review_notes = input.notes or "人工拒绝"
                policy_log.save()

                # 从审核队列中移除
                PolicyAuditQueue._default_manager.filter(policy_log=policy_log).delete()

                output.audit_status = AuditStatus.REJECTED
                output.message = "政策已拒绝"
                output.success = True

                logger.info(f"Policy {policy_log.id} rejected by {input.reviewer.username}")

        except PolicyLog.DoesNotExist:
            output.errors.append(f"政策日志 {input.policy_log_id} 不存在")
            logger.error(f"Policy log {input.policy_log_id} not found")

        except Exception as e:
            output.errors.append(f"审核失败: {str(e)}")
            logger.error(f"Failed to review policy {input.policy_log_id}: {e}", exc_info=True)

        return output


class BulkReviewUseCase:
    """批量审核用例"""

    def __init__(self, review_use_case: ReviewPolicyItemUseCase):
        self.review_use_case = review_use_case

    def execute(
        self,
        policy_log_ids: List[int],
        approved: bool,
        reviewer: Any,
        notes: str = ""
    ) -> Dict[str, Any]:
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
        results = {
            'total': len(policy_log_ids),
            'success': 0,
            'failed': 0,
            'errors': []
        }

        for policy_log_id in policy_log_ids:
            input_dto = ReviewPolicyItemInput(
                policy_log_id=policy_log_id,
                approved=approved,
                reviewer=reviewer,
                notes=notes
            )

            output = self.review_use_case.execute(input_dto)

            if output.success:
                results['success'] += 1
            else:
                results['failed'] += 1
                results['errors'].extend(output.errors)

        return results


class AutoAssignAuditsUseCase:
    """自动分配审核任务用例"""

    def execute(self, max_per_user: int = 10) -> Dict[str, Any]:
        """
        自动将待审核的政策分配给审核人员

        Args:
            max_per_user: 每个用户最多分配数量

        Returns:
            Dict: 分配结果统计
        """
        from ..infrastructure.models import PolicyAuditQueue
        from django.contrib.auth.models import User
        from django.utils import timezone

        # 获取所有待审核且未分配的政策
        unassigned = PolicyAuditQueue._default_manager.filter(
            assigned_to__isnull=True,
            policy_log__audit_status='pending_review'
        ).order_by('-created_at')

        # 获取可用的审核人员（有权限的用户）
        auditors = User._default_manager.filter(is_staff=True).distinct()

        if not auditors:
            logger.warning("No auditors found with staff privileges")
            return {'assigned': 0, 'remaining': unassigned.count()}

        # 轮询分配
        assigned_count = 0
        for idx, queue_item in enumerate(unassigned):
            auditor = auditors[idx % auditors.count()]

            # 检查该用户已分配数量
            current_assigned = PolicyAuditQueue._default_manager.filter(
                assigned_to=auditor,
                policy_log__audit_status='pending_review'
            ).count()

            if current_assigned >= max_per_user:
                continue

            queue_item.assigned_to = auditor
            queue_item.assigned_at = timezone.now()
            queue_item.save()

            assigned_count += 1

        logger.info(f"Auto-assigned {assigned_count} policy reviews to {auditors.count()} auditors")

        return {
            'assigned': assigned_count,
            'remaining': unassigned.count() - assigned_count,
            'auditors': auditors.count()
        }

