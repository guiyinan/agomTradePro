# AgomTradePro 系统重新设计：Regime Navigator + Pulse 分层架构

> **日期**: 2026-03-23
> **版本**: 1.0
> **状态**: 已实施并验收收口
> **涉及模块**: regime, pulse(新), dashboard, decision, rotation, beta_gate
> **预估周期**: Phase 1 (5-6周) + Phase 2 (4-5周) + Phase 3 (3-4周)

---

## 1. 问题陈述

### 1.1 当前系统两个根本性问题

**问题一：前端缺乏主线**

系统有 34 个业务模块平铺暴露于导航栏，用户打开系统后面对大量下拉菜单和功能入口，无法理解系统的设计框架，不知从何下手。Dashboard 模板 86KB，Decision Workspace 模板 84KB，信息密度过高，缺乏工作流引导。

**问题二：Regime 宏观窗口太宽**

Regime 基于 PMI + CPI 月频数据，判定增长/通胀四象限（复苏/过热/滞胀/通缩）。一个 regime 状态可能持续 6-18 个月，在此期间系统给不出差异化指引。PMI/CPI 作为滞后确认指标，当 regime 变化时市场已经 price in 了数月。用户每天打开系统看到相同的 regime 判定，系统缺乏"活力"。

**两个问题相互关联**：前端没有主线，部分原因是 regime 这个"系统灵魂"粒度太粗，无法驱动日常交互。Regime 一个季度不变，那用户每天打开系统看什么？

### 1.2 设计目标

1. 让用户每天打开系统都有**有价值的信息**可看，而不是静态不变的 regime 标签
2. 为系统建立清晰的**使用主线**：日常监控 + 投资决策
3. Regime 从"给标签"升级为"给导航"，联动具体行动建议
4. 在 regime 的月频锚点之上，增加**周频战术层**（Pulse），让系统有呼吸感

---

## 2. 设计共识

以下方向已与项目负责人确认。

### 2.1 前端主线：B+C 混合模式

**日常模式（B）— 90% 使用场景**

核心问题："今天我的持仓需要关注什么？"

- 打开就看到：待处理信号、持仓异常、regime/pulse 变化提醒
- 行动项驱动，没有待办就快速浏览退出
- Regime/Pulse 作为背景状态栏，影响信号权重和风险预算

**决策模式（C）— 10% 使用场景，最高价值**

核心问题："我要做一笔新决策，从哪开始？"

- 漏斗式引导：宏观环境 → 推荐方向 → 板块选择 → 推优筛选 → 审批执行 → 审计复盘
- 每一步都有 regime/pulse 提供的上下文和建议
- 从日常模式中的信号可一键进入决策模式
- 形成从执行到核算盈亏的大闭环（Brinson 归因）

**两种模式无缝切换** — 日常模式里看到信号，点进去进入决策漏斗。

### 2.2 Regime 定位：导航仪（不只是红绿灯）

当前 regime 输出太单薄（一个象限 + 一个概率分布）。作为导航仪，需要扩展输出：

| 输出维度 | 当前状态 | 目标 |
|---------|---------|------|
| 当前象限 | ✅ `RegimeCalculationResult.regime` | 保留 |
| 置信度/概率分布 | ✅ `RegimeCalculationResult.distribution` | 保留 |
| 移动方向 | ❌ 缺 | 稳定 / 正在向 X 象限移动 |
| 转折概率 | ❌ 缺 | 领先指标暗示的转换可能性 |
| 受益资产类别 | ❌ 缺 | 复苏→权益为主，滞胀→防御为主 |
| 推荐板块 | ⚠️ rotation 有但没联动 | 基于 regime 的板块偏好 |
| 风险预算 | ❌ 缺 | regime 决定的整体仓位上限 |
| 关注指标 | ❌ 缺 | "下一次转折看什么" |

### 2.3 Regime 节奏：分层架构

```
╔══════════════════════════════════════════════════╗
║  战略层（Regime）                                 ║
║  月频 | PMI + CPI | 4象限                        ║
║  "当前处于复苏期"                                 ║
║  提供：资产类别权重区间、大方向判断                 ║
╠══════════════════════════════════════════════════╣
║  战术层（Pulse 脉搏）                             ║
║  周频 | 利差/商品/流动性/情绪                      ║
║  "复苏偏弱，建议降低进攻性"                        ║
║  提供：regime 内强弱微调、转折预警                  ║
╠══════════════════════════════════════════════════╣
║  行动层（Action Recommendation）                  ║
║  Regime 权重区间 + Pulse 微调 → 具体配置          ║
║  "权益 55%  债券 30%  现金 15%"                   ║
║  提供：可执行的资产配置建议 + 风险预算              ║
╚══════════════════════════════════════════════════╝
```

