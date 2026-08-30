# 审核报告输出目录

本目录接收候选绑定报告及其 SHA-256 sidecar。当前 AUD/DATA 与 TUI 报告的技术性 `DEFER` 已按
单一所有者模式验证入账；TUI 报告同时记录了项目所有者对既有 UAT 的有限 `APPROVE`。

## 立即接受的文件

- aud03-data02-production-review-return-<decision_id>.json
- aud03-data02-production-review-return-<decision_id>.json.sha256
- tui-m5-operations-review-return-<decision_id>.json
- tui-m5-operations-review-return-<decision_id>.json.sha256

如审批系统另行导出签名文件或 receipt，也放在本目录，并附各自 sidecar。

EVID-01/02 与 STRAT-01 的报告使用独立子目录：

- [evidence-strategy/](evidence-strategy/README.md)

TAR-05 Terminal Runtime 的报告使用独立子目录：

- [terminal-runtime/](terminal-runtime/README.md)

## 禁止事项

- 不覆盖 README、review-checklist.json、preflight 或 template。
- 不提交 template_only=true 的模板副本作为审核结果。
- 不把普通聊天用户名冒充法律姓名或生产账号。候选绑定的单一所有者声明可以作为个人项目 owner
  receipt，但必须如实记录其来源与无外部签名事实。
- 不在报告中写密码、token、cookie、API key、连接串或秘密 query parameter。
- 不预签尚未发生的 DATA-02 执行结果或 TUI 14 日最终观察。

报告进入本目录不等于获批。个人模式校验 JSON/schema、sidecar、候选、owner authorization、字段完整性
和依赖；team mode 另校验身份/receipt/职责分离。任何模式都不豁免技术字段或真实结果。
