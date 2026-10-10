# S6 阶段环境契约

本文是 S6 阶段进入条件的人工可读真源。运行时登记位于
`shared/release_rehearsal_stage_environment.py::CONTRACT_STAGES`；测试要求本表与 runner 的
`STAGES` 同步。新增阶段若未同时登记运行时契约、本矩阵和测试，统一 preflight 以
`REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING` 失败关闭。

统一 preflight 在候选镜像身份冻结后、`isolated_database_migrations` 之前运行。它一次执行所有宿主侧和候选侧只读探针，将全部缺口写入
`stage-environment-preflight.json`，最终只用总码
`REHEARSAL_STAGE_ENVIRONMENT_PREFLIGHT_FAILED` 阻断排期。报告只含阶段、类别和稳定码，不含 env 值、密钥引用内容、URL
凭据、provider 响应或异常文本。成功报告连同 prebuild 报告的路径与 SHA-256 作为 required report 进入不可变
release manifest、release validator 和 handoff receipt；缺失、摘要不匹配、矩阵不完整或任一格不是 pass 均失败关闭。
该 preflight 本身不调用 provider、创建任务、写建议或连接可变生产配置。其后的迁移阶段只允许在精确绑定的 disposable PostgreSQL
中执行候选镜像 migrations；它不是生产迁移入口。

## 失败证据与抽象

| attempt | 已确认事实 | 被抽象的契约 |
| --- | --- | --- |
| fresh prepare（candidate `c6fcf4a…`） | candidate exporter 的 `copytree` 无法读取 root:0700 的工作区顶层；随后 wrapper 在 `set -u` 下用未加括号的 `$mode_FAILED` 把错误遮蔽成 `mode_FAILED`。 | attempt planner v2 在 reserve 时从 exact clean Git candidate tree 的 blob 建立不含 `.git` 的独立快照，拒绝 symlink/特殊项，只密封快照为候选 GID 的 `0550/0440`；保存含 receipt SHA 与 tree SHA 的无秘密 receipt。每次 Docker exporter 前只读复核，并要求唯一、位于 image 参数之前的 `--user <non-root UID>:<candidate GID>`、精确 image 与只读 mount。 |
| `72de41d46b7242de9789cc0f8ce9d32c` | prepare 完成；runner 在 `akshare_financial_slice` 阻断，前缀已完成至 `github_ci_evidence`。CI 证据目录/文件由 root 生成，非 root 候选只读挂载时不可读。 | 文件树必须无 symlink/特殊文件，并以 descriptor 复核 group 与 `0550/0440` 密封状态；财报阶段挂载前再次只读复核。 |
| `ebe16fb787094b45957b16e17dfd771a` | `prepare-status.json` 为 exit 127，候选阶段未启动；远端 wrapper 含 CR 字节。 | 所有经 SSH/pipe 传输且随后执行或解析的文本必须 UTF-8、无 BOM/NUL/CR，并通过重复 `--transport-input` 显式登记。 |
| `5caf4f22e0264b3f9a9d67a06432f655` | prepare 完成；runner 在 `akshare_financial_slice` 阻断，生产快照当时缺 provider 3 的两条财报 egress 规则。 | 候选侧必须在 provider I/O 前复用持久化 `preview_route`，逐一验证 provider row × dataset × host × deployment region。 |
| `11fa71b43e504660b2f77a6ff7a31d28` | fresh prepare 已恢复最新生产只读快照，但 `universe` exporter 在 internal Docker network 内调用 provider-backed 市场日历，Tushare/Akshare 均无出口，最终 `S6_TARGET_SESSION_UNAVAILABLE`。 | prepare 的 target date 必须由生产者已封存的 current publication graph 推导；禁止依赖 provider 出网、主机 wall clock、`date.today()` 或原始表 `MAX(date)`。 |

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
5. **资源与时间**：后续证据阶段继续要求至少 12 GiB；昂贵构建前另要求至少 24 GiB，其中 12 GiB 是构建保留量，确保构建完成后仍有
   12 GiB 供 provider、数据库、bundle 与 validator 阶段使用。两个阈值均写入 release policy 和报告观察值，由 validator 对账；
   不允许以构建后清理全局 Docker cache 代替容量准入。可用内存至少 512 MiB，timeout 层级合法、时钟带时区，隔离 PostgreSQL
   `clock_timestamp()` 与应用时钟差不超过 5 秒。
