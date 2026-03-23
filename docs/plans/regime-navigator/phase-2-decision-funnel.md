# Phase 2: 决策模式 — 引导漏斗

> **父文档**: [regime-navigator-pulse-redesign-260323.md](regime-navigator-pulse-redesign-260323.md)
> **前置依赖**: Phase 1 完成（Regime Navigator + Pulse MVP + Dashboard 日常模式）
> **预估周期**: 4-5 周
> **目标**: 完成 C 模式的漏斗式决策引导，用户可从宏观环境一路走到建仓执行

---

## 1. 设计概述

决策模式的核心理念：**投资决策是一个漏斗**，从宽到窄，每一步缩小选择范围，每一步都有系统提供的上下文辅助。

```
Step 1: 环境评估    "当前宏观环境如何？适合投资吗？"
    ↓ (regime + pulse + policy 综合判断)
Step 2: 方向选择    "应该配置哪类资产？比例多少？"
    ↓ (action recommendation 的资产权重)
Step 3: 板块选择    "在推荐的资产类别中，哪些板块最有利？"
    ↓ (rotation 模块的板块轮动建议)
Step 4: 资产筛选    "在选定板块中，具体买什么？"
    ↓ (alpha/equity/fund 模块的评分和筛选)
Step 5: 执行确认    "仓位多大？何时执行？"
    ↓ (beta_gate 约束 + decision_rhythm 频率控制)
    → 创建投资信号 / 提交模拟盘订单
```

### 与日常模式的关系

- 日常模式（Dashboard）回答："今天有什么需要关注的？"
- 决策模式（Workspace）回答："我要做一笔新决策，怎么做？"
- **入口**：Dashboard 侧栏底部"发起新决策"按钮 → 进入决策模式
- **跳入**：日常模式中的信号可直接跳到决策模式对应步骤（如点击信号 → 跳到 Step 4 资产筛选）

---

## 2. 后端设计（Week 7-8）

### 2.1 决策上下文用例

**文件**: 新建 `apps/decision_workflow/` 模块，或在 `core/views.py` 中扩展

考虑到决策漏斗涉及多个模块的编排（regime、pulse、rotation、alpha、beta_gate），建议在已有的 decision 相关代码中增加编排层。

```python
# core/application/decision_context.py (新建)

@dataclass
class DecisionStep1Response:
    """Step 1: 环境评估"""
    regime_name: str
    regime_confidence: float
    regime_movement: dict        # direction, target, probability
    pulse_composite: float
    pulse_dimensions: list[dict] # 4 维度分数
    regime_strength: str
    policy_level: str | None
    policy_summary: str | None
    overall_verdict: str         # "适合投资" / "谨慎投资" / "不建议新增仓位"
    verdict_reasoning: str


@dataclass
class DecisionStep2Response:
    """Step 2: 方向选择"""
    action_recommendation: dict  # 来自 RegimeActionRecommendation
    asset_weights: dict[str, float]
    risk_budget_pct: float
    recommended_sectors: list[str]
    user_can_adjust: bool        # 用户是否可以手动微调


@dataclass
class DecisionStep3Response:
    """Step 3: 板块选择"""
    sector_recommendations: list[dict]  # [{name, score, regime_alignment, momentum}]
    rotation_signals: list[dict]        # 来自 rotation 模块
    regime_favored_sectors: list[str]


@dataclass
class DecisionStep4Response:
    """Step 4: 资产筛选"""
    candidates: list[dict]  # [{code, name, score, alpha_signal, factors, sector}]
    filter_criteria: dict   # 筛选条件
    total_candidates: int
    page: int
    page_size: int


@dataclass
class DecisionStep5Response:
    """Step 5: 执行确认"""
    asset_code: str
    asset_name: str
    suggested_weight: float      # 建议仓位
    position_limit: float        # beta_gate 约束
    current_holding: float       # 当前持仓
    regime_compatible: bool      # 是否与 regime 兼容
    rhythm_allowed: bool         # decision_rhythm 是否允许
    next_allowed_date: date | None
    signal_preview: dict         # 预填的信号模板
```

### 2.2 API 端点设计

所有端点返回 JSON（用于 HTMX partial 渲染）：

| 端点 | 方法 | 参数 | 说明 |
|------|------|------|------|
| `/api/decision/context/` | GET | - | Step 1: 环境评估（regime + pulse + policy 综合） |
| `/api/decision/direction/` | GET | - | Step 2: 方向选择（action recommendation） |
| `/api/decision/sectors/` | GET | `?category=equity` | Step 3: 板块推荐（接入 rotation 模块） |
| `/api/decision/screen/` | GET | `?sector=消费&page=1` | Step 4: 资产筛选（接入 alpha/equity/fund） |
| `/api/decision/sizing/` | GET | `?asset_code=000001.SZ` | Step 5: 仓位建议（接入 beta_gate） |
| `/api/decision/execute/` | POST | `{asset_code, weight, ...}` | 创建投资信号 |

### 2.3 编排逻辑

**Step 1（环境评估）** 编排：

