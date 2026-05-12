"""
Unit tests for Attribution services in Audit module domain layer.

Tests for:
- analyze_attribution() function
- _build_regime_periods()
- _calculate_period_performances()
- _heuristic_pnl_decomposition()
- _identify_loss_source()
- _generate_lessons()
- _calculate_total_transaction_cost()
- _build_period_attributions()
"""

from datetime import date, timedelta
from unittest.mock import Mock

import pytest

from apps.audit.domain.entities import (
    AttributionConfig,
    AttributionMethod,
    AttributionResult,
    LossSource,
    PeriodPerformance,
    RegimePeriod,
)
from apps.audit.domain.services import (
    _build_period_attributions,
    _build_regime_periods,
    _calculate_period_performances,
    _calculate_total_transaction_cost,
    _generate_lessons,
    _heuristic_pnl_decomposition,
    _identify_loss_source,
    analyze_attribution,
)

# ============ Fixtures ============

@pytest.fixture
def sample_regime_history():
    """Create sample regime history."""
    return [
        {"date": date(2024, 1, 1), "regime": "RECOVERY", "confidence": 0.85},
        {"date": date(2024, 2, 1), "regime": "RECOVERY", "confidence": 0.88},
        {"date": date(2024, 3, 1), "regime": "OVERHEAT", "confidence": 0.75},
        {"date": date(2024, 4, 1), "regime": "OVERHEAT", "confidence": 0.80},
        {"date": date(2024, 5, 1), "regime": "SLOWDOWN", "confidence": 0.60},
    ]


@pytest.fixture
def sample_equity_curve():
    """Create sample equity curve."""
    return [
        (date(2024, 1, 1), 100000.0),
        (date(2024, 2, 1), 105000.0),
        (date(2024, 3, 1), 108000.0),
        (date(2024, 4, 1), 112000.0),
        (date(2024, 5, 1), 110000.0),
    ]


@pytest.fixture
def sample_asset_returns():
    """Create sample asset returns."""
    base_date = date(2024, 1, 1)
    return {
        "equity": [(base_date + timedelta(days=d), 0.01 + d * 0.001) for d in range(120)],
        "bond": [(base_date + timedelta(days=d), 0.005 + d * 0.0005) for d in range(120)],
        "gold": [(base_date + timedelta(days=d), 0.008 + d * 0.0008) for d in range(120)],
    }


@pytest.fixture
def sample_periods():
    """Create sample RegimePeriods."""
    return [
        RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 29),
            regime="RECOVERY",
            confidence=0.85
        ),
        RegimePeriod(
            start_date=date(2024, 3, 1),
            end_date=date(2024, 4, 30),
            regime="OVERHEAT",
            confidence=0.75
        ),
        RegimePeriod(
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 31),
            regime="SLOWDOWN",
            confidence=0.60
        ),
    ]


@pytest.fixture
def sample_performances():
    """Create sample PeriodPerformances."""
    periods = [
        RegimePeriod(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 29),
            regime="RECOVERY",
            confidence=0.85
        ),
        RegimePeriod(
            start_date=date(2024, 3, 1),
            end_date=date(2024, 4, 30),
            regime="OVERHEAT",
            confidence=0.75
        ),
        RegimePeriod(
            start_date=date(2024, 5, 1),
            end_date=date(2024, 5, 31),
            regime="SLOWDOWN",
            confidence=0.25
        ),
    ]

    return [
        PeriodPerformance(
            period=periods[0],
            portfolio_return=0.05,
            benchmark_return=0.03,
            best_asset_return=0.08,
            worst_asset_return=0.01,
            asset_returns={"equity": 0.08, "bond": 0.01, "gold": 0.02}
        ),
        PeriodPerformance(
            period=periods[1],
            portfolio_return=0.04,
            benchmark_return=0.035,
            best_asset_return=0.06,
            worst_asset_return=0.02,
            asset_returns={"equity": 0.06, "bond": 0.02, "gold": 0.03}
        ),
        PeriodPerformance(
            period=periods[2],
            portfolio_return=-0.03,
            benchmark_return=-0.01,
            best_asset_return=0.01,
            worst_asset_return=-0.05,
            asset_returns={"equity": 0.01, "bond": -0.02, "gold": -0.05}
        ),
    ]


