"""
AI Policy Classifier - 政策AI分类服务

本模块实现基于AI的政策分类和结构化提取功能。
使用现有的ai_provider基础设施进行AI调用。
"""

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from apps.ai_provider.application.repository_provider import (
    build_ai_failover_helper,
    get_ai_provider_repository,
    get_ai_usage_repository,
)
from apps.ai_provider.domain.services import AICostCalculator
from apps.policy.domain.entities import (
    AIClassificationResult,
    AuditStatus,
    InfoCategory,
    PolicyLevel,
    RiskImpact,
    RSSItem,
    StructuredPolicyData,
)
from apps.policy.domain.interfaces import PolicyClassifierProtocol
from apps.regime.infrastructure.config_helper import ConfigHelper, ConfigKeys
from shared.numeric import safe_float

logger = logging.getLogger(__name__)


def AIProviderRepository() -> Any:
    """Compatibility factory for tests and policy infrastructure callers."""

    return get_ai_provider_repository()


def AIUsageRepository() -> Any:
    """Compatibility factory for tests and policy infrastructure callers."""

    return get_ai_usage_repository()


def AIFailoverHelper(providers: list[dict[str, Any]]) -> Any:
    """Compatibility factory for tests and policy infrastructure callers."""

    return build_ai_failover_helper(providers)


