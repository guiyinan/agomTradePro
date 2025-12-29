"""
Domain Entities for Policy Events.
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional


class PolicyLevel(Enum):
    """政策档位"""
    P0 = "P0"  # 常态
    P1 = "P1"  # 预警
    P2 = "P2"  # 干预
    P3 = "P3"  # 危机


@dataclass(frozen=True)
class PolicyEvent:
    """政策事件实体"""
    event_date: date
    level: PolicyLevel
    title: str
    description: str
    evidence_url: str  # 新闻链接或官方公告
