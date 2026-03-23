"""
Share Application DTOs

数据传输对象，用于层间数据传递。
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class ShareLinkDTO:
    """分享链接 DTO"""
    id: int
    owner_id: int
    owner_username: str
    account_id: int
    short_code: str
    title: str
    subtitle: str | None
    share_level: str
    status: str
    has_password: bool
    expires_at: datetime | None
    max_access_count: int | None
    access_count: int
    last_snapshot_at: datetime | None
    last_accessed_at: datetime | None
    allow_indexing: bool
    visibility: dict[str, bool]
    share_url: str
    created_at: datetime
    updated_at: datetime


@dataclass
class CreateShareLinkDTO:
    """创建分享链接请求 DTO"""
    account_id: int
    title: str
    subtitle: str | None = None
    share_level: str = "snapshot"
    password: str | None = None
    expires_at: datetime | None = None
    max_access_count: int | None = None
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
    title: str | None = None
    subtitle: str | None = None
    share_level: str | None = None
    password: str | None = None
    expires_at: datetime | None = None
    max_access_count: int | None = None
    allow_indexing: bool | None = None
    show_amounts: bool | None = None
    show_positions: bool | None = None
    show_transactions: bool | None = None
    show_decision_summary: bool | None = None
    show_decision_evidence: bool | None = None
    show_invalidation_logic: bool | None = None


@dataclass
class ShareSnapshotDTO:
    """分享快照 DTO"""
    id: int
    share_link_id: int
    snapshot_version: int
    summary: dict[str, Any]
    performance: dict[str, Any]
    positions: dict[str, Any]
    transactions: dict[str, Any]
    decisions: dict[str, Any]
    generated_at: datetime
    source_range_start: date | None
    source_range_end: date | None


@dataclass
class ShareAccessDTO:
    """分享访问请求 DTO"""
    short_code: str
    password: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    referer: str | None = None


@dataclass
class ShareAccessResultDTO:
    """分享访问结果 DTO"""
    success: bool
    status: str
    share_link: ShareLinkDTO | None = None
    snapshot: ShareSnapshotDTO | None = None
    requires_password: bool = False
    error_message: str | None = None


@dataclass
class ShareAccessLogDTO:
    """访问日志 DTO"""
    id: int
    share_link_id: int
    share_link_title: str
    accessed_at: datetime
    ip_hash: str
    user_agent: str | None
    referer: str | None
    is_verified: bool
    result_status: str


@dataclass
class ShareStatsDTO:
    """分享统计 DTO"""
    total_shares: int
    active_shares: int
    total_views: int
    total_visitors: int
    most_viewed: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]


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
    sharpe_ratio: float | None
    total_trades: int

    # 绩效数据
    daily_returns: list[dict[str, Any]] = field(default_factory=list)
    monthly_returns: list[dict[str, Any]] = field(default_factory=list)
    drawdown_history: list[dict[str, Any]] = field(default_factory=list)

    # 持仓数据
    positions: list[dict[str, Any]] = field(default_factory=list)

    # 交易数据
    transactions: list[dict[str, Any]] = field(default_factory=list)

    # 决策数据
    decision_summary: dict[str, Any] | None = None
    decision_evidence: list[dict[str, Any]] | None = None
    invalidation_logic: list[dict[str, Any]] | None = None

    # 时间范围
    data_start_date: date | None = None
    data_end_date: date | None = None
