# AgomSAAF 模块依赖关系文档

> **版本**: V1.0
> **生成日期**: 2026-03-18
> **模块总数**: 32个

---

## 1. 模块依赖拓扑图

### 1.1 分层架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    第一层：基础设施层 (Infrastructure)                    │
│                    (只被依赖，无跨模块依赖)                               │
├─────────────────────────────────────────────────────────────────────────┤
│  ai_provider    events    macro    regime                               │
│  (AI服务商)     (事件)    (宏观)   (象限判定)                            │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    第二层：核心业务层 (Core Business)                     │
├─────────────────────────────────────────────────────────────────────────┤
│  signal ─────────────────→ regime                                      │
│  policy ─────────────────→ ai_provider                                 │
│  sentiment ──────────────→ ai_provider                                 │
│  filter ─────────────────→ macro                                       │
│  alpha_trigger ──────────→ events                                      │
│  beta_gate ──────────────→ events                                      │
│  factor (独立)                                                          │
│  hedge (独立)                                                           │
│  rotation (独立)                                                        │
│  sector (独立)                                                          │
│  alpha (独立)                                                           │
│  agent_runtime (独立)                                                   │
│  task_monitor (独立)                                                    │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    第三层：资产分析层 (Asset Analysis)                    │
├─────────────────────────────────────────────────────────────────────────┤
│  equity ──────────→ asset_analysis                                     │
│  fund ────────────→ asset_analysis                                     │
│  asset_analysis ──→ regime, policy, sentiment, signal                  │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    第四层：应用集成层 (Application Integration)           │
├─────────────────────────────────────────────────────────────────────────┤
│  backtest ──────────→ equity                                           │
│  audit ─────────────→ backtest, macro, regime                          │
│  dashboard ─────────→ account, regime, signal                          │
│  prompt ─────────────→ ai_provider, macro, regime                      │
│  realtime ──────────→ regime, simulated_trading                        │
│  market_data ───────→ realtime                                         │
│  terminal ──────────→ prompt                                           │
│  strategy ──────────→ account, ai_provider, prompt                     │
│  decision_rhythm ───→ alpha_trigger, events, regime                    │
│  share ─────────────→ decision_rhythm, simulated_trading               │
└─────────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────────┐
│                    第五层：顶层聚合层 (Top Aggregation)                   │
├─────────────────────────────────────────────────────────────────────────┤
│  simulated_trading ──→ ai_provider, asset_analysis, policy,            │
│                        prompt, regime, signal, strategy (7个)           │
│                                                                         │
│  account ───────────→ audit, backtest, decision_rhythm, equity,        │
│                        events, factor, hedge, macro, prompt, regime,    │
│                        rotation, signal, simulated_trading,             │
│                        strategy (14个)                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 依赖方向图