6. **外部状态**：冻结 provider settings、N=1/2N=2 财报预算、隔离 DB/Redis 身份、CI run 和两个生产周期入口的 disabled 状态。

## Prepare target-date authority

`universe` exporter 在单个 PostgreSQL `REPEATABLE READ READ ONLY` 事务中读取三类 `current` pointer、精确 publication header、
`CandidateRawAuditManifest`、Task Monitor 结果、价格 publication members 与其 `PriceBar` 事实。三类 pointer 必须共享从 publication run ID
确定性派生的 activation ID；manifest 必须共享同一个 task attempt，并与成功 Task Monitor 的 run、attempt、publication IDs、hashes、
member counts、source timestamps 和 dataset coverage 摘要逐项一致。Task Monitor 的 bounded JSON 与历史 Python literal 两种文本编码均只用
安全解析器读取，malformed/truncated 结果失败关闭。

价格 target date 只允许来自上述 publication 精确选中的、内容 hash 一致的 `1d/none` 价格事实的唯一 `bar_date`，且 publication
`as_of` 必须等于中国市场 15:00 收盘对应的 UTC 时点。11 个停牌证券之类的动态缺口只有在 publication scope blocks、coverage 计数、
publication hash 与 Task Monitor dataset summary 全部一致时才允许作为解释明确的 partial dataset；不得写死证券或把未解释缺口吞成成功。
该读取不访问 provider、不排队任务、不写建议，也不以数据年龄门槛替代 producer evidence。任一图节点缺失或漂移统一返回
`S6_CURRENT_MARKET_PUBLICATION_TARGET_INVALID`，外层保留候选 universe export 的稳定阻断语义。

## 候选迁移阶段

`isolated_database_migrations` 位于候选镜像身份与环境 preflight 之后、所有 provider evidence stage 之前。迁移必须在候选镜像中通过
固定的 `scripts.manage_vps_migrations migrate --noinput` 命令执行；Django 的 `DATABASE_URL` 在这个阶段只能绑定
`MIGRATOR_DATABASE_URL`。阶段同时核对 `agom_release_rehearsal_*` 数据库名、`agom-s6-postgres-*` 隔离 host、当前 PostgreSQL
container ID、连接的实际数据库身份和 `agomtradepro_migrator` session role。配置 URL 对了但实际连接身份不符仍然阻断。

迁移报告 `isolated_database_migrations` 只保留候选 SHA/image、隔离数据库名/host/port/container ID、固定迁移命令与 migrator role、
`database_address` 是从隔离 Docker network inspect 得到的合法 IP；数据库身份、`pending_before`、`applied_migrations`、`pending_after` 和阶段时间不得包含 URL、密码或 env 内容。列表必须排序且无重复；
`pending_after` 必须为空，`applied_migrations` 必须与 `pending_before` 完全相同。`pending_before=[]` 允许无迁移的 noop；non-empty
列表表示该 disposable snapshot 在这次运行中应用了候选迁移。

迁移完成后，launcher 立即用 runtime `DATABASE_URL` 再运行候选镜像中的现有只读数据库 preflight。只有同一 database/container/image
身份仍成立且 migration graph 无 pending 时，才可开始 provider stage。该后置 preflight 不运行 migration，也不写业务数据。
迁移阶段中断或提交结果不确定时不得重放同一迁移尝试；保留失败证据并使用新的 disposable 数据库与 fresh attempt。旧的
`REHEARSAL_WRITE_MIGRATIONS_PENDING` attempt 不通过手工迁移后续跑来补成完整证据。

