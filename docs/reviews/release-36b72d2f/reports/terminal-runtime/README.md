# TAR-05 Terminal Runtime 审核报告输出目录

本目录只接收 TAR-05 审核团队完成后的 final report、同名 SHA-256 sidecar，以及报告引用的签名、
环境、manifest、load/chaos、UAT、canary、telemetry 或 rollback 文件及其 sidecar。当前 P1 技术报告已按
单一所有者模式作为 `DEFER` 验证入账；没有启用 queued runtime 或任何后续动作。

接受的主文件名：

- `tar05-operations-review-return-<decision_id>.json`
- `tar05-operations-review-return-<decision_id>.json.sha256`

禁止覆盖 README、preflight、template 或 checklist；禁止提交 `template_only=true`、缺 sidecar、跨候选、
含 placeholder/秘密或预签后续 phase 的文件。每份 report 只能决定一个当前 dependency-ready phase。

P1 报告必须提供真实环境/候选/预算/回滚边界；个人模式以 owner authorization 取代多自然人身份与职责
分离，team mode 保留原要求。P2–P7 只有在依赖通过且存在真实执行输入或结果后才接收。报告存在不等于
批准；通过 schema/hash/candidate/owner-or-team-identity/bounded-envelope/dependency 校验后才更新清单。
无效报告不改变生产 authorization、
execution focus、queued runtime、inline concurrency 或 registry。
