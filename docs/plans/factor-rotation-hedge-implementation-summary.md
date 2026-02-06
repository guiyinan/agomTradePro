# 因子选股 + 资产轮动 + 对冲组合 实施总结

> **实施日期**: 2026-02-05
> **实施阶段**: Phase 1 - 数据基础设施
> **状态**: ✅ 完成

## 1. 实施概览

### 新增模块

| 模块 | 功能 | 文件数 | 数据表数 |
|------|------|--------|----------|
| **Factor** | 因子选股 | 15+ | 5 |
| **Rotation** | 资产轮动 | 15+ | 5 |
| **Hedge** | 对冲组合 | 15+ | 5 |

### 总计

- **新增文件**: 45+ 个
- **新增数据表**: 15 个
- **初始化数据**:
  - 因子定义: 27 个
  - 因子组合配置: 6 个
  - 资产类别: 18 个 ETF
  - 轮动配置: 5 个
  - 对冲对配置: 10 个

## 2. 模块架构

### Factor (因子选股)

```
apps/factor/
├── domain/
│   ├── entities.py          # FactorDefinition, FactorScore, FactorPortfolioConfig
│   └── services.py          # FactorEngine, ScoringService (纯Python)
├── application/
│   ├── dtos.py              # 数据传输对象
│   └── use_cases.py         # CalculateFactorScoresUseCase, CreateFactorPortfolioUseCase
├── infrastructure/
│   ├── models.py            # 5个ORM模型
│   └── management/commands/
│       └── init_factors.py  # 初始化命令
└── interface/
    ├── views.py             # DRF ViewSets
    ├── serializers.py       # DRF Serializers
    └── urls.py              # API路由
```

### Rotation (资产轮动)

```
apps/rotation/
├── domain/
│   ├── entities.py          # AssetClass, RotationConfig, RotationSignal, MomentumScore
│   └── services.py          # MomentumRotationEngine, RegimeBasedRotationEngine
├── application/
│   ├── dtos.py
│   └── use_cases.py         # GenerateRotationSignalUseCase, CompareAssetsUseCase
├── infrastructure/
│   ├── models.py            # 5个ORM模型
│   └── management/commands/
│       └── init_rotation.py  # 初始化命令
└── interface/
    ├── views.py
    ├── serializers.py
    └── urls.py
```

### Hedge (对冲组合)

```
apps/hedge/
├── domain/
│   ├── entities.py          # HedgePair, CorrelationMetric, HedgePortfolio
│   └── services.py          # CorrelationMonitor, HedgeRatioCalculator
├── application/
│   ├── dtos.py
│   └── use_cases.py         # CheckHedgeEffectivenessUseCase
├── infrastructure/
│   ├── models.py            # 5个ORM模型
│   └── management/commands/
│       └── init_hedge.py     # 初始化命令
└── interface/
    ├── views.py
    ├── serializers.py
    └── urls.py
```

## 3. 数据表

### Factor 模块

| 表名 | 用途 |
|------|------|
| `factor_definition` | 因子定义（27个因子） |
| `factor_exposure` | 因子暴露度历史 |
| `factor_portfolio_config` | 因子组合配置（6个配置） |
| `factor_portfolio_holdings` | 因子组合持仓 |
| `factor_performance` | 因子表现跟踪 |

### Rotation 模块

| 表名 | 用途 |
|------|------|
| `rotation_asset_class` | 资产类别（18个ETF） |
| `rotation_config` | 轮动配置（5个策略） |
| `rotation_signal` | 轮动信号历史 |
| `rotation_portfolio` | 轮动组合状态 |
| `rotation_momentum_score` | 动量得分缓存 |

### Hedge 模块

| 表名 | 用途 |
|------|------|
| `hedge_pair` | 对冲对配置（10个对冲对） |
| `hedge_correlation_history` | 相关性历史 |
| `hedge_portfolio_holdings` | 对冲组合持仓 |
| `hedge_alert` | 对冲告警 |
| `hedge_performance` | 对冲表现跟踪 |

## 4. 初始化数据

### 因子定义 (27个)

**价值因子**:
- PE(TTM)、PB、PS、股息率

**质量因子**:
- ROE、ROA、资产负债率、流动比率、毛利率

**成长因子**:
- 营收增长率、利润增长率、营收3年复合增长率

