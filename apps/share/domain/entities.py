"""
Share Domain Entities

分享实体定义、披露级别枚举、状态枚举。

遵循DDD原则：
- 使用dataclass定义值对象和实体
- Domain层纯净：只使用Python标准库
- 所有分享相关业务逻辑在此层定义
"""
from dataclasses import dataclass
from datetime import datetime, date
from enum import Enum
from typing import Optional, Dict, Any


class ShareLevel(Enum):
    """
    分享级别/披露级别

    SNAPSHOT - 静态快照: 适合公开传播，展示固定时间点的账户状态
    OBSERVER - 观察者模式: 适合熟人围观，可看到实时更新（有频率限制）
    RESEARCH - 研究模式: 适合研究用途，包含决策依据和证伪逻辑
    """
    SNAPSHOT = "snapshot"    # 静态快照
    OBSERVER = "observer"    # 观察者模式
    RESEARCH = "research"    # 研究模式


class ShareStatus(Enum):
    """
    分享状态

    ACTIVE - 活跃: 链接有效且可访问
    REVOKED - 已撤销: 用户主动取消分享
    EXPIRED - 已过期: 超过有效期或访问次数限制
    DISABLED - 已禁用: 管理员禁用或系统自动禁用
    """
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    DISABLED = "disabled"


class AccessResultStatus(Enum):
    """
    访问结果状态

    SUCCESS - 访问成功
    PASSWORD_REQUIRED - 需要密码
    PASSWORD_INVALID - 密码错误
    EXPIRED - 链接已过期
    REVOKED - 链接已撤销
    MAX_COUNT_EXCEEDED - 超过最大访问次数
    NOT_FOUND - 链接不存在
    """
    SUCCESS = "success"
    PASSWORD_REQUIRED = "password_required"
    PASSWORD_INVALID = "password_invalid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    MAX_COUNT_EXCEEDED = "max_count_exceeded"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class ShareLinkEntity:
    """
    分享链接实体

    表示一个可公开访问的账户分享链接。
    """
    id: Optional[int]
    owner_id: int
    account_id: int
    short_code: str
    title: str
    subtitle: Optional[str]
    share_level: ShareLevel
    status: ShareStatus
    password_hash: Optional[str]
    expires_at: Optional[datetime]
    max_access_count: Optional[int]
    access_count: int
    last_snapshot_at: Optional[datetime]
    last_accessed_at: Optional[datetime]
    allow_indexing: bool
    show_amounts: bool
    show_positions: bool
    show_transactions: bool
    show_decision_summary: bool
    show_decision_evidence: bool
    show_invalidation_logic: bool
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    def is_accessible(self, now: datetime) -> tuple[bool, AccessResultStatus]:
        """
        检查链接是否可访问

        Returns:
            (is_accessible, status)
        """
        if self.status != ShareStatus.ACTIVE:
            if self.status == ShareStatus.REVOKED:
                return False, AccessResultStatus.REVOKED
            if self.status == ShareStatus.EXPIRED:
                return False, AccessResultStatus.EXPIRED
            return False, AccessResultStatus.NOT_FOUND

        if self.expires_at and now > self.expires_at:
            return False, AccessResultStatus.EXPIRED

        if self.max_access_count and self.access_count >= self.max_access_count:
            return False, AccessResultStatus.MAX_COUNT_EXCEEDED

        return True, AccessResultStatus.SUCCESS

    def requires_password(self) -> bool:
        """是否需要密码验证"""
        return self.password_hash is not None and self.password_hash != ""

    def get_visibility_config(self) -> Dict[str, bool]:
        """获取可见性配置"""
        return {
            "amounts": self.show_amounts,
            "positions": self.show_positions,
            "transactions": self.show_transactions,
            "decision_summary": self.show_decision_summary,
            "decision_evidence": self.show_decision_evidence,
            "invalidation_logic": self.show_invalidation_logic,
        }


@dataclass(frozen=True)
class ShareSnapshotEntity:
    """
    分享快照实体

    存储分享链接在某个时间点的完整状态快照。
    """
    id: Optional[int]
    share_link_id: int
    snapshot_version: int
    summary_payload: Dict[str, Any]
    performance_payload: Dict[str, Any]
    positions_payload: Dict[str, Any]
    transactions_payload: Dict[str, Any]
    decision_payload: Dict[str, Any]
    generated_at: datetime
    source_range_start: Optional[date]
    source_range_end: Optional[date]

    def is_empty(self) -> bool:
        """检查快照是否为空"""
        return (
            not self.summary_payload
            and not self.performance_payload
            and not self.positions_payload
            and not self.transactions_payload
            and not self.decision_payload
        )


@dataclass(frozen=True)
class ShareAccessLogEntity:
    """
    分享访问日志实体

    记录每次访问分享链接的行为。
    """
    id: Optional[int]
    share_link_id: int
    accessed_at: datetime
    ip_hash: str
    user_agent: Optional[str]
    referer: Optional[str]
    is_verified: bool
    result_status: AccessResultStatus

    def is_successful_access(self) -> bool:
        """是否是成功的访问"""
        return self.result_status == AccessResultStatus.SUCCESS


@dataclass(frozen=True)
class ShareConfig:
    """
    分享配置值对象

    定义创建分享时的配置选项。
    """
    title: str
    subtitle: Optional[str] = None
    share_level: ShareLevel = ShareLevel.SNAPSHOT
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

    def get_visibility_flags(self) -> Dict[str, bool]:
        """获取可见性标志"""
        return {
            "show_amounts": self.show_amounts,
            "show_positions": self.show_positions,
            "show_transactions": self.show_transactions,
            "show_decision_summary": self.show_decision_summary,
            "show_decision_evidence": self.show_decision_evidence,
            "show_invalidation_logic": self.show_invalidation_logic,
        }

    def requires_password(self) -> bool:
        """是否需要密码"""
        return self.password is not None and self.password != ""
