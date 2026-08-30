# Release 36b72d2f TAR-05 Terminal Runtime 审核入口

> 审核包：release-36b72d2f-terminal-runtime-review-v1  
> 候选 commit：`36b72d2fc01604afdb15d236a1e91d082fb62a5b`  
> release：`20260830071422`  
> 当前状态：P1 技术报告已按单一所有者模式作为 DEFER 入账；仍缺真实 staging、manifest、Worker/resources 和 bounded envelope，queued runtime、load、chaos、provider/MCP 与 production canary 均未授权。

本入口补充前两个审核包未覆盖的 `TAR-05`。需要脱离仓库转发时，发送
[离线审核输入包](release-36b72d2f-terminal-runtime-review-input-package.zip)及其
[SHA-256 sidecar](release-36b72d2f-terminal-runtime-review-input-package.zip.sha256)。

本入口引用
[个人项目单一所有者授权](../../../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）。单一所有者可以承担原多角色
治理职责；环境、manifest、Worker、预算、SLO 和真实执行证据仍不可省略。

## 1. 审核材料

- [详细审核指引](../../../deployment/tar05-review-team-handoff-2026-08-30-36b72d2f.md)
- [候选绑定授权 preflight](../../../deployment/tar05-production-authorization-preflight-2026-08-30-36b72d2f.json)
- [TAR-05 回传模板](../../../deployment/tar05-operations-review-return-template-2026-08-30-36b72d2f.json)
- [动态审核清单](review-checklist.json)
- [审核报告输出规则](../reports/terminal-runtime/README.md)

全部权威源的路径、SHA-256 和用途登记在动态清单中。审核团队应先校验 hash，再作决定。

## 2. 依赖顺序

1. P1：个人 owner authorization 或 team reviewer/operator，加上批准的 staging、最终候选 runtime manifest/flags/Worker/resources、预算和回滚边界；
2. P2：staging `1/5/10/20` capacity、soak、全部 metrics 与 19 项 hard SLO；
3. P3：九类 staging chaos/recovery 场景；
4. P4：受控真实 provider/MCP、审批、角色 UAT、费用/审计和 secret-redaction；
5. P5：在 P4 与 `TUI-01` 完成后，单独批准 production staff canary；
6. P6：真实 retained observation window、defect/incident、rollback 和三方签署；
7. P7：一般用户 rollout 与 legacy inline retirement 的独立后置决定。

P1 当前为 `deferred`。补齐真实环境/候选字段后可重新提交；一个 final report 只决定一个 dependency-ready phase；后续
phase 必须保持 `null` 或 `DEFER`，不能预签。

## 3. 输出文件

- `tar05-operations-review-return-<decision_id>.json`
- `tar05-operations-review-return-<decision_id>.json.sha256`

输出目录：

    docs/reviews/release-36b72d2f/reports/terminal-runtime/

审核团队只复制模板并填写 final report，不修改 preflight、template、checklist、registry 或生产配置。
final JSON 必须设 `template_only=false`；个人模式引用 owner authorization，team mode 填写
identity/account/receipt/有效期。每个当前 phase 只使用
`APPROVE`、`REJECT` 或 `DEFER`，并附同名 SHA-256 sidecar。不得包含秘密或 placeholder。

## 4. 动态更新

报告落目录不等于授权。repository governance 流程将验证 JSON/schema、sidecar、候选、runtime manifest、
owner-or-team identity contract、traffic/fault/cost/duration/account envelope、phase 必填字段和
依赖；全部通过才更新本目录的 `review-checklist.json`、重建 sidecar，并同步 Terminal primary plan、
`docs/plans/README.md` 与 machine registry。

任何实际 load、fault、external model call、production flag/Worker/canary、rollback、观察与 inline 退役
结果，都必须真实发生后另行验收；旧候选证据、本地 harness、瞬时 scrape 或零值不能替代。
