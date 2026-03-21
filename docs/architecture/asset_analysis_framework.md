# 通用资产分析框架设计与实施

> 最后更新：2026-01-04
> 版本：v3.3（日志与告警版）

## 一、概述

### 1.1 背景

本框架旨在将基金分析的多维度评分体系抽象为**通用资产分析框架**，支持股票、基金、债券、商品等多种资产类别的统一评分和推荐机制。

### 1.2 核心目标

1. **建立多维度资产评分体系**
   - Regime（宏观环境）维度
   - Policy（政策档位）维度
   - Sentiment（舆情情绪）维度
   - Signal（投资信号）维度

2. **实现代码复用**
   - 遵循 DRY 原则，避免 Fund/Equity 模块重复代码
   - 减少 70%+ 重复逻辑

3. **提供动态推荐策略**
   - 基于实时市场环境调整资产评分
   - 支持回测验证各维度权重

4. **AI 赋能的情感分析**
   - 使用系统 AI API 分析舆情情感
   - 自动计算市场情绪指数

### 1.3 业务价值

- **提高决策质量**：多维度交叉验证，减少单一指标的误判
- **适应市场变化**：Policy 档位和舆情反映市场的即时变化
- **风险控制**：Signal 准入机制提供风险预警
- **用户体验**：统一的评分标准，便于跨资产类别比较

---

## 二、核心理念：DRY 原则

### 2.1 现状问题

- **Fund 和 Equity 模块各自独立实现相似逻辑**
  - RegimeMatcher 在两个模块中重复
  - PolicyMatcher 在两个模块中重复
  - 权重配置重复管理
- **代码重复，维护成本高**
- **不利于统一策略回测**

### 2.2 解决方案

- **将通用逻辑抽象到 `apps/asset_analysis`（独立业务 App）**
- **Fund 和 Equity 继承并扩展特有逻辑**
- **统一的评分标准和权重配置**（从数据库读取）

### 2.3 为什么是独立 App 而非 shared 模块？

**架构原则：**
- `apps/` - 独立的业务能力模块（完整四层架构）
- `shared/` - 技术性的通用组件（Protocol、工具类）

**asset_analysis 是业务模块的理由：**
1. ✅ 提供独立的业务能力：资产评分与推荐
2. ✅ 拥有完整的四层架构（Domain/Application/Infrastructure/Interface）
3. ✅ 包含业务实体（AssetScore）和业务规则（RegimeMatcher）
4. ✅ 拥有独立的数据模型（WeightConfigModel）
5. ✅ 提供 API 接口供前端调用

**shared/ 应该只包含：**
- Protocol 接口定义（如 `RepositoryProtocol`）
- 纯技术性的算法（如 `KalmanFilter`）
- 配置管理（如 `secrets.py`）

**依赖关系：**
```
apps/fund → depends on → apps/asset_analysis
apps/equity → depends on → apps/asset_analysis

apps/asset_analysis → depends on → shared/domain/interfaces.py (仅 Protocol)
```

---

## 三、架构设计

### 3.1 模块结构

```
apps/asset_analysis/                   # 通用资产分析模块（独立业务 App）
├── domain/                            # Domain 层
│   ├── entities.py                    # AssetScore, AssetType, AssetStyle 等实体
│   ├── value_objects.py               # WeightConfig, ScoreContext 值对象
│   ├── services.py                    # 通用匹配器（RegimeMatcher等）
│   └── interfaces.py                  # 业务接口定义
│
├── infrastructure/                    # Infrastructure 层
│   ├── models.py                      # WeightConfigModel ORM 模型
│   └── repositories.py                # WeightConfigRepository 数据仓储
│
├── application/                       # Application 层
│   ├── use_cases.py                   # MultiDimScreenUseCase 用例
│   ├── services.py                    # AssetMultiDimScorer 评分器
│   └── dtos.py                        # ScreenRequest, ScreenResponse DTO
│
└── interface/                         # Interface 层
    ├── serializers.py                 # DRF 序列化器
    └── views.py                       # 通用 API 视图
```

### 3.2 资产类型扩展

```python
# apps/asset_analysis/domain/entities.py

from enum import Enum
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Optional

class AssetType(Enum):
    """资产类型"""
    EQUITY = "equity"          # 股票
    FUND = "fund"              # 基金
    BOND = "bond"              # 债券
    COMMODITY = "commodity"    # 商品
    INDEX = "index"            # 指数
    SECTOR = "sector"          # 行业

class AssetStyle(Enum):
    """资产风格"""
    GROWTH = "growth"          # 成长
    VALUE = "value"            # 价值
    BLEND = "blend"            # 混合
    QUALITY = "quality"        # 质量
    DEFENSIVE = "defensive"    # 防御

class AssetSize(Enum):
    """资产规模"""
    LARGE_CAP = "large"        # 大盘
    MID_CAP = "mid"            # 中盘
    SMALL_CAP = "small"        # 小盘

@dataclass(frozen=True)
class AssetScore:
    """通用资产评分实体"""
    # 资产标识
    asset_type: AssetType
    asset_code: str
    asset_name: str

    # 风格属性
    style: Optional[AssetStyle] = None
    size: Optional[AssetSize] = None
    sector: Optional[str] = None  # 行业

    # 各维度得分（0-100）
    regime_score: float = 0.0
    policy_score: float = 0.0
    sentiment_score: float = 0.0
    signal_score: float = 0.0

    # 特有维度（可扩展）
    # 基金可用：manager_score, fund_flow_score
    # 股票可用：technical_score, fundamental_score
    custom_scores: Dict[str, float] = field(default_factory=dict)

    # 综合得分
    total_score: float = 0.0
    rank: int = 0

    # 推荐信息
    allocation_percent: float = 0.0
    risk_level: str = "未知"

    # 元信息
    score_date: date = field(default_factory=date.today)
    context: Optional[Dict] = None

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "asset_type": self.asset_type.value,
            "asset_code": self.asset_code,
            "asset_name": self.asset_name,
            "style": self.style.value if self.style else None,
            "size": self.size.value if self.size else None,
            "sector": self.sector,
            "scores": {
                "regime": self.regime_score,
                "policy": self.policy_score,
                "sentiment": self.sentiment_score,
                "signal": self.signal_score,
                "custom": self.custom_scores,
            },
            "total_score": self.total_score,
            "rank": self.rank,
            "allocation": f"{self.allocation_percent}%",
            "risk_level": self.risk_level,
        }
```

