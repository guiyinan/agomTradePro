# A｜EVID-01/02：真实 single-owner authority root

决策编号 `OWNER-20261018-A`；状态：Owner 已批准方案，长期、不设自动到期；生产 authority 尚未登记或激活。批准原文及范围见 [审批记录第 3 项](approval-log.md)。

**待决定：** 是否基于已实现的 EVID-07 single-owner policy，为 Owner 本人的真实账户建立来源可核验的 authority root。

| 选项 | 含义 |
| --- | --- |
| A1（推荐） | 使用真实 Owner 身份与现有 single-owner policy，按精确账户、tenant、scope 和有效窗建立 authority；Owner 可按该政策兼任 claimant/approver |
| A2 | 继续沿用默认分离身份模式，待第二个真实人工审批主体与来源材料到位 |
| A3 | 继续不激活 authority，保持受限只读与准确阻断 |

**已批准的方案与范围：** A1，长期、不设自动到期。只覆盖附件列出的本人身份、一个明确模拟账户及当前目标所需数据/计划/手工成交导入范围；不得扩大为跨用户、券商自动执行、所有账户或所有数据源的授权。真实身份和来源核验、显式生效及 current-source/撤销检查仍须完成，不追溯生效。

**期限决定的历史：** 原建议为首次有效期 30 天。Owner 在第 3 项批准时明确回复“**不用设置有效期，一直这样吧**”，替换了该建议；30 天不再是当前方案。

**实现前的有界核查：** 无自动到期须由 authority-root 合同显式表达，并保留撤销、current-head、source、账户和用途校验。现有合同若要求 `valid_until` 或有限有效窗，先完成该表达的兼容核查；不得用 `9999` 日期、任意远期时间或跳过检查伪装永久。权限根无自动到期不延长底层来源、政策或数据的有效期，也不自动恢复已撤销或来源失效的权限。本次批准不直接修改业务代码或生产记录。

**执行前必须补齐的真实材料：** 当前认证主体 ID、实际 owner/tenant/account ID、真实账户创建与物理来源事实、政策 id/version/hash、来源证据和明确生效起点；读取当前 head、撤销状态、底层来源/政策有效性和双角色约束。历史“零 current authority”报告只是旧观察，不代替本次库存。身份材料通过受控通道提供，不把口令或 token 写入本页。

**验收：** 现有 EVID-07 合同明确不等于 EVID-01/02 生产关闭；须在原生 PostgreSQL 证明 append/replay/first-winner/current-head、无自动到期、撤销、底层来源/政策失效、回滚与跨账户拒绝，取得真实 owner-scoped 接口验收。审核 B 不替代系统必须的人类身份字段。

**风险：** 本人兼任两角色减少角色分离；source scope、时钟或撤销链绑定不完整会形成过宽权限。以独立 agent 复核及 Owner 签字补充审查，不能据此伪造第二个人或审批流水。

**回滚：** 追加撤销或 successor 政策/authority，恢复默认拒绝，保留所有历史 root、receipt、generation 和审计；不删除旧行、不改历史签署、不恢复整库覆盖新数据。

**批准记录：** Owner 于 2026-10-18 批准第 3 项方案，并明确不设自动到期。身份/账户/tenant/政策附件与生效起点尚待核验；材料未齐时不执行生产登记。

依据：`governance/active_plan_registry.json` 的 EVID-01/02/07；`apps/account/domain/single_owner_authority_policy_v1.py`；`apps/account/application/single_owner_actor_authority.py`；`docs/plans/evidence-governance-and-decision-hard-gate-remediation-plan-2026-08-12.md`。
