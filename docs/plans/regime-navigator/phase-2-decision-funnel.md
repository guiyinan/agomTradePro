# Phase 2: 决策模式 — 引导漏斗 (v2.0 包含统一工作流与审计复盘)

> **父文档**: [regime-navigator-pulse-redesign-260323.md](regime-navigator-pulse-redesign-260323.md)
> **参考文档**: `docs/development/decision-unified-workflow.md`, `apps/audit/domain/entities.py`
> **前置依赖**: Phase 1 完成（Regime Navigator + Pulse MVP + Dashboard 日常模式）
> **预估周期**: 5-6 周
> **目标**: 完成 C 模式的漏斗式决策引导，用户可从宏观环境一路走到建仓执行，最后完成事后归因审计闭环。

---

## 1. 设计概述

决策模式的核心理念：**投资决策是一个漏斗**，从宽到窄，每一步缩小选择范围，并在执行后形成反思闭环。根据最新的架构设计，中间过程由 `DecisionUnifiedWorkflow` (Top-down + Bottom-up 融合) 支撑，后端通过 `apps/audit` 提供归因闭环。

```text
Step 1: 环境评估    "当前宏观环境如何？适合投资吗？"
    ↓ (Regime + Pulse + Policy 综合判断)
Step 2: 方向选择    "应该配置哪类资产？比例多少？"
    ↓ (Action Recommendation 的资产权重)
Step 3: 板块选择    "在推荐的资产类别中，哪些板块最有利？"
    ↓ (Rotation 模块的板块轮动建议)
Step 4: 推优筛选    "在选定板块中，具体买什么？"
    ↓ (Top-down + Bottom-up 融合，生成 UnifiedRecommendation)
Step 5: 审批执行    "仓位多大？何时执行？"
    ↓ (Beta Gate 约束 + 频率控制 + 状态机流转 NEW->APPROVED->EXECUTED)
Step 6: 审计复盘    "这笔交易产生了何种收益/亏损？归因于什么？"
    ↓ (Audit 模块提供 Heuristic / Brinson 归因，识别 LossSource)
    → 产生 AttributionResult 经验总结，反哺系统
```

### 与日常模式的关系

- 日常模式（Dashboard）回答："今天有什么需要关注的？"
- 决策模式（Workspace）回答："我要做一笔新决策，完整闭环怎么走？"
- **入口**：Dashboard 侧栏底部"发起新决策"按钮 → 进入决策模式
- **跳入**：日常模式中的推荐列表可直接跳到决策模式对应步骤（如点击 UnifiedRecommendation → 跳到 Step 5 审批执行）

---

## 2. 后端设计

### 2.1 决策上下文用例设计

依赖已有的 `apps/decision_rhythm` 和 `apps/audit` 模块进行编排：

```python
# core/application/decision_context.py (扩展现有用例)

@dataclass
class DecisionStep1Response:
    """Step 1: 环境评估"""
    regime_name: str
    pulse_composite: float
    regime_strength: str
    policy_level: str | None
    overall_verdict: str         # "适合投资" / "谨慎投资" / "不建议新增仓位"

@dataclass
class DecisionStep2Response:
    """Step 2: 方向选择"""
    action_recommendation: dict  
    asset_weights: dict[str, float]
    risk_budget_pct: float

@dataclass
class DecisionStep3Response:
    """Step 3: 板块选择"""
    sector_recommendations: list[dict]
    rotation_signals: list[dict]

@dataclass
class DecisionStep4Response:
    """Step 4: 推优筛选 (Unified Recommendation)"""
    unified_recommendations: list[dict]  # 基于 decision_rhythm 生成
    total_candidates: int
    page: int

@dataclass
class DecisionStep5Response:
    """Step 5: 审批执行"""
    approval_request_id: str
    suggested_weight: float
    position_limit: float        # beta_gate 约束
    gate_penalties: dict         # quota, cooldown 惩罚
    status: str                  # EXECUTED / REJECTED

@dataclass
class DecisionStep6Response:
    """Step 6: 审计复盘"""
    attribution_method: str      # "brinson" / "heuristic"
    benchmark_return: float
    portfolio_return: float
    excess_return: float
    allocation_effect: float     # 择时/配置效应
    selection_effect: float      # 选股效应
    interaction_effect: float    # 交互效应
    loss_source: str | None      # REGIME_TIMING_ERROR / ASSET_SELECTION_ERROR
    lesson_learned: str
```