**动量因子**:
- 1月/3月/6月动量、52周新高距离

**波动因子**:
- 20日/60日波动率、Beta、下行捕获率

**流动性因子**:
- 20日/60日换手率、20日振幅、量比

**技术因子**:
- RSI、MACD、均线交叉

### 因子组合配置 (6个)

1. **价值成长平衡组合** - 平衡价值和成长因子
2. **深度价值组合** - 专注低估值股票
3. **高成长组合** - 专注高成长股票
4. **质量优选组合** - 专注高质量公司
5. **动量精选组合** - 基于价格动量
6. **小盘价值组合** - 专注小盘价值股

### 资产类别 (18个ETF)

**股票ETF**:
- 沪深300ETF、中证500ETF、创业板ETF、中证1000ETF、科创50ETF
- 白酒ETF、新能源ETF、红利ETF

**债券ETF**:
- 十年国债ETF、国债ETF、十年地方债ETF、可转债ETF

**商品ETF**:
- 豆粕ETF、黄金ETF、能源化工ETF

**货币基金**:
- 银华日利、华宝添益、建信添益

### 轮动策略配置 (5个)

1. **动量轮动策略** - 基于价格动量选择表现最好的3-5个资产
2. **宏观象限轮动策略** - 根据宏观象限配置
3. **风险平价策略** - 按波动率倒数分配权重
4. **股债平衡轮动** - 股债动态平衡
5. **核心卫星策略** - 核心资产(沪深300) 60%，卫星资产轮动 40%

### 对冲对配置 (10个)

1. **股债对冲** - 沪深300ETF vs 10年国债ETF
2. **成长价值对冲** - 创业板ETF vs 红利ETF
3. **大小盘对冲** - 中证1000ETF vs 沪深300ETF
4. **股票黄金对冲** - 沪深300ETF vs 黄金ETF
5. **股票商品对冲** - 沪深300ETF vs 豆粕ETF
6. **A股黄金对冲** - 中证500ETF vs 黄金ETF
7. **高波低波对冲** - 创业板ETF vs 10年国债ETF
8. **中盘国债对冲** - 中证500ETF vs 10年国债ETF
9. **核心卫星对冲** - 中证1000ETF vs 沪深300ETF
10. **可转债对冲** - 沪深300ETF vs 可转债ETF

## 5. API 端点

### Factor API

```
GET    /factor/api/definitions/       # 获取所有因子定义
GET    /factor/api/configs/           # 获取所有因子组合配置
POST   /factor/api/configs/{id}/activate/   # 激活配置
POST   /factor/api/configs/calculate_scores/ # 计算因子得分
```

### Rotation API

```
GET    /rotation/api/assets/          # 获取所有资产类别
GET    /rotation/api/configs/         # 获取所有轮动配置
POST   /rotation/api/configs/{id}/generate_signal/ # 生成轮动信号
GET    /rotation/api/signals/latest/  # 获取最新信号
```

### Hedge API

```
GET    /hedge/api/pairs/              # 获取所有对冲对
POST   /hedge/api/pairs/{id}/check_effectiveness/ # 检查对冲效果
GET    /hedge/api/correlations/       # 获取相关性历史
GET    /hedge/api/holdings/latest/    # 获取最新持仓
GET    /hedge/api/alerts/             # 获取告警列表
POST   /hedge/api/alerts/{id}/resolve/ # 解决告警
```

## 6. 管理命令

```bash
# 初始化因子定义和组合配置
python manage.py init_factors

# 初始化资产类别和轮动配置
python manage.py init_rotation

# 初始化对冲对配置
python manage.py init_hedge
```

## 7. 下一步

Phase 1 已完成，建立了完整的数据基础设施。接下来需要实施：

- **Phase 2**: 资产轮动策略实现
- **Phase 3**: 因子选股策略实现
- **Phase 4**: 对冲组合策略实现
- **Phase 5**: 整合优化和 MCP 工具实现

## 8. 架构合规性

所有模块严格遵循 AgomSaaS 四层架构：

- ✅ Domain 层: 无外部依赖（no pandas, numpy, django）
- ✅ Application 层: 用例编排，通过依赖注入使用 Infrastructure
- ✅ Infrastructure 层: ORM 模型和适配器
- ✅ Interface 层: DRF 视图和序列化器
- ✅ 所有数据通过数据库初始化脚本加载，无硬编码
