# S6 预检、续跑和诊断

本规范对应 `scripts/run_release_rehearsal.py`。目标是让同一候选的环境故障或后续阶段失败可恢复，避免重复构建、重复 provider 调用；不改变业务验收门槛或部署审批。`isolated_database_migrations` 是有状态写入阶段：只有报告和检查点证明迁移阶段完整成功、目标 container ID 未变时，后续阶段才可按普通检查点恢复；迁移阶段被启动但结果不明时绝不能 `--resume` 重放。

## 操作方式

每次全新 S6 先由仓库内规划器分配独立 attempt。省略 `--attempt-id` 时生成 UUID4；输出的 root、evidence、
PostgreSQL/Redis/network/volume/database 和 provider export 临时路径必须作为本次 prepare 与 launcher 的唯一输入，
不得从上一轮脚本做字符串替换：

```text
python scripts/plan_release_rehearsal_attempt.py \
  --candidate-sha <40位候选SHA> \
  --attempts-dir /opt/agomtradepro/rehearsals \
  --workspace <exact-clean-checkout> \
  --container-gid <candidate-GID> \
  --reserve
```

`--reserve` 原子创建 attempt root 和只读 `attempt-plan.json`，随后立即从 exact Git blobs 创建计划内的
`candidate-source` 与只读 receipt；缺少 workspace/GID 时拒绝 reserve。已存在目录、symlink、脏工作区或碰撞均失败关闭，
不删除旧证据。
同一 attempt 续跑必须显式传入原 `--attempt-id --resume`，并要求计划逐字节一致。相同 SHA 的新尝试使用新 attempt ID，
因此资源和 `/tmp` export 路径互不覆盖。

## 候选 exporter 源码准备

每个 fresh prepare 由上述 planner 强制调用 tracked CLI，从 exact candidate commit 的 Git blobs 建立独立源码快照；工作区必须位于该 SHA 且 clean。
快照不含 `.git`、ignored 或 untracked 内容，拒绝 symlink、gitlink 和特殊项。只对新快照调用
`seal_container_input_tree`，按 candidate GID 密封为 POSIX `0550/0440`；绝不递归修改原 clone 的权限。示例：

receipt 不包含源码或秘密，记录 candidate SHA、快照 tree SHA-256、receipt 内容 SHA-256、GID 和密封模式。每次 Docker exporter 启动前，必须使用同一 CLI 的
`--run-export`（或先用 `--verify-only` 做额外只读检查）；`--run-export` 会再次校验 receipt SHA、tree digest、candidate、GID 和 descriptor mode，
并验证只读挂载恰好指向 `/candidate-src`。每条 exporter argv 必须且只能在 Docker image 之前包含与镜像身份一致的非 root
`--user <container-uid>:<candidate-GID>`，同时传入正数 `--container-uid` 和不可变的
`--execution-image sha256:<64 hex>`。该镜像只提供 prepare 阶段的依赖运行时，当前取自已部署生产 Web 容器的精确 image ID；
候选代码身份由只读 source snapshot 与 receipt 绑定，不能把 execution image 记作候选镜像。候选镜像随后由 S6 build 阶段生成，
继续接受独立的 revision/image/receipt 校验。export manifest 必须分别记录 execution image ID、candidate SHA、source tree digest
和每个输出摘要。生产 Dockerfile 当前将 `appuser` 固定为 UID 1000。
导出 stdout/stderr 进入 attempt 私有日志文件，命令只向 wrapper 返回稳定错误码：
`S6_CANDIDATE_EXPORT_PRODUCTION_FAILED`、`S6_CANDIDATE_EXPORT_UNIVERSE_FAILED` 或
`S6_CANDIDATE_EXPORT_CONTRACT_FAILED`。Shell wrapper 应直接消费 CLI 错误码；兼容 wrapper 必须 source
`scripts/shared/s6_candidate_export_failure.sh`，禁止自行拼接 `$mode_FAILED`。

## Fresh prepare wrapper v2

planner `--reserve` 已生成只读 `attempt-plan.json`、候选源码快照和 receipt 后，执行：

```bash
bash scripts/prepare_release_rehearsal_attempt.sh --plan-file <reserved-attempt>/attempt-plan.json
```

