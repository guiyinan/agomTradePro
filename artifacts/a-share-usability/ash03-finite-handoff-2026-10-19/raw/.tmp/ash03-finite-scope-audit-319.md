# ASH-03 有限退出范围静态核对

只读核对：2026-10-19。没有修改治理或生产文件，也未运行 QA、项目导入、数据库或 Git 操作。

结论：完成当前清单的三项收尾后，可以登记“ASH-03 本轮有限仓库开发切片完成”，不能据此把治理 registry 中整个 `ASH-03` 单元标为 `completed`。

依据：

- Owner 的 `owner-decision.md` 将后续顺序写为 ASH-03 →（有界并行前置 ASH-04）→ ASH-07…，并把 M1/M2/M3 作为各自可观察的业务里程碑；它没有批准用仓库切片完成来替代这些验收。审批记录第 10 项明确只是在关闭 ASH-02 时保留“ASH-03 active”，并强调真实持仓、导入后 T+1 与 M1/M2/M3 属于其各自范围（`docs/reviews/owner-scope-freeze-2026-10-18/owner-decision.md:29-37`; `docs/reviews/owner-scope-freeze-2026-10-18/approval-log.md:98-103`）。
- 主计划 §7.1–7.2 的原始 ASH-03 退出目标包括订单级冻结资金/股份、并发预留与幂等释放、部分成交/撤单、停机后由持久预留和券商事实恢复，以及费用预算和历史修正；这些不等同于已交付的即时模拟成交锁与同事务扣减（`docs/plans/a-share-usability-implementation-plan-2026-10-16.md:155-175`）。
- §19.82–19.83 记录了自动模拟四类 BUY/SELL 接入现有单笔结算 UoW、运行幂等及不确定结果停止等有限交付；同节同时明确没有整批自动恢复，并将完整 ASH-03、券商余额对账、Owner M1/M2/M3 与生产验收留作未完成事项（同计划 `:1579-1612`）。
- 当前 registry 仍将 `closure_backlog.units[ASH-03].status` 设为 `active`，其 `exit_gate` 仍要求真实会话下的未结算/可卖/预留数量、实际成交导入与成本合同、PostgreSQL 并发/部分成交/取消/恢复/回滚证据。`a-share-usability` 的 `next_gate` 也仍称 ASH-03 active，并列出成交事实、余额纳入声明、结算/成本及未知估值（`governance/active_plan_registry.json`，version `2026-10-19.v284`）。

建议登记方式：

1. 清单三项均有实际提交和对应验证后，在清单及 §19.83 追加带提交 SHA/证据绑定的回执，措辞限定为“本轮有限仓库开发切片完成；未完成 ASH-03 原 §7 全部退出门”。
2. 保留 registry 的 `ASH-03` 单元为 `active`，保留原 §7 exit gate；将 `next_gate` 更新为剩余订单级预留、部分成交/撤单/释放、停机恢复等可判定事项。若治理流程要把执行焦点移到有界 ASH-04，可只移动 `execution_focus` 并明示 ASH-03 全单元仍 active、保留残项；焦点移动不等于单元完成。
3. 不将“无本轮仓库工作”登记为 ASH-03 `completed` 或将剩余 §7 要求隐去。若要缩减整个单元的 Owner-approved exit gate，需先取得并记录明确的 Owner 范围修订；现有 Owner 记录不足以推断该授权。

有限边界：当前即时模拟的事务内账户锁/扣减、已发生逐笔券商事实及当前 unknown 状态，并不能证明挂单生命周期预留、订单部分成交/取消与恢复已经完成。此 memo 是范围/治理静态判断，不是全 §7 验收，也不是 Owner M1/M2/M3、RC/S6 或生产验收。