```
                    ┌─────────────┐
                    │   shared/   │
                    └──────┬──────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           基础设施层                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ai_provider│ │  events  │ │  macro   │ │  regime  │                    │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘                    │
└──────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           核心业务层                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │  signal  │ │  policy  │ │sentiment │ │  filter  │ │alpha_trig│       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │beta_gate │ │  factor  │ │  hedge   │ │ rotation │ │  sector  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                                 │
│  │  alpha   │ │agent_run │ │task_mon  │                                 │
│  └──────────┘ └──────────┘ └──────────┘                                 │
└──────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           资产分析层                                      │
│  ┌──────────────────────────────────────────────────────────────┐       │
│  │                     asset_analysis                            │       │
│  └──────────────────────────────────────────────────────────────┘       │
│                           ▲           ▲                                 │
│  ┌──────────┐             │           │             ┌──────────┐        │
│  │  equity  │─────────────┘           └─────────────│   fund   │        │
│  └──────────┘                                         └──────────┘        │
└──────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           应用集成层                                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ backtest │ │  audit   │ │dashboard │ │  prompt  │ │ realtime │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │market_dt │ │ terminal │ │ strategy │ │decision_r│ │  share   │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                           顶层聚合层                                      │
│  ┌────────────────────────────┐  ┌────────────────────────────┐         │
│  │     simulated_trading      │  │         account            │         │
│  │       (7 依赖)             │  │       (14 依赖)            │         │
│  └────────────────────────────┘  └────────────────────────────┘         │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 详细依赖关系表

### 2.1 按模块列出依赖

| 模块 | 依赖数量 | 依赖的模块 |
|------|---------|-----------|
| **account** | 14 | audit, backtest, decision_rhythm, equity, events, factor, hedge, macro, prompt, regime, rotation, signal, simulated_trading, strategy |
| **simulated_trading** | 7 | ai_provider, asset_analysis, policy, prompt, regime, signal, strategy |
| **decision_rhythm** | 3 | alpha_trigger, events, regime |
| **audit** | 3 | backtest, macro, regime |
| **dashboard** | 3 | account, regime, signal |
| **strategy** | 3 | account, ai_provider, prompt |
| **asset_analysis** | 4 | equity, fund, policy, regime, sentiment, signal |
| **share** | 2 | decision_rhythm, simulated_trading |
| **prompt** | 3 | ai_provider, macro, regime |
| **realtime** | 2 | regime, simulated_trading |
| **backtest** | 1 | equity |
| **equity** | 1 | asset_analysis |
| **fund** | 1 | asset_analysis |
| **signal** | 1 | regime |
| **policy** | 1 | ai_provider |
| **sentiment** | 1 | ai_provider |
| **filter** | 1 | macro |
| **alpha_trigger** | 1 | events |
| **beta_gate** | 1 | events |
| **market_data** | 1 | realtime |
| **terminal** | 1 | prompt |
| **ai_provider** | 0 | - |
| **events** | 0 | - |
| **macro** | 0 | - |
| **regime** | 0 | - |
| **alpha** | 0 | - |
| **factor** | 0 | - |
| **hedge** | 0 | - |
| **rotation** | 0 | - |
| **sector** | 0 | - |
| **agent_runtime** | 0 | - |
| **task_monitor** | 0 | - |

### 2.2 按被依赖次数排序

| 模块 | 被依赖次数 | 被哪些模块依赖 |
|------|-----------|---------------|
| **regime** | 10 | account, asset_analysis, audit, dashboard, decision_rhythm, prompt, realtime, simulated_trading, signal, strategy |
| **ai_provider** | 4 | policy, prompt, sentiment, simulated_trading, strategy |
| **events** | 3 | account, alpha_trigger, beta_gate, decision_rhythm |
| **macro** | 3 | account, audit, filter, prompt |
| **signal** | 3 | account, asset_analysis, dashboard, simulated_trading |
| **asset_analysis** | 3 | equity, fund, simulated_trading |
| **policy** | 2 | asset_analysis, simulated_trading |
| **prompt** | 2 | account, simulated_trading, strategy, terminal |
| **backtest** | 2 | account, audit |
| **equity** | 2 | account, backtest |
| **simulated_trading** | 2 | account, realtime, share |
| **decision_rhythm** | 2 | account, share |
| **sentiment** | 1 | asset_analysis |
| **alpha_trigger** | 1 | decision_rhythm |
| **account** | 1 | dashboard, strategy |
| **realtime** | 1 | market_data |
| **strategy** | 1 | account, simulated_trading |
| **alpha** | 0 | - |
| **factor** | 0 | - |
| **hedge** | 0 | - |
| **rotation** | 0 | - |
| **sector** | 0 | - |
| **beta_gate** | 0 | - |
| **filter** | 0 | - |
| **terminal** | 0 | - |
| **agent_runtime** | 0 | - |
| **task_monitor** | 0 | - |
| **audit** | 0 | - |
| **dashboard** | 0 | - |
| **market_data** | 0 | - |
| **share** | 0 | - |
| **fund** | 0 | - |

---

## 3. 模块分层详解

### 3.1 第一层：基础设施层 (4个模块)

这些模块是系统的基石，被广泛依赖，但不依赖其他业务模块。

| 模块 | 职责 | 被依赖次数 |
|------|------|-----------|
| `regime` | 宏观象限判定引擎 | 10 |
| `ai_provider` | AI 服务商管理 | 5 |
| `events` | 事件发布与订阅 | 4 |
| `macro` | 宏观数据采集 | 4 |

**特点**：
- 高稳定性要求
- 接口变更影响面大
- 应保持向后兼容

### 3.2 第二层：核心业务层 (13个模块)

依赖基础设施层，提供核心业务能力。

| 模块 | 依赖 | 职责 |
|------|------|------|
| `signal` | regime | 投资信号管理 |
| `policy` | ai_provider | 政策事件管理 |
| `sentiment` | ai_provider | 舆情分析 |
| `filter` | macro | 滤波器 |
| `alpha_trigger` | events | Alpha 离散触发 |
| `beta_gate` | events | Beta 闸门 |
| `alpha` | - | AI 选股 (Qlib) |
| `factor` | - | 因子管理 |
| `hedge` | - | 对冲策略 |
| `rotation` | - | 板块轮动 |
| `sector` | - | 板块分析 |
| `agent_runtime` | - | Agent 运行时 |
| `task_monitor` | - | 任务监控 |

### 3.3 第三层：资产分析层 (3个模块)

资产评分与筛选相关模块。

| 模块 | 依赖 | 职责 |
|------|------|------|
| `asset_analysis` | regime, policy, sentiment, signal | 通用资产分析框架 |
| `equity` | asset_analysis | 个股分析 |
| `fund` | asset_analysis | 基金分析 |

**注意**：存在潜在的循环依赖风险：
- `equity → asset_analysis → equity`（通过依赖注入解决）
- `fund → asset_analysis → fund`（通过依赖注入解决）

### 3.4 第四层：应用集成层 (10个模块)

整合多个模块能力，提供完整业务流程。

| 模块 | 依赖数 | 依赖 |
|------|--------|------|
| `backtest` | 1 | equity |
| `audit` | 3 | backtest, macro, regime |
| `dashboard` | 3 | account, regime, signal |
| `prompt` | 3 | ai_provider, macro, regime |
| `realtime` | 2 | regime, simulated_trading |
| `market_data` | 1 | realtime |
| `terminal` | 1 | prompt |
| `strategy` | 3 | account, ai_provider, prompt |
| `decision_rhythm` | 3 | alpha_trigger, events, regime |
| `share` | 2 | decision_rhythm, simulated_trading |

### 3.5 第五层：顶层聚合层 (2个模块)

系统最复杂的模块，依赖大量其他模块。

| 模块 | 依赖数 | 依赖 |
|------|--------|------|
| `simulated_trading` | 7 | ai_provider, asset_analysis, policy, prompt, regime, signal, strategy |
| `account` | 14 | audit, backtest, decision_rhythm, equity, events, factor, hedge, macro, prompt, regime, rotation, signal, simulated_trading, strategy |

---

## 4. 问题分析

### 4.1 🔴 高风险：account 模块过重

**问题描述**：
- `account` 模块依赖 **14 个**其他模块
- 职责过多，违反单一职责原则
- 变更影响面大，测试困难

**建议拆分方案**：

```
account (当前)
    ↓ 拆分为
