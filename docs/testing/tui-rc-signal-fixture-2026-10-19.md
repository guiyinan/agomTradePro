# Signal 表单选项与本地 RC 夹具

本轮隔离浏览器实测资产类别有 6 个实际选项，指标为 0。鲜库虽有 94 个 active catalog 和 98 条量纲规则，但没有 MacroFact 或 publication；指标查询只返回可用的已发布数据，因此 catalog 存在不能保证表单有可选指标。这个结论只绑定已核查的本地环境，不能据此认定 VPS 的实际数据状态。

此次仅使既有本地 RC 旅程预配置明确的 synthetic 指标数据，生产查询和激活规则不变。夹具必须显式 opt-in、loopback HTTP、Playwright settings、CI 标记和固定 RUNNER_TEMP SQLite 路径全部匹配；拒绝远端 UAT 范围、真实源/冲突记录及重复身份漂移。通过既有 normalizer/publisher/query/freshness 链读取，并仅在测试范围写入精确绑定的 synthetic pointer，不表示激活、Account fence 或 RawAudit 已验收。工作流仅新增 opt-in，保留已提交的临时加密密钥初始化。

相同私有源/同一隔离数据库连续两次 Signal 创建与管理浏览器流程各 1 项通过，无失败或跳过。第二次运行后，五张夹具表的原始内容、来源/可用时间、publication id/hash 和 pointer 均一致；catalog bootstrap 的 policy 时间戳会变，语义配置保持一致。v2 helper 导入错误、早期 health 超时和原验收索引均保留；实际 helper import 已修正，最终元数据由独立 reviewer 再核对。

原件位于本机仓库外持久归档，实际源码、命令、结果、失败及哈希见[证据索引](tui-rc-signal-fixture-evidence-2026-10-19.json)；未上传到远端。此批是 test-only 修复，不向 VPS 补造业务数据，不证明生产 UAT 或 RC/S6。最终候选仍需同 SHA 全量发布验证。本轮不部署。
