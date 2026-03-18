# AgomSaaS 系统扩展计划：因子选股 + 资产轮动 + 对冲组合

> **版本**: 1.0
> **创建日期**: 2026-02-05
> **预计工期**: 11 周（5 个 Phase）
> **依赖**: AgomSaaS V3.4 架构

---

## 1. 项目概述

### 1.1 目标

在现有 AgomSaaS 系统基础上，新增三大核心功能模块：

| 模块 | 功能描述 | 业务价值 |
|------|----------|----------|
| **因子选股 (Factor)** | 基于多因子的股票筛选和评分 | 系统化选股，量化选股逻辑 |
| **资产轮动 (Rotation)** | 跨资产类别的动态配置 | 顺应宏观周期，优化资产配置 |
| **对冲组合 (Hedge)** | 负相关资产对冲风险 | 降低组合波动，控制回撤 |

### 1.2 架构原则

遵循 AgomSaaS 四层架构：

```
┌─────────────────────────────────────────────────────────┐
│                   Interface 层                            │
│  views.py | serializers.py | urls.py | admin.py        │
├─────────────────────────────────────────────────────────┤
│                Application 层                             │
│  use_cases.py | tasks.py | dtos.py                     │
├─────────────────────────────────────────────────────────┤
│                  Domain 层                                │
│  entities.py | services.py | rules.py (纯业务逻辑)      │
├─────────────────────────────────────────────────────────┤
│               Infrastructure 层                            │
│  models.py | repositories.py | adapters/                │
└─────────────────────────────────────────────────────────┘
```

### 1.3 数据初始化原则

**❌ 禁止硬编码**：所有配置数据存储在数据库中
**✅ 必须提供初始化脚本**：通过 Django management command 初始化

---

## 2. 模块设计

### 2.1 因子选股模块 (apps/factor)

#### 功能定位

多因子选股系统，支持：
- 因子计算（价值、质量、成长、动量、波动、流动性）
- 因子合成（加权打分）
- 股票池筛选（沪深300、中证500等）
- 组合生成

#### 四层结构

```
apps/factor/
├── domain/
│   ├── entities.py          # FactorDefinition, FactorExposure, FactorPortfolio
│   ├── services.py          # FactorEngine, ScoringService
│   └── rules.py             # 因子计算规则
├── application/
│   ├── use_cases.py         # CalculateFactorUseCase, CreatePortfolioUseCase
│   └── dtos.py              # FactorCalculationRequest, PortfolioConfig
├── infrastructure/
│   ├── models.py            # FactorDefinitionModel, FactorExposureModel
│   ├── repositories.py      # FactorRepository
│   └── adapters/            # TushareFactorAdapter
├── interface/
│   ├── views.py             # FactorViewSet
│   ├── serializers.py       # FactorSerializer
│   └── urls.py              # /api/factor/
└── management/
    └── commands/
        └── init_factors.py   # 初始化因子定义数据
```

#### 核心实体 (Domain)

```python
# domain/entities.py
from dataclasses import dataclass
from typing import Dict, List
from enum import Enum

class FactorCategory(Enum):
    VALUE = "value"       # 价值
    QUALITY = "quality"   # 质量
    GROWTH = "growth"     # 成长
    MOMENTUM = "momentum" # 动量
    VOLATILITY = "volatility" # 波动
    LIQUIDITY = "liquidity"   # 流动性

@dataclass(frozen=True)
class FactorDefinition:
    """因子定义"""
    code: str                    # 因子代码，如 "pe_ttm"
    name: str                    # 因子名称
    category: FactorCategory     # 因子类别
    description: str             # 描述
    data_source: str             # 数据来源
    update_frequency: str        # 更新频率：daily, weekly, monthly
    is_active: bool = True

@dataclass(frozen=True)
class FactorExposure:
    """因子暴露度"""
    stock_code: str
    trade_date: date
    factor_code: str
    factor_value: float
    percentile_rank: float       # 全市场排名百分位 (0-1)
    z_score: float               # 标准化得分

@dataclass(frozen=True)
class FactorPortfolioConfig:
    """因子组合配置"""
    name: str
    factor_weights: Dict[str, float]  # {"pe_ttm": -0.3, "roe": 0.3}
    universe: str                      # 'hs300', 'zz500', 'all_a'
    rebalance_frequency: str           # 'weekly', 'monthly'
    top_n: int                         # 选股数量
    min_market_cap: float = None       # 最小市值
    max_pe: float = None               # 最大PE
```

