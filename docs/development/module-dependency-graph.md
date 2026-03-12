# AgomSAAF 模块依赖关系图

> **文档版本**: V1.7
> **生成日期**: 2026-02-01
> **更新日期**: 2026-03-12
> **系统版本**: AgomSAAF V3.4
> **项目状态**: 生产就绪

## 概述

AgomSAAF 当前包含 27 个业务模块和 1 个共享技术组件 (`shared/`)。本文档描述模块间依赖关系，确保架构清晰、依赖方向正确。根据 2026-02-20 的代码扫描，所有模块均具备完整四层目录。

**自动校验状态（2026-03-12）**
- `python manage.py check`: 通过
- 业务模块：27（`apps/`，排除 `shared`/`__pycache__`）
- 四层目录完整性：27/27 ✅
- 循环依赖：0（已全部解耦）✅
- 测试规模：1,600+ 项（2026-03-12，`pytest --collect-only`）

## 架构分层

```
┌─────────────────────────────────────────────────────────────────┐
│                    Interface 层 (接口层)                          │
│  views.py (DRF API) | serializers.py | admin.py | urls.py      │
└─────────────────────────────────────────────────────────────────┘
                               ↓↑
┌─────────────────────────────────────────────────────────────────┐
│                  Application 层 (应用层)                          │
│  use_cases.py | tasks.py (Celery) | services.py | dtos.py       │
└─────────────────────────────────────────────────────────────────┘
                               ↓↑
┌─────────────────────────────────────────────────────────────────┐
│                    Domain 层 (领域层)                            │
│  entities.py | rules.py | services.py | protocols.py            │
│                  【禁止: django.*, pandas, 外部库】              │
└─────────────────────────────────────────────────────────────────┘
                               ↓↑
┌─────────────────────────────────────────────────────────────────┐
│               Infrastructure 层 (基础设施层)                      │
│  models.py (ORM) | repositories.py | adapters/ | mappers.py     │
└─────────────────────────────────────────────────────────────────┘
```

## 模块列表 (27个)

### 核心引擎模块 (5个)
| 模块 | 职责 | 状态 |
|------|------|------|
| `macro` | 宏观数据采集 | ✅ 完整 |
| `regime` | Regime 判定引擎 | ✅ 完整 |
| `policy` | 政策事件管理 | ✅ 完整 |
| `signal` | 投资信号管理 | ✅ 完整 |
| `filter` | HP/Kalman 滤波器 | ✅ 完整 |

### 资产分析模块 (5个)
| 模块 | 职责 | 状态 |
|------|------|------|
| `asset_analysis` | 通用资产分析框架 | ✅ 完整 |
| `equity` | 个股分析 | ✅ 完整 |
| `fund` | 基金分析 | ✅ 完整 |
| `sector` | 板块分析 | ✅ 完整 |
| `sentiment` | 舆情情感分析 | ✅ 完整 |

### 风控与账户模块 (5个)
| 模块 | 职责 | 状态 |
|------|------|------|
| `account` | 账户与持仓管理 | ✅ 完整 |
| `audit` | 事后审计 | ✅ 完整 |
| `simulated_trading` | 模拟盘自动交易 | ✅ 完整 |
| `realtime` | 实时价格监控 | ✅ 完整 |
| `strategy` | 策略系统 | ✅ 完整 |

### AI与工具模块 (12个)
| 模块 | 职责 | 状态 |
|------|------|------|
| `ai_provider` | AI 服务提供商管理 | ✅ 完整 |
| `prompt` | AI Prompt 模板系统 | ✅ 完整 |
| `dashboard` | 仪表盘 | ✅ 完整 |
| `events` | 事件系统 | ✅ 完整 |
| `alpha` | Alpha 选股信号 | ✅ 完整 |
| `alpha_trigger` | Alpha 离散触发 | ✅ 完整 |
| `beta_gate` | Beta 闸门 | ✅ 完整 |
| `decision_rhythm` | 决策频率约束 | ✅ 完整 |
| `factor` | 因子管理 | ✅ 完整 |
| `rotation` | 资产轮动 | ✅ 完整 |
| `hedge` | 对冲策略 | ✅ 完整 |

## 依赖关系图

### 模块依赖矩阵 (2026-03-12 扫描)