wrapper 只接受 planner v2 的规范字节和 plan 内资源/path，不会自行 reserve，也不会删除或回滚 reservation。
当前 checkout 必须是 plan 绑定的 exact clean candidate；`<reserved-attempt>/inputs-private` 预先只放置权限为
`0700` 的目录及 `0600` 的 `runner.env`、`vps-password.txt`。失败会保留 attempt、日志和安全状态，供诊断；需要重试时应 reserve 新 attempt。

生产 Web 容器的 immutable `sha256:<64 hex>` image ID 只作为 exporter 依赖运行时记录；每个 mode 都由快照 helper
通过 `--run-export` 在挂载前复核 source receipt/tree，并传入唯一的非 root `--user UID:GID`。wrapper 先用 Web 容器内的
只读事务查询当前数据库名，再与生产 PostgreSQL 的 `current_database()` 交叉核对；它只对该生产库执行 `pg_dump`，并恢复到
plan 绑定的独立 PostgreSQL 容器和 volume。候选 exporter 在三个 mode 启动前才加入独立 `--internal` prepare network；该网络只连接
隔离 PostgreSQL 的 attempt 派生只读别名，不连接生产网络或 Redis。隔离快照上引导的 `agomtradepro_s6_exporter` 角色没有写权限，
每个 exporter 事务还强制 `default_transaction_read_only=on` 与 `transaction_read_only=on`。

生产 Web 的 `Config.Env` 只在内存中解析。`provider.env` 只保留后续 S6 provider 阶段的明确白名单：Tushare token/URL/request mode、
部署区域、显式 HTTP(S) proxy 和 `DJANGO_SETTINGS_MODULE`；生产 `SECRET_KEY`、数据库 DSN、Redis 配置及未知 token/API key 不进入该文件。
`prepare-export.env` 与 `provider.env` 分离，只包含新生成的 rehearsal Django/encryption key 和连接隔离只读数据库所需字段；三次 exporter
只挂载前者，不接收 provider token、真实生产加密密钥或 Redis 环境。后续 `isolated-postgres.env` / `isolated-migrator.env` 才组合
隔离 DB/Redis 身份、provider 白名单和需要读取快照加密数据的 production encryption key。三个 exporter 成功后 wrapper 断开隔离 PG
并删除 prepare network；失败会保留 attempt、容器、volume、网络与诊断供调查，不回滚 planner reservation。

`production`、`universe`、`contract` 三个 mode 重新生成/交叉验证 settings、identities、unit contract、动态 universe 摘要及 runner
参数契约。安全 `prepare-status.json` 与 `prepare-receipt.json` 记录 execution image ID、候选 source/output 摘要、prepare network/PG alias
及稳定阶段状态，不写入环境变量或密钥值。

该流程的信任边界是已经通过 exact-SHA 代码评审和 CI 的候选：source snapshot 内同时包含 exporter 与 snapshot verifier，因此它不能作为
执行任意不受信代码的独立沙箱。若将来允许未评审候选进入 S6，必须把 verifier 固定到候选之外的 operator-owned 工具链。当前单元测试也不能
替代 Linux Docker 的真实 UID/GID、internal network、PostgreSQL privilege 和失败资源保留验证；这些能力仍须由下一次 fresh S6 实证。
六类环境契约覆盖的是已知假设，不证明未知环境类别已经穷尽。

该门禁仅适用于新的 fresh attempt；不得为历史 attempt 追加成功 receipt，或据此改变其状态。

首次运行必须从候选 checkout 内直接执行 `scripts/run_release_rehearsal.py`。复制到仓库外的 launcher 会以
`S6_LAUNCHER_PROVENANCE_INVALID` 失败关闭。对于允许检查点恢复的失败，先修复具体环境问题，再使用**完全相同的参数和输出目录**，追加 `--resume`。
所有经 SSH/pipe 传输后执行或解析的脚本与配置必须分别用 `--transport-input` 登记；该清单及每个文件摘要属于
checkpoint binding，同一 attempt 内缺项或字节漂移会失败关闭。

```text
python scripts/run_release_rehearsal.py <原有完整参数> --resume
```

无需人工选择起始阶段。执行器自动验证检查点，复用已完成的前缀，从第一个未完成阶段继续。最终 validator 始终运行；成功后由 launcher 生成原有非授权 handoff receipt，部署入口继续进行原有独立校验。

