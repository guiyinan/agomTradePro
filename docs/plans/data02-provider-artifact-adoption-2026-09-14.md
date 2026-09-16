# DATA-02 配置供应商原始响应接入

本阶段解决财务响应捕获和加密存储未接入实际 Tushare provider 路径的问题。
功能仅在显式配置启用后生效；默认保持旧路径，不修改历史事实或公告时间。

## 已完成

- `fetch_financials` 通过 Tushare client、已登记的出网规则及 strict capture 读取一次原始响应；
  相同字节经 SHA/长度验证后写入 Fernet 原件存储和版本化 RawAudit 引用。
- HTTP 200 但供应商业务失败、错误表格、无出网规则或不完整配置均不能写入成功财务审计。
- 审计引用可验证并读回原始字节；审计写入失败保留孤儿原件引用，不自动删除文件。
  查找审计采用数据库 JSON capture ID 条件，不在 Python 解码全部历史财务审计。
- 原件开关缺失或关闭时保留旧 provider 路径，包括尚未入库的 provider。
  配置启用后须使用已入库 provider、不含凭据的 HTTPS URL 和完整显式存储配置。

## 配置与管理入口

`initialize_financial_response_artifact` 默认只预览；`--register` 注册五项定义，
`--activate` 在校验完整输入后通过 Config Center 激活 profile patch。
启用需显式提供 environment、root、encryption-key-ref、encryption-key-version、
max-body-bytes、actor 和 reason；密钥值通过已有 secret resolver 获取，命令不接收明文密钥。
禁用使用 `--enabled false` 或 `--disabled`，并保留 environment、actor、reason 审计信息。

原件配置 namespace 为 `data_center.financial_response_artifact`，定义包含 enabled、root、
encryption_key、encryption_key_version、max_body_bytes。还须登记该 provider 的
`equity.financial.fact` 出网规则；不得启用后绕过规则直接访问供应商。

## 验证与剩余

Root 最终回归实际 175 passed，覆盖 adoption、既有 provider adapters、strict capture、body store、
financial egress capture、execution contracts、Tushare transport 和 Config Center owner 桥。
Black、isort、Ruff 检查通过。九个接入文件及随后四个配置边界修正文件分别通过增量 mypy
（累计 11 个生产文件），均为零回归；修正后全生产类型债务检查为 0 错误、0 文件。
新鲜度契约检查（62 surfaces）与 Celery 契约检查（91 tasks）通过，未修改债务基线。

CI 首轮发现新增 App 直接依赖超出既有依赖预算、夹具依赖未跟踪 var 目录、入口清单及计划登记缺失。
配置定义通过标准库 metadata DTO 交给 Config Center owner 校验整批后保存；读取、secret ref、
secret resolve 和激活均经已有中立桥。依赖图恢复原有 206 条边、零循环，未增加治理预算。
夹具改用 pytest-owned tmp_path；入口清单由脚本重新生成，计划只新增 supporting 登记，未晋级单元。

尚未执行本阶段代码的 VPS 部署、真实供应商响应保存及生产验收。
响应范围保持 caller-declared，row_count/period_ends 的零值不代表完成原生行覆盖验证。
响应完成时间只证明 EOF 观察时间，不能作为 available_at 或公告时间；capture UUID
不能作为供应商原生行 ID。本阶段不激活 policy3，也不晋级 DATA-02/EVID 或人工验收状态。

## 风险与回退

文件与数据库不能跨事务原子提交，审计失败后须按原件引用核对孤儿状态。
生产启用前需核验持久化挂载、有效密钥引用、HTTPS provider 与出网规则。
可通过配置禁用返回旧路径；禁止清除原件、回填历史时间或修改既有 canonical fact 哈希。

## 24. Rejected response artifact follow-up (2026-09-14)

The explicitly enabled financial handler now retains a complete provider-rejected
response under a separate `financial_response_failure` audit capability and
`financial-response-failure-link.v1` link. It preserves encrypted exact bytes,
the response EOF timestamp and a stable business rejection code, then raises the
original provider error. It does not create successful financial audits or facts.
Sequential replay checks full request/audit metadata, validates supplied audit
hashes, rejects success/failure UUID conflicts and supports failure-only orphan
follow-up. Existing success-only audit ports remain compatible.

