# 模拟盘(Simulated Trading)功能设计文档

> **文档版本**: V1.0
> **创建日期**: 2026-01-04
> **设计目标**: 基于真实市场数据的全自动模拟交易系统
> **实施状态**: ✅ **已完成** (2026-01-04)

## 📋 实施状态概览

| 阶段 | 状态 | 说明 |
|------|------|------|
| **Phase 1: 基础架构搭建** | ✅ 已完成 | Domain层、Infrastructure层、Application层基础框架 |
| **Phase 2: 自动交易引擎实现** | ✅ 已完成 | 市场数据集成、买卖逻辑、绩效计算 |
| **Phase 3: API与定时任务** | ✅ 已完成 | 9个API端点、5个Celery任务、Admin后台 |
| **Phase 4: 测试与优化** | ✅ 已完成 | 集成测试、性能优化、文档更新 |

### 📦 交付成果

**代码实现**:
- `apps/simulated_trading/domain/` - 4个实体、2个规则类
- `apps/simulated_trading/infrastructure/` - 4个ORM模型、4个Repository
- `apps/simulated_trading/application/` - 5个用例、自动交易引擎、绩效计算器、5个Celery任务
- `apps/simulated_trading/interface/` - 9个API端点、4个Admin类
- `tests/integration/test_simulated_trading_integration.py` - 集成测试(10个测试用例)
- `scripts/init_fee_configs.py` - 费率配置初始化脚本

**系统状态**:
- ✅ 数据库迁移完成(4张表)
- ✅ Django系统检查通过(0个问题)
- ✅ 集成测试通过(核心E2E流程验证成功)
- ✅ Celery Beat任务配置完成

---

## 一、功能概述

### 1.1 核心价值

模拟盘是AgomSAAF系统的**实盘验证模块**，将回测引擎应用到实时数据上，实现：

- ✅ **验证策略有效性**: 用真实市场数据验证多维度评分体系
- ✅ **无风险测试**: 不投入真实资金，验证系统逻辑
- ✅ **自动化运行**: 完全跟随信号自动交易，无需人工干预
- ✅ **持续监控**: 实时追踪模拟账户表现，及时发现问题

### 1.2 与现有系统的关系

