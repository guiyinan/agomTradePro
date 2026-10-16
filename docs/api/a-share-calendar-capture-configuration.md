# A 股交易所日历采集配置前置条件

本文说明如何为内部日历采集组合准备 Data Center 配置，以及哪些条件尚不能在运维层验证。它不是初始化种子、授权申请或采集操作说明；本文没有执行 manifest 同步、策略激活、权限授予或 Provider 请求。

## 当前可用范围

`compose_calendar_snapshot_capture` 只组装既有 Tushare `trade_cal` → 精确保留 `RawPayload` → 不可变日历快照的内部流程。组合构造不发网络请求；执行 capture 才会请求数据并写入保留原文和快照。它不发布 current pointer，也不检查登录用户、CSRF 或发布权限。

当前治理 manifest 中没有 `calendar_response_max_age_seconds`、`exchange_calendar` binding 或对应 codec 项；`scripts/check_data_center_catalog_contracts.py` 也把允许的数据集键固定为当前清单中的十项。新增数据集前，须先由治理所有者明确数据集身份，并按其变更流程协调该检查器及相关投影。本文的字段清单是待审批配置合同，不代表生产已经配置或具备运行资格。

当前 capture 源只有严格解析完整日期范围的 Tushare `trade_cal` 合同，固定技术 validator key 为 `exchange_calendar.tushare.trade_cal.full_date.v1`。该 key 表示本项目已有的完整日期解析器，不是通用 Provider Registry 项，也不证明其他供应商可用。当前没有合格的第二日历来源或 failover；不得把 AKShare、行情日历字段或模型结果当作备用日历。

## 必须成对配置的版本身份

采集选择器必须先检查目标 `dataset_key` 的完整 active Dataset Contract 集合：必须恰有一个 active 版本，且该版本明确配置日历响应 TTL。不能先过滤掉 TTL 为 `NULL` 的 active 版本再判断唯一性；同数据集的 active V2 合同加 active、无 TTL 的旧合同也属于歧义，必须阻断。其他数据集的合同和同数据集 inactive 的旧版本不构成该项歧义。选定合同后，再逐字匹配相同 `dataset_key`、`contract_version`、`schema_version` 的 active publication policy 和 enabled `exchange_calendar` binding，并要求 codec 为 `calendar-nullable-member-v1`。TTL 必须由审批后的合同显式提供；不从研究用 `freshness_seconds`、其他 TTL 或示例值回退。

| Governance 文件 | row | 必需字段与约束 |
| --- | --- | --- |
| `governance/dataset_contracts.json` | `contracts[]` | `dataset_key`、`contract_version`、明确的 `schema_version`、`frequency`、非空 `fields[]`，以及正的 JSON 整数 `calendar_response_max_age_seconds`；`owner` 可放在 row 或 manifest 顶层。loader 对省略的 `schema_version` 仍沿用 `1.0` 兼容值，新增候选应显式写出。TTL 是日历响应年龄预算，不是市场参数或上游观测时钟；没有业务默认值。修改此 TTL 必须使用新的 `contract_version`，不能用同一版本身份原地改值。 |
| `governance/provider_bindings.json` | `bindings[]` | 精确的 `dataset_key` / `contract_version` / `schema_version`、`provider: "tushare"`、`capability: "exchange_calendar"`、`validator_key: "exchange_calendar.tushare.trade_cal.full_date.v1"`、`enabled: true`。同一数据集只能有一个匹配 binding。`priority` 不是选择器的消歧规则。 |
| `governance/publication_policies.json` | `policies[]` | 精确的 `dataset_key`、非 `legacy` 的 `policy_version`、`member_codec_version: "calendar-nullable-member-v1"`，以及经治理批准的 `required_evidence`、`minimum_coverage_ratio`、`allow_partial`、`conflict_action` 和 `retention_days`。policy 必须绑定相同的合同和 schema 版本。 |
| `governance/data_ownership_contracts.json` | `datasets[]` | 保留并补齐该数据集的 `owner`、`business_owner` 和 `acceptance_owner`。初始化命令会一并同步 owner manifest。 |

