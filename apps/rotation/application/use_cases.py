"""
Rotation Module Application Layer - Use Cases

Application use cases for the rotation module.
Orchestrates domain services and infrastructure adapters.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from apps.rotation.application.dtos import (
    AssetComparisonRequest,
    AssetComparisonResponse,
    AssetMomentumScore,
    AssetsViewRequest,
    AssetsViewResponse,
    ConfigLatestSignal,
    RotationConfigsViewRequest,
    RotationConfigsViewResponse,
    RotationSignalRequest,
    RotationSignalResponse,
    RotationSignalsViewRequest,
    RotationSignalsViewResponse,
)
from apps.rotation.application.repository_provider import (
    get_rotation_interface_repository,
)
from apps.rotation.domain.entities import RotationConfig
from apps.rotation.domain.services import (
    RotationContext,
    RotationService,
)


@dataclass
class RotationUseCaseContext:
    """Context for rotation use case execution"""
    calc_date: date
    asset_universe: list[str]

    # Repository accessors (injected)
    get_asset_prices: Callable[[str, date, int], list[float] | None]
    get_current_regime: Callable[[], str | None]
    get_rotation_config: Callable[[str], RotationConfig | None]


class GenerateRotationSignalUseCase:
    """
    Use case: Generate rotation signal.

    Generates target allocation based on rotation strategy.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self, request: RotationSignalRequest) -> RotationSignalResponse:
        """Execute rotation signal generation"""
        # Get configuration
        config = self.context.get_rotation_config(request.config_name)
        if not config:
            raise ValueError(f"Configuration not found: {request.config_name}")

        # Use request date or current date
        signal_date = request.signal_date or self.context.calc_date

        # Create domain context
        domain_context = RotationContext(
            calc_date=signal_date,
            asset_universe=config.asset_universe,
            get_asset_prices=self.context.get_asset_prices,
            get_current_regime=self.context.get_current_regime,
        )

        # Create service and generate signal
        service = RotationService(domain_context)
        signal = service.generate_signal(config)

        # Convert momentum ranking
        momentum_ranking = [
            {"asset": asset, "score": score}
            for asset, score in signal.momentum_ranking
        ]

        return RotationSignalResponse(
            config_name=signal.config_name,
            signal_date=signal.signal_date,
            target_allocation=signal.target_allocation,
            current_regime=signal.current_regime,
            action_required=signal.action_required,
            reason=signal.reason,
            momentum_ranking=momentum_ranking,
        )


