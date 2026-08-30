# Release 36b72d2f 审核入口

> 审核包：release-36b72d2f-production-closure-review-v1  
> 候选 commit：36b72d2fc01604afdb15d236a1e91d082fb62a5b  
> release：20260830071422  
> 当前状态：单一所有者授权已登记；AUD/DATA 技术报告为 DEFER；既有 TUI UAT owner gate 与 TUI retained-source repository remediation 已完成，TUI production deployment 已获 exact-action 授权但尚未执行；其余生产门继续 fail-closed。

审核团队从本页开始即可，不需要自行搜索仓库历史。

本候选采用
[个人项目单一所有者授权](../../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)
（SHA-256=`d9c6e9f4128603d0f2208e107a430db93332ec2db2e523886d5248bb63005fd7`）。同一项目所有者可以承担
治理角色，现有模板中的多自然人/production-account/职责分离字段不再是个人模式的硬门；技术字段、
候选、sidecar、真实结果和 fail-closed 仍是硬门。

需要脱离仓库转发时，发送
[离线审核输入包](release-36b72d2f-review-input-package.zip)及其
[SHA-256 sidecar](release-36b72d2f-review-input-package.zip.sha256)。解压后仍从本页开始审核。

EVID/STRAT 另从
[EVID / STRAT 补充审核入口](evidence-strategy/README.md)开始；该补充包与本页 AUD/DATA/TUI 包
职责不同，不得用一个总体决定互相替代。

TAR-05 的 staging/capacity/chaos/provider/
production canary 审核另从
[Terminal Runtime 补充审核入口](terminal-runtime/README.md)开始；该补充包同样不能替代本页或
EVID/STRAT 的决定，当前只接受 P1 环境/候选报告。

## 1. 审核材料

### 必读

- [详细审核指引](../../deployment/closure-review-team-handoff-2026-08-30-36b72d2f.md)
- [动态审核清单](review-checklist.json)
- [审核报告输出规则](reports/README.md)

### AUD-03 / DATA-02

- [候选绑定生产授权 preflight](../../deployment/aud03-data02-production-authorization-preflight-2026-08-30-36b72d2f.json)
- [审核报告模板](../../deployment/aud03-data02-production-review-return-template-2026-08-30-36b72d2f.json)
- [DATA-02 dry-run checkpoint](../../deployment/data02-audit-runtime-checkpoint-2026-08-30.json)
- [AUD-03 SELECT-only 原始观察](../../deployment/aud03-operational-observation-select-only-2026-08-30-36b72d2f.json)

### TUI M5

- [observation source preflight](../../deployment/tui-m5-observation-source-preflight-2026-08-30-36b72d2f.json)
- [monitoring remediation preflight](../../deployment/tui-m5-monitoring-remediation-preflight-2026-08-30-36b72d2f.json)
- [TUI-03 repository exit evidence](../../testing/tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json)
- [审核报告模板](../../deployment/tui-m5-operations-review-return-template-2026-08-30-36b72d2f.json)
- [production-safe UAT](../../../config/tui/migration/evidence/web_to_tui_uat_candidate.production-safe.v2.json)
- [cleanup scope evidence](../../../config/tui/migration/evidence/web_to_tui_cleanup_candidate.v1.json)
- [rollback evidence](../../../config/tui/migration/evidence/web_to_tui_rollback_candidate.v1.json)
- [registry backup checkpoint](../../deployment/tui-registry-backup-checkpoint-2026-08-30.json)

上述文件的精确 SHA-256 和用途已登记在 review-checklist.json。审核团队应先核对 hash，再作决定。

## 2. 审核团队要做什么

审核分为两个独立 work order，不能用一句“全部同意”合并：

1. AUD-03 / DATA-02：
   - 个人模式核实 owner authorization；team mode 核实 production owner、root approver、reviewer 与职责分离；
   - 审核真实 authority current heads；
   - 审核 forward runtime profile successor；
   - 审核一次精确 DATA-02 execute 的 operator/source/batch/期限/回滚点和风险边界；
   - 对每个 phase 分别输出 APPROVE、REJECT 或 DEFER。
2. TUI M5：
   - source 已由 single owner 选择为新 collector；repository 合同已固定 pinned image、retention、storage、query access 与窗口重置；
   - 下一阶段只审核真实 deployment/target-up/retention/query/rollback evidence；
   - role owner 对已经发生的 UAT 已确认；
   - 不得预签尚未完成的 14 日 telemetry、defect 或最终 cutover。

详细字段、停止条件与禁止事项以“详细审核指引”和两个 JSON 模板为准。

## 3. 审核团队输出什么

审核团队应复制模板，而不是覆盖模板：

- AUD/DATA：
  aud03-data02-production-review-return-<decision_id>.json
- TUI：
  tui-m5-operations-review-return-<decision_id>.json

每份 final JSON 必须：

- template_only=false；
- 精确绑定本页候选 commit/release/image；
- 个人模式引用候选绑定 owner authorization；team mode 填写真实姓名、production account、角色、receipt/reference 和有效期；
- 每阶段填写 APPROVE、REJECT 或 DEFER；
- 不使用 TBD、N/A、unknown、test、admin 或 placeholder 冒充值；
- 不包含密码、token、cookie、API key 或连接串；
- 附同名 .json.sha256 sidecar；
- 如签名系统另有文件，附签名文件及其 SHA-256，并明确绑定 final JSON SHA-256。

## 4. 审核报告输出地址

仓库相对地址：

    docs/reviews/release-36b72d2f/reports/

当前 worktree 绝对地址：

    D:\githv\agomTradePro-release-closure-20260830\docs\reviews\release-36b72d2f\reports\

审核团队可以把文件返回给项目方，由项目方放入上述目录；也可以在受控协作流程中直接提交到该目录。
不要把 report 写入 docs/deployment，不要覆盖 checklist、template 或 preflight。

## 5. 动态更新规则

review-checklist.json 是本审核入口的唯一动态审核状态投影。审核团队不能直接修改它。每次收到 report：

1. 校验 JSON 可解析、schema 正确且 template_only=false；
2. 校验同名 sidecar 与文件 SHA-256；
3. 校验 candidate commit/release/image；
4. 校验个人模式 owner authorization，或 team mode 的身份、production account、职责分离、receipt 与有效期；
5. 校验每个 APPROVE 分支的全部必填字段和依赖；
6. 只有通过后，更新匹配 work order 的 status、decision、report_path、report_sha256、next_gate；
7. 同步更新 checklist.updated_at、summary，并重建 checklist sidecar；
8. 再同步 primary plan、docs/plans/README.md 和 governance/active_plan_registry.json。

无效、过期、跨候选或缺 sidecar 的报告不得改变 checklist。DEFER/REJECT 会被真实记录，但不会解除生产门。

## 6. 当前下一步

当前审核回传已处理，下一步需要：

- 通过 canonical Account 边界建立或选择真实 authority heads，不能从 owner 声明直接推导；
- TUI-03 已固定并验证 image、retention、storage、query-access、rules、health 和 packaging 合同；
- owner 对 run `tui01-36b72d2f-20260830-01` 的有限确认已完成；下一步是 clean successor 部署、首个 retained sample 与窗口重置，14 日 telemetry 和 final cutover 仍未完成。

收到后先做只读验证，再按 checklist 依赖逐项推进；不会把审核报告解释为跨候选、无限期或全动作授权。