#### 数据库模型 (Infrastructure)

```python
# infrastructure/models.py
from django.db import models

class FactorDefinitionModel(models.Model):
    """因子定义表"""
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=[
        ('value', '价值'),
        ('quality', '质量'),
        ('growth', '成长'),
        ('momentum', '动量'),
        ('volatility', '波动'),
        ('liquidity', '流动性'),
    ])
    description = models.TextField(blank=True)
    data_source = models.CharField(max_length=50)
    update_frequency = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

    def to_domain(self) -> FactorDefinition:
        return FactorDefinition(
            code=self.code,
            name=self.name,
            category=FactorCategory(self.category),
            description=self.description,
            data_source=self.data_source,
            update_frequency=self.update_frequency,
            is_active=self.is_active,
        )

class FactorExposureModel(models.Model):
    """因子暴露度表"""
    stock_code = models.CharField(max_length=20, db_index=True)
    trade_date = models.DateField(db_index=True)
    factor_code = models.CharField(max_length=50, db_index=True)
    factor_value = models.DecimalField(max_digits=18, decimal_places=6)
    percentile_rank = models.DecimalField(max_digits=5, decimal_places=4)
    z_score = models.DecimalField(max_digits=10, decimal_places=6)

    class Meta:
        unique_together = [('stock_code', 'trade_date', 'factor_code')]
        indexes = [
            models.Index(fields=['trade_date', 'factor_code']),
            models.Index(fields=['stock_code', 'trade_date']),
        ]

class FactorPortfolioConfigModel(models.Model):
    """因子组合配置表"""
    name = models.CharField(max_length=100, unique=True)
    factor_weights = models.JSONField()  # {"pe_ttm": -0.3, "roe": 0.3}
    universe = models.CharField(max_length=20)  # 'hs300', 'zz500', 'all_a'
    rebalance_frequency = models.CharField(max_length=20)
    top_n = models.IntegerField(default=30)
    min_market_cap = models.DecimalField(max_digits=18, decimal_places=2, null=True)
    max_pe = models.DecimalField(max_digits=10, decimal_places=4, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class FactorPortfolioHoldingModel(models.Model):
    """因子组合持仓表"""
    config = models.ForeignKey(FactorPortfolioConfigModel, on_delete=models.CASCADE)
    trade_date = models.DateField()
    stock_code = models.CharField(max_length=20)
    weight = models.DecimalField(max_digits=5, decimal_places=4)
    factor_score = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        unique_together = [('config', 'trade_date', 'stock_code')]
```

#### 初始化脚本 (management command)

```python
# management/commands/init_factors.py
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = '初始化因子定义数据'

    def handle(self, **options):
        initial_factors = [
            {
                'code': 'pe_ttm',
                'name': 'PE(TTM)',
                'category': 'value',
                'description': '滚动市盈率',
                'data_source': 'tushare',
                'update_frequency': 'daily',
            },
            {
                'code': 'pb',
                'name': '市净率',
                'category': 'value',
                'description': '市净率',
                'data_source': 'tushare',
                'update_frequency': 'daily',
            },
            # ... 更多因子
        ]

        for factor_data in initial_factors:
            factor, created = FactorDefinitionModel.objects.get_or_create(
                code=factor_data['code'],
                defaults=factor_data
            )
            if created:
                self.stdout.write(f'[创建] {factor.code} - {factor.name}')
            else:
                self.stdout.write(f'[存在] {factor.code} - {factor.name}')
```

---

### 2.2 资产轮动模块 (apps/rotation)

#### 功能定位

跨资产类别轮动系统，支持：
- 基于 Regime 的轮动
- 动量轮动
- 风险平价轮动
- 资产配置建议

#### 四层结构