├── user/           # 用户管理 (依赖: 0)
├── portfolio/      # 投资组合管理 (依赖: regime, signal, strategy)
├── position/       # 持仓管理 (依赖: portfolio, realtime)
└── capital/        # 资金管理 (依赖: portfolio, simulated_trading)
```

**拆分后预期依赖数**：
- `user`: 0
- `portfolio`: 3-4
- `position`: 2-3
- `capital`: 2-3

### 4.2 🟠 中风险：simulated_trading 依赖过多

**问题描述**：
- 依赖 **7 个**模块
- 耦合度高，难以独立测试和部署

**建议**：
1. 引入 **Facade 模式**，封装复杂依赖
2. 通过 **事件驱动** 解耦，减少直接依赖
3. 提取公共接口到 Domain 层

```python
# 引入 Facade 示例
class TradingFacade:
    def __init__(self, 
                 regime_service: RegimeService,
                 signal_service: SignalService,
                 policy_service: PolicyService):
        self._regime = regime_service
        self._signal = signal_service
        self._policy = policy_service
    
    def execute_trade(self, signal_id: str) -> TradeResult:
        # 封装复杂逻辑
        pass
```

### 4.3 🟡 低风险：asset_analysis 双向依赖

**问题描述**：
- `equity → asset_analysis`
- `asset_analysis → equity`（通过依赖注入）

**当前状态**：已通过 Protocol 接口解耦

**验证点**：
- ✅ 无编译时循环依赖
- ✅ 通过依赖注入实现运行时绑定
- ⚠️ 需要在文档中明确说明

### 4.4 ✅ 良好实践：事件驱动解耦

以下模块通过 `events` 系统实现松耦合：

| 发布者 | 事件类型 | 订阅者 |
|--------|---------|--------|
| regime | REGIME_CHANGED | alpha_trigger, beta_gate, decision_rhythm |
| policy | POLICY_CHANGED | beta_gate, decision_rhythm |
| signal | SIGNAL_TRIGGERED | simulated_trading |

---

## 5. 改进建议

### 5.1 短期改进 (1-2 周)

1. **完善本文档**
   - 添加接口依赖（Protocol 依赖）
   - 添加数据流依赖
   - 定期自动更新

2. **添加架构守护测试**
   ```python
   # tests/architecture/test_dependencies.py
   def test_account_should_not_import_backtest():
       """account 模块不应直接导入 backtest 模块"""
       assert not has_import("apps.account", "apps.backtest")
   ```

### 5.2 中期改进 (1-2 月)

1. **拆分 account 模块**
   - 评估拆分影响
   - 逐步迁移
   - 更新所有引用

2. **重构 simulated_trading**
   - 引入 Facade 模式
   - 减少直接依赖
   - 提升可测试性

### 5.3 长期改进 (持续)

1. **建立依赖监控**
   - CI 中检查依赖变化
   - 依赖数超阈值告警
   - 定期架构评审

2. **文档同步机制**
   - 代码变更自动更新文档
   - 架构决策记录 (ADR)

---

## 6. 依赖规则总结

### 6.1 允许的依赖方向

```
✅ 上层 → 下层 (第五层 → 第四层 → 第三层 → 第二层 → 第一层)
✅ 同层模块 → 同层模块
✅ 任何模块 → shared/
✅ 任何模块 → core/
```

### 6.2 禁止的依赖方向

```
❌ 下层 → 上层 (第一层 → 第二层 → ...)
❌ shared/ → apps/
❌ 循环依赖 (A → B → A)
```

### 6.3 依赖数量阈值

| 层级 | 建议依赖数上限 | 当前最大 | 状态 |
|------|---------------|---------|------|
| 基础设施层 | 0 | 0 | ✅ |
| 核心业务层 | 2 | 1 | ✅ |
| 资产分析层 | 4 | 4 | ⚠️ |
| 应用集成层 | 5 | 3 | ✅ |
| 顶层聚合层 | 5 | 14 | 🔴 |

---

## 附录：完整依赖矩阵

```
                 依赖方 (行) → 被依赖方 (列)
                 
               a  a  a  b  d  e  f  m  p  r  s  s  s  t
               c  s  u  a  e  q  i  a  o  e  i  i  t  a
               c  s  d  c  c  u  l  c  l  g  g  m  r  s
               o  e  i  k  i  i  t  r  i  i  n  u  a  k
               u  t  t  t  s  t  e  o  c  m  a  l  t  _
               n     .  e  i  y     .  y  e  l  a  e  m
               t     .  s  o        .     .     t  g  o
                     .  t  n        .           .  d n
                     .  .           .           .  . i
                     .  .           .           .  . t
                     .  .           .           .  . o
                     .  .           .           .  . r
                     .  .           .           .  . i
                     .  .           .           .  . n
                     .  .           .           .  . g
