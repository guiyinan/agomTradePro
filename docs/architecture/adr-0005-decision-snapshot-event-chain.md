# ADR-0005：决策输入快照与事件链的关系

状态：Accepted（2026-07-22）

## 决策

`events.StoredEvent` 保存聚合类型、ID、版本、有效时间和 schema 版本，并对聚合版本唯一约束。各业务模块继续拥有状态表；`decision_rhythm.DecisionInputSnapshot` 冻结一次决策所引用的事件版本、PIT manifest、持仓、配置、策略和 Prompt 版本，并以稳定 hash 防篡改。下游只传 `snapshot_id`，不重新读取“当前状态”。

## 后果

组件缺失、未来时间、版本缺失、`must_not_use` 或 hash 不一致一律 fail closed。`AgentContextSnapshot` 只作展示/任务上下文并引用 canonical 决策快照，不成为第二真源。