class AIPolicyClassifier(PolicyClassifierProtocol):
    """
    AI政策分类器

    使用AI模型对RSS条目进行分类和结构化信息提取。
    支持自动通过/拒绝/人工审核的决策。
    """

    # 默认阈值（从配置读取失败时使用）
    DEFAULT_AUTO_APPROVE_THRESHOLD = 0.75
    DEFAULT_AUTO_REJECT_THRESHOLD = 0.3

    def __init__(self, ai_helper: Any, usage_repo: Any | None = None):
        """
        初始化分类器

        Args:
            ai_helper: AI故障转移辅助类
            usage_repo: AI使用日志仓储（可选，用于记录使用情况）
        """
        self.ai_helper = ai_helper
        self.usage_repo = usage_repo
        self.cost_calculator = AICostCalculator()

    @property
    def auto_approve_threshold(self) -> float:
        """获取自动通过阈值（从配置读取）"""
        value = safe_float(
            ConfigHelper.get_float(
                ConfigKeys.AI_AUTO_APPROVE_THRESHOLD,
                self.DEFAULT_AUTO_APPROVE_THRESHOLD,
            )
        )
        return (
            value
            if value is not None and 0.0 <= value <= 1.0
            else self.DEFAULT_AUTO_APPROVE_THRESHOLD
        )

    @property
    def auto_reject_threshold(self) -> float:
        """获取自动拒绝阈值（从配置读取）"""
        value = safe_float(
            ConfigHelper.get_float(
                ConfigKeys.AI_AUTO_REJECT_THRESHOLD,
                self.DEFAULT_AUTO_REJECT_THRESHOLD,
            )
        )
        return (
            value
            if value is not None and 0.0 <= value <= 1.0
            else self.DEFAULT_AUTO_REJECT_THRESHOLD
        )

    def classify_rss_item(
        self, item: RSSItem, content: str | None = None
    ) -> AIClassificationResult:
        """
        对单个RSS条目进行分类

        Args:
            item: RSS条目
            content: 可选的完整内容（如果extract_content=True）

        Returns:
            AIClassificationResult: 分类结果
        """
        start_time = timezone.now()

        # 构建提示词
        messages = self._build_classification_prompt(item, content)

        # 调用AI
        raw_ai_result = self.ai_helper.chat_completion_with_failover(
            messages=messages, temperature=0.3, max_tokens=2000  # 降低温度以获得更一致的结果
        )
        ai_result = dict(raw_ai_result) if isinstance(raw_ai_result, Mapping) else {}

        processing_time_ms = int((timezone.now() - start_time).total_seconds() * 1000)

        # 记录AI使用日志
        if self.usage_repo and ai_result.get("provider_used"):
            self._log_ai_usage(ai_result, "policy_classification")

        if ai_result.get("status") != "success":
            return AIClassificationResult(
                success=False,
                error_message="AI policy classification unavailable",
                processing_metadata={
                    "ai_model_used": ai_result.get("model", "unknown"),
                    "ai_processing_time_ms": processing_time_ms,
                    "error_code": "ai_policy_provider_unavailable",
                },
            )

        # 解析AI返回结果
        try:
            parsed_data = self._parse_ai_response(ai_result.get("content", ""))
            structured_payload = parsed_data.get("structured_data")
            if not isinstance(structured_payload, Mapping):
                raise ValueError("structured_data must be an object")
            structured_data_payload = {str(key): value for key, value in structured_payload.items()}
            confidence = safe_float(parsed_data.get("confidence"))
            if confidence is None or not 0.0 <= confidence <= 1.0:
                raise ValueError("confidence must be finite and in [0, 1]")
            info_category = InfoCategory(str(parsed_data.get("info_category") or ""))
            risk_impact = RiskImpact(str(parsed_data.get("risk_impact") or ""))
            sentiment_score = safe_float(structured_data_payload.get("sentiment_score"))
            if "sentiment_score" in structured_data_payload and sentiment_score is None:
                raise ValueError("sentiment_score must be finite")
            if sentiment_score is not None and not -1.0 <= sentiment_score <= 1.0:
                raise ValueError("sentiment_score must be in [-1, 1]")

            # 构建结构化数据
            structured_data = StructuredPolicyData(
                policy_subject=self._optional_string(structured_data_payload, "policy_subject"),
                policy_object=self._optional_string(structured_data_payload, "policy_object"),
                effective_date=self._optional_string(structured_data_payload, "effective_date"),
                expiry_date=self._optional_string(structured_data_payload, "expiry_date"),
                conditions=self._string_list(structured_data_payload, "conditions"),
                impact_scope=self._optional_string(structured_data_payload, "impact_scope"),
                affected_sectors=self._string_list(structured_data_payload, "affected_sectors"),
                affected_stocks=self._string_list(structured_data_payload, "affected_stocks"),
                sentiment=self._optional_string(structured_data_payload, "sentiment"),
                sentiment_score=sentiment_score,
                keywords=self._string_list(structured_data_payload, "keywords"),
                summary=self._optional_string(structured_data_payload, "summary"),
            )

            # 确定审核状态
            approve_threshold = self.auto_approve_threshold
            reject_threshold = self.auto_reject_threshold
            if reject_threshold >= approve_threshold:
                approve_threshold = self.DEFAULT_AUTO_APPROVE_THRESHOLD
                reject_threshold = self.DEFAULT_AUTO_REJECT_THRESHOLD
            if confidence >= approve_threshold:
                audit_status = AuditStatus.AUTO_APPROVED
            elif confidence < reject_threshold:
                audit_status = AuditStatus.REJECTED
            else:
                audit_status = AuditStatus.PENDING_REVIEW

            # 解析政策档位
            policy_level_str = parsed_data.get("policy_level")
            policy_level = None
            if policy_level_str:
                policy_level = PolicyLevel(str(policy_level_str))

            return AIClassificationResult(
                success=True,
                info_category=info_category,
                audit_status=audit_status,
                ai_confidence=confidence,
                policy_level=policy_level,
                structured_data=structured_data,
                risk_impact=risk_impact,
                processing_metadata={
                    "ai_model_used": ai_result.get("model"),
                    "ai_provider_used": ai_result.get("provider_used"),
                    "ai_processing_time_ms": processing_time_ms,
                    "ai_tokens_used": ai_result.get("total_tokens", 0),
                    "extraction_method": "ai",
                },
            )

        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}", exc_info=True)
            return AIClassificationResult(
                success=False,
                error_message="AI policy response invalid",
                processing_metadata={
                    "ai_model_used": ai_result.get("model"),
                    "ai_processing_time_ms": processing_time_ms,
                    "error_code": "ai_policy_response_invalid",
                },
            )

    def batch_classify(
        self, items: list[tuple[RSSItem, str | None]]
    ) -> list[AIClassificationResult]:
        """
        批量分类

        Args:
            items: (RSS条目, 可选内容) 的列表

        Returns:
            List[AIClassificationResult]: 分类结果列表
        """
        results = []
        for item, content in items:
            result = self.classify_rss_item(item, content)
            results.append(result)
        return results

    def _log_ai_usage(self, ai_result: dict[str, Any], request_type: str) -> None:
        """记录AI使用日志"""
        try:
            # 获取提供商
            provider_repo = AIProviderRepository()
            provider = provider_repo.get_by_name(ai_result.get("provider_used", ""))

            if not provider:
                return

            # 计算预估成本
            estimated_cost = self.cost_calculator.calculate_cost(
                model=ai_result.get("model", provider.default_model),
                prompt_tokens=ai_result.get("prompt_tokens", 0),
                completion_tokens=ai_result.get("completion_tokens", 0),
            )

            # 记录日志
            if not self.usage_repo:
                self.usage_repo = AIUsageRepository()

            self.usage_repo.log_usage(
                provider=provider,
                model=ai_result.get("model", provider.default_model),
                prompt_tokens=ai_result.get("prompt_tokens", 0),
                completion_tokens=ai_result.get("completion_tokens", 0),
                total_tokens=ai_result.get("total_tokens", 0),
                estimated_cost=estimated_cost,
                response_time_ms=ai_result.get("response_time_ms", 0),
                status=ai_result.get("status", "error"),
                request_type=request_type,
                error_message=ai_result.get("error_message", ""),
                request_metadata={
                    "finish_reason": ai_result.get("finish_reason"),
                },
            )
        except Exception as e:
            logger.warning(f"Failed to log AI usage: {e}")

    def _build_classification_prompt(
        self, item: RSSItem, content: str | None = None
    ) -> list[dict[str, str]]:
        """
        构建AI分类提示词

        Args:
            item: RSS条目
            content: 可选的完整内容

        Returns:
            List[Dict]: 消息列表
        """
        # 构建输入文本
        input_text = f"标题: {item.title}\n"
        if item.description:
            input_text += f"摘要: {item.description}\n"
        if content:
            input_text += f"正文: {content[:3000]}\n"  # 限制长度
        if item.pub_date:
            input_text += f"发布时间: {item.pub_date.strftime('%Y-%m-%d %H:%M')}\n"
        if item.link:
            input_text += f"链接: {item.link}\n"

        system_prompt = """你是一个专业的金融政策分析师。你的任务是从RSS新闻条目中提取结构化信息并进行分类。

请严格按照以下JSON格式返回结果，不要添加任何其他文字：

{
  "info_category": "macro|sector|individual|sentiment|other",
  "confidence": 0.0-1.0,
  "risk_impact": "high_risk|medium_risk|low_risk|unknown",
  "structured_data": {
    "policy_subject": "政策主体（如：国务院、央行、证监会）",
    "policy_object": "政策客体（如：房地产、股市、制造业）",
    "effective_date": "YYYY-MM-DD格式或null",
    "expiry_date": "YYYY-MM-DD格式或null",
    "conditions": ["条件1", "条件2"],
    "impact_scope": "national|regional|sector|specific",
    "affected_sectors": ["板块1", "板块2"],
    "affected_stocks": ["股票代码1", "股票代码2"],
    "sentiment": "positive|negative|neutral",
    "sentiment_score": -1.0到1.0之间,
    "keywords": ["关键词1", "关键词2"],
    "summary": "一句话政策摘要（50字以内）"
  }
}

分类说明：
- macro: 宏观经济政策（货币、财政、国家层面政策）
- sector: 行业/板块政策（影响特定行业的政策）
- individual: 个股相关（具体公司的新闻、公告）
- sentiment: 市场情绪（投资者情绪、市场评论，非具体政策）
- other: 其他（无法归类的新闻）

置信度说明：
- 0.9-1.0: 非常确定（分类明确，内容完整）
- 0.7-0.9: 较确定（分类基本明确，但有些模糊）
- 0.5-0.7: 不确定（分类模糊，内容不完整）
- 0.3-0.5: 很不确定（内容严重不完整或无法理解）
- 0.0-0.3: 完全不确定（不应入库）

风险影响说明：
- high_risk: 可能导致市场大幅波动（如：危机政策、重大监管变化）
- medium_risk: 可能影响特定板块或资产
- low_risk: 影响较小或仅作为参考
- unknown: 无法判断风险影响

如果无法提取某个字段，请使用null或空列表。"""

        user_prompt = f"""请分析以下RSS新闻条目：

{input_text}

返回JSON格式的分析结果。"""

        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _parse_ai_response(self, response: str) -> dict[str, Any]:
        """
        解析AI返回的JSON响应

        Args:
            response: AI返回的原始文本

        Returns:
            Dict: 解析后的数据字典
        """
        # 尝试提取JSON
        try:
            # 尝试直接解析
            parsed = json.loads(response)
            if not isinstance(parsed, dict):
                raise ValueError("AI response must be a JSON object")
            return {str(key): value for key, value in parsed.items()}
        except json.JSONDecodeError:
            # 尝试提取JSON块
            json_match = re.search(r"```json\s*(.*?)\s*```", response, re.DOTALL)
            if json_match:
                try:
                    parsed = json.loads(json_match.group(1))
                    if isinstance(parsed, dict):
                        return {str(key): value for key, value in parsed.items()}
                except json.JSONDecodeError:
                    pass

            # 尝试提取花括号内容
            brace_match = re.search(r"\{.*\}", response, re.DOTALL)
            if brace_match:
                try:
                    parsed = json.loads(brace_match.group(0))
                    if isinstance(parsed, dict):
                        return {str(key): value for key, value in parsed.items()}
                except json.JSONDecodeError:
                    pass

            logger.warning("Could not parse AI response as JSON")
            raise ValueError("AI response is not valid JSON") from None

    @staticmethod
    def _optional_string(payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string or null")
        return value.strip() or None

    @staticmethod
    def _string_list(payload: Mapping[str, Any], key: str) -> list[str]:
        value = payload.get(key, [])
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError(f"{key} must be a list of strings")
        return [item.strip() for item in value if item.strip()]


def create_ai_policy_classifier() -> AIPolicyClassifier | None:
    """
    创建AI分类器实例（使用数据库配置的AI服务）

    Returns:
        AIPolicyClassifier or None: 如果AI服务未配置则返回None
    """
    try:
        provider_repo = AIProviderRepository()
        active_providers = provider_repo.get_active_configured_system_providers()
        if not active_providers:
            logger.warning("No active AI providers configured in database")
            return None

        providers_list = []
        for provider in active_providers:
            extra_config = provider.extra_config if isinstance(provider.extra_config, dict) else {}
            api_key = provider_repo.get_api_key(provider)
            if not api_key:
                continue
            providers_list.append(
                {
                    "name": provider.name,
                    "base_url": provider.base_url,
                    "api_key": api_key,
                    "default_model": provider.default_model,
                    "priority": provider.priority,
                    "api_mode": extra_config.get("api_mode"),
                    "fallback_enabled": extra_config.get("fallback_enabled"),
                }
            )

        if not providers_list:
            logger.warning(
                "AI policy classifier disabled because no provider credentials are usable: %s",
                "no active providers",
            )
            return None

        # 创建故障转移辅助类
        ai_helper = AIFailoverHelper(providers_list)
        if not ai_helper.has_available_adapters:
            logger.warning(
                "AI policy classifier disabled because no healthy providers are available: %s",
                ai_helper.describe_unavailable_providers(),
            )
            return None

        # 创建使用日志仓储
        usage_repo = AIUsageRepository()

        logger.info(f"Created AI policy classifier with {len(providers_list)} providers")
        return AIPolicyClassifier(ai_helper, usage_repo)

    except Exception as e:
        logger.error(f"Failed to create AI policy classifier: {e}", exc_info=True)
        return None