# ============ Test _build_regime_periods ============

class TestBuildRegimePeriods:
    """Test _build_regime_periods function."""

    def test_empty_history(self):
        """Test with empty regime history."""
        result = _build_regime_periods([])
        assert result == []

    def test_single_regime(self):
        """Test with single regime entry."""
        history = [
            {"date": date(2024, 1, 1), "regime": "RECOVERY", "confidence": 0.85}
        ]
        result = _build_regime_periods(history)
        assert len(result) == 1
        assert result[0].regime == "RECOVERY"
        assert result[0].start_date == date(2024, 1, 1)
        assert result[0].end_date == date(2024, 1, 1)
        assert result[0].confidence == 0.85

    def test_multiple_same_regime(self):
        """Test with multiple same regime entries."""
        history = [
            {"date": date(2024, 1, 1), "regime": "RECOVERY", "confidence": 0.85},
            {"date": date(2024, 2, 1), "regime": "RECOVERY", "confidence": 0.88},
        ]
        result = _build_regime_periods(history)
        assert len(result) == 1
        assert result[0].regime == "RECOVERY"
        assert result[0].start_date == date(2024, 1, 1)
        assert result[0].end_date == date(2024, 2, 1)

    def test_regime_change(self):
        """Test with regime changes."""
        history = [
            {"date": date(2024, 1, 1), "regime": "RECOVERY", "confidence": 0.85},
            {"date": date(2024, 2, 1), "regime": "OVERHEAT", "confidence": 0.75},
            {"date": date(2024, 3, 1), "regime": "SLOWDOWN", "confidence": 0.60},
        ]
        result = _build_regime_periods(history)
        assert len(result) == 3

        # First period
        assert result[0].regime == "RECOVERY"
        assert result[0].start_date == date(2024, 1, 1)
        assert result[0].end_date == date(2024, 2, 1)

        # Second period
        assert result[1].regime == "OVERHEAT"
        assert result[1].start_date == date(2024, 2, 1)
        assert result[1].end_date == date(2024, 3, 1)

        # Third period
        assert result[2].regime == "SLOWDOWN"
        assert result[2].start_date == date(2024, 3, 1)
        assert result[2].end_date == date(2024, 3, 1)

    def test_missing_confidence(self):
        """Test with missing confidence field."""
        history = [
            {"date": date(2024, 1, 1), "regime": "RECOVERY"},
        ]
        result = _build_regime_periods(history)
        assert len(result) == 1
        assert result[0].confidence == 0.0  # Default value

    def test_full_history(self, sample_regime_history):
        """Test with full sample history."""
        result = _build_regime_periods(sample_regime_history)
        assert len(result) == 3
        assert result[0].regime == "RECOVERY"
        assert result[1].regime == "OVERHEAT"
        assert result[2].regime == "SLOWDOWN"


# ============ Test _calculate_period_performances ============