```
apps/rotation/
├── domain/
│   ├── entities.py          # AssetClass, RotationSignal, RotationConfig
│   ├── services.py          # RegimeBasedRotation, MomentumRotation, RiskParityRotation
│   └── rules.py             # 轮动策略规则
├── application/
│   ├── use_cases.py         # GenerateRotationSignalUseCase
│   └── dtos.py
├── infrastructure/
│   ├── models.py            # AssetClassModel, RotationSignalModel
│   ├── repositories.py
│   └── adapters/
├── interface/
│   ├── views.py
│   ├── serializers.py
│   └── urls.py              # /api/rotation/
└── management/
    └── commands/
        └── init_rotation.py  # 初始化资产类别和配置
```

#### 核心实体 (Domain)

```python
# domain/entities.py
class AssetCategory(Enum):
    EQUITY = "equity"       # 股票
    BOND = "bond"           # 债券
    COMMODITY = "commodity" # 商品
    CURRENCY = "currency"   # 货币
    ALTERNATIVE = "alternative" # 另类

@dataclass(frozen=True)
class AssetClass:
    """可投资资产类别"""
    code: str               # 资产代码，如 "510300" (沪深300ETF)
    name: str               # 资产名称
    category: AssetCategory # 资产类别
    description: str
    underlying_index: str   # 标的指数

@dataclass(frozen=True)
class RotationSignal:
    """轮动信号"""
    signal_date: date
    config_id: str
    target_allocation: Dict[str, float]  # {"510300": 0.3, "511260": 0.4}
    current_regime: str      # 当前宏观象限
    momentum_rank: List[Tuple[str, float]]  # [(资产代码, 动量得分)]
    risk_adjusted: bool
```

#### 数据库模型

```python
# infrastructure/models.py
class AssetClassModel(models.Model):
    """资产类别表"""
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=20, choices=[
        ('equity', '股票'),
        ('bond', '债券'),
        ('commodity', '商品'),
        ('currency', '货币'),
        ('alternative', '另类'),
    ])
    description = models.TextField(blank=True)
    underlying_index = models.CharField(max_length=50)
    is_active = models.BooleanField(default=True)

class RotationConfigModel(models.Model):
    """轮动配置表"""
    name = models.CharField(max_length=100, unique=True)
    strategy_type = models.CharField(max_length=50, choices=[
        ('regime_based', '基于象限'),
        ('momentum', '动量轮动'),
        ('risk_parity', '风险平价'),
    ])
    params = models.JSONField()  # 策略参数
    rebalance_frequency = models.CharField(max_length=20)
    is_active = models.BooleanField(default=True)

class RotationSignalModel(models.Model):
    """轮动信号历史"""
    config = models.ForeignKey(RotationConfigModel, on_delete=models.CASCADE)
    signal_date = models.DateField(db_index=True)
    target_allocation = models.JSONField()  # {"510300": 0.3, ...}
    current_regime = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [('config', 'signal_date')]
```

#### 初始化脚本

```python
# management/commands/init_rotation.py
INITIAL_ASSETS = [
    {
        'code': '510300',
        'name': '沪深300ETF',
        'category': 'equity',
        'underlying_index': '000300.SH',
        'description': '跟踪沪深300指数，蓝筹代表',
    },
    {
        'code': '510500',
        'name': '中证500ETF',
        'category': 'equity',
        'underlying_index': '000905.SH',
        'description': '跟踪中证500指数，成长代表',
    },
    # ... 更多资产
]

REGIME_ALLOCATION = {
    "Recovery": {
        "510300": 0.30,
        "510500": 0.20,
        "159985": 0.15,  # 商品
        "511260": 0.20,  # 国债
        "511880": 0.15,  # 货币
    },
    # ... 更多象限配置
}
```

---

### 2.3 对冲组合模块 (apps/hedge)

#### 功能定位

对冲组合管理系统，支持：
- 相关性监控
- 对冲比例计算
- 对冲组合构建
- 对冲效果验证

#### 四层结构

```
apps/hedge/
├── domain/
│   ├── entities.py          # HedgePair, CorrelationMetric, HedgePortfolio
│   ├── services.py          # CorrelationMonitor, HedgeRatioCalculator
│   └── rules.py             # 对冲规则
├── application/
│   ├── use_cases.py         # CreateHedgePortfolioUseCase, MonitorCorrelationUseCase
│   └── dtos.py
├── infrastructure/
│   ├── models.py            # HedgePairModel, CorrelationHistoryModel
│   ├── repositories.py
│   └── adapters/
├── interface/
│   ├── views.py
│   ├── serializers.py
│   └── urls.py              # /api/hedge/
└── management/
    └── commands/
        └── init_hedge.py     # 初始化对冲对配置
```

