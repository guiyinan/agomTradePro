"""
Factor Module Domain Layer - Services

Pure Python business logic for factor calculation and portfolio construction.
Follows four-layer architecture: NO external dependencies (no pandas, numpy, django).

Uses only:
- Python standard library (statistics, typing, dataclasses)
- Pure business algorithms
"""

from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Tuple, Callable
from bisect import bisect_right
import statistics
import math

from apps.factor.domain.entities import (
    FactorCategory,
    FactorDefinition,
    FactorExposure,
    FactorScore,
    FactorPortfolioConfig,
    FactorPortfolioHolding,
    FactorDirection,
    get_common_factors,
)


@dataclass
class FactorCalculationContext:
    """Context for factor calculation"""
    trade_date: date
    universe: List[str]  # List of stock codes
    factor_definitions: List[FactorDefinition]

    # Data accessors (injected from Infrastructure layer)
    get_factor_value: Callable[[str, str, date], Optional[float]]  # (stock_code, factor_code, date) -> value
    get_stock_info: Callable[[str], Optional[Dict]]  # (stock_code) -> {name, sector, market_cap, ...}


class FactorEngine:
    """
    Pure Python factor calculation engine.

    Domain layer service - NO external dependencies.
    Uses only Python standard library for calculations.
    """

    def __init__(self, context: FactorCalculationContext):
        self.context = context
        self._factor_def_map = {f.code: f for f in context.factor_definitions}
        self._common_factor_map = {f.code: f for f in get_common_factors()}
        self._factor_value_cache: Dict[Tuple[str, str], Optional[float]] = {}
        self._factor_distribution_cache: Dict[str, List[float]] = {}
        self._factor_stats_cache: Dict[str, Tuple[float, float]] = {}
        self._factor_exposure_cache: Dict[Tuple[str, str], Optional[FactorExposure]] = {}
        self._stock_info_cache: Dict[str, Optional[Dict]] = {}

    def calculate_factor_exposure(
        self,
        stock_code: str,
        factor_code: str
    ) -> Optional[FactorExposure]:
        """
        Calculate factor exposure for a single stock-factor pair.

        Returns:
            FactorExposure with percentile rank and z-score
        """
        if factor_code not in self._factor_def_map:
            return None

        cache_key = (stock_code, factor_code)
        if cache_key in self._factor_exposure_cache:
            return self._factor_exposure_cache[cache_key]

        factor_def = self._factor_def_map[factor_code]
        raw_value = self._get_factor_value(stock_code, factor_code)

        if raw_value is None:
            if factor_def.allow_missing:
                self._factor_exposure_cache[cache_key] = None
                return None
            raise ValueError(f"Missing factor value for {stock_code} {factor_code}")

        # Calculate cross-sectional statistics
        all_values = self._get_all_factor_values(factor_code)
        if not all_values:
            self._factor_exposure_cache[cache_key] = None
            return None

        # Calculate percentile rank
        percentile_rank = self._calculate_percentile(raw_value, all_values)

        # Calculate z-score
        mean, std = self._get_factor_stats(factor_code)
        z_score = (raw_value - mean) / std if std > 0 else 0.0

        # Normalize to 0-100 scale
        normalized_score = self._z_score_to_percentile(z_score)

        # Adjust direction for negative factors
        if factor_def.direction == FactorDirection.NEGATIVE:
            percentile_rank = 1.0 - percentile_rank
            z_score = -z_score
            normalized_score = 100.0 - normalized_score

        exposure = FactorExposure(
            stock_code=stock_code,
            trade_date=self.context.trade_date,
            factor_code=factor_code,
            factor_value=raw_value,
            percentile_rank=percentile_rank,
            z_score=z_score,
            normalized_score=normalized_score,
        )
        self._factor_exposure_cache[cache_key] = exposure
        return exposure

    def calculate_factor_scores(
        self,
        factor_weights: Dict[str, float]
    ) -> List[FactorScore]:
        """
        Calculate composite factor scores for all stocks in universe.

        Args:
            factor_weights: Dictionary of {factor_code: weight}

        Returns:
            List of FactorScore sorted by composite_score descending
        """
        # Validate weights
        total_weight = sum(factor_weights.values())
        if abs(total_weight - 1.0) > 0.01:
            raise ValueError(f"Factor weights must sum to 1.0, got {total_weight}")

        # Calculate scores for each stock
        scores = []
        for stock_code in self.context.universe:
            score = self._calculate_stock_score(stock_code, factor_weights)
            if score:
                scores.append(score)

        # Calculate percentile ranks
        scores = self._assign_percentile_ranks(scores)

        # Sort by composite score
        scores.sort(key=lambda s: s.composite_score, reverse=True)

        return scores

    def select_portfolio(
        self,
        config: FactorPortfolioConfig
    ) -> List[FactorPortfolioHolding]:
        """
        Select portfolio based on factor configuration.

        Args:
            config: Factor portfolio configuration

        Returns:
            List of portfolio holdings
        """
        # Calculate scores
        scores = self.calculate_factor_scores(config.factor_weights)

        # Apply filters
        filtered_scores = self._apply_filters(scores, config)

        # Select top N
        selected = filtered_scores[:config.top_n]

        # Calculate weights
        holdings = self._calculate_weights(selected, config)

        return holdings

    def _get_all_factor_values(self, factor_code: str) -> List[float]:
        """Get all factor values for the universe"""
        if factor_code in self._factor_distribution_cache:
            return self._factor_distribution_cache[factor_code]

        values = []
        for stock_code in self.context.universe:
            value = self._get_factor_value(stock_code, factor_code)
            if value is not None:
                values.append(value)
        values.sort()
        self._factor_distribution_cache[factor_code] = values
        return values

    def _calculate_percentile(self, value: float, all_values: List[float]) -> float:
        """Calculate percentile rank (0-1)"""
        if not all_values:
            return 0.5

        n = len(all_values)
        count_le = bisect_right(all_values, value)
        return count_le / n

    def _get_factor_value(self, stock_code: str, factor_code: str) -> Optional[float]:
        cache_key = (stock_code, factor_code)
        if cache_key not in self._factor_value_cache:
            self._factor_value_cache[cache_key] = self.context.get_factor_value(
                stock_code,
                factor_code,
                self.context.trade_date,
            )
        return self._factor_value_cache[cache_key]

    def _get_factor_stats(self, factor_code: str) -> Tuple[float, float]:
        if factor_code not in self._factor_stats_cache:
            self._factor_stats_cache[factor_code] = self._calculate_mean_std(
                self._get_all_factor_values(factor_code)
            )
        return self._factor_stats_cache[factor_code]

    def _calculate_mean_std(self, values: List[float]) -> Tuple[float, float]:
        """Calculate mean and standard deviation"""
        if not values:
            return 0.0, 1.0

        n = len(values)
        mean = sum(values) / n

        if n == 1:
            return mean, 1.0

        variance = sum((v - mean) ** 2 for v in values) / (n - 1)
        std = math.sqrt(variance)

        return mean, std

    def _z_score_to_percentile(self, z_score: float) -> float:
        """
        Convert z-score to percentile (0-100).

        Uses error function approximation.
        """
        # Approximation of the cumulative normal distribution
        # Based on Abramowitz and Stegun formula 7.1.26
        sign = 1 if z_score >= 0 else -1
        z = abs(z_score) / math.sqrt(2)

        # Constants for the approximation
        a1 = 0.254829592
        a2 = -0.284496736
        a3 = 1.421413741
        a4 = -1.453152027
        a5 = 1.061405429
        p = 0.3275911

        # Horner's method
        t = 1.0 / (1.0 + p * z)
        y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-z * z)

        percentile = 0.5 * (1.0 + sign * y)
        return percentile * 100

    def _calculate_stock_score(
        self,
        stock_code: str,
        factor_weights: Dict[str, float]
    ) -> Optional[FactorScore]:
        """Calculate composite score for a single stock"""
        factor_scores = {}
        stock_info = self._get_stock_info(stock_code)

        if not stock_info:
            return None

        # Calculate individual factor scores
        for factor_code in factor_weights:
            exposure = self.calculate_factor_exposure(stock_code, factor_code)
            if exposure:
                factor_scores[factor_code] = exposure.normalized_score

        # Calculate composite score
        composite_score = sum(
            factor_scores.get(fc, 50.0) * fw
            for fc, fw in factor_weights.items()
        )

        # Calculate category scores
        category_scores = self._calculate_category_scores(factor_scores)

        return FactorScore(
            stock_code=stock_code,
            stock_name=stock_info.get("name", ""),
            trade_date=self.context.trade_date,
            factor_scores=factor_scores,
            factor_weights=factor_weights,
            composite_score=composite_score,
            percentile_rank=0.0,  # Will be assigned later
            sector=stock_info.get("sector", ""),
            market_cap=stock_info.get("market_cap"),
            **category_scores,
        )

    def _calculate_category_scores(self, factor_scores: Dict[str, float]) -> Dict[str, float]:
        """Calculate scores by factor category"""
        # Map factors to categories
        category_scores = {
            "value_score": 0.0,
            "quality_score": 0.0,
            "growth_score": 0.0,
            "momentum_score": 0.0,
            "volatility_score": 0.0,
            "liquidity_score": 0.0,
        }

        category_counts = {k: 0 for k in category_scores.keys()}

        for factor_code, score in factor_scores.items():
            if factor_code in self._common_factor_map:
                factor_def = self._common_factor_map[factor_code]
                category_key = f"{factor_def.category.value}_score"
                if category_key in category_scores:
                    category_scores[category_key] += score
                    category_counts[category_key] += 1

        # Average scores within categories
        for key in category_scores:
            if category_counts[key] > 0:
                category_scores[key] /= category_counts[key]

        return category_scores

    def _get_stock_info(self, stock_code: str) -> Optional[Dict]:
        if stock_code not in self._stock_info_cache:
            self._stock_info_cache[stock_code] = self.context.get_stock_info(stock_code)
        return self._stock_info_cache[stock_code]

    def _assign_percentile_ranks(self, scores: List[FactorScore]) -> List[FactorScore]:
        """Assign percentile ranks based on composite scores"""
        if not scores:
            return scores

        n = len(scores)
        sorted_scores = sorted(scores, key=lambda s: s.composite_score)

        result = []
        for i, score in enumerate(sorted_scores):
            # Create new immutable score with percentile rank
            percentile_rank = (i + 1) / n
            result.append(score)

        return result

    def _apply_filters(
        self,
        scores: List[FactorScore],
        config: FactorPortfolioConfig
    ) -> List[FactorScore]:
        """Apply filtering conditions"""
        filtered = scores

        # Market cap filter
        if config.min_market_cap is not None or config.max_market_cap is not None:
            filtered = [
                s for s in filtered
                if self._check_market_cap_filter(s, config)
            ]

        # PE filter
        if config.min_pe is not None or config.max_pe is not None:
            filtered = [
                s for s in filtered
                if self._check_pe_filter(s, config)
            ]

        # PB filter
        if config.max_pb is not None:
            filtered = [
                s for s in filtered
                if self._check_pb_filter(s, config)
            ]

        # Debt ratio filter
        if config.max_debt_ratio is not None:
            filtered = [
                s for s in filtered
                if self._check_debt_ratio_filter(s, config)
            ]

        return filtered

    def _check_market_cap_filter(self, score: FactorScore, config: FactorPortfolioConfig) -> bool:
        """Check market cap filter"""
        if score.market_cap is None:
            return True

        cap_in_billion = float(score.market_cap) / 1_000_000_000

        if config.min_market_cap is not None and cap_in_billion < config.min_market_cap:
            return False
        if config.max_market_cap is not None and cap_in_billion > config.max_market_cap:
            return False

        return True

    def _check_pe_filter(self, score: FactorScore, config: FactorPortfolioConfig) -> bool:
        """Check PE filter (need to fetch from data)"""
        # This would require accessing PE data
        # For now, pass through
        return True

    def _check_pb_filter(self, score: FactorScore, config: FactorPortfolioConfig) -> bool:
        """Check PB filter"""
        # This would require accessing PB data
        return True

    def _check_debt_ratio_filter(self, score: FactorScore, config: FactorPortfolioConfig) -> bool:
        """Check debt ratio filter"""
        # This would require accessing debt ratio data
        return True

    def _calculate_weights(
        self,
        scores: List[FactorScore],
        config: FactorPortfolioConfig
    ) -> List[FactorPortfolioHolding]:
        """Calculate portfolio weights"""
        if not scores:
            return []

        n = len(scores)

        if config.weight_method == "equal_weight":
            weight = 1.0 / n
            return [
                FactorPortfolioHolding(
                    config_name=config.name,
                    trade_date=self.context.trade_date,
                    stock_code=score.stock_code,
                    stock_name=score.stock_name,
                    weight=weight,
                    factor_score=score.composite_score,
                    rank=i + 1,
                    sector=score.sector,
                    factor_scores=score.factor_scores,
                )
                for i, score in enumerate(scores)
            ]

        elif config.weight_method == "factor_weighted":
            # Weight by factor score
            total_score = sum(s.composite_score for s in scores)
            return [
                FactorPortfolioHolding(
                    config_name=config.name,
                    trade_date=self.context.trade_date,
                    stock_code=score.stock_code,
                    stock_name=score.stock_name,
                    weight=score.composite_score / total_score if total_score > 0 else 1.0 / n,
                    factor_score=score.composite_score,
                    rank=i + 1,
                    sector=score.sector,
                    factor_scores=score.factor_scores,
                )
                for i, score in enumerate(scores)
            ]

        else:  # market_cap_weighted or default
            # Use equal weight for now (market cap would require additional data)
            weight = 1.0 / n
            return [
                FactorPortfolioHolding(
                    config_name=config.name,
                    trade_date=self.context.trade_date,
                    stock_code=score.stock_code,
                    stock_name=score.stock_name,
                    weight=weight,
                    factor_score=score.composite_score,
                    rank=i + 1,
                    sector=score.sector,
                    factor_scores=score.factor_scores,
                )
                for i, score in enumerate(scores)
            ]


