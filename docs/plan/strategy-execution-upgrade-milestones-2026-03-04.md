# 交易策略执行升级规划（分 M 里程碑）

> 日期：2026-03-04  
> 适用场景：个人基金投资（资金规模 <= 2 万美元），预留向轻量 OMS/EMS 升级空间。  
> 核心目标：把“什么时候下单、下多少单”从规则可配置升级为可验证、可回放、可灰度切换。

---

## 1. 目标与边界

### 1.1 本次要解决的问题
1. 何时下单：信号触发、过滤、执行窗口要可配置且可追溯。
2. 下多少单：仓位 sizing 从静态表达式升级为可扩展策略引擎。
3. 降低误操作：引入 pre-trade 风控和执行前确认。
4. 预留升级：未来可接入多账户分配、算法执行、轻量 OMS。

### 1.2 本次不做
1. 不做高频低延迟 EMS。
2. 不做机构级复杂审批流（双人四眼、法遵系统深度对接）。
3. 不做多券商复杂路由优化。

---

## 2. 目标架构（可升级）

```text
Signal/Model
  -> Decision Policy (是否交易)
  -> Sizing Engine (交易量计算)
  -> Pre-Trade Risk Gate (硬风控)
  -> Order Intent (标准化订单意图)
  -> Execution Adapter (模拟/实盘适配器)
  -> Fill/Result
  -> Audit + Replay
```

关键原则：
1. 策略决策与执行解耦（先出 `OrderIntent`，再执行）。
2. 先模拟后实盘（同一引擎，不同 adapter）。
3. 每一步都有审计事件和 request_id。

---

## 3. 里程碑总览

| 里程碑 | 周期 | 目标 | 退出条件 |
|--------|------|------|----------|
| M0 | 2-3 天 | 基线与契约冻结 | 有统一 `OrderIntent` 协议 + 回放样本 |
| M1 | 1 周 | 决策与仓位引擎 MVP | 支持“何时下单/下多少单”可配置 + 可回测 |
| M2 | 1 周 | 预交易风控与执行安全 | 下单前硬风控 + 幂等 + 熔断 |
| M3 | 1 周 | 执行抽象与灰度发布 | 模拟/实盘双适配 + 金丝雀切换 |
| M4 | 持续 | 向轻量 OMS 演进 | 多账户分配、订单状态机、执行质量统计 |

---

## 4. M0：基线与契约冻结

### 4.1 交付
1. 定义统一领域对象 `OrderIntent`：
   - `intent_id`, `strategy_id`, `symbol`, `side`, `qty`, `limit_price`, `time_in_force`, `reason`, `risk_snapshot`
2. 定义订单状态机（最小）：
   - `DRAFT -> APPROVED -> SENT -> PARTIAL_FILLED -> FILLED / CANCELED / REJECTED`
3. 建立回放样本集：
   - 最近 3-6 个月关键市场区间（上涨、震荡、下跌）

### 4.2 DoD
1. 不同策略输出结构一致。
2. 任意一次下单能通过 `intent_id` 追踪全链路。

---

## 5. M1：决策与仓位引擎 MVP（核心）

### 5.1 决策层（什么时候下单）
实现 `DecisionPolicyEngine`，输入：
1. 信号（强度/方向/置信度）
2. 市场状态（regime/policy/波动率）
3. 账户状态（现金、持仓、当日交易次数）

输出：
1. `ALLOW / DENY / WATCH`
2. `reason_codes`（可审计）
3. `valid_until`（触发有效期）

### 5.2 仓位层（下多少单）
实现可插拔 `SizingEngine`：
1. `fixed_fraction`（固定风险比例）
2. `vol_target`（目标波动仓位）
3. `atr_risk`（基于 ATR 的止损距离）
4. `max_drawdown_adaptive`（回撤自适应降杠杆）

统一输出：
1. `target_notional`
2. `qty`
3. `expected_risk_pct`
4. `sizing_explain`

### 5.3 关键约束
1. 所有计算可回放（给同样输入必须可复现）。
2. 参数全部配置化，不在业务代码硬编码阈值。

### 5.4 DoD
1. 新增策略可只通过配置接入（无需改执行主流程）。
2. 回测可对比至少 2 套 sizing 方法。

---

## 6. M2：预交易风控与执行安全

### 6.1 Pre-Trade Risk Gate
硬风控规则（拒单）：
1. 单标的最大仓位（例如 20%）
2. 单日最大交易次数
3. 单日最大亏损阈值（触发后当日禁新开仓）
4. 滑点估计超阈值
5. 流动性不足（最小成交量或盘口深度不足）

