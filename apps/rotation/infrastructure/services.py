"""
Rotation Module Infrastructure Layer - Integration Services

Integration services that connect domain logic with data adapters.
This layer is NOT part of the four-layer architecture but provides
integration between Application layer and Infrastructure.
"""

import logging
from datetime import date
from typing import Any

from apps.rotation.domain.entities import (
    RotationStrategyType,
)
from apps.rotation.domain.services import (
    RotationContext,
    RotationService,
    is_rotation_signal_stale,
)
from apps.rotation.infrastructure.adapters.price_adapter import (
    RotationPriceDataService,
)
from apps.rotation.infrastructure.repositories import (
    AssetClassRepository,
    MomentumScoreRepository,
    RotationConfigRepository,
    RotationSignalRepository,
)

logger = logging.getLogger(__name__)


class RotationIntegrationService:
    """
    High-level service for rotation operations.

    Integrates domain services with repositories and data adapters.
    """

    def __init__(
        self,
        price_service: RotationPriceDataService | None = None,
    ):
        self.price_service = price_service or RotationPriceDataService()
        self.asset_repo = AssetClassRepository()
        self.config_repo = RotationConfigRepository()
        self.signal_repo = RotationSignalRepository()
        self.momentum_repo = MomentumScoreRepository()

    def generate_rotation_signal(
        self, config_name: str, signal_date: date | None = None
    ) -> dict | None:
        """
        Generate rotation signal for a configuration.

        Args:
            config_name: Name of the rotation configuration
            signal_date: Date for signal (default: today)

        Returns:
            Dictionary with signal details
        """
        signal_date = signal_date or date.today()

        # Get configuration
        config = self.config_repo.get_by_name(config_name)
        if not config:
            logger.error(f"Configuration not found: {config_name}")
            return None

        # Get current regime from regime module
        current_regime = self._get_current_regime()

        # Create domain context
        def get_prices(asset_code: str, end_date: date, days: int) -> list[float] | None:
            return self.price_service.get_prices(asset_code, end_date, days)

        def get_regime() -> str | None:
            return current_regime

        context = RotationContext(
            calc_date=signal_date,
            asset_universe=config.asset_universe,
            get_asset_prices=get_prices,
            get_current_regime=get_regime,
        )

        # Generate signal using domain service
        try:
            domain_service = RotationService(context)
            signal = domain_service.generate_signal(config)

            # Save to database
            config_model = self.config_repo.get_model_by_name(config_name)
            if config_model:
                self.signal_repo.save(signal, config_model.id)

                return {
                    "config_name": signal.config_name,
                    "signal_date": signal.signal_date.isoformat(),
                    "target_allocation": signal.target_allocation,
                    "current_regime": signal.current_regime,
                    "expected_volatility": signal.expected_volatility,
                    "expected_return": signal.expected_return,
                    "action_required": signal.action_required,
                    "reason": signal.reason,
                    "momentum_ranking": signal.momentum_ranking,
                    "data_quality": self._build_signal_data_quality(signal, config),
                }

        except ValueError as e:
            if self._is_expected_signal_generation_gap(e):
                logger.info(
                    "Skip fresh rotation signal for %s because no valid allocation can be derived yet: %s",
                    config_name,
                    e,
                )
                return {
                    "config_name": config_name,
                    "signal_date": signal_date.isoformat(),
                    "status": "skipped",
                    "error": "no_valid_allocation",
                    "reason": str(e),
                    "target_allocation": {},
                    "momentum_ranking": [],
                }
            else:
                logger.error(f"Failed to generate signal for {config_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to generate signal for {config_name}: {e}")
            return None

    def compare_assets(self, asset_codes: list[str], lookback_days: int = 60) -> dict:
        """
        Compare multiple assets across multiple dimensions.

        Args:
            asset_codes: List of asset codes to compare
            lookback_days: Number of days to look back for calculations

        Returns:
            Dictionary with comparison results
        """

        # Create domain context
        def get_prices(asset_code: str, end_date: date, days: int) -> list[float] | None:
            return self.price_service.get_prices(
                asset_code,
                end_date,
                days,
                cache_result=False,
            )

        def get_regime() -> str | None:
            return None

        context = RotationContext(
            calc_date=date.today(),
            asset_universe=asset_codes,
            get_asset_prices=get_prices,
            get_current_regime=get_regime,
        )

        # Get comparison using domain service
        domain_service = RotationService(context)
        comparison = domain_service.compare_assets(asset_codes)

        return {
            "calc_date": date.today().isoformat(),
            "lookback_days": lookback_days,
            "assets": comparison,
        }

    def get_correlation_matrix(self, asset_codes: list[str], window_days: int = 60) -> dict:
        """
        Get correlation matrix for specified assets.

        Args:
            asset_codes: List of asset codes
            window_days: Window for correlation calculation

        Returns:
            Dictionary with correlation matrix
        """
        from shared.infrastructure.correlation import NumPyCorrelationCalculator

        # Fetch price data for all assets
        price_dict = {}
        for asset_code in asset_codes:
            prices = self.price_service.get_prices(
                asset_code,
                date.today(),
                window_days + 30,
                cache_result=False,
            )
            if prices:
                price_dict[asset_code] = prices[-window_days:]

        if not price_dict:
            return {
                "error": "No price data available",
                "calc_date": date.today().isoformat(),
            }

        # Calculate correlation matrix
        calculator = NumPyCorrelationCalculator()
        correlation_matrix = calculator.calculate_correlation_matrix(price_dict, window_days)

        # Convert to dict format
        matrix_dict = {
            asset1: {
                asset2: correlation_matrix.get_correlation(asset1, asset2) for asset2 in asset_codes
            }
            for asset1 in asset_codes
        }

        return {
            "calc_date": date.today().isoformat(),
            "window_days": window_days,
            "assets": asset_codes,
            "correlation_matrix": matrix_dict,
        }

    def get_rotation_recommendation(
        self,
        strategy_type: str = "momentum",
        *,
        prefer_persisted: bool = False,
    ) -> dict:
        """
        Get rotation recommendation based on strategy type.

        Args:
            strategy_type: 'momentum', 'regime_based', or 'risk_parity'

        Returns:
            Dictionary with recommendation
        """
        # Get active configuration for strategy type
        configs = self.config_repo.get_active()

        strategy_map = {
            "momentum": RotationStrategyType.MOMENTUM,
            "regime_based": RotationStrategyType.REGIME_BASED,
            "risk_parity": RotationStrategyType.RISK_PARITY,
        }

        target_strategy = strategy_map.get(strategy_type, RotationStrategyType.MOMENTUM)

        # Find matching configuration
        config = None
        for c in configs:
            if c.strategy_type == target_strategy:
                config = c
                break

        if not config:
            # Use first active config as fallback
            config = configs[0] if configs else None

        if not config:
            return {
                "error": "No active rotation configuration found",
                "calc_date": date.today().isoformat(),
            }

        config_model = self.config_repo.get_model_by_name(config.name)
        latest_signal = (
            self.signal_repo.get_latest_signal(config_model.id)
            if config_model is not None
            else None
        )

        if prefer_persisted and latest_signal is not None:
            result = self._build_recommendation_from_signal_model(latest_signal)
            is_stale = is_rotation_signal_stale(
                latest_signal.signal_date,
                config.rebalance_frequency,
                date.today(),
            )
            self._apply_recommendation_metadata(
                result=result,
                data_source="stored_signal_fallback" if is_stale else "stored_signal",
                is_stale=is_stale,
                strategy_type=strategy_type,
                config_description=config.description,
                warning_message=(
                    "工作台优先复用最近一次已落库轮动信号，避免页面刷新时重复触发外部行情请求。"
                    if is_stale
                    else None
                ),
            )
            return result

        # Decision workspace is read-heavy; when today's signal is already persisted,
        # reuse it instead of re-fetching market data on every page request.
        if latest_signal is not None and not is_rotation_signal_stale(
            latest_signal.signal_date,
            config.rebalance_frequency,
            date.today(),
        ):
            result = self._build_recommendation_from_signal_model(latest_signal)
            self._apply_recommendation_metadata(
                result=result,
                data_source="stored_signal",
                is_stale=False,
                strategy_type=strategy_type,
                config_description=config.description,
                warning_message=None,
            )
            return result

        # Generate signal
        signal = self.generate_rotation_signal(config.name)

        if signal:
            self._apply_recommendation_metadata(
                result=signal,
                data_source="fresh_generation",
                is_stale=False,
                strategy_type=strategy_type,
                config_description=config.description,
                warning_message=None,
            )
            return signal

        if latest_signal is not None:
            logger.info(
                "Rotation recommendation reuses stored signal for %s dated %s after fresh generation fallback",
                config.name,
                latest_signal.signal_date.isoformat(),
            )
            result = self._build_recommendation_from_signal_model(latest_signal)
            self._apply_recommendation_metadata(
                result=result,
                data_source="stored_signal_fallback",
                is_stale=True,
                strategy_type=strategy_type,
                config_description=config.description,
                warning_message=("实时轮动重算失败，当前展示最近一次已落库信号，" "结果可能滞后。"),
            )
            return result

        return {
            "error": "Failed to generate rotation signal",
            "calc_date": date.today().isoformat(),
        }

    @staticmethod
    def _is_expected_signal_generation_gap(exc: ValueError) -> bool:
        message = str(exc)
        return "Target allocation weights must sum to 1.0" in message and message.rstrip().endswith(
            "got 0"
        )

    @staticmethod
    def _build_recommendation_from_signal_model(signal_model) -> dict:
        """Convert persisted RotationSignalModel into API-ready recommendation."""
        return {
            "config_name": signal_model.config.name if signal_model.config else "",
            "signal_date": signal_model.signal_date.isoformat(),
            "target_allocation": signal_model.target_allocation,
            "current_regime": signal_model.current_regime,
            "expected_volatility": float(getattr(signal_model, "expected_volatility", 0.0) or 0.0),
            "expected_return": float(getattr(signal_model, "expected_return", 0.0) or 0.0),
            "action_required": signal_model.action_required,
            "reason": signal_model.reason,
            "momentum_ranking": signal_model.momentum_ranking,
            "data_quality": RotationIntegrationService._build_model_signal_data_quality(
                signal_model
            ),
        }

    @staticmethod
    def _build_signal_data_quality(signal, config) -> dict[str, Any]:
        """Summarize whether the generated signal is data-driven enough to trust."""
        universe_size = len(config.asset_universe or [])
        ranked_count = len(signal.momentum_ranking or [])
        selected_count = len(signal.target_allocation or {})
        requires_ranking = getattr(getattr(config, "strategy_type", None), "value", None) in {
            "momentum",
            "regime_based",
            "custom",
            "mean_reversion",
        }
        coverage_count = ranked_count if requires_ranking else selected_count
        coverage_ratio = coverage_count / universe_size if universe_size else 0.0
        metrics_available = signal.expected_return != 0.0 or signal.expected_volatility != 0.0
        status = "ok"
        warnings = []
        if universe_size and coverage_count < universe_size:
            status = "degraded"
            warnings.append("partial_price_coverage")
        if not metrics_available:
            status = "degraded"
            warnings.append("risk_return_metrics_unavailable")
        if selected_count == 0:
            status = "invalid"
            warnings.append("empty_target_allocation")

        return {
            "status": status,
            "universe_size": universe_size,
            "ranked_asset_count": ranked_count,
            "selected_asset_count": selected_count,
            "coverage_ratio": round(coverage_ratio, 4),
            "metrics_available": metrics_available,
            "warnings": warnings,
        }

    @staticmethod
    def _build_model_signal_data_quality(signal_model) -> dict[str, Any]:
        """Build quality metadata for a persisted signal model."""
        config = getattr(signal_model, "config", None)
        universe = getattr(config, "asset_universe", []) or []
        ranked = getattr(signal_model, "momentum_ranking", []) or []
        allocation = getattr(signal_model, "target_allocation", {}) or {}
        strategy_type = str(getattr(config, "strategy_type", "") or "")
        requires_ranking = strategy_type in {
            "momentum",
            "regime_based",
            "custom",
            "mean_reversion",
        }
        coverage_count = len(ranked) if requires_ranking else len(allocation)
        coverage_ratio = coverage_count / len(universe) if universe else 0.0
        metrics_available = (
            float(getattr(signal_model, "expected_return", 0.0) or 0.0) != 0.0
            or float(getattr(signal_model, "expected_volatility", 0.0) or 0.0) != 0.0
        )
        warnings = []
        status = "ok"
        if universe and coverage_count < len(universe):
            status = "degraded"
            warnings.append("partial_price_coverage")
        if not metrics_available:
            status = "degraded"
            warnings.append("risk_return_metrics_unavailable")
        if not allocation:
            status = "invalid"
            warnings.append("empty_target_allocation")
        return {
            "status": status,
            "universe_size": len(universe),
            "ranked_asset_count": len(ranked),
            "selected_asset_count": len(allocation),
            "coverage_ratio": round(coverage_ratio, 4),
            "metrics_available": metrics_available,
            "warnings": warnings,
        }

    @staticmethod
    def _apply_recommendation_metadata(
        result: dict,
        data_source: str,
        is_stale: bool,
        strategy_type: str,
        config_description: str,
        warning_message: str | None,
    ) -> None:
        """Attach source/freshness metadata for downstream UI rendering."""
        result["data_source"] = data_source
        result["is_stale"] = is_stale
        result["strategy_type"] = strategy_type
        result["config_description"] = config_description
        result["warning_message"] = warning_message
        quality_status = (result.get("data_quality") or {}).get("status")
        result["actionable"] = (
            data_source in {"fresh_generation", "stored_signal"}
            and (not is_stale)
            and quality_status == "ok"
        )
        if result["actionable"]:
            result["execution_block_reason"] = None
        elif is_stale:
            result["execution_block_reason"] = "stale_rotation_signal"
        elif data_source.endswith("_fallback"):
            result["execution_block_reason"] = "fallback_rotation_signal"
        elif quality_status and quality_status != "ok":
            result["execution_block_reason"] = f"rotation_data_quality_{quality_status}"
        else:
            result["execution_block_reason"] = "rotation_signal_not_actionable"

    def get_asset_info(self, asset_code: str) -> dict | None:
        """
        Get information about a specific asset.

        Args:
            asset_code: Asset code

        Returns:
            Dictionary with asset information
        """
        asset = self.asset_repo.get_by_code(asset_code)

        if not asset:
            return None

        # Get recent prices
        prices = self.price_service.get_prices(asset_code, date.today(), 60)

        price_info = {}
        if prices and len(prices) > 1:
            current_price = prices[-1]
            prev_price = prices[-20] if len(prices) > 20 else prices[0]

            price_info = {
                "current_price": round(current_price, 3),
                "change_20d": (
                    round((current_price - prev_price) / prev_price * 100, 2)
                    if prev_price > 0
                    else 0
                ),
                "has_price_data": True,
            }
        else:
            price_info = {
                "current_price": None,
                "change_20d": None,
                "has_price_data": False,
            }

        return {
            "code": asset.code,
            "name": asset.name,
            "category": asset.category.value,
            "description": asset.description,
            "underlying_index": asset.underlying_index,
            "currency": asset.currency,
            "is_active": asset.is_active,
            **price_info,
        }

    def get_all_assets(self) -> list[dict]:
        """Get information about all active assets."""
        assets = self.asset_repo.get_all_active()

        result = []
        for asset in assets:
            info = self.get_asset_info(asset.code)
            if info:
                result.append(info)

        return result

    def get_asset_master(self, include_inactive: bool = True) -> list[dict]:
        """Get asset master data without blocking on market-data lookups."""
        assets = self.asset_repo.get_all() if include_inactive else self.asset_repo.get_all_active()

        return [
            {
                "code": asset.code,
                "name": asset.name,
                "category": asset.category.value,
                "description": asset.description,
                "underlying_index": asset.underlying_index,
                "currency": asset.currency,
                "is_active": asset.is_active,
                "current_price": None,
                "change_20d": None,
                "has_price_data": False,
            }
            for asset in assets
        ]

    def _get_current_regime(self) -> str | None:
        """
        Get current macro regime from regime module.

        Returns:
            Current regime name or None
        """
        try:
            from apps.regime.application.current_regime import resolve_current_regime

            current_state = resolve_current_regime(as_of_date=date.today())
            if current_state:
                return current_state.dominant_regime
        except Exception as e:
            logger.warning(f"Failed to get current regime: {e}")

        return None

    def clear_price_cache(self):
        """Clear the price data cache."""
        self.price_service.clear_cache()