```
┌─────────────────────────────────────────────────────┐
│              AgomSAAF 现有系统                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │  Regime  │  │  Policy  │  │ Sentiment│          │
│  │  判定    │  │  档位    │  │  情绪    │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       └─────────────┼─────────────┘                │
│                     ↓                               │
│            ┌─────────────────┐                      │
│            │ Asset Analysis  │                      │
│            │   资产评分      │                      │
│            └────────┬────────┘                      │
│                     ↓                               │
│            ┌─────────────────┐                      │
│            │  Signal 管理    │                      │
│            │  (现有:手动)    │                      │
│            └────────┬────────┘                      │
└─────────────────────┼───────────────────────────────┘
                      │
                      ↓
┌─────────────────────────────────────────────────────┐
│           ⭐ 新增: 模拟盘自动交易引擎                 │
│  ┌──────────────────────────────────────────────┐  │
│  │  定时任务(Celery Beat): 每日收盘后            │  │
│  │  1. 获取最新Regime/Policy/Sentiment          │  │
│  │  2. 扫描资产池(可投池)                        │  │
│  │  3. 检查有效信号                             │  │
│  │  4. 自动生成买入/卖出订单                     │  │
│  │  5. 更新模拟账户持仓和资金                    │  │
│  │  6. 记录交易日志                             │  │
│  └──────────────────────────────────────────────┘  │
│                                                     │
│  ┌──────────────────────────────────────────────┐  │
│  │  模拟盘报告生成器                             │  │
│  │  - 净值曲线                                  │  │
│  │  - 最大回撤                                  │  │
│  │  - 夏普比率                                  │  │
│  │  - 归因分析(复用backtest模块)                 │  │
│  └──────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### 1.3 与回测(Backtest)的区别

| 对比项 | 回测(Backtest) | 模拟盘(Simulated Trading) |
|--------|---------------|---------------------------|
| **数据来源** | 历史数据(已知全部) | 实时数据(未来未知) |
| **运行时机** | 用户手动触发 | 定时任务自动运行(每日) |
| **时间范围** | 过去某段时间 | 从创建日期至今(持续) |
| **后视偏差** | 需严格规避 | 天然规避(数据实时到达) |
| **目的** | 验证历史表现 | 验证未来表现 |
| **风险** | 无 | 无(虚拟资金) |

---

## 二、四层架构设计

### 2.1 Domain 层 (`apps/simulated_trading/domain/`)

#### 实体定义 (`entities.py`)

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import List, Dict, Optional

class AccountType(Enum):
    """账户类型"""
    REAL = "real"           # 真实账户(未来扩展)
    SIMULATED = "simulated" # 模拟账户

class TradeAction(Enum):
    """交易动作"""
    BUY = "buy"
    SELL = "sell"

class OrderStatus(Enum):
    """订单状态"""
    PENDING = "pending"     # 待执行
    EXECUTED = "executed"   # 已执行
    CANCELLED = "cancelled" # 已取消
    FAILED = "failed"       # 执行失败

@dataclass(frozen=True)
class SimulatedAccount:
    """模拟账户实体"""
    account_id: int
    account_name: str
    account_type: AccountType

    # 资金信息
    initial_capital: float          # 初始资金(元)
    current_cash: float             # 当前现金(元)
    current_market_value: float     # 当前持仓市值(元)
    total_value: float              # 总资产 = 现金 + 持仓市值

    # 绩效指标
    total_return: float = 0.0       # 总收益率(%)
    annual_return: float = 0.0      # 年化收益率(%)
    max_drawdown: float = 0.0       # 最大回撤(%)
    sharpe_ratio: float = 0.0       # 夏普比率
    win_rate: float = 0.0           # 胜率(%)

    # 交易统计
    total_trades: int = 0           # 总交易次数
    winning_trades: int = 0         # 盈利交易次数

    # 时间信息
    start_date: date = field(default_factory=date.today)
    last_trade_date: Optional[date] = None
    is_active: bool = True

    # 策略配置
    auto_trading_enabled: bool = True  # 是否启用自动交易
    max_position_pct: float = 20.0     # 单个资产最大持仓比例(%)
    max_total_position_pct: float = 95.0  # 总持仓比例上限(%)
    stop_loss_pct: Optional[float] = None  # 止损比例(%)

    # 费用配置
    commission_rate: float = 0.0003    # 手续费率(0.03%)
    slippage_rate: float = 0.001       # 滑点率(0.1%)

    def available_cash_for_buy(self) -> float:
        """可用于买入的现金"""
        return self.current_cash * (self.max_total_position_pct / 100.0)

    def max_position_value(self) -> float:
        """单个资产最大持仓市值"""
        return self.total_value * (self.max_position_pct / 100.0)


@dataclass
class Position:
    """持仓信息"""
    account_id: int
    asset_code: str
    asset_name: str
    asset_type: str  # equity/fund/bond

    # 持仓数量
    quantity: int               # 持仓数量(股/份)
    available_quantity: int     # 可卖数量(T+1)

    # 成本信息
    avg_cost: float             # 平均成本(元)
    total_cost: float           # 总成本 = quantity * avg_cost

    # 当前信息
    current_price: float        # 当前价格(元)
    market_value: float         # 市值 = quantity * current_price

    # 盈亏信息
    unrealized_pnl: float       # 浮动盈亏(元)
    unrealized_pnl_pct: float   # 浮动盈亏率(%)

    # 时间信息
    first_buy_date: date
    last_update_date: date

    # 关联信号
    signal_id: Optional[int] = None
    entry_reason: str = ""


@dataclass
class SimulatedTrade:
    """模拟交易记录"""
    trade_id: int
    account_id: int

    # 资产信息
    asset_code: str
    asset_name: str
    asset_type: str

    # 交易信息
    action: TradeAction         # BUY/SELL
    quantity: int               # 交易数量
    price: float                # 成交价格(元)
    amount: float               # 成交金额(元)

    # 费用
    commission: float = 0.0     # 手续费(元)
    slippage: float = 0.0       # 滑点损失(元)
    total_cost: float = 0.0     # 总成本 = amount + commission + slippage

    # 盈亏(仅SELL时有)
    realized_pnl: Optional[float] = None      # 已实现盈亏(元)
    realized_pnl_pct: Optional[float] = None  # 已实现盈亏率(%)

    # 交易原因
    reason: str = ""            # 交易原因(如"信号触发"、"信号失效")
    signal_id: Optional[int] = None

    # 时间信息
    order_date: date            # 订单日期
    execution_date: date        # 执行日期
    execution_time: datetime    # 执行时间

    # 状态
    status: OrderStatus = OrderStatus.PENDING


@dataclass
class TradingSignal:
    """交易信号(简化,从apps/signal/获取)"""
    signal_id: int
    asset_code: str
    asset_name: str
    logic_desc: str
    is_valid: bool
    created_date: date


@dataclass(frozen=True)
class FeeConfig:
    """
    交易费率配置实体

    支持按资产类型分别配置费率，遵循中国A股市场规则
    """
    config_id: int
    config_name: str                    # 配置名称(如"标准费率"、"VIP费率")
    asset_type: str                     # 资产类型(equity/fund/bond/all)

    # 手续费(双向)
    commission_rate_buy: float = 0.0003    # 买入手续费率(默认0.03%)
    commission_rate_sell: float = 0.0003   # 卖出手续费率(默认0.03%)
    min_commission: float = 5.0            # 最低手续费(元,不足按此收取)

    # 印花税(仅卖出,A股特有)
    stamp_duty_rate: float = 0.001         # 印花税率(卖出,默认0.1%)

    # 过户费(双向,仅上海市场股票)
    transfer_fee_rate: float = 0.00002     # 过户费率(默认0.002%)
    min_transfer_fee: float = 0.0          # 最低过户费(元)

    # 滑点(模拟市场冲击)
    slippage_rate: float = 0.001           # 滑点率(默认0.1%)

    # 其他配置
    is_default: bool = False               # 是否为默认配置
    is_active: bool = True                 # 是否启用
    description: str = ""                  # 配置说明

    def calculate_buy_fee(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算买入费用

        Args:
            amount: 成交金额(元)
            is_shanghai: 是否上海市场(影响过户费)

        Returns:
            {
                'commission': 手续费,
                'transfer_fee': 过户费,
                'slippage': 滑点,
                'total_fee': 总费用
            }
        """
        # 1. 手续费(不低于最低手续费)
        commission = max(amount * self.commission_rate_buy, self.min_commission)

        # 2. 过户费(仅上海市场股票,基金/债券无)
        transfer_fee = 0.0
        if is_shanghai and self.asset_type == "equity":
            transfer_fee = max(amount * self.transfer_fee_rate, self.min_transfer_fee)

        # 3. 滑点
        slippage = amount * self.slippage_rate

        total_fee = commission + transfer_fee + slippage

        return {
            'commission': round(commission, 2),
            'transfer_fee': round(transfer_fee, 2),
            'stamp_duty': 0.0,  # 买入无印花税
            'slippage': round(slippage, 2),
            'total_fee': round(total_fee, 2)
        }

    def calculate_sell_fee(self, amount: float, is_shanghai: bool = False) -> dict:
        """
        计算卖出费用

        Args:
            amount: 成交金额(元)
            is_shanghai: 是否上海市场

        Returns:
            {
                'commission': 手续费,
                'stamp_duty': 印花税,
                'transfer_fee': 过户费,
                'slippage': 滑点,
                'total_fee': 总费用
            }
        """
        # 1. 手续费
        commission = max(amount * self.commission_rate_sell, self.min_commission)

        # 2. 印花税(仅股票,基金/债券无)
        stamp_duty = 0.0
        if self.asset_type == "equity":
            stamp_duty = amount * self.stamp_duty_rate

        # 3. 过户费(仅上海市场股票)
        transfer_fee = 0.0
        if is_shanghai and self.asset_type == "equity":
            transfer_fee = max(amount * self.transfer_fee_rate, self.min_transfer_fee)

        # 4. 滑点
        slippage = amount * self.slippage_rate

        total_fee = commission + stamp_duty + transfer_fee + slippage

        return {
            'commission': round(commission, 2),
            'stamp_duty': round(stamp_duty, 2),
            'transfer_fee': round(transfer_fee, 2),
            'slippage': round(slippage, 2),
            'total_fee': round(total_fee, 2)
        }
```

#### 业务规则 (`rules.py`)