上表只规定本 capture 选择器要求的字段，不给出可直接提交的 manifest，也不替代各字段自己的治理审查。诸如 dataset key、版本、TTL、覆盖率、证据键和 owner 均由负责方明确填写；不可从示例 fixture 或交易日期推导。

## ProviderConfig 与秘密快照

`ProviderConfigAdmin` 位于 Django Admin 的 Provider Config 页面。它允许维护 `source_type`、`is_active`、`priority`、`http_url`、`api_endpoint` 和 `extra_config`；Tushare 连接方式是 `sdk_path`、`unified_relay` 或 `rest_path`。后两种方式要求填写 `http_url`。API key/secret 使用遮蔽输入，提交后经现有 Config Center 凭据接口保存；留空表示保留已有值。Dataset Contract、Provider Binding 和 Publication Policy 的 Admin 都是只读页面，不能通过 Admin 新增这些目录行。

当前 binding 没有 ProviderConfig 实例 ID，`get_secrets()` 也不是按 binding/provider ID 返回秘密。因此采集组合要求数据库中恰有一个 active `source_type="tushare"` ProviderConfig；多个 active Tushare 实例会阻断。系统不按 `priority`、名称或 token 相似度选择实例。不要为了通过此检查而普遍停用其他 ProviderConfig：多实例与共享秘密之间尚缺逐实例身份合同，这仍是生产资格边界。

客户端秘密只从一次 `get_secrets().data_sources` 快照取得。采集组合会将已选 ProviderConfig 的 Tushare API key、`http_url` 和 `extra_config.tushare_request_mode` 与该快照逐项核对；模式与 URL 不匹配、token 缺失、存储的 `api_secret` 非空或配置值类型无效时均 fail closed。组合本身不读取其他 Provider、不自行从环境变量挑选备用 token，也不打印或持久化 token/URL 凭据。`get_secrets()` 保留其既有数据源解析策略；捕获端只接受其返回快照与唯一选中配置一致的情形。

该一致性核对不是 Config Center 秘密更新的线性化证明：配置表 fence 不锁定秘密服务或它的缓存。如果秘密快照与 ProviderConfig 不一致，应使用已有受控配置流程处理，再重新执行核对；不能靠绕过比较、临时切换 Provider 或手工输出秘密值解决。

## 数据库与事务边界

当前组合固定使用 `default` alias，因为既有 ProviderConfig、RawLanding 和日历事实仓储都绑定该 alias。调用方必须先建立一个由其自己拥有的外层事务，再在该事务内选择配置、组装并调用 capture；组合会检查配置表、RawPayload 与快照事实的 ORM 读写路由都指向同一 alias，并固定到该外层事务。内部仓储可以使用嵌套 `atomic()` / savepoint；本组合没有正式发布 writer 的“恰有一个 atomic block”要求。

PostgreSQL 配置选择要求 `READ COMMITTED`，并按表名顺序对合同、binding、policy 和 ProviderConfig 表取得 `SHARE` 表锁，以阻止候选配置在调用方事务内出现新增或更新幻读；本地 `lock_timeout` 最多收紧到五秒。SQLite 使用既有无行更新 fence；其他数据库后端当前会阻断。该 fence 不覆盖 Config Center 的秘密记录或缓存。

`known_at` 必须由调用方显式提供为 aware UTC 时间。选择器只从当前 active 行中检查其 `created_at` 和 `updated_at` 不晚于该 cutoff；Catalog 不保存足够的历史状态来重建过去时点的 active 配置，所以这不是 PIT 配置读取。

## 现有管理命令与核验边界

`initialize_data_center_catalog` 读取四份 JSON manifest，默认路径分别为 `governance/dataset_contracts.json`、`governance/provider_bindings.json`、`governance/publication_policies.json` 和 `governance/data_ownership_contracts.json`。它接受 `--contracts`、`--bindings`、`--policies`、`--owners` 路径覆盖；没有 `--dry-run`。该命令会同步所有传入合同、binding、policy 和 owner 行，并通过现有 policy repository 激活 manifest 中的精确 policy；它不是只改一个日历值的预览器。执行前必须审阅四份完整 manifest 及其对现有 active 配置的影响。