class CompareAssetsUseCase:
    """
    Use case: Compare multiple assets.

    Returns comparison metrics for specified assets.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self, request: AssetComparisonRequest) -> AssetComparisonResponse:
        """Execute asset comparison"""
        # Create domain context
        domain_context = RotationContext(
            calc_date=self.context.calc_date,
            asset_universe=request.asset_codes,
            get_asset_prices=self.context.get_asset_prices,
            get_current_regime=self.context.get_current_regime,
        )

        # Create service and compare
        service = RotationService(domain_context)
        comparison = service.compare_assets(request.asset_codes)

        return AssetComparisonResponse(
            assets=comparison,
            comparison_date=self.context.calc_date,
        )


class GetCurrentRegimeUseCase:
    """
    Use case: Get current macro regime.

    Returns the current macro regime for rotation.
    """

    def __init__(self, context: RotationUseCaseContext):
        self.context = context

    def execute(self) -> str | None:
        """Execute get current regime"""
        return self.context.get_current_regime()


# ============================================================================
# View UseCases - For page views (template rendering)
# ============================================================================

class GetAssetsForViewUseCase:
    """
    Use case: Get data for rotation assets page.

    Returns assets, categories, and momentum scores for template rendering.
    """

    def __init__(self, integration_service, view_repo=None):
        """
        Initialize with integration service.

        Args:
            integration_service: RotationIntegrationService instance
        """
        self.service = integration_service
        self.view_repo = view_repo or get_rotation_interface_repository()

    def execute(self, request: AssetsViewRequest) -> AssetsViewResponse:
        """
        Execute assets view data retrieval.

        Args:
            request: AssetsViewRequest (empty)

        Returns:
            AssetsViewResponse with assets, categories, and momentum scores
        """
        # Maintenance page should not block on historical-price fetches.
        assets = self.service.get_asset_master(include_inactive=True)

        # Get momentum scores for each asset
        momentum_scores = {}
        latest_calc_date = None

        if assets:
            for asset in assets:
                scores = self.service.momentum_repo.get_latest_scores(asset['code'], limit=1)
                if scores:
                    score = scores[0]
                    momentum_scores[asset['code']] = AssetMomentumScore(
                        composite_score=round(score.composite_score, 3),
                        rank=score.rank,
                        momentum_1m=round(score.momentum_1m, 3),
                        momentum_3m=round(score.momentum_3m, 3),
                        momentum_6m=round(score.momentum_6m, 3),
                        trend_strength=round(score.trend_strength, 3),
                        calc_date=score.calc_date,
                    )
                    if latest_calc_date is None or score.calc_date > latest_calc_date:
                        latest_calc_date = score.calc_date

        # Group by category
        categories = {
            'equity': {'name': '股票', 'assets': []},
            'bond': {'name': '债券', 'assets': []},
            'commodity': {'name': '商品', 'assets': []},
            'currency': {'name': '货币', 'assets': []},
            'alternative': {'name': '另类', 'assets': []},
        }

        for asset in assets:
            category = asset['category']
            if category in categories:
                categories[category]['assets'].append(asset)

        return AssetsViewResponse(
            assets=assets,
            categories=categories,
            momentum_scores=momentum_scores,
            latest_calc_date=latest_calc_date,
            maintenance_notice=(
                "资产维护页默认展示资产主数据与最近一次已落库的动量结果，"
                "不会同步拉取实时/历史行情；若外部行情链路异常，页面仍可维护，"
                "但价格与动量可能存在延迟。"
            ),
        )


class GetRotationConfigsForViewUseCase:
    """
    Use case: Get data for rotation configs page.

    Returns configs and their latest signals for template rendering.
    """

    def __init__(self, integration_service, view_repo=None):
        """
        Initialize with integration service.

        Args:
            integration_service: RotationIntegrationService instance
        """
        self.service = integration_service
        self.view_repo = view_repo or get_rotation_interface_repository()

    def execute(self, request: RotationConfigsViewRequest) -> RotationConfigsViewResponse:
        """
        Execute configs view data retrieval.

        Args:
            request: RotationConfigsViewRequest (empty)

        Returns:
            RotationConfigsViewResponse with configs and latest signals
        """
        configs = self.view_repo.list_config_rows()

        # Get latest signal for each config
        latest_signals = {}
        for config in configs:
            latest_signal = self.service.signal_repo.get_latest_signal(config['id'])
            if latest_signal:
                latest_signals[config['id']] = ConfigLatestSignal(
                    signal_date=latest_signal.signal_date,
                    current_regime=latest_signal.current_regime,
                    action_required=latest_signal.action_required,
                    target_allocation=latest_signal.target_allocation,
                )

        return RotationConfigsViewResponse(
            configs=configs,
            latest_signals=latest_signals,
            strategy_types=[
                ('regime_based', '基于象限'),
                ('momentum', '动量轮动'),
                ('risk_parity', '风险平价'),
                ('mean_reversion', '均值回归'),
                ('custom', '自定义'),
            ],
            frequencies=['daily', 'weekly', 'monthly', 'quarterly'],
        )


class GetRotationSignalsForViewUseCase:
    """
    Use case: Get data for rotation signals page.

    Returns signals with filters for template rendering.
    """

    def __init__(self, integration_service, view_repo=None):
        """
        Initialize with integration service.

        Args:
            integration_service: RotationIntegrationService instance
        """
        self.service = integration_service
        self.view_repo = view_repo or get_rotation_interface_repository()

    def execute(self, request: RotationSignalsViewRequest) -> RotationSignalsViewResponse:
        """
        Execute signals view data retrieval.

        Args:
            request: RotationSignalsViewRequest with filter parameters

        Returns:
            RotationSignalsViewResponse with filtered signals and metadata
        """
        cutoff_date = date.today() - timedelta(days=60)
        signals = self.view_repo.list_recent_signal_rows(
            config_filter=request.config_filter,
            regime_filter=request.regime_filter,
            action_filter=request.action_filter,
            cutoff_date=cutoff_date,
        )

        configs = self.view_repo.list_active_config_rows()

        # Get latest signal for each config
        latest_by_config = {}
        for config in configs:
            latest = self.service.signal_repo.get_latest_signal(config['id'])
            if latest:
                latest_by_config[config['id']] = {
                    'id': latest.id,
                    'signal_date': latest.signal_date,
                    'current_regime': latest.current_regime,
                    'action_required': latest.action_required,
                    'target_allocation': latest.target_allocation,
                }

        # Get current regime
        current_regime = None
        try:
            current_regime = self.service._get_current_regime()
        except Exception:
            pass

        return RotationSignalsViewResponse(
            signals=signals,
            configs=configs,
            latest_by_config=latest_by_config,
            current_regime=current_regime,
            regime_choices=['Recovery', 'Overheat', 'Stagflation', 'Deflation'],
            action_choices=['rebalance', 'hold', 'reduce', 'increase'],
            filter_config=request.config_filter,
            filter_regime=request.regime_filter,
            filter_action=request.action_filter,
        )