class TestCalculatePeriodPerformances:
    """Test _calculate_period_performances function."""

    def test_empty_periods(self, sample_equity_curve, sample_asset_returns):
        """Test with empty periods list."""
        result = _calculate_period_performances([], sample_equity_curve, sample_asset_returns)
        assert result == []

    def test_single_period(self, sample_equity_curve, sample_asset_returns):
        """Test with single period."""
        periods = [
            RegimePeriod(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                regime="RECOVERY"
            )
        ]
        result = _calculate_period_performances(periods, sample_equity_curve, sample_asset_returns)
        assert len(result) == 1
        assert isinstance(result[0], PeriodPerformance)
        assert result[0].period == periods[0]

    def test_portfolio_return_calculation(self, sample_equity_curve, sample_asset_returns):
        """Test portfolio return calculation."""
        periods = [
            RegimePeriod(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 2, 1),
                regime="RECOVERY"
            )
        ]
        result = _calculate_period_performances(periods, sample_equity_curve, sample_asset_returns)
        # Return = (105000 - 100000) / 100000 = 0.05
        assert abs(result[0].portfolio_return - 0.05) < 0.001

    def test_benchmark_return_calculation(self, sample_equity_curve, sample_asset_returns):
        """Test benchmark return calculation (average of assets)."""
        periods = [
            RegimePeriod(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 2, 1),
                regime="RECOVERY"
            )
        ]
        result = _calculate_period_performances(periods, sample_equity_curve, sample_asset_returns)
        # Should be average of asset returns in the period
        assert isinstance(result[0].benchmark_return, float)

    def test_asset_returns_dict(self, sample_equity_curve, sample_asset_returns):
        """Test asset returns dictionary is populated."""
        periods = [
            RegimePeriod(
                start_date=date(2024, 1, 1),
                end_date=date(2024, 1, 31),
                regime="RECOVERY"
            )
        ]
        result = _calculate_period_performances(periods, sample_equity_curve, sample_asset_returns)
        assert "equity" in result[0].asset_returns
        assert "bond" in result[0].asset_returns
        assert "gold" in result[0].asset_returns

    def test_missing_equity_data(self):
        """Test with missing equity data for period."""
        periods = [
            RegimePeriod(
                start_date=date(2024, 12, 1),  # Not in equity curve
                end_date=date(2024, 12, 31),
                regime="RECOVERY"
            )
        ]
        result = _calculate_period_performances(periods, sample_equity_curve, [])
        assert len(result) == 0  # Should skip periods with missing data


# ============ Test _heuristic_pnl_decomposition ============

class TestHeuristicPnlDecomposition:
    """Test _heuristic_pnl_decomposition function."""

    def test_empty_performances(self):
        """Test with empty performances list."""
        timing, selection, interaction = _heuristic_pnl_decomposition([])
        assert timing == 0.0
        assert selection == 0.0
        assert interaction == 0.0

    def test_all_positive_returns(self, sample_performances):
        """Test with all positive returns."""
        # Modify to all positive
        positive_performances = sample_performances[:2]  # First two are positive
        timing, selection, interaction = _heuristic_pnl_decomposition(positive_performances)

        # Timing should be 30% of positive returns
        expected_timing = 0.05 * 0.3 + 0.04 * 0.3
        assert abs(timing - expected_timing) < 0.001

        # Selection should be 50% of excess returns
        expected_selection = (0.05 - 0.03) * 0.5 + (0.04 - 0.035) * 0.5
        assert abs(selection - expected_selection) < 0.001

    def test_mixed_returns(self, sample_performances):
        """Test with mixed positive and negative returns."""
        timing, selection, interaction = _heuristic_pnl_decomposition(sample_performances)

        # Only positive returns contribute to timing
        assert timing > 0  # First two periods have positive returns

        # Only positive excess returns contribute to selection
        assert selection >= 0

    def test_all_negative_returns(self):
        """Test with all negative returns."""
        negative_performances = [
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 2, 1),
                    regime="SLOWDOWN"
                ),
                portfolio_return=-0.05,
                benchmark_return=-0.03,
                best_asset_return=-0.01,
                worst_asset_return=-0.10,
                asset_returns={"equity": -0.01, "bond": -0.05, "gold": -0.10}
            ),
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 2, 1),
                    end_date=date(2024, 3, 1),
                    regime="SLOWDOWN"
                ),
                portfolio_return=-0.03,
                benchmark_return=-0.02,
                best_asset_return=0.0,
                worst_asset_return=-0.08,
                asset_returns={"equity": 0.0, "bond": -0.03, "gold": -0.08}
            ),
        ]
        timing, selection, interaction = _heuristic_pnl_decomposition(negative_performances)

        # No positive returns means no timing contribution
        assert timing == 0.0

        # No positive excess returns means no selection contribution
        assert selection == 0.0

        # All returns are negative
        assert interaction < 0

    def test_pnl_sum_matches_total(self, sample_performances):
        """Test that PnL components sum to total return."""
        timing, selection, interaction = _heuristic_pnl_decomposition(sample_performances)
        total_return = sum(p.portfolio_return for p in sample_performances)
        sum_components = timing + selection + interaction

        # The heuristic doesn't guarantee exact equality, but should be close
        # because interaction = total - timing - selection
        assert abs(sum_components - total_return) < 0.01


