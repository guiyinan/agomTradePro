"""RSS fetch use cases for Policy.

Owner module for the RSS ingestion pipeline: fetch feeds, deduplicate items,
optionally classify with AI, fall back to keyword matching, persist policy
logs in two phases, manage the audit queue, and send alerts.
"""

import logging
import time
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from core.exceptions import AIServiceError, DataFetchError, ExternalServiceError
from core.metrics import record_exception

from ..domain.entities import (
    AuditStatus,
    InfoCategory,
    PolicyEvent,
    PolicyLevel,
    ProxyConfig,
    RiskImpact,
    RSSSourceConfig,
)
from ..domain.interfaces import PolicyClassifierProtocol
from ..domain.rules import DEFAULT_KEYWORD_RULES, get_policy_response
from .event_use_cases import RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS, AlertServiceProtocol
from .repository_provider import (
    ContentExtractorError,
    DjangoPolicyRepository,
    FeedparserAdapter,
    RSSRepository,
    create_content_extractor,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FetchRSSInput",
    "FetchRSSOutput",
    "FetchRSSUseCase",
    "RSSSourceDetail",
]


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

    def __post_init__(self) -> None:
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
        ai_classifier: PolicyClassifierProtocol | None = None,
    ) -> None:
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
            source = self.rss_repository.get_source_by_id(input.source_id)
            if source is None:
                output.errors.append(f"RSS源 {input.source_id} 不存在")
                return output
            if not source.is_active:
                output.errors.append(f"RSS源 {input.source_id} 已停用")
                return output
            sources = [source]
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
            except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
                error_msg = f"RSS源 {source.name} 抓取失败（未预期）: {str(e)}"
                output.errors.append(error_msg)
                logger.exception(error_msg)
                record_exception(e, module="policy", is_handled=False)

        output.success = output.sources_processed > 0
        return output

    def _fetch_single_source(self, source: Any, force_refetch: bool) -> dict[str, Any]:
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
                classifier = self.ai_classifier
                if classifier is not None:
                    try:
                        classification_result = classifier.classify_rss_item(item)

                        if classification_result.success:
                            info_category = (
                                classification_result.info_category or InfoCategory.OTHER
                            )
                            audit_status = (
                                classification_result.audit_status or AuditStatus.PENDING_REVIEW
                            )
                            ai_confidence = classification_result.ai_confidence
                            structured_data = classification_result.structured_data
                            risk_impact = classification_result.risk_impact or RiskImpact.UNKNOWN

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
                    except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
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
                                proxy_config=(
                                    asdict(source_config.proxy_config)
                                    if source_config.proxy_config is not None
                                    else None
                                ),
                                timeout=source.timeout_seconds,
                            )
                            if extracted_content:
                                description = extracted_content[:5000]

                                # 如果AI提取失败但提取了内容，可以重试AI分类
                                if (
                                    classification_result
                                    and not classification_result.success
                                    and classifier is not None
                                ):
                                    try:
                                        classification_result = classifier.classify_rss_item(
                                            item, content=extracted_content
                                        )
                                        if classification_result.success:
                                            info_category = (
                                                classification_result.info_category
                                                or InfoCategory.OTHER
                                            )
                                            audit_status = (
                                                classification_result.audit_status
                                                or AuditStatus.PENDING_REVIEW
                                            )
                                            ai_confidence = classification_result.ai_confidence
                                            structured_data = classification_result.structured_data
                                            risk_impact = (
                                                classification_result.risk_impact
                                                or RiskImpact.UNKNOWN
                                            )
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
                                    except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
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
                    "processing_metadata": (
                        classification_result.processing_metadata if classification_result else {}
                    ),
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

            except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
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
                except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as save_error:
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
        self.rss_repository.update_source_last_fetch(
            source.id,
            fetch_status,
            error_msg=error_msg or "",
        )

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
        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
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
        except RECOVERABLE_POLICY_USE_CASE_EXCEPTIONS as e:
            logger.error(f"Failed to send alert for RSS event: {e}")
            return False
