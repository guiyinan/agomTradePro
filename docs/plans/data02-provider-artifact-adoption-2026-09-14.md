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