# ============ Test _identify_loss_source ============

class TestIdentifyLossSource:
    """Test _identify_loss_source function."""

    def test_no_losses(self):
        """Test with no losing periods."""
        all_positive = [
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 2, 1),
                    regime="RECOVERY",
                    confidence=0.8
                ),
                portfolio_return=0.05,
                benchmark_return=0.03,
                best_asset_return=0.08,
                worst_asset_return=0.01,
                asset_returns={"equity": 0.08, "bond": 0.01}
            ),
        ]
        source, amount, periods = _identify_loss_source(all_positive)
        assert source == LossSource.UNKNOWN
        assert amount == 0.0
        assert len(periods) == 0

    def test_regime_timing_error(self):
        """Test identification of regime timing error."""
        # Low confidence losses indicate regime timing issues
        low_conf_losses = [
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 2, 1),
                    regime="RECOVERY",
                    confidence=0.2  # Low confidence
                ),
                portfolio_return=-0.02,
                benchmark_return=0.01,
                best_asset_return=0.05,
                worst_asset_return=-0.03,
                asset_returns={"equity": 0.05, "bond": -0.03}
            ),
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 2, 1),
                    end_date=date(2024, 3, 1),
                    regime="RECOVERY",
                    confidence=0.25  # Low confidence
                ),
                portfolio_return=-0.03,
                benchmark_return=0.01,
                best_asset_return=0.04,
                worst_asset_return=-0.05,
                asset_returns={"equity": 0.04, "bond": -0.05}
            ),
        ]
        source, amount, periods = _identify_loss_source(low_conf_losses)
        assert source == LossSource.REGIME_TIMING_ERROR
        assert amount < 0
        assert len(periods) == 2

    def test_market_volatility(self):
        """Test identification of market volatility loss."""
        # Large loss (>5%) indicates market volatility
        large_loss = [
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 2, 1),
                    regime="SLOWDOWN",
                    confidence=0.7
                ),
                portfolio_return=-0.08,  # > 5% loss
                benchmark_return=-0.05,
                best_asset_return=-0.02,
                worst_asset_return=-0.15,
                asset_returns={"equity": -0.02, "bond": -0.15}
            ),
        ]
        source, amount, periods = _identify_loss_source(large_loss)
        assert source == LossSource.MARKET_VOLATILITY
        assert amount < -0.05

    def test_asset_selection_error(self):
        """Test identification of asset selection error."""
        # Small loss with decent confidence indicates asset selection issue
        selection_loss = [
            PeriodPerformance(
                period=RegimePeriod(
                    start_date=date(2024, 1, 1),
                    end_date=date(2024, 2, 1),
                    regime="RECOVERY",
                    confidence=0.7  # Good confidence
                ),
                portfolio_return=-0.02,  # Small loss
                benchmark_return=0.03,
                best_asset_return=0.08,
                worst_asset_return=-0.01,
                asset_returns={"equity": 0.08, "bond": -0.01}
            ),
        ]
        source, amount, periods = _identify_loss_source(selection_loss)
        assert source == LossSource.ASSET_SELECTION_ERROR

    def test_loss_calculation(self, sample_performances):
        """Test loss amount calculation."""
        source, amount, periods = _identify_loss_source(sample_performances)
        # Only third period has negative return (-0.03)
        assert abs(amount - (-0.03)) < 0.001
        assert len(periods) == 1


