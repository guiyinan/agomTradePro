# A｜EVID-01/02：真实 single-owner authority root

决策编号 `OWNER-20261018-A`；状态：待签批。本页仅准备方案，不创建或激活任何 authority。

**待决定：** 是否基于已实现的 EVID-07 single-owner policy，为 Owner 本人的真实账户建立来源可核验的 authority root。

| 选项 | 含义 |
| --- | --- |
| A1（推荐） | 使用真实 Owner 身份与现有 single-owner policy，按精确账户、tenant、scope 和有效窗建立 authority；Owner 可按该政策兼任 claimant/approver |
| A2 | 继续沿用默认分离身份模式，待第二个真实人工审批主体与来源材料到位 |
| A3 | 继续不激活 authority，保持受限只读与准确阻断 |

**推荐值与范围：** A1。首次有效期建议 30 天，起止时刻由签批明确，不追溯到过去。只覆盖签批附件列出的本人身份、一个模拟账户及当前目标所需数据/计划/手工成交导入范围；不得扩大为跨用户、券商自动执行、所有账户或所有数据源的授权。

**执行前必须补齐的真实材料：** 当前认证主体 ID、实际 owner/tenant/account ID、真实账户创建与物理来源事实、政策 id/version/hash、来源证据及有效起止时间；读取当前 head、撤销/过期状态和双角色约束。历史“零 current authority”报告只是旧观察，不代替本次库存。身份材料通过受控通道提供，不把口令或 token 写入本页。

**验收：** 现有 EVID-07 合同明确不等于 EVID-01/02 生产关闭；须在原生 PostgreSQL 证明 append/replay/first-winner/current-head/撤销/过期/回滚与跨账户拒绝，取得真实 owner-scoped 接口验收。审核 B 不替代系统必须的人类身份字段。

**风险：** 本人兼任两角色减少角色分离；source scope、时钟或撤销链绑定不完整会形成过宽权限。以独立 agent 复核及 Owner 签字补充审查，不能据此伪造第二个人或审批流水。

**回滚：** 追加撤销或 successor 政策/authority，恢复默认拒绝，保留所有历史 root、receipt、generation 和审计；不删除旧行、不改历史签署、不恢复整库覆盖新数据。

**签批栏：** 选择 ___；身份/账户/tenant/政策附件 ___；有效起止 ___；签署人及日期 ___。材料未齐时只批准方案，不执行生产登记。

依据：`governance/active_plan_registry.json` 的 EVID-01/02/07；`apps/account/domain/single_owner_authority_policy_v1.py`；`apps/account/application/single_owner_actor_authority.py`；`docs/plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md`。
