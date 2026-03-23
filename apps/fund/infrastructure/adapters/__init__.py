"""
基金数据适配器

支持的数据源：
- Tushare: 基金净值、持仓
- AKShare: 基金基本信息
"""

from .akshare_fund_adapter import AkShareFundAdapter
from .hybrid_fund_adapter import HybridFundAdapter
from .tushare_fund_adapter import TushareFundAdapter

# Backward-compat alias used by alpha simple provider.
TushareAdapter = TushareFundAdapter

__all__ = [
    "TushareFundAdapter",
    "AkShareFundAdapter",
    "HybridFundAdapter",
    "TushareAdapter",
]