# ============ Test _generate_lessons ============

class TestGenerateLessons:
    """Test _generate_lessons function."""

    def test_regime_timing_lessons(self):
        """Test lessons for regime timing error."""
        lesson, suggestions = _generate_lessons([], LossSource.REGIME_TIMING_ERROR)
        assert "Regime 判断" in lesson
        assert len(suggestions) == 3
        assert any("置信度" in s for s in suggestions)
        assert any("仓位" in s for s in suggestions)

    def test_asset_selection_lessons(self):
        """Test lessons for asset selection error."""
        lesson, suggestions = _generate_lessons([], LossSource.ASSET_SELECTION_ERROR)
        assert "资产选择" in lesson
        assert len(suggestions) == 3
        assert any("准入矩阵" in s for s in suggestions)
        assert any("分散" in s for s in suggestions)

    def test_market_volatility_lessons(self):
        """Test lessons for market volatility."""
        lesson, suggestions = _generate_lessons([], LossSource.MARKET_VOLATILITY)
        assert "市场剧烈波动" in lesson
        assert len(suggestions) == 3
        assert any("止损" in s for s in suggestions)
        assert any("波动率" in s for s in suggestions)

    def test_unknown_lessons(self):
        """Test lessons for unknown/default case."""
        lesson, suggestions = _generate_lessons([], LossSource.UNKNOWN)
        assert "整体表现良好" in lesson
        assert len(suggestions) == 2

    def test_policy_intervention_lessons(self):
        """Test lessons for policy intervention."""
        lesson, suggestions = _generate_lessons([], LossSource.POLICY_INTERVENTION)
        # Should fall through to default case
        assert len(suggestions) >= 2


# ============ Test _calculate_total_transaction_cost ============

class TestCalculateTotalTransactionCost:
    """Test _calculate_total_transaction_cost function."""

    def test_empty_trades(self):
        """Test with empty trades list."""
        result = _calculate_total_transaction_cost([])
        assert result == 0.0

    def test_single_trade(self):
        """Test with single trade."""
        trade = Mock()
        trade.cost = 10.5
        result = _calculate_total_transaction_cost([trade])
        assert result == 10.5

    def test_multiple_trades(self):
        """Test with multiple trades."""
        trades = [Mock(cost=5.0), Mock(cost=10.0), Mock(cost=7.5)]
        result = _calculate_total_transaction_cost(trades)
        assert result == 22.5

    def test_zero_cost_trades(self):
        """Test with zero cost trades."""
        trades = [Mock(cost=0.0), Mock(cost=0.0)]
        result = _calculate_total_transaction_cost(trades)
        assert result == 0.0

    def test_negative_cost_trades(self):
        """Test with negative cost (rebates)."""
        trades = [Mock(cost=10.0), Mock(cost=-2.0), Mock(cost=5.0)]
        result = _calculate_total_transaction_cost(trades)
        assert result == 13.0


# ============ Test _build_period_attributions ============

