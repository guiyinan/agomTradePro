"""
Sentiment 模块 - Application 层 Celery 任务

本模块包含异步任务定义，使用 Celery 执行定时或后台任务。
"""

import logging
from datetime import date, datetime
from typing import Any, Dict

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(
    name='sentiment.calculate_daily_sentiment_index',
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 分钟后重试
    time_limit=900,
    soft_time_limit=850,
)
def calculate_daily_sentiment_index(self, target_date: str = None) -> dict[str, Any]:
    """
    每日计算综合情绪指数

    定时任务：每天晚上 23:00 执行

    Args:
        target_date: 目标日期（YYYY-MM-DD 格式），不指定则使用今天

    Returns:
        执行结果字典
    """
    from apps.ai_provider.infrastructure.repositories import AIProviderRepository
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository
    from apps.sentiment.application.services import SentimentAnalyzer, SentimentIndexCalculator
    from apps.sentiment.infrastructure.repositories import SentimentIndexRepository

    try:
        # 解析日期
        if target_date:
            target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        else:
            target_date_obj = date.today()

        logger.info(f"开始计算 {target_date_obj} 的情绪指数")

        # 1. 获取当日政策事件
        policy_repo = DjangoPolicyRepository()
        policy_events = policy_repo.get_events_in_range(target_date_obj, target_date_obj)

        logger.info(f"找到 {len(policy_events)} 个政策事件")

        # 2. 初始化服务
        ai_provider_repo = AIProviderRepository()
        analyzer = SentimentAnalyzer(ai_provider_repo)

        # 3. 分析政策情感
        policy_scores = []
        for event in policy_events:
            try:
                text = f"{event.title}\n{event.description or ''}"
                result = analyzer.analyze_text(text)
                policy_scores.append(result.sentiment_score)
                logger.info(f"政策事件 {event.id} 情感评分: {result.sentiment_score}")
            except Exception as e:
                logger.error(f"分析政策事件 {event.id} 失败: {e}")
                continue

        # 4. TODO: 获取当日新闻并分析（未来扩展）
        # 目前新闻部分为空，使用默认权重
        news_scores = []

        # 5. 计算综合指数（权重从配置读取）
        calculator = SentimentIndexCalculator()
        sentiment_index = calculator.calculate_index(
            news_scores=news_scores,
            policy_scores=policy_scores,
            # news_weight 和 policy_weight 从配置读取，无需显式传递
        )

        # 6. 保存到数据库
        index_repo = SentimentIndexRepository()
        index_repo.save(sentiment_index)

        logger.info(f"情绪指数计算完成: {sentiment_index.composite_index:.2f}")

        return {
            "date": str(target_date_obj),
            "composite_index": sentiment_index.composite_index,
            "news_sentiment": sentiment_index.news_sentiment,
            "policy_sentiment": sentiment_index.policy_sentiment,
            "confidence": sentiment_index.confidence_level,
            "news_count": sentiment_index.news_count,
            "policy_events": len(policy_events),
            "status": "success",
        }

    except Exception as e:
        logger.error(f"计算情绪指数失败: {e}", exc_info=True)
        raise  # 重新抛出异常以触发重试


@shared_task(
    name='sentiment.analyze_policy_event',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def analyze_policy_event_sentiment(self, event_id: int) -> dict[str, Any]:
    """
    分析单个政策事件的情感

    Args:
        event_id: 政策事件 ID

    Returns:
        分析结果字典
    """
    from apps.ai_provider.infrastructure.repositories import AIProviderRepository
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository
    from apps.sentiment.application.services import SentimentAnalyzer

    try:
        # 获取政策事件
        policy_repo = DjangoPolicyRepository()
        event = policy_repo.get_by_id(event_id)

        if not event:
            return {"status": "error", "message": f"政策事件 {event_id} 不存在"}

        # 分析情感
        ai_provider_repo = AIProviderRepository()
        analyzer = SentimentAnalyzer(ai_provider_repo)

        text = f"{event.title}\n{event.description or ''}"
        result = analyzer.analyze_text(text)

        logger.info(f"政策事件 {event_id} 情感分析完成: {result.sentiment_score}")

        return {
            "event_id": event_id,
            "sentiment_score": result.sentiment_score,
            "category": result.category.value,
            "confidence": result.confidence,
            "keywords": result.keywords,
            "status": "success",
        }

    except Exception as e:
        logger.error(f"分析政策事件 {event_id} 情感失败: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@shared_task(
    name='sentiment.batch_analyze_texts',
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def batch_analyze_texts(self, texts: list) -> list:
    """
    批量分析文本情感

    Args:
        texts: 文本列表

    Returns:
        分析结果列表
    """
    from apps.ai_provider.infrastructure.repositories import AIProviderRepository
    from apps.sentiment.application.services import SentimentAnalyzer

    ai_provider_repo = AIProviderRepository()
    analyzer = SentimentAnalyzer(ai_provider_repo)

    results = []
    for text in texts:
        try:
            result = analyzer.analyze_text(text)
            results.append({
                "text": text[:100] + "..." if len(text) > 100 else text,
                "score": result.sentiment_score,
                "category": result.category.value,
                "confidence": result.confidence,
            })
        except Exception as e:
            logger.error(f"分析文本失败: {e}")
            results.append({
                "text": text[:100] + "..." if len(text) > 100 else text,
                "error": str(e),
            })

    return results


@shared_task(
    name='sentiment.check_data_freshness',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def check_sentiment_data_freshness(self) -> dict[str, Any]:
    """
    检查情绪数据新鲜度

    检查最近的情绪指数数据是否存在，用于监控。
    """
    from apps.sentiment.infrastructure.repositories import SentimentIndexRepository

    try:
        index_repo = SentimentIndexRepository()
        latest = index_repo.get_latest()

        if not latest:
            return {
                "status": "warning",
                "message": "没有情绪指数数据",
            }

        # 检查数据是否是最新的
        today = date.today()
        latest_date = latest.index_date.date() if hasattr(latest.index_date, 'date') else latest.index_date

        if latest_date == today:
            return {
                "status": "ok",
                "message": f"今日数据已更新: {latest.composite_index:.2f}",
                "latest_date": str(latest_date),
                "composite_index": latest.composite_index,
            }
        else:
            days_diff = (today - latest_date).days
            return {
                "status": "warning",
                "message": f"数据过期 {days_diff} 天",
                "latest_date": str(latest_date),
            }

    except Exception as e:
        logger.error(f"检查情绪数据新鲜度失败: {e}", exc_info=True)
        return {
            "status": "error",
            "message": str(e),
        }