### 2.2 API 端点设计

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/decision/context/step1/` | GET | - | Step 1: 环境评估 |
| `/api/decision/context/step2/` | GET | - | Step 2: 方向选择 |
| `/api/decision/context/step3/` | GET | `?category=equity` | Step 3: 板块推荐 |
| `/api/decision/screen/` | GET | `?sector=消费` | Step 4: 推优筛选（基于 `UnifiedRecommendation`） |
| `/api/decision/execute/preview/` | POST | `{recommendation_id}` | Step 5: 审批预览（Beta Gate 等） |
| `/api/decision/execute/approve/` | POST | `{approval_request_id}` | Step 5: 确认并执行 |
| `/api/decision/context/step6/` | GET | `?trade_id=xxx&backtest_id=123` | Step 6: 工作台局部加载审计复盘 |
| `/api/decision/audit/` | GET | `?trade_id=xxx&backtest_id=123` | Step 6: 获取基于 Brinson 的归因报告 JSON |
| `/api/decision/funnel/context/` | GET | `?trade_id=xxx&backtest_id=123` | SDK / MCP 获取完整漏斗上下文 |

### 2.3 复用现有模块

| 步骤 | 复用模块 | 复用方式 |
|------|---------|---------|
| Step 1 | `apps/regime`, `pulse` | 调用 `BuildRegimeNavigatorUseCase`, `GetLatestPulseUseCase` |
| Step 2 | `apps/regime` | 调用 `GetActionRecommendationUseCase` |
| Step 3 | `apps/rotation` | 调用 rotation 服务生成真实轮动配置，并与 Action Recommendation 推荐板块编排 |
| Step 4 | `apps/decision_rhythm` | 直接调用 `GenerateUnifiedRecommendationsUseCase` 及综合分评定 |
| Step 5 | `apps/decision_rhythm` | 调用 `ExecutionApprovalService` 完成状态机流转 |
| Step 6 | `apps/audit` | 优先读取已生成 `AttributionReport`，缺失时实时触发归因生成并返回 `LossSource` / 经验总结 |

---

## 3. 前端设计

### 3.1 决策工作台页面结构

**文件**: 重构 `core/templates/decision/workspace.html`

```text
┌─────────────────────────────────────────────────────────────────┐
│  [Regime 状态栏] (复用 Phase 1 组件)                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 1     Step 2     Step 3     Step 4     Step 5     Step 6  │
│  ● 环境 ─── ○ 方向 ─── ○ 板块 ─── ○ 筛选 ─── ○ 执行 ─── ○ 复盘  │
│  ══════                                                         │
│                                                                 │
│ ┌─────────────────────────────────────────────────────────────┐ │
│ │  [当前步骤内容区 - HTMX 动态加载]                           │ │
│ └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Stepper 导航实现

使用 Alpine.js 管理 6 步状态：

```html
<!-- decision/workspace.html -->
<div x-data="{ currentStep: 1, maxReached: 1 }">
    <div class="decision-stepper">
        <template x-for="step in [
            {n: 1, label: '环境评估'},
            {n: 2, label: '方向选择'},
            {n: 3, label: '板块选择'},
            {n: 4, label: '推优筛选'},
            {n: 5, label: '审批执行'},
            {n: 6, label: '审计复盘'}
        ]">
            <button
                :class="{'active': currentStep === step.n, 'completed': step.n < currentStep}"
                :disabled="step.n > maxReached"
                @click="currentStep = step.n"
                x-text="step.label">
            </button>
        </template>
    </div>

    <!-- 步骤内容区 -->
    <div x-show="currentStep === 1" hx-get="/api/decision/context/" hx-trigger="intersect once">...</div>
    <!-- ... -->
</div>
```

### 3.3 步骤模板 Partials

| 文件 | 内容 |
|------|------|
| `core/templates/decision/steps/environment.html` | Regime 象限图 + Pulse 仪表盘 + Policy 状态 |
| `core/templates/decision/steps/direction.html` | 资产类别配置饼图 + 权重滑块 + 风险预算 |
| `core/templates/decision/steps/sector.html` | 板块卡片列表（动量排名 + regime alignment） |
| `core/templates/decision/steps/screen.html` | UnifiedRecommendation 列表（Top-down+Bottom-up 融合分） |
| `core/templates/decision/steps/execute.html` | 审批操作板 (Approve/Reject) + Beta Gate 拦截提示 + 执行按钮 |
| `core/templates/decision/steps/audit.html` | Brinson 效果瀑布图 + Loss Source 分析结论 |

---

## 4. 模式切换与联动

- **Dashboard 统一入口**：增加"发起新决策"进入完整漏斗。
- **快捷审批 / 复盘跳入**：
  - 点击待审批的 `UnifiedRecommendation` -> 跳转到 `Step 5 (执行)`
  - 点击历史交易详情 -> 跳转到 `Step 6 (复盘)`，自动带入 `trade_id` 显示审计归因。

---

## 5. 验收测试要求

1. **Step 4 (推优)**：必须验证 `GenerateUnifiedRecommendationsUseCase` 是否成功融合 `[regime, policy, alpha, sentiment, flow]` 多维因子，处理完软硬 Gate 惩罚。
2. **Step 5 (审批)**：验证同资产 BUY/SELL 冲突能否被正确捕获 (`BUY_SELL_CONFLICT`)；状态机 (`ApprovalStatusStateMachine`) 转换是否合法。
3. **Step 6 (复盘)**：验证基于实际发生交易记录生成的 `BrinsonAttributionResult`，能否准确将超额收益拆解为：Allocation Effect 和 Selection Effect，并正确判别 `LossSource`。

### 5.1 当前实现说明

- Step 3 已取消静态 mock，工作台通过 `DecisionContextUseCase` 真实编排 `apps/rotation` 与 `GetActionRecommendationUseCase`。
- Step 4 / Step 5 继续复用 `apps/decision_rhythm` 现有真实接口链路，不再单独复制一套漏斗 mock。
- Step 6 支持 `trade_id` / `backtest_id` 两种入口；若数据库中尚无归因报告，会即时调用 `GenerateAttributionReportUseCase` 生成后返回。

## 6. 交付物清单

| 交付物 | 类型 | 模块 |
|--------|------|------|
| `core/application/decision_context.py` | 新建 | 决策上下文编排 |
| `core/api_views_decision_funnel.py` | 新建 | JSON API |
| `core/views_decision_funnel.py` | 新建 | HTMX partial 视图 |
| `core/templates/decision/workspace.html` | 重写 | UI (HTMX+Alpine) |
| `.../steps/environment.html` ~ `audit.html` (6个) | 新建 | UI 片段 |
| `core/static/css/decision.css` 漏斗进阶样式 | 新建 | CSS |
| 集成测试用例 `test_decision_funnel_e2e.py` | 新建 | Testing |