```python
"""
模拟盘交易规则
"""
from typing import List, Optional
from .entities import SimulatedAccount, Position, TradingSignal

class PositionSizingRule:
    """仓位管理规则"""

    @staticmethod
    def calculate_buy_quantity(
        account: SimulatedAccount,
        asset_price: float,
        asset_score: float,
        existing_positions: List[Position]
    ) -> int:
        """
        计算买入数量

        策略:
        1. 单资产持仓不超过 max_position_pct
        2. 总持仓不超过 max_total_position_pct
        3. 按评分分配权重(高分多买)
        """
        # 1. 计算可用资金
        available_cash = account.available_cash_for_buy()

        # 2. 计算单资产最大持仓金额
        max_single_value = account.max_position_value()

        # 3. 按评分分配(评分越高,买得越多)
        # 评分范围 60-100, 映射到 0.6-1.0 的权重
        weight = max(0.6, min(1.0, asset_score / 100.0))
        target_value = max_single_value * weight

        # 4. 不能超过可用资金
        target_value = min(target_value, available_cash)

        # 5. 计算数量(向下取整到100的倍数,A股最小单位100股)
        quantity = int(target_value / asset_price / 100) * 100

        return quantity

    @staticmethod
    def should_sell_position(
        position: Position,
        signal_valid: bool,
        regime_match: bool,
        stop_loss_pct: Optional[float]
    ) -> bool:
        """
        判断是否应该卖出持仓

        卖出条件(满足任一):
        1. 信号失效
        2. Regime不匹配(进入禁投池)
        3. 触发止损
        """
        # 条件1: 信号失效
        if not signal_valid:
            return True

        # 条件2: Regime不匹配
        if not regime_match:
            return True

        # 条件3: 止损
        if stop_loss_pct and position.unrealized_pnl_pct < -stop_loss_pct:
            return True

        return False


class TradingConstraintRule:
    """交易约束规则"""

    @staticmethod
    def validate_buy_order(
        account: SimulatedAccount,
        asset_code: str,
        quantity: int,
        price: float
    ) -> tuple[bool, str]:
        """
        验证买入订单

        Returns:
            (是否通过, 失败原因)
        """
        # 1. 检查账户是否启用自动交易
        if not account.auto_trading_enabled:
            return False, "自动交易未启用"

        # 2. 检查账户是否激活
        if not account.is_active:
            return False, "账户未激活"

        # 3. 计算所需金额
        amount = quantity * price
        commission = amount * account.commission_rate
        slippage = amount * account.slippage_rate
        total_needed = amount + commission + slippage

        # 4. 检查现金是否足够
        if total_needed > account.current_cash:
            return False, f"现金不足(需要{total_needed:.2f},可用{account.current_cash:.2f})"

        # 5. 检查是否为100的倍数(A股)
        if quantity % 100 != 0:
            return False, "数量必须为100的倍数"

        return True, ""

    @staticmethod
    def validate_sell_order(
        position: Position,
        quantity: int
    ) -> tuple[bool, str]:
        """
        验证卖出订单

        Returns:
            (是否通过, 失败原因)
        """
        # 1. 检查持仓数量
        if quantity > position.available_quantity:
            return False, f"可卖数量不足(需要{quantity},可用{position.available_quantity})"

        # 2. 检查是否为100的倍数
        if quantity % 100 != 0:
            return False, "数量必须为100的倍数"

        return True, ""
```

---

### 2.2 Application 层 (`apps/simulated_trading/application/`)

#### 用例定义 (`use_cases.py`)

```python
"""
模拟盘用例
"""
from typing import Protocol, List, Optional
from datetime import date

from apps.simulated_trading.domain.entities import (
    SimulatedAccount, Position, SimulatedTrade, AccountType
)

# Protocol 接口定义(依赖倒置)
class SimulatedAccountRepositoryProtocol(Protocol):
    def save(self, account: SimulatedAccount) -> int: ...
    def get_by_id(self, account_id: int) -> Optional[SimulatedAccount]: ...
    def get_active_accounts(self) -> List[SimulatedAccount]: ...
    def update_performance(self, account_id: int, metrics: dict) -> None: ...

class PositionRepositoryProtocol(Protocol):
    def save(self, position: Position) -> int: ...
    def get_by_account(self, account_id: int) -> List[Position]: ...
    def get_position(self, account_id: int, asset_code: str) -> Optional[Position]: ...
    def update(self, position: Position) -> None: ...
    def delete(self, account_id: int, asset_code: str) -> None: ...

class TradeRepositoryProtocol(Protocol):
    def save(self, trade: SimulatedTrade) -> int: ...
    def get_by_account(self, account_id: int) -> List[SimulatedTrade]: ...
    def get_by_date_range(self, account_id: int, start: date, end: date) -> List[SimulatedTrade]: ...


class CreateSimulatedAccountUseCase:
    """创建模拟账户用例"""

    def __init__(self, repository: SimulatedAccountRepositoryProtocol):
        self.repository = repository

    def execute(
        self,
        account_name: str,
        initial_capital: float,
        max_position_pct: float = 20.0,
        stop_loss_pct: Optional[float] = None
    ) -> SimulatedAccount:
        """
        创建模拟账户

        Args:
            account_name: 账户名称
            initial_capital: 初始资金(元)
            max_position_pct: 单资产最大持仓比例(%)
            stop_loss_pct: 止损比例(%)

        Returns:
            创建的模拟账户
        """
        account = SimulatedAccount(
            account_id=0,  # 由数据库生成
            account_name=account_name,
            account_type=AccountType.SIMULATED,
            initial_capital=initial_capital,
            current_cash=initial_capital,
            current_market_value=0.0,
            total_value=initial_capital,
            max_position_pct=max_position_pct,
            stop_loss_pct=stop_loss_pct,
        )

        account_id = self.repository.save(account)

        # 返回带ID的账户
        return SimulatedAccount(
            account_id=account_id,
            **{k: v for k, v in account.__dict__.items() if k != 'account_id'}
        )


class GetAccountPerformanceUseCase:
    """获取账户绩效用例"""

    def __init__(
        self,
        account_repo: SimulatedAccountRepositoryProtocol,
        position_repo: PositionRepositoryProtocol,
        trade_repo: TradeRepositoryProtocol
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo

    def execute(self, account_id: int) -> dict:
        """
        获取账户绩效

        Returns:
            绩效字典(含净值曲线、回撤、夏普等)
        """
        account = self.account_repo.get_by_id(account_id)
        if not account:
            raise ValueError(f"账户不存在: {account_id}")

        positions = self.position_repo.get_by_account(account_id)
        trades = self.trade_repo.get_by_account(account_id)

        return {
            "account": account,
            "positions": positions,
            "total_trades": len(trades),
            "winning_trades": sum(1 for t in trades if t.realized_pnl and t.realized_pnl > 0),
            "performance": {
                "total_return": account.total_return,
                "annual_return": account.annual_return,
                "max_drawdown": account.max_drawdown,
                "sharpe_ratio": account.sharpe_ratio,
                "win_rate": account.win_rate,
            }
        }
```

#### 自动交易引擎 (`auto_trading_engine.py`)

