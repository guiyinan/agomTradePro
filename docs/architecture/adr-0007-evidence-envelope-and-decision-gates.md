# ADR-0007：Evidence Envelope 与决策硬闸所有权

> 状态：Accepted（分阶段实施）  
> 日期：2026-08-12  
> 对应计划：[`../plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md`](../plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md)

## 决策

1. Research 拥有输出级 `EvidenceOperatorSpec`、`EvidenceEnvelope` 和 `TrackRecordSnapshot` 合同，不拥有其他 App 的原始事实。
2. Data Center、Signal、Regime、Policy、Pulse、Alpha 和 R1–R8 owner 通过 Application adapter 提供内容寻址的事实与业务证据。
3. Risk Center 拥有版本化证据授权策略、授权 receipt 和主动风险预算；无 active policy 必须 fail closed。
4. Portfolio 拥有政策基准、人工签署、风险预算预约和决策计划；旧 `decision_rhythm` 计划写路径迁入 Portfolio facade 后才能退出冻结清单。
5. Broker Execution 在创建、审批、lease、submitting 四个节点重读本地 receipt/hash；不得通过外部网络临时补证据。
6. TUI 只负责不可隐藏的 Evidence Strip 和动作阻断，不得自行推导权限。
7. `DecisionPermission` 是唯一有序轴；兼容布尔字段全部从该轴派生。

## 所有权与接口矩阵

| 能力 | 真源 owner | 外部 App 允许持久化 | 强制接口 |
|------|------------|---------------------|----------|
| 原始观测与 Publication | Data Center / Signal | identity、version、hash | owner Application read provider |
| Operator Spec、Envelope、Track Record | Research | identity、version、hash | Research Application facade |
| Promotion 与 monitoring | 各研究 owner / Research 汇总 | exact receipt ref | owner exact read provider |
| Evidence authorization、风险预算 | Risk Center | exact authorization/reservation ref | Risk Center Application use case |
| Policy benchmark、attestation、transition plan | Portfolio | 本 owner全量 | Portfolio Application facade |
| Broker order、lease、submit、fill | Broker Execution | exact gate receipt refs | Broker Application use case |
| 展示与交互 | Terminal/TUI | 不持久化业务判断 | EvidenceSummaryDTO / authenticated detail API |

## 冻结策略

第一阶段先冻结当前 Decision Rhythm、Portfolio、Broker Execution、Simulated Trading 与 Strategy HTTP 写入口，以及会委托 HTTP 写操作的 SDK 方法。登记只表示历史入口存在，不表示它已经满足新证据门禁。

任何冻结清单变更必须同时更新本 ADR、实施计划和 Evidence/Risk/Broker 验收测试；M4 完成前不得借登记扩展新的仓位影响入口。

## 后果

- M1 可在不改变现有 canonical result hash 的前提下增加正交 Evidence 合同。
- M2–M4 必须逐入口从冻结状态迁往有 receipt 的 owner facade，不能并行新增旁路。
- M5 初始化所有旧 artifact 为 `SHADOW`，不回填或伪造历史权限。
