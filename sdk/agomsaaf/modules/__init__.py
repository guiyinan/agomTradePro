"""
AgomSAAF SDK 业务模块

包含所有业务模块的客户端封装。
"""

from .account import AccountModule
from .backtest import BacktestModule
from .base import BaseModule
from .equity import EquityModule
from .factor import FactorModule
from .fund import FundModule
from .hedge import HedgeModule
from .macro import MacroModule
from .policy import PolicyModule
from .realtime import RealtimeModule
from .regime import RegimeModule
from .rotation import RotationModule
from .sector import SectorModule
from .signal import SignalModule
from .simulated_trading import SimulatedTradingModule
from .strategy import StrategyModule

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
    "FactorModule",
    "FundModule",
    "SectorModule",
    "StrategyModule",
    "RealtimeModule",
    "RotationModule",
    "HedgeModule",
]