### 6.2 执行安全
1. 幂等键：避免重复下单
2. 超时撤单与重试策略
3. 熔断器：连续失败 N 次自动停机
4. “实盘确认开关”：高风险动作需要二次确认

### 6.3 DoD
1. 错单/重复单风险显著降低。
2. 失败路径全部可观测（日志+告警+审计）。

---

## 7. M3：执行抽象与灰度发布

### 7.1 执行适配层
统一 `ExecutionAdapterProtocol`：
1. `submit_order(intent) -> broker_order_id`
2. `query_order_status(order_id)`
3. `cancel_order(order_id)`

适配器：
1. `PaperAdapter`（模拟）
2. `BrokerAdapter`（实盘，先单券商）

### 7.2 灰度策略
1. 先 100% 模拟
2. 再 10% 真实仓位金丝雀
3. 通过阈值后提升到 30%-50%

阈值建议：
1. 拒单率 < 2%
2. 重复单 = 0
3. 实际滑点未超预算 20%

### 7.3 DoD
1. 可在不改策略逻辑情况下切换模拟/实盘。
2. 灰度期间可快速回滚到模拟执行。

---

## 8. M4：向轻量 OMS 演进（预留空间）

### 8.1 新能力（分批）
1. 多账户分配（同一 intent 分配到多个子账户）
2. 订单篮子（Basket）与批处理提交
3. 审批流（高风险交易需人工批准）
4. 执行质量分析（TCA-lite：滑点、成交率、时延）

### 8.2 数据模型预留
1. `order_intent`
2. `order_allocation`
3. `execution_report`
4. `risk_decision_log`
5. `strategy_param_version`

### 8.3 API 预留（示例）
1. `POST /api/execution/intents/`
2. `POST /api/execution/intents/{id}/approve/`
3. `POST /api/execution/intents/{id}/send/`
4. `GET /api/execution/orders/{id}/status/`
5. `GET /api/execution/tca/summary/`

---

## 9. 验证指标（你这个规模最关键）

1. 稳定性：
   - 连续 30 天无重复单、无严重错单
2. 风控：
   - 单日亏损保护触发后无新增违规单
3. 执行质量：
   - 平均滑点控制在预算内
4. 可解释性：
   - 每一单都有 `decision_reason + sizing_explain + risk_snapshot`
5. 可回滚性：
   - 执行层异常时 5 分钟内切回 PaperAdapter

---

## 10. 建议实施顺序（精简版）

1. 先做 M0 + M1（决定“该不该下单、下多少”）。
2. 再做 M2（把风险挡在下单前）。
3. 再做 M3（把实盘接入做成可灰度、可回滚）。
4. M4 按资金增长和需求逐步开启。

---

## 11. 你当前系统可直接复用的基础

1. 现有数据库驱动仓位规则（`position_size_expr`）可作为 M1 的一种 Sizing 插件。
2. 现有 Regime/Policy 过滤可作为 DecisionPolicyEngine 输入。
3. 你正在规划的操作审计日志可直接用于执行链路审计。

---

## 12. 最小可落地范围（两周版）

若只做两周，建议只交付：
1. `OrderIntent` 标准化 + 状态机（M0）
2. `DecisionPolicyEngine` + `SizingEngine` 两种方法（M1）
3. Pre-Trade Risk Gate 三条硬规则（M2 子集）
4. Paper/Real 双 adapter + 一键回退开关（M3 子集）

做到这一步，你的系统就从“策略建议系统”升级为“可控执行系统”。

---

## 13. 可开发任务清单（同文件派工版）

> 说明：以下任务按“先后依赖”排序，默认 Django 四层架构落地。  
> 标记：`[BE]` 后端，`[FE]` 前端，`[QA]` 测试/验收，`[OPS]` 运维。

### 13.1 M0 任务清单（契约冻结）

1. `[BE]` 定义订单意图领域实体与 DTO
   - 文件：
     - `apps/strategy/domain/entities.py`
     - `apps/strategy/application/dto.py`
   - 输出：
     - `OrderIntent`、`RiskSnapshot`、`DecisionResult` 数据结构
2. `[BE]` 增加最小订单状态机
   - 文件：
     - `apps/strategy/domain/services.py`
   - 输出：
     - `transition_status(from, event) -> to`
3. `[BE]` 增加状态机单测
   - 文件：
     - `tests/unit/strategy/test_order_state_machine.py`

### 13.2 M1 任务清单（何时下单/下多少）

1. `[BE]` 新增 DecisionPolicyEngine
   - 文件：
     - `apps/strategy/domain/services.py`
     - `apps/strategy/application/use_cases.py`
   - 输出：
     - `evaluate_decision(context) -> ALLOW/DENY/WATCH`
