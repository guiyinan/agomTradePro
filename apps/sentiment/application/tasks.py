"""
Sentiment 模块 - Application 层 Celery 任务

本模块包含异步任务定义，使用 Celery 执行定时或后台任务。
"""

import logging
import math
from datetime import date, datetime

from apps.data_center.domain.entities import NewsFact
from core.exceptions import AIServiceError
from shared.infrastructure.celery_typing import BoundTask, typed_shared_task

logger = logging.getLogger(__name__)


def _normalize_news_sentiment_score(raw_score: float) -> float:
    """Normalize data-center news score into the sentiment [-3, 3] scale."""

    if isinstance(raw_score, bool):
        raise ValueError("news sentiment score must be a finite number")
    score = float(raw_score)
    if not math.isfinite(score):
        raise ValueError("news sentiment score must be a finite number")
    if -1.0 <= score <= 1.0:
        score *= 3.0
    return max(-3.0, min(3.0, score))


def _build_news_text(news_item: NewsFact) -> str:
    """Build analyzable text from a market news fact."""

    title = str(news_item.title or "")
    summary = str(news_item.summary or "")
    return f"{title}\n{summary}".strip()


def _parse_target_date(target_date: str | None) -> date:
    """Parse an optional task date without retrying permanent input errors."""

    if target_date is None or not target_date.strip():
        return date.today()
    try:
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("target_date must use YYYY-MM-DD format") from exc


@typed_shared_task(
    name="sentiment.calculate_daily_sentiment_index",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 分钟后重试
    time_limit=900,
    soft_time_limit=850,
)
def calculate_daily_sentiment_index(
    self: BoundTask,
    target_date: str | None = None,
) -> dict[str, object]:
    """
    每日计算综合情绪指数

    定时任务：每天晚上 23:00 执行

    Args:
        target_date: 目标日期（YYYY-MM-DD 格式），不指定则使用今天

    Returns:
        执行结果字典
    """
    from apps.ai_provider.application.repository_provider import get_ai_provider_repository
    from apps.policy.application.repository_provider import get_current_policy_repository
    from apps.sentiment.application.repository_provider import (
        get_market_news_for_sentiment,
        get_sentiment_index_repository,
    )
    from apps.sentiment.application.services import SentimentAnalyzer, SentimentIndexCalculator

    target_date_obj = _parse_target_date(target_date)

    try:
        logger.info(f"开始计算 {target_date_obj} 的情绪指数")

        # 1. 获取当日政策事件
        policy_repo = get_current_policy_repository()
        policy_events = policy_repo.get_events_in_range(target_date_obj, target_date_obj)

        logger.info(f"找到 {len(policy_events)} 个政策事件")

        # 2. 初始化服务
        ai_provider_repo = get_ai_provider_repository()
        analyzer = SentimentAnalyzer(ai_provider_repo)

        # 3. 分析政策情感
        policy_scores: list[float] = []
        ai_failure_count = 0
        for event in policy_events:
            try:
                text = f"{event.title}\n{event.description or ''}"
                result = analyzer.analyze_text(text)
                if result.error_message is not None:
                    ai_failure_count += 1
                    logger.warning(
                        "政策事件 %s 情感分析不可用，不计入指数",
                        event.title,
                    )
                    continue
                policy_scores.append(result.sentiment_score)
                logger.info(
                    "政策事件 %s (%s) 情感评分: %s",
                    event.title,
                    event.event_date,
                    result.sentiment_score,
                )
            except Exception as exc:
                ai_failure_count += 1
                logger.error(
                    "分析政策事件 %s (%s) 失败: %s",
                    event.title,
                    event.event_date,
                    exc,
                )
                continue

        # 4. 获取当日市场新闻并分析
        news_items = get_market_news_for_sentiment(target_date_obj, limit=50)
        logger.info(f"找到 {len(news_items)} 条市场新闻")
        news_scores: list[float] = []
        for news_item in news_items:
            stored_score = news_item.sentiment_score
            if stored_score is not None:
                try:
                    news_scores.append(_normalize_news_sentiment_score(stored_score))
                except (TypeError, ValueError) as exc:
                    logger.error(
                        "新闻 %s 的已存情绪评分无效，已跳过: %s",
                        news_item.external_id or news_item.url,
                        exc,
                    )
                continue

            try:
                text = _build_news_text(news_item)
                if not text:
                    continue
                result = analyzer.analyze_text(text)
                if result.error_message is not None:
                    ai_failure_count += 1
                    logger.warning(
                        "新闻 %s 情感分析不可用，不计入指数",
                        news_item.external_id or news_item.url,
                    )
                    continue
                news_scores.append(result.sentiment_score)
            except Exception as exc:
                ai_failure_count += 1
                logger.error(
                    "分析新闻 %s 失败: %s",
                    news_item.external_id or news_item.url,
                    exc,
                )
                continue

        if ai_failure_count:
            raise AIServiceError(f"{ai_failure_count} sentiment analyses failed")

        # 5. 计算综合指数（权重从配置读取）
        calculator = SentimentIndexCalculator()
        sentiment_index = calculator.calculate_index(
            news_scores=news_scores,
            policy_scores=policy_scores,
            # news_weight 和 policy_weight 从配置读取，无需显式传递
        )

        # 6. 保存到数据库
        index_repo = get_sentiment_index_repository()
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

    except Exception as exc:
        logger.exception("计算情绪指数失败")
        raise self.retry(exc=exc, countdown=300) from exc


