"""
AgomSAAF SDK 业务模块

包含所有业务模块的客户端封装。
"""

from agomsaaf.modules.account import AccountModule
from agomsaaf.modules.backtest import BacktestModule
from agomsaaf.modules.base import BaseModule
from agomsaaf.modules.equity import EquityModule
from agomsaaf.modules.fund import FundModule
from agomsaaf.modules.macro import MacroModule
from agomsaaf.modules.policy import PolicyModule
from agomsaaf.modules.realtime import RealtimeModule
from agomsaaf.modules.regime import RegimeModule
from agomsaaf.modules.sector import SectorModule
from agomsaaf.modules.signal import SignalModule
from agomsaaf.modules.simulated_trading import SimulatedTradingModule
from agomsaaf.modules.strategy import StrategyModule

__all__ = [
    "BaseModule",
    "RegimeModule",
    "SignalModule",
    "MacroModule",
    "PolicyModule",
    "BacktestModule",
    "AccountModule",
    "SimulatedTradingModule",
    "EquityModule",
    "FundModule",
    "SectorModule",
    "StrategyModule",
    "RealtimeModule",
]