#### 核心实体 (Domain)

```python
# domain/entities.py
class HedgeMethod(Enum):
    BETA = "beta"                   # Beta对冲
    MIN_VARIANCE = "min_variance"   # 最小方差
    EQUAL_RISK = "equal_risk"       # 等风险贡献

@dataclass(frozen=True)
class HedgePair:
    """对冲对"""
    name: str                    # 组合名称，如 "股债对冲"
    long_asset: str             # 多头资产代码
    hedge_asset: str            # 对冲资产代码
    hedge_method: HedgeMethod   # 对冲方法
    target_long_weight: float   # 目标多头权重

@dataclass(frozen=True)
class CorrelationMetric:
    """相关性指标"""
    asset1: str
    asset2: str
    calc_date: date
    window_days: int
    correlation: float          # 相关系数
    alert: str = None           # 预警信息

@dataclass(frozen=True)
class HedgePortfolio:
    """对冲组合"""
    config_id: str
    trade_date: date
    long_weight: float
    hedge_weight: float
    hedge_ratio: float          # 对冲比例
    current_correlation: float  # 当前相关性
    portfolio_beta: float       # 组合Beta
```

#### 数据库模型

```python
# infrastructure/models.py
class HedgePairModel(models.Model):
    """对冲对配置表"""
    name = models.CharField(max_length=100, unique=True)
    long_asset = models.CharField(max_length=20)
    hedge_asset = models.CharField(max_length=20)
    hedge_method = models.CharField(max_length=30, choices=[
        ('beta', 'Beta对冲'),
        ('min_variance', '最小方差'),
        ('equal_risk', '等风险贡献'),
    ])
    target_long_weight = models.DecimalField(max_digits=5, decimal_places=4, default=0.7)
    rebalance_trigger = models.DecimalField(max_digits=5, decimal_places=4, default=0.05)
    is_active = models.BooleanField(default=True)

class CorrelationHistoryModel(models.Model):
    """相关性历史表"""
    asset1 = models.CharField(max_length=20, db_index=True)
    asset2 = models.CharField(max_length=20, db_index=True)
    calc_date = models.DateField(db_index=True)
    window_days = models.IntegerField()
    correlation = models.DecimalField(max_digits=6, decimal_places=4)

    class Meta:
        unique_together = [('asset1', 'asset2', 'calc_date', 'window_days')]
        indexes = [
            models.Index(fields=['calc_date', 'asset1', 'asset2']),
        ]

class HedgePortfolioHoldingModel(models.Model):
    """对冲组合持仓表"""
    config = models.ForeignKey(HedgePairModel, on_delete=models.CASCADE)
    trade_date = models.DateField()
    long_weight = models.DecimalField(max_digits=5, decimal_places=4)
    hedge_weight = models.DecimalField(max_digits=5, decimal_places=4)
    current_correlation = models.DecimalField(max_digits=6, decimal_places=4)
    portfolio_beta = models.DecimalField(max_digits=6, decimal_places=4)

    class Meta:
        unique_together = [('config', 'trade_date')]
```

#### 初始化脚本

```python
# management/commands/init_hedge.py
INITIAL_HEDGE_PAIRS = [
    {
        'name': '股债对冲',
        'long_asset': '510300',     # 沪深300
        'hedge_asset': '511260',    # 10年国债
        'hedge_method': 'beta',
        'target_long_weight': 0.7,
    },
    {
        'name': '成长价值对冲',
        'long_asset': '159915',     # 创业板ETF
        'hedge_asset': '512100',    # 红利ETF
        'hedge_method': 'equal_risk',
        'target_long_weight': 0.6,
    },
    # ... 更多对冲对
]
```

---

## 3. 统一信号系统

### 3.1 扩展现有 Signal 模块

在现有 `apps/signal/` 基础上扩展，新增统一信号表：

