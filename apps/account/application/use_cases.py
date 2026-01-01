"""
Account Application Use Cases

持仓管理的用例编排。
遵循四层架构：协调Domain层服务和Infrastructure层仓储。
"""

from decimal import Decimal
from typing import List, Optional, Dict
from datetime import datetime, date
from dataclasses import dataclass

from apps.account.domain.entities import (
    AccountProfile,
    Position,
    PortfolioSnapshot,
    PositionSource,
    RegimeMatchAnalysis,
    AssetAllocation,
    RiskTolerance,
    AssetClassType,
    Region,
    CrossBorderFlag,
)
from apps.account.domain.services import PositionService
from apps.account.infrastructure.repositories import (
    AccountRepository,
    PortfolioRepository,
    PositionRepository,
    TransactionRepository,
    AssetMetadataRepository,
)
from apps.regime.infrastructure.repositories import DjangoRegimeRepository


@dataclass
class CreatePositionInput:
    """创建持仓输入"""
    user_id: int
    asset_code: str
    shares: Optional[float] = None  # 不指定则自动计算
    price: Optional[Decimal] = None  # 不指定则获取行情


@dataclass
class CreatePositionOutput:
    """创建持仓输出"""
    position: Position
    shares: float
    notional: Decimal
    cash_required: Decimal


@dataclass
class RegimeAnalysisOutput:
    """Regime分析输出"""
    current_regime: str
    regime_date: date
    match_analysis: RegimeMatchAnalysis
    asset_allocation: List[AssetAllocation]
    risk_assessment: Dict[str, any]


class CreatePositionUseCase:
    """创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
        asset_meta_repo: AssetMetadataRepository,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo
        self.asset_meta_repo = asset_meta_repo

    def execute(self, input: CreatePositionInput) -> CreatePositionOutput:
        """
        创建持仓

        流程：
        1. 获取用户账户配置
        2. 如果未指定shares，根据风险偏好自动计算
        3. 获取或创建资产元数据
        4. 创建持仓记录
        5. 创建交易记录
        """
        # 1. 获取用户配置
        profile = self.account_repo.get_by_user_id(input.user_id)
        if not profile:
            raise ValueError(f"用户 {input.user_id} 账户配置不存在")

        # 2. 获取或创建投资组合
        portfolio_id = self.account_repo.get_or_create_default_portfolio(input.user_id)

        # 3. 获取资产元数据
        asset_meta = self.asset_meta_repo.get_or_create_asset(
            asset_code=input.asset_code,
            name=input.asset_code,  # 简化处理，实际应从接口获取名称
        )

        # 4. 确定价格
        price = input.price
        if price is None:
            price = Decimal("100.0")  # TODO: 从行情接口获取

        # 5. 计算仓位（如果未指定）
        if input.shares is None:
            calc = PositionService.calculate_position_size(
                account_capital=profile.initial_capital,
                risk_tolerance=profile.risk_tolerance,
                asset_class=AssetClassType(asset_meta["asset_class"]),
                region=Region(asset_meta["region"]),
                current_price=price,
            )
            shares = calc.shares
        else:
            shares = input.shares

        # 6. 创建持仓
        position = self.position_repo.create_position(
            portfolio_id=portfolio_id,
            asset_code=input.asset_code,
            shares=shares,
            price=price,
            source="manual",
        )

        return CreatePositionOutput(
            position=position,
            shares=shares,
            notional=Decimal(str(shares * float(price))),
            cash_required=Decimal(str(shares * float(price))),
        )


class CreatePositionFromSignalUseCase:
    """从投资信号创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo

    def execute(
        self,
        user_id: int,
        signal_id: int,
        price: Optional[Decimal] = None,
    ) -> CreatePositionOutput:
        """
        从投资信号创建持仓

        流程：
        1. 验证信号归属
        2. 计算建议仓位
        3. 创建持仓
        4. 记录信号关联
        """
        # 获取用户配置
        profile = self.account_repo.get_by_user_id(user_id)
        if not profile:
            raise ValueError(f"用户 {user_id} 账户配置不存在")

        # 确定价格
        if price is None:
            price = Decimal("100.0")  # TODO: 从行情接口获取

        # 创建持仓（会自动记录信号关联）
        position = self.position_repo.create_position_from_signal(
            user_id=user_id,
            signal_id=signal_id,
            price=price,
        )

        if not position:
            raise ValueError(f"信号 {signal_id} 不存在或无权限")

        return CreatePositionOutput(
            position=position,
            shares=position.shares,
            notional=position.market_value,
            cash_required=position.market_value,
        )


class ClosePositionUseCase:
    """平仓用例"""

    def __init__(self, position_repo: PositionRepository):
        self.position_repo = position_repo

    def execute(
        self,
        position_id: int,
        user_id: int,
        shares: Optional[float] = None,
    ) -> Optional[Position]:
        """
        平仓

        Args:
            position_id: 持仓ID
            user_id: 用户ID（验证权限）
            shares: 平仓数量，None表示全部平仓
        """
        # 验证权限
        position = self.position_repo.get_position_by_id(position_id)
        if not position:
            raise ValueError(f"持仓 {position_id} 不存在")

        if position.user_id != user_id:
            raise ValueError("无权限操作此持仓")

        # 执行平仓
        return self.position_repo.close_position(position_id, shares)