```python
def get_decision_context(as_of_date: date) -> DecisionStep1Response:
    # 1. 获取 Regime Navigator
    navigator = BuildRegimeNavigatorUseCase(macro_repo).execute(as_of_date)

    # 2. 获取 Pulse
    pulse = GetLatestPulseUseCase(pulse_repo).execute()

    # 3. 获取 Policy Level（如有）
    policy = get_current_policy_level()

    # 4. 综合判断 verdict
    if navigator.regime_result.regime == RegimeType.STAGFLATION and pulse.regime_strength == "weak":
        verdict = "不建议新增仓位"
    elif pulse.regime_strength == "weak":
        verdict = "谨慎投资"
    else:
        verdict = "适合投资"

    return DecisionStep1Response(...)
```

**Step 3（板块选择）** 编排：

```python
def get_sector_recommendations(category: str = "equity") -> DecisionStep3Response:
    # 1. 获取 action recommendation 的推荐板块
    action = GetActionRecommendationUseCase(...).execute(date.today())

    # 2. 获取 rotation 模块的板块动量评分
    rotation_engine = MomentumRotationEngine(context)
    scores = rotation_engine.calculate_momentum_scores()

    # 3. 合并 regime 偏好和动量排名
    return DecisionStep3Response(
        sector_recommendations=merge_regime_and_momentum(action.recommended_sectors, scores),
        ...
    )
```

**Step 5（执行确认）** 编排：

```python
def get_sizing_suggestion(asset_code: str) -> DecisionStep5Response:
    # 1. 获取 action recommendation 的整体风险预算
    action = GetActionRecommendationUseCase(...).execute(date.today())

    # 2. beta_gate 评估
    gate_result = BetaGateEvaluator.evaluate(asset_code, regime, policy, risk_profile)

    # 3. decision_rhythm 检查
    rhythm_ok = DecisionRhythmChecker.is_allowed(asset_code, date.today())

    # 4. 当前持仓
    current = PositionRepository.get_by_asset(asset_code)

    # 5. 建议仓位 = min(action.position_limit, gate.max_weight)
    return DecisionStep5Response(
        suggested_weight=min(action.position_limit_pct, gate_result.max_weight),
        ...
    )
```

### 2.4 复用现有模块

| 步骤 | 复用模块 | 复用方式 |
|------|---------|---------|
| Step 1 | `apps/regime` (Navigator) | 直接调用 `BuildRegimeNavigatorUseCase` |
| Step 1 | `apps/pulse` | 直接调用 `GetLatestPulseUseCase` |
| Step 1 | `apps/policy` | 调用 `get_current_policy_level()` |
| Step 2 | `apps/regime` (ActionMapper) | 直接调用 `GetActionRecommendationUseCase` |
| Step 3 | `apps/rotation` | 调用 `MomentumRotationEngine` + `RegimeBasedRotationEngine` |
| Step 4 | `apps/alpha` | 调用 `GetAlphaSignalsUseCase` |
| Step 4 | `apps/equity` / `apps/fund` | 调用评分/筛选用例 |
| Step 4 | `apps/filter` | 复用筛选器逻辑 |
| Step 5 | `apps/beta_gate` | 调用 `BetaGateEvaluator.evaluate()` |
| Step 5 | `apps/decision_rhythm` | 调用频率约束检查 |
| 执行 | `apps/signal` | 调用 `CreateSignalUseCase` |

---

## 3. 前端设计（Week 9-10）

### 3.1 决策工作台页面结构

**文件**: 重构 `core/templates/decision/workspace.html`

```
┌─────────────────────────────────────────────────────────────┐
│  [Regime 状态栏] (复用 Phase 1 组件)                         │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1        Step 2        Step 3        Step 4    Step 5  │
│  ● 环境 ─────── ○ 方向 ─────── ○ 板块 ─────── ○ 筛选 ── ○ 执行 │
│  ═══════                                                     │
│                                                              │
│ ┌──────────────────────────────────────────────────────────┐ │
│ │                                                          │ │
│ │  [当前步骤内容区 - HTMX 动态加载]                         │ │
│ │                                                          │ │
│ │  Step 1 示例:                                            │ │
│ │  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │ │
│ │  │ Regime   │ │ Pulse    │ │ Policy   │                 │ │
│ │  │ 复苏期   │ │ 综合偏弱 │ │ P1 正常  │                 │ │
│ │  │ ▸过热25% │ │ 增长 0.3 │ │          │                 │ │
│ │  └──────────┘ │ 流动性-0.4│ └──────────┘                 │ │
│ │               └──────────┘                               │ │
│ │                                                          │ │
│ │  综合判断: ⚠️ 谨慎投资                                    │ │
│ │  "复苏期但脉搏偏弱，建议降低进攻性"                        │ │
│ │                                                          │ │
│ │                              [下一步: 选择方向 →]         │ │
│ └──────────────────────────────────────────────────────────┘ │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Stepper 导航实现

使用 Alpine.js 管理步骤状态 + HTMX 加载每步内容：

```html
<!-- decision/workspace.html -->
<div x-data="{ currentStep: 1, maxReached: 1 }">
    <!-- Stepper 导航 -->
    <div class="decision-stepper">
        <template x-for="step in [
            {n: 1, label: '环境评估'},
            {n: 2, label: '方向选择'},
            {n: 3, label: '板块选择'},
            {n: 4, label: '资产筛选'},
            {n: 5, label: '执行确认'},
        ]">
            <button
                :class="{'active': currentStep === step.n, 'completed': step.n < currentStep}"
                :disabled="step.n > maxReached"
                @click="currentStep = step.n"
                x-text="step.label">
            </button>
        </template>
    </div>

    <!-- 步骤内容区 (HTMX 加载) -->
    <div x-show="currentStep === 1"
         hx-get="/api/decision/context/"
         hx-trigger="intersect once"
         hx-target="#step-1-content">
        <div id="step-1-content"></div>
    </div>
    <!-- ... 其他步骤类似 -->