```python
# apps/signal/infrastructure/models.py (新增)
class UnifiedSignalModel(models.Model):
    """统一信号表（汇总各模块信号）"""
    signal_date = models.DateField(db_index=True)
    signal_source = models.CharField(max_length=30, choices=[
        ('regime', '宏观象限'),
        ('factor', '因子选股'),
        ('rotation', '资产轮动'),
        ('hedge', '对冲组合'),
        ('manual', '手动'),
    ])
    signal_type = models.CharField(max_length=30)  # buy, sell, rebalance, alert
    asset_code = models.CharField(max_length=20, db_index=True)
    asset_name = models.CharField(max_length=100)
    target_weight = models.DecimalField(max_digits=5, decimal_places=4, null=True)
    current_weight = models.DecimalField(max_digits=5, decimal_places=4, null=True)
    action_required = models.CharField(max_length=50)
    priority = models.IntegerField(default=5)  # 1-10
    reason = models.TextField()
    is_executed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['signal_date', '-priority']),
            models.Index(fields=['signal_date', 'signal_source']),
        ]
```

---

## 4. SDK 和 MCP 扩展

### 4.1 SDK 新增模块

```
sdk/agomsaaf/modules/
├── factor.py              # 因子选股模块
│   └── FactorModule
├── rotation.py            # 资产轮动模块
│   └── RotationModule
└── hedge.py               # 对冲组合模块
    └── HedgeModule
```

### 4.2 MCP 新增工具

```
sdk/agomsaaf_mcp/tools/
├── factor_tools.py        # get_factor_top_stocks, explain_factor_stock
├── rotation_tools.py      # get_rotation_signal, compare_asset_momentum
└── hedge_tools.py         # get_correlation_matrix, check_hedge_effectiveness
```

---

## 5. 实施路线图

### Phase 1: 数据基础（2 周）

**目标**: 建立数据采集和存储基础

| 任务 | 具体内容 | 交付物 |
|------|----------|--------|
| ETF 行情数据 | 接入 10+ 核心 ETF 日线数据 | 能查询 ETF 历史价格 |
| 股票基本面数据 | 接入 PE/PB/ROE 等核心指标 | 能查询股票基本面 |
| 相关性计算引擎 | 实现滚动相关性计算 | 能计算任意两资产相关性 |
| 初始化脚本 | `init_factors`, `init_rotation`, `init_hedge` | 一键初始化所有配置 |

**文件清单**:
- `shared/infrastructure/correlation.py` - 相关性计算算法
- `apps/factor/management/commands/init_factors.py`
- `apps/rotation/management/commands/init_rotation.py`
- `apps/hedge/management/commands/init_hedge.py`

### Phase 2: 资产轮动（2 周）

**目标**: 实现基于 Regime 和动量的轮动策略

| 任务 | 具体内容 | 交付物 |
|------|----------|--------|
| Rotation 模块完整实现 | 四层架构完整 | 可用的轮动模块 |
| Regime 轮动策略 | 对接现有 Regime 模块 | 能根据象限生成配置 |
| 动量轮动策略 | N 个月动量排序 | 动量排名 |
| MCP 工具 | `get_rotation_signal` | 可通过 Claude 调用 |

**关键文件**:
- `apps/rotation/domain/services.py` - 轮动策略实现
- `apps/rotation/application/use_cases.py` - 用例编排
- `sdk/agomsaaf_mcp/tools/rotation_tools.py`

### Phase 3: 因子选股（3 周）

**目标**: 实现多因子选股系统

| 任务 | 具体内容 | 交付物 |
|------|----------|--------|
| Factor 模块完整实现 | 四层架构完整 | 可用的因子模块 |
| 6 大核心因子 | 价值、质量、成长、动量、波动、流动性 | 因子计算 |
| 因子合成 | 综合打分，排名 | 选股结果 |
| MCP 工具 | `get_factor_top_stocks` | 可通过 Claude 调用 |

**关键文件**:
- `apps/factor/domain/services.py` - FactorEngine
- `apps/factor/infrastructure/adapters/tushare_adapter.py` - Tushare 数据适配器

### Phase 4: 对冲组合（2 周）

**目标**: 实现对冲组合管理

| 任务 | 具体内容 | 交付物 |
|------|----------|--------|
| Hedge 模块完整实现 | 四层架构完整 | 可用的对冲模块 |
| 相关性监控 | 异常预警 | 预警信号 |
| 对冲比例计算 | Beta/等风险 | 对冲比例 |
| MCP 工具 | `check_hedge_effectiveness` | 可通过 Claude 调用 |