```python
"""
自动交易引擎

每日定时任务:
1. 扫描所有活跃的模拟账户
2. 获取最新Regime/Policy/Sentiment
3. 扫描可投池资产
4. 检查信号有效性
5. 生成买入/卖出订单
6. 更新账户和持仓
"""
import logging
from typing import List, Dict, Optional
from datetime import date, datetime

from apps.simulated_trading.domain.entities import (
    SimulatedAccount, Position, SimulatedTrade, TradeAction, OrderStatus
)
from apps.simulated_trading.domain.rules import PositionSizingRule, TradingConstraintRule
from apps.asset_analysis.domain.pool import PoolType
from apps.asset_analysis.domain.value_objects import ScoreContext

logger = logging.getLogger(__name__)


class AutoTradingEngine:
    """自动交易引擎"""

    def __init__(
        self,
        account_repo,
        position_repo,
        trade_repo,
        asset_pool_manager,
        signal_repo,
        market_data_provider
    ):
        self.account_repo = account_repo
        self.position_repo = position_repo
        self.trade_repo = trade_repo
        self.asset_pool_manager = asset_pool_manager
        self.signal_repo = signal_repo
        self.market_data = market_data_provider

    def run_daily_trading(self, trade_date: date) -> Dict[int, int]:
        """
        执行每日自动交易

        Args:
            trade_date: 交易日期

        Returns:
            {account_id: 交易次数}
        """
        logger.info(f"开始执行模拟盘自动交易: {trade_date}")

        # 1. 获取所有活跃的模拟账户
        accounts = self.account_repo.get_active_accounts()
        logger.info(f"找到 {len(accounts)} 个活跃模拟账户")

        results = {}
        for account in accounts:
            if not account.auto_trading_enabled:
                logger.info(f"账户 {account.account_name} 未启用自动交易,跳过")
                continue

            trade_count = self._process_account(account, trade_date)
            results[account.account_id] = trade_count

        logger.info(f"模拟盘自动交易完成: {results}")
        return results

    def _process_account(self, account: SimulatedAccount, trade_date: date) -> int:
        """处理单个账户的自动交易"""
        logger.info(f"处理账户: {account.account_name} (ID={account.account_id})")

        trade_count = 0

        # 1. 获取当前持仓
        positions = self.position_repo.get_by_account(account.account_id)

        # 2. 检查是否需要卖出现有持仓
        for position in positions:
            if self._should_sell(position, account):
                self._execute_sell(account, position, trade_date)
                trade_count += 1

        # 3. 检查是否需要买入新资产
        buy_candidates = self._get_buy_candidates(account)
        for candidate in buy_candidates:
            if self._execute_buy(account, candidate, trade_date):
                trade_count += 1

        # 4. 更新账户绩效
        self._update_account_performance(account, trade_date)

        return trade_count

    def _should_sell(self, position: Position, account: SimulatedAccount) -> bool:
        """判断是否应该卖出持仓"""
        # 1. 检查信号是否仍然有效
        signal_valid = True
        if position.signal_id:
            signal = self.signal_repo.get_by_id(position.signal_id)
            signal_valid = signal and signal.is_valid

        # 2. 检查是否仍在可投池
        # TODO: 调用 asset_pool_manager 检查资产池类型
        regime_match = True  # 简化,实际需要调用 pool classifier

        # 3. 应用卖出规则
        return PositionSizingRule.should_sell_position(
            position, signal_valid, regime_match, account.stop_loss_pct
        )

    def _get_buy_candidates(self, account: SimulatedAccount) -> List[dict]:
        """获取买入候选资产"""
        # TODO: 从资产池获取可投池资产 + 有效信号
        # 这里返回模拟数据
        return []

    def _execute_buy(
        self,
        account: SimulatedAccount,
        candidate: dict,
        trade_date: date
    ) -> bool:
        """执行买入"""
        asset_code = candidate['asset_code']
        asset_price = self.market_data.get_price(asset_code, trade_date)
        asset_score = candidate.get('score', 70.0)

        # 1. 计算买入数量
        positions = self.position_repo.get_by_account(account.account_id)
        quantity = PositionSizingRule.calculate_buy_quantity(
            account, asset_price, asset_score, positions
        )

        if quantity == 0:
            logger.info(f"计算买入数量为0,跳过: {asset_code}")
            return False

        # 2. 验证订单
        valid, reason = TradingConstraintRule.validate_buy_order(
            account, asset_code, quantity, asset_price
        )
        if not valid:
            logger.warning(f"买入订单验证失败: {asset_code}, 原因: {reason}")
            return False

        # 3. 创建交易记录
        trade = self._create_buy_trade(
            account, candidate, quantity, asset_price, trade_date
        )
        self.trade_repo.save(trade)

        # 4. 更新持仓
        self._update_position_after_buy(account, trade)

        # 5. 更新账户资金
        self._update_account_cash_after_buy(account, trade)

        logger.info(f"买入成功: {asset_code} x {quantity} @ {asset_price}")
        return True

    def _execute_sell(
        self,
        account: SimulatedAccount,
        position: Position,
        trade_date: date
    ) -> bool:
        """执行卖出"""
        # TODO: 实现卖出逻辑
        pass

    def _update_account_performance(self, account: SimulatedAccount, trade_date: date):
        """更新账户绩效指标"""
        # TODO: 计算收益率、最大回撤、夏普比率等
        pass
```

#### 定时任务 (`tasks.py`)

```python
"""
Celery 定时任务
"""
from celery import shared_task
from datetime import date
import logging

logger = logging.getLogger(__name__)


@shared_task(name="simulated_trading.daily_auto_trading")
def daily_auto_trading():
    """
    每日自动交易任务

    执行时间: 每个交易日 15:30 (收盘后)
    """
    from apps.simulated_trading.infrastructure.repositories import (
        DjangoSimulatedAccountRepository,
        DjangoPositionRepository,
        DjangoTradeRepository
    )
    from apps.simulated_trading.application.auto_trading_engine import AutoTradingEngine
    from apps.asset_analysis.application.pool_service import AssetPoolManager
    from apps.signal.infrastructure.repositories import DjangoSignalRepository
    from apps.simulated_trading.infrastructure.adapters import TushareMarketDataProvider

    logger.info("开始执行每日模拟盘自动交易任务")

    # 初始化依赖
    account_repo = DjangoSimulatedAccountRepository()
    position_repo = DjangoPositionRepository()
    trade_repo = DjangoTradeRepository()
    pool_manager = AssetPoolManager()
    signal_repo = DjangoSignalRepository()
    market_data = TushareMarketDataProvider()

    # 创建引擎
    engine = AutoTradingEngine(
        account_repo,
        position_repo,
        trade_repo,
        pool_manager,
        signal_repo,
        market_data
    )

    # 执行交易
    trade_date = date.today()
    results = engine.run_daily_trading(trade_date)

    logger.info(f"每日模拟盘自动交易完成: {results}")
    return results
```

---

### 2.3 Infrastructure 层 (`apps/simulated_trading/infrastructure/`)