## 阶段 × 六类矩阵

“已有”表示当前代码或已有门禁执行断言；“无资源”表示该阶段不触碰该类资源，
这是显式契约而不是静默跳过。

| 阶段 | 文件系统 | 传输编码 | 网络出口 | 身份与密钥 | 资源与时间 | 外部状态 |
| --- | --- | --- | --- | --- | --- | --- |
| `build_only` | 已有：`_build_image` 拒绝缺失/多份 report 与 image tar；remote builder 校验归档。 | 已有：起跑前检查所有显式登记的 `--transport-input` 为 UTF-8/LF；未登记 transport 输入使 CLI 失败关闭。runner 自身启动前的 wrapper 边界见未验证风险。 | 已有：SSH/build host 由实际连接、host-key 交换及 build 命令失败关闭；没有额外 provider 请求。独立 allowlist preview 边界见未验证风险。 | 已有：`_validate_inputs` 只接受 regular password file；prebuild 同时验证 remote builder 所需 `paramiko` 可导入，缺失时在 SSH 前以稳定码阻断。构建前校验受治理的 Docker policy、默认 context 与 Unix socket、client/server 版本；拒绝 Docker Engine 29.3.0/29.3.1，构建显式使用 legacy builder，并核对输出标记，禁止 BuildKit 默认路径、inline cache 和自动回退。版本、endpoint 或模式不符均以稳定码阻断且诊断不输出 endpoint/版本细节。 | 已有：prebuild 要求 24 GiB，明确保留 12 GiB 构建预算和 12 GiB 后续阶段余量；remote builder 自身仍保留 12 GiB `/var/lib/docker` 硬门槛与显式 build timeout。 | 已有：`_candidate_sha` 要求 exact SHA 和 clean tree；候选 exporter 从 exact Git blobs 准备隔离 source snapshot，不对原工作树 chmod；build-only 禁止部署。 |
| `docker_identity` | 已有：`_freeze_provider_settings_snapshot`、`_write_identity` 以排他写/哈希/只读 mode 冻结输入。 | 已有：统一门禁检查冻结 env/JSON/unit/identity 与登记传输文件。 | 无资源：仅检查本地候选镜像，不出网。 | 已有：`_candidate_container_gid`、OCI revision/image ID/release tag 精确绑定。 | 已有：命令 60 秒上限；统一门禁检查预算关系。 | 已有：checkpoint binding 绑定候选、输入摘要和隔离环境身份。 |
| `isolated_database_migrations` | 要求：候选身份只读挂载；仅迁移结果 JSON 进入独立输出目录并密封。 | 要求：校验必要 DB identity 后，最小化重建 migrator stage env；私有 `0400` 文件只允许 DB identity、Django `SECRET_KEY` 与历史 migration 可能需要的 `AGOMTRADEPRO_ENCRYPTION_KEY`。provider/API secret 不进入 stage env，任何 secret 都不得进入 argv、report、诊断或 release bundle；报告 schema 拒绝额外字段。 | 要求：不注入 provider env/凭据/路由，迁移命令只访问精确绑定的 disposable PostgreSQL；生产 entrypoint 另等待精确绑定的隔离 Redis。该 stage 与其他 S6 stage 复用非 internal network，网络层外连未物理封禁，属未验证风险。 | 要求：候选 image/SHA、数据库名/host/IP/port/container ID 和 migrator role 精确绑定；迁移只使用 `MIGRATOR_DATABASE_URL`。 | 要求：独立 stage timeout 和统一资源门禁；超时/unknown commit 保持阻断，不自动重放。 | 要求：`pending_before/applied_migrations/pending_after` 精确对账；迁后立即用 runtime URL 做只读 migration preflight。 |
| `provider_probe` | 已有：`_invoke_container_stage` 校验目录 inode、group write 窗口并在退出时密封。 | 已有：统一门禁在阶段前检查 env/冻结输入/transport bytes。 | 已有：候选动态探针复用 `provider_policy_and_routes`；stage 自身继续保留 response evidence。 | 已有：完整 identities digest、quote/valuation provider ID 与候选镜像绑定；Config Center provider policy 只读解析。 | 已有：sample 50、max dispatch、provider timeout 与外层 stage timeout 层级。 | 已有：冻结 provider settings，禁止从 live 设置静默漂移。 |
| `response_replay` | 已有：provider probe 与 unit contract 只读 mount；报告/identity/hash 复核。 | 已有：统一门禁。 | 无资源：只重放已留存响应，不出网。 | 已有：probe SHA、unit contract SHA、candidate/provider digest。 | 已有：stage timeout；内存/磁盘由统一门禁覆盖。 | 已有：只消费同 attempt 前缀，checkpoint 防跨候选复用。 |
| `full_universe_capacity` | 已有：独立 stage 输出目录，报告密封并哈希。 | 已有：统一门禁。 | 已有：模型行情 bulk route 由候选动态探针预览，容量阶段仍执行真实 provider 契约。 | 已有：quote/valuation provider row 与 identities 一致。 | 已有：请求、窗口、deadline、lock wait、dispatch 均显式；容量阶段单独运行以免并发污染测量。 | 已有：动态 universe/target date/provider snapshot 被报告绑定。 |
| `production_policy_parity` | 已有：只读挂载启动时冻结的 provider settings，而不是可变源文件。 | 已有：统一门禁检查冻结副本。 | 已有：`provider_policy_and_routes` 同生产组合只读执行。 | 已有：raw file SHA 与 canonical payload SHA 双绑定。 | 已有：stage timeout 与统一资源门禁。 | 已有：生产策略 snapshot 与候选报告精确对账；两个周期入口必须 disabled。 |
| `isolated_postgresql_write` | 已有：独立输出目录；所有身份文件只读 mount。 | 已有：统一门禁。 | 无外网：只连接已绑定的隔离 PostgreSQL/Redis network。 | 已有：`_preflight_isolated_database_container` 和 `preflight_isolated_write_rehearsal` 绑定容器、DB、host、candidate。 | 已有：迁移阶段及迁后只读 preflight 确认 migration graph 无 pending；写入事务回滚由本阶段检查，DB clock 由动态探针检查。 | 已有：`AGOM_RELEASE_REHEARSAL_DATABASE=1`、network alias、container ID 在并行组前复核。 |
| `github_ci_evidence` | 已有：`seal_container_input_tree` 按 descriptor 设置并复核 `0550/0440`；财报 mount 前 `verify_container_input_tree` 再次只读复核。 | 已有：统一门禁；GitHub artifact 下载内容另由 collector 的 schema/hash 校验。 | 已有：GitHub API/下载由 collector 访问，仓库/run ID 固定，连接或下载失败即关闭；独立 host allowlist preview 边界见未验证风险。 | 已有：exact SHA、repository、run ID、provider identities 和 artifact 节点契约。 | 已有：max age 24h 与 stage timeout。 | 已有：五组 CI、要求节点、零 skipped/failure/error 由 collector/validator 对账。 |
| `akshare_financial_slice` | 已有：CI 输入树 descriptor 二次复核；candidate output 独立目录；双 body store/hash/size/RawAudit 验证。 | 已有：统一门禁。 | 已有：复用 `_require_akshare_financial_egress_routes`；逐一检查 provider ID、`equity.financial.fact`/`equity.financial.source-time`、`datacenter.eastmoney.com`、公开 deployment region。 | 已有：AKShare active row、完整 identity、artifact secret ref 可解析且不输出值。 | 已有：N≤1、2N≤2、200 行、stage timeout；统一门禁复核时钟/资源。 | 已有：预算 loader、owner-approved contract、两周期入口 disabled；不修改规则或开关。 |
| `financial_scope_capacity` | 已有：独立 stage 输出；scope report 与加密 capture 以相对路径、大小和 SHA-256 组成 bundle graph，拒绝 symlink、特殊文件和未列出的 artifact。 | 已有：统一门禁检查 provider identity、release manifest 与 stage inputs。 | 已有：调用既有 scope-discovery use case，仅按其隔离环境 pre-egress owner event 读取全量活跃证券的 financial/source-time 数据集。 | 已有：candidate/image、完整 provider identities digest、release universe 与 financial universe 分别绑定；该 capture authority 不冒充 production 双人 review。 | 已有：每只证券 2 个逻辑请求、最多 4 次物理尝试，完整计数和阶段 timeout。 | 已有：只连接带 release guard 的 disposable PostgreSQL；允许 raw capture/audit 与加密 artifact 写，事实表和 publication 写入必须为零。 |
| `bundle_build` | 已有：只接收已验证报告；prebuild/final 环境报告与其 SHA-256 图一并复制；`_freeze_bundle` 拒绝 symlink 并将文件设只读，`bundle_tree_digest` 绑定路径/大小/hash。 | 已有：统一门禁。 | 无资源：本地组装，不出网。 | 已有：candidate/image/date/universe/provider/settings 全身份写入 manifest。 | 已有：固定 120 秒 timeout 与磁盘门禁。 | 已有：环境报告属于 required reports；policy 和 manifest builder 精确对账。 |
| `release_validator` | 已有：冻结 bundle 在 validator 前后重算 tree digest，防验证后替换。 | 已有：统一门禁。 | 无资源：本地验证，不出网。 | 已有：validator-owned receipt、manifest SHA、candidate image ID 与 OCI revision。 | 已有：固定 120 秒 timeout。 | 已有：release policy 的 required reports、schema、freshness、完整阶段 × 六类矩阵、prebuild 摘要和 CI 节点全部复核。 |

