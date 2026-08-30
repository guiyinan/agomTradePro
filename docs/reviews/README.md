# 生产审核入口

本目录是候选审核的稳定入口。项目当前采用 `single_owner_personal_project`：唯一真人所有者
“阿狗涅夫”的候选绑定声明替代多自然人和职责分离要求，但不替代任何技术证据或执行结果。
动态执行状态仍以 governance/active_plan_registry.json 为机器真源；本目录只管理审核清单、输入证据、
回传报告和经验证后的审核状态投影。

## 当前审核包

- [Release 36b72d2f AUD / DATA / TUI 审核入口](release-36b72d2f/README.md)
- [Release 36b72d2f EVID / STRAT 审核入口](release-36b72d2f/evidence-strategy/README.md)
- [Release 36b72d2f TAR-05 Terminal Runtime 审核入口](release-36b72d2f/terminal-runtime/README.md)
- [AUD / DATA / TUI 动态审核清单](release-36b72d2f/review-checklist.json)
- [EVID / STRAT 动态审核清单](release-36b72d2f/evidence-strategy/review-checklist.json)
- [TAR-05 动态审核清单](release-36b72d2f/terminal-runtime/review-checklist.json)
- [审核报告输出目录](release-36b72d2f/reports/README.md)
- [单一所有者授权声明](../deployment/personal-project-single-owner-authorization-2026-08-30-36b72d2f.json)

外部团队或所有者不得直接修改 active plan registry、生产配置或 authority ledger。报告与 sidecar 由
仓库治理流程验证后投影到 checklist。单一所有者模式可以接受真实技术缺口对应的 `DEFER`，但不会把
缺失的 authority、业务定义、retained history、staging、runtime 或交易事实写成通过。

当前已从审核转入实际整改：`TUI-01=completed`；`TUI-03` 的固定 digest Prometheus、21 日/4GB
留存、持久卷、真实 scrape target、M5 rules、健康检查、打包与认证 HTTPS query 合同已经通过，
结构化证据为
[`tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json`](../testing/tui03-retained-monitoring-repository-closure-evidence-2026-08-30.json)。
`TUI-02` 现等待生产部署和从首个 retained sample 重新起算的真实 14 日窗口。
