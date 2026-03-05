"""
AI Policy Classifier - 政策AI分类服务

本模块实现基于AI的政策分类和结构化提取功能。
使用现有的ai_provider基础设施进行AI调用。
"""

import logging
import json
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from django.utils import timezone

from apps.ai_provider.infrastructure.adapters import OpenAICompatibleAdapter, AIFailoverHelper
from apps.ai_provider.infrastructure.repositories import AIProviderRepository
from apps.ai_provider.domain.services import AICostCalculator
from apps.policy.domain.entities import (
    RSSItem,
    AIClassificationResult,
    StructuredPolicyData,
    InfoCategory,
    AuditStatus,
    RiskImpact,
    PolicyLevel,
)
from apps.policy.domain.interfaces import PolicyClassifierProtocol
from shared.infrastructure.config_helper import ConfigHelper, ConfigKeys

logger = logging.getLogger(__name__)


class AIPolicyClassifier(PolicyClassifierProtocol):
    """
    AI政策分类器

    使用AI模型对RSS条目进行分类和结构化信息提取。
    支持自动通过/拒绝/人工审核的决策。
    """

    # 默认阈值（从配置读取失败时使用）
    DEFAULT_AUTO_APPROVE_THRESHOLD = 0.75
    DEFAULT_AUTO_REJECT_THRESHOLD = 0.3

    def __init__(self, ai_helper: AIFailoverHelper, usage_repo=None):
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
        return ConfigHelper.get_float(
            ConfigKeys.AI_AUTO_APPROVE_THRESHOLD,
            self.DEFAULT_AUTO_APPROVE_THRESHOLD
        )

    @property
    def auto_reject_threshold(self) -> float:
        """获取自动拒绝阈值（从配置读取）"""
        return ConfigHelper.get_float(
            ConfigKeys.AI_AUTO_REJECT_THRESHOLD,
            self.DEFAULT_AUTO_REJECT_THRESHOLD
        )

    def classify_rss_item(
        self,
        item: RSSItem,
        content: Optional[str] = None
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
        ai_result = self.ai_helper.chat_completion_with_failover(
            messages=messages,
            temperature=0.3,  # 降低温度以获得更一致的结果
            max_tokens=2000
        )

        processing_time_ms = int((timezone.now() - start_time).total_seconds() * 1000)

        # 记录AI使用日志
        if self.usage_repo and ai_result.get('provider_used'):
            self._log_ai_usage(ai_result, 'policy_classification')

        if ai_result.get('status') != 'success':
            return AIClassificationResult(
                success=False,
                error_message=f"AI调用失败: {ai_result.get('error_message', 'Unknown error')}",
                processing_metadata={
                    'ai_model_used': ai_result.get('model', 'unknown'),
                    'ai_processing_time_ms': processing_time_ms,
                    'ai_error': ai_result.get('error_message')
                }
            )

        # 解析AI返回结果
        try:
            parsed_data = self._parse_ai_response(ai_result.get('content', ''))

            # 构建结构化数据
            structured_data = StructuredPolicyData(
                policy_subject=parsed_data.get('structured_data', {}).get('policy_subject'),
                policy_object=parsed_data.get('structured_data', {}).get('policy_object'),
                effective_date=parsed_data.get('structured_data', {}).get('effective_date'),
                expiry_date=parsed_data.get('structured_data', {}).get('expiry_date'),
                conditions=parsed_data.get('structured_data', {}).get('conditions', []),
                impact_scope=parsed_data.get('structured_data', {}).get('impact_scope'),
                affected_sectors=parsed_data.get('structured_data', {}).get('affected_sectors', []),
                affected_stocks=parsed_data.get('structured_data', {}).get('affected_stocks', []),
                sentiment=parsed_data.get('structured_data', {}).get('sentiment'),
                sentiment_score=parsed_data.get('structured_data', {}).get('sentiment_score'),
                keywords=parsed_data.get('structured_data', {}).get('keywords', []),
                summary=parsed_data.get('structured_data', {}).get('summary'),
            )

            # 确定审核状态
            confidence = parsed_data.get('confidence', 0.5)
            if confidence >= self.auto_approve_threshold:
                audit_status = AuditStatus.AUTO_APPROVED
            elif confidence < self.auto_reject_threshold:
                audit_status = AuditStatus.REJECTED
            else:
                audit_status = AuditStatus.PENDING_REVIEW

            # 解析政策档位
            policy_level_str = parsed_data.get('policy_level')
            policy_level = None
            if policy_level_str:
                try:
                    policy_level = PolicyLevel(policy_level_str)
                except ValueError:
                    logger.warning(f"Invalid policy_level from AI: {policy_level_str}")

            return AIClassificationResult(
                success=True,
                info_category=InfoCategory(parsed_data.get('info_category', 'macro')),
                audit_status=audit_status,
                ai_confidence=confidence,
                policy_level=policy_level,
                structured_data=structured_data,
                risk_impact=RiskImpact(parsed_data.get('risk_impact', 'unknown')),
                processing_metadata={
                    'ai_model_used': ai_result.get('model'),
                    'ai_provider_used': ai_result.get('provider_used'),
                    'ai_processing_time_ms': processing_time_ms,
                    'ai_tokens_used': ai_result.get('total_tokens', 0),
                    'extraction_method': 'ai'
                }
            )

        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}", exc_info=True)
            return AIClassificationResult(
                success=False,
                error_message=f"解析AI响应失败: {str(e)}",
                processing_metadata={
                    'ai_model_used': ai_result.get('model'),
                    'ai_processing_time_ms': processing_time_ms,
                    'raw_response': ai_result.get('content', '')[:500]
                }
            )

    def batch_classify(
        self,
        items: List[tuple[RSSItem, Optional[str]]]
    ) -> List[AIClassificationResult]:
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

    def _log_ai_usage(self, ai_result: Dict[str, Any], request_type: str):
        """记录AI使用日志"""
        try:
            # 获取提供商
            provider_repo = AIProviderRepository()
            provider = provider_repo.get_by_name(ai_result.get('provider_used', ''))

            if not provider:
                return

            # 计算预估成本
            estimated_cost = self.cost_calculator.calculate_cost(
                model=ai_result.get('model', provider.default_model),
                prompt_tokens=ai_result.get('prompt_tokens', 0),
                completion_tokens=ai_result.get('completion_tokens', 0)
            )

            # 记录日志
            from apps.ai_provider.infrastructure.repositories import AIUsageRepository
            if not self.usage_repo:
                self.usage_repo = AIUsageRepository()

            self.usage_repo.log_usage(
                provider=provider,
                model=ai_result.get('model', provider.default_model),
                prompt_tokens=ai_result.get('prompt_tokens', 0),
                completion_tokens=ai_result.get('completion_tokens', 0),
                total_tokens=ai_result.get('total_tokens', 0),
                estimated_cost=estimated_cost,
                response_time_ms=ai_result.get('response_time_ms', 0),
                status=ai_result.get('status', 'error'),
                request_type=request_type,
                error_message=ai_result.get('error_message', ''),
                request_metadata={
                    'finish_reason': ai_result.get('finish_reason'),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to log AI usage: {e}")

    def _build_classification_prompt(
        self,
        item: RSSItem,
        content: Optional[str] = None
    ) -> List[Dict[str, str]]:
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
            {"role": "user", "content": user_prompt}
        ]

    def _parse_ai_response(self, response: str) -> Dict[str, Any]:
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
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON块
            json_match = re.search(r'```json\s*(.*?)\s*```', response, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass

            # 尝试提取花括号内容
            brace_match = re.search(r'\{.*\}', response, re.DOTALL)
            if brace_match:
                try:
                    return json.loads(brace_match.group(0))
                except json.JSONDecodeError:
                    pass

            # 都失败了，返回默认值
            logger.warning(f"Could not parse AI response as JSON: {response[:200]}")
            return {
                'info_category': 'other',
                'confidence': 0.3,
                'risk_impact': 'unknown',
                'structured_data': {}
            }


def create_ai_policy_classifier() -> Optional[AIPolicyClassifier]:
    """
    创建AI分类器实例（使用数据库配置的AI服务）

    Returns:
        AIPolicyClassifier or None: 如果AI服务未配置则返回None
    """
    try:
        # 从数据库获取AI提供商配置
        provider_repo = AIProviderRepository()
        active_providers = provider_repo.get_active_providers()

        if not active_providers:
            logger.warning("No active AI providers configured in database")
            return None

        # 构建提供商列表（按优先级排序）
        providers_list = []
        for provider in active_providers:
            extra_config = provider.extra_config if isinstance(provider.extra_config, dict) else {}
            # 使用 repository 的 get_api_key 方法解密
            api_key = provider_repo.get_api_key(provider)
            providers_list.append({
                'name': provider.name,
                'base_url': provider.base_url,
                'api_key': api_key,
                'default_model': provider.default_model,
                'priority': provider.priority,
                'api_mode': extra_config.get('api_mode'),
                'fallback_enabled': extra_config.get('fallback_enabled'),
            })

        # 创建故障转移辅助类
        ai_helper = AIFailoverHelper(providers_list)

        # 创建使用日志仓储
        from apps.ai_provider.infrastructure.repositories import AIUsageRepository
        usage_repo = AIUsageRepository()

        logger.info(f"Created AI policy classifier with {len(providers_list)} providers")
        return AIPolicyClassifier(ai_helper, usage_repo)

    except Exception as e:
        logger.error(f"Failed to create AI policy classifier: {e}", exc_info=True)
        return None