在变更被审批且适用的治理检查已更新后，命令形状为：

```powershell
.\agomtradepro\Scripts\python.exe manage.py initialize_data_center_catalog `
  --contracts governance/dataset_contracts.json `
  --bindings governance/provider_bindings.json `
  --policies governance/publication_policies.json `
  --owners governance/data_ownership_contracts.json
```

`scripts/check_data_center_catalog_contracts.py` 当前验证的是其源码中固定的十个数据集键；若要添加新 dataset，该检查器会拒绝，必须先完成单独批准的合同变更。`scripts/check_data_center_runtime_catalog.py` 要求部署环境提供 `DATABASE_URL`，会检查运行时合同/绑定/policy/owner 的键、合同版本、binding provider/capability 和 owner 角色；它不核对 policy version/member codec、此 capture 所需的 TTL、ProviderConfig 实例或秘密快照，不能单独作为 capture ready 证明。

Policy-only 的 `activate_publication_policies` 命令参数为必需的 `--expected-state <path>`、可选 `--policies <path>`（默认 `governance/publication_policies.json`）和 `--execute`。默认只做 preview，只有传 `--execute` 才提交。candidate manifest 必须是 `schema_version: "1.0"` 的 JSON，policy 集合需覆盖 expected-state 中完整的 active policy dataset 集合；`candidate_policy_projection_sha256` 是 candidate 文件原始字节的 SHA-256。expected-state 必须声明 `read_only: true`，绑定 active contract/policy、candidate target、完整 unrelated catalog rowset fingerprints 和 published-current metadata。它不是普通临时草稿：任何候选字节或运行状态变化都会使预检失败。

当前没有受支持的 expected-state 生成命令；不要从 full-market preflight 推测、手工伪造 fingerprints 或直接传 `--execute`。Policy activation 只负责 policy 行，不配置 provider secret，也不运行日历采集。本文未执行上述写命令。

当前没有独立的运维只读命令来返回“所选 calendar dataset + exact TTL + codec + binding + ProviderConfig ID”安全收据。完整逻辑由内部 `SelectCalendarCaptureConfigurationUseCase` 和组合覆盖；其当前测试位于 `tests/unit/data_center/test_calendar_capture_configuration.py`、`tests/unit/data_center/test_calendar_capture_configuration_repository.py` 和 `tests/component/data_center/test_calendar_snapshot_capture_composition.py`。组件测试只替换出站 HTTP transport，不访问真实供应商。

## 采集入口与时间含义

内部 capture intent 要求调用方明确传入交易所标识、`coverage_start` 和 `coverage_end`；没有默认交易所、默认日期范围或“今天”替代值。Tushare 请求严格使用 `exchange,cal_date,is_open,pretrade_date` 完整日期字段，由 exact full-date parser 从保留的原始响应重新解析。此链路保留 RawPayload，但没有 Calendar 专属 RawAudit occurrence/run 合同；不能把 RawPayload 保留描述成已验证的 RawAudit 请求审计。

`response_completed_at` 是本地收到完整响应的时间，不是交易所发布时间或观测时间。上游时间未提供时 `source_published_at` 等 source-time 字段保持 `None`，不得用请求时间、capture 时间或数据库记录时钟填充。Capture 只产生 unpublished snapshot，不能改动 current pointer。

此内部 factory 不是 HTTP 或 TUI 授权边界，也没有新增公开采集 URL。任何运维发布动作都必须由真实 session/CSRF 请求上下文重新验证专用 `publish_exchange_calendar` 权限；不能用 manifest 写入、配置 fence、capture receipt 或 source parsing 代替授权。日历结果仍是参考数据，不授予账户、风险、下单或券商执行能力。