class ScoringService:
    """
    Service for scoring stocks based on multiple factors.

    Domain layer - pure Python business logic.
    """

    def __init__(self, context: FactorCalculationContext):
        self.context = context
        self.engine = FactorEngine(context)

    def get_top_stocks(
        self,
        factor_weights: Dict[str, float],
        top_n: int = 30
    ) -> List[FactorScore]:
        """
        Get top N stocks by composite factor score.

        Args:
            factor_weights: Dictionary of {factor_code: weight}
            top_n: Number of top stocks to return

        Returns:
            List of top N FactorScore objects
        """
        scores = self.engine.calculate_factor_scores(factor_weights)
        return scores[:top_n]

    def explain_stock_score(
        self,
        stock_code: str,
        factor_weights: Dict[str, float]
    ) -> Optional[Dict]:
        """
        Explain a stock's factor score breakdown.

        Returns:
            Dictionary with score breakdown and explanation
        """
        score = self.engine._calculate_stock_score(stock_code, factor_weights)

        if not score:
            return None

        # Build explanation
        explanation = {
            "stock_code": score.stock_code,
            "stock_name": score.stock_name,
            "composite_score": round(score.composite_score, 2),
            "percentile_rank": round(score.percentile_rank * 100, 1),
            "factor_breakdown": {},
            "category_breakdown": {
                "value": round(score.value_score, 2),
                "quality": round(score.quality_score, 2),
                "growth": round(score.growth_score, 2),
                "momentum": round(score.momentum_score, 2),
                "volatility": round(score.volatility_score, 2),
                "liquidity": round(score.liquidity_score, 2),
            },
        }

        for factor_code, score_value in score.factor_scores.items():
            weight = factor_weights.get(factor_code, 0.0)
            contribution = score_value * weight
            explanation["factor_breakdown"][factor_code] = {
                "score": round(score_value, 2),
                "weight": round(weight, 3),
                "contribution": round(contribution, 2),
            }

        return explanation