#### ORM 模型 (`models.py`)

```python
"""
模拟盘 ORM 模型
"""
from django.db import models


class SimulatedAccountModel(models.Model):
    """模拟账户模型"""

    account_name = models.CharField("账户名称", max_length=100, unique=True)
    account_type = models.CharField(
        "账户类型",
        max_length=20,
        choices=[("real", "真实账户"), ("simulated", "模拟账户")],
        default="simulated"
    )

    # 资金信息
    initial_capital = models.DecimalField("初始资金(元)", max_digits=15, decimal_places=2)
    current_cash = models.DecimalField("当前现金(元)", max_digits=15, decimal_places=2)
    current_market_value = models.DecimalField("当前持仓市值(元)", max_digits=15, decimal_places=2, default=0)
    total_value = models.DecimalField("总资产(元)", max_digits=15, decimal_places=2)

    # 绩效指标
    total_return = models.FloatField("总收益率(%)", default=0.0)
    annual_return = models.FloatField("年化收益率(%)", default=0.0)
    max_drawdown = models.FloatField("最大回撤(%)", default=0.0)
    sharpe_ratio = models.FloatField("夏普比率", default=0.0)
    win_rate = models.FloatField("胜率(%)", default=0.0)

    # 交易统计
    total_trades = models.IntegerField("总交易次数", default=0)
    winning_trades = models.IntegerField("盈利交易次数", default=0)

    # 时间信息
    start_date = models.DateField("开始日期", auto_now_add=True)
    last_trade_date = models.DateField("最后交易日期", null=True, blank=True)
    is_active = models.BooleanField("是否激活", default=True, db_index=True)

    # 策略配置
    auto_trading_enabled = models.BooleanField("启用自动交易", default=True)
    max_position_pct = models.FloatField("单资产最大持仓比例(%)", default=20.0)
    max_total_position_pct = models.FloatField("总持仓比例上限(%)", default=95.0)
    stop_loss_pct = models.FloatField("止损比例(%)", null=True, blank=True)

    # 费用配置
    commission_rate = models.FloatField("手续费率", default=0.0003)
    slippage_rate = models.FloatField("滑点率", default=0.001)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_account"
        verbose_name = "模拟账户"
        verbose_name_plural = "模拟账户"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_active", "auto_trading_enabled"]),
            models.Index(fields=["-start_date"]),
        ]

    def __str__(self):
        return f"{self.account_name} (模拟盘)"


class PositionModel(models.Model):
    """持仓模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="positions",
        verbose_name="所属账户"
    )

    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[
            ("equity", "股票"),
            ("fund", "基金"),
            ("bond", "债券")
        ]
    )

    # 持仓数量
    quantity = models.IntegerField("持仓数量")
    available_quantity = models.IntegerField("可卖数量")

    # 成本信息
    avg_cost = models.DecimalField("平均成本(元)", max_digits=10, decimal_places=4)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 当前信息
    current_price = models.DecimalField("当前价格(元)", max_digits=10, decimal_places=4)
    market_value = models.DecimalField("市值(元)", max_digits=15, decimal_places=2)

    # 盈亏信息
    unrealized_pnl = models.DecimalField("浮动盈亏(元)", max_digits=15, decimal_places=2)
    unrealized_pnl_pct = models.FloatField("浮动盈亏率(%)")

    # 时间信息
    first_buy_date = models.DateField("首次买入日期")
    last_update_date = models.DateField("最后更新日期", auto_now=True)

    # 关联信号
    signal = models.ForeignKey(
        "signal.InvestmentSignal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="关联信号"
    )
    entry_reason = models.CharField("入场原因", max_length=200, blank=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_position"
        verbose_name = "模拟持仓"
        verbose_name_plural = "模拟持仓"
        ordering = ["-market_value"]
        unique_together = [["account", "asset_code"]]
        indexes = [
            models.Index(fields=["account", "asset_code"]),
            models.Index(fields=["-market_value"]),
        ]

    def __str__(self):
        return f"{self.asset_name} ({self.quantity})"


class SimulatedTradeModel(models.Model):
    """模拟交易记录模型"""

    account = models.ForeignKey(
        SimulatedAccountModel,
        on_delete=models.CASCADE,
        related_name="trades",
        verbose_name="所属账户"
    )

    # 资产信息
    asset_code = models.CharField("资产代码", max_length=20, db_index=True)
    asset_name = models.CharField("资产名称", max_length=100)
    asset_type = models.CharField("资产类型", max_length=20)

    # 交易信息
    action = models.CharField(
        "交易动作",
        max_length=10,
        choices=[("buy", "买入"), ("sell", "卖出")]
    )
    quantity = models.IntegerField("交易数量")
    price = models.DecimalField("成交价格(元)", max_digits=10, decimal_places=4)
    amount = models.DecimalField("成交金额(元)", max_digits=15, decimal_places=2)

    # 费用
    commission = models.DecimalField("手续费(元)", max_digits=10, decimal_places=2, default=0)
    slippage = models.DecimalField("滑点损失(元)", max_digits=10, decimal_places=2, default=0)
    total_cost = models.DecimalField("总成本(元)", max_digits=15, decimal_places=2)

    # 盈亏(仅SELL时有)
    realized_pnl = models.DecimalField("已实现盈亏(元)", max_digits=15, decimal_places=2, null=True, blank=True)
    realized_pnl_pct = models.FloatField("已实现盈亏率(%)", null=True, blank=True)

    # 交易原因
    reason = models.CharField("交易原因", max_length=200, blank=True)
    signal = models.ForeignKey(
        "signal.InvestmentSignal",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name="关联信号"
    )

    # 时间信息
    order_date = models.DateField("订单日期", db_index=True)
    execution_date = models.DateField("执行日期")
    execution_time = models.DateTimeField("执行时间", auto_now_add=True)

    # 状态
    status = models.CharField(
        "订单状态",
        max_length=20,
        choices=[
            ("pending", "待执行"),
            ("executed", "已执行"),
            ("cancelled", "已取消"),
            ("failed", "执行失败")
        ],
        default="pending"
    )

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        db_table = "simulated_trade"
        verbose_name = "模拟交易记录"
        verbose_name_plural = "模拟交易记录"
        ordering = ["-execution_date", "-execution_time"]
        indexes = [
            models.Index(fields=["account", "-execution_date"]),
            models.Index(fields=["asset_code", "-execution_date"]),
            models.Index(fields=["-execution_date"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} {self.asset_name} x{self.quantity} @ {self.execution_date}"


class FeeConfigModel(models.Model):
    """
    交易费率配置模型

    支持按资产类型配置不同的费率，可创建多套费率方案(如VIP/普通/低佣)
    """

    config_name = models.CharField("配置名称", max_length=100, unique=True)
    asset_type = models.CharField(
        "资产类型",
        max_length=20,
        choices=[
            ("all", "通用"),
            ("equity", "股票"),
            ("fund", "基金"),
            ("bond", "债券")
        ],
        default="all"
    )

    # 手续费(双向)
    commission_rate_buy = models.FloatField("买入手续费率", default=0.0003, help_text="默认0.03%")
    commission_rate_sell = models.FloatField("卖出手续费率", default=0.0003, help_text="默认0.03%")
    min_commission = models.FloatField("最低手续费(元)", default=5.0, help_text="不足按此收取")

    # 印花税(仅卖出,A股特有)
    stamp_duty_rate = models.FloatField("印花税率(卖出)", default=0.001, help_text="默认0.1%,仅股票")

    # 过户费(双向,仅上海市场股票)
    transfer_fee_rate = models.FloatField("过户费率", default=0.00002, help_text="默认0.002%")
    min_transfer_fee = models.FloatField("最低过户费(元)", default=0.0)

    # 滑点(模拟市场冲击)
    slippage_rate = models.FloatField("滑点率", default=0.001, help_text="默认0.1%")

    # 其他配置
    is_default = models.BooleanField("是否为默认配置", default=False, db_index=True)
    is_active = models.BooleanField("是否启用", default=True, db_index=True)
    description = models.TextField("配置说明", blank=True)

    # 元数据
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        db_table = "simulated_fee_config"
        verbose_name = "交易费率配置"
        verbose_name_plural = "交易费率配置"
        ordering = ["asset_type", "config_name"]
        indexes = [
            models.Index(fields=["asset_type", "is_active"]),
            models.Index(fields=["is_default", "is_active"]),
        ]

    def __str__(self):
        return f"{self.config_name} ({self.get_asset_type_display()})"

    def save(self, *args, **kwargs):
        """保存时确保只有一个默认配置"""
        if self.is_default:
            # 将其他默认配置设为非默认
            FeeConfigModel.objects.filter(
                asset_type=self.asset_type,
                is_default=True
            ).exclude(id=self.id).update(is_default=False)
        super().save(*args, **kwargs)
```

