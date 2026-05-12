"""
板块轮动分析单元测试

测试 Domain 层的 SectorRotationAnalyzer 服务
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.sector.domain.entities import SectorIndex, SectorInfo, SectorRelativeStrength
from apps.sector.domain.services import SectorRotationAnalyzer


class TestSectorRotationAnalyzer:
    """板块轮动分析器测试"""

    def test_calculate_momentum(self):
        """测试动量计算"""
        analyzer = SectorRotationAnalyzer()

        # 测试数据：5 天的收益率
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]

        momentum = analyzer.calculate_momentum(returns, lookback_days=5)

        # 验证：累计收益率为正
        assert momentum > 0

        # 手动计算预期值：(1.01 * 1.02 * 0.99 * 1.03 * 1.01 - 1) * 100
        expected = (1.01 * 1.02 * 0.99 * 1.03 * 1.01 - 1) * 100
        assert abs(momentum - expected) < 0.01

    def test_calculate_relative_strength(self):
        """测试相对强弱计算"""
        analyzer = SectorRotationAnalyzer()

        sector_returns = {
            date(2024, 1, 2): 0.02,
            date(2024, 1, 3): 0.01,
            date(2024, 1, 4): -0.01
        }
        market_returns = {
            date(2024, 1, 2): 0.01,
            date(2024, 1, 3): 0.005,
            date(2024, 1, 4): -0.02
        }

        rs = analyzer.calculate_relative_strength(sector_returns, market_returns)

        assert len(rs) == 3
        assert rs[date(2024, 1, 2)] == 0.01  # 0.02 - 0.01
        assert rs[date(2024, 1, 3)] == 0.005  # 0.01 - 0.005
        assert rs[date(2024, 1, 4)] == 0.01  # -0.01 - (-0.02)

    def test_normalize_score(self):
        """测试评分归一化"""
        analyzer = SectorRotationAnalyzer()

        # 测试边界值
        score1 = analyzer._normalize_score(5.0, -10.0, 10.0)
        assert score1 == 75.0

        score2 = analyzer._normalize_score(-5.0, -10.0, 10.0)
        assert score2 == 25.0

        # 测试超出边界
        score3 = analyzer._normalize_score(15.0, -10.0, 10.0)
        assert score3 == 100.0

        score4 = analyzer._normalize_score(-15.0, -10.0, 10.0)
        assert score4 == 0.0

    def test_rank_sectors_by_regime(self):
        """测试板块排名"""
        analyzer = SectorRotationAnalyzer()

        # 准备测试数据
        sectors_data = [
            (
                SectorInfo('801010', '农林牧渔', 'SW1'),
                SectorIndex('801010', date(2024, 1, 2),
                          Decimal('1000'), Decimal('1010'), Decimal('990'),
                          Decimal('1005'), 1000000, Decimal('10000000'), 0.5),
                SectorRelativeStrength('801010', date(2024, 1, 2), 0.5, 5.0)
            ),
            (
                SectorInfo('801020', '采掘', 'SW1'),
                SectorIndex('801020', date(2024, 1, 2),
                          Decimal('1000'), Decimal('1010'), Decimal('990'),
                          Decimal('1003'), 1000000, Decimal('10000000'), 0.3),
                SectorRelativeStrength('801020', date(2024, 1, 2), 0.3, 3.0)
            )
        ]

        regime_weights = {
            '801010': 0.8,
            '801020': 0.6
        }

        scores = analyzer.rank_sectors_by_regime(
            sectors_data=sectors_data,
            regime_weights=regime_weights
        )

        # 验证结果
        assert len(scores) == 2
        assert scores[0].rank == 1
        assert scores[0].sector_code == '801010'  # 应该是农林牧渔（动量和权重都更高）
        assert scores[1].rank == 2

    def test_calculate_beta(self):
        """测试贝塔系数计算"""
        analyzer = SectorRotationAnalyzer()

        sector_returns = [0.02, 0.01, -0.01, 0.03, 0.01]
        market_returns = [0.01, 0.005, -0.005, 0.02, 0.01]

        beta = analyzer.calculate_beta(sector_returns, market_returns)

        # Beta 应该在合理范围内（0.5 - 2.0）
        assert 0.5 < beta < 2.0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
