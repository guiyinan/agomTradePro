# F｜STRAT-01 规范登记授权

决策编号 `OWNER-20261018-F`；状态：待签批，不执行生产登记、不改变 research_only。

**已有状态：** 登记表 next_gate 记录 `APPROVE-STRAT-20260915-01` 已批准 R1～R8 owner semantics，八份定义及 receipt sidecar 的 Git LF 字节匹配；canonical dry-run、真实 current-head/精确 scope 与 append-only 登记仍待完成。原批准与失败/未完成证据均保留，不重新杜撰定义。

| 选项 | 含义 |
| --- | --- |
| F1（推荐） | 对已批准的八份定义与政策执行规范化 dry-run；精确冻结版本/hash、Owner 身份与范围后，按批准附件 append-only 登记 |
| F2 | 只做 dry-run，暂不写生产登记 |
| F3 | 重新设计研究方法再登记，不属于当前目标，后置 |

**推荐值：** F1 的两阶段执行；签批先明确允许的八个 artifact/version/hash 与 ledger，再通过真实 authority 与 dry-run 后登记。已有 owner semantics 审批继续有效；本次登记批准不扩展其算法、样本窗或资格。

**固定限制：** `research_only=true`、`must_not_use_for_decision=true`、`must_not_execute=true` 保持；不创建虚假的 PIT/OOS/qualification、Promotion、绩效证明或受益人审批，不因登记成功把研究产物接入自动交易。STRAT-03 已延期，不成为当前 M1/M2 的新增门槛。

**验收：** 全部引用可解析、原始与 Git LF hash 分开、缺失字段明确拒绝、同一 scope/current-head 无冲突、幂等重放不重复插入、账本追加与查询一致；记录实际写入与身份，不把模板或 dry-run 当成生产登记成功。A 页 authority 与 B 页独立审查按其真实适用约束执行。

**风险：** 登记字节与已批准语义不符、跨版本/范围混用，或把“已登记”误读为“可交易”。任何 hash、policy、scope 改变须重新界定受影响批准。

**回滚：** 追加撤销/退役或 successor，停用新 current head，保留旧定义、receipt、历史账本；不删除行或改旧 hash。

**签批栏：** 选择 ___；八份 artifact/版本/hash/ledger 附件 ___；允许执行的 dry-run/登记范围与窗口 ___；Owner 签署及日期 ___。