## 稳定码与聚合语义

- 宿主静态问题：`REHEARSAL_STAGE_FILESYSTEM_ENTRY_INVALID`、
  `REHEARSAL_STAGE_TRANSFER_ENCODING_INVALID`、
  `REHEARSAL_STAGE_IDENTITY_OR_SECRET_CONTRACT_INVALID`、
  `REHEARSAL_STAGE_RUNNER_DEPENDENCY_MISSING`、
  `REHEARSAL_STAGE_DISK_HEADROOM_INSUFFICIENT`、
  `REHEARSAL_STAGE_MEMORY_HEADROOM_INSUFFICIENT`、`REHEARSAL_STAGE_CLOCK_INVALID`、
  `REHEARSAL_STAGE_TIME_BUDGET_INVALID`。
- Docker 构建契约：`REHEARSAL_DOCKER_BUILDER_POLICY_INVALID`、
  `REHEARSAL_DOCKER_BUILDER_PREFLIGHT_FAILED`、
  `REHEARSAL_DOCKER_BUILDER_MODE_MISMATCH`、`REHEARSAL_DOCKER_BUILD_FAILED`。
  远端只打印稳定码；Docker 版本与 endpoint 只进入经过 validator 校验的 build observation。
- Candidate source CLI 将快照、receipt、密封与 exporter 前复核错误映射为 `S6_CANDIDATE_SOURCE_*`；Docker exporter 失败映射为
  `S6_CANDIDATE_EXPORT_PRODUCTION_FAILED`、`S6_CANDIDATE_EXPORT_UNIVERSE_FAILED` 或
  `S6_CANDIDATE_EXPORT_CONTRACT_FAILED`。wrapper 应消费 CLI 的稳定错误码；兼容 shell 必须复用受测 helper，不得自行拼接 `$mode_FAILED`。
