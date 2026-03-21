下面是一份**可直接交付工程团队执行的《PRD + 技术设计文档（TDD）》**，
**Markdown 格式、工程化表达、无口号、可拆任务**。
内容覆盖 **Beta Gate + Alpha Trigger + Decision Rhythm** 三者的**完整闭环**，并**严格兼容你现有四层架构**。

你可以**原样丢进代码仓库 `/docs/decision_plane_v1.md`**，或直接发给工程负责人。

---

# AgomTradePro 决策平面改造

## PRD + 技术设计文档（TDD）

> **文档版本**：v1.0
> **状态**：READY FOR IMPLEMENTATION
> **适用系统**：AgomTradePro V3.4+
> **设计目标关键词**：
> **Hard Beta Gate / Discrete Alpha / Sparse Decision**

---

## 一、背景与问题定义（PRD）

### 1.1 背景

AgomTradePro 当前已具备：

* 严格的 **Regime + Policy** 宏观过滤
* PIT 数据、防后视偏差、完整回测与风控
* 多维度资产评分与模拟交易验证

系统目标已经达到：

> **“不在错误的宏观环境中下注”**

但在“**如何只关注能赚钱的信息**”这一目标上，仍存在结构性不足。

---

### 1.2 核心问题（Problem Statement）

#### P1：Beta 约束是“软”的

* Regime / Policy 主要通过**评分、权重、暂停逻辑**影响结果
* 不满足 Beta 的资产仍会出现在筛选结果和 Dashboard 中
* **结果**：信息负担大，注意力被稀释

#### P2：Alpha 信号被“平均化”

* 多维评分体系天然倾向“折中解”
* 缺少 **离散、结构性、强不对称** 的 Alpha 触发事件
* **结果**：系统很稳健，但很少“必须出手”

#### P3：缺乏决策稀疏度控制

* 系统每天可产生大量“可看项”
* 没有“本周只允许 1–3 个候选”的工程化约束
* **结果**：系统勤奋，但决策效率低

---

## 二、产品目标（PRD）

### 2.1 总体目标

构建一个**决策平面（Decision Plane）**，使系统具备以下能力：

1. **Beta Gate（硬闸门）**

   * 明确哪些资产 / 策略 **在当前宏观环境下“不可见”**
2. **Alpha Trigger（离散触发）**

   * 只在出现结构性错位时产出 **少量、可证伪、可行动的 Alpha 候选**
3. **Decision Rhythm（稀疏决策）**

   * 工程化限制每周 / 每月的“可决策数量”

---

### 2.2 成功判定标准（Success Metrics）

| 指标                | 目标        |
| ----------------- | --------- |
| 默认资产候选数量          | ↓ ≥ 60%   |
| 每周 AlphaCandidate | ≤ 3       |
| 每周 Actionable     | ≤ 1       |
| Alpha 事件证伪覆盖率     | 100%      |
| “无 Alpha” 周期      | 明确展示为正常状态 |

---

## 三、系统总体架构（TDD）

### 3.1 架构原则

* **不破坏现有四层架构**
* 新能力通过 **新增业务域** 实现
* 所有规则在 **Domain 层可测试**

### 3.2 新增业务域（Apps）

```
apps/
├─ beta_gate/          # Beta 闸门（可见性裁剪）
├─ alpha_trigger/      # Alpha 离散触发
├─ decision_rhythm/    # 决策节律与配额
├─ events/             # 领域事件（Domain Events）
```

---

## 四、PRD 详细设计

---

## 4.1 Beta Gate（硬闸门）

### 4.1.1 产品目标

将 **Regime + Policy + Risk Profile**
从“评分因子”升级为：

> **可见性裁剪器（Visibility Filter）**

不满足条件的资产 / 策略：

* ❌ 不参与评分
* ❌ 不进入资产池
* ❌ 不在默认 API / Dashboard 中出现

---

### 4.1.2 核心对象（Domain）

#### `VisibilityUniverse`

```text
VisibilityUniverse
- as_of
- regime_snapshot_id
- policy_snapshot_id
- risk_profile_id
- visible_asset_categories []
- visible_strategies []
- hard_exclusions []        # (category, reason, ttl)
- notes
```

#### `BetaGateDecision`

```text
BetaGateDecision
- decision: ALLOW | DENY | WATCH
- reason_codes []
- ttl
- manual_override (optional)
```

---

### 4.1.3 行为规则（Domain Rules）

* Policy = P3
  → 仅允许 CASH / HEDGE / OBSERVE
* Policy = P2
  → 禁用高波动策略、权益类 Alpha
* Regime 不确定性 > 阈值
  → 进入 WATCH Universe（不可执行）

---

### 4.1.4 API（Interface）

```http
GET /api/beta-gate/universe/latest
```

返回：

* 当前可见资产类别
* 被硬性排除的资产及原因
* 有效期（TTL）

---

## 4.2 Alpha Trigger（离散 Alpha）

### 4.2.1 产品目标

Alpha ≠ 高分资产
Alpha = **结构性错位 × 时间窗口 × 不对称性**