候选 migrations 在 `isolated_database_migrations` 阶段内由候选镜像执行，且只连接精确绑定的 disposable 数据库、只使用 migrator URL。阶段通过后，launcher 立即执行 runtime URL 下的只读 migration preflight；迁移阶段报告、镜像身份与 container ID 均进入检查点和 release manifest。旧 attempt 因 `REHEARSAL_WRITE_MIGRATIONS_PENDING` 阻断时，不能手工迁移后续跑来补齐新 required report，应保留原记录并为新 schema 建立 fresh attempt。

若 migration command 尚未启动且检查点完整，按既定前缀恢复规则处理；若 command 已启动后超时、进程中断、容器消失、报告缺失/无效或提交状态无法确认，视为 unknown commit，停止该 attempt，不自动重跑迁移。应从新的 disposable database 和 fresh attempt 重新开始。迁移报告若已成功封存，且后续 provider/validator stage 失败，只能在检查点验证 migration report 与相同 database/container identity 均未变化后恢复；恢复会跳过已完成的迁移阶段。

若仅 validator 失败，续跑不重复 producer 阶段。缺失的本机镜像从已经校验的归档重新加载，不重新构建。

## 复用条件

- 检查点只适用于本工具生成的**同一候选 SHA、同一工作树位置、同一输出目录**。输出目录的绝对路径进入检查点绑定，复制或移动目录后拒绝续跑。工作树必须保持干净。
- 目标日期、全集、provider 身份、单位合同、provider/隔离库 env 内容摘要、数据库/网络、CI run、配额和业务预算必须一致。env 内容只记录摘要，不存储凭据。
- 构建超时与 SSH 密码文件可改变；它们不改变已有业务证据。外层阶段等待与 provider probe 业务预算分别由 `--stage-timeout-seconds` 和 `--provider-probe-timeout-seconds` 控制，两者都会绑定到检查点，不能在续跑中改变。默认外层等待为 3600 秒，provider probe 仍为 1800 秒；任务 deadline、锁等待、请求数及 provider 窗口继续使用各自独立预算。
- 每个成功阶段记录原始完成时间和完整产物树摘要，含原始响应文件。缺失、篡改、符号链接、未来时间或超过 `max-age-hours` 的检查点均拒绝复用。复用不会刷新证据时间。
- 最终报告的身份、内容、CI 和 freshness 继续接受原有完整 validator 校验。检查点本身不是部署凭证。
- 没有检查点的旧版运行不能自动导入；不同 SHA 不能续跑，不能手工补写检查点/receipt 或拼接旧 bundle。

## 阶段与环境

1. 构建前验证执行端 Docker daemon、指定网络、隔离 PostgreSQL/Redis 容器及同一运行遗留的活动容器。
   `--isolated-database-container` 和 `--isolated-redis-container` 必须正在运行并加入指定网络；各自网络
   aliases/DNSNames 必须包含 `--isolated-database-host` 和 `--isolated-redis-host`。隔离 env 必须显式声明并一致绑定
   `POSTGRES_HOST`、`POSTGRES_DB`、`DATABASE_URL`、`MIGRATOR_DATABASE_URL`、`REDIS_HOST`、`REDIS_URL` 和
   `AGOM_RELEASE_REHEARSAL_DATABASE=1`；缺失、重复、旧 namespace 或 URL/独立字段不一致均在远端构建前失败关闭，
   且诊断只返回稳定码，不写出 DSN 或凭据。写入前再次核对数据库容器 ID。检测到活动容器或数据库容器被替换时停止，
   不自动杀掉身份未确认的旧工作。
2. 构建报告和镜像归档独立落检查点；镜像装载失败也不需要重新构建。远端和下载到本机的 build report 文件名均包含
   release tag 与随机 attempt ID；远端返回路径必须与本次调用预分配路径完全一致，清理也只删除该路径，避免同 tag 重试或
   并行构建互相覆盖。
3. 使用候选镜像验证隔离 PostgreSQL 实际连接身份及迁移图，在 provider 请求之前阻断未迁移数据库。数据库查询运行在 PostgreSQL `REPEATABLE READ, READ ONLY` 事务中；任何写入尝试由数据库以 SQLSTATE `25006` 拒绝并映射为 `REHEARSAL_WRITE_PREFLIGHT_READ_ONLY_VIOLATION`。此检查不执行 migrate、不初始化 catalog、不写入业务数据。第一次运行需要先取得候选镜像才能做该精确检查。
4. 真实 provider probe 仍是权威链路验证，沿用真实 payload 和预算；不新增简化 smoke 请求冒充真实请求，也不为预检重复消耗一轮 provider 配额。