2. `[BE]` 新增 SizingEngine（2 个起步策略）
   - 文件：
     - `apps/strategy/domain/services.py`
   - 输出：
     - `fixed_fraction`
     - `atr_risk`
3. `[BE]` 参数配置持久化与版本化
   - 文件：
     - `apps/strategy/infrastructure/models.py`
     - `apps/strategy/infrastructure/repositories.py`
   - 输出：
     - `strategy_param_version`（可回滚）
4. `[BE]` 增加评估 API
   - 文件：
     - `apps/strategy/interface/views.py`
     - `apps/strategy/interface/urls.py`
   - 端点建议：
     - `POST /strategy/api/execution/evaluate/`
5. `[QA]` 单元 + 集成测试
   - 文件：
     - `tests/unit/strategy/test_decision_policy_engine.py`
     - `tests/unit/strategy/test_sizing_engine.py`
     - `tests/integration/strategy/test_execution_evaluate_api.py`

### 13.3 M2 任务清单（Pre-Trade 风控）

1. `[BE]` 新增 PreTradeRiskGate
   - 文件：
     - `apps/strategy/domain/services.py`
   - 规则：
     - 单标的仓位上限
     - 单日最大交易次数
     - 单日最大亏损禁开仓
2. `[BE]` 幂等与重复单保护
   - 文件：
     - `apps/strategy/infrastructure/models.py`
     - `apps/strategy/infrastructure/repositories.py`
     - `apps/strategy/application/use_cases.py`
   - 输出：
     - `idempotency_key` 校验
3. `[BE]` 审计事件打点
   - 文件：
     - `apps/audit/application/use_cases.py`
     - `apps/strategy/application/use_cases.py`
4. `[QA]` 风控拒单路径测试
   - 文件：
     - `tests/unit/strategy/test_pretrade_risk_gate.py`
     - `tests/integration/strategy/test_pretrade_rejections.py`

### 13.4 M3 任务清单（执行适配与灰度）

1. `[BE]` 定义 ExecutionAdapterProtocol
   - 文件：
     - `apps/strategy/domain/interfaces.py`
2. `[BE]` 实现 PaperAdapter
   - 文件：
     - `apps/strategy/infrastructure/providers.py`
3. `[BE]` 实现 BrokerAdapter（先占位 + 沙盒）
   - 文件：
     - `apps/strategy/infrastructure/providers.py`
4. `[BE]` 增加执行编排 UseCase
   - 文件：
     - `apps/strategy/application/strategy_executor.py`
5. `[BE]` 增加灰度开关
   - 文件：
     - `core/settings/base.py`
     - `apps/strategy/application/use_cases.py`
   - 配置建议：
     - `EXECUTION_MODE=paper|broker`
     - `BROKER_CANARY_RATIO=0.1`
6. `[QA]` 双适配器一致性测试
   - 文件：
     - `tests/integration/strategy/test_execution_adapters.py`

### 13.5 FE/OPS 任务清单（跨里程碑）

1. `[FE]` 策略执行评估页
   - 文件：
     - `core/templates/strategy/*`（按现有模板结构）
   - 功能：
     - 输入 context，一键看 `decision + sizing + risk reasons`
2. `[FE]` 执行审计页（我的执行记录）
   - 文件：
     - `core/templates/audit/*` 或 `apps/audit/templates/*`
3. `[OPS]` 告警与回滚
   - 文件：
     - `docker-compose*.yml`
     - `scripts/*`
   - 内容：
     - 连续失败熔断告警
     - 一键切回 paper 模式

---

## 14. 测试用例最小集合（必须通过）

1. 决策正确性：
   - 同输入同输出（可复现）
   - 关键阈值边界值测试
2. 仓位正确性：
   - qty 不超过现金与仓位上限
   - 极端波动下自动降仓
3. 风控有效性：
   - 触发禁开仓规则时拒单
   - 拒单原因可追溯
4. 执行安全：
   - 相同 `idempotency_key` 不重复下单
   - adapter 故障可回退
5. 审计完整性：
   - 每次执行都有 `request_id + intent_id + reason_codes`

---

## 15. 每个里程碑的发布门禁

1. M0 Gate：
   - 状态机单测 100% 通过
2. M1 Gate：
   - decision/sizing 单测 + 评估 API 集成测试通过
3. M2 Gate：
   - 风控拒单测试通过，重复单测试通过
4. M3 Gate：
   - paper/broker 适配器测试通过
   - 灰度开关在预发环境验证通过

---

## 16. 建议负责人分工（可直接改为真实名字）

1. 策略引擎负责人：M0 + M1
2. 风控与执行负责人：M2 + M3
3. 审计与可观测负责人：跨里程碑支持
4. QA 负责人：测试集与 Gate 落地
5. 运维负责人：回滚与告警流程
