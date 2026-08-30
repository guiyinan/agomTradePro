# Evidence / Strategy 审核报告输出目录

本目录只接收 EVID-01/02 与 STRAT-01 审核团队完成后的 final report、同名 SHA-256 sidecar，以及
报告引用的签名或业务定义文件及其 sidecar。当前两份候选绑定技术报告已按单一所有者模式作为
`DEFER` 验证入账；它们没有产生 authority、registration 或执行授权。

接受的主文件名：

- `evid-01-evid-02-production-review-return-<decision_id>.json`
- `evid-01-evid-02-production-review-return-<decision_id>.json.sha256`
- `strat-01-business-owner-review-return-<decision_id>.json`
- `strat-01-business-owner-review-return-<decision_id>.json.sha256`

禁止覆盖 README、preflight、template 或 checklist；禁止提交 `template_only=true`、缺 sidecar、跨候选、
含 placeholder/秘密或预签生产结果的文件。业务定义、policy、calendar、universe 或 thresholds 附件必须有
稳定引用和 SHA-256，不得只写聊天摘要。

报告存在不等于批准。个人模式以 owner authorization 取代多自然人 identity/separation/receipt；team
mode 保留原校验。业务定义、authority head、dry-run、dependency 和真实执行证据在两种模式下都不能省略。
