# EVID-01/02 与 STRAT-01 审核团队交接

> 候选 commit：`36b72d2fc01604afdb15d236a1e91d082fb62a5b`  
> release：`20260830071422`  
> image：`sha256:09f6491440a4bc16934ac5544c793a0b5b9d22c8ec6f8ab35d61693b0121c94b`  
> 当前结论：EVID authority/operator 与 STRAT owner ledger 均为 zero-seed；所有决策与执行门继续 fail-closed。

## 0. 个人项目单一所有者覆盖

候选绑定的
[`personal-project-single-owner-authorization-2026-08-30-36b72d2f.json`](personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）声明本项目只有一名真人
所有者。该 owner receipt 取代下文 team-mode 的多自然人、production account 和职责分离要求；同一
所有者可以提交业务决定并委托自动化做 schema/hash/执行验证。

该覆盖不产生 authority row、operator head 或 R1–R8 业务定义，也不允许代理编写“看起来合理”的定义。
当前 zero-seed 技术报告可作为有效 `DEFER` 入账；`APPROVE` 仍要求对应 assignment/head、definition、
policy、calendar、scope、qualification、dry-run 或执行结果真实存在。

当前动态状态（晚于下文初始交接说明）：EVID P1 与 STRAT P1 回传均已通过候选/sidecar/缺失事实
校验，并作为真实 `DEFER` 入账；不再因缺少第二名自然人而拒收。EVID 的 authority/assignment/head
仍为零，STRAT 的 R1–R8 定义仍未提供，所以没有任何生产 gate 晋级。下一步分别是 owner-led
canonical authority bootstrap，以及 owner 给出最小真实策略定义；下文 team-mode 多人要求只作可选路径。

team-mode 下，本交接要求审核团队提供真实身份、业务定义和分阶段决定，不要求审核团队直接修改数据库、
registry 或动态 checklist。审批必须拆成 EVID 与 STRAT 两份机器报告；一句“全部同意”不可执行。

## 1. 先核对材料

- 生产授权 preflight：
  `evid-strat-production-authorization-preflight-2026-08-30-36b72d2f.json`
  - SHA-256：`8518c165c21395716497a320f23e232d2744e29bea1cec8281f50fd7d19787ae`
- EVID 回传模板：
  `evid-01-evid-02-production-review-return-template-2026-08-30-36b72d2f.json`
  - SHA-256：`e7055af3c6dc94893a1c2900c2fbc6fd783125b96d432cddfa3f691df05269a2`
- STRAT 回传模板：
  `strat-01-business-owner-review-return-template-2026-08-30-36b72d2f.json`
  - SHA-256：`c21b14ed8a60123f3412fde414a4c2aab6ccd695eb651e5daef7722973322c24`

当前生产事实：

- Account `0050–0055` migration 已应用；13 张 authority/evidence 表总行数为 `0`；
- evidence operator spec/approval/activation 三表为 `0/0/0`，approval/activation head 为空；
- Research R1–R8 `65` 张、Portfolio R4/R5/R8 `7` 张、Account authority/assignment 广义
  `16` 张、owner/policy/operator/assignment 广义 `35` 张表总行数均为 `0`；
- disposable PostgreSQL harness 的三项软件合同通过，但 `production_claim=false`，不能替代生产验收。

源证据及精确 SHA 已列在 preflight。任一候选、文件 hash 或职责身份不一致，应输出 `DEFER`，
要求重新生成候选绑定材料；不得把决定迁移到后继候选。

## 2. EVID 审核 work order

使用 EVID 模板，按以下顺序逐阶段填写 `APPROVE`、`REJECT` 或 `DEFER`。

### EVID Phase 1：Account 上游 assignment seal

审核团队必须确认：

- authority subject owner 的真实姓名、production account、actor/user、tenant/owner 身份；
- actor/auth-context/user/RBAC 的 exact-current source identity/version/hash；
- owner-assignment subject、provenance receipt 和 assignment evidence 的 identity/version/hash；
- 真实有效期、撤销路径和独立 approval receipt；
- subject 与 root approver 是不同人员和不同生产账号；
- 身份不是从 mutable User/Profile/session、fixture 或聊天内容推导。

Phase 1 只授权精确上游 seal，不自动授权 owner/tenant root、Research scope、operator activation 或
STRAT 写入。

### EVID Phase 2：owner/tenant authority root

只有 Phase 1 已有真实 current-head receipts 时才能批准。模板固定要求：

- `authority_id/version`、`tenant_id`、`owner_id`；
- exact assignment evidence id/version/content hash；
- root 为 `active`、permission=`evidence_read`、无 predecessor；
- approver role=`owner_tenant_authority_approver`，且为独立 human staff；
- account namespace/account/actor/user、server clock、validity 与最终 hashes 均由上游和服务端派生，
  不能由调用方填写；
- 写后必须返回 first-winner、same-alias exact-current、identity/content hash 及重复竞争结果。

### EVID Phase 3：Research evidence scope

只有 Phase 2 root 已写入并通过 exact-current same-alias 读回才能批准。必须提供：

- scope source id/version；
- approved observation id/version/content hash；
- observation 中 owner/tenant/account/actor 与 authority root 的精确绑定；
- artifact owner/type/id/version/content hash；
- 有效期、撤销或 successor 语义；
- first-winner、same-alias current scope 和 chain receipt。

### EVID Phase 4：operator definition、approval 与 activation

必须审核真实 owner record、operator id/version、definition document 与 SHA-256、有效期、失效和回滚
条件。approval 和 activation 分别给出真实账号与 receipt；activation 必须引用 exact approval hash，
operator/version/definition hash 不得漂移。

### EVID Phase 5：生产 PostgreSQL acceptance

本阶段会产生有界生产写入，必须单独批准精确 database、subject IDs、维护窗口、停止条件、清理或
forward revocation、恢复点和负责人。至少验证：

- empty-root first-winner race；
- same-predecessor successor first-winner race；
- 外层事务 rollback 后零 partial rows；
- revoked/expired head 不回退旧版本；
- same-alias authority → Evidence 端到端读回。

本地 disposable harness 只能证明软件合同，不能用于批准本阶段通过。执行结果、current heads、
revocation 和双签必须执行后另行审核，不能预签。

## 3. STRAT-01 审核 work order

使用 STRAT 模板，对 R1–R8 每项分别作决定。每个 `APPROVE` 项至少需要：

- 真实 business owner 姓名、production account、角色、组织和 receipt；
- definition id/version、业务文档引用与 SHA-256；
- policy id/version 和完整 decision rules；
- calendar id/version、IANA timezone、cutoff 语义；
- scope id/version、universe 引用与 SHA-256；
- minimum duration/periods/samples/coverage；
- qualification id/version、阈值和可证伪条件；
- 适用时的 benchmark、cost、liquidity 和 label 语义；
- invalidation、retire 和 rollback 条件；
- valid_from/valid_until。

八项能力为：R1 Forecast Baseline、R2 Market Structure、R3 Macro Factor、R4 Risk/Allocation、
R5 Relative Value、R6 State Model、R7 Scenario Research、R8 Optimization Monitoring。

审核人批准的是带 hash 的业务定义文档，不得自行填写“看起来合理”的 canonical content hash。
系统必须先做 schema/hash/current-head/overlap dry-run，再形成第二阶段的精确 append-only registration
授权。若 dry-run 尚未提供，`phase_2_append_only_registration.decision` 必须保持 `DEFER`。

当前审核不包含 PIT/OOS backfill、合成历史、Promotion、consumer UAT、strategy execution 或阈值
降低。真实 registration 后的 rows/hashes/current-head 仍需另行审核，历史与 Promotion 更不能预签。

## 4. 回传文件

不要覆盖模板。复制为：

- `evid-01-evid-02-production-review-return-<decision_id>.json`
- `evid-01-evid-02-production-review-return-<decision_id>.json.sha256`
- `strat-01-business-owner-review-return-<decision_id>.json`
- `strat-01-business-owner-review-return-<decision_id>.json.sha256`

将 final report 返回：

    docs/reviews/release-36b72d2f/reports/evidence-strategy/

每份 final JSON 必须设 `template_only=false`、精确绑定候选并附同名 SHA-256 sidecar。个人模式引用第 0
节 owner authorization；team mode 填写 identity/account/receipt/有效期。外部签名存在时也需附 sidecar。

## 5. 禁止事项

- 不使用 `TBD`、`N/A`、`unknown`、`test`、`admin` 或 placeholder 冒充值；
- 不把普通系统管理员、聊天审批或用户会话当成 root authority；
- 不把 Data Center facts、下游 assessment 或零行 inventory 反充为 owner definition；
- 不在报告中写密码、token、cookie、API key、连接串或秘密 URL 参数；
- 不预签生产 race/rollback、真实 registration、PIT/OOS、Promotion 或 consumer UAT；
- 不直接修改 checklist、active plan registry 或生产 ledger；
- 不清除全局 decision/execution deny。

报告进入目录本身不等于批准。项目治理方必须先校验 JSON/schema、sidecar、候选、owner-or-team identity
contract、阶段依赖和必填字段，才允许更新动态 checklist。任何无效或跨候选报告均不改变状态。
