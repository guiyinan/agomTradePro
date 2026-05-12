"""
Tests for apps.sector.domain.services — SectorRotationAnalyzer

Pure-Python tests: no Django, pandas, or numpy imports.
Uses factory helpers from tests.factories.domain_factories.
"""

from datetime import date

import pytest

from apps.sector.domain.entities import (
    SectorIndex,
    SectorInfo,
    SectorRelativeStrength,
)
from apps.sector.domain.services import SectorRotationAnalyzer
from tests.factories.domain_factories import (
    make_sector_index,
    make_sector_info,
    make_sector_relative_strength,
)


@pytest.fixture
def analyzer() -> SectorRotationAnalyzer:
    return SectorRotationAnalyzer()


# ============================================================
# calculate_relative_strength
# ============================================================


class TestCalculateRelativeStrength:
    """Tests for SectorRotationAnalyzer.calculate_relative_strength"""

    def test_basic_relative_strength(self, analyzer: SectorRotationAnalyzer) -> None:
        """Relative strength = sector return - market return."""
        d1 = date(2024, 1, 2)
        d2 = date(2024, 1, 3)
        sector_returns = {d1: 0.02, d2: 0.01}
        market_returns = {d1: 0.01, d2: 0.005}

        result = analyzer.calculate_relative_strength(sector_returns, market_returns)

        assert result[d1] == pytest.approx(0.01)
        assert result[d2] == pytest.approx(0.005)

    def test_missing_market_date_defaults_to_zero(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """When market has no data for a date, market return defaults to 0."""
        d1 = date(2024, 1, 2)
        sector_returns = {d1: 0.03}
        market_returns: dict[date, float] = {}

        result = analyzer.calculate_relative_strength(sector_returns, market_returns)

        assert result[d1] == pytest.approx(0.03)

    def test_empty_sector_returns(self, analyzer: SectorRotationAnalyzer) -> None:
        """Empty sector returns produces empty result."""
        result = analyzer.calculate_relative_strength({}, {date(2024, 1, 2): 0.01})
        assert result == {}

    def test_negative_relative_strength(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Sector underperforming market yields negative RS."""
        d1 = date(2024, 1, 2)
        sector_returns = {d1: -0.01}
        market_returns = {d1: 0.02}

        result = analyzer.calculate_relative_strength(sector_returns, market_returns)

        assert result[d1] == pytest.approx(-0.03)

    def test_zero_returns(self, analyzer: SectorRotationAnalyzer) -> None:
        """Both zero returns yields zero RS."""
        d1 = date(2024, 1, 2)
        result = analyzer.calculate_relative_strength({d1: 0.0}, {d1: 0.0})
        assert result[d1] == pytest.approx(0.0)


# ============================================================
# calculate_momentum
# ============================================================


class TestCalculateMomentum:
    """Tests for SectorRotationAnalyzer.calculate_momentum"""

    def test_basic_momentum(self, analyzer: SectorRotationAnalyzer) -> None:
        """Cumulative return of [0.01, 0.02, -0.01, 0.03, 0.01] * 100."""
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]
        momentum = analyzer.calculate_momentum(returns, lookback_days=5)
        expected = ((1.01 * 1.02 * 0.99 * 1.03 * 1.01) - 1.0) * 100
        assert momentum == pytest.approx(expected, abs=1e-4)

    def test_empty_returns(self, analyzer: SectorRotationAnalyzer) -> None:
        """Empty returns list yields 0."""
        assert analyzer.calculate_momentum([]) == 0.0

    def test_single_return(self, analyzer: SectorRotationAnalyzer) -> None:
        """Single return produces that return * 100."""
        result = analyzer.calculate_momentum([0.05], lookback_days=20)
        assert result == pytest.approx(5.0, abs=1e-4)

    def test_lookback_truncation(self, analyzer: SectorRotationAnalyzer) -> None:
        """Only the last lookback_days entries are used."""
        returns = [0.10, 0.20, 0.01, 0.02]
        momentum = analyzer.calculate_momentum(returns, lookback_days=2)
        expected = ((1.01 * 1.02) - 1.0) * 100
        assert momentum == pytest.approx(expected, abs=1e-4)

    def test_zero_returns_list(self, analyzer: SectorRotationAnalyzer) -> None:
        """All-zero returns yield zero momentum."""
        result = analyzer.calculate_momentum([0.0, 0.0, 0.0], lookback_days=3)
        assert result == pytest.approx(0.0)

    def test_negative_returns_only(self, analyzer: SectorRotationAnalyzer) -> None:
        """Negative returns produce negative momentum."""
        returns = [-0.01, -0.02, -0.03]
        result = analyzer.calculate_momentum(returns, lookback_days=5)
        assert result < 0.0


# ============================================================
# rank_sectors_by_regime
# ============================================================


class TestRankSectorsByRegime:
    """Tests for SectorRotationAnalyzer.rank_sectors_by_regime"""

    def _make_sector_data(
        self,
        code: str,
        name: str,
        rs: float = 1.0,
        momentum: float = 2.0,
    ) -> tuple[SectorInfo, SectorIndex, SectorRelativeStrength]:
        info = make_sector_info(sector_code=code, sector_name=name)
        index = make_sector_index(sector_code=code)
        strength = make_sector_relative_strength(
            sector_code=code,
            relative_strength=rs,
            momentum=momentum,
        )
        return (info, index, strength)

    def test_single_sector_rank_is_one(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """A single sector always gets rank 1."""
        data = [self._make_sector_data("801010", "农林牧渔")]
        regime_weights = {"801010": 0.8}

        scores = analyzer.rank_sectors_by_regime(data, regime_weights)

        assert len(scores) == 1
        assert scores[0].rank == 1

    def test_multiple_sectors_ordered_by_score(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Higher score sectors get lower rank numbers."""
        data = [
            self._make_sector_data("801010", "农林牧渔", rs=5.0, momentum=10.0),
            self._make_sector_data("801020", "采掘", rs=-3.0, momentum=-5.0),
        ]
        regime_weights = {"801010": 0.9, "801020": 0.2}

        scores = analyzer.rank_sectors_by_regime(data, regime_weights)

        assert scores[0].rank == 1
        assert scores[1].rank == 2
        assert scores[0].total_score > scores[1].total_score

    def test_empty_sectors_data(self, analyzer: SectorRotationAnalyzer) -> None:
        """Empty input produces empty result."""
        scores = analyzer.rank_sectors_by_regime([], {})
        assert scores == []

    def test_default_regime_weight_for_missing_code(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Missing sector code in regime_weights defaults to 0.5."""
        data = [self._make_sector_data("801099", "未知板块")]
        regime_weights: dict[str, float] = {}

        scores = analyzer.rank_sectors_by_regime(data, regime_weights)

        assert scores[0].regime_fit_score == pytest.approx(50.0)

    def test_score_fields_populated(self, analyzer: SectorRotationAnalyzer) -> None:
        """All score fields on the result are populated."""
        data = [self._make_sector_data("801010", "农林牧渔", rs=2.0, momentum=3.0)]
        regime_weights = {"801010": 0.7}

        scores = analyzer.rank_sectors_by_regime(data, regime_weights)
        s = scores[0]

        assert s.sector_code == "801010"
        assert s.sector_name == "农林牧渔"
        assert 0.0 <= s.momentum_score <= 100.0
        assert 0.0 <= s.relative_strength_score <= 100.0
        assert s.regime_fit_score == pytest.approx(70.0)


# ============================================================
# _normalize_score
# ============================================================


class TestNormalizeScore:
    """Tests for SectorRotationAnalyzer._normalize_score"""

    def test_midpoint(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(0.0, -10.0, 10.0) == pytest.approx(50.0)

    def test_max_value(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(10.0, -10.0, 10.0) == pytest.approx(100.0)

    def test_min_value(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(-10.0, -10.0, 10.0) == pytest.approx(0.0)

    def test_equal_min_max_returns_50(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(5.0, 5.0, 5.0) == pytest.approx(50.0)

    def test_clamp_above_max(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(20.0, -10.0, 10.0) == pytest.approx(100.0)

    def test_clamp_below_min(self, analyzer: SectorRotationAnalyzer) -> None:
        assert analyzer._normalize_score(-20.0, -10.0, 10.0) == pytest.approx(0.0)


# ============================================================
# calculate_beta
# ============================================================


class TestCalculateBeta:
    """Tests for SectorRotationAnalyzer.calculate_beta"""

    def test_identical_returns_beta_one(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """When sector and market returns are identical, beta should be 1."""
        returns = [0.01, 0.02, -0.01, 0.03, 0.01]
        beta = analyzer.calculate_beta(returns, returns)
        assert beta == pytest.approx(1.0, abs=1e-6)

    def test_double_returns_beta_two(self, analyzer: SectorRotationAnalyzer) -> None:
        """Sector returns = 2x market returns => beta ~ 2."""
        market = [0.01, 0.02, -0.01, 0.03, 0.01]
        sector = [r * 2 for r in market]
        beta = analyzer.calculate_beta(sector, market)
        assert beta == pytest.approx(2.0, abs=1e-6)

    def test_mismatched_lengths_returns_default(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Different-length lists return default beta of 1.0."""
        assert analyzer.calculate_beta([0.01, 0.02], [0.01]) == 1.0

    def test_single_element_returns_default(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Less than 2 data points returns default beta of 1.0."""
        assert analyzer.calculate_beta([0.01], [0.01]) == 1.0

    def test_zero_market_variance_returns_default(
        self, analyzer: SectorRotationAnalyzer
    ) -> None:
        """Zero market variance (constant returns) returns default beta."""
        sector = [0.01, 0.02, 0.03, 0.04]
        market = [0.25, 0.25, 0.25, 0.25]
        assert analyzer.calculate_beta(sector, market) == 1.0

    def test_negative_beta(self, analyzer: SectorRotationAnalyzer) -> None:
        """Inversely correlated returns produce negative beta."""
        market = [0.01, -0.01, 0.02, -0.02, 0.01]
        sector = [-0.01, 0.01, -0.02, 0.02, -0.01]
        beta = analyzer.calculate_beta(sector, market)
        assert beta < 0.0