- **Regime（月频）**：PMI + CPI 确认的大方向，变化慢但稳定，作为战略锚点
- **Pulse（周频）**：利差、商品指数、流动性、情绪等高频数据，在 regime 框架内做微调
- **Action**：Regime + Pulse 联合输出，转化为具体的资产配置建议和风险预算

---

## 3. Pulse 指标体系设计

### 3.1 四维度框架

Pulse 不是一个简单的综合分数，而是 4 个维度的仪表盘。用户一眼能看到：增长在转好、但流动性在收紧、通胀压力在上升。

```
Pulse 脉搏层
├── 增长脉搏 (Growth Pulse)
│   ├── CN_TERM_SPREAD_10Y2Y   利差              [已有, 日频, high_frequency_fetchers.py]
│   └── CN_NEW_CREDIT          信贷脉冲(变化率)   [已有, 月频, financial_fetchers.py]
│
├── 通胀脉搏 (Inflation Pulse)
│   ├── CN_NHCI                南华商品指数       [已有, 日频, high_frequency_fetchers.py]
│   └── (预留 PPI 高频代理)
│
├── 流动性脉搏 (Liquidity Pulse)
│   ├── CN_SHIBOR              银行间拆借利率     [已有, 日频, financial_fetchers.py]
│   ├── CN_CREDIT_SPREAD       信用利差           [已有, 日频, high_frequency_fetchers.py]
│   ├── CN_M2                  M2增速(变化率)     [已有, 月频, base_fetchers.py]
│   ├── DR007                  质押式回购利率     [Phase 2 新增]
│   └── 央行净投放              公开市场操作      [Phase 2 新增]
│
└── 情绪脉搏 (Sentiment Pulse)
    ├── VIX_INDEX              恐慌指数           [已有, 日频, high_frequency_fetchers.py]
    └── USD_INDEX              美元指数           [已有, 日频, high_frequency_fetchers.py]
```

### 3.2 指标信号判定逻辑

每个指标产出一个标准化信号：`bullish (+1)` / `neutral (0)` / `bearish (-1)`，外加信号强度 `0-1`。

| 指标 | Bullish 条件 | Bearish 条件 | 对 Regime 的含义 |
|------|-------------|-------------|-----------------|
| 利差(10Y-2Y) | > 100BP 且上升 | < 0BP (倒挂) | 利差收窄→衰退预警，扩大→增长预期改善 |
| 新增信贷 | 同比增速 > 10% | 同比增速 < 0% | 信贷扩张→经济回暖领先信号 |
| NHCI | 近4周上涨 > 5% | 近4周下跌 > 5% | 商品涨→通胀压力，跌→需求走弱 |
| SHIBOR(1M) | 低于均值1σ | 高于均值1σ | SHIBOR高→流动性紧，低→流动性松 |
| 信用利差 | 收窄趋势 | 走扩趋势 | 利差走扩→风险偏好下降 |
| M2增速 | 增速加快 | 增速放缓 | M2增速加快→流动性宽松 |
| VIX | < 20 且下降 | > 30 或快速上升 | VIX高→恐慌，低→乐观 |
| USD | 走弱(有利新兴市场) | 走强(资金回流美国) | 美元走强→新兴市场压力 |

### 3.3 维度聚合

```python
# 每个维度内的指标等权聚合
growth_pulse  = mean(growth_indicators_scores)     # -1 to +1
inflation_pulse = mean(inflation_indicators_scores)
liquidity_pulse = mean(liquidity_indicators_scores)
sentiment_pulse = mean(sentiment_indicators_scores)

# 综合分数（4维度等权）
composite_score = mean(growth, inflation, liquidity, sentiment)  # -1 to +1

# Regime 内强弱
if composite_score > 0.3:
    regime_strength = "strong"
elif composite_score > -0.3:
    regime_strength = "moderate"
else:
    regime_strength = "weak"
```

### 3.4 转折预警逻辑

当多个维度的信号与当前 regime 矛盾时，触发转折预警：

```python
# 示例：当前 regime = Recovery（复苏）
# 预警条件：增长脉搏转 bearish + 流动性脉搏转 bearish
if current_regime == RECOVERY:
    if growth_pulse < -0.3 and liquidity_pulse < -0.3:
        transition_warning = True
        transition_direction = "Deflation"  # 可能转向通缩
    if inflation_pulse > 0.5 and growth_pulse > 0.3:
        transition_warning = True
        transition_direction = "Overheat"  # 可能转向过热
```

