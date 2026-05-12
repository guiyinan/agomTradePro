"""
Domain Entities for Policy Events.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Optional


class PolicyLevel(Enum):
    """政策档位"""

    PENDING = "PX"  # 待分类
    P0 = "P0"  # 常态
    P1 = "P1"  # 预警
    P2 = "P2"  # 干预
    P3 = "P3"  # 危机


class EventType(Enum):
    """事件类型（区分政策与热点情绪）"""

    POLICY = "policy"  # 政策事件
    HOTSPOT = "hotspot"  # 热点事件
    SENTIMENT = "sentiment"  # 情绪事件
    MIXED = "mixed"  # 混合事件
    UNKNOWN = "unknown"  # 未知类型


class GateLevel(Enum):
    """热点情绪闸门等级"""

    L0 = "L0"  # 正常
    L1 = "L1"  # 关注
    L2 = "L2"  # 警戒
    L3 = "L3"  # 严控


class AssetClass(Enum):
    """资产分类"""

    EQUITY = "equity"  # 股票
    BOND = "bond"  # 债券
    COMMODITY = "commodity"  # 商品
    FX = "fx"  # 外汇
    CRYPTO = "crypto"  # 加密货币
    ALL = "all"  # 全资产


class InfoCategory(Enum):
    """信息分类"""

    MACRO = "macro"  # 宏观政策
    SECTOR = "sector"  # 板块政策
    INDIVIDUAL = "individual"  # 个股舆情
    SENTIMENT = "sentiment"  # 市场情绪
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
class RSSHubGlobalConfig:
    """RSSHub 全局配置实体"""

    base_url: str
    access_key: str
    enabled: bool
    default_format: str = "rss"


@dataclass(frozen=True)
class ProxyConfig:
    """代理配置值对象"""

    host: str
    port: int
    username: str | None = None
    password: str | None = None
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
    proxy_config: ProxyConfig | None = None

    timeout_seconds: int = 30
    retry_times: int = 3

    # ========== RSSHub 配置 ==========
    rsshub_enabled: bool = False
    rsshub_route_path: str = ""
    rsshub_use_global_config: bool = True
    rsshub_custom_base_url: str = ""
    rsshub_custom_access_key: str = ""
    rsshub_format: str = ""


@dataclass(frozen=True)
class RSSItem:
    """RSS条目实体"""

    title: str
    link: str  # 用作去重标识
    pub_date: datetime
    description: str | None = None
    guid: str | None = None  # RSS的guid字段（优先用于去重）
    author: str | None = None
    source: str = "rss"  # 数据来源标识


@dataclass(frozen=True)
class PolicyLevelKeywordRule:
    """政策档位关键词规则实体"""

    level: PolicyLevel
    keywords: list[str]
    weight: int
    category: str | None = None


@dataclass(frozen=True)
class StructuredPolicyData:
    """AI提取的结构化政策数据"""

    policy_subject: str | None = None
    policy_object: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None
    conditions: list[str] = field(default_factory=list)
    impact_scope: str | None = None
    affected_sectors: list[str] = field(default_factory=list)
    affected_stocks: list[str] = field(default_factory=list)
    sentiment: str | None = None
    sentiment_score: float | None = None
    keywords: list[str] = field(default_factory=list)
    summary: str | None = None


@dataclass(frozen=True)
class AIClassificationResult:
    """AI分类结果"""

    success: bool
    info_category: InfoCategory | None = None
    audit_status: AuditStatus | None = None
    ai_confidence: float | None = None
    policy_level: Optional["PolicyLevel"] = None  # AI 推荐的政策档位
    structured_data: StructuredPolicyData | None = None
    risk_impact: RiskImpact | None = None
    error_message: str | None = None
    processing_metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================
# 工作台相关实体
# ============================================================


@dataclass(frozen=True)
class HeatSentimentScore:
    """热点情绪评分值对象"""

    heat_score: float  # 0-100，热度评分
    sentiment_score: float  # -1.0 ~ +1.0，情绪评分

    def __post_init__(self):
        """验证评分范围"""
        if not 0 <= self.heat_score <= 100:
            raise ValueError(f"heat_score must be in [0, 100], got {self.heat_score}")
        if not -1.0 <= self.sentiment_score <= 1.0:
            raise ValueError(f"sentiment_score must be in [-1.0, 1.0], got {self.sentiment_score}")


@dataclass(frozen=True)
class SentimentGateThresholds:
    """热点情绪闸门阈值配置"""

    heat_l1_threshold: float = 30.0
    heat_l2_threshold: float = 60.0
    heat_l3_threshold: float = 85.0
    sentiment_l1_threshold: float = -0.3
    sentiment_l2_threshold: float = -0.6
    sentiment_l3_threshold: float = -0.8


@dataclass(frozen=True)
class IngestionConfig:
    """政策摄入配置值对象"""

    auto_approve_enabled: bool = False
    auto_approve_min_level: PolicyLevel = PolicyLevel.P2
    auto_approve_threshold: float = 0.85
    p23_sla_hours: int = 2
    normal_sla_hours: int = 24


@dataclass(frozen=True)
class WorkbenchEvent:
    """工作台事件实体"""

    id: int
    event_date: date
    event_type: EventType
    level: PolicyLevel
    gate_level: GateLevel | None
    title: str
    description: str
    evidence_url: str
    ai_confidence: float | None
    heat_score: float | None
    sentiment_score: float | None
    gate_effective: bool
    asset_class: AssetClass | None
    asset_scope: list[str]
    created_at: datetime
    audit_status: str
    effective_at: datetime | None = None
    effective_by_id: int | None = None
    rollback_reason: str = ""
    review_notes: str = ""


@dataclass(frozen=True)
class WorkbenchSummary:
    """工作台概览"""

    policy_level: PolicyLevel
    policy_level_event: str | None  # 触发政策档位的事件标题
    global_heat_score: float | None
    global_sentiment_score: float | None
    global_gate_level: GateLevel | None
    pending_review_count: int
    sla_exceeded_count: int
    effective_today_count: int
    last_fetch_at: datetime | None = None


@dataclass(frozen=True)
class GateActionRecord:
    """闸门操作记录"""

    event_id: int
    action: str  # approve, reject, rollback, override
    operator_id: int | None
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    reason: str
    rule_version: str
    created_at: datetime