**关键文件**:
- `apps/hedge/domain/services.py` - CorrelationMonitor, HedgeRatioCalculator
- `apps/hedge/application/use_cases.py` - CreateHedgePortfolioUseCase

### Phase 5: 整合优化（2 周）

**目标**: 整合所有模块，完善用户体验

| 任务 | 具体内容 | 交付物 |
|------|----------|--------|
| 统一信号系统 | 汇总所有模块信号 | unified_signal 表 |
| 回测验证 | 各策略历史表现 | 回测报告 |
| 仪表盘 | 可视化展示 | Dashboard 页面 |
| 文档完善 | 使用指南、API 文档 | docs/ |

---

## 6. 关键文件清单

### 新建文件

```
apps/factor/
├── __init__.py
├── domain/
│   ├── entities.py
│   ├── services.py
│   └── rules.py
├── application/
│   ├── __init__.py
│   ├── use_cases.py
│   └── dtos.py
├── infrastructure/
│   ├── __init__.py
│   ├── models.py
│   ├── repositories.py
│   └── adapters/
│       └── __init__.py
├── interface/
│   ├── __init__.py
│   ├── views.py
│   ├── serializers.py
│   └── urls.py
└── management/
    └── commands/
        ├── __init__.py
        └── init_factors.py

apps/rotation/
├── (同样结构)
└── management/commands/init_rotation.py

apps/hedge/
├── (同样结构)
└── management/commands/init_hedge.py

sdk/agomsaaf/modules/
├── factor.py
├── rotation.py
└── hedge.py

sdk/agomsaaf_mcp/tools/
├── factor_tools.py
├── rotation_tools.py
└── hedge_tools.py

docs/
├── factor-guide.md
├── rotation-guide.md
└── hedge-guide.md
```

### 修改文件

```
apps/signal/
├── infrastructure/models.py  # 新增 UnifiedSignalModel
└── domain/entities.py        # 扩展 Signal 实体

sdk/agomsaaf/
├── __init__.py                # 注册新模块
└── client.py                  # 添加模块属性

sdk/agomsaaf_mcp/
└── server.py                  # 注册新工具

core/
└── settings/
    └── base.py                # 注册新 app
```

---

## 7. 验收标准

### 功能验收

| 模块 | 验收标准 |
|------|----------|
| **Factor** | 能通过 Claude "帮我选 20 只低估值高质量股票" 获得结果 |
| **Rotation** | 能通过 Claude "现在该买什么资产" 获得配置建议 |
| **Hedge** | 能通过 Claude "我的股债组合对冲还有效吗" 获得评估 |
| **统一信号** | 所有模块信号汇总到 unified_signal 表 |

### 技术验收

- [ ] 所有数据通过初始化脚本加载，无硬编码
- [ ] 遵循四层架构，Domain 层无外部依赖
- [ ] 所有模块有完整的单元测试（覆盖率 >80%）
- [ ] MCP 工具可正常调用
- [ ] SDK API 可正常调用
- [ ] 数据库迁移正常执行

---

## 8. 风险和依赖

### 依赖

| 依赖项 | 状态 | 说明 |
|--------|------|------|
| Tushare 数据权限 | 待确认 | 需要积分账户 |
| 现有 Regime 模块 | ✅ 已有 | 直接对接 |
| 现有 Policy 模块 | ✅ 已有 | 对冲位置已有 |

### 风险

| 风险 | 缓解措施 |
|------|----------|
| 数据质量 | 建立 Failover 机制 |
| 因子有效性 | 定期回测验证 |
| 相关性失灵 | 实时监控预警 |
| 性能问题 | 异步计算 + 缓存 |

---

## 9. 时间表

```
Week 1-2:   Phase 1 - 数据基础
Week 3-4:   Phase 2 - 资产轮动
Week 5-7:   Phase 3 - 因子选股
Week 8-9:   Phase 4 - 对冲组合
Week 10-11: Phase 5 - 整合优化
```

---

## 10. 后续扩展

完成后可以考虑：
- 更多因子（情绪、分析师预期）
- 机器学习因子挖掘
- 期权对冲策略
- 跨市场轮动（A股、港股、美股）