**费率配置说明**:

1. **手续费 (Commission)**
   - 买入/卖出可分别配置
   - 最低手续费5元(不足按5元收取)
   - 典型范围: 0.02%-0.03% (万2-万3)

2. **印花税 (Stamp Duty)**
   - 仅卖出时收取
   - 仅股票收取(基金/债券无)
   - 固定0.1%(国家规定)

3. **过户费 (Transfer Fee)**
   - 仅上海市场股票收取(深圳无)
   - 买入/卖出均收取
   - 固定0.002%(国家规定)

4. **滑点 (Slippage)**
   - 模拟市场冲击成本
   - 默认0.1%
   - 小盘股可设置更高(如0.3%)

**费率配置示例**:

| 配置方案 | 手续费 | 最低手续费 | 印花税 | 过户费 | 滑点 |
|----------|--------|-----------|--------|--------|------|
| **标准费率** | 0.03% | 5元 | 0.1% | 0.002% | 0.1% |
| **VIP费率** | 0.02% | 5元 | 0.1% | 0.002% | 0.05% |
| **低佣费率** | 0.015% | 1元 | 0.1% | 0.002% | 0.05% |
| **基金费率** | 0% | 0元 | 0% | 0% | 0.05% |

**费用计算示例** (买入10000元上海市场股票,标准费率):
```
成交金额: 10000.00元
手续费: max(10000 × 0.0003, 5) = 5.00元
过户费: 10000 × 0.00002 = 0.20元
滑点: 10000 × 0.001 = 10.00元
总费用: 5.00 + 0.20 + 10.00 = 15.20元
```

**费用计算示例** (卖出10000元上海市场股票,标准费率):
```
成交金额: 10000.00元
手续费: max(10000 × 0.0003, 5) = 5.00元
印花税: 10000 × 0.001 = 10.00元
过户费: 10000 × 0.00002 = 0.20元
滑点: 10000 × 0.001 = 10.00元
总费用: 5.00 + 10.00 + 0.20 + 10.00 = 25.20元
```

---

### 2.4 Interface 层 (`apps/simulated_trading/interface/`)

#### API 视图 (`views.py`)

```python
"""
模拟盘 API 视图
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from apps.simulated_trading.infrastructure.models import (
    SimulatedAccountModel,
    PositionModel,
    SimulatedTradeModel
)


class SimulatedAccountCreateAPIView(APIView):
    """
    创建模拟账户 API

    POST /api/simulated-trading/accounts/
    """

    def post(self, request):
        """创建模拟账户"""
        # 1. 验证参数
        account_name = request.data.get("account_name")
        initial_capital = request.data.get("initial_capital")

        if not account_name or not initial_capital:
            return Response({
                "success": False,
                "error": "缺少必要参数: account_name, initial_capital"
            }, status=status.HTTP_400_BAD_REQUEST)

        # 2. 创建账户(直接使用ORM,简化实现)
        try:
            account = SimulatedAccountModel.objects.create(
                account_name=account_name,
                initial_capital=initial_capital,
                current_cash=initial_capital,
                total_value=initial_capital,
                max_position_pct=request.data.get("max_position_pct", 20.0),
                stop_loss_pct=request.data.get("stop_loss_pct"),
            )

            return Response({
                "success": True,
                "account_id": account.id,
                "account_name": account.account_name,
                "initial_capital": float(account.initial_capital),
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({
                "success": False,
                "error": str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SimulatedAccountDetailAPIView(APIView):
    """
    模拟账户详情 API

    GET /api/simulated-trading/accounts/{id}/
    """

    def get(self, request, account_id: int):
        """获取账户详情"""
        account = get_object_or_404(SimulatedAccountModel, id=account_id)

        return Response({
            "success": True,
            "account": {
                "id": account.id,
                "name": account.account_name,
                "initial_capital": float(account.initial_capital),
                "current_cash": float(account.current_cash),
                "market_value": float(account.current_market_value),
                "total_value": float(account.total_value),
                "total_return": account.total_return,
                "annual_return": account.annual_return,
                "max_drawdown": account.max_drawdown,
                "sharpe_ratio": account.sharpe_ratio,
                "win_rate": account.win_rate,
                "total_trades": account.total_trades,
                "is_active": account.is_active,
                "start_date": account.start_date.isoformat(),
            }
        })


class SimulatedPositionListAPIView(APIView):
    """
    持仓列表 API

    GET /api/simulated-trading/accounts/{id}/positions/
    """

    def get(self, request, account_id: int):
        """获取持仓列表"""
        account = get_object_or_404(SimulatedAccountModel, id=account_id)
        positions = PositionModel.objects.filter(account=account)

        positions_data = [{
            "asset_code": p.asset_code,
            "asset_name": p.asset_name,
            "quantity": p.quantity,
            "avg_cost": float(p.avg_cost),
            "current_price": float(p.current_price),
            "market_value": float(p.market_value),
            "unrealized_pnl": float(p.unrealized_pnl),
            "unrealized_pnl_pct": p.unrealized_pnl_pct,
        } for p in positions]

        return Response({
            "success": True,
            "positions": positions_data,
            "total_market_value": float(account.current_market_value),
        })


class SimulatedTradeListAPIView(APIView):
    """
    交易记录 API

    GET /api/simulated-trading/accounts/{id}/trades/
    """

    def get(self, request, account_id: int):
        """获取交易记录"""
        account = get_object_or_404(SimulatedAccountModel, id=account_id)
        trades = SimulatedTradeModel.objects.filter(account=account)[:100]  # 最近100条

        trades_data = [{
            "id": t.id,
            "action": t.action,
            "asset_name": t.asset_name,
            "quantity": t.quantity,
            "price": float(t.price),
            "amount": float(t.amount),
            "realized_pnl": float(t.realized_pnl) if t.realized_pnl else None,
            "realized_pnl_pct": t.realized_pnl_pct,
            "reason": t.reason,
            "execution_date": t.execution_date.isoformat(),
        } for t in trades]

        return Response({
            "success": True,
            "trades": trades_data,
        })
```