Alpha Trigger 只输出 **事件**，不输出分数。

---

### 4.2.2 AlphaCandidate（Domain Entity）

```text
AlphaCandidate
- id
- as_of
- universe_id
- trigger_type
- thesis
- evidence_refs []
- time_window (start, end)
- expression
- invalidation
- expected_asymmetry (HIGH/MED/LOW)
- status
- audit_trail []
```

---

### 4.2.3 必须实现的 Trigger（MVP）

#### 1️⃣ Policy Shift Trigger

* Policy 档位跃迁 / 口径变化
* 触发结构性约束变化

#### 2️⃣ Credit Spread Trigger

* 利差 / 期限利差进入极端分位
* 流动性或监管约束导致的错配

#### 3️⃣ Supply Shock Trigger

* 发行 / 配额 / 再融资节奏异常
* 明确时间窗口

---

### 4.2.4 行为约束

* AlphaCandidate **必须绑定 VisibilityUniverse**
* **必须定义证伪条件**
* 到期自动 `EXPIRED`
* 证伪命中自动 `DROPPED`

---

### 4.2.5 API

```http
POST /api/alpha-trigger/run
GET  /api/alpha-candidates/?status=
```

---

## 4.3 Decision Rhythm（决策节律）

### 4.3.1 产品目标

工程化解决一个问题：

> **“本周我最多应该看几个机会？”**

---

### 4.3.2 配额模型（Domain）

```text
DecisionQuota
- period: WEEK | MONTH
- max_watch
- max_candidate
- max_actionable
- ranking_policy
```

---

### 4.3.3 排序与降级逻辑

排序优先级（默认）：

1. 不对称性
2. 确定性
3. 时间窗口短

超过配额时：

* 自动降级
* 记录降级原因
* 写入审计轨迹

---

### 4.3.4 API

```http
POST /api/decision-rhythm/run
GET  /api/decision-rhythm/summary/latest
```

---

## 五、Dashboard 要求（PRD）

### 5.1 必须新增的三个区块

#### 1️⃣ Beta Gate 状态

* 当前 Regime / Policy
* 可见资产类别
* 锁仓 / 观察提示

#### 2️⃣ Alpha 面板

```
WATCH | CANDIDATE | ACTIONABLE
```

#### 3️⃣ 决策配额

* 本期配额
* 已占用
* 剩余额度
* “无 Alpha = 正常状态”提示

---

## 六、非功能性要求（TDD）

| 类别   | 要求                                    |
| ---- | ------------------------------------- |
| 可解释性 | 所有 Gate / Trigger / 降级都有 reason codes |
| 可审计性 | 所有状态变化留痕                              |
| 可测试性 | Domain 规则测试 ≥ 80%                     |
| 性能   | 每日全流程 < 5 min                         |
| 解耦   | 使用 Domain Events                      |

---

## 七、明确非目标（Non-Goals）

* 不接券商 API
* 不做 ML 自动学习
* 不追求高频

---

## 八、实施里程碑（工程排期建议）

| 周期       | 交付                          |
| -------- | --------------------------- |
| Week 1   | Beta Gate MVP               |
| Week 2–3 | Alpha Trigger（3 类）          |
| Week 4   | Decision Rhythm + Dashboard |
| Week 5–6 | Audit 闭环（推荐）                |

---

## 九、验收清单（DoD）

* [ ] Beta 不满足的资产 **不可见**
* [ ] AlphaCandidate ≤ 3 / week
* [ ] Actionable ≤ 1 / week
* [ ] 100% Alpha 有证伪条件
* [ ] 全量测试通过，旧模块不回归

---

## 十、一句对工程团队的话（可以写在群公告）

> **这次改造的目标不是“更聪明”，
> 而是“更少、更硬、更敢于什么都不做”。**

---

所有数据阈值不能硬编码

---

## 十一、详细实施文档

> **更新日期**：2026-02-03
> **状态**：已更新

详细的实施技术设计文档已迁移至：

**[docs/development/decision-plane-implementation.md](../development/decision-plane-implementation.md)**

该文档包含：
- 完整的 Domain 层实体定义代码
- Application 层用例编排设计
- Infrastructure 层 ORM 和仓储设计
- API 接口规范
- 集成点设计
- 实施里程碑和关键文件清单

---

## 十二、快速参考

### 实施阶段总览

| 阶段 | 时间 | 交付内容 |
|------|------|----------|
| Phase 1 | 2-3周 | Domain 层实体 + 事件总线 |
| Phase 2 | 2-3周 | Application 层用例 + 事件处理器 |
| Phase 3 | 2周 | Infrastructure 层 ORM + 仓储 |
| Phase 4 | 2周 | API 接口 + UI 集成 |
| Phase 5 | 1-2周 | 测试 + 优化 |

### 新增模块

```
apps/
├─ beta_gate/          # 硬闸门过滤
├─ alpha_trigger/      # Alpha 事件触发
├─ decision_rhythm/    # 决策配额管理
└─ events/             # 领域事件总线
```