---

## 四、通用匹配器

### 4.1 Regime 匹配器

```python
# apps/asset_analysis/domain/services.py

class RegimeMatcher:
    """Regime 匹配器（通用）"""

    # Regime × 风格 矩阵
    REGIME_STYLE_MATRIX = {
        ("Recovery", "growth"): 90,
        ("Recovery", "value"): 75,
        ("Recovery", "blend"): 80,
        ("Overheat", "value"): 85,
        ("Overheat", "growth"): 70,
        ("Overheat", "blend"): 75,
        ("Stagflation", "defensive"): 90,
        ("Stagflation", "quality"): 85,
        ("Stagflation", "growth"): 40,
        ("Deflation", "defensive"): 85,
        ("Deflation", "value"): 80,
        ("Deflation", "growth"): 50,
    }

    # Regime × 资产类型 矩阵
    REGIME_ASSET_TYPE_MATRIX = {
        ("Recovery", "equity"): 90,
        ("Recovery", "fund"): 85,
        ("Recovery", "bond"): 50,
        ("Overheat", "equity"): 70,
        ("Overheat", "fund"): 75,
        ("Overheat", "bond"): 80,
        ("Stagflation", "equity"): 30,
        ("Stagflation", "fund"): 40,
        ("Stagflation", "bond"): 90,
        ("Deflation", "equity"): 40,
        ("Deflation", "fund"): 50,
        ("Deflation", "bond"): 85,
    }

    @classmethod
    def match(cls, asset: AssetScore, current_regime: str) -> float:
        """计算 Regime 匹配得分"""
        score = 0.0

        # 1. 资产类型匹配（权重 60%）
        type_score = cls.REGIME_ASSET_TYPE_MATRIX.get(
            (current_regime, asset.asset_type.value),
            50
        )
        score += type_score * 0.6

        # 2. 风格匹配（权重 40%）
        if asset.style:
            style_score = cls.REGIME_STYLE_MATRIX.get(
                (current_regime, asset.style.value),
                60
            )
            score += style_score * 0.4

        # 3. 行业调整（权重 10%，可选）
        if asset.sector:
            sector_score = cls._get_sector_regime_score(asset.sector, current_regime)
            score += sector_score * 0.1

        return min(100, score)

    @staticmethod
    def _get_sector_regime_score(sector: str, regime: str) -> float:
        """行业 Regime 匹配得分"""
        SECTOR_REGIME_SCORE = {
            ("金融", "Recovery"): 85,
            ("科技", "Recovery"): 95,
            ("消费", "Recovery"): 80,
            ("医药", "Stagflation"): 85,
            ("公用事业", "Deflation"): 90,
            # ... 更多配置
        }
        return SECTOR_REGIME_SCORE.get((sector, regime), 70)
```

### 4.2 Policy 匹配器

```python
class PolicyMatcher:
    """Policy 档位匹配器（通用）"""

    # Policy × 资产类型 矩阵
    POLICY_ASSET_TYPE_MATRIX = {
        ("P0", "equity"): 90,
        ("P0", "fund"): 90,
        ("P0", "bond"): 70,
        ("P1", "equity"): 70,
        ("P1", "fund"): 75,
        ("P1", "bond"): 85,
        ("P2", "equity"): 30,
        ("P2", "fund"): 40,
        ("P2", "bond"): 95,
        ("P3", "equity"): 10,
        ("P3", "fund"): 20,
        ("P3", "bond"): 80,
    }

    @classmethod
    def match(cls, asset: AssetScore, policy_level: str) -> float:
        """计算 Policy 匹配得分"""
        base_score = cls.POLICY_ASSET_TYPE_MATRIX.get(
            (policy_level, asset.asset_type.value),
            50
        )

        # 根据风险等级调整
        risk_adjustment = {
            "P0": 1.0,
            "P1": 0.9,
            "P2": 0.7,
            "P3": 0.5,
        }.get(policy_level, 1.0)

        return base_score * risk_adjustment
```

### 4.3 Sentiment 匹配器

```python
class SentimentMatcher:
    """舆情情绪匹配器（通用）"""

    @classmethod
    def match(cls, asset: AssetScore, sentiment_index: float) -> float:
        """
        计算情绪匹配得分

        sentiment_index: -3.0 ~ +3.0
        """
        # 股票/基金在情绪高涨时受益
        if asset.asset_type in [AssetType.EQUITY, AssetType.FUND]:
            # 情绪指数 +1 ~ +3 时得分高
            if sentiment_index > 1:
                return 60 + (sentiment_index - 1) * 15
            # 情绪指数 -1 ~ +1 时中等
            elif sentiment_index > -1:
                return 50 + sentiment_index * 10
            # 情绪指数低时得分低
            else:
                return 40 + (sentiment_index + 3) * 10

        # 债券在情绪低落时受益（避险）
        elif asset.asset_type == AssetType.BOND:
            if sentiment_index < -1:
                return 60 + (-sentiment_index - 1) * 15
            else:
                return 50 - sentiment_index * 10

        return 50
```