class RotationSignalScheduler:
    """
    Scheduler for automatically generating rotation signals.

    Can be used with Celery beat for periodic signal generation.
    """

    def __init__(
        self,
        integration_service: RotationIntegrationService | None = None,
        config_repo: RotationConfigRepository | None = None,
    ):
        self.service = integration_service or RotationIntegrationService()
        self.config_repo = config_repo or RotationConfigRepository()

    def generate_all_signals(self, signal_date: date | None = None) -> dict[str, Any]:
        """
        Generate signals for all active configurations.

        Args:
            signal_date: Date for signal generation

        Returns:
            Summary of signal generation
        """
        signal_date = signal_date or date.today()

        configs = self.config_repo.get_active()

        results = {
            "signal_date": signal_date.isoformat(),
            "total_configs": len(configs),
            "successful": 0,
            "skipped": 0,
            "failed": 0,
            "signals": [],
        }

        for config in configs:
            try:
                signal = self.service.generate_rotation_signal(config.name, signal_date)
                if signal:
                    if signal.get("status") == "skipped":
                        results["skipped"] += 1
                    else:
                        results["successful"] += 1
                    results["signals"].append(
                        {
                            "config": config.name,
                            "strategy": config.strategy_type.value,
                            "signal": signal,
                        }
                    )
                else:
                    results["failed"] += 1
            except Exception as e:
                logger.error(f"Failed to generate signal for {config.name}: {e}")
                results["failed"] += 1

        return results
