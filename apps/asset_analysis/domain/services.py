"""
资产分析模块 - Domain 层服务

本模块包含通用的匹配器（Matcher）类，用于计算资产在各维度的得分。
这些匹配器是纯函数实现，不依赖外部状态，符合 Domain 层的设计原则。
"""

from typing import Dict, List, Tuple

from apps.asset_analysis.domain.entities import AssetScore, AssetType


class RegimeMatcher:
    """
    Regime 匹配器（通用）

    根据 Regime（宏观环境）和资产属性计算匹配得分。
    Regime 类型：Recovery（复苏）/ Overheat（过热）/ Stagflation（滞胀）/ Deflation（通缩）
    """

    # Regime × 风格 矩阵
    REGIME_STYLE_MATRIX: dict[tuple[str, str], float] = {
        ("Recovery", "growth"): 90,
        ("Recovery", "value"): 75,
        ("Recovery", "blend"): 80,
        ("Recovery", "quality"): 85,
        ("Recovery", "defensive"): 60,
        ("Overheat", "value"): 85,
        ("Overheat", "growth"): 70,
        ("Overheat", "blend"): 75,
        ("Overheat", "quality"): 80,
        ("Overheat", "defensive"): 65,
        ("Stagflation", "defensive"): 90,
        ("Stagflation", "quality"): 85,
        ("Stagflation", "growth"): 40,
        ("Stagflation", "value"): 70,
        ("Stagflation", "blend"): 60,
        ("Deflation", "defensive"): 85,
        ("Deflation", "value"): 80,
        ("Deflation", "growth"): 50,
        ("Deflation", "quality"): 90,
        ("Deflation", "blend"): 70,
    }

    # Regime × 资产类型 矩阵
    REGIME_ASSET_TYPE_MATRIX: dict[tuple[str, str], float] = {
        ("Recovery", "equity"): 90,
        ("Recovery", "fund"): 85,
        ("Recovery", "bond"): 50,
        ("Recovery", "commodity"): 75,
        ("Recovery", "index"): 88,
        ("Overheat", "equity"): 70,
        ("Overheat", "fund"): 75,
        ("Overheat", "bond"): 80,
        ("Overheat", "commodity"): 90,
        ("Overheat", "index"): 72,
        ("Stagflation", "equity"): 30,
        ("Stagflation", "fund"): 40,
        ("Stagflation", "bond"): 90,
        ("Stagflation", "commodity"): 85,
        ("Stagflation", "index"): 35,
        ("Deflation", "equity"): 40,
        ("Deflation", "fund"): 50,
        ("Deflation", "bond"): 85,
        ("Deflation", "commodity"): 45,
        ("Deflation", "index"): 42,
    }

    @classmethod
    def match(cls, asset: AssetScore, current_regime: str) -> float:
        """
        计算 Regime 匹配得分

        Args:
            asset: 资产评分实体
            current_regime: 当前 Regime（Recovery/Overheat/Stagflation/Deflation）

        Returns:
            匹配得分（0-100）
        """
        score = 0.0

        # 1. 资产类型匹配（权重 60%）
        type_score = cls.REGIME_ASSET_TYPE_MATRIX.get(
            (current_regime, asset.asset_type.value),
            50
        )
        score += type_score * 0.6

        # 2. 风格匹配（权重 40%）
        if asset.style:
            style_score = cls.REGIME_STYLE_MATRIX.get(
                (current_regime, asset.style.value),
                60
            )
            score += style_score * 0.4
        else:
            # 无风格信息时，使用平均得分
            score += 70 * 0.4

        # 3. 行业调整（权重 10%，可选加分项）
        if asset.sector:
            sector_score = cls._get_sector_regime_score(asset.sector, current_regime)
            score += sector_score * 0.1

        return min(100.0, max(0.0, score))

    @staticmethod
    def _get_sector_regime_score(sector: str, regime: str) -> float:
        """
        行业 Regime 匹配得分

        Args:
            sector: 行业名称
            regime: Regime 类型

        Returns:
            行业匹配得分（0-100）
        """
        SECTOR_REGIME_SCORE: dict[tuple[str, str], float] = {
            # Recovery 行业偏好
            ("金融", "Recovery"): 85,
            ("科技", "Recovery"): 95,
            ("消费", "Recovery"): 80,
            ("工业", "Recovery"): 88,
            ("材料", "Recovery"): 82,

            # Overheat 行业偏好
            ("能源", "Overheat"): 90,
            ("材料", "Overheat"): 88,
            ("金融", "Overheat"): 75,

            # Stagflation 行业偏好
            ("医药", "Stagflation"): 85,
            ("公用事业", "Stagflation"): 90,
            ("消费", "Stagflation"): 70,

            # Deflation 行业偏好
            ("公用事业", "Deflation"): 90,
            ("金融", "Deflation"): 75,
            ("消费", "Deflation"): 80,
        }

        return SECTOR_REGIME_SCORE.get((sector, regime), 70)


