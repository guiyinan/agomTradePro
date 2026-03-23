"""
Alpha Monitoring Tasks

Celery 任务用于定期监控 Alpha 模块状态并生成告警。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from celery import shared_task
from django.db.models import Avg, Count, Max
from django.utils import timezone

from apps.alpha.infrastructure.models import (
    AlphaScoreCacheModel,
    QlibModelRegistryModel,
)
from shared.infrastructure.metrics import AlertManager, MetricType, get_alpha_metrics
from shared.infrastructure.model_evaluation import (
    IC_Calculator,
    RollingMetrics,
)

logger = logging.getLogger(__name__)


@shared_task(name="alpha.monitor.evaluate_alerts")
def evaluate_alerts():
    """
    评估告警规则

    定期任务（每分钟）：
    1. 获取当前指标值
    2. 评估告警规则
    3. 记录告警日志
    """
    try:
        metrics = get_alpha_metrics()
        alert_manager = AlertManager()

        # 评估所有告警规则
        alerts = alert_manager.evaluate_all()

        if alerts:
            logger.warning(f"=== Alpha 告警 ({len(alerts)} 条) ===")
            for alert in alerts:
                logger.warning(alert)

            # 返回告警信息（可用于通知）
            return {
                "status": "alert",
                "count": len(alerts),
                "alerts": alerts,
                "timestamp": timezone.now().isoformat()
            }

        return {
            "status": "ok",
            "count": 0,
            "timestamp": timezone.now().isoformat()
        }

    except Exception as e:
        logger.error(f"告警评估失败: {e}", exc_info=True)
        raise


@shared_task(name="alpha.monitor.update_provider_metrics")
def update_provider_metrics():
    """
    更新 Provider 指标

    定期任务（每 5 分钟）：
    1. 计算 Provider 成功率
    2. 计算数据陈旧度
    3. 更新覆盖率指标
    """
    try:
        metrics = get_alpha_metrics()

        # 1. 计算各 Provider 的成功率
        providers = ["qlib", "cache", "simple", "etf"]

        for provider in providers:
            # 统计最近的缓存记录
            recent_caches = AlphaScoreCacheModel._default_manager.filter(
                provider_source=provider,
                created_at__gte=timezone.now() - timedelta(hours=1)
            )

            total = recent_caches.count()
            if total > 0:
                # 成功率：status 为 available 的比例
                available = recent_caches.filter(status="available").count()
                success_rate = available / total
                metrics.registry.set_gauge(
                    "alpha_provider_success_rate",
                    success_rate,
                    labels={"provider": provider}
                )

                # 平均陈旧度
                avg_staleness = 0
                for cache in recent_caches:
                    staleness = cache.get_staleness_days()
                    avg_staleness += staleness
                avg_staleness /= total

                metrics.registry.set_gauge(
                    "alpha_provider_staleness_days",
                    avg_staleness,
                    labels={"provider": provider}
                )

                logger.debug(
                    f"Provider {provider}: 成功率={success_rate:.2%}, "
                    f"陈旧度={avg_staleness:.1f}天"
                )

        # 2. 计算覆盖率
        latest_cache = (
            AlphaScoreCacheModel._default_manager.filter(
                universe_id="csi300",
                created_at__gte=timezone.now() - timedelta(days=1),
            )
            .order_by("-created_at")
            .first()
        )

        if latest_cache and latest_cache.scores:
            scored_count = len(latest_cache.scores)
            # 假设 csi300 有 300 只股票
            universe_count = 300
            coverage = scored_count / universe_count
            metrics.registry.set_gauge("alpha_coverage_ratio", coverage)

            logger.debug(f"覆盖率: {coverage:.2%} ({scored_count}/{universe_count})")

        # 3. 记录指标到日志
        metrics.log_metrics()

        return {
            "status": "success",
            "timestamp": timezone.now().isoformat()
        }

    except Exception as e:
        logger.error(f"更新 Provider 指标失败: {e}", exc_info=True)
        raise


@shared_task(name="alpha.monitor.calculate_ic_drift")
def calculate_ic_drift():
    """
    计算 IC 漂移

    定期任务（每周）：
    1. 获取历史 IC 值
    2. 计算滚动 IC
    3. 检测 IC 漂移
    """
    try:
        metrics = get_alpha_metrics()

        # 获取激活的模型
        active_model = QlibModelRegistryModel._default_manager.filter(
            is_active=True
        ).first()

        if not active_model:
            logger.warning("没有激活的模型，跳过 IC 漂移计算")
            return {"status": "skipped", "reason": "no_active_model"}

        # 获取该模型的缓存记录（用于计算历史 IC）
        caches = AlphaScoreCacheModel._default_manager.filter(
            model_artifact_hash=active_model.artifact_hash,
            provider_source="qlib"
        ).order_by('intended_trade_date')

        if caches.count() < 20:
            logger.warning(f"缓存数据不足 ({caches.count()} 条)，跳过 IC 漂移计算")
            return {"status": "skipped", "reason": "insufficient_data"}

        # 使用 cache_evaluation 计算滚动 IC
        from apps.alpha.infrastructure.cache_evaluation import calculate_rolling_metrics

        first_cache = caches.first()
        last_cache = caches.last()

        rolling = calculate_rolling_metrics(
            model_artifact_hash=active_model.artifact_hash,
            universe_id=first_cache.universe_id,
            start_date=first_cache.intended_trade_date,
            end_date=last_cache.intended_trade_date,
            window=20,
        )

        if not rolling:
            logger.warning("滚动 IC 计算无结果（可能缺少真实收益数据），标记为 skipped")
            return {"status": "skipped", "reason": "no_rolling_ic_data"}

        historical_ics = [r.ic for r in rolling]
        current_ic = historical_ics[-1]

        # 记录 IC 指标
        metrics.record_ic_metrics(current_ic, historical_ics, window=20)

        hist_mean = sum(historical_ics[-20:]) / len(historical_ics[-20:])
        logger.info(
            f"IC 漂移计算完成: 当前 IC={current_ic:.4f}, "
            f"历史均值={hist_mean:.4f}"
        )

        return {
            "status": "success",
            "current_ic": current_ic,
            "historical_mean": hist_mean,
            "drift": current_ic - hist_mean,
            "timestamp": timezone.now().isoformat()
        }

    except Exception as e:
        logger.error(f"IC 漂移计算失败: {e}", exc_info=True)
        raise


@shared_task(name="alpha.monitor.check_queue_lag")
def check_queue_lag():
    """
    检查队列积压

    定期任务（每分钟）：
    1. 使用 Celery inspect 获取活动任务数
    2. 更新队列积压指标
    """
    try:
        metrics = get_alpha_metrics()

        # 尝试使用 Celery inspect
        try:
            from celery import current_app

            inspect = current_app.control.inspect()
            active = inspect.active()

            if active:
                # 统计各队列的活动任务数
                queue_tasks = {}

                for worker, tasks in active.items():
                    for task in tasks:
                        queue = task.get("delivery_info", {}).get("routing_key", "default")

                        if queue not in queue_tasks:
                            queue_tasks[queue] = 0
                        queue_tasks[queue] += 1

                # 更新指标
                for queue_name, count in queue_tasks.items():
                    if "qlib" in queue_name:
                        metrics.record_queue_lag(queue_name, count)
                        logger.debug(f"队列 {queue_name}: {count} 个活动任务")

                return {
                    "status": "success",
                    "queues": queue_tasks,
                    "timestamp": timezone.now().isoformat()
                }

        except Exception as e:
            logger.warning(f"无法获取 Celery 队列状态: {e}")

        # 如果无法获取实际队列状态，使用默认值
        metrics.record_queue_lag("qlib_infer", 0)
        metrics.record_queue_lag("qlib_train", 0)

        return {
            "status": "fallback",
            "timestamp": timezone.now().isoformat()
        }

    except Exception as e:
        logger.error(f"检查队列积压失败: {e}", exc_info=True)
        raise


@shared_task(name="alpha.monitor.generate_daily_report")
def generate_daily_report():
    """
    生成每日监控报告

    定期任务（每天）：
    1. 汇总当天关键指标
    2. 生成报告摘要
    3. 记录到日志
    """
    try:
        metrics = get_alpha_metrics()
        today = timezone.now().date()

        # 统计今天的缓存记录
        today_caches = AlphaScoreCacheModel._default_manager.filter(
            created_at__date=today
        )

        # 按 Provider 分组
        provider_stats = {}
        for cache in today_caches:
            provider = cache.provider_source
            if provider not in provider_stats:
                provider_stats[provider] = {"count": 0, "available": 0}
            provider_stats[provider]["count"] += 1
            if cache.status == "available":
                provider_stats[provider]["available"] += 1

        # 统计模型活动
        model_activations = QlibModelRegistryModel._default_manager.filter(
            activated_at__date=today
        ).count()

        # 生成报告
        report = {
            "date": today.isoformat(),
            "cache_records": today_caches.count(),
            "provider_stats": provider_stats,
            "model_activations": model_activations,
            "metrics_snapshot": metrics.get_metrics_json()
        }

        logger.info("=== Alpha 每日监控报告 ===")
        logger.info(f"日期: {report['date']}")
        logger.info(f"缓存记录: {report['cache_records']} 条")

        for provider, stats in provider_stats.items():
            success_rate = stats["available"] / stats["count"] if stats["count"] > 0 else 0
            logger.info(
                f"  {provider}: {stats['count']} 条, "
                f"成功率 {success_rate:.2%}"
            )

        logger.info(f"模型激活: {model_activations} 次")

        return report

    except Exception as e:
        logger.error(f"生成每日报告失败: {e}", exc_info=True)
        raise


@shared_task(name="alpha.monitor.cleanup_old_metrics")
def cleanup_old_metrics(days: int = 30):
    """
    清理旧的监控数据

    定期任务（每周）：
    1. 删除过期的缓存记录
    2. 归档旧的指标数据
    """
    try:
        cutoff_date = timezone.now().date() - timedelta(days=days)

        # 删除旧的缓存记录
        deleted_count = AlphaScoreCacheModel._default_manager.filter(
            intended_trade_date__lt=cutoff_date
        ).delete()[0]

        logger.info(f"清理了 {deleted_count} 条过期缓存记录")

        # TODO: 归档指标数据到长期存储

        return {
            "status": "success",
            "deleted_count": deleted_count,
            "cutoff_date": cutoff_date.isoformat()
        }

    except Exception as e:
        logger.error(f"清理旧数据失败: {e}", exc_info=True)
        raise


# ============================================================================
# 向后兼容：旧任务名别名
# ============================================================================

@shared_task(name="apps.alpha.application.monitoring_tasks.evaluate_alerts")
def evaluate_alerts_legacy():
    """Legacy alias for evaluate_alerts task name."""
    return evaluate_alerts()


@shared_task(name="apps.alpha.application.monitoring_tasks.update_provider_metrics")
def update_provider_metrics_legacy():
    """Legacy alias for update_provider_metrics task name."""
    return update_provider_metrics()


@shared_task(name="apps.alpha.application.monitoring_tasks.check_queue_lag")
def check_queue_lag_legacy():
    """Legacy alias for check_queue_lag task name."""
    return check_queue_lag()


@shared_task(name="apps.alpha.application.monitoring_tasks.calculate_ic_drift")
def calculate_ic_drift_legacy():
    """Legacy alias for calculate_ic_drift task name."""
    return calculate_ic_drift()


@shared_task(name="apps.alpha.application.monitoring_tasks.generate_daily_report")
def generate_daily_report_legacy():
    """Legacy alias for generate_daily_report task name."""
    return generate_daily_report()


@shared_task(name="apps.alpha.application.monitoring_tasks.cleanup_old_metrics")
def cleanup_old_metrics_legacy(days: int = 30):
    """Legacy alias for cleanup_old_metrics task name."""
    return cleanup_old_metrics(days=days)


# ============================================================================
# 辅助函数：手动触发指标更新
# ============================================================================

def update_metrics_from_alpha_result(result, provider_name: str):
    """
    从 AlphaResult 更新指标

    在 AlphaService 中调用此函数以记录指标。
    """
    metrics = get_alpha_metrics()

    # 记录 Provider 调用
    metrics.record_provider_call(
        provider_name=provider_name,
        success=result.success,
        latency_ms=result.latency_ms or 0,
        staleness_days=result.staleness_days
    )

    # 记录覆盖率
    if result.scores:
        metrics.record_coverage(len(result.scores), 300)  # 假设 universe 有 300 只股票


def log_metrics_summary():
    """
    记录指标摘要到日志

    用于调试和监控。
    """
    metrics = get_alpha_metrics()

    logger.info("=== Alpha 模块指标摘要 ===")

    # Provider 成功率
    for provider in ["qlib", "cache", "simple", "etf"]:
        metric = metrics.registry.get_metric(
            "alpha_provider_success_rate",
            {"provider": provider}
        )
        if metric:
            logger.info(f"{provider} 成功率: {metric.value:.2%}")

    # 覆盖率
    coverage = metrics.registry.get_metric("alpha_coverage_ratio")
    if coverage:
        logger.info(f"覆盖率: {coverage.value:.2%}")

    # 队列积压
    for queue in ["qlib_infer", "qlib_train"]:
        metric = metrics.registry.get_metric("qlib_infer_queue_lag", {"queue": queue})
        if metric:
            logger.info(f"{queue} 队列积压: {metric.value:.0f}")

    logger.info("========================")

