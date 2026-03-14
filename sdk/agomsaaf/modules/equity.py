from typing import TYPE_CHECKING
"""
AgomSAAF SDK - Equity 个股分析模块

提供个股分析相关的 API 操作。
"""

from datetime import date
from typing import Any, Optional

from .base import BaseModule


class EquityModule(BaseModule):
    """
    个股分析模块

    提供股票评分、推荐、分析等功能。
    """

    def __init__(self, client: Any) -> None:
        """
        初始化 Equity 模块

        Args:
            client: AgomSAAF 客户端实例
        """
        super().__init__(client, "/api/equity")

    def get_stock_score(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取股票评分

        Args:
            stock_code: 股票代码（如 000001.SZ）
            as_of_date: 评分日期（None 表示最新）

        Returns:
            股票评分信息，包括综合评分、各维度分数

        Raises:
            NotFoundError: 当股票不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> score = client.equity.get_stock_score("000001.SZ")
            >>> print(f"综合评分: {score['overall_score']}")
            >>> print(f"估值分数: {score['valuation_score']}")
        """
        detail = self.get_stock_detail(stock_code)
        return {
            "success": detail.get("success", True),
            "stock_code": stock_code,
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "overall_score": detail.get("score"),
            "data": detail,
        }

    def list_stocks(
        self,
        sector: Optional[str] = None,
        min_score: Optional[float] = None,
        max_score: Optional[float] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """
        获取股票列表

        Args:
            sector: 行业过滤（可选）
            min_score: 最低评分过滤（可选）
            max_score: 最高评分过滤（可选）
            limit: 返回数量限制

        Returns:
            股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> stocks = client.equity.list_stocks(
            ...     sector="银行",
            ...     min_score=60
            ... )
            >>> for stock in stocks:
            ...     print(f"{stock['code']}: {stock['name']}")
        """
        response = self._get("pool/")
        stocks = response.get("stocks", response.get("results", response))
        if not isinstance(stocks, list):
            return []

        filtered: list[dict[str, Any]] = []
        for stock in stocks:
            stock_sector = stock.get("sector")
            stock_score = stock.get("score")

            if sector is not None and stock_sector != sector:
                continue
            if min_score is not None and stock_score is not None and stock_score < min_score:
                continue
            if max_score is not None and stock_score is not None and stock_score > max_score:
                continue
            filtered.append(stock)

        return filtered[:limit]

    def get_stock_detail(self, stock_code: str) -> dict[str, Any]:
        """
        获取股票详情

        Args:
            stock_code: 股票代码

        Returns:
            股票详情信息

        Raises:
            NotFoundError: 当股票不存在时

        Example:
            >>> client = AgomSAAFClient()
            >>> detail = client.equity.get_stock_detail("000001.SZ")
            >>> print(f"股票名称: {detail['name']}")
            >>> print(f"行业: {detail['sector']}")
        """
        stocks = self.list_stocks(limit=500)
        for stock in stocks:
            if stock.get("code") == stock_code or stock.get("stock_code") == stock_code:
                return stock
        return {
            "success": False,
            "stock_code": stock_code,
            "error": "stock detail is unavailable in current pool snapshot",
        }

    def get_recommendations(
        self,
        regime: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        获取股票推荐

        Args:
            regime: 宏观象限过滤（可选）
            limit: 返回数量限制

        Returns:
            推荐股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> recs = client.equity.get_recommendations(regime="Recovery")
            >>> for stock in recs:
            ...     print(f"{stock['code']}: {stock['reason']}")
        """
        payload: dict[str, Any] = {"max_count": limit}
        if regime is not None:
            payload["regime"] = regime

        response = self._post("screen/", json=payload)
        stock_codes = response.get("stock_codes", [])
        if not isinstance(stock_codes, list):
            return []

        return [
            {
                "code": stock_code,
                "regime": response.get("regime"),
                "screening_criteria": response.get("screening_criteria", {}),
            }
            for stock_code in stock_codes[:limit]
        ]

    def analyze_stock(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        分析股票

        返回股票的详细分析，包括基本面、技术面、估值等。

        Args:
            stock_code: 股票代码
            as_of_date: 分析日期（None 表示最新）

        Returns:
            股票分析结果

        Example:
            >>> client = AgomSAAFClient()
            >>> analysis = client.equity.analyze_stock("000001.SZ")
            >>> print(f"基本面分析: {analysis['fundamental']}")
            >>> print(f"技术面分析: {analysis['technical']}")
        """
        detail = self.get_stock_detail(stock_code)
        valuation = self.get_valuation(stock_code, as_of_date)
        return {
            "success": detail.get("success", True),
            "stock_code": stock_code,
            "as_of_date": as_of_date.isoformat() if as_of_date else None,
            "detail": detail,
            "valuation": valuation,
        }

    def get_sector_stocks(self, sector: str) -> list[dict[str, Any]]:
        """
        获取行业股票列表

        Args:
            sector: 行业名称

        Returns:
            该行业的股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> stocks = client.equity.get_sector_stocks("银行")
            >>> for stock in stocks:
            ...     print(f"{stock['code']}: {stock['name']}")
        """
        return self.list_stocks(sector=sector, limit=100)

    def get_financials(
        self,
        stock_code: str,
        report_type: str = "annual",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        获取财务数据

        Args:
            stock_code: 股票代码
            report_type: 报告类型（annual/quarterly）
            limit: 返回数量限制

        Returns:
            财务数据列表

        Example:
            >>> client = AgomSAAFClient()
            >>> financials = client.equity.get_financials("000001.SZ")
            >>> for f in financials:
            ...     print(f"{f['report_date']}: 营收 {f['revenue']}")
        """
        return []

    def get_valuation(
        self,
        stock_code: str,
        as_of_date: Optional[date] = None,
    ) -> dict[str, Any]:
        """
        获取估值数据

        Args:
            stock_code: 股票代码
            as_of_date: 估值日期（None 表示最新）

        Returns:
            估值数据，包括 PE、PB、PS 等指标

        Example:
            >>> client = AgomSAAFClient()
            >>> valuation = client.equity.get_valuation("000001.SZ")
            >>> print(f"PE: {valuation['pe']}")
            >>> print(f"PB: {valuation['pb']}")
        """
        params: dict[str, Any] = {}
        if as_of_date is not None:
            params["as_of_date"] = as_of_date.isoformat()

        return self._get(f"valuation/{stock_code}/", params=params)

    # =========================================================================
    # 估值修复跟踪 API
    # =========================================================================

    def get_valuation_repair_status(
        self,
        stock_code: str,
        lookback_days: int = 756,
    ) -> dict[str, Any]:
        """
        获取股票估值修复状态

        实时计算单只股票的估值修复状态，包括当前阶段、修复进度、速度等。

        Args:
            stock_code: 股票代码（如 000001.SZ）
            lookback_days: 回看窗口天数（默认 756 天，约 3 年）

        Returns:
            估值修复状态信息，包括：
            - phase: 当前阶段（undervalued/repair_started/repairing/near_target/completed/stalled 等）
            - composite_percentile: 综合估值分位数
            - repair_progress: 修复进度（0-1）
            - repair_speed_per_30d: 修复速度（每30天百分点）
            - estimated_days_to_target: 预计到达目标天数
            - is_stalled: 是否停滞
            - description: 状态描述

        Example:
            >>> client = AgomSAAFClient()
            >>> status = client.equity.get_valuation_repair_status("000001.SZ")
            >>> print(f"阶段: {status['phase']}")
            >>> print(f"修复进度: {status['repair_progress'] * 100:.1f}%")
        """
        params: dict[str, Any] = {"lookback_days": lookback_days}
        return self._get(f"valuation-repair/{stock_code}/", params=params)

    def get_valuation_repair_history(
        self,
        stock_code: str,
        lookback_days: int = 252,
    ) -> list[dict[str, Any]]:
        """
        获取估值修复历史百分位序列

        返回指定股票的历史估值百分位时间序列，用于绘制图表。

        Args:
            stock_code: 股票代码（如 000001.SZ）
            lookback_days: 回看窗口天数（默认 252 天，约 1 年）

        Returns:
            百分位历史点列表，每个点包含：
            - trade_date: 交易日期
            - pe_percentile: PE 分位数
            - pb_percentile: PB 分位数
            - composite_percentile: 综合分位数

        Example:
            >>> client = AgomSAAFClient()
            >>> history = client.equity.get_valuation_repair_history("000001.SZ")
            >>> for point in history[-10:]:
            ...     print(f"{point['trade_date']}: {point['composite_percentile'] * 100:.1f}%")
        """
        params: dict[str, Any] = {"lookback_days": lookback_days}
        response = self._get(f"valuation-repair/{stock_code}/history/", params=params)
        return response.get("points", response)

    def scan_valuation_repairs(
        self,
        universe: str = "all_active",
        lookback_days: int = 756,
        limit: Optional[int] = None,
    ) -> dict[str, Any]:
        """
        批量扫描估值修复股票

        对指定股票池进行批量扫描，识别估值修复股票并保存快照。

        Args:
            universe: 股票池标识（"all_active" 或 "current_pool"）
            lookback_days: 回看窗口天数（默认 756 天）
            limit: 扫描数量限制（可选）

        Returns:
            扫描结果，包括：
            - scanned_count: 扫描数量
            - saved_count: 保存数量
            - failed_count: 失败数量
            - phase_counts: 各阶段数量统计

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.equity.scan_valuation_repairs(universe="all_active")
            >>> print(f"扫描 {result['scanned_count']} 只，保存 {result['saved_count']} 只")
        """
        data: dict[str, Any] = {
            "universe": universe,
            "lookback_days": lookback_days,
        }
        if limit is not None:
            data["limit"] = limit

        return self._post("valuation-repair/scan/", json=data)

    def list_valuation_repairs(
        self,
        universe: str = "all_active",
        phase: Optional[str] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        列出估值修复股票

        从快照表读取活跃的估值修复股票列表。

        Args:
            universe: 股票池标识（"all_active" 或 "current_pool"）
            phase: 阶段过滤（undervalued/repair_started/repairing/near_target/stalled）
            limit: 返回数量限制

        Returns:
            修复股票列表，包括：
            - count: 总数量
            - results: 股票列表

        Example:
            >>> client = AgomSAAFClient()
            >>> result = client.equity.list_valuation_repairs(phase="repairing")
            >>> for stock in result['results']:
            ...     print(f"{stock['stock_code']}: {stock['phase']}")
        """
        params: dict[str, Any] = {"universe": universe, "limit": limit}
        if phase is not None:
            params["phase"] = phase

        return self._get("valuation-repair-list/", params=params)

    # =========================================================================
    # 估值数据可信链 API
    # =========================================================================

    def sync_valuation_data(
        self,
        days_back: int = 1,
        stock_codes: Optional[list[str]] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        primary_source: str = "akshare",
        fallback_source: str = "tushare",
    ) -> dict[str, Any]:
        """
        同步估值数据到本地估值表。

        Args:
            days_back: 回溯天数
            stock_codes: 指定股票代码列表（可选）
            start_date: 起始日期（可选）
            end_date: 结束日期（可选）
            primary_source: 主数据源
            fallback_source: 备数据源

        Returns:
            同步统计结果
        """
        data: dict[str, Any] = {
            "days_back": days_back,
            "primary_source": primary_source,
            "fallback_source": fallback_source,
        }
        if stock_codes is not None:
            data["stock_codes"] = stock_codes
        if start_date is not None:
            data["start_date"] = start_date.isoformat()
        if end_date is not None:
            data["end_date"] = end_date.isoformat()

        return self._post("valuation-data/sync/", json=data)

    def validate_valuation_data(
        self,
        as_of_date: Optional[date] = None,
        primary_source: str = "akshare",
    ) -> dict[str, Any]:
        """
        对本地估值表生成质量快照并计算 gate 状态。
        """
        data: dict[str, Any] = {"primary_source": primary_source}
        if as_of_date is not None:
            data["as_of_date"] = as_of_date.isoformat()
        return self._post("valuation-data/validate/", json=data)

    def get_valuation_data_freshness(self) -> dict[str, Any]:
        """
        获取本地估值数据新鲜度。
        """
        return self._get("valuation-data/freshness/")

    def get_valuation_data_quality_latest(self) -> dict[str, Any]:
        """
        获取最近一次估值数据质量快照。
        """
        return self._get("valuation-data/quality-latest/")

    # ============== 估值修复配置管理 ==============

    def get_valuation_repair_config(self) -> dict[str, Any]:
        """
        获取当前激活的估值修复策略参数配置。

        Returns:
            当前激活的配置，包含所有阈值参数

        Example:
            >>> config = client.equity.get_valuation_repair_config()
            >>> print(f"目标百分位: {config['target_percentile']}")
        """
        response = self._get("config/valuation-repair/active/")
        return response.get("data", response)

    def list_valuation_repair_configs(self, limit: int = 20) -> list[dict[str, Any]]:
        """
        列出所有估值修复配置版本。

        Args:
            limit: 返回数量限制

        Returns:
            配置版本列表

        Example:
            >>> configs = client.equity.list_valuation_repair_configs()
        """
        response = self._get("config/valuation-repair/", params={"limit": limit})
        return response.get("results", response)

    def create_valuation_repair_config(
        self,
        change_reason: str,
        min_history_points: int = 120,
        default_lookback_days: int = 756,
        confirm_window: int = 20,
        min_rebound: float = 0.05,
        stall_window: int = 40,
        stall_min_progress: float = 0.02,
        target_percentile: float = 0.50,
        undervalued_threshold: float = 0.20,
        near_target_threshold: float = 0.45,
        overvalued_threshold: float = 0.80,
        pe_weight: float = 0.6,
        pb_weight: float = 0.4,
        confidence_base: float = 0.4,
        confidence_sample_threshold: int = 252,
        confidence_sample_bonus: float = 0.2,
        confidence_blend_bonus: float = 0.15,
        confidence_repair_start_bonus: float = 0.15,
        confidence_not_stalled_bonus: float = 0.1,
        repairing_threshold: float = 0.10,
        eta_max_days: int = 999,
    ) -> dict[str, Any]:
        """
        创建新的估值修复配置（草稿状态）。

        Args:
            change_reason: 变更原因（必填）
            min_history_points: 最小历史样本数
            default_lookback_days: 默认回看交易日数
            confirm_window: 修复确认窗口（交易日）
            min_rebound: 最小反弹幅度（百分位）
            stall_window: 停滞检测窗口（交易日）
            stall_min_progress: 停滞最小进展阈值
            target_percentile: 目标百分位
            undervalued_threshold: 低估阈值
            near_target_threshold: 接近目标阈值
            overvalued_threshold: 高估阈值
            pe_weight: PE 权重
            pb_weight: PB 权重
            confidence_base: 置信度基础值
            confidence_sample_threshold: 置信度样本数阈值
            confidence_sample_bonus: 置信度样本数奖励
            confidence_blend_bonus: 置信度 Blend 奖励
            confidence_repair_start_bonus: 置信度修复起点奖励
            confidence_not_stalled_bonus: 置信度非停滞奖励
            repairing_threshold: REPAIRING 阶段阈值
            eta_max_days: ETA 最大天数

        Returns:
            创建的配置

        Example:
            >>> config = client.equity.create_valuation_repair_config(
            ...     change_reason="调高目标百分位",
            ...     target_percentile=0.55,
            ... )
        """
        data = {
            "change_reason": change_reason,
            "min_history_points": min_history_points,
            "default_lookback_days": default_lookback_days,
            "confirm_window": confirm_window,
            "min_rebound": min_rebound,
            "stall_window": stall_window,
            "stall_min_progress": stall_min_progress,
            "target_percentile": target_percentile,
            "undervalued_threshold": undervalued_threshold,
            "near_target_threshold": near_target_threshold,
            "overvalued_threshold": overvalued_threshold,
            "pe_weight": pe_weight,
            "pb_weight": pb_weight,
            "confidence_base": confidence_base,
            "confidence_sample_threshold": confidence_sample_threshold,
            "confidence_sample_bonus": confidence_sample_bonus,
            "confidence_blend_bonus": confidence_blend_bonus,
            "confidence_repair_start_bonus": confidence_repair_start_bonus,
            "confidence_not_stalled_bonus": confidence_not_stalled_bonus,
            "repairing_threshold": repairing_threshold,
            "eta_max_days": eta_max_days,
        }
        return self._post("config/valuation-repair/", json=data)

    def activate_valuation_repair_config(self, config_id: int) -> dict[str, Any]:
        """
        激活指定的估值修复配置。

        激活后，新配置立即生效，同时停用其他配置。

        Args:
            config_id: 配置 ID

        Returns:
            激活结果

        Example:
            >>> result = client.equity.activate_valuation_repair_config(5)
        """
        return self._post(f"config/valuation-repair/{config_id}/activate/")

    def rollback_valuation_repair_config(self, config_id: int) -> dict[str, Any]:
        """
        回滚到指定的估值修复配置版本。

        Args:
            config_id: 要回滚到的配置 ID

        Returns:
            回滚结果

        Example:
            >>> result = client.equity.rollback_valuation_repair_config(3)
        """
        return self._post(f"config/valuation-repair/{config_id}/rollback/")