@typed_shared_task(
    name="sentiment.analyze_policy_event",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def analyze_policy_event_sentiment(
    self: BoundTask,
    event_id: int,
) -> dict[str, object]:
    """
    分析单个政策事件的情感

    Args:
        event_id: 政策事件 ID

    Returns:
        分析结果字典
    """
    from apps.ai_provider.application.repository_provider import get_ai_provider_repository
    from apps.policy.application.repository_provider import get_current_policy_repository
    from apps.sentiment.application.services import SentimentAnalyzer

    if isinstance(event_id, bool) or not isinstance(event_id, int) or event_id <= 0:
        raise ValueError("event_id must be a positive integer")

    try:
        # 获取政策事件
        policy_repo = get_current_policy_repository()
        event = policy_repo.get_event_by_id(event_id)

        if not event:
            return {"status": "error", "message": f"政策事件 {event_id} 不存在"}

        # 分析情感
        ai_provider_repo = get_ai_provider_repository()
        analyzer = SentimentAnalyzer(ai_provider_repo)

        text = f"{event.title}\n{event.description or ''}"
        result = analyzer.analyze_text(text)
        if result.error_message is not None:
            raise AIServiceError("policy-event sentiment analysis failed")

        logger.info(f"政策事件 {event_id} 情感分析完成: {result.sentiment_score}")

        return {
            "event_id": event_id,
            "sentiment_score": result.sentiment_score,
            "category": result.category.value,
            "confidence": result.confidence,
            "keywords": result.keywords,
            "status": "success",
        }

    except Exception as exc:
        logger.exception("分析政策事件 %s 情感失败", event_id)
        raise self.retry(exc=exc, countdown=60) from exc


@typed_shared_task(
    name="sentiment.batch_analyze_texts",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    time_limit=900,
    soft_time_limit=850,
)
def batch_analyze_texts(
    self: BoundTask,
    texts: list[str],
) -> list[dict[str, object]]:
    """
    批量分析文本情感

    Args:
        texts: 文本列表

    Returns:
        分析结果列表
    """
    from apps.ai_provider.application.repository_provider import get_ai_provider_repository
    from apps.sentiment.application.services import SentimentAnalyzer

    ai_provider_repo = get_ai_provider_repository()
    analyzer = SentimentAnalyzer(ai_provider_repo)

    if any(not isinstance(text, str) for text in texts):
        raise ValueError("texts must contain only strings")

    results: list[dict[str, object]] = []
    for text in texts:
        try:
            result = analyzer.analyze_text(text)
            if result.error_message is not None:
                raise AIServiceError("batch sentiment analysis failed")
            results.append(
                {
                    "text": text[:100] + "..." if len(text) > 100 else text,
                    "score": result.sentiment_score,
                    "category": result.category.value,
                    "confidence": result.confidence,
                }
            )
        except AIServiceError:
            raise
        except Exception as exc:
            logger.error("分析文本失败: %s", exc)
            results.append(
                {
                    "text": text[:100] + "..." if len(text) > 100 else text,
                    "error": str(exc),
                }
            )

    return results


@typed_shared_task(
    name="sentiment.check_data_freshness",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    time_limit=300,
    soft_time_limit=280,
)
def check_sentiment_data_freshness(self: BoundTask) -> dict[str, object]:
    """
    检查情绪数据新鲜度

    检查最近的情绪指数数据是否存在，用于监控。
    """
    from apps.sentiment.application.repository_provider import get_sentiment_index_repository

    try:
        index_repo = get_sentiment_index_repository()
        latest = index_repo.get_latest()

        if not latest:
            return {
                "status": "warning",
                "message": "没有情绪指数数据",
            }

        # 检查数据是否是最新的
        today = date.today()
        latest_date = latest.index_date.date()

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

    except Exception as exc:
        logger.exception("检查情绪数据新鲜度失败")
        raise self.retry(exc=exc, countdown=60) from exc