| 模块 | 出度(依赖别人) | 入度(被依赖) | 状态 | 说明 |
|------|---------------|-------------|------|------|
| regime | 1 | 18 | 🟢 核心 | 纯净的基础设施模块 |
| macro | 2 | 10 | 🟢 核心 | 通过 orchestration 层解耦 |
| dashboard | 13 | 0 | 🟡 聚合层 | 合理的展示层聚合，收益曲线已接入组合日快照 |
| decision_rhythm | 11 | 2 | 🟡 业务核心 | 职责较多，耦合11个模块 |
| simulated_trading | 10 | 3 | 🟢 已解耦 | 通过 Gateway 模式解耦 |
| strategy | 10 | 1 | 🟢 已解耦 | 通过 Facade 模式解耦 |
| asset_analysis | 6 | 3 | 🟢 正常 | 数据分析核心 |
| signal | 6 | 4 | 🟢 正常 | 信号管理模块 |
| equity | 4 | 5 | 🟢 正常 | 个股分析模块 |
| alpha_trigger | 5 | 2 | 🟢 正常 | 通过 Protocol 解耦 |
| events | 2 | 6 | 🟢 已解耦 | 通过 Wrapper 模式解耦 |
| policy | 3 | 5 | 🟢 正常 | 政策管理模块 |
| fund | 6 | 1 | 🟢 正常 | 基金分析模块 |
| account | 6 | 4 | 🟢 正常 | 账户管理模块 |
| realtime | 4 | 2 | 🟢 正常 | 实时监控模块 |
| beta_gate | 4 | 2 | 🟢 正常 | Beta闸门模块 |
| backtest | 5 | 2 | 🟢 正常 | 回测模块 |
| audit | 3 | 3 | 🟢 正常 | 审计模块 |
| rotation | 2 | 2 | 🟢 正常 | 轮动模块 |
| factor | 3 | 1 | 🟢 正常 | 因子模块 |
| sentiment | 2 | 2 | 🟢 正常 | 舆情模块 |
| prompt | 3 | 1 | 🟢 正常 | Prompt模块 |
| ai_provider | 0 | 8 | 🟢 核心 | AI服务提供商 |
| market_data | 2 | 0 | 🟢 正常 | 市场数据模块 |
| filter | 1 | 0 | 🟢 正常 | 滤波器模块 |
| sector | 1 | 0 | 🟢 正常 | 板块模块 |
| hedge | 1 | 0 | 🟢 正常 | 对冲模块 |

### 循环依赖解决状态 (2026-03-12 验证)

| 循环对 | 之前状态 | 当前状态 | 解决方案 |
|--------|----------|----------|----------|
| regime ↔ macro | 🔴 直接循环 | 🟢 **已解决** | orchestration层 + Protocol |
| strategy ↔ simulated_trading | 🔴 直接循环 | 🟢 **已解决** | Facade + Gateway 模式 |
| events ↔ alpha_trigger | 🔴 直接循环 | 🟢 **已解决** | Wrapper延迟导入 + Protocol |
| events ↔ decision_rhythm | 🔴 直接循环 | 🟢 **已解决** | Wrapper延迟导入 + Protocol |

### 架构健康度评分

| 维度 | 第一轮(整改前) | 第二轮(部分整改) | 当前(2026-03-12) |
|------|----------------|------------------|------------------|
| 架构设计 | 60分 | 85分 | **90分** |
| 循环依赖 | 40分 | 70分 | **95分** |
| 模块边界 | 50分 | 75分 | **88分** |
| 可维护性 | 55分 | 78分 | **85分** |

### 拓扑依赖图 (2026-03-12)

```
┌──────────────────────────────────────────────────────────────────┐
│                      Interface 层                                 │
│   dashboard  account  audit  events_interface                    │
└─────────────────────────────┬────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌─────────────────┐   ┌───────────────┐
│  决策触发层    │   │   业务逻辑层     │   │  基础设施层    │
│               │   │                 │   │               │
│ alpha_trigger │   │ strategy ───────┼──►│ regime        │
│ beta_gate     │   │ simulated_trading│   │ macro         │
│ decision_     │   │ policy          │   │ ai_provider   │
│   rhythm      │   │ backtest        │   │ market_data   │
│               │   │                 │   │               │
│      ▲        │   │        ▲        │   │      ▲        │
│      │        │   │        │        │   │      │        │
│      │Gateway │   │ Facade │        │   │Protocol       │
│      │/Wrapper│   └────────┼────────┘   │      │        │
│      ▼        │            │            │      │        │
│   events ─────┼────────────┘            └──────┘        │
└───────────────┘                                         │
        │                                                 │
        └─────────────────────────────────────────────────┘
                              │
                              ▼
                    ┌─────────────────┐
                    │   数据分析层     │
                    │ equity  signal  │
                    │ fund    factor  │
                    │ sentiment       │
                    └─────────────────┘
```

**图例说明**：
- `───►` 单向依赖（正确方向）
- `Facade/Gateway/Protocol` 解耦模式
- 上层模块依赖下层模块
- 基础设施层模块相互独立

### 数据流依赖