The frozen four-module local regression passed 117 tests with no failures,
errors or skips. Six production files passed incremental mypy with zero
regressions and the full debt ceiling at zero; Black, isort, Ruff and compile
checks passed. Exact pytest originals, source hashes, earlier failed attempts and
static-check provenance are recorded in
`docs/testing/data02-rejected-response-artifact-validation-2026-09-14.json`.

The fixture rejection bodies are synthetic. The previous real 62-byte supplier
code-2003 response remains unreplayable; this patch only fixes future complete
rejections. No native availability/announcement timestamp or source-row identity
is inferred. Concurrent uniqueness is not claimed. Production deployment and a
new source-bound failure-artifact validation remain pending; DATA-02 stays
awaiting production acceptance.

## 25. 2026-09-14 留存补丁部署与 DNS 阻断

PR68 全部 30 项 CI 通过，Source ba1605 已标准代码部署并返回 0。HTTPS 200，41 个关键文件 Git/release/live 一致；14 条策略、3 组 catalog、4 组 current 元数据、Authority 根/撤销记录、runtime/加密 secret 行均保全。采集器原范围只有根/撤销记录，不能称 19 组账本 before/after 已验证；完整 19 组 after 已补采，before 仍待独立 backup-derived 比较。

两次启动失败原件保留。修正 Compose 路径及 Django 初始化顺序后，实际只读 preflight 通过，对应失败窗口 egress 为 0。随后一次方法调用遭 EGRESS_DNS_TIMEOUT，原异常重抛，无响应原件及成功/失败财务审计候选；未将网络阻断当作 FRA1 留存通过。后续先诊断 DNS，确认恢复后有目的复测。

[生产验证封存](../deployment/data02-rejected-response-production-validation-2026-09-14.json)绑定 21 份原始工件。精确 available_at、native identity、历史 raw hash、历史 62 字节回放、完整账本保全及 DATA02 生产退出门仍未完成，注册状态和签署未改变。

## 26. 2026-09-14 DNS 恢复后的真实拒绝响应复测

容器 DNS 恢复至 116.218 ms 后，保留原 DNS 阻断工件并执行一次真实方法调用。实际 transport attempt 为 1；供应商仍返回 2003，原 TUSHARE_PROVIDER_REJECTED 异常重抛。新拒绝响应 62 B 已落盘，RawAudit 38591 为 failure/error/row_count=0；原始 body SHA 与解密 SHA 一致，真实 Fernet 和 FRA1 magic 校验通过。未写财务 Fact。

[真实复测封存](../deployment/data02-rejected-response-production-retest-2026-09-14.json)绑定新的响应原件和执行收据。新的响应即便 SHA 与历史 62 B 一致，也不能使历史内存原件变为可回放。response_completed_at 不等于 available_at；native identity、精确可用时间、历史 raw hash、成功财务验收和完整 19 组账本部署保全仍未完成，DATA02 状态和签署不变。

## 27. 2026-09-15 新候选审计构造 preflight

当前生产 `891c40c57` 候选的 `READ ONLY` 工厂构造在审计配置快照
`snapshot_hash_mismatch` 处被阻断；还未调用供应商，也未写入审计、事实或发布。
[只读构造证据](../deployment/data02-audited-quote-construction-readonly-2026-09-15-891c40c57.json)
与 [AUD 哈希范围证据](../deployment/aud03-config-snapshot-hash-scope-readonly-2026-09-15-891c40c57.json)
分别绑定实际执行和根因。此结论不能覆盖前述真实 `2003` 响应，更不能替代
5,533 标的回填或四份 immutable publication identity；`DATA-02` 继续
`awaiting_production`。仓库唯一执行焦点仍为 `EVID-09`，ConfigCenter 契约修复须待
焦点释放后另立隔离 slice，并以新快照/真实部署重新验证，不修改历史 seal。
