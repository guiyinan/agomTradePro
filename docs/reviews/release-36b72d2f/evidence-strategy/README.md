# Release 36b72d2f Evidence / Strategy 审核入口

> 审核包：release-36b72d2f-evidence-strategy-review-v1  
> 候选 commit：`36b72d2fc01604afdb15d236a1e91d082fb62a5b`  
> release：`20260830071422`  
> 当前状态：单一所有者授权已登记；EVID-P1 与 STRAT-P1 的候选绑定技术报告已作为 DEFER 入账，生产门继续 fail-closed。

本入口补充主审核包未覆盖的 `EVID-01`、`EVID-02` 和 `STRAT-01`。需要脱离仓库转发时，发送
[离线审核输入包](release-36b72d2f-evidence-strategy-review-input-package.zip)及其
[SHA-256 sidecar](release-36b72d2f-evidence-strategy-review-input-package.zip.sha256)。

本入口引用
[个人项目单一所有者授权](../../../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）。该 owner receipt 取代
多自然人和职责分离材料，但不能生成 zero-seed authority/operator row 或 R1–R8 业务定义。

## 1. 审核材料

- [详细审核指引](../../../deployment/evid-strat-review-team-handoff-2026-08-30-36b72d2f.md)
- [候选绑定授权 preflight](../../../deployment/evid-strat-production-authorization-preflight-2026-08-30-36b72d2f.json)
- [EVID 回传模板](../../../deployment/evid-01-evid-02-production-review-return-template-2026-08-30-36b72d2f.json)
- [STRAT 回传模板](../../../deployment/strat-01-business-owner-review-return-template-2026-08-30-36b72d2f.json)
- [动态审核清单](review-checklist.json)
- [审核报告输出规则](../reports/evidence-strategy/README.md)

全部权威证据的路径、SHA-256 和用途登记在动态清单中。审核团队应先校验 hash，再作决定。

## 2. 审核范围

EVID 报告必须按五个依赖阶段分别决定：

1. Account 上游 actor/owner-assignment seal；
2. owner/tenant authority root；
3. Research evidence scope；
4. evidence operator definition、approval 和 activation；
5. 有界生产 PostgreSQL first-winner/successor/revocation/rollback acceptance。

STRAT 报告必须对 R1–R8 每项分别提交带 hash 的真实业务定义、owner、policy、calendar、scope、
sample window、qualification 和适用的 benchmark/cost/liquidity/label/失效/回滚语义。业务定义审核
通过后仍须先做 canonical dry-run，production registration 不能在同一报告里预签。

## 3. 输出文件

- `evid-01-evid-02-production-review-return-<decision_id>.json`
- `evid-01-evid-02-production-review-return-<decision_id>.json.sha256`
- `strat-01-business-owner-review-return-<decision_id>.json`
- `strat-01-business-owner-review-return-<decision_id>.json.sha256`

输出目录：

    docs/reviews/release-36b72d2f/reports/evidence-strategy/

审核团队只复制模板并填写 final report，不修改 preflight、template、checklist、registry 或生产 ledger。
每份 final JSON 必须设 `template_only=false`；个人模式引用 owner authorization，team mode 填写
identity/account/receipt/有效期。每阶段仅使用
`APPROVE`、`REJECT` 或 `DEFER`，并附同名 SHA-256 sidecar。不得包含秘密或 placeholder。

## 4. 动态更新

报告落目录不等于授权。repository governance 流程校验 JSON/schema、sidecar、候选、owner-or-team
identity contract、阶段必填字段和依赖；全部通过才更新本目录的 `review-checklist.json`，
重建 sidecar，并同步 EVID/STRAT primary plans、`docs/plans/README.md` 与 machine registry。

执行后 current heads、生产 PG race/rollback、STRAT registered rows、PIT/OOS、Promotion 和 consumer UAT
均必须在真实发生后单独验收，不能预签或由零行事实推导。