class PolicyMatcher:
    """
    Policy 档位匹配器（通用）

    根据政策档位和资产类型计算匹配得分。
    Policy 档位：P0（宽松）/ P1（中性偏松）/ P2（中性偏紧）/ P3（紧缩）
    """

    # Policy × 资产类型 矩阵
    POLICY_ASSET_TYPE_MATRIX: dict[tuple[str, str], float] = {
        ("P0", "equity"): 90,
        ("P0", "fund"): 90,
        ("P0", "bond"): 70,
        ("P0", "commodity"): 80,
        ("P0", "index"): 88,
        ("P1", "equity"): 70,
        ("P1", "fund"): 75,
        ("P1", "bond"): 85,
        ("P1", "commodity"): 75,
        ("P1", "index"): 72,
        ("P2", "equity"): 30,
        ("P2", "fund"): 40,
        ("P2", "bond"): 95,
        ("P2", "commodity"): 50,
        ("P2", "index"): 35,
        ("P3", "equity"): 10,
        ("P3", "fund"): 20,
        ("P3", "bond"): 90,
        ("P3", "commodity"): 40,
        ("P3", "index"): 15,
    }

    @classmethod
    def match(cls, asset: AssetScore, policy_level: str) -> float:
        """
        计算 Policy 匹配得分

        Args:
            asset: 资产评分实体
            policy_level: 政策档位（P0/P1/P2/P3）

        Returns:
            匹配得分（0-100）
        """
        base_score = cls.POLICY_ASSET_TYPE_MATRIX.get(
            (policy_level, asset.asset_type.value),
            50
        )

        # 根据风险等级调整
        risk_adjustment = {
            "P0": 1.0,
            "P1": 0.9,
            "P2": 0.75,
            "P3": 0.6,
        }.get(policy_level, 1.0)

        return min(100.0, base_score * risk_adjustment)


class SentimentMatcher:
    """
    舆情情绪匹配器（通用）

    根据市场情绪指数和资产类型计算匹配得分。
    情绪指数范围：-3.0（极度悲观）到 +3.0（极度乐观）
    """

    @classmethod
    def match(cls, asset: AssetScore, sentiment_index: float) -> float:
        """
        计算情绪匹配得分

        Args:
            asset: 资产评分实体
            sentiment_index: 情绪指数（-3.0 ~ +3.0）

        Returns:
            匹配得分（0-100）
        """
        # 股票/基金/指数在情绪高涨时受益
        if asset.asset_type in [AssetType.EQUITY, AssetType.FUND, AssetType.INDEX]:
            # 情绪指数 +1 ~ +3 时得分高
            if sentiment_index > 1:
                return min(100.0, 60 + (sentiment_index - 1) * 15)
            # 情绪指数 -1 ~ +1 时中等
            elif sentiment_index > -1:
                return 50 + sentiment_index * 10
            # 情绪指数低时得分低
            else:
                return max(0.0, 40 + (sentiment_index + 3) * 10)

        # 债券/防御性资产在情绪低落时受益（避险）
        elif asset.asset_type in [AssetType.BOND]:
            if sentiment_index < -1:
                return min(100.0, 60 + (-sentiment_index - 1) * 15)
            else:
                return max(0.0, 50 - sentiment_index * 10)

        # 商品在极端情绪（无论正负）时受益（避险/投机）
        elif asset.asset_type == AssetType.COMMODITY:
            abs_sentiment = abs(sentiment_index)
            if abs_sentiment > 2:
                return 80
            elif abs_sentiment > 1:
                return 65
            else:
                return 50

        return 50.0


class SignalMatcher:
    """
    投资信号匹配器（通用）

    根据激活的投资信号和资产匹配度计算得分。
    """

    @classmethod
    def match(cls, asset: AssetScore, active_signals: list) -> float:
        """
        计算信号匹配得分

        Args:
            asset: 资产评分实体
            active_signals: 激活的投资信号列表

        Returns:
            匹配得分（0-100）
        """
        if not active_signals:
            return 50.0  # 无信号时中性

        match_count = 0
        for signal in active_signals:
            if cls._is_signal_match_asset(signal, asset):
                match_count += 1

        # 根据匹配信号数量评分
        if match_count >= 3:
            return 90.0
        elif match_count >= 2:
            return 75.0
        elif match_count >= 1:
            return 60.0
        else:
            return 40.0

    @staticmethod
    def _is_signal_match_asset(signal, asset: AssetScore) -> bool:
        """
        判断信号是否匹配资产

        Args:
            signal: 投资信号对象（需有 asset_code/asset_class/sector 属性）
            asset: 资产评分实体

        Returns:
            是否匹配
        """
        # 精确匹配
        if hasattr(signal, 'asset_code') and signal.asset_code == asset.asset_code:
            return True

        # 资产类别匹配
        if hasattr(signal, 'asset_class') and signal.asset_class == asset.asset_type.value:
            return True

        # 行业匹配
        if asset.sector and hasattr(signal, 'sector') and signal.sector == asset.sector:
            return True

        return False