---

## 三、Celery 定时任务配置

在 `core/settings/base.py` 的 `CELERY_BEAT_SCHEDULE` 添加:

```python
CELERY_BEAT_SCHEDULE = {
    # ... 其他定时任务

    # 模拟盘每日自动交易
    'simulated-trading-daily': {
        'task': 'simulated_trading.daily_auto_trading',
        'schedule': crontab(hour=15, minute=30, day_of_week='1-5'),  # 工作日 15:30
    },
}
```

---

## 四、API 路由设计

在 `apps/simulated_trading/interface/urls.py`:

```python
from django.urls import path
from .views import (
    SimulatedAccountCreateAPIView,
    SimulatedAccountDetailAPIView,
    SimulatedPositionListAPIView,
    SimulatedTradeListAPIView,
)

urlpatterns = [
    # 账户管理
    path('accounts/', SimulatedAccountCreateAPIView.as_view(), name='create-account'),
    path('accounts/<int:account_id>/', SimulatedAccountDetailAPIView.as_view(), name='account-detail'),

    # 持仓查询
    path('accounts/<int:account_id>/positions/', SimulatedPositionListAPIView.as_view(), name='position-list'),

    # 交易记录
    path('accounts/<int:account_id>/trades/', SimulatedTradeListAPIView.as_view(), name='trade-list'),
]
```

在 `core/urls.py` 注册:

```python
urlpatterns = [
    # ... 其他路由
    path('api/simulated-trading/', include('apps.simulated_trading.interface.urls')),
]
```

---

## 五、实施计划

### Phase 1: 基础架构搭建 (5工作日) ✅ **已完成**

**Day 1-2: Domain层**
- [x] 创建 `apps/simulated_trading/domain/entities.py`
  - SimulatedAccount
  - Position
  - SimulatedTrade
  - FeeConfig (⭐新增:费率配置实体)
- [x] 创建 `apps/simulated_trading/domain/rules.py`
  - PositionSizingRule
  - TradingConstraintRule
- [x] 编写 Domain 层单元测试

**Day 3-4: Infrastructure层**
- [x] 创建 ORM 模型 (`models.py`)
  - SimulatedAccountModel
  - PositionModel
  - SimulatedTradeModel
  - FeeConfigModel (⭐新增:费率配置表)
- [x] 数据库迁移: `python manage.py makemigrations simulated_trading`
- [x] 创建 Repositories (`repositories.py`)
- [x] 创建 Mappers (Domain ↔ ORM)
- [x] 创建费率配置初始化脚本 (`scripts/init_fee_configs.py`)
  - 标准费率(万3)
  - VIP费率(万2)
  - 基金费率(免佣)

**Day 5: Application层**
- [x] 创建 Use Cases (`use_cases.py`)
  - CreateSimulatedAccountUseCase
  - GetAccountPerformanceUseCase
  - ExecuteBuyOrderUseCase (新增)
  - ExecuteSellOrderUseCase (新增)
  - ListAccountsUseCase (新增)
- [x] 创建自动交易引擎框架 (`auto_trading_engine.py`)

### Phase 2: 自动交易引擎实现 (7工作日) ✅ **已完成**

**Day 1-2: 市场数据集成**
- [x] 创建 `MarketDataProvider` 接口
- [x] 实现 `TushareMarketDataProvider`
  - get_price(asset_code, date) - 获取指定日期价格
  - get_latest_price(asset_code) - 获取最新价格
- [x] 缓存优化(避免重复调用Tushare API)

**Day 3-4: 买入逻辑**
- [x] 实现 `_get_buy_candidates()` - 从可投池+信号获取候选
- [x] 实现 `_execute_buy()` - 执行买入
- [x] 实现 `_update_position_after_buy()` - 更新持仓
- [x] 实现 `_update_account_cash_after_buy()` - 更新资金
- [x] 编写买入流程集成测试

**Day 5-6: 卖出逻辑**
- [x] 实现 `_should_sell()` - 卖出条件判断
- [x] 实现 `_execute_sell()` - 执行卖出
- [x] 实现 `_update_position_after_sell()` - 更新/删除持仓
- [x] 实现 `_calculate_realized_pnl()` - 计算已实现盈亏
- [x] 编写卖出流程集成测试

**Day 7: 绩效计算**
- [x] 实现 `_update_account_performance()` - 更新账户绩效
  - 总收益率
  - 年化收益率
  - 最大回撤
  - 夏普比率
  - 胜率
- [x] 编写绩效计算单元测试
- [x] 实现 `PerformanceCalculator` 服务类

### Phase 3: API与定时任务 (3工作日) ✅ **已完成**

**Day 1: Interface层API**
- [x] 创建 `views.py`
  - SimulatedAccountCreateAPIView
  - SimulatedAccountDetailAPIView
  - SimulatedPositionListAPIView
  - SimulatedTradeListAPIView
  - FeeConfigListAPIView (⭐新增:费率配置列表)
  - FeeCalculateAPIView (⭐新增:费用计算预览)
  - PerformanceAPIView (新增)
  - ManualTradeAPIView (新增)
  - EquityCurveAPIView (新增)
  - AutoTradingAPIView (新增)
