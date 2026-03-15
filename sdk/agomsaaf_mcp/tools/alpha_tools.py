"""
Alpha MCP Tools

Model Context Protocol (MCP) 工具定义。
提供 Alpha 信号相关的 MCP 工具。
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from agomsaaf import AgomSAAFClient


logger = logging.getLogger(__name__)


def _ensure_django() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    import django
    if not django.apps.apps.ready:
        django.setup()


def register_alpha_tools(server) -> None:
    """
    注册 Alpha 相关的 MCP 工具

    Args:
        server: MCP 服务器实例
    """

    @server.tool()
    def get_alpha_stock_scores(
        universe: str = "csi300",
        trade_date: str | None = None,
        top_n: int = 20,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """
        获取 AI 选股评分

        获取指定股票池的 Alpha 评分，支持自动降级（Qlib → Cache → Simple → ETF）。

        Args:
            universe: 股票池标识（默认 csi300）
                     支持: csi300, csi500, sse50, csi1000, cyb
            trade_date: 交易日期（ISO 格式，如 2026-02-05）
                       默认为今天
            top_n: 返回前 N 只股票（默认 20，最大 500）

        Returns:
            包含股票评分的字典：
            {
                "success": true,
                "source": "cache",
                "status": "available",
                "stocks": [
                    {
                        "code": "000001.SH",
                        "score": 0.85,
                        "rank": 1,
                        "confidence": 0.8,
                        "factors": {"momentum": 0.7, "value": 0.6},
                        "asof_date": "2026-02-05"
                    },
                    ...
                ],
                "metadata": {...}
            }

        Example:
            >>> result = get_alpha_stock_scores("csi300", "2026-02-05", 10)
            >>> print(f"数据源: {result['source']}")
            >>> for stock in result['stocks']:
            ...     print(f"{stock['rank']}. {stock['code']}: {stock['score']:.3f}")
        """
        try:
            client = AgomSAAFClient()
            return client.alpha.get_stock_scores(
                universe=universe,
                trade_date=trade_date,
                top_n=top_n,
                user_id=user_id,
            )

        except Exception as e:
            logger.warning(f"获取 Alpha 评分失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "source": "none",
                "status": "error",
                "stocks": [],
            }

    @server.tool()
    def upload_alpha_scores(
        universe_id: str,
        asof_date: str,
        intended_trade_date: str,
        scores: list[dict[str, Any]],
        model_id: str = "local_qlib",
        model_artifact_hash: str = "",
        scope: str = "user",
    ) -> dict[str, Any]:
        """
        上传本地 Qlib 或离线生成的 Alpha 评分

        Args:
            universe_id: 股票池标识，如 csi300
            asof_date: 信号生成日期（YYYY-MM-DD）
            intended_trade_date: 计划交易日期（YYYY-MM-DD）
            scores: 评分列表，每条包含 code/score/rank/confidence/factors/source
            model_id: 模型标识
            model_artifact_hash: 模型文件哈希
            scope: user=个人评分，system=系统级评分（仅 admin token 可用）

        Returns:
            上传结果，包含 success/count/scope/id/created 等字段
        """
        try:
            client = AgomSAAFClient()
            return client.alpha.upload_scores(
                scores=scores,
                universe_id=universe_id,
                asof_date=asof_date,
                intended_trade_date=intended_trade_date,
                model_id=model_id,
                model_artifact_hash=model_artifact_hash,
                scope=scope,
            )
        except Exception as e:
            logger.warning(f"上传 Alpha 评分失败: {e}")
            return {
                "success": False,
                "error": str(e),
                "count": 0,
                "scope": scope,
            }

    @server.tool()
    def get_alpha_provider_status() -> dict[str, Any]:
        """
        获取 Alpha Provider 状态（诊断用）

        获取所有 Alpha Provider 的健康状态和配置信息。
        用于诊断和监控系统状态。

        Returns:
            Provider 状态字典：
            {
                "cache": {
                    "priority": 10,
                    "status": "available",
                    "max_staleness_days": 5
                },
                "simple": {
                    "priority": 100,
                    "status": "available",
                    "max_staleness_days": 7
                },
                "etf": {
                    "priority": 1000,
                    "status": "available",
                    "max_staleness_days": 30
                }
            }

        Example:
            >>> status = get_alpha_provider_status()
            >>> for name, info in status.items():
            ...     print(f"{name}: {info['status']} (priority={info['priority']})")
        """
        try:
            client = AgomSAAFClient()
            return client.alpha.get_provider_status()

        except Exception as e:
            logger.error(f"获取 Provider 状态失败: {e}", exc_info=True)
            return {
                "error": str(e)
            }

    @server.tool()
    def get_alpha_available_universes() -> dict[str, Any]:
        """
        获取支持的股票池列表

        获取当前系统支持的所有股票池标识。

        Returns:
            股票池列表：
            {
                "universes": ["csi300", "csi500", "sse50", "csi1000", "cyb"]
            }

        Example:
            >>> result = get_alpha_available_universes()
            >>> print("支持的股票池:")
            >>> for universe in result['universes']:
            ...     print(f"  - {universe}")
        """
        try:
            client = AgomSAAFClient()
            result = client.alpha.get_available_universes()
            universes = result.get("universes", []) if isinstance(result, dict) else []

            return {
                "universes": universes
            }

        except Exception as e:
            logger.error(f"获取股票池列表失败: {e}", exc_info=True)
            return {
                "error": str(e),
                "universes": []
            }

    @server.tool()
    def get_alpha_factor_exposure(
        stock_code: str,
        trade_date: str | None = None,
        provider: str = "simple"
    ) -> dict[str, Any]:
        """
        获取个股因子暴露

        获取指定股票的因子暴露度。

        Args:
            stock_code: 股票代码（如 000001.SH）
            trade_date: 交易日期（ISO 格式），默认为今天
            provider: Provider 名称（simple/etf），默认 simple

        Returns:
            因子暴露字典：
            {
                "stock_code": "000001.SH",
                "trade_date": "2026-02-05",
                "factors": {
                    "pe_inv": 0.05,
                    "pb_inv": 0.2,
                    "roe": 0.15,
                    "dividend_yield": 0.03
                }
            }

        Example:
            >>> result = get_alpha_factor_exposure("000001.SH", "2026-02-05")
            >>> print(f"PE倒数因子: {result['factors']['pe_inv']:.3f}")
        """
        from datetime import date

        try:
            _ensure_django()
            from apps.alpha.application.services import AlphaService
            service = AlphaService()

            # 解析日期
            parsed_date = date.today()
            if trade_date:
                try:
                    parsed_date = date.fromisoformat(trade_date)
                except ValueError:
                    pass

            # 获取指定的 Provider
            registry = service._registry
            provider_instance = registry.get_provider(provider)

            if not provider_instance:
                return {
                    "success": False,
                    "error": f"Provider '{provider}' 不存在",
                    "stock_code": stock_code,
                }

            # 获取因子暴露
            factors = provider_instance.get_factor_exposure(stock_code, parsed_date)

            return {
                "success": True,
                "stock_code": stock_code,
                "trade_date": parsed_date.isoformat(),
                "provider": provider,
                "factors": factors
            }

        except Exception as e:
            logger.error(f"获取因子暴露失败: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stock_code": stock_code,
                "factors": {}
            }

    @server.tool()
    def check_alpha_health() -> dict[str, Any]:
        """
        检查 Alpha 服务健康状态

        检查 Alpha 服务的整体健康状态。

        Returns:
            健康状态信息：
            {
                "status": "healthy",
                "timestamp": "2026-02-05T10:30:00",
                "providers": {
                    "available": 2,
                    "total": 3
                },
                "details": {
                    "cache": {...},
                    "simple": {...},
                    "etf": {...}
                }
            }

        Example:
            >>> health = check_alpha_health()
            >>> print(f"状态: {health['status']}")
            >>> print(f"可用 Provider: {health['providers']['available']}/{health['providers']['total']}")
        """
        try:
            client = AgomSAAFClient()
            providers_status = client.alpha.get_provider_status()
            if isinstance(providers_status, dict) and "providers" in providers_status:
                providers_status = providers_status["providers"]

            # 统计状态
            total = len(providers_status)
            available = sum(
                1 for s in providers_status.values()
                if s.get("status") in ["available", "degraded"]
            )

            health_status = "healthy" if available > 0 else "unhealthy"

            return {
                "status": health_status,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "providers": {
                    "available": available,
                    "total": total,
                },
                "details": providers_status
            }

        except Exception as e:
            logger.error(f"健康检查失败: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