- 候选动态问题：`REHEARSAL_STAGE_MODEL_MARKET_ROUTE_INVALID`、
  `REHEARSAL_FINANCIAL_SLICE_EGRESS_ROUTE_REQUIRED`、
  `REHEARSAL_STAGE_PROVIDER_IDENTITY_INVALID`、
  `REHEARSAL_STAGE_FINANCIAL_SECRET_CONTRACT_INVALID`、
  `REHEARSAL_STAGE_DATABASE_CLOCK_INVALID`、
  `REHEARSAL_STAGE_FINANCIAL_BUDGET_INVALID`、
  `REHEARSAL_STAGE_PERIODIC_ENTRYPOINT_INVALID`。
- 报告 malformed 使用 `REHEARSAL_STAGE_DYNAMIC_PREFLIGHT_REPORT_INVALID`；未登记阶段使用
  `REHEARSAL_STAGE_ENVIRONMENT_CONTRACT_MISSING`。所有探针跑完后才返回总阻断码。
- 候选动态探针必须把报告排他写入 `/run/agom/stage/dynamic-stage-environment-preflight.json`；runner 只从绑定的 regular file
  读取并校验 schema/allowlist。容器 entrypoint、readiness 和框架日志均不再属于 JSON 传输契约，stdout 噪声不能造成误报。

