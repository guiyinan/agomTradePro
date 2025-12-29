"""
Domain Entities for Macro Data.

This file defines pure data classes using only Python standard library.
No Django, Pandas, or external dependencies allowed.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class MacroIndicator:
    """宏观指标值对象"""
    code: str
    value: float
    observed_at: date
    published_at: Optional[date] = None
    source: str = "unknown"