---

## 4. 架构设计

### 4.1 Pulse 作为独立模块 `apps/pulse/`

**理由**：Pulse 有独立的业务实体（PulseSnapshot, PulseIndicatorReading）、独立的数据模型（PulseLog）、独立的生命周期（周频 vs regime 月频），符合 AGENTS.md 中独立 app 的标准。

**依赖关系**：

```
apps/macro   ──数据──→  apps/pulse   ──脉搏快照──→  apps/regime (action_mapper)
                              ↑                          ↓
                    MacroDataProviderProtocol     RegimeActionRecommendation
                                                         ↓
                                                   apps/dashboard (展示)
                                                   apps/decision  (决策流程)
```

Pulse 只读取 macro 模块已采集的数据，不自建 fetcher。

### 4.2 RegimeActionMapper 放在 `apps/regime/domain/`

`RegimeActionMapper` 是 regime 输出的丰富化，本质上是"regime 判定 + pulse 微调 → 可执行建议"的纯域逻辑。

```python
# apps/regime/domain/action_mapper.py

def map_regime_pulse_to_action(
    navigator: RegimeNavigatorOutput,
    pulse: PulseSnapshot
) -> RegimeActionRecommendation:
    """
    将 Regime 导航仪输出 + Pulse 脉搏 → 具体行动建议

    映射逻辑：
    1. Regime 提供资产类别权重区间（如 equity: 50%-70%）
    2. Pulse composite_score 在区间内插值
       - composite > 0.3 → 取上限（进攻）
       - composite < -0.3 → 取下限（防御）
       - 否则 → 取中值
    3. 输出具体配置 + 风险预算
    """
```

### 4.3 Regime → 资产映射表

| Regime | 权益 | 债券 | 商品 | 现金 | 风险预算(总仓位上限) |
|--------|------|------|------|------|---------------------|
| Recovery (复苏) | 50-70% | 15-30% | 5-15% | 5-15% | 85% |
| Overheat (过热) | 20-40% | 10-25% | 25-40% | 10-20% | 70% |
| Stagflation (滞胀) | 5-20% | 20-35% | 15-30% | 25-40% | 50% |
| Deflation (通缩) | 10-25% | 40-60% | 0-10% | 15-30% | 60% |

Pulse 在区间内微调：`weight = lower + (upper - lower) * (composite_score + 1) / 2`

### 4.4 34 个模块的导航重组

| 分类 | 模块 | 可见性 |
|------|------|--------|
| **主线** | dashboard, decision, regime, pulse(新) | 顶部导航 + 侧栏始终可见 |
| **宏观环境** | macro, policy, sentiment | 下拉菜单 |
| **投资决策** | signal, rotation, strategy, backtest, filter | 下拉菜单 |
| **资产分析** | equity, fund, sector, asset_analysis, alpha, factor | 下拉菜单 |
| **执行与账户** | account, simulated_trading, realtime, hedge, share | 下拉菜单 |
| **决策流程** | beta_gate, alpha_trigger, decision_rhythm | 决策模式内部步骤，不单独暴露 |
| **系统/运维** | ai_provider, prompt, terminal, agent_runtime, ai_capability, events, task_monitor, market_data, setup_wizard, audit | 设置/运维入口 |

---

## 5. 分阶段实施计划

### Phase 1: Regime Navigator + Pulse MVP + Dashboard 改造（5-6 周）

**目标**：最小完整垂直切片 — regime 导航仪 + pulse 脉搏 → 联合行动建议 → 在 dashboard 上可见。

详见：[phase-1-regime-navigator-pulse-mvp.md](phase-1-regime-navigator-pulse-mvp.md)

### Phase 2: 决策模式（引导漏斗）（4-5 周）

**目标**：完成 C 模式的漏斗式决策引导。

详见：[phase-2-decision-funnel.md](phase-2-decision-funnel.md)

### Phase 3: 增强与打磨（3-4 周）

**目标**：补充 Pulse 指标、配置化、历史回溯、前端打磨。

详见：[phase-3-enrichment-polish.md](phase-3-enrichment-polish.md)

---

## 6. 代码复用分析

