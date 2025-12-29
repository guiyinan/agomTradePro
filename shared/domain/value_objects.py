"""
Shared Value Objects.
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional


@dataclass(frozen=True)
class DateRange:
    """日期范围值对象"""
    start: date
    end: date

    def __post_init__(self):
        if self.start > self.end:
            raise ValueError("start date must be before end date")

    @property
    def days(self) -> int:
        return (self.end - self.start).days


@dataclass(frozen=True)
class Percentage:
    """百分比值对象"""
    value: float

    def __post_init__(self):
        if not 0 <= self.value <= 100:
            raise ValueError("percentage must be between 0 and 100")

    @property
    def as_decimal(self) -> float:
        return self.value / 100

    def __str__(self) -> str:
        return f"{self.value:.2f}%"


@dataclass(frozen=True)
class ZScore:
    """Z-score 值对象"""
    value: float

    @property
    def is_positive(self) -> bool:
        return self.value > 0

    @property
    def is_negative(self) -> bool:
        return self.value < 0

    @property
    def magnitude(self) -> float:
        return abs(self.value)
