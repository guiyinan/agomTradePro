"""
Sentiment 模块 - Application 层 Celery 任务

本模块包含异步任务定义，使用 Celery 执行定时或后台任务。
"""

import logging
import math
from datetime import UTC, date, datetime, time

from django.utils import timezone

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
        return timezone.localdate()
    try:
        return datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("target_date must use YYYY-MM-DD format") from exc


def _calculate_daily_sentiment_index(
    target_date_obj: date,
    *,
    news_mode: str = "published",
) -> dict[str, object]:
    """Calculate and persist one date-labelled sentiment index."""

    from apps.ai_provider.application.repository_provider import get_ai_provider_repository
    from apps.policy.application.repository_provider import get_current_policy_repository
    from apps.sentiment.application.repository_provider import (
        get_market_news_for_sentiment,
        get_sentiment_index_repository,
    )
    from apps.sentiment.application.services import SentimentAnalyzer, SentimentIndexCalculator

    logger.info("开始计算 %s 的情绪指数", target_date_obj)

    policy_repo = get_current_policy_repository()
    policy_events = policy_repo.get_events_in_range(target_date_obj, target_date_obj)

    logger.info("找到 %s 个政策事件", len(policy_events))

    ai_provider_repo = get_ai_provider_repository()
    analyzer = SentimentAnalyzer(ai_provider_repo)

    policy_scores: list[float] = []
    failure_count = 0
    for event in policy_events:
        try:
            text = f"{event.title}\n{event.description or ''}"
            result = analyzer.analyze_text(text)
            if result.error_message is not None:
                failure_count += 1
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
            failure_count += 1
            logger.error(
                "分析政策事件 %s (%s) 失败: %s",
                event.title,
                event.event_date,
                exc,
            )

    if news_mode == "published":
        news_items = get_market_news_for_sentiment(target_date_obj, limit=50)
    else:
        news_items = get_market_news_for_sentiment(
            target_date_obj,
            limit=50,
            mode=news_mode,
        )
    logger.info("找到 %s 条市场新闻", len(news_items))
    news_scores: list[float] = []
    for news_item in news_items:
        stored_score = news_item.sentiment_score
        if stored_score is not None:
            try:
                news_scores.append(_normalize_news_sentiment_score(stored_score))
            except (TypeError, ValueError) as exc:
                failure_count += 1
                logger.error(
                    "新闻 %s 的已存情绪评分无效，已跳过: %s",
                    news_item.external_id or news_item.url,
                    exc,
                )
            continue

        try:
            text = _build_news_text(news_item)
            if not text:
                failure_count += 1
                continue
            result = analyzer.analyze_text(text)
            if result.error_message is not None:
                failure_count += 1
                logger.warning(
                    "新闻 %s 情感分析不可用，不计入指数",
                    news_item.external_id or news_item.url,
                )
                continue
            news_scores.append(result.sentiment_score)
        except Exception as exc:
            failure_count += 1
            logger.error(
                "分析新闻 %s 失败: %s",
                news_item.external_id or news_item.url,
                exc,
            )

    requested_count = len(policy_events) + len(news_items)
    succeeded_count = len(policy_scores) + len(news_scores)
    if failure_count and succeeded_count == 0:
        raise AIServiceError(f"{failure_count} sentiment analyses failed")

    calculator = SentimentIndexCalculator()
    sentiment_index = calculator.calculate_index(
        news_scores=news_scores,
        policy_scores=policy_scores,
        index_date=datetime.combine(target_date_obj, time.min, tzinfo=UTC),
    )

    index_repo = get_sentiment_index_repository()
    index_repo.save(sentiment_index)

    if not sentiment_index.data_sufficient:
        outcome = "blocked"
    elif failure_count:
        outcome = "partial"
    else:
        outcome = "success"
    logger.info(
        "情绪指数计算完成: date=%s score=%.2f outcome=%s",
        target_date_obj,
        sentiment_index.composite_index,
        outcome,
    )
    return {
        "date": target_date_obj.isoformat(),
        "composite_index": sentiment_index.composite_index,
        "news_sentiment": sentiment_index.news_sentiment,
        "policy_sentiment": sentiment_index.policy_sentiment,
        "confidence": sentiment_index.confidence_level,
        "news_count": sentiment_index.news_count,
        "policy_events": len(policy_events),
        "requested": requested_count,
        "succeeded": succeeded_count,
        "failed": failure_count,
        "stored": 1,
        "outcome": outcome,
        "success": outcome == "success",
        "status": outcome,
        "blocked_reason": ("sentiment_data_insufficient" if outcome == "blocked" else ""),
    }


@typed_shared_task(
    name="sentiment.calculate_daily_sentiment_index",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=900,
    soft_time_limit=850,
)
def calculate_daily_sentiment_index(
    self: BoundTask,
    target_date: str | None = None,
    mode: str = "published",
) -> dict[str, object]:
    """Calculate one sentiment index from published or explicit historical facts."""

    target_date_obj = _parse_target_date(target_date)
    if mode not in {"published", "historical"}:
        raise ValueError("mode must be 'published' or 'historical'")
    try:
        return _calculate_daily_sentiment_index(target_date_obj, news_mode=mode)
    except Exception as exc:
        logger.exception("计算情绪指数失败")
        raise self.retry(exc=exc, countdown=300) from exc


@typed_shared_task(
    name="sentiment.refresh_current_sentiment_index",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    time_limit=1200,
    soft_time_limit=1140,
)
def refresh_current_sentiment_index(
    self: BoundTask,
    target_date: str | None = None,
) -> dict[str, object]:
    """Refresh broad-market news and then persist the date-labelled index."""

    target_date_obj = _parse_target_date(target_date)
    try:
        from apps.data_center.application.interface_services import (
            sync_market_news_for_sentiment,
        )

        sync_result = sync_market_news_for_sentiment(limit=100)
        result = _calculate_daily_sentiment_index(target_date_obj)
        result["news_sync"] = {
            "provider": sync_result.provider_name,
            "stored": sync_result.stored_count,
            "status": sync_result.status,
            "error_message": sync_result.error_message,
        }
        if result.get("outcome") == "success" and sync_result.status != "success":
            result["outcome"] = "partial"
            result["status"] = "partial"
            result["success"] = False
        return result
    except Exception as exc:
        logger.exception("刷新当前情绪指数失败")
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
    from apps.sentiment.application.current_sentiment import resolve_current_sentiment

    try:
        current = resolve_current_sentiment()
        latest = current.diagnostic_index

        if not latest:
            return {
                "status": "warning",
                "message": "没有情绪指数数据",
                "freshness_status": current.freshness_status,
                "must_not_use_for_decision": True,
                "blocked_reason": current.blocked_reason,
            }

        if not current.must_not_use_for_decision:
            return {
                "status": "ok",
                "message": f"今日数据已更新: {latest.composite_index:.2f}",
                "latest_date": str(current.observed_at),
                "composite_index": latest.composite_index,
                "freshness_status": current.freshness_status,
                "must_not_use_for_decision": False,
                "blocked_reason": "",
            }
        return {
            "status": "warning",
            "message": f"情绪数据不可用于决策: {current.blocked_reason}",
            "latest_date": str(current.observed_at),
            "freshness_status": current.freshness_status,
            "must_not_use_for_decision": True,
            "blocked_reason": current.blocked_reason,
        }

    except Exception as exc:
        logger.exception("检查情绪数据新鲜度失败")
        raise self.retry(exc=exc, countdown=60) from exc