已成功且产物完整的 provider 阶段不会在续跑时重复调用。未成功的 provider 阶段没有可复用的成功证据，显式 `--resume` 会在保留失败产物后重新执行该阶段并再次消耗受控配额；必须先确认原失败根因已修复且剩余配额可用。执行器不会自动循环续跑。

相同输出目录使用 OS 文件锁，进程退出会释放；不要删除锁文件来绕过活动运行。未完成目录会移入 `failed-attempts` 的唯一子目录后重试，历史失败产物不覆盖。已完成运行拒绝再次续跑。

## 运维观察与停止条件

- `run-status.json`：业务阶段、已完成阶段和稳定阻断码。
- `activity-status.json`：根目录的安全活动摘要；`run-status.json.activity_status_path` 指向该文件，运维侧无需进入
  `diagnostics` 即可读取活动命令数、阶段标签、已耗时、超时预算、输出字节数与最近心跳。它不包含 argv、环境变量或原始输出。
- `diagnostics/current-command.json`：兼容入口，保存最近一次命令心跳或终态。
- `diagnostics/active-commands.json` 与 `diagnostics/active-commands/<invocation-id>.json`：同时列出所有仍运行的并行命令；
  一个命令结束只移除自己的 invocation，不会覆盖仍运行命令。长命令每约 5 秒刷新；结束后活动集合归零，并在 diagnostics
  根目录按 command 与 invocation ID 保留独立终态。
- `diagnostics` 中每个完成命令保存独立 JSON：保留数据库、权限、网络、超时、语法等白名单诊断分类、稳定业务码及最多八个 traceback 文件名/行号/函数名；不保存原始 stdout/stderr、异常消息、命令参数、token 或 provider 响应。原始响应只留在原有受控证据目录。
- SSH 远端长命令每约 15 秒向 launcher 输出一次只含已耗时与 stdout/stderr 字节数的安全心跳；Python 日志使用即时
  flush，避免非交互管道缓冲造成“长时间无进度”。心跳代表 launcher 有响应，输出字节增长才表示新增输出；两者都不代表业务成功。
- 超时返回 `S6_STAGE_TIMEOUT`。执行器终止自己启动的本地进程树，并尝试移除该命令唯一命名的候选容器。远端构建由原有构建器管理；launcher 被强杀或 SSH 中断时，重试构建前仍需确认远端任务已退出，不能假定远端自动取消。
- 操作者发送 Ctrl-C 时，执行器取消全部活动阶段的进程组并尝试移除各阶段唯一命名的容器，CLI 返回 130；`run-status.json` 写入 `outcome=interrupted` 和 `S6_RUN_INTERRUPTED`，不生成 handoff receipt。若当前阶段为已启动但未确认完成的迁移阶段，不得 `--resume`；其他阶段按同一候选检查点规则处理。
- 失败即返回，不自动启动下一轮。修复后显式续跑；身份改变、证据过期或最终 validator 拒绝时保持阻断。

## 回归与边界

回归覆盖各阶段故障后续跑、不重复构建/已成功 provider 调用、输入漂移、产物篡改、检查点时效、互斥、遗留容器、失败产物保留、镜像重新加载、超时和诊断不泄密。新增检查点模块纳入 deployment 测试选择。

本次修改只修复工具链。Windows 本地回归不代表远端 Linux、真实 provider、生产 PostgreSQL 或生产部署已经验收；上线仍由发布候选的正常验收流程负责。

2026-09-27 本地证据：启动器/validator/bundle/部署入口/CI 选测组合 260 passed、3 skipped；补充阶段前缀与数据库预检实参验证后的启动器回归 57 passed、1 skipped；冻结代码后的启动器与部署入口回归 115 passed、2 skipped。跳过项均为 Windows 无符号链接创建权限。三份生产 Python 文件联合增量 mypy 为 0 回归，全库债务检查为 0 errors；模块地图和全库治理一致性通过。未执行真实 provider 或生产写入。
