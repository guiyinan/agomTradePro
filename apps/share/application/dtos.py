"""
Share Application DTOs

数据传输对象，用于层间数据传递。
"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, Any, List
from decimal import Decimal


@dataclass
class ShareLinkDTO:
    """分享链接 DTO"""
    id: int
    owner_id: int
    owner_username: str
    account_id: int
    short_code: str
    title: str
    subtitle: Optional[str]
    share_level: str
    status: str
    has_password: bool
    expires_at: Optional[datetime]
    max_access_count: Optional[int]
    access_count: int
    last_snapshot_at: Optional[datetime]
    last_accessed_at: Optional[datetime]
    allow_indexing: bool
    visibility: Dict[str, bool]
    share_url: str
    created_at: datetime
    updated_at: datetime


@dataclass
class CreateShareLinkDTO:
    """创建分享链接请求 DTO"""
    account_id: int
    title: str
    subtitle: Optional[str] = None
    share_level: str = "snapshot"
    password: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_access_count: Optional[int] = None
    allow_indexing: bool = False
    show_amounts: bool = True
    show_positions: bool = True
    show_transactions: bool = True
    show_decision_summary: bool = True
    show_decision_evidence: bool = False
    show_invalidation_logic: bool = False


@dataclass
class UpdateShareLinkDTO:
    """更新分享链接请求 DTO"""
    title: Optional[str] = None
    subtitle: Optional[str] = None
    share_level: Optional[str] = None
    password: Optional[str] = None
    expires_at: Optional[datetime] = None
    max_access_count: Optional[int] = None
    allow_indexing: Optional[bool] = None
    show_amounts: Optional[bool] = None
    show_positions: Optional[bool] = None
    show_transactions: Optional[bool] = None
    show_decision_summary: Optional[bool] = None
    show_decision_evidence: Optional[bool] = None
    show_invalidation_logic: Optional[bool] = None


@dataclass
class ShareSnapshotDTO:
    """分享快照 DTO"""
    id: int
    share_link_id: int
    snapshot_version: int
    summary: Dict[str, Any]
    performance: Dict[str, Any]
    positions: Dict[str, Any]
    transactions: Dict[str, Any]
    decisions: Dict[str, Any]
    generated_at: datetime
    source_range_start: Optional[date]
    source_range_end: Optional[date]


@dataclass
class ShareAccessDTO:
    """分享访问请求 DTO"""
    short_code: str
    password: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    referer: Optional[str] = None


@dataclass
class ShareAccessResultDTO:
    """分享访问结果 DTO"""
    success: bool
    status: str
    share_link: Optional[ShareLinkDTO] = None
    snapshot: Optional[ShareSnapshotDTO] = None
    requires_password: bool = False
    error_message: Optional[str] = None


@dataclass
class ShareAccessLogDTO:
    """访问日志 DTO"""
    id: int
    share_link_id: int
    share_link_title: str
    accessed_at: datetime
    ip_hash: str
    user_agent: Optional[str]
    referer: Optional[str]
    is_verified: bool
    result_status: str


@dataclass
class ShareStatsDTO:
    """分享统计 DTO"""
    total_shares: int
    active_shares: int
    total_views: int
    total_visitors: int
    most_viewed: List[Dict[str, Any]]
    recent_activity: List[Dict[str, Any]]


@dataclass
class SnapshotPayloadDTO:
    """快照数据 DTO"""
    # 摘要数据
    account_name: str
    account_type: str
    start_date: date
    current_value: Decimal
    initial_capital: Decimal
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    total_trades: int

    # 绩效数据
    daily_returns: List[Dict[str, Any]] = field(default_factory=list)
    monthly_returns: List[Dict[str, Any]] = field(default_factory=list)
    drawdown_history: List[Dict[str, Any]] = field(default_factory=list)

    # 持仓数据
    positions: List[Dict[str, Any]] = field(default_factory=list)

    # 交易数据
    transactions: List[Dict[str, Any]] = field(default_factory=list)

    # 决策数据
    decision_summary: Optional[Dict[str, Any]] = None
    decision_evidence: Optional[List[Dict[str, Any]]] = None
    invalidation_logic: Optional[List[Dict[str, Any]]] = None

    # 时间范围
    data_start_date: Optional[date] = None
    data_end_date: Optional[date] = None