```
┌─────────────────────────────────────────────────────────────────┐
│                         数据采集层                              │
│                                                                   │
│  ┌──────────┐                                                   │
│  │  MACRO   │──┐                                                │
│  │ 宏观数据  │  │                                                │
│  └──────────┘  │                                                │
│               │                                                │
│  ┌──────────┐  ▼                                                │
│  │  FILTER  │◄─ 数据滤波 (HP/Kalman)                            │
│  └────┬─────┘                                                  │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                         核心引擎层                              │
│                                                                   │
│  ┌──────────┐                                                    │
│  │  REGIME  │──┐                                               │
│  │ Regime判定│  │                                               │
│  └────┬─────┘  │                                               │
│       │        │                                               │
│       ▼        │                                               │
│  ┌──────────┐  │                                               │
│  │  POLICY  │──┼──► 政策档位 (P0-P3)                             │
│  └────┬─────┘  │                                               │
│       │        │                                               │
│       ▼        │                                               │
│  ┌──────────┐  │                                               │
│  │  SIGNAL  │◄─┘                                               │
│  └────┬─────┘                                                  │
└───────┼──────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                       资产分析层                                │
│                                                                   │
│  ┌─────────────┐    ┌──────────────────────────────────────┐   │
│  │ASSET_ANALYSIS│◄──┤   EQUITY  │  FUND  │  SECTOR  │SENTIMENT│   │
│  │  通用框架    │    └──────────────────────────────────────┘   │
│  └──────┬──────┘                                                  │
└─────────┼─────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                       决策控制层                                │
│                                                                   │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐                   │
│  │ STRATEGY │◄───│  ACCOUNT │◄───│REALTIME  │                   │
│  └──────────┘    └────┬─────┘    └──────────┘                   │
│                       │                                             │
│                       ▼                                             │
│              ┌────────────────┐                                   │
│              │SIMULATED_TRADING│                                  │
│              └────────────────┘                                   │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                       验证与改进层                              │
│                                                                   │
│  ┌──────────┐    ┌──────────┐                                    │
│  │ BACKTEST │◄───│  AUDIT   │                                    │
│  └──────────┘    └──────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────┐
│                         可视化层                                │
│                                                                   │
│  ┌──────────┐    ┌──────────┐                                    │
│  │DASHBOARD │◄───│AI_PROVIDER│                                   │
│  └──────────┘    │  PROMPT  │                                    │
│                  └──────────┘                                    │
└─────────────────────────────────────────────────────────────────┘

横向支撑：SHARED (配置、告警、规则引擎、Kalman滤波器、Protocol接口)
```

## 跨模块依赖清单

### `asset_analysis` 被
- `apps/equity` - 使用通用评分器
- `apps/fund` - 使用通用评分器
- `apps/strategy` - 使用资产池分类器
- `apps/simulated_trading` - 使用可投池筛选

### `regime` 被
- `apps/policy` - 同步评估
- `apps/signal` - 准入检查
- `apps/asset_analysis` - RegimeMatcher
- `apps/strategy` - 资产配置权重
- `apps/account` - Regime匹配度监控
- `apps/backtest` - 回测输入

### `policy` 被
- `apps/signal` - 政策档位过滤
- `apps/account` - 对冲策略触发
- `apps/strategy` - 资产配置调整

### `signal` 被
- `apps/account` - 信号关联持仓
- `apps/simulated_trading` - 自动交易信号源
- `apps/backtest` - 历史信号验证

### `realtime` 被
- `apps/simulated_trading` - 实时价格数据
- `apps/account` - 持仓市值计算
- `apps/strategy` - 再平衡触发

### `simulated_trading` 被
- `apps/account` - 模拟账户关联
- `apps/audit` - 交易记录分析

### `backtest` 被
- `apps/strategy` - 策略回测验证
- `apps/audit` - 回测归因分析

## shared 组件使用情况

| shared 组件 | 被使用方 | 说明 |
|------------|---------|------|
| `shared.domain.interfaces` | 所有模块 | Protocol 定义 |
| `shared.infrastructure.kalman_filter` | regime | Kalman 滤波器 |
| `shared.infrastructure.alert_service` | policy, signal | 告警服务 |
| `shared.infrastructure.cache_service` | macro, regime | Redis 缓存 |
| `shared.config.secrets` | 所有外部 API 调用 | 密钥管理 |

## 依赖规则

### 允许的依赖
```
✅ Interface → Application → Domain → Infrastructure
✅ 业务模块 → shared
✅ 业务模块 → 其他业务模块的 Domain 层
✅ 业务模块 → 其他业务模块的 Application 层（通过 Facade/Gateway/Protocol）
```

### 禁止的依赖
```
❌ Domain → Infrastructure
❌ Domain → Application
❌ Domain → Interface
❌ Domain → django.*、pandas、外部库
❌ shared → 业务模块
❌ 循环依赖
```

