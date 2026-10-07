# S6 阶段环境契约

本文是 S6 阶段进入条件的人工可读真源。运行时登记位于
`shared/release_rehearsal_stage_environment.py::CONTRACT_STAGES`；测试要求本表与 runner 的
`STAGES` 同步。新增阶段若未同时登记运行时契约、本矩阵和测试，统一 preflight 以
`REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING` 失败关闭。

统一 preflight 在候选镜像身份冻结后、`provider_probe` 之前运行。它一次执行所有宿主侧和候选侧只读探针，将全部缺口写入
`stage-environment-preflight.json`，最终只用总码
`REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED` 阻断排期。报告只含阶段、类别和稳定码，不含 env 值、密钥引用内容、URL
凭据、provider 响应或异常文本。它不会调用 provider、创建任务、写建议或改生产配置。

## 失败证据与抽象

| attempt | 已确认事实 | 被抽象的契约 |
| --- | --- | --- |
| `72de41d46b7242de9789cc0f8ce9d32c` | prepare 完成；runner 在 `akshare_financial_slice` 阻断，前缀已完成至 `github_ci_evidence`。CI 证据目录/文件由 root 生成，非 root 候选只读挂载时不可读。 | 文件树必须无 symlink/特殊文件，并以 descriptor 复核 group 与 `0550/0440` 密封状态；财报阶段挂载前再次只读复核。 |
| `ebe16fb787094b45957b16e17dfd771a` | `prepare-status.json` 为 exit 127，候选阶段未启动；远端 wrapper 含 CR 字节。 | 所有经 SSH/pipe 传输且随后执行或解析的文本必须 UTF-8、无 BOM/NUL/CR，并通过重复 `--transport-input` 显式登记。 |
| `5caf4f22e0264b3f9a9d67a06432f655` | prepare 完成；runner 在 `akshare_financial_slice` 阻断，生产快照当时缺 provider 3 的两条财报 egress 规则。 | 候选侧必须在 provider I/O 前复用持久化 `preview_route`，逐一验证 provider row × dataset × host × deployment region。 |

上述只读证据来自 VPS 历史 attempt；目录没有被修改或删除。

## 六类定义

运行时类别键固定为：`filesystem`、`transfer_encoding`、`network_egress`、
`identity_and_secrets`、`resources_and_time`、`external_state`。

1. **文件系统**：所有 mount/source/output 必须是预期的 regular file/directory；拒绝 symlink、device、socket 和替换后的 inode；
   候选输入树在 POSIX 使用 descriptor 复核属组与 mode。
2. **传输编码**：显式登记的 SSH/pipe 输入、env、JSON 和冻结快照必须为非空 UTF-8，且不含 BOM、NUL、CR/CRLF。
3. **网络出口**：模型行情路由复用 `provider_policy_and_routes`；财报路由复用
   `_require_akshare_financial_egress_routes`，后者调用持久化 `preview_route` 和公开
   `akshare_financial_deployment_region`。
4. **身份与密钥**：只验证必要 env key、provider identity、active provider row、Config Center secret 可解析性和格式；从不记录值。
5. **资源与时间**：保留 build 的 12 GiB Docker 硬门槛；统一门禁另要求证据文件系统至少 12 GiB、可用内存至少 512 MiB、
   timeout 层级合法、时钟带时区、隔离 PostgreSQL `clock_timestamp()` 与应用时钟差不超过 5 秒。
6. **外部状态**：冻结 provider settings、N=1/2N=2 财报预算、隔离 DB/Redis 身份、CI run 和两个生产周期入口的 disabled 状态。

## 阶段 × 六类矩阵

“已有”表示当前代码或已有门禁执行断言；“无资源”表示该阶段不触碰该类资源，
这是显式契约而不是静默跳过。