class TestBuildPeriodAttributions:
    """Test _build_period_attributions function."""

    def test_empty_performances(self):
        """Test with empty performances."""
        result = _build_period_attributions([])
        assert result == []

    def test_single_period(self, sample_performances):
        """Test with single performance."""
        result = _build_period_attributions([sample_performances[0]])
        assert len(result) == 1
        assert result[0]["regime"] == "RECOVERY"
        assert "portfolio_return" in result[0]
        assert "benchmark_return" in result[0]
        assert "excess_return" in result[0]

    def test_multiple_periods(self, sample_performances):
        """Test with multiple performances."""
        result = _build_period_attributions(sample_performances)
        assert len(result) == 3

    def test_excess_return_calculation(self, sample_performances):
        """Test excess return is calculated correctly."""
        result = _build_period_attributions([sample_performances[0]])
        expected_excess = 0.05 - 0.03  # portfolio - benchmark
        assert abs(result[0]["excess_return"] - expected_excess) < 0.001

    def test_all_fields_present(self, sample_performances):
        """Test all expected fields are present."""
        result = _build_period_attributions([sample_performances[0]])
        expected_keys = {
            "start_date", "end_date", "regime", "confidence",
            "portfolio_return", "benchmark_return", "excess_return",
            "asset_returns"
        }
        assert set(result[0].keys()) == expected_keys

    def test_asset_returns_included(self, sample_performances):
        """Test asset returns dictionary is included."""
        result = _build_period_attributions([sample_performances[0]])
        assert "asset_returns" in result[0]
        assert isinstance(result[0]["asset_returns"], dict)


# ============ Test analyze_attribution (integration) ============

class TestAnalyzeAttribution:
    """Test analyze_attribution function."""

    @pytest.fixture
    def mock_backtest_result(self):
        """Create mock backtest result."""
        result = Mock()
        result.total_return = 0.10
        result.equity_curve = [
            (date(2024, 1, 1), 100000.0),
            (date(2024, 2, 1), 105000.0),
            (date(2024, 3, 1), 108000.0),
        ]
        result.trades = [Mock(cost=5.0), Mock(cost=3.0)]
        return result

    def test_full_attribution_analysis(
        self,
        mock_backtest_result,
        sample_regime_history,
        sample_asset_returns
    ):
        """Test full attribution analysis."""
        result = analyze_attribution(
            mock_backtest_result,
            sample_regime_history,
            sample_asset_returns
        )

        assert isinstance(result, AttributionResult)
        assert result.total_return == 0.10
        assert result.transaction_cost_pnl == 8.0  # 5 + 3
        # Verify attribution method is set (Issue #4 fix)
        assert result.attribution_method == AttributionMethod.HEURISTIC

    def test_default_config(self, mock_backtest_result, sample_regime_history, sample_asset_returns):
        """Test with default configuration."""
        result = analyze_attribution(
            mock_backtest_result,
            sample_regime_history,
            sample_asset_returns
        )
        # Should use default config with HEURISTIC method
        assert isinstance(result, AttributionResult)
        assert result.attribution_method == AttributionMethod.HEURISTIC

    def test_custom_config(self, mock_backtest_result, sample_regime_history, sample_asset_returns):
        """Test with custom configuration."""
        custom_config = AttributionConfig(
            risk_free_rate=0.025,
            benchmark_return=0.10,
            attribution_method=AttributionMethod.BRINSON  # Use Brinson method
        )
        result = analyze_attribution(
            mock_backtest_result,
            sample_regime_history,
            sample_asset_returns,
            custom_config
        )
        assert isinstance(result, AttributionResult)
        # Verify the method is passed through
        assert result.attribution_method == AttributionMethod.BRINSON

    def test_empty_regime_history(self, mock_backtest_result):
        """Test with empty regime history."""
        result = analyze_attribution(
            mock_backtest_result,
            [],
            {}
        )
        # Should return result with empty period_attributions
        assert isinstance(result, AttributionResult)
        assert result.period_attributions == []
        # Method should still be set
        assert result.attribution_method == AttributionMethod.HEURISTIC

    def test_lesson_and_suggestions_generated(
        self,
        mock_backtest_result,
        sample_regime_history,
        sample_asset_returns
    ):
        """Test that lessons and suggestions are generated."""
        result = analyze_attribution(
            mock_backtest_result,
            sample_regime_history,
            sample_asset_returns
        )
        assert result.lesson_learned
        assert len(result.improvement_suggestions) > 0
        # Attribution method should be set
        assert hasattr(result, 'attribution_method')