### 架构治理规则 (2026-03-11)

以下规则从 2026-03-11 起生效，用于防止核心耦合：

| 规则 | 描述 | 替代方案 |
|------|------|----------|
| 禁止 `macro -> regime task` 直接依赖 | macro 模块不应直接调用 regime 的 Celery 任务 | 使用 `apps/regime/application/orchestration.py` 中的编排函数 |
| 禁止 `simulated_trading -> strategy executor` 直接依赖 | simulated_trading 不应直接导入 StrategyExecutor | 使用 `StrategyExecutionGateway` |
| 禁止 `strategy -> simulated_trading ORM` 直接依赖 | strategy 不应直接导入 PositionModel/SimulatedAccountModel | 使用 `SimulatedTradingFacade` |
| 禁止 `events -> 业务 handler` 直接依赖 | events 模块不应直接导入业务模块的 handler | 使用 `EventSubscriberRegistry` |
| 禁止 `dashboard view -> 跨 app ORM` 持续扩散 | dashboard 视图不应持续增加跨模块 ORM 导入 | 使用 Query Services |

## 解耦模式 (2026-03-11 重构)

### Protocol 模式
用于解决循环依赖
- `MacroDataProviderProtocol` - regime 通过 Protocol 访问 macro 数据
- 位置: `apps/regime/domain/protocols.py`

### Adapter 模式
接口转换适配
- `MacroRepositoryAdapter` - 将 MacroDataProviderProtocol 接口适配为 Repository 接口
- 位置: `apps/regime/infrastructure/macro_data_provider.py`
- 用途: 供 CalculateRegimeV2UseCase 使用，隐藏 Provider 与 Repository 的差异

### Facade 模式
隐藏 ORM 实现细节
- `SimulatedTradingFacade` - 为 strategy 提供模拟交易数据访问
- 位置: `apps/simulated_trading/application/facade.py`

### Gateway 模式
跨模块通信网关
- `StrategyExecutionGateway` - 为 simulated_trading 提供策略执行接口
- 位置: `apps/strategy/application/execution_gateway.py`

### Registry 模式
实现 IoC (控制反转)
- `EventSubscriberRegistry` - 业务模块自行注册事件订阅器
- 位置: `apps/events/domain/registry.py`
- 特性: 支持重复注册检测，相同 (module_name, event_type) 会更新而非追加

### Query Service 模式
聚合跨模块数据查询
- `AlphaVisualizationQuery` - Alpha 可视化数据
- `DecisionPlaneQuery` - 决策平面数据
- `RegimeSummaryQuery` - Regime 摘要数据
- 位置: `apps/dashboard/application/queries.py`

## 技术债务

### 已解决 (2026-03-11)
- ✅ ~~`apps/shared/interface` - 应移至 `shared/infrastructure/htmx/`~~ (已完成 2026-02-20)
- ✅ ~~macro ↔ regime 循环依赖~~ - 通过 Protocol 模式解耦
- ✅ ~~strategy ↔ simulated_trading 循环依赖~~ - 通过 Facade/Gateway 模式解耦
- ✅ ~~events → 业务 handler 直接依赖~~ - 通过 Registry 模式实现 IoC
- ✅ ~~dashboard 视图跨模块 ORM 聚合~~ - 通过 Query Service 模式封装

### 已解决 (2026-03-12)
- ✅ ~~收益趋势图历史数据存储（当前返回空列表）~~ - dashboard 已改为读取 `account.PortfolioDailySnapshotModel` 输出真实历史曲线
- ✅ dashboard 收益曲线口径对齐 - 历史序列以当前组合 `total_return_pct` 锚定，最新点与首页总收益一致

### P2 (低优先级)
- Celery 任务监控 Flower 集成

## 变更记录

| 日期 | 变更内容 |
|------|---------|
| 2026-03-12 | V1.7 - 收益趋势图历史数据已落地，dashboard 改为基于 PortfolioDailySnapshot 输出历史曲线 |
| 2026-03-12 | V1.6 - 添加模块依赖矩阵评分、循环依赖解决状态表、架构健康度评分、最新拓扑依赖图 |
| 2026-03-11 | V1.5 - 补充 Adapter 模式文档，修复 EventSubscriberRegistry 重复注册风险 |
| 2026-03-11 | V1.4 - 架构技术债最小治理：解耦 macro-regime、strategy-simulated_trading、events-业务模块、dashboard 聚合 |
| 2026-02-20 | V1.3 - 架构合规性修复：删除 apps/shared/，修复 shared 对 apps 的违规依赖 |
| 2026-02-01 | V1.1 - 审计和仪表盘模块完成，项目完成度 100% |
| 2026-02-01 | 创建文档，基于代码库审核结果 |