| 阶段 | 文件系统 | 传输编码 | 网络出口 | 身份与密钥 | 资源与时间 | 外部状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `build_only` | 已有：`_build_image` 拒绝缺失/多份 report 与 image tar；remote builder 校验归档。 | 已有：起跑前检查所有显式登记的 `--transport-input` 为 UTF-8/LF；未登记 transport 输入使 CLI 失败关闭。runner 自身启动前的 wrapper 边界见未验证风险。 | 已有：SSH/build host 由实际连接、host-key 交换及 build 命令失败关闭；没有额外 provider 请求。独立 allowlist preview 边界见未验证风险。 | 已有：`_validate_inputs` 只接受 regular password file；remote builder 独立读取，不进报告。 | 已有：remote build 的 12 GiB `/var/lib/docker` 硬门槛、显式 build timeout；统一门禁复核证据盘/内存。 | 已有：`_candidate_sha` 要求 exact SHA 和 clean tree；build-only 禁止部署。 |
| `docker_identity` | 已有：`_freeze_provider_settings_snapshot`、`_write_identity` 以排他写/哈希/只读 mode 冻结输入。 | 已有：统一门禁检查冻结 env/JSON/unit/identity 与登记传输文件。 | 无资源：仅检查本地候选镜像，不出网。 | 已有：`_candidate_container_gid`、OCI revision/image ID/release tag 精确绑定。 | 已有：命令 60 秒上限；统一门禁检查预算关系。 | 已有：checkpoint binding 绑定候选、输入摘要和隔离环境身份。 |
| `provider_probe` | 已有：`_invoke_container_stage` 校验目录 inode、group write 窗口并在退出时密封。 | 已有：统一门禁在阶段前检查 env/冻结输入/transport bytes。 | 已有：候选动态探针复用 `provider_policy_and_routes`；stage 自身继续保留 response evidence。 | 已有：完整 identities digest、quote/valuation provider ID 与候选镜像绑定；Config Center provider policy 只读解析。 | 已有：sample 50、max dispatch、provider timeout 与外层 stage timeout 层级。 | 已有：冻结 provider settings，禁止从 live 设置静默漂移。 |
| `response_replay` | 已有：provider probe 与 unit contract 只读 mount；报告/identity/hash 复核。 | 已有：统一门禁。 | 无资源：只重放已留存响应，不出网。 | 已有：probe SHA、unit contract SHA、candidate/provider digest。 | 已有：stage timeout；内存/磁盘由统一门禁覆盖。 | 已有：只消费同 attempt 前缀，checkpoint 防跨候选复用。 |
| `full_universe_capacity` | 已有：独立 stage 输出目录，报告密封并哈希。 | 已有：统一门禁。 | 已有：模型行情 bulk route 由候选动态探针预览，容量阶段仍执行真实 provider 契约。 | 已有：quote/valuation provider row 与 identities 一致。 | 已有：请求、窗口、deadline、lock wait、dispatch 均显式；容量阶段单独运行以免并发污染测量。 | 已有：动态 universe/target date/provider snapshot 被报告绑定。 |
| `production_policy_parity` | 已有：只读挂载启动时冻结的 provider settings，而不是可变源文件。 | 已有：统一门禁检查冻结副本。 | 已有：`provider_policy_and_routes` 同生产组合只读执行。 | 已有：raw file SHA 与 canonical payload SHA 双绑定。 | 已有：stage timeout 与统一资源门禁。 | 已有：生产策略 snapshot 与候选报告精确对账；两个周期入口必须 disabled。 |
| `isolated_postgresql_write` | 已有：独立输出目录；所有身份文件只读 mount。 | 已有：统一门禁。 | 无外网：只连接已绑定的隔离 PostgreSQL/Redis network。 | 已有：`_preflight_isolated_database_container` 和 `preflight_isolated_write_rehearsal` 绑定容器、DB、host、candidate。 | 已有：526 migrations/事务回滚由阶段检查；DB clock 由动态探针检查。 | 已有：`AGOM_RELEASE_REHEARSAL_DATABASE=1`、network alias、container ID 在并行组前复核。 |
| `github_ci_evidence` | 已有：`seal_container_input_tree` 按 descriptor 设置并复核 `0550/0440`；财报 mount 前 `verify_container_input_tree` 再次只读复核。 | 已有：统一门禁；GitHub artifact 下载内容另由 collector 的 schema/hash 校验。 | 已有：GitHub API/下载由 collector 访问，仓库/run ID 固定，连接或下载失败即关闭；独立 host allowlist preview 边界见未验证风险。 | 已有：exact SHA、repository、run ID、provider identities 和 artifact 节点契约。 | 已有：max age 24h 与 stage timeout。 | 已有：五组 CI、要求节点、零 skipped/failure/error 由 collector/validator 对账。 |
| `akshare_financial_slice` | 已有：CI 输入树 descriptor 二次复核；candidate output 独立目录；双 body store/hash/size/RawAudit 验证。 | 已有：统一门禁。 | 已有：复用 `_require_akshare_financial_egress_routes`；逐一检查 provider ID、`equity.financial.fact`/`equity.financial.source-time`、`datacenter.eastmoney.com`、公开 deployment region。 | 已有：AKShare active row、完整 identity、artifact secret ref 可解析且不输出值。 | 已有：N≤1、2N≤2、200 行、stage timeout；统一门禁复核时钟/资源。 | 已有：预算 loader、owner-approved contract、两周期入口 disabled；不修改规则或开关。 |
| `bundle_build` | 已有：只接收已验证报告；`_freeze_bundle` 拒绝 symlink 并将文件设只读，`bundle_tree_digest` 绑定路径/大小/hash。 | 已有：统一门禁。 | 无资源：本地组装，不出网。 | 已有：candidate/image/date/universe/provider/settings 全身份写入 manifest。 | 已有：固定 120 秒 timeout 与磁盘门禁。 | 已有：required reports policy 和 manifest builder 对账。 |
| `release_validator` | 已有：冻结 bundle 在 validator 前后重算 tree digest，防验证后替换。 | 已有：统一门禁。 | 无资源：本地验证，不出网。 | 已有：validator-owned receipt、manifest SHA、candidate image ID 与 OCI revision。 | 已有：固定 120 秒 timeout。 | 已有：release policy 的 required reports、schema、freshness 和 CI 节点全部复核。 |