class AnalyzePortfolioUseCase:
    """组合分析用例"""

    def __init__(
        self,
        portfolio_repo: PortfolioRepository,
        regime_repo: DjangoRegimeRepository,
    ):
        self.portfolio_repo = portfolio_repo
        self.regime_repo = regime_repo

    def execute(
        self,
        portfolio_id: int,
        user_id: int,
    ) -> RegimeAnalysisOutput:
        """
        分析投资组合

        返回：
        1. 当前Regime状态
        2. 持仓与Regime的匹配度分析
        3. 资产配置分布
        4. 风险评估
        """
        # 1. 获取组合快照
        snapshot = self.portfolio_repo.get_portfolio_snapshot(portfolio_id)
        if not snapshot:
            raise ValueError(f"投资组合 {portfolio_id} 不存在")

        # 2. 获取当前Regime
        latest_regime = self.regime_repo.get_latest_snapshot()
        if latest_regime:
            current_regime = latest_regime.dominant_regime
            regime_date = latest_regime.observed_at
        else:
            current_regime = "Unknown"
            regime_date = date.today()

        # 3. 计算Regime匹配度
        match_analysis = PositionService.calculate_regime_match_score(
            positions=snapshot.positions,
            current_regime=current_regime,
        )

        # 4. 计算资产配置分布
        allocation_by_class = PositionService.calculate_asset_allocation(
            positions=snapshot.positions,
            dimension="asset_class",
        )
        allocation_by_region = PositionService.calculate_asset_allocation(
            positions=snapshot.positions,
            dimension="region",
        )

        # 5. 风险评估
        risk_assessment = PositionService.assess_portfolio_risk(
            positions=snapshot.positions,
            account_capital=snapshot.cash_balance + snapshot.invested_value,
        )

        return RegimeAnalysisOutput(
            current_regime=current_regime,
            regime_date=regime_date,
            match_analysis=match_analysis,
            asset_allocation=allocation_by_class + allocation_by_region,
            risk_assessment=risk_assessment,
        )


