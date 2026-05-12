"""
板块分析模块 - Domain 层服务

遵循项目架构约束：
- 纯业务逻辑，不依赖 Django ORM
- 不依赖外部库（pandas、numpy 等）
- 通过依赖注入接收数据
"""

from datetime import date

from .entities import SectorIndex, SectorInfo, SectorRelativeStrength, SectorScore


class SectorRotationAnalyzer:
    """板块轮动分析服务（纯 Domain 层逻辑）

    职责：
    1. 计算板块相对强弱
    2. 计算板块动量
    3. 基于 Regime 对板块进行综合评分
    """

    def calculate_relative_strength(
        self,
        sector_returns: dict[date, float],
        market_returns: dict[date, float]
    ) -> dict[date, float]:
        """计算板块相对强弱

        Args:
            sector_returns: {日期: 板块收益率}
            market_returns: {日期: 大盘收益率}

        Returns:
            {日期: 相对强弱}
            相对强弱 = 板块收益率 - 大盘收益率

        Examples:
            >>> sector_returns = {date(2024,1,2): 0.02, date(2024,1,3): 0.01}
            >>> market_returns = {date(2024,1,2): 0.01, date(2024,1,3): 0.005}
            >>> analyzer = SectorRotationAnalyzer()
            >>> rs = analyzer.calculate_relative_strength(sector_returns, market_returns)
            >>> rs[date(2024,1,2)]
            0.01
        """
        relative_strength = {}

        for trade_date, sector_return in sector_returns.items():
            market_return = market_returns.get(trade_date, 0.0)
            rs = sector_return - market_return
            relative_strength[trade_date] = rs

        return relative_strength

    def calculate_momentum(
        self,
        sector_returns: list[float],
        lookback_days: int = 20
    ) -> float:
        """计算板块动量

        Args:
            sector_returns: 近期收益率列表（按时间顺序，最新的在最后）
            lookback_days: 回看天数

        Returns:
            累计收益率（%）

        Examples:
            >>> returns = [0.01, 0.02, -0.01, 0.03, 0.01]
            >>> analyzer = SectorRotationAnalyzer()
            >>> momentum = analyzer.calculate_momentum(returns, lookback_days=5)
            >>> round(momentum, 4)
            0.0602
        """
        if not sector_returns:
            return 0.0

        # 取最近的 N 天数据
        recent_returns = sector_returns[-lookback_days:] if len(sector_returns) >= lookback_days else sector_returns

        # 计算累计收益率：(1+r1)*(1+r2)*...*(1+rn) - 1
        cumulative_return = 1.0
        for r in recent_returns:
            cumulative_return *= (1 + r)

        return (cumulative_return - 1.0) * 100

    def rank_sectors_by_regime(
        self,
        sectors_data: list[tuple[SectorInfo, SectorIndex, SectorRelativeStrength]],
        regime_weights: dict[str, float],
        momentum_window: int = 20,
        momentum_weight: float = 0.3,
        rs_weight: float = 0.4,
        regime_weight: float = 0.3
    ) -> list[SectorScore]:
        """基于 Regime 对板块进行综合评分和排名

        Args:
            sectors_data: [(板块信息, 板块指数, 相对强弱)] 列表
            regime_weights: {板块代码: Regime 权重}（由 Application 层注入）
            momentum_window: 动量计算窗口
            momentum_weight: 动量评分权重
            rs_weight: 相对强弱评分权重
            regime_weight: Regime 适配度权重

        Returns:
            按综合评分降序排列的 SectorScore 列表

        Examples:
            >>> sector_info = SectorInfo('801010', '农林牧渔', 'SW1')
            >>> sector_index = SectorIndex('801010', date(2024,1,2), Decimal('1000'), ...)
            >>> sector_rs = SectorRelativeStrength('801010', date(2024,1,2), 0.5, 2.5)
            >>> regime_weights = {'801010': 0.8, '801020': 0.6}
            >>> analyzer = SectorRotationAnalyzer()
            >>> scores = analyzer.rank_sectors_by_regime(
            ...     [(sector_info, sector_index, sector_rs)],
            ...     regime_weights
            ... )
        """
        sector_scores = []

        for sector_info, sector_index, sector_rs in sectors_data:
            # 1. 动量评分（归一化到 0-100）
            # 假设动量范围为 -10% 到 +10%，映射到 0-100
            momentum = sector_rs.momentum
            momentum_score = self._normalize_score(momentum, -10.0, 10.0)

            # 2. 相对强弱评分（归一化到 0-100）
            # 假设相对强弱范围为 -5% 到 +5%
            rs = sector_rs.relative_strength
            rs_score = self._normalize_score(rs, -5.0, 5.0)

            # 3. Regime 适配度评分（从权重字典获取，已经是 0-1 范围）
            regime_weight = regime_weights.get(sector_info.sector_code, 0.5)
            regime_score = regime_weight * 100

            # 4. 综合评分
            total_score = (
                momentum_score * momentum_weight +
                rs_score * rs_weight +
                regime_score * regime_weight
            )

            sector_scores.append(SectorScore(
                sector_code=sector_info.sector_code,
                sector_name=sector_info.sector_name,
                trade_date=sector_index.trade_date,
                momentum_score=momentum_score,
                relative_strength_score=rs_score,
                regime_fit_score=regime_score,
                total_score=total_score,
                rank=0  # 排名稍后计算
            ))

        # 按综合评分降序排序
        sector_scores.sort(key=lambda x: x.total_score, reverse=True)

        # 更新排名
        for i, score in enumerate(sector_scores, 1):
            # 由于 dataclass 是 frozen 的，需要创建新对象
            sector_scores[i-1] = SectorScore(
                sector_code=score.sector_code,
                sector_name=score.sector_name,
                trade_date=score.trade_date,
                momentum_score=score.momentum_score,
                relative_strength_score=score.relative_strength_score,
                regime_fit_score=score.regime_fit_score,
                total_score=score.total_score,
                rank=i
            )

        return sector_scores

    def _normalize_score(
        self,
        value: float,
        min_val: float,
        max_val: float
    ) -> float:
        """将值归一化到 0-100 范围

        Args:
            value: 原始值
            min_val: 最小值
            max_val: 最大值

        Returns:
            归一化后的值（0-100）

        Examples:
            >>> analyzer = SectorRotationAnalyzer()
            >>> analyzer._normalize_score(5.0, -10.0, 10.0)
            75.0
            >>> analyzer._normalize_score(-5.0, -10.0, 10.0)
            25.0
        """
        if max_val == min_val:
            return 50.0

        normalized = (value - min_val) / (max_val - min_val)
        return max(0.0, min(100.0, normalized * 100))

    def calculate_beta(
        self,
        sector_returns: list[float],
        market_returns: list[float]
    ) -> float:
        """计算板块贝塔系数（相对于大盘）

        Beta = Cov(sector, market) / Var(market)

        Args:
            sector_returns: 板块收益率列表
            market_returns: 大盘收益率列表（长度需与 sector_returns 相同）

        Returns:
            贝塔系数

        Examples:
            >>> sector_returns = [0.02, 0.01, -0.01, 0.03, 0.01]
            >>> market_returns = [0.01, 0.005, -0.005, 0.02, 0.01]
            >>> analyzer = SectorRotationAnalyzer()
            >>> beta = analyzer.calculate_beta(sector_returns, market_returns)
        """
        if len(sector_returns) != len(market_returns) or len(sector_returns) < 2:
            return 1.0  # 默认值

        n = len(sector_returns)

        # 计算平均值
        avg_sector = sum(sector_returns) / n
        avg_market = sum(market_returns) / n

        # 计算协方差和方差
        covariance = sum(
            (sector_returns[i] - avg_sector) * (market_returns[i] - avg_market)
            for i in range(n)
        ) / n

        variance = sum(
            (market_returns[i] - avg_market) ** 2
            for i in range(n)
        ) / n

        if variance == 0:
            return 1.0

        return covariance / variance