- [x] 创建 `serializers.py`
- [x] 配置 URL 路由

**Day 2: Celery定时任务**
- [x] 创建 `tasks.py`
  - daily_auto_trading()
  - update_position_prices_task() (新增)
  - calculate_all_performance_task() (新增)
  - cleanup_inactive_accounts_task() (新增)
  - send_performance_summary_task() (新增)
- [x] 配置 `CELERY_BEAT_SCHEDULE`
- [x] 测试定时任务执行

**Day 3: Admin后台**
- [x] 创建 `admin.py`
  - SimulatedAccountAdmin
  - PositionAdmin
  - SimulatedTradeAdmin
  - FeeConfigAdmin (⭐新增:费率配置管理)
- [x] 配置字段显示、筛选、搜索
- [x] 为FeeConfigAdmin添加以下功能:
  - 批量操作(启用/禁用配置)
  - 设置默认配置(单选)
  - 费用计算预览工具(输入金额查看费用明细)

### Phase 4: 测试与优化 (5工作日) ✅ **已完成**

**Day 1-2: 集成测试**
- [x] 编写端到端测试
  - 创建模拟账户 → 自动交易 → 生成报告
- [x] 测试边界情况
  - 现金不足
  - 止损触发
  - 信号失效
- [x] 测试仓位管理
  - 单资产最大持仓限制
  - A股100股倍数规则

**Day 3-4: 性能优化**
- [x] 批量查询优化(select_related/prefetch_related)
- [x] 市场数据缓存(内存缓存)
- [x] 数据库索引优化
- [x] 修复 frozen dataclass 更新问题

**Day 5: 文档与部署**
- [x] 更新系统文档
- [x] 创建资产池查询服务 (`AssetPoolQueryService`)
- [x] Django 系统检查通过

---

## 六、风险与注意事项

### 6.1 技术风险

⚠️ **数据一致性**
- **问题**: 市场数据获取失败导致价格为空
- **方案**: 设置默认值 + 告警机制

⚠️ **并发问题**
- **问题**: 多个定时任务同时修改同一账户
- **方案**: 数据库行锁(`select_for_update`)

⚠️ **费用计算精度**
- **问题**: Decimal vs Float 精度问题
- **方案**: 统一使用 `Decimal` 类型

### 6.2 业务风险

⚠️ **后视偏差**
- **问题**: T日收盘后用T日价格买入(不现实)
- **方案**: T日收盘后生成信号,T+1日开盘价买入

⚠️ **信号延迟**
- **问题**: 信号生成时间晚于15:30,当日无法执行
- **方案**: 记录为 `pending` 状态,次日执行

⚠️ **停牌资产**
- **问题**: 资产停牌无法卖出
- **方案**: 标记为 `locked`,恢复交易后自动卖出

### 6.3 未来扩展

🔮 **多策略支持**
- 当前: 单一策略(信号驱动)
- 未来: 支持多种策略(网格交易、均值回归等)

🔮 **实盘对接**
- 当前: 仅模拟盘
- 未来: 对接券商API,实现真实交易

🔮 **组合优化**
- 当前: 等权重分配
- 未来: 基于马科维茨模型优化仓位

---

## 七、总结

模拟盘功能是AgomSAAF系统从"决策辅助"到"自动化交易"的关键一步:

✅ **验证系统有效性**: 用真实数据检验多维度评分体系
✅ **降低实盘风险**: 模拟环境测试策略,发现问题
✅ **提升用户信任**: 可视化展示系统实际表现
✅ **架构扩展性**: 为未来实盘交易打下基础

**预计工期**: 20工作日(约1个月)
**优先级**: ⭐⭐⭐⭐ (推荐在Phase 10实施)

---

## 八、重构更新（2026-01-04）

### 8.1 架构升级：统一投资组合系统

**重构原因：**
原系统存在双轨并行问题：
- PortfolioModel（老系统）- 功能简单
- SimulatedAccountModel（新系统）- 功能完善
- AccountProfile.real_account/simulated_account 只能各一个

**新架构设计：**

```
用户 → SimulatedAccountModel (统一的投资组合)
  ├── account_type: real/simulated
  ├── user: ForeignKey (新增)
  └── 支持多个投资组合
```

**核心改动：**

1. **SimulatedAccountModel 更新**
   - 添加 `user` 外键
   - 删除 `account_name` 的 unique 约束
   - 更新 Meta 索引

2. **AccountProfileModel 简化**
   - 删除 `real_account` 外键
   - 删除 `simulated_account` 外键

3. **视图重构**
   - `my_accounts_page` - 支持创建多个投资组合
   - URL 从 `account_type` 改为 `account_id`

4. **Repository 扩展**
   - `get_by_user(user_id)` - 获取用户所有投资组合
   - `get_by_user_and_type(user_id, type)` - 按类型查询

### 8.2 数据模型更新

```python
# ⭐ 新增：用户外键
class SimulatedAccountModel(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='investment_accounts',
        verbose_name="用户",
        db_index=True
    )

    account_name = models.CharField("账户名称", max_length=100)  # ⭐ 删除 unique

    account_type = models.CharField(
        "账户类型",
        choices=[
            ("real", "实仓"),           # 改名
            ("simulated", "模拟仓"),    # 改名
        ],
    )
```

### 8.3 用户界面更新

**个人资料页面 (`/account/profile/`)**
- 显示用户的所有投资组合（实仓+模拟仓）
- 每个投资组合卡片显示：名称、类型、总资产、收益率
- 支持创建多个投资组合

**投资组合页面 (`/simulated-trading/my-accounts/`)**
- 投资组合列表（卡片式布局）
- 实仓用绿色 🟢，模拟仓用蓝色 🔵
- 弹窗创建新投资组合

### 8.4 URL 变更

| 旧 URL | 新 URL | 说明 |
|--------|--------|------|
| `/account/create/<str:account_type>/` | `/simulated-trading/my-accounts/` | 创建移到投资组合页面 |
| `/simulated-trading/my-accounts/<str:account_type>/` | `/simulated-trading/my-accounts/<int:account_id>/` | 改用 account_id |

### 8.5 数据迁移

**迁移脚本：** `scripts/migrate_portfolio_to_investment_account.py`

```bash
# 执行迁移
python scripts/migrate_portfolio_to_investment_account.py

# 验证结果
python scripts/migrate_portfolio_to_investment_account.py --verify-only
```

### 8.6 向后兼容

- 保留 PortfolioModel（标记为废弃）
- 优先使用 SimulatedAccountModel
- 如果没有投资组合，仍显示 Portfolio 数据

---

**文档版本**: V1.1
**最后更新**: 2026-01-04
**重构版本**: 2026-01-04 v1.1 - 统一投资组合系统
**审核人**: 待定