## 未验证风险与下一轮门槛

- 本清单只覆盖已知六类，不能证明环境假设已经穷尽；未知类别风险必须保留在每次台账与交接中。
- Windows 本地不能证明 POSIX symlink race、descriptor ownership、非 root 容器读取和实际 mode；相关正反例必须由 Linux CI 执行，
  下一轮 fresh S6 再提供真实容器证据，不能把 Windows skip 计作通过。
- runner 无法在自身启动前检查启动它的 wrapper；candidate source 已由 attempt planner v2 强制创建并绑定到计划，exporter 由 tracked CLI
  在调用 Docker 前复核，但更外层上传/执行链仍必须在发送端复用同一 UTF-8/LF 规则，并把每个实际输入通过
  `--transport-input` 交给 runner 复核。未登记即输入校验失败。宿主应先用 `requirements-ops.txt` 创建 attempt 私有虚拟环境；
  `paramiko` 固定到上游删除 RSA/SHA-1 支持的不可变提交 `a4489456b6f65281e172380cc4826cee5e851dbb`
  （包版本 `5.0.0`）；runner 起动后还会独立复核该版本，因此错误解释器、漏装依赖或旧版依赖会在远端构建前失败关闭。
  私有 venv 的源码获取仍依赖 GitHub 可达性，该 launcher 前置边界须由 prepare/bootstrap receipt 记录，不能记作 runner 自证。
- build host 的 SSH/DNS/host-key 路径和 GitHub artifact host 仍缺独立的无副作用 allowlist preview；当前由实际阶段失败关闭，
  不能宣称这些外部依赖已被统一门禁完全覆盖。
- migration stage 仅约束容器内不注入 provider env、凭据与路由，并由命令连接精确绑定的隔离 PostgreSQL；它与其他 S6 stage
  共用非 internal network，尚未用网络策略物理阻断或验证外连，不能据此声称网络层零外网。
- 12 GiB 构建保留量来自当前镜像构建的实测量级并有 24 GiB 前置门槛保护，但它不是未来镜像大小的无界证明；若构建工作集继续增长，
  remote builder 和构建后统一门禁仍会失败关闭，并须先做容量测算或扩容，不能降低 12 GiB 后续阶段余量。
- legacy builder 是 Docker CLI 的过渡路径，当前 policy 将 CLI 限定在 29.3.2 至 30.0.0 之前；升级 Docker CLI 前必须先迁移到已验证的独立 builder。Engine 29.3.2 是本次上游修复的最低版本；本地契约测试不能替代目标 VPS 的只读版本核验和安全版本 S6 实证。
- 本门禁在本地与 CI 通过后仍不得称为 S6 实证；必须等待下一轮新候选，从 fresh production snapshot、fresh inputs、fresh attempt
  且禁止 `--resume` 跑完整阶段序列。当前已准备或历史 attempt 均不能补记为本门禁证据。