─────────────────────────────────────────────────────
account         -  .  .  X  X  X  X  X  X  X  X  X  X  X
asset_analysis  .  -  .  .  .  .  .  .  .  .  .  X  .  .
audit           .  .  -  X  .  .  .  X  X  .  .  .  .  .
backtest        .  .  .  -  .  .  X  .  .  .  .  .  .  .
decision_rhythm .  X  .  .  -  X  .  .  .  .  X  .  .  .
equity          .  X  .  .  .  -  .  .  .  .  .  .  .  .
fund            .  X  .  .  .  .  -  .  .  .  .  .  .  .
macro           .  .  .  .  .  .  .  -  .  .  .  .  .  .
policy          .  .  .  .  .  .  .  .  -  .  .  .  .  .
regime          .  .  .  .  .  .  .  .  .  -  .  .  .  .
signal          .  .  .  .  .  .  .  .  .  X  -  .  .  .
simulated_trading X X . . . . . . X . X X - .
strategy        X  .  .  .  .  .  .  .  X  .  .  .  -  .

图例：
  X = 依赖
  . = 不依赖
  - = 自身

注：仅显示有依赖的模块，完整矩阵包含 32x32 = 1024 个格子
```

---

**文档维护**: AgomSAAF Team
**最后更新**: 2026-03-18
**文档版本**: V1.0
