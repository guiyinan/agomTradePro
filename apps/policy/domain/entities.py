"""
Domain Entities for Policy Events.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Dict, Any


class PolicyLevel(Enum):
    """政策档位"""
    P0 = "P0"  # 常态
    P1 = "P1"  # 预警
    P2 = "P2"  # 干预
    P3 = "P3"  # 危机


class InfoCategory(Enum):
    """信息分类"""
    MACRO = "macro"           # 宏观政策
    SECTOR = "sector"         # 板块政策
    INDIVIDUAL = "individual" # 个股舆情
    SENTIMENT = "sentiment"   # 市场情绪
    OTHER = "other"


class AuditStatus(Enum):
    """审核状态"""
    PENDING_REVIEW = "pending_review"
    AUTO_APPROVED = "auto_approved"
    MANUAL_APPROVED = "manual_approved"
    REJECTED = "rejected"


class RiskImpact(Enum):
    """风险影响"""
    HIGH_RISK = "high_risk"
    MEDIUM_RISK = "medium_risk"
    LOW_RISK = "low_risk"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PolicyEvent:
    """政策事件实体"""
    event_date: date
    level: PolicyLevel
    title: str
    description: str
    evidence_url: str  # 新闻链接或官方公告


@dataclass(frozen=True)
class ProxyConfig:
    """代理配置值对象"""
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    proxy_type: str = "http"  # http/https/socks5


@dataclass(frozen=True)
class RSSSourceConfig:
    """RSS源配置实体（Domain层，纯数据结构）"""
    name: str
    url: str
    category: str  # 政府文件/央行公告/财政部/证监会等
    is_active: bool
    fetch_interval_hours: int  # 抓取间隔（小时）
    extract_content: bool  # 是否提取完整内容
    proxy_config: Optional[ProxyConfig] = None


@dataclass(frozen=True)
class RSSItem:
    """RSS条目实体"""
    title: str
    link: str  # 用作去重标识
    pub_date: datetime
    description: Optional[str] = None
    guid: Optional[str] = None  # RSS的guid字段（优先用于去重）
    author: Optional[str] = None
    source: str = "rss"  # 数据来源标识


@dataclass(frozen=True)
class PolicyLevelKeywordRule:
    """政策档位关键词规则实体"""
    level: PolicyLevel
    keywords: List[str]
    weight: int
    category: Optional[str] = None


@dataclass(frozen=True)
class StructuredPolicyData:
    """AI提取的结构化政策数据"""
    policy_subject: Optional[str] = None
    policy_object: Optional[str] = None
    effective_date: Optional[str] = None
    expiry_date: Optional[str] = None
    conditions: List[str] = field(default_factory=list)
    impact_scope: Optional[str] = None
    affected_sectors: List[str] = field(default_factory=list)
    affected_stocks: List[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    sentiment_score: Optional[float] = None
    keywords: List[str] = field(default_factory=list)
    summary: Optional[str] = None


@dataclass(frozen=True)
class AIClassificationResult:
    """AI分类结果"""
    success: bool
    info_category: Optional[InfoCategory] = None
    audit_status: Optional[AuditStatus] = None
    ai_confidence: Optional[float] = None
    structured_data: Optional[StructuredPolicyData] = None
    risk_impact: Optional[RiskImpact] = None
    error_message: Optional[str] = None
    processing_metadata: Dict[str, Any] = field(default_factory=dict)