### 4.4 Signal 匹配器

```python
from typing import List

class SignalMatcher:
    """投资信号匹配器（通用）"""

    @classmethod
    def match(cls, asset: AssetScore, active_signals: List) -> float:
        """计算信号匹配得分"""
        if not active_signals:
            return 50  # 无信号时中性

        match_count = 0
        for signal in active_signals:
            # 检查信号资产是否匹配
            if cls._is_signal_match_asset(signal, asset):
                match_count += 1

        # 根据匹配信号数量评分
        if match_count >= 3:
            return 90
        elif match_count >= 2:
            return 75
        elif match_count >= 1:
            return 60
        else:
            return 40

    @staticmethod
    def _is_signal_match_asset(signal, asset: AssetScore) -> bool:
        """判断信号是否匹配资产"""
        # 精确匹配
        if signal.asset_code == asset.asset_code:
            return True

        # 资产类别匹配
        if hasattr(signal, 'asset_class') and signal.asset_class == asset.asset_type.value:
            return True

        # 行业匹配
        if asset.sector and hasattr(signal, 'sector') and signal.sector == asset.sector:
            return True

        return False
```

---

## 五、通用评分器

```python
# apps/asset_analysis/application/services.py

class AssetMultiDimScorer:
    """通用资产多维度评分器"""

    def __init__(self, weight_repository):
        self.weight_repo = weight_repository

    def score(self, asset: AssetScore, context: ScoreContext) -> AssetScore:
        """计算综合得分"""
        # 1. 获取权重配置（从数据库）
        weights = self.weight_repo.get_active_weights(
            asset_type=asset.asset_type.value
        )

        # 2. 各维度得分
        regime_score = RegimeMatcher.match(asset, context.current_regime)
        policy_score = PolicyMatcher.match(asset, context.policy_level)
        sentiment_score = SentimentMatcher.match(asset, context.sentiment_index)
        signal_score = SignalMatcher.match(asset, context.active_signals)

        # 3. 加权计算
        total_score = (
            regime_score * weights.regime_weight +
            policy_score * weights.policy_weight +
            sentiment_score * weights.sentiment_weight +
            signal_score * weights.signal_weight
        )

        # 4. 返回更新后的资产对象
        return AssetScore(
            **{**asset.__dict__, **{
                'regime_score': regime_score,
                'policy_score': policy_score,
                'sentiment_score': sentiment_score,
                'signal_score': signal_score,
                'total_score': total_score,
            }}
        )

    def score_batch(
        self,
        assets: List[AssetScore],
        context: ScoreContext
    ) -> List[AssetScore]:
        """批量评分"""
        scored_assets = [self.score(asset, context) for asset in assets]

        # 排序并设置排名
        scored_assets.sort(key=lambda x: x.total_score, reverse=True)
        for rank, asset in enumerate(scored_assets, start=1):
            asset.__dict__['rank'] = rank

        return scored_assets
```

---

## 六、数据模型设计

### 6.1 值对象

```python
# apps/asset_analysis/domain/value_objects.py

@dataclass(frozen=True)
class WeightConfig:
    """权重配置（值对象）"""
    regime_weight: float = 0.40
    policy_weight: float = 0.25
    sentiment_weight: float = 0.20
    signal_weight: float = 0.15

    def __post_init__(self):
        # 验证权重总和为1.0
        total = (self.regime_weight + self.policy_weight +
                 self.sentiment_weight + self.signal_weight)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"权重总和必须为1.0，当前为{total}")

@dataclass(frozen=True)
class ScoreContext:
    """评分上下文（值对象）"""
    current_regime: str
    policy_level: str
    sentiment_index: float
    active_signals: List
    score_date: date = field(default_factory=date.today)
```

### 6.2 基金扩展

```python
# apps/fund/domain/entities.py

from apps.asset_analysis.domain.entities import AssetScore, AssetType

@dataclass(frozen=True)
class FundScore(AssetScore):
    """基金评分（继承自通用评分）"""

    asset_type: AssetType = AssetType.FUND

    # 基金特有属性
    fund_company: Optional[str] = None
    fund_manager: Optional[str] = None
    establishment_date: Optional[date] = None

    # 基金特有维度得分
    manager_score: float = 0.0
    fund_flow_score: float = 0.0
    fund_size_score: float = 0.0

    def __post_init__(self):
        # 基金特有得分计入 custom_scores
        if self.custom_scores is None:
            object.__setattr__(self, 'custom_scores', {})
        self.custom_scores['manager'] = self.manager_score
        self.custom_scores['flow'] = self.fund_flow_score
        self.custom_scores['size'] = self.fund_size_score
```

### 6.3 股票扩展

```python
# apps/equity/domain/entities.py

@dataclass(frozen=True)
class EquityScore(AssetScore):
    """股票评分（继承自通用评分）"""

    asset_type: AssetType = AssetType.EQUITY

    # 股票特有属性
    market: Optional[str] = None          # SH/SZ
    industry: Optional[str] = None        # 行业（二级分类）
    market_cap: Optional[float] = None    # 市值（亿）

    # 股票特有维度得分
    technical_score: float = 0.0          # 技术面得分
    fundamental_score: float = 0.0        # 基本面得分

    def __post_init__(self):
        if self.custom_scores is None:
            object.__setattr__(self, 'custom_scores', {})
        self.custom_scores['technical'] = self.technical_score
        self.custom_scores['fundamental'] = self.fundamental_score
```