| 组件 | 当前文件 | 复用策略 |
|------|---------|---------|
| `RegimeCalculatorV2` | `apps/regime/domain/services_v2.py` | **直接复用**，不修改。Navigator 在其上层封装 |
| `RegimeType` / `ThresholdConfig` / `TrendIndicator` | `apps/regime/domain/services_v2.py` | **直接复用**，新实体引用 |
| `RegimeCalculationResult` | `apps/regime/domain/services_v2.py` | **直接复用**，Navigator 组合它 |
| `CalculateRegimeV2UseCase` | `apps/regime/application/use_cases.py` | **被调用**，Navigator 用例依赖它 |
| `MacroDataProviderProtocol` | `apps/regime/domain/protocols.py` | **复用协议**，Pulse 也通过此协议读数据 |
| `HighFrequencySignalUseCase` | `apps/regime/application/use_cases.py` | **重构**：评估逻辑迁移到 Pulse，regime 保留冲突解决 |
| `HighFrequencyIndicatorFetcher` | `apps/macro/infrastructure/adapters/fetchers/high_frequency_fetchers.py` | **原样复用**，Pulse 读已入库的数据 |
| `RegimeBasedRotationEngine` | `apps/rotation/domain/services.py` | **增强**：接入 ActionRecommendation 的资产权重 |
| `RegimeConstraint` (Beta Gate) | `apps/beta_gate/domain/entities.py` | **复用**：决策模式中仓位约束步骤调用 |
| `DashboardData` DTO | `apps/dashboard/application/use_cases.py` | **扩展**：新增 pulse_snapshot、action_recommendation 字段 |
| `RegimeLog` ORM | `apps/regime/infrastructure/models.py` | **扩展**：新增 navigator_output JSON 字段 |
| `resolve_current_regime()` | `apps/regime/application/current_regime.py` | **保持兼容**，新增 `resolve_current_navigator()` 平行入口 |

---

## 7. 关键风险与应对

| 风险 | 严重度 | 应对方案 |
|------|--------|---------|
| 宏观数据未采集或过期 | 高 | Pulse 优雅降级：`PulseSnapshot.data_source` 标记 stale，UI 显示"数据过期"，用最后可用值 |
| Pulse 权重校准不准 | 中 | Phase 1 等权处理；Phase 3 支持数据库配置化 + 历史回测验证 |
| 大模板重构破坏现有功能 | 中 | Phase 1 只添加新组件（regime_status_bar, pulse_card），不改现有布局；Phase 2 才重构 workspace |
| SQLite 并发写入冲突 | 中 | 现有 Celery + SQLite 开发环境已工作；生产使用 PostgreSQL |
| Pulse 与 HighFrequencySignal 职责重叠 | 低 | 明确划分：Pulse = 战术层综合评估（4维度），HighFreqSignal = 单指标预警（保留用于实时告警） |
| 跨模块依赖过深 | 低 | ActionMapper 通过 Protocol 接口获取 Pulse 数据，不直接导入 Pulse 基础设施层 |

---

## 8. 成功标准

### Phase 1 完成标准

- [ ] `GET /api/regime/navigator/` 返回完整导航仪数据（象限 + 方向 + 资产指引 + 关注指标）
- [ ] `GET /api/pulse/current/` 返回 4 维度脉搏快照
- [ ] `GET /api/regime/action/` 返回联合行动建议（具体资产配置百分比）
- [ ] Dashboard 顶部显示 Regime 状态栏（带方向箭头和 Pulse 强度指示）
- [ ] Dashboard 显示"今日关注"卡片（待处理信号 + regime/pulse 变化提醒）
- [ ] Dashboard 显示 Pulse 四维仪表盘
- [ ] Domain 层测试覆盖率 ≥ 90%
- [ ] API 契约测试全部通过

### Phase 2 完成标准

- [x] 决策漏斗 6 步流程可走通（环境 → 方向 → 板块 → 推优 → 执行 → 复盘）
- [x] 日常模式 → 决策模式切换流畅
- [x] 导航栏按新分类重组完成

### Phase 3 完成标准

- [x] DR007 + 央行净投放 fetcher 上线
- [x] Pulse 指标权重支持数据库配置
- [x] 历史 Regime + Pulse 叠加时序图可查看
- [x] Dashboard / 决策工作台色调和引导打磨完成
- [x] Pulse 变化提醒已进入“今日关注”，并支持浏览器本地通知开关

### 当前实现备注

- `beta_gate`、`alpha_trigger`、`decision_rhythm` 仍作为系统内部能力存在，但不再作为首页/顶部导航中的独立主入口暴露；统一收束到“决策工作台 / 决策模式”中承接。
- 历史叠加图落地在 `Regime` 页面，通过 `/api/regime/navigator/history/` 获取数据并用 ECharts 渲染三层时序。
- 浏览器通知采用本地偏好开关（`localStorage` + Notification API）实现，不新增后端设置表。
