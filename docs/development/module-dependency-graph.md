# AgomSAAF 模块依赖关系图

> **文档版本**: V1.5
> **生成日期**: 2026-02-01
> **更新日期**: 2026-03-11
> **系统版本**: AgomSAAF V3.4
> **项目状态**: 生产就绪

## 概述

AgomSAAF 当前包含 27 个业务模块和 1 个共享技术组件 (`shared/`)。本文档描述模块间依赖关系，确保架构清晰、依赖方向正确。根据 2026-02-20 的代码扫描，所有模块均具备完整四层目录。

**自动校验状态（2026-02-20）**
- `python manage.py check`: 通过
- 业务模块：27（`apps/`，排除 `shared`/`__pycache__`）
- 四层目录完整性：27/27 ✅
- 测试规模：1,529 项（2026-02-20，`pytest --collect-only`）

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

### P2 (低优先级)
- 收益趋势图历史数据存储（当前返回空列表）
- Celery 任务监控 Flower 集成

## 变更记录

| 日期 | 变更内容 |
|------|---------|
| 2026-03-11 | V1.5 - 补充 Adapter 模式文档，修复 EventSubscriberRegistry 重复注册风险 |
| 2026-03-11 | V1.4 - 架构技术债最小治理：解耦 macro-regime、strategy-simulated_trading、events-业务模块、dashboard 聚合 |
| 2026-02-20 | V1.3 - 架构合规性修复：删除 apps/shared/，修复 shared 对 apps 的违规依赖 |
| 2026-02-01 | V1.1 - 审计和仪表盘模块完成，项目完成度 100% |
| 2026-02-01 | 创建文档，基于代码库审核结果 |