---

## 七、数据库 Schema

### 7.1 权重配置表

```sql
-- 多维度评分权重配置表
CREATE TABLE asset_weight_config (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) UNIQUE NOT NULL,
    description TEXT,

    -- 四大维度权重
    regime_weight FLOAT DEFAULT 0.40,
    policy_weight FLOAT DEFAULT 0.25,
    sentiment_weight FLOAT DEFAULT 0.20,
    signal_weight FLOAT DEFAULT 0.15,

    -- 适用条件（可选）
    asset_type VARCHAR(20),           -- 资产类型（为空表示通用）
    market_condition VARCHAR(20),     -- 市场状态（为空表示通用）

    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0,       -- 优先级（数字越大优先级越高）

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- 约束：权重总和必须为1.0
    CONSTRAINT weight_sum_check CHECK (
        ABS((regime_weight + policy_weight + sentiment_weight + signal_weight) - 1.0) < 0.01
    )
);

-- 创建索引
CREATE INDEX idx_weight_config_active ON asset_weight_config(is_active, priority DESC);
```

### 7.2 情绪指数表

```sql
-- 舆情情绪指数表
CREATE TABLE sentiment_index (
    id SERIAL PRIMARY KEY,
    index_date DATE UNIQUE NOT NULL,

    -- 情绪指数（-3.0 ~ +3.0）
    news_sentiment FLOAT DEFAULT 0.0,
    policy_sentiment FLOAT DEFAULT 0.0,
    composite_index FLOAT DEFAULT 0.0,

    -- 置信度
    confidence_level FLOAT DEFAULT 0.0,

    -- 分类情绪（JSON）
    sector_sentiment JSON,

    -- 数据来源统计
    news_count INTEGER DEFAULT 0,
    policy_events_count INTEGER DEFAULT 0,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sentiment_date ON sentiment_index(index_date DESC);
```

### 7.3 基金多维度评分表

```sql
-- 基金多维度评分表
CREATE TABLE fund_multidim_score (
    id SERIAL PRIMARY KEY,
    fund_code VARCHAR(10) NOT NULL,
    score_date DATE NOT NULL,

    -- 维度得分
    regime_score FLOAT DEFAULT 0,
    policy_score FLOAT DEFAULT 0,
    sentiment_score FLOAT DEFAULT 0,
    signal_score FLOAT DEFAULT 0,

    -- 综合得分
    total_score FLOAT DEFAULT 0,
    rank INTEGER,

    -- 上下文
    regime VARCHAR(20),
    policy_level VARCHAR(2),
    sentiment_index FLOAT,
    active_signals_count INTEGER DEFAULT 0,

    -- 推荐
    allocation_percent FLOAT DEFAULT 0,
    risk_level VARCHAR(20),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(fund_code, score_date)
);

CREATE INDEX idx_fund_score_date ON fund_multidim_score(score_date DESC, total_score DESC);
```

---

## 八、API 接口设计

### 8.1 多维度筛选 API

```python
# POST /api/asset-analysis/multidim-screen/

request:
{
    "asset_type": "fund",           # 或 "equity", "bond"
    "filters": {
        "fund_type": "股票型",
        "investment_style": "成长",
        "min_scale": 1000000000     # 10亿元
    },
    "weights": {                    # 可选，不填则从数据库读取
        "regime": 0.40,
        "policy": 0.25,
        "sentiment": 0.20,
        "signal": 0.15
    },
    "max_count": 30
}

response:
{
    "success": true,
    "timestamp": "2026-01-03T12:00:00Z",
    "context": {
        "regime": "Recovery",
        "policy_level": "P0",
        "sentiment_index": 0.5,
        "active_signals_count": 3
    },
    "weights": {
        "regime": 0.40,
        "policy": 0.25,
        "sentiment": 0.20,
        "signal": 0.15
    },
    "assets": [
        {
            "asset_code": "000001",
            "asset_name": "华夏成长",
            "asset_type": "fund",
            "scores": {
                "regime": 85,
                "policy": 78,
                "sentiment": 72,
                "signal": 60,
                "total": 76.5
            },
            "allocation": "15%",
            "risk_level": "中风险"
        },
        ...
    ]
}
```

### 8.2 权重配置 API

```python
# GET /api/asset-analysis/weight-configs/

response:
{
    "success": true,
    "configs": {
        "default": {
            "regime": 0.40,
            "policy": 0.25,
            "sentiment": 0.20,
            "signal": 0.15
        },
        "policy_crisis": {
            "regime": 0.20,
            "policy": 0.50,
            "sentiment": 0.20,
            "signal": 0.10
        }
    },
    "active": "default"
}
```

### 8.3 情绪指数 API

```python
# GET /api/sentiment/?date=2026-01-03

response:
{
    "success": true,
    "date": "2026-01-03",
    "index": {
        "composite": 0.5,
        "news": 0.3,
        "policy": 0.7
    },
    "level": "中性偏乐观",
    "confidence": 0.75,
    "sector_sentiment": {
        "金融": 0.6,
        "科技": 0.9,
        "消费": 0.2
    }
}
```

---

## 九、情感分析实现（AI API 方案）

### 9.1 技术方案选择

**使用系统 AI API**（`apps/ai_provider` 模块）

**优势：**
- ✅ 统一的 AI 提供商管理
- ✅ 支持多种 AI 模型（OpenAI、DeepSeek、Qwen、Moonshot）
- ✅ 预算管理和成本控制
- ✅ 调用日志和监控

