"""
Alpha SDK Module

提供 Python SDK 访问 Alpha 信号功能。
"""

import os
from typing import Any, Dict, List, Optional

from .base import BaseModule


def _get_alpha_service() -> Any:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.development")
    import django
    if not django.apps.apps.ready:
        django.setup()
    from apps.alpha.application.services import AlphaService

    return AlphaService()


class AlphaModule(BaseModule):
    """
    Alpha 模块 SDK

    提供 Alpha 信号相关的 SDK 方法。

    Example:
        >>> client = AgomSAAFClient()
        >>> scores = client.alpha.get_stock_scores("csi300")
        >>> for stock in scores['stocks'][:5]:
        ...     print(f"{stock['rank']}. {stock['code']}: {stock['score']:.3f}")
    """

    def __init__(self, client: Any) -> None:
        super().__init__(client, "/api/alpha")

    def get_stock_scores(
        self,
        universe: str = "csi300",
        trade_date: Optional[str] = None,
        top_n: int = 30,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        获取股票评分

        获取指定股票池的 Alpha 评分，支持自动降级。

        Args:
            universe: 股票池标识（默认 csi300）
            trade_date: 交易日期（ISO 格式），默认今天
            top_n: 返回前 N 只股票（默认 30）

        Returns:
            包含股票评分的字典：
            {
                "success": True,
                "source": "cache",
                "status": "available",
                "stocks": [...],
                "metadata": {...}
            }

        Example:
            >>> result = client.alpha.get_stock_scores("csi300", "2026-02-05", 10)
            >>> print(f"数据源: {result['source']}")
        """
        params: dict[str, Any] = {
            "universe": universe,
            "top_n": top_n,
        }
        if trade_date is not None:
            params["trade_date"] = trade_date
        if user_id is not None:
            params["user_id"] = user_id
        return self._get("scores/", params=params)

    def upload_scores(
        self,
        scores: List[Dict[str, Any]],
        universe_id: str,
        asof_date: str,
        intended_trade_date: str,
        model_id: str = "local_qlib",
        model_artifact_hash: str = "",
        scope: str = "user",
    ) -> Dict[str, Any]:
        """
        上传本地 Qlib 推理结果到 VPS

        Args:
            scores: 评分列表，每条格式：{code, score, rank, factors, confidence, source}
            universe_id: 股票池标识（如 "csi300"）
            asof_date: 信号真实生成日期（ISO 格式，如 "2026-03-08"）
            intended_trade_date: 计划交易日期（ISO 格式）
            model_id: 模型标识（默认 "local_qlib"）
            model_artifact_hash: 模型文件哈希（可选）
            scope: 写入范围，"user" = 个人，"system" = 全局（仅 admin）

        Returns:
            {"success": true, "count": N, "scope": "user"|"system", "id": pk, "created": bool}

        Example:
            >>> scores = [
            ...     {"code": "000001.SZ", "score": 0.85, "rank": 1,
            ...      "factors": {"momentum": 0.8}, "confidence": 0.9},
            ... ]
            >>> result = client.alpha.upload_scores(
            ...     scores=scores,
            ...     universe_id="csi300",
            ...     asof_date="2026-03-08",
            ...     intended_trade_date="2026-03-10",
            ... )
            >>> print(f"上传 {result['count']} 条，scope={result['scope']}")
        """
        payload = {
            "universe_id": universe_id,
            "asof_date": asof_date,
            "intended_trade_date": intended_trade_date,
            "model_id": model_id,
            "scope": scope,
            "scores": scores,
        }
        if model_artifact_hash:
            payload["model_artifact_hash"] = model_artifact_hash

        return self._post("scores/upload/", json=payload)

    def get_provider_status(self) -> Dict[str, Any]:
        """
        获取 Provider 状态

        获取所有 Alpha Provider 的健康状态。

        Returns:
            Provider 状态字典

        Example:
            >>> status = client.alpha.get_provider_status()
            >>> for name, info in status.items():
            ...     print(f"{name}: {info['status']}")
        """
        return self._get("providers/status/")

    def get_available_universes(self) -> Dict[str, Any]:
        """
        获取支持的股票池列表

        Returns:
            股票池列表

        Example:
            >>> result = client.alpha.get_available_universes()
            >>> print(result['universes'])
        """
        return self._get("universes/")

    def get_factor_exposure(
        self,
        stock_code: str,
        trade_date: Optional[str] = None,
        provider: str = "simple"
    ) -> Dict[str, Any]:
        """
        获取个股因子暴露

        Args:
            stock_code: 股票代码
            trade_date: 交易日期（ISO 格式）
            provider: Provider 名称

        Returns:
            因子暴露字典

        Example:
            >>> result = client.alpha.get_factor_exposure("000001.SH")
            >>> print(result['factors'])
        """
        from datetime import date

        parsed_date = date.today()
        if trade_date:
            parsed_date = date.fromisoformat(trade_date)

        service = _get_alpha_service()
        provider_instance = service._registry.get_provider(provider)
        if not provider_instance:
            return {
                "success": False,
                "error": f"Provider '{provider}' 不存在",
                "stock_code": stock_code,
                "factors": {},
            }

        factors = provider_instance.get_factor_exposure(stock_code, parsed_date)
        return {
            "success": True,
            "stock_code": stock_code,
            "trade_date": parsed_date.isoformat(),
            "provider": provider,
            "factors": factors,
        }

    def check_health(self) -> Dict[str, Any]:
        """
        检查 Alpha 服务健康状态

        Returns:
            健康状态信息

        Example:
            >>> health = client.alpha.check_health()
            >>> print(f"状态: {health['status']}")
        """
        return self._get("health/")

    def get_top_stocks(
        self,
        universe: str = "csi300",
        trade_date: Optional[str] = None,
        top_n: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取排名前 N 的股票（便捷方法）

        Args:
            universe: 股票池标识
            trade_date: 交易日期
            top_n: 返回前 N 只

        Returns:
            股票列表

        Example:
            >>> top_stocks = client.alpha.get_top_stocks("csi300", top_n=5)
            >>> for stock in top_stocks:
            ...     print(f"{stock['code']}: {stock['score']:.3f}")
        """
        result = self.get_stock_scores(universe, trade_date, top_n)

        if result.get("success"):
            return result.get("stocks", [])
        else:
            return []

    def compare_stocks(
        self,
        stock_codes: List[str],
        universe: str = "csi300",
        trade_date: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """
        比较多只股票的评分（便捷方法）

        Args:
            stock_codes: 股票代码列表
            universe: 股票池标识
            trade_date: 交易日期

        Returns:
            股票代码到评分的映射

        Example:
            >>> comparison = client.alpha.compare_stocks(
            ...     ["000001.SH", "000002.SH", "600519.SH"]
            ... )
            >>> for code, data in comparison.items():
            ...     print(f"{code}: score={data['score']:.3f}, rank={data['rank']}")
        """
        result = self.get_stock_scores(universe, trade_date, top_n=1000)

        if not result.get("success"):
            return {code: None for code in stock_codes}

        # 构建代码到评分的映射
        stock_map = {s["code"]: s for s in result.get("stocks", [])}

        # 返回请求的股票
        return {
            code: stock_map.get(code)
            for code in stock_codes
        }