class UpdatePositionPricesUseCase:
    """更新持仓价格用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        asset_meta_repo: AssetMetadataRepository,
    ):
        self.position_repo = position_repo
        self.asset_meta_repo = asset_meta_repo

    def execute(self, user_id: int) -> Dict[str, any]:
        """
        批量更新用户持仓价格

        返回更新统计
        """
        # TODO: 集成行情数据源
        # 这里提供框架，实际实现需要调用外部API

        # 临时方案：批量更新（使用成本价）
        count = self.asset_meta_repo.update_position_prices(user_id)

        return {
            "updated_count": count,
            "user_id": user_id,
            "updated_at": datetime.now(),
        }


@dataclass
class CreatePositionFromBacktestInput:
    """从回测创建持仓输入"""
    user_id: int
    backtest_id: int
    scale_factor: float = 1.0  # 缩放因子，用于按比例调整仓位


@dataclass
class CreatePositionFromBacktestOutput:
    """从回测创建持仓输出"""
    positions_created: List[Position]
    total_positions: int
    total_value: float
    backtest_name: str


class CreatePositionFromBacktestUseCase:
    """从回测结果创建持仓用例"""

    def __init__(
        self,
        position_repo: PositionRepository,
        account_repo: AccountRepository,
        asset_meta_repo: AssetMetadataRepository,
    ):
        self.position_repo = position_repo
        self.account_repo = account_repo
        self.asset_meta_repo = asset_meta_repo

    def execute(self, input: CreatePositionFromBacktestInput) -> CreatePositionFromBacktestOutput:
        """
        从回测结果创建持仓

        流程：
        1. 验证回测归属
        2. 从回测的trades中提取最终持仓
        3. 为每个资产创建持仓记录
        4. 记录交易历史
        """
        from apps.backtest.infrastructure.models import BacktestResultModel
        from apps.backtest.infrastructure.repositories import DjangoBacktestRepository

        # 1. 获取回测结果
        try:
            backtest_model = BacktestResultModel.objects.get(id=input.backtest_id)
        except BacktestResultModel.DoesNotExist:
            raise ValueError(f"回测 {input.backtest_id} 不存在")

        # 验证归属
        if backtest_model.user_id != input.user_id:
            raise ValueError("无权限访问此回测结果")

        if backtest_model.status != 'completed':
            raise ValueError(f"回测状态为 {backtest_model.status}，无法应用")

        # 2. 从trades中提取最终持仓
        final_holdings = self._extract_final_holdings_from_trades(
            backtest_model.trades,
            input.scale_factor
        )

        if not final_holdings:
            raise ValueError("回测结果中无持仓数据")

        # 3. 获取或创建投资组合
        portfolio_id = self.account_repo.get_or_create_default_portfolio(input.user_id)

        # 4. 为每个资产创建持仓
        positions_created = []
        total_value = 0.0

        for holding in final_holdings:
            asset_class = holding['asset_class']

            # 映射 asset_class 到 asset_code（回测中使用的是大类名称）
            asset_code = self._map_asset_class_to_code(asset_class)

            # 获取或创建资产元数据
            asset_meta = self.asset_meta_repo.get_or_create_asset(
                asset_code=asset_code,
                name=asset_class,  # 使用大类名称作为显示名称
                asset_class=self._infer_asset_class_type(asset_class),
                region=self._infer_region(asset_class),
            )

            # 获取当前价格（使用回测结束时的价格或最新价格）
            from decimal import Decimal
            price = Decimal(str(holding.get('price', 100.0)))

            # 创建持仓
            position = self.position_repo.create_position(
                portfolio_id=portfolio_id,
                asset_code=asset_code,
                shares=holding['shares'],
                price=price,
                source='backtest',
                source_id=input.backtest_id,
            )

            positions_created.append(position)
            total_value += float(position.market_value)

        return CreatePositionFromBacktestOutput(
            positions_created=positions_created,
            total_positions=len(positions_created),
            total_value=total_value,
            backtest_name=backtest_model.name,
        )

    def _extract_final_holdings_from_trades(
        self,
        trades: List[Dict],
        scale_factor: float = 1.0
    ) -> List[Dict]:
        """
        从交易记录中提取最终持仓

        分析逻辑：
        1. 按时间排序所有交易
        2. 逐笔更新持仓状态
        3. 返回最终持仓（shares > 0）
        """
        holdings: Dict[str, Dict] = {}  # asset_class -> {shares, last_price}

        for trade in trades:
            asset_class = trade.get('asset_class')
            action = trade.get('action')
            shares = trade.get('shares', 0)
            price = trade.get('price', 100)

            if asset_class not in holdings:
                holdings[asset_class] = {'shares': 0.0, 'price': price}

            if action == 'buy':
                holdings[asset_class]['shares'] += shares
                # 更新加权平均价格
                old_shares = holdings[asset_class]['shares'] - shares
                old_price = holdings[asset_class]['price']
                if old_shares > 0:
                    holdings[asset_class]['price'] = (
                        (old_shares * old_price + shares * price) /
                        holdings[asset_class]['shares']
                    )
                else:
                    holdings[asset_class]['price'] = price
            elif action == 'sell':
                holdings[asset_class]['shares'] -= shares
                # 清零持仓时重置价格
                if holdings[asset_class]['shares'] <= 0:
                    holdings[asset_class]['shares'] = 0
                    holdings[asset_class]['price'] = price

        # 过滤掉零持仓，应用缩放因子
        final_holdings = []
        for asset_class, data in holdings.items():
            if data['shares'] > 0:
                final_holdings.append({
                    'asset_class': asset_class,
                    'shares': data['shares'] * scale_factor,
                    'price': data['price'],
                })

        return final_holdings

    def _map_asset_class_to_code(self, asset_class: str) -> str:
        """
        将回测中的资产大类映射为具体资产代码

        这是一个简化实现，实际应用中需要：
        1. 用户选择具体ETF或基金
        2. 或者使用系统默认的标的映射表
        """
        # 默认映射表（可扩展）
        mapping = {
            'A_SHARE_GROWTH': '000001.SH',   # 沪深300成长
            'A_SHARE_VALUE': '000905.SH',   # 中证500价值
            'CHINA_BOND': '000012.SH',      # 国债指数
            'GOLD': 'AU9999.SGE',           # 黄金现货
            'COMMODITY': '002040.SH',       # 商品ETF
            'CASH': 'CNY',
            'a_share_growth': '000001.SH',
            'a_share_value': '000905.SH',
            'china_bond': '000012.SH',
            'gold': 'AU9999.SGE',
            'commodity': '002040.SH',
            'cash': 'CNY',
        }
        return mapping.get(asset_class, asset_class)

    def _infer_asset_class_type(self, asset_class: str) -> AssetClassType:
        """从资产大类推断资产类型"""
        asset_class_lower = asset_class.lower()

        if 'growth' in asset_class_lower or 'share' in asset_class_lower or 'equity' in asset_class_lower:
            return AssetClassType.EQUITY
        elif 'bond' in asset_class_lower or 'fixed' in asset_class_lower:
            return AssetClassType.FIXED_INCOME
        elif 'gold' in asset_class_lower or 'commodity' in asset_class_lower:
            return AssetClassType.COMMODITY
        elif 'cash' in asset_class_lower or 'money' in asset_class_lower:
            return AssetClassType.CASH
        else:
            return AssetClassType.OTHER

    def _infer_region(self, asset_class: str) -> Region:
        """从资产大类推断地区"""
        asset_class_lower = asset_class.lower()

        if 'china' in asset_class_lower or 'a_share' in asset_class_lower or 'sh' in asset_class_lower:
            return Region.CN
        elif 'us' in asset_class_lower:
            return Region.US
        elif 'global' in asset_class_lower:
            return Region.GLOBAL
        else:
            return Region.CN  # 默认中国