### 9.2 情感分析服务

```python
# apps/sentiment/application/services.py

class SentimentAnalyzer:
    """情感分析服务（调用 AI API）"""

    def __init__(self, ai_provider_service):
        self.ai_service = ai_provider_service

    def analyze_text(self, text: str) -> SentimentAnalysisResult:
        """
        分析文本情感

        使用系统 AI API（apps/ai_provider）
        """
        # 1. 构建 Prompt
        prompt = self._build_sentiment_prompt(text)

        # 2. 调用 AI API
        from apps.ai_provider.domain.entities import AIChatRequest

        request = AIChatRequest(
            messages=[
                {"role": "system", "content": "你是一个金融舆情情感分析专家。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # 降低随机性，提高一致性
            max_tokens=500
        )

        response = self.ai_service.chat(request)

        # 3. 解析结果
        sentiment_score = self._parse_sentiment_score(response.content)

        return SentimentAnalysisResult(
            text=text,
            sentiment_score=sentiment_score,
            confidence=0.8,
            category=self._categorize_sentiment(sentiment_score),
            keywords=[],
            analyzed_at=datetime.now()
        )

    def _build_sentiment_prompt(self, text: str) -> str:
        """构建情感分析 Prompt"""
        return f"""
请分析以下金融新闻/政策的情感倾向，并给出 -3.0 到 +3.0 的评分：

评分标准：
- -3.0: 极度负面（如熔断、危机、暴跌、崩盘）
- -1.5: 负面（如下跌、利空、收紧、加息）
- 0.0: 中性（如持平、观望、维持）
- +1.5: 正面（如上涨、利好、放松、降息）
- +3.0: 极度正面（如大涨、降准、重大利好）

文本内容：
{text}

请只返回一个数字评分（-3.0 到 +3.0），不要返回其他内容。
"""

    def _parse_sentiment_score(self, ai_response: str) -> float:
        """解析 AI 返回的情感评分"""
        import re
        match = re.search(r'-?\d+\.?\d*', ai_response)
        if match:
            score = float(match.group())
            return max(-3.0, min(3.0, score))
        return 0.0

    def _categorize_sentiment(self, score: float) -> str:
        """将评分转换为类别"""
        if score >= 1.5:
            return "POSITIVE"
        elif score <= -1.5:
            return "NEGATIVE"
        else:
            return "NEUTRAL"
```

### 9.3 每日情绪指数计算

```python
# apps/sentiment/application/tasks.py

from celery import shared_task
from datetime import date

@shared_task
def calculate_daily_sentiment_index():
    """
    每日计算综合情绪指数

    定时任务：每天晚上23:00执行
    """
    from apps.policy.infrastructure.repositories import DjangoPolicyRepository
    from apps.sentiment.infrastructure.repositories import SentimentIndexRepository
    from apps.sentiment.application.services import SentimentAnalyzer
    from apps.ai_provider.domain.services import AIProviderService

    # 1. 获取当日政策事件
    policy_repo = DjangoPolicyRepository()
    today = date.today()
    policy_events = policy_repo.get_events_in_range(today, today)

    # 2. 分析政策情感
    ai_service = AIProviderService()
    analyzer = SentimentAnalyzer(ai_service)

    policy_scores = []
    for event in policy_events:
        text = f"{event.title} {event.description}"
        result = analyzer.analyze_text(text)
        policy_scores.append(result.sentiment_score)

    policy_sentiment = sum(policy_scores) / len(policy_scores) if policy_scores else 0.0

    # 3. TODO: 获取当日新闻并分析（未来扩展）
    news_sentiment = 0.0

    # 4. 计算综合指数
    composite_index = policy_sentiment * 0.6 + news_sentiment * 0.4

    # 5. 保存到数据库
    sentiment_repo = SentimentIndexRepository()
    sentiment_index = SentimentIndex(
        index_date=today,
        news_sentiment=news_sentiment,
        policy_sentiment=policy_sentiment,
        composite_index=composite_index,
        confidence_level=0.75,
        sector_sentiment={},
        news_count=0,
        policy_events_count=len(policy_events)
    )
    sentiment_repo.save(sentiment_index)

    return {
        "date": str(today),
        "composite_index": composite_index,
        "policy_events": len(policy_events)
    }
```

---

## 十、权重配置机制（数据库配置）

### 10.1 配置层级

```python
class DjangoWeightConfigRepository:
    """权重配置仓储"""

    def get_active_weights(
        self,
        asset_type: Optional[str] = None,
        market_condition: Optional[str] = None
    ) -> WeightConfig:
        """
        获取当前生效的权重配置

        优先级：
        1. 匹配 asset_type + market_condition 的配置
        2. 匹配 asset_type 的配置
        3. 通用配置（asset_type 为空）
        4. 默认权重（如果数据库无配置）
        """
        query = WeightConfigModel.objects.filter(is_active=True)

        # 优先匹配特定条件
        if asset_type and market_condition:
            specific = query.filter(
                asset_type=asset_type,
                market_condition=market_condition
            ).first()
            if specific:
                return self._to_entity(specific)

        # 其次匹配资产类型
        if asset_type:
            type_specific = query.filter(asset_type=asset_type).first()
            if type_specific:
                return self._to_entity(type_specific)

        # 最后使用通用配置
        general = query.filter(asset_type='').first()
        if general:
            return self._to_entity(general)

        # 降级到默认值
        return WeightConfig()

    def _to_entity(self, model: WeightConfigModel) -> WeightConfig:
        """ORM 转实体"""
        return WeightConfig(
            regime_weight=model.regime_weight,
            policy_weight=model.policy_weight,
            sentiment_weight=model.sentiment_weight,
            signal_weight=model.signal_weight
        )
```

