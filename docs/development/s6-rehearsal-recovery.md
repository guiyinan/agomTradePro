# S6 预检、续跑和诊断

本规范对应 `scripts/run_release_rehearsal.py`。目标是让同一候选的环境故障或后续阶段失败可恢复，避免重复构建、重复 provider 调用；不改变业务验收门槛或部署审批。

## 操作方式

每次全新 S6 先由仓库内规划器分配独立 attempt。省略 `--attempt-id` 时生成 UUID4；输出的 root、evidence、
PostgreSQL/Redis/network/volume/database 和 provider export 临时路径必须作为本次 prepare 与 launcher 的唯一输入，
不得从上一轮脚本做字符串替换：

```text
python scripts/plan_release_rehearsal_attempt.py \
  --candidate-sha <40位候选SHA> \
  --attempts-dir /opt/agomtradepro/rehearsals \
  --reserve
```

`--reserve` 原子创建 attempt root 和只读 `attempt-plan.json`；已存在目录、symlink 或碰撞均失败关闭，不删除旧证据。
同一 attempt 续跑必须显式传入原 `--attempt-id --resume`，并要求计划逐字节一致。相同 SHA 的新尝试使用新 attempt ID，
因此资源和 `/tmp` export 路径互不覆盖。

首次运行必须从候选 checkout 内直接执行 `scripts/run_release_rehearsal.py`。复制到仓库外的 launcher 会以
`S6_LAUNCHER_PROVENANCE_INVALID` 失败关闭。失败后先修复具体环境问题，再使用**完全相同的参数和输出目录**，追加 `--resume`。

```text
python scripts/run_release_rehearsal.py <原有完整参数> --resume
```

无需人工选择起始阶段。执行器自动验证检查点，复用已完成的前缀，从第一个未完成阶段继续。最终 validator 始终运行；成功后由 launcher 生成原有非授权 handoff receipt，部署入口继续进行原有独立校验。

例如隔离写入因未迁移而失败，应用迁移后续跑会复用镜像、provider、回放和容量证据，重新执行隔离写入及后续步骤。若仅 validator 失败，续跑不重复 producer 阶段。缺失的本机镜像从已经校验的归档重新加载，不重新构建。

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
- `diagnostics/current-command.json`：兼容入口，保存最近一次命令心跳或终态。
- `diagnostics/active-commands.json` 与 `diagnostics/active-commands/<invocation-id>.json`：同时列出所有仍运行的并行命令；
  一个命令结束只移除自己的 invocation，不会覆盖仍运行命令。长命令每约 5 秒刷新；结束后活动集合归零，并在 diagnostics
  根目录按 command 与 invocation ID 保留独立终态。
- `diagnostics` 中每个完成命令保存独立 JSON：保留数据库、权限、网络、超时、语法等白名单诊断分类、稳定业务码及最多八个 traceback 文件名/行号/函数名；不保存原始 stdout/stderr、异常消息、命令参数、token 或 provider 响应。原始响应只留在原有受控证据目录。
- 心跳代表 launcher 有响应，输出字节增长才表示新增输出；两者都不代表业务成功。
- 超时返回 `S6_STAGE_TIMEOUT`。执行器终止自己启动的本地进程树，并尝试移除该命令唯一命名的候选容器。远端构建由原有构建器管理；launcher 被强杀或 SSH 中断时，重试构建前仍需确认远端任务已退出，不能假定远端自动取消。
- 操作者发送 Ctrl-C 时，执行器取消全部活动阶段的进程组并尝试移除各阶段唯一命名的容器，CLI 返回 130；`run-status.json` 写入 `outcome=interrupted` 和 `S6_RUN_INTERRUPTED`，不生成 handoff receipt。后续只能按同一候选检查点规则显式 `--resume`。
- 失败即返回，不自动启动下一轮。修复后显式续跑；身份改变、证据过期或最终 validator 拒绝时保持阻断。

## 回归与边界

回归覆盖各阶段故障后续跑、不重复构建/已成功 provider 调用、输入漂移、产物篡改、检查点时效、互斥、遗留容器、失败产物保留、镜像重新加载、超时和诊断不泄密。新增检查点模块纳入 deployment 测试选择。

本次修改只修复工具链。Windows 本地回归不代表远端 Linux、真实 provider、生产 PostgreSQL 或生产部署已经验收；上线仍由发布候选的正常验收流程负责。

2026-09-27 本地证据：启动器/validator/bundle/部署入口/CI 选测组合 260 passed、3 skipped；补充阶段前缀与数据库预检实参验证后的启动器回归 57 passed、1 skipped；冻结代码后的启动器与部署入口回归 115 passed、2 skipped。跳过项均为 Windows 无符号链接创建权限。三份生产 Python 文件联合增量 mypy 为 0 回归，全库债务检查为 0 errors；模块地图和全库治理一致性通过。未执行真实 provider 或生产写入。