## 稳定码与聚合语义

- 宿主静态问题：`REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID`、
  `REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID`、
  `REHEARSAL_STAGE_IDENTITY_OR_SECRET_CONTRACT_INVALID`、
  `REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT`、
  `REHEARSAL_STAGE_MEMORY_HEADROOM_INSUFFICIENT`、`REHEARSAL_STAGE_CLOCK_INVALID`、
  `REHEARSAL_STAGE_TIME_BUDGET_INVALID`。
- 候选动态问题：`REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID`、
  `REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED`、
  `REHEARSAL_STAGE_PROVIDER_IDENTITY_INVALID`、
  `REHEARSAL_STAGE_FINANCIAL_SECRET_CONTRACT_INVALID`、
  `REHEARSAL_STAGE_DATABASE_CLOCK_INVALID`、
  `REHEARSAL_STAGE_FINANCIAL_BUDGET_INVALID`、
  `REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID`。
- 报告 malformed 使用 `REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID`；未登记阶段使用
  `REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING`。所有探针跑完后才返回总阻断码。

## 未验证风险与下一轮门槛

- 本清单只覆盖已知六类，不能证明环境假设已经穷尽；未知类别风险必须保留在每次台账与交接中。
- Windows 本地不能证明 POSIX symlink race、descriptor ownership、非 root 容器读取和实际 mode；相关正反例必须由 Linux CI 执行，
  下一轮 fresh S6 再提供真实容器证据，不能把 Windows skip 计作通过。
- runner 无法在自身启动前检查启动它的 wrapper；上传/执行链必须在发送端复用同一 UTF-8/LF 规则，并把每个实际输入通过
  `--transport-input` 交给 runner 复核。未登记即输入校验失败。
- build host 的 SSH/DNS/host-key 路径和 GitHub artifact host 仍缺独立的无副作用 allowlist preview；当前由实际阶段失败关闭，
  不能宣称这些外部依赖已被统一门禁完全覆盖。
- 本门禁在本地与 CI 通过后仍不得称为 S6 实证；必须等待下一轮新候选，从 fresh production snapshot、fresh inputs、fresh attempt
  且禁止 `--resume` 跑完整十阶段。当前已准备或历史 attempt 均不能补记为本门禁证据。