### 10.2 初始化脚本

```python
# scripts/init_weight_config.py

"""
初始化权重配置数据

运行：python manage.py shell < scripts/init_weight_config.py
"""

from apps.asset_analysis.infrastructure.models import WeightConfigModel

# 1. 默认配置（通用）
WeightConfigModel.objects.get_or_create(
    name='default',
    defaults={
        'description': '默认权重配置（适用所有资产）',
        'regime_weight': 0.40,
        'policy_weight': 0.25,
        'sentiment_weight': 0.20,
        'signal_weight': 0.15,
        'is_active': True,
        'priority': 0,
    }
)

# 2. 政策危机配置
WeightConfigModel.objects.get_or_create(
    name='policy_crisis',
    defaults={
        'description': '政策危机时提高Policy权重',
        'regime_weight': 0.20,
        'policy_weight': 0.50,
        'sentiment_weight': 0.20,
        'signal_weight': 0.10,
        'market_condition': 'crisis',
        'is_active': True,
        'priority': 10,
    }
)

# 3. 情绪极端配置
WeightConfigModel.objects.get_or_create(
    name='sentiment_extreme',
    defaults={
        'description': '市场情绪极端时提高Sentiment权重',
        'regime_weight': 0.30,
        'policy_weight': 0.30,
        'sentiment_weight': 0.30,
        'signal_weight': 0.10,
        'market_condition': 'extreme_sentiment',
        'is_active': True,
        'priority': 10,
    }
)

print("权重配置初始化完成！")
```

---

## 十一、实施计划（详细任务清单）

### Phase 1: 通用框架基础（3-5天）✅ 已完成

**任务清单：**

- [x] **1.1 创建模块结构**
  - 创建 `apps/asset_analysis` 目录（已完成）
  - 创建 domain/application/infrastructure/interface 子目录（已完成）
  - 添加 `__init__.py` 文件（已完成）

- [x] **1.2 Domain 层实现**
  - `domain/entities.py`：AssetScore, AssetType, AssetStyle, AssetSize
  - `domain/value_objects.py`：WeightConfig, ScoreContext
  - `domain/services.py`：RegimeMatcher, PolicyMatcher, SentimentMatcher, SignalMatcher
  - `domain/interfaces.py`：AssetRepositoryProtocol

- [x] **1.3 Application 层实现**
  - `application/services.py`：AssetMultiDimScorer
  - `application/use_cases.py`：MultiDimScreenUseCase
  - `application/dtos.py`：ScreenRequest, ScreenResponse

- [x] **1.4 Infrastructure 层实现**
  - `infrastructure/models.py`：WeightConfigModel
  - `infrastructure/repositories.py`：DjangoWeightConfigRepository

- [x] **1.5 单元测试**
  - 测试 Domain 层匹配器
  - 测试 AssetMultiDimScorer
  - **测试结果：18/18 通过** ✅

**完成时间：2026-01-04**

### Phase 2: Sentiment 维度实现（3-4天）✅ 已完成

**任务清单：**

- [x] **2.1 创建 Sentiment 模块**
  - 创建 `apps/sentiment` 目录
  - 创建四层架构子目录

- [x] **2.2 Domain 层**
  - `domain/entities.py`：SentimentIndex, SentimentAnalysisResult, SentimentSource

- [x] **2.3 Application 层**
  - `application/services.py`：SentimentAnalyzer（调用 AI API）
  - `application/tasks.py`：calculate_daily_sentiment_index（Celery 任务）

- [x] **2.4 Infrastructure 层**
  - `infrastructure/models.py`：SentimentIndexModel, SentimentAnalysisLog, SentimentCache
  - `infrastructure/repositories.py`：SentimentIndexRepository

- [x] **2.5 集成测试**
  - 测试情感分析服务
  - 测试情绪指数计算
  - **测试结果：17/17 通过** ✅

**完成时间：2026-01-04**

### Phase 3: Fund 模块集成（2-3天）✅ 已完成

**任务清单：**

- [x] **3.1 扩展 Fund Domain 层**
  - 修改 `apps/fund/domain/entities.py`：添加 FundAssetScore（组合而非继承）
  - 实现风格和规模的自动映射

- [x] **3.2 实现 AssetRepositoryProtocol**
  - 修改 `apps/fund/infrastructure/repositories.py`：添加 DjangoFundAssetRepository
  - 实现通用资产仓储接口

- [x] **3.3 创建多维度筛选 API**
  - 修改 `apps/fund/application/services.py`：添加 FundMultiDimScorer
  - 修改 `apps/fund/interface/views.py`：FundMultiDimScreenAPIView
  - 修改 `apps/fund/interface/urls.py`：添加路由

- [x] **3.4 数据库配置**
  - 权重配置初始化（5条记录）
  - Sentiment 模块迁移

- [x] **3.5 API 集成测试**
  - 测试多维度筛选 API
  - 测试评分准确性
  - **测试结果：11/11 通过** ✅

**完成时间：2026-01-04**

**API 端点：**
- `POST /api/fund/multidim-screen/` - 基金多维度筛选

### Phase 4: Equity 模块集成（2-3天）✅ 已完成

**任务清单：**

- [x] **4.1 扩展 Equity Domain 层**
  - 修改 `apps/equity/domain/entities.py`：添加 EquityAssetScore（组合而非继承）
  - 实现风格（growth/value/blend/defensive）和规模（large/mid/small）的自动映射
  - 实现 `from_stock_info()` 类方法