</div>
```

### 3.3 步骤模板 Partials

| 文件 | 内容 |
|------|------|
| `core/templates/decision/steps/environment.html` | Regime 象限图 + Pulse 仪表盘 + Policy 状态 + 综合判断 |
| `core/templates/decision/steps/direction.html` | 资产类别配置饼图 + 权重滑块（用户可微调）+ 风险预算显示 |
| `core/templates/decision/steps/sector.html` | 板块卡片列表（动量排名 + regime alignment 标记）+ 选择操作 |
| `core/templates/decision/steps/screen.html` | 资产筛选表格（排序、过滤）+ Alpha 评分 + 基本面概览 |
| `core/templates/decision/steps/execute.html` | 仓位计算器 + Beta Gate 约束显示 + 信号预览 + 确认提交按钮 |

### 3.4 步骤间数据传递

使用 URL 参数 + HTMX `hx-vals` 传递用户在前一步骤的选择：

```
Step 1 → Step 2: 自动（无需用户选择）
Step 2 → Step 3: ?category=equity (用户选择的资产类别)
Step 3 → Step 4: ?sector=消费&sector=科技 (用户选择的板块)
Step 4 → Step 5: ?asset_code=000001.SZ (用户选择的资产)
Step 5 → 执行:  POST 创建信号
```

---

## 4. 模式切换（Week 10-11）

### 4.1 从日常模式进入决策模式

- Dashboard 侧栏底部增加"发起新决策"按钮
- 点击后 `window.location = '/decision/workspace/'`
- 决策模式页面左上角增加"← 返回日常"链接

### 4.2 从信号跳入决策模式

- 日常模式的信号列表中，每个信号增加"查看决策上下文"按钮
- 点击后跳转到 `/decision/workspace/?step=4&asset_code=XXX`
- 决策模式自动定位到 Step 4（资产筛选），预填该资产

### 4.3 URL 设计

```
/dashboard/                           # 日常模式
/decision/workspace/                  # 决策模式 (Step 1)
/decision/workspace/?step=2           # 直接跳到 Step 2
/decision/workspace/?step=4&sector=消费  # 带上下文跳到 Step 4
```

---

## 5. 测试方案

### 5.1 后端测试

| 测试 | 内容 |
|------|------|
| `tests/unit/test_decision_context.py` | 环境评估逻辑、verdict 判定、regime×pulse 组合覆盖 |
| `tests/unit/test_decision_direction.py` | 方向选择逻辑、权重计算 |
| `tests/unit/test_decision_sectors.py` | 板块推荐排序逻辑、regime alignment 评分 |
| `tests/api/test_decision_api.py` | 5 个步骤 API 契约测试 |
| `tests/integration/test_decision_flow.py` | 全链路: Step 1 → Step 5 → 信号创建 |

### 5.2 前端验证

```
1. 打开 /decision/workspace/
2. Step 1: 确认 regime + pulse + policy 信息正确显示
3. 点击"下一步"→ Step 2: 确认资产权重饼图渲染
4. 选择权益类 → Step 3: 确认板块列表有内容
5. 选择板块 → Step 4: 确认筛选表格展示资产
6. 选择资产 → Step 5: 确认仓位建议、beta_gate 约束
7. 确认提交 → 验证信号创建成功
8. 从 Dashboard 信号列表跳入 Step 4，验证跳转正确
```

---

## 6. 交付物清单

| 交付物 | 类型 |
|--------|------|
| `core/application/decision_context.py` 决策编排层 | 新建 |
| `core/views.py` 5 个步骤 API 端点 | 修改 |
| `core/templates/decision/workspace.html` Stepper 重构 | 重写 |
| `core/templates/decision/steps/environment.html` | 新建 |
| `core/templates/decision/steps/direction.html` | 新建 |
| `core/templates/decision/steps/sector.html` | 新建 |
| `core/templates/decision/steps/screen.html` | 新建 |
| `core/templates/decision/steps/execute.html` | 新建 |
| `core/static/css/decision.css` 漏斗步骤样式 | 新建 |
| `core/static/js/decision-stepper.js` Alpine 交互 | 新建 |
| Dashboard "发起新决策"按钮 | 修改 |
| 单元测试 + API 契约测试 | 新建 |