- [x] **4.2 实现 AssetRepositoryProtocol**
  - 修改 `apps/equity/infrastructure/repositories.py`：添加 DjangoEquityAssetRepository
  - 实现通用资产仓储接口
  - 支持按行业、市场、市值、PE等过滤

- [x] **4.3 创建多维度筛选 API**
  - 创建 `apps/equity/application/services.py`：添加 EquityMultiDimScorer
  - 修改 `apps/equity/interface/views.py`：EquityMultiDimScreenAPIView
  - 修改 `apps/equity/interface/urls.py`：添加路由

- [x] **4.4 API 集成测试**
  - 测试多维度筛选 API
  - 测试评分准确性
  - 测试风险等级计算
  - **测试结果：13/13 通过** ✅

**完成时间：2026-01-04**

**API 端点：**
- `POST /api/equity/multidim-screen/` - 个股多维度筛选

### Phase 5: 数据初始化与迁移（1天）✅ 已完成

**任务清单：**

- [x] **5.1 创建初始化脚本**
  - 创建 `scripts/init_weight_config.py`

- [x] **5.2 执行数据迁移**
  - `python manage.py makemigrations sentiment`
  - `python manage.py migrate`

- [x] **5.3 初始化数据**
  - 运行权重配置初始化脚本（5条配置记录）
  - 数据完整性检查

**完成时间：2026-01-04**

### Phase 5: 前端界面更新（2-3天）✅ 已完成

**任务清单：**

- [x] **5.1 更新模板**
  - 修改 `core/templates/fund/dashboard.html`
  - 添加情绪指数卡片（5个统计卡片：Regime、置信度、Policy、情绪指数、推荐策略）
  - 添加多维度评分功能区域
  - 添加权重配置面板

- [x] **5.2 更新视图**
  - 修改 `apps/fund/interface/views.py`：fund_dashboard
  - 添加 Policy 档位和情绪指数信息获取

- [x] **5.3 前端交互测试**
  - 测试页面显示
  - 测试多维度评分功能
  - **测试结果：42/42 通过** ✅

**完成时间：2026-01-04**

**新增功能：**
- 基金 Dashboard 顶部显示 5 个关键指标卡片
- 多维度评分筛选功能（Regime + Policy + Sentiment + Signal）
- 权重配置查看按钮
- 激活信号数量显示

### Phase 6: 测试与优化（2-3天）✅ 已完成

**任务清单：**

- [x] **6.1 端到端测试**
  - 完整流程测试（42/42 测试通过）

- [ ] **6.2 性能优化**
  - 添加缓存机制（待后续实现）
  - 优化数据库查询（待后续实现）
  - 添加索引（待后续实现）

- [x] **6.3 监控与日志**
  - 添加评分日志 ✅
  - 添加异常告警 ✅

- [x] **6.4 文档更新**
  - 更新本文档

**完成时间：2026-01-04**

---

## 十二、日志与告警系统

### 12.1 评分日志

系统自动记录每次资产评分的详细信息，包括：
- 请求来源和用户信息
- 评分上下文（Regime、Policy、Sentiment、Signal）
- 权重配置
- 筛选条件
- 结果统计
- 执行时间
- 状态和错误信息

**日志模型：** `AssetScoringLog`
```python
from apps.asset_analysis.infrastructure.models import AssetScoringLog

# 查询最近的评分日志
recent_logs = AssetScoringLog.objects.filter(
    asset_type="fund",
    status="success"
).order_by('-created_at')[:10]
```

### 12.2 告警系统

系统支持多种类型的告警：
- **scoring_error**: 评分错误
- **weight_config_error**: 权重配置错误
- **data_quality_issue**: 数据质量问题
- **performance_issue**: 性能问题
- **api_failure**: API 调用失败
- **validation_error**: 验证错误

**告警严重级别：**
- **info**: 信息
- **warning**: 警告
- **error**: 错误
- **critical**: 严重

**告警模型：** `AssetAnalysisAlert`
```python
from apps.asset_analysis.infrastructure.models import AssetAnalysisAlert

# 查询未解决的告警
unresolved_alerts = AssetAnalysisAlert.objects.filter(
    is_resolved=False,
    severity__in=['error', 'critical']
).order_by('-created_at')
```

### 12.3 使用告警服务

```python
from apps.asset_analysis.application.logging_service import AlertService

alert_service = AlertService()

# 创建性能告警
alert_service.create_performance_alert(
    asset_type="fund",
    execution_time_ms=6000,
    threshold_ms=5000,
)

# 获取未解决的告警
alerts = alert_service.get_unresolved_alerts(severity="error")

# 解决告警
alert_service.resolve_alert(
    alert_id=123,
    resolved_by=1,
    resolution_notes="已修复权重配置问题"
)
```

---

## 十三、测试与验证

### 12.1 单元测试

```python
# tests/unit/shared/test_asset_matchers.py

def test_regime_matcher_recovery_equity():
    """测试 Regime 匹配器 - Recovery × Equity"""
    asset = AssetScore(
        asset_type=AssetType.EQUITY,
        asset_code="000001",
        asset_name="测试股票"
    )
    score = RegimeMatcher.match(asset, "Recovery")
    assert 85 <= score <= 95  # 应该得高分


def test_policy_matcher_p3_equity():
    """测试 Policy 匹配器 - P3 × Equity"""
    asset = AssetScore(
        asset_type=AssetType.EQUITY,
        asset_code="000001",
        asset_name="测试股票"
    )
    score = PolicyMatcher.match(asset, "P3")
    assert score <= 20  # 危机模式下股票得分低
```

### 12.2 集成测试

```python
# tests/integration/test_multidim_screen.py

def test_fund_multidim_screen_api():
    """测试基金多维度筛选 API"""
    client = APIClient()
    response = client.post('/fund/api/multidim-screen/', {
        "fund_type": "股票型",
        "investment_style": "成长",
        "max_count": 10
    })

    assert response.status_code == 200
    data = response.json()
    assert data['success'] is True
    assert len(data['assets']) <= 10
    assert 'context' in data
    assert 'weights' in data
```

### 12.3 性能测试

- [ ] 筛选响应时间 < 2秒（30只基金）
- [ ] 情绪分析 AI 调用 < 5秒/条
- [ ] 每日情绪指数计算 < 5分钟

---

## 十三、优势与价值

### 13.1 架构优势

- ✅ **DRY 原则**：减少 70%+ 重复代码
- ✅ **统一标准**：所有资产使用相同的评分体系
- ✅ **易于扩展**：新增资产类型只需继承 AssetScore
- ✅ **灵活配置**：权重可从数据库动态调整

### 13.2 业务价值

- ✅ **提高决策质量**：多维度交叉验证
- ✅ **适应市场变化**：Policy 档位和舆情实时反映
- ✅ **风险控制**：Signal 准入机制提供预警
- ✅ **AI 赋能**：情感分析自动化

---

## 十四、后续扩展

### 14.1 Equity 模块迁移 ✅ 已完成

- ✅ 将股票评分迁移到通用框架
- ✅ 添加股票特有维度（technical_score, fundamental_score, valuation_score）
- ✅ 实现多维度筛选 API
- ✅ 完成集成测试（13/13 测试通过）

### 14.2 回测验证

- 使用历史数据验证多维度评分效果
- 优化权重配置

### 14.3 机器学习优化

- 使用 ML 自动调整权重
- 预测最优资产配置

### 14.4 实时情绪监控

- 集成新闻 API 实时分析
- 实时情绪指数更新

---

## 相关文档

- [RSS 政策事件集成文档](../integration/rss_policy_integration.md)
- [投资信号与持仓关系说明](../business/signal_and_position.md)
- [AgomTradePro_V3.4 架构文档](../business/AgomTradePro_V3.4.md)
- [API 参考文档](../testing/api/API_REFERENCE.md)

---

## 更新日志

- **2026-01-04**: v3.3 日志与告警版发布
  - ✅ 新增日志记录功能
  - ✅ 新增异常告警功能
  - 新增 `AssetScoringLog` 模型：记录每次评分的详细信息
  - 新增 `AssetAnalysisAlert` 模型：存储和管理告警
  - 新增 `ScoringLogger` 服务：评分日志记录器
  - 新增 `AlertService` 服务：告警服务（支持6种告警类型）
  - 更新 `AssetMultiDimScorer`：集成日志和告警功能
  - 数据库迁移：新增 `asset_scoring_log` 和 `asset_analysis_alert` 表
  - 测试覆盖：新增 15 个日志和告警测试
  - 支持的告警类型：
    - scoring_error（评分错误）
    - weight_config_error（权重配置错误）
    - data_quality_issue（数据质量问题）
    - performance_issue（性能问题）
    - api_failure（API 调用失败）
    - validation_error（验证错误）

- **2026-01-04**: v3.2 前端集成版发布
  - ✅ Phase 5 完成：数据初始化与迁移
  - ✅ Phase 5 完成：前端界面更新
  - ✅ Phase 6 完成：测试与优化（42/42 测试通过）
  - 更新 `apps/fund/interface/views.py`：添加 Policy 和 Sentiment 信息
  - 更新 `core/templates/fund/dashboard.html`：
    - 顶部显示 5 个关键指标卡片（Regime、置信度、Policy、情绪指数、推荐策略）
    - 新增多维度评分筛选功能区域
    - 支持查看权重配置
    - 显示激活信号数量
  - 初始化权重配置数据（5 条配置记录）
  - 前端 JavaScript 集成多维度评分 API
  - 测试覆盖：42 个测试全部通过

- **2026-01-04**: v3.1 Equity 集成版发布
  - ✅ Phase 4 完成：Equity 模块集成（13/13 测试通过）
  - 扩展 `apps/equity` 集成通用资产分析框架
  - 新增 `EquityAssetScore` 实体（支持风格/规模自动映射）
  - 新增 `DjangoEquityAssetRepository` 仓储实现
  - 新增 `EquityMultiDimScorer` 评分服务
  - API 端点：`/api/equity/multidim-screen/`（个股多维度筛选）
  - 支持按行业、市场、市值、PE 等过滤
  - 支持个股特有维度：技术面、基本面、估值评分

- **2026-01-04**: v3.0 实现版发布
  - ✅ Phase 1 完成：通用资产分析框架（18/18 测试通过）
  - ✅ Phase 2 完成：Sentiment 情感分析模块（17/17 测试通过）
  - ✅ Phase 3 完成：Fund 模块集成（11/11 测试通过）
  - 新增 `apps/asset_analysis` 通用资产分析模块
  - 新增 `apps/sentiment` 舆情情感分析模块
  - 扩展 `apps/fund` 集成通用资产分析框架
  - 数据库表：`asset_weight_config`, `sentiment_index`, `sentiment_analysis_log`, `sentiment_cache`
  - API 端点：`/api/fund/multidim-screen/`（基金多维度筛选）

- **2026-01-03**: v2.0 整合版发布
  - 合并基金增强计划和通用框架文档
  - 采用 AI API 方案实现情感分析
  - 采用数据库配置管理权重
  - 完善实施计划和任务清单
