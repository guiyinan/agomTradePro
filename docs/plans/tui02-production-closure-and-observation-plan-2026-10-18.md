# TUI-02 收口、观察与测试部署方案



> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](../testing/evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。



> 本轮执行边界（2026-10-19）：Owner 最新要求是“通过后把具体部署方案给我确认，先不要部署”。因此本轮只做分批提交、隔离回归和同候选 RC/S6；不执行 VPS 部署、生产迁移、release 切换或观察 T0。下文保留的既往测试升级授权及历史候选不是本轮执行许可。具体候选、镜像、迁移/回滚证据和部署步骤齐备后，提交可审阅方案给 Owner 确认。



方案创建：2026-10-18；当前状态见第 19.2 节（2026-10-22）：尚无完成资格的新冻结候选，未创建 S6 测试账户、未部署或启动观察。以下第 1 节之前保留的是 2026-10-20T07:33:57.544811Z 历史快照，后续结果按第 8 节之后的实际记录读取。

最近实际运行的不可变候选是 `5b31d61ed68e35af8ea24faf97c8ec7987ec3851`（`tui02-rc-5b31d61ed68e`）。正式 RC `39377217739` 已完成但失败：Critical PostgreSQL teardown 失败，Nightly full-unit 在 35 分钟步骤上限终止；该 SHA 未取得完整 RC 资格。

该 SHA 的五组必需 CI、89 项 CI 用户旅程和独立 Publication PostgreSQL 均有成功证据，但它们只绑定 5b31，不可转移到后续 SHA。Nightly 日志更正为收集 21,626 项、21,624 条唯一终态结果（21,622 passed、2 skipped）；没有最终 pytest summary 或 full-unit JUnit，不能据差额推断未执行数或通过。

db79243dbfa3942704e1532a9607bbcc31e8f514 上六模块 flush-fixture 私有叠加的本地 PostgreSQL 阶段运行 421.647 秒后超时，仅见 7 个进度点、无 JUnit；SQLite 阶段未启动。驱动自身的 fast-stop 返回 1，且记录 `stop_confirmed=false`、`pidfile_absent=false`；随后父进程针对该专属目录执行 immediate stop，返回 0，确认 PID 文件消失，独立进程族审计为空。该结果不证明 55 个展开用例或 flush 资格。六模块 imports-only 候选的 Black、isort、Ruff 和官方 test-tier 检查均返回 0，投影未变化；这仅是静态/投影证据，不是 PostgreSQL 通过。下一 clean candidate 拟分两个独立批次纳入六模块 fixture imports 与 AUD05 opt-in/精确六模块 CI 接线；精确 CI R2 仍待独立静态审查，尚无该接线的 workflow 运行、完整 55-case JUnit 或新的冻结候选。此前本地 PostgreSQL trial snapshot 未包含最终精确 CI 接线。Nightly 诊断 R1 被独立静态审查阻断，35 分钟上限尚未修复。

当前没有新的最终候选 SHA/标签，未创建 S6 账户、未部署、未启动 T0，`production_manifest_review_satisfied=false`。Owner 已授权仅在新候选完整 RC 通过后启动的 fresh S6 disposable PostgreSQL 中创建随机测试 superuser；当前尚未创建，账户不得入 Git，凭据仅经内存→stdin→FD3 传递，且该测试身份不替代生产独立复核。14 天冻结、低频逐项验收与会签、无备份约束保持不变。下一候选仍需同一 SHA 完成完整 RC、五组必需 CI、独立 Publication PostgreSQL 和 fresh S6；不得拼接旧 SHA 或本地局部结果。

最近一次本地 full-registry flush-fixture 尝试以 `db79243dbfa3942704e1532a9607bbcc31e8f514` 为来源；它不是最终候选。下列早期批次及后续组件证据只适用于其实际输入，不拼成最终发布资格：

| 独立批次 | 已验证结果与依据 |
| --- | --- |
| 事务测试恢复 `9b622893c…` | 正式 SQLite 配置同序列 2 pass / 1 error → 3 pass；[说明](../testing/tui-rc-contenttypes-order-2026-10-19.md) |
| 估值模块边界 `4c5361d10…` | 150 项回归、四生产文件增量 mypy、默认全债务、官方投影及 89 项 freshness 通过；[说明](../testing/tui-rc-equity-module-bounds-2026-10-19.md) |
| A 股未接线 Domain `07db8e78e…` | 24 项 Domain、增量/全类型及官方地图通过；不含 model/migration/HTTP/交易激活；[紧凑证据](../testing/a-share-ash03-reservation-domain-2026-10-19.json) |
| 非空资产池适配 `e786271a5…` | 原生产 3 个类型反例失败，候选相关 90 项通过；共享四生产文件增量/全类型及官方投影通过；保留真实 PE/PB/CNY 市值；[说明](../testing/tui-rc-pool-owner-adapter-2026-10-20.md) |
| M5 正向读取 `61e7fcbe4…` | 同一精确共享输入的定向 1 项通过，另建副本后原本地预览集 15 项全通过，无错误/跳过；两项 live-AI 按既有规则排除。源码、暂存语义/ITA 和隔离基线未变、服务关闭；[说明](../testing/tui-rc-m5-published-fixtures-2026-10-20.md) |
| A 股数量精度 `6ac0ef537…` | 原数量规则不变，补强两处 Decimal 算术上下文；该文件 79 项单元、增量/默认全类型、架构及增长检查通过；[紧凑证据](../testing/a-share-ash03-quantity-context-2026-10-20.json) |

C1 supporting 计划索引已在 `b19b00074…` 独立提交：完整 clean Git 基线先真实拒绝未注册计划，仅三文件修正后 registry 为 v287 / 62 paths / 79 units / 0 违规，全治理十五节通过；不依赖未提交的 hierarchy 或 INDEX，不改变单位状态、依赖或焦点。

A1 标签 `tui02-rc-a1a50e8c1a18` 保留原失败：正式 RC `39366575649` 的 PostgreSQL 夹具准入失败，Nightly 全量单元在 35 分钟上限终止。日志的 21,368 passed / 2 skipped 只是已完成进度，没有最终 pytest 摘要或完整 JUnit；不得记作全套通过。既有五组自动 CI、89 项用户旅程和独立 Publication PostgreSQL 的成功仍仅属于 A1。

本轮夹具修正只为两个精确登记 API 节点显式开放经原生身份校验的临时 PostgreSQL；默认 SQLite 与 M5 限制、来源证据、权限及发布成员断言保留。五个测试文件的最终 payload 与已完成格式检查的 R3 一致：原守卫组 22 项通过；同一 ab020 私有 Git 来源的 PostgreSQL API 2 项和 SQLite API 2 项通过。SQLite 同进程另跑末尾风险单测 1 项通过，setup/call/teardown 约 0.04/0.02/1.55 秒，只说明本次定向没有复现挂起。第一次串行脚本的 SQLite 已启动后因剩余窗口不足被主动中止，未产生 JUnit；原件保留为未验证，不是业务断言失败。详见[紧凑证据](../testing/tui-rc-native-consumer-fixtures-2026-10-20.json)。

Nightly full-unit 阶段栈诊断 R1 仍是未采纳的私有候选，已被独立静态审查阻断（review SHA `3c5c872927cc67b16b60b512aa9c7147e46dbb8ebdf1f019819b5f80a08f2b3f`）。该诊断不修复或证明 35 分钟耗时根因；后续诊断如另行准备，仍须保留步骤上限、300 秒单例、完整选集和覆盖率，并单独审查。它不是当前六模块 flush-fixture 采用范围的前置项。官方 test-tier 投影须在干净候选中生成并复核。A 股后续 G2B 私有业务补丁不进入本轮冻结范围；以后 dev 提交不得移动旧标签。最终同候选完整 RC、独立 Publication PostgreSQL 和 fresh S6 仍待实际执行，测试身份不得替代生产独立复核。

剩余顺序：核对完整干净来源后冻结不可变候选；在该 SHA 执行正式回归、完整 RC、独立 Publication PostgreSQL 和全新 S6，再生成包含实际 tag/image、迁移/兼容回滚、停机与验收步骤的具体部署方案供 Owner 确认。M5 本地预览含明确绑定的其他任务 WIP，不代替最终候选验证。普通开发不等待 RC/S6；冻结之后发布验证使用独立干净 tag 来源。

旧 `e9ea1c569…` 的 Fast `39271458679`、Consistency `39271459092` 失败及独立 Publication PostgreSQL `39271458779` 成功仍按原 SHA 保留；后续修复不会追认旧失败为通过。历史修复和失败原件见第 7 节及各专项验收说明。本轮继续遵守“先不要部署”。

## 1. 已批准的决策与边界



Owner 在本聊天批准“一次 14 天生产冻结例外，低频任务逐项验收和独立复核”，当时要求与 A 股协调、认证修复和验收规则分批提交，具体部署方案再确认；最新指令进一步明确本轮先完成验证并交付具体方案，未经本轮确认不部署。通用政策批准不能代替实际任务 UAT 或单项风险接受。



已独立核实 Owner 在“观测开发进程”的补充：“现有的vps部署可以随时更新，因为没有实际投入生产”及“不用备份”。“现有的vps部署可以随时更新”发生于北京时间 2026-10-18 22:43:58，晚于本聊天 22:33:08 的初始确认要求。该次授权把 VPS 按测试/演示环境处理，允许既有独立批次持续 code-only 升级。这是历史授权；本轮以最新“先不要部署”为准，完成同候选验证后仍须提交具体方案供 Owner 确认；本次不创建、下载或校验备份，保留数据卷和密钥。此前备份下载及本地校验没有完成，不记作已验证恢复点。



正式迁移观察仍采用已批准的同候选 14 天冻结，真实 T0 加 1,209,600 秒得到 eligible instant；容器启动、部署时间和 up 样本都不能代替 T0。观察对象被升级时，真实重置或结束本轮，不能跨候选拼接。无需再次批准相同冻结政策；目标资格、候选身份、真实采集和逐任务验收仍须成立。当前不执行测试升级；正式迁移资格、逐项验收和新增业务写入的授权边界分别保留。



退出标准真源仍是 `governance/active_plan_registry.json`、Web→TUI 主计划、迁移矩阵、cutover evidence 和 M5 绑定指南。本文件只记录此次实施与发布方案；测试更新免备份不改变正式 Classic 退出的生产 registry 备份门禁。



## 2. VPS 只读核查与 401 根因



核查时间为北京时间 2026-10-18 22:20—22:26；未修改服务、配置、凭据、数据库或观察绑定，SSH 会话已结束。



| 项目 | 实测结果 |

| --- | --- |

| release | `20261008050500` |

| 完整 commit | `d3fdbd6f1ce8a1b77c4ba4fec923d651f4a2b7df` |

| Web image | `sha256:da482ea1210f0b486852e97b83eb7437577aa957efb872b1f06e8c5c725b1996` |

| Web StartedAt | `2026-10-18T12:35:59.755489779Z` |

| Prometheus runtime start | `2026-10-18T12:36:00.849922041Z` |

| health / ready | HTTP 200 |

| decision-ready | HTTP 503，独立业务限制，不能为 TUI 验收改成成功 |

| 匿名 / 现有客户端的外部监控 query | 均由 Caddy 返回 401 |

| 内部采集 | up=1；5 条 M5 rules healthy；迁移原始计数和 task 聚合均为空向量 |

| 保留与网络 | 3w / 4GiB；9090 未公开 |



Caddy 容器缺失 `PROMETHEUS_QUERY_USER` 和 `PROMETHEUS_QUERY_PASSWORD_HASH`，活动 Basic 账号为禁用后备值 `monitoring_disabled`。现有客户端用户名及密码均不匹配；密码只在 VPS 内存中经 libcrypt bcrypt 比对，未输出密码或哈希。



旧 release 的 `deploy/prometheus-query.env` 不存在，root-only 客户端 `/opt/agomtradepro/prometheus-query-client.secret` 存在且为 0600。Caddyfile SHA-256 为 `efdaffa629c24a0e8f04834177fc5e5c229068e206408ecbf7620800da39457e`。这是跨 release 配置持久化缺口；不能据此认定哪次操作首次丢失配置，也不能通过换 Django token 或取消保护修复。



空向量不等于零，up=1 不证明任务遥测合格。旧候选与旧 eligible 时间不计入新窗口。核查时 VPS 仍是旧代码，不能把本地 TUI 交付当作已上线。



## 3. 并行施工和分批提交



A 股协调会话：`codex://threads/01a14268-4d88-75e2-812a-fdbdd60b1b24`。共享 `dev/next-development`，使用独立提交；不新建开发分支、不覆盖 A 股脏树、用户文件或 intent-to-add 状态。重型本地 QA 与 Git/index 窗口串行移交。最初 P1—P3 仅使用指定 scripts/schema/tests/docs，不写 registry 或共享投影；后续 RC 阶段 A 股明确交还完整源码、必要官方投影和 QA/Git 窗口，执行边界及精确交接记录见 RC 分阶段计划。数据库回归只使用隔离测试库，不使用共享业务库。



| 批次 | 提交 / 状态 | 范围 |

| --- | --- | --- |

| P1 认证 | `1c0acfac3f6a9fe7579391159a19f16e05f9900f` | 7 路径；root-only 持久配置、发布前预检、当前及回滚 release 装配、测试和说明 |

| supporting 登记 | A 股 `1c11f8e8595b94d77d4d484c68801b278a5c8398` | 仅登记本方案，不改变验收资格 |

| ASH-02 | A 股 `c2e0227290e51426debfe0d0bec405c805ca0de9` | A 股有限开发范围收口，独立提交 |

| P2 初始验收 | `98dcea40b7326d76aae37b228a2e3deac9242c34` | 8 路径；14 天低频契约与源一致性 |

| 独立工程仪表盘 | `f82cc04c9c88ad01139aa1f3f15a66fa064a897e` | 期间另一任务提交 CI/docs/JS 脚本，未修改本次 TUI runtime 依赖；本任务保留 |

| P3 退出波次 | `505848aa14a51a843b67bfa793870bc64ea06344` | 48 小时低频闭环、官方 catalog 复用、独立回归与专项说明 |



认证：预检先于停服务、迁移、备份或指针变化；复用现有客户端，不轮换密码。在目标 host 内派生/校验 bcrypt，失败即停止；服务端配置原子保存到 release 外并装配新/旧 release。root、0600、普通单链接、精确字段与可接受密码均强校验；hash 不进入日志、argv、仓库或公开报告。



低频：完整绑定候选、精确 task、全部对应路由、波次和到期时间；保留真实 count/null、原始响应哈希、实际 UAT 记录哈希、责任人明确接受风险及独立 reviewer。统计不足为 `insufficient_sample`，错误比较为 `not_applicable`。每项须有真实 TUI 执行，无有效单项证明或有已观测错误则拒绝；高频统计门槛保留。姓名字段是可审阅人工会签，不能代替实际身份或签名。



初始 14 天 v3 查询固定在真实 eligible instant；最终 readiness 重建并精确比对快照及官方矩阵投影，不能缩减任务。48 小时 v2 波次同样重算原始 telemetry、缺陷、计划周期与部署证据；v1 也要求本波全部任务和周期覆盖，保留周期、缺陷、回滚、lineage 和每波最多 10 路由。多个 Classic 路由可共用 task，catalog 仍须精确等于官方投影。当前最终授权使用真实 UTC，历史回放不能取得当前授权。到期检查覆盖已记录波次，旧波例外若到期需重新独立复核，不能自动延期。



本轮官方 catalog 同步只改 source SHA 和移除矩阵已不收录的 `terminal-config` 映射：当前 117 条 Classic route / 100 个可比较 task。同步前旧 catalog 为 118/101；未修改矩阵或旧 cutover evidence，旧证据仍拒绝。



## 4. 验证、失败记录和剩余风险



- P1 单测 121 passed / 2 skipped；Windows 无 symlink 权限导致新认证和既有构建 marker 反例跳过，未记为通过。限定 isort/Black/Ruff、增量 mypy 通过；固定 archive+7 文件候选全库债务为 0。

- P1 共享树全债务曾报 A 股范围两项 nullable 错误，未改其源或债务基线；另行采用固定候选验证，原失败日志保留。

- P2 最终 88 passed；限定格式、增量 mypy、固定 archive+8 文件全债务、catalog check、inventory 均通过。证据 `.tmp/t2a/manifest.json`、同目录日志及 `.tmp/tui02-acceptance-verified.xml`。首次 archive 导出遇 Windows 长路径失败，保留失败记录。

- P2 首轮 34 passed / 37 failed 暴露旧 catalog SHA 漂移；修复测试的官方投影 fixture，未放宽生产门禁。实际 `--require-allow` 仍 DENY 1/10；没有生成生产批准。

- P3 修改前的 recorder/guard 回归 29 passed；初跑 99 passed / 49 failed，其中共享 runtime 漂移使候选来源校验正确拒绝，其余为旧 fixture 范围/新调用参数及重复 vector 负例。共享树另一次启动因 A 股导入循环失败，未运行用例；A 股已确认并修复，未混入本候选。隔离首轮 38 passed / 110 setup errors 来自未创建 `.tmp` 临时父目录，保留日志，未算作通过。其后 158 passed / 4 failed，修正旧测试中的迁移前 task key，并用只读 `GIT_DIR/GIT_WORK_TREE/GIT_OPTIONAL_LOCKS=0` 给 archive 提供正确历史查询根；未改变生产检查器或共享 index。类型检查首次暴露 namespace 重复、未声明类型的 JSON Schema 边界、冗余 cast 与间接导出，已在原脚本内修正，未加 ignore 或抬基线。用 f82 固定 archive 加精确 11 路径 overlay 最终重验。最终结果：162 passed；四份生产脚本逐文件增量 mypy 均 0 regression / 0 legacy，全候选债务 0；isort/Black/Ruff 与 scoped diff check 通过；catalog check 通过，inventory 为 197 templates / 117 route_pages、数据库连接尝试 0。真实 readiness 仍 DENY 1/10；cleanup guard 仅 PASS“没有超过 M0-D 基线的清理”，不是新波授权。证据见 `.tmp/t3q/manifest-complete.json`、`pytest-complete.xml`、`debt-complete.log`、`incremental-ready-1.log`、`incremental-ready-2.log`、`incremental-checked-guard.log`、`incremental-recorder-corrected.log` 及 `*-complete.log`。

- Luna max 实现协作、另一位 Luna max 独立只读审查与主代理复核共同覆盖候选、时钟、原始计数、验证后重开证据、任务范围与普通门槛；不能替代真实用户 UAT。



A 股已接收监控反馈的 98d 历史候选 CI 问题，负责核对 Architecture 边界、Data Center 生成投影、精简 App 启动与 targeted/noDB 原始日志，并作为独立修复批次处理；本任务不调高预算、不越窗修改对应源码/投影。修复若进入新的发布 SHA，同候选 CI/RC/S6 与制品身份必须重验，不能沿用先前局部结果。



未完成：VPS 认证恢复与真实 Linux/Compose/HTTPS 验证、迁移埋点空序列具体原因、同镜像发布预检、实际任务 UAT/单项批准、真实 retained checkpoint、14 天观察、分波退出与 registry 关闭。Linux bcrypt/Compose 实际解析及 Windows 跳过反例仍待目标环境；3w/4GiB 实际连续保留须验证。原始结果/UAT 的 raw-byte SHA 要保留原字节，不能换行转换后沿用旧 hash。



## 5. 具体测试部署执行方案（验证通过并经 Owner 确认后实施）



最近实际运行的不可变候选为 `5b31d61ed68e35af8ea24faf97c8ec7987ec3851`，其标签 `tui02-rc-5b31d61ed68e` 的正式 RC `39377217739` 失败（Critical PostgreSQL teardown、Nightly full-unit 35 分钟终止）。该 SHA 的五组必需 CI、89 项旅程和独立 Publication PostgreSQL 成功证据只属于该 SHA，不能抵消 RC 失败或移用于新候选。db792 上的六模块本地 PostgreSQL flush-fixture 尝试超时且无 JUnit；不能据此声称 55 个展开用例或 registry flush 合格。新候选的 CI 精确调用接线及独立完整 JUnit 仍待准备/验证；新的提交和不可变标签尚未固定。发布包只能来自通过全部适用门禁的干净提交，不能从共享脏树或私有 overlay 打包；不得复用 5b31 的部分证据、失败 attempt 或不同 SHA 的局部结果。



目标：由 `AGOM_VPS_HOST` 指向已核查测试 VPS；user/port 取环境，不在方案保存密码；target `/opt/agomtradepro`（必须与环境一致），compose project `agomtradepro`。方式：`upgrade`、code-only、明确 `-SkipPreDeployBackup`；保留 PostgreSQL/Redis/媒体/Prometheus 数据卷、加密密钥及旧 release/image。无 wipe、SQLite 导入、数据库恢复、凭据轮换、实盘开关、下单、付费 AI、额外回填或 Alpha/decision-repair。



迁移计数口径：以下 28/29 项仅是 2026-10-19 针对当时源码和只读数据库快照的历史比较，不是 db792 或尚未固定的新候选迁移计划；此处不推算当前待执行数量。最终候选 SHA 固定后，仍须对精确候选和目标数据库只读重算有序迁移计划并验证兼容性。以历史只读核查的 VPS 源码 `d3fdbd6f…` 为比较起点，到当时已提交 `e18c796a7…` 的 Git 新增迁移为 28 份：account0067—0068，data_center0090—0103，risk_center0010—0011，simulated_trading0024—0033。E 没有模型或迁移改动。实际待执行数仍须重新只读读取目标 `django_migrations`，不能以 Git 数量或旧 VPS 版本替代线上事实。新纳入的 account0068 分类历史券商回执为未核实；simulated_trading0031—0033增加估值、现金、成本/费用知识状态，其中现金迁移分类既有账户，历史成本保持 unknown。这些迁移带反向丢失保护，不能假定所有 DDL 可撤销；预检须确认旧镜像在新 schema 与 unknown 状态下的行为兼容，不能仅证明字段可读。



2026-10-19 09:50:27 UTC 已补做只读 SSH 核查：运行中的 Web 仍为上述 `d3fdbd6f…` revision、`20261008050500` image 和相同 image digest，未切换服务。PostgreSQL 的显式 `BEGIN READ ONLY` 查询返回 526 条已应用迁移；与 `3b11ed5703e4a9fce55e66ad0de92e92f02e9a05` Git 树比较，有 29 个迁移名尚未登记，较上述历史比较新增 `simulated_trading0034_automatic_trading_invocation`。这是实际迁移表与源码的集合差，尚不是候选 MigrationExecutor 的有序执行计划或 schema 回滚兼容证明。最终候选冻结后仍须在隔离恢复库生成真实计划并验证旧镜像兼容，不能据此直接部署。



本次只读命令、原始输出与比较报告共 8 项在本机持久归档 `C:/Users/muku/.codex/evidence-archives/agomTradePro/2026-10-19/tui02-vps-readonly-3b11ed5703e4/originals.zip`，SHA-256 `8ab6a83b83fdc8722eddbfa6d36cf1f4c020a0c89b78798c528d0179b1fcc3ba`；同目录 `files.json` SHA-256 `3a9c39eaa67cc6052a0b54492b9e4450d2badb9061e722e0760a968d31c1f6f8`，逐项读回验证一致。归档仅本机可用，未上传；查询没有执行迁移、部署、备份或观察绑定。



执行顺序与停止条件：



1. A 股交还 VPS 写窗口后，先只读核对 release/commit/image、数据卷、密钥文件权限、数据库已应用迁移和任务开关。身份与计划不一致先停止并更新范围，不能盲目覆盖。

2. 按既有授权固定最终候选并协调构建/预检窗口，为固定 SHA 发布不可变新 tag `tui02-observation-<最终SHA前12位>`（必须解析成真实标签；已有同名但不同指向则停止，绝不覆盖）；从该 tag 的独立干净源码准备同镜像构建、迁移计划、旧镜像在新增 schema 和知识状态下的兼容性验证及官方 release rehearsal/receipt。不得用其他 SHA 的 CI/S6。当前没有可用的新镜像/receipt，制品验证失败就不切换；不创建备份来替代兼容性证明。

3. 真实源码确认 cold-start 带 `--preserve-protected-schedules-disabled`；但后续 `setup_macro_daily_sync` 会把 daily-sync-and-calculate、check-data-freshness、high-frequency-generate-signal、high-frequency-recalculate-regime 设为 enabled。四项现态和参数必须已启用且语义一致，否则停止并另给最小修复。Celery 与 queued worker 沿用既有授权；wrapper 默认 Celery=true 不能直接覆盖现态。

4. 将真实标签替换占位后，使用仓库发布入口 `scripts/deploy-vps.ps1 -Upgrade -SkipPreDeployBackup -GitBranch <validated-tui02-tag>`，固定源码 SHA、真实 prebuilt tag/image、manifest/receipt、目标日期、universe/provider/settings 摘要和 GitHub run。wrapper 从干净候选 HEAD 获取 `--expected-source-commit`，远端 clone 必须精确匹配；tag 指向与固定 SHA 不同则停止，不能临时改用脏树上传或绕证据。只有已证明新 schema/知识状态兼容的旧 release 才可作为自动代码回滚目标；未经证明不得启动升级。禁用 Alpha/decision-repair 引导。必要的迁移、静态资源、能力目录、TUI registry、bootstrap、周期配置与 superuser reconciliation 均是明确写入，预计短暂停机。

5. 认证 preflight 失败时不进入停服务或迁移。新服务失败时仅按已验证的 schema 兼容性恢复旧镜像/release；不能反向删除保留数据或自动数据库恢复。无法安全回滚时停止服务并报告事实。

6. 发布后核对 health/ready、容器和不可变身份、HTTPS/QLib 身份、数据 freshness、Caddy 账号与认证矩阵、up/rules/保留，以及普通任务与专业入口。匿名/错误凭据 401，正确 query/query_range 200；9090 继续不公开，decision-ready 的独立限制不掩盖。

7. 只读核查迁移原始序列；需要验证埋点的实际安全读取任务列入手工 UAT。不得通过下单、导入或付费调用凑样本。采集缺失保持缺失并定位，不开始虚假 T0。



既有测试环境免备份偏好作为计划输入保留。本轮部署尚未获具体执行确认；同候选 CI/RC/S6、制品身份、测试隔离、代码/schema 兼容回滚及协调窗口满足后，先提交包含真实候选、迁移、回滚、停机和验收步骤的方案给 Owner 确认，收到确认后才能部署。当前缺项是技术前置，未执行或未通过不得报告“部署就绪”。预检失败应停止并修复；若涉及额外任务启用、数据恢复、回填、真实交易或其他新增范围，应列出具体差异并取得相应授权，不扩大既有 code-only 升级边界。



## 6. 正式观察与 TUI-02 完成标准



测试部署成功不等于正式生产资格。目标资格、同候选身份、认证与真实采集成立后，按已批准冻结例外生成官方 deployment attestation、retained checkpoint 和绑定，开始真实 14 天。开发、隔离 QA、下一版构建继续；观察对象冻结，紧急修复或升级按真实重置处理。



eligible instant 后以 `python scripts/check_web_to_tui_cutover_readiness.py --require-allow` 的真实结果验收九项前置与同候选批准。普通任务用统计，低频逐项 UAT/风险接受/独立复核，未通过的任务继续阻断。ALLOW 后再逐波执行 Classic 退出，每波独立候选、至少 48 小时及计划周期、无阻断缺陷、独立复核和回滚，最终 `check_web_to_tui_cleanup_guard.py --require-allow`。



TUI-02 只有在 registry 全部退出项、应完成波次和观察、正式备份/回滚与 sole-owner 最终签字均成立后关闭；不能以认证恢复、本地测试、等待满 14 天或普通测试升级替代。当前未删除 Classic，未生成任何实际 UAT 或任务批准，未关闭 TUI-02。



## 7. 历史修复与失败记录（截至 2026-10-19，当前状态见开头）



与 A 股按精确源码路径、私有数据库及独占 Git 窗口交接；A 股原生 PostgreSQL 端口和库不用于本轮测试。每个私有导出保留基线及 overlay hash，不把多个 SHA 的局部结果拼成候选通过。共享投影及 registry 仍归 A 股协调，不手工改写。



G 批次已独立提交并推送 `2cd7f1efd8761c31edbda1d661e5358cebed7de9`：M5 本地 ORM 夹具在 worker 内进入数据库 blocker，并在 `finally` 关闭本线程连接，保留角色、所有权及远端写入限制。原始私有预览为 `ed032a79bb015e1ddf1619f8b33cb77bc416e1d6` 加五个明确 overlay；并非仅含 G 的干净提交。13 个所选浏览器用例为 **7 passed / 6 failed / 0 setup errors / 0 skipped / 2 deselected**，原来的 13 个 setup errors 未复现，不代表 M5 或 RC 全绿。源码及原始字节证据见 [专用说明](../testing/tui-rc-m5-fixture-lifecycle-2026-10-19.md) 和 [manifest](../testing/evidence-archive-2026-10-19.md#原件定位 "原件：artifacts/tui-rc/m5-fixture-lifecycle-2026-10-19/manifest.json")。提交前默认空白检查与未改规则的 gitleaks 均通过，外来五文件及 ITA 状态未改；完成后 Git 窗口已交还 A 股。



剩余六个用例主体失败另批处理：两例成功操作后的业务状态前缀断言过时；个人服务商创建的服务端栈确认隔离环境缺加密配置；直接读、参数读及详情读取还需捕获实际响应与终态。不得把日历 composition 错误未经逐案证明就当作共同根因，也不以增加 timeout、删除失败或 skip 通过。



ReDoc 和信号问题继续独立验收。ReDoc 初始浏览器实测 document/script 均 200，但经典 script 加载新版模块包时报 `Cannot use 'import.meta' outside a module`，正文始终为空；单独 schema 请求 200，Content-Type 为 `application/vnd.oai.openapi`；JSON 解析失败不能据此认定 YAML schema 有误。兼容版本固定补丁须由既有页面测试及实际渲染证明，不能只验证 URL。信号鲜库有 94 个 active catalog、98 条量纲规则，却没有 MacroFact 或 publication；仍须核对实际 DOM 的资产类别和指标各自数量。合成 fixture 仅允许显式 opt-in 的 loopback、playwright settings、同一 SQLite NAME/TEST.NAME/AGOM 路径，走真实规范化、发布及新鲜度查询，不代表生产数据或真实用户验收。



ReDoc 已独立提交 `1385f109ea41cf4ab9263e0e14d6fc2c681969b5`，H 仪表盘不可用提示为 `00f77c06dba64178c86d524fdd0b8c649a3a191a`，I 导航诊断为 `ef167f4a44d1e48641306627c8ec7174be7b7c8c`；均已推送。H 的 14 项单测、H/I 共用的 4 项实际浏览器检查通过，不能重复计作 8 项。原件在本机仓库外持久归档，逐项位置和哈希见对应[ReDoc](../testing/tui-rc-redoc-evidence-2026-10-19.json)、[H](../testing/tui-rc-dashboard-evidence-2026-10-19.json)、[I](../testing/tui-rc-navigation-evidence-2026-10-19.json) 索引；不表示远端已持有归档。



后续业务阻断反馈已提交 `f30b239e580dc3faa16544660442c3265be7b242`，信号本地 RC 测试夹具已提交 `cddd39816c8f7f1517e23cecbcb7b3060b32bc7c`，均已推送，分别见[阻断反馈说明](../testing/tui-rc-blocked-feedback-2026-10-19.md)和[信号夹具说明](../testing/tui-rc-signal-fixture-2026-10-19.md)。新增 M5 账户流程仍在私有验证，未报告通过。A 股已明确将下一批股票池能力留作后续开发，本轮必要修复完成后固定候选；之后 `dev` 的新提交不自动移动本轮候选。



快速反馈选择器已独立提交并推送 `78c7b81872a64e8cfaaca623bf0faa8c91c725b0`。原候选在 Python 3.11/3.13 各有 74 passed / 43 setup errors：需要应用服务器的浏览器用例被交给普通 pytest，登录夹具连接 localhost:8000 失败，未进入测试主体。只修正 ci-only/shared-only 快速分支漏用既有目标过滤器的问题；67 项选择器单测、格式、增量类型和全库债务通过，独立审查完成。完整 RC 的托管服务器、全部 UAT、无跳过和至少 20 项门槛不变。实际源码及失败原件见[专用说明](../testing/tui-rc-ci-selector-2026-10-19.md)和[证据索引](../testing/tui-rc-ci-selector-evidence-2026-10-19.json)，不构成最终候选 RC 通过。



该 SHA 的 Fast Feedback `39226273177`（含 Python 3.11/3.13）、Architecture `39226273166`、Consistency `39226273160` 和 Security `39226273158` 均已真实 success。Alpha 运维概览权限随后独立提交并推送 `3b11ed5703e4a9fce55e66ad0de92e92f02e9a05`：两项 staff-only 读取与可见性测试 2 passed，保留普通用户 403 和角色反例；格式、官方 inventory/catalog、两生产文件增量类型及全库债务、官方 TUI build/check 通过。parent 独立核对 127 个 runtime manifest 输入及其中 125 个未改输入，采用后共享官方 check 和两生产文件规模门禁通过；三项 JS 未纳入本批。原 DTO 断言失败、过期 manifest 和 CRLF 规范化过程均保留，见[权限说明](../testing/tui-rc-alpha-audience-2026-10-19.md)和[证据索引](../testing/tui-rc-alpha-audience-evidence-2026-10-19.json)。不同输入的局部结果不相加为最终 RC 资格。



随后 Alpha SHA 的 Fast Feedback `39230236531` 实际因一条旧 Node 断言失败（175 passed / 1 failed）：失败操作仍等待“读取完成”。修正既有 F6/F9 测试的这一处状态等待已独立提交并推送 `558982f121b489817405221f01f900c96e6d5835`；targeted 2 项及三个正式 Node 目录全部 176 项实际通过，0 failure/error/skip。原超时、F6 不重复请求、F9 展开及第二次提交的断言保留，生产源码未变；私有输入、原 CI 失败、错误的 driver 计数与独立 XML 复核均见[专用说明](../testing/tui-rc-node-f6-status-2026-10-19.md)及[证据索引](../testing/tui-rc-node-f6-status-evidence-2026-10-19.json)。



A 股在单独短窗提交并推送 `cfcc2f374ed520fe532d0271d865765c0bff9541`，仅为 model-history API 夹具及两份 compact 说明；没有纳入股票池运行时代码或投影。该批本地 55/3 项证据来自组合副本，不能当作纯提交的完整验证，最终 RC 的 API 回归仍需实际通过。共享 index 已空且外来文件/ITA 状态保留，窗口已明确交还本任务。



M5 run08 的缺确认失败源于 dashboard 链接参数未填入可见表单；r4 填写真实控件后，run09 已越过确认，但在原 60 秒完成断言处实际得到“操作未完成，请检查结果后重试”，最终 1 failed / 0 skipped。账户数仍为 6，唯一测试名称匹配 0；server 已清理。两个 POST 的传输 200 没有证明业务成功；本次没有捕获确认提交 envelope 或关闭 context 前的失败画面，不能声称直接观测到 503。只读查明该鲜库没有 runtime profile/创建配置 definition；另 canonical 创建事务明确仅支持 PostgreSQL，与正式 RC 浏览器套件的 SQLite 不兼容。该 UI create/delete 前置只存在于未提交私有候选，不是原参数化读取任务的职责。下一修订只提供生命周期受控的本人账户测试夹具，真实 UI 读取及所有权/清理断言保留；不种虚构配置、降级生产事务、改变 RC 后端，或把 ORM 测试行当作 canonical 创建、RawAudit 和 authority 证据。新候选尚待实际 QA 和独立复核。



M5 全模块 run10 已实际完成：14 项执行，10 passed / 4 failed / 0 skipped，另 2 项 live AI 按既定 marker 排除。四项失败分别为直接读取、带参数读取、基金确认操作和详情生命周期；保留原时限、原件和失败，不冻结为通过候选。wrapper/server/pytest 父子进程全部结束且 18770 无监听后，完整重型 QA 窗口已立即交还 A 股；本任务继续做有界的只读根因核查和精确补丁准备，不并行启动重型测试。



最终 clean 候选冻结后才运行完整 RC，并使用该 SHA 的独立 Publication PostgreSQL workflow artifact 及全新 S6 attempt；RC 内的 reusable publication job 不能替代 S6 要求的独立 workflow run ID。Owner 最新授权由代理直接创建测试 superuser，替代此前人工终端输入安排：在该 fresh attempt 的 disposable PostgreSQL 中创建并明确标记为测试身份，账号与凭据不纳入 Git；不为此修改生产账户。认证仍使用 active superuser 和 closed anonymous FD 3，口令不进入聊天、argv、环境、普通文件或日志。该测试身份不构成第二名人类复核，`production_manifest_review_satisfied=false` 保持不变。当前尚未创建该账户，也未执行全新 S6；需先完成实际隔离身份核验和创建/管道方案复核，不能把授权当作执行结果。所有前置通过后补全本轮具体部署方案供 Owner 确认。本轮未部署，未开始 14 天观察，TUI-02 未关闭。



测试身份方案的私有草稿已完成静态复核；首稿的 FD 3 生命周期问题已在第二版修正，首稿保留为失败历史。2026-10-19 11:02 UTC 在目标 Linux 宿主实际运行纯公开 sentinel 管道探针，确认子进程继承/readback、写端关闭后的 EOF、已占用 FD 3 拒绝且保留、可变缓冲清零均通过。该探针没有使用真实口令，也没有调用 Docker、Django、数据库、账户创建或 S6 runner。它只验证传递机制，不替代 fresh attempt 的 plan/receipt、容器/网络/数据库身份和 auth schema 核验；账号仍待 RC 通过及隔离库准备成功后创建，创建时不再要求 Owner 手输口令。



本轮追加实测：ReDoc 固定脚本版本后，新 HTML 资源契约 1 passed；现有 ReDoc 页面 case 经仓库标准 `pytest.ini` 和 live-server wrapper 复验 1 passed / 0 failures / 0 errors / 0 skipped。独立匿名浏览器采集 script/schema 均 200、`.redoc-wrap` 为 1、正文 601,706 字符，未捕获页面脚本错误或失败请求；已目视核对实际渲染截图。此前非标准 `-c pyproject.toml` 的一次 1 failed / 1 downstream browser setup error 原样保留，不能归因于单一配置差异，也不计作通过。修复尚未部署。



信号实际 DOM 已核对：资产类别为 6 个实际选项加 1 空提示，指标只有 1 空提示、0 个实际选项。隔离鲜库的 94 catalog / 0 MacroFact 与 published-only 查询行为吻合，缺的是可用的已发布指标数据，资产类别未丢失。后续 UI 合成数据 fixture 的 synthetic pointer 仅表示预配置测试数据；不验证或替代 macro activation、Account authority fence、RawAudit 批准及生产/UAT资格。



M5 原 provider 失败在同一临时密钥传入独立测试 server/pytest 后，未修改原 case 即 1 passed / 0 failures / 0 errors / 0 skipped。独立三用例读取诊断仍为 3 failed，全部保持原时限与断言；原首个详情的 5 秒等待本轮已越过，后续 Alpha 创建暴露同一旧文案断言。不得把这一局部进展拼成 M5 全绿。新版七路径候选格式、增量 mypy、全库债务及独立官方模块地图 build/check 均通过；共享投影未改写。H/I、其余结果契约及信号 fixture 继续分批验收，正式同候选 RC/S6 尚未开始。


## 8. 2026-10-20 候选 A3 失败与下一批收口范围

候选 `a3cc46bff47204b10385a0d427f9f660284cf8e7` 的固定标签 `tui02-rc-a3cc46bff472` 保持原样。正式 RC `39403771041` 已失败，不能用后续修复重标该结果；允许以其代码为基础产生新的候选。三类实际失败分别为：完整 PostgreSQL 套件内既有测试在事务外执行 `select_for_update()`；Python 3.11/3.13 Fast 的逐步骤数据库名断言过时；Nightly 的生命周期日志引用被业务测试 monkeypatch 的共享 `json.dumps`，引起日志异常和后续级联错误。Nightly 没有正常的最终 pytest 汇总或完整单测 JUnit，本次不能描述为 35 分钟超时。

A3 的独立 Publication PostgreSQL `39403765380`（job `118564606809`）实际通过：100 项、0 failure/error/skip，59 个必需身份及 5 份必需 XML 均存在；正式 RC 的 Required RC User Journeys 为 89 项通过、0 failure/error/skip。这些结果只属于 A3，不构成 RC 整体通过，也不能移作新 SHA 的资格。A3 尚未运行全新 S6；未来 S6 的 `github_run_id` 必须绑定新候选自己的独立 Publication PostgreSQL run，正式 RC run ID 另外记录。

下一批按事项分别提交：为既有锁查询补齐测试事务；修正 CI 逐步骤数据库身份断言；隔离生命周期日志的 JSON 序列化函数。前两项不改变业务事务或放宽断言，日志修复不改变测试选择、超时和覆盖率要求。CI 测试文件与外来七路径 WIP 重叠，Nightly 文件另有外来 PG 预检；只在 A 股明确交接源码及 Git 窗口后采用获准的单路径或两处日志改动，保护其余 WIP 和真实 ITA 状态，不整批暂存。

私有局部复验为 9 项 CI 测试加 1 项原风险业务单测通过；日志污染基线实际复现失败，修复后的聚焦探针通过，五项生命周期探针退出码与预期 `[0, 1, 1, 0, 0]` 一致。一次完整源码后置检查在原 110 秒上限终止，所属进程均结束；没有取得完整后置哈希证明，不能宣称全树后置核验通过。该私有检查不是新增正式发布门禁。完整 55 项 PostgreSQL 回归、新候选完整 RC 和全新 S6 仍待实际执行。

本段原件位于本机 Git 忽略目录 `.tmp/tui-rc4-followup/`：`a3-formal-rc-evidence-r1/terminal-audit.json`（SHA-256 `4738b4db040a2f69f1b1986372ecd6d57005f66f846ccdaf72c64b73daddf765`）、`a3-direct-pg-evidence-r1/qualification.json`（`7b586b19cc4a4926e3929260eb9a8b91bf4ea3741456a0da7121764b77b4ad7f`）、`a3-three-fix-local-qa-r1/handoff-receipt.json`（`e2c037dfc0c99e9e43d586bdbd62ea97ee6ffe60216aec88cc4665c311cf497f`）。这只是本机定位，未声称远端持有原件。

新候选冻结前纳入必要修复及本段说明；冻结后在同一不可变 SHA 上完成必需 CI、完整 RC（含完整单测、55 项 PG 和用户旅程）、独立 Publication PostgreSQL 和全新 S6，不拼接不同 SHA。测试 superuser 仅在成功准备的 fresh S6 隔离 PostgreSQL 内创建；不修改生产账户，口令不进入聊天、文件、日志、argv、环境或 Git，仍经闭合匿名 FD 3 传递。合成身份不代表第二名人类独立复核，`production_manifest_review_satisfied=false` 保持不变。

14 天观察固定同候选；每周开发、隔离 QA 和下一版构建继续，生产观察对象发生升级或紧急变更时按既有规则重置。低频任务仍按逐项验收、风险接受和独立复核处理。保留 Owner 对当前测试阶段不制作备份的选择，不据此改写第 6 节正式 Classic 退出所需的备份、回滚和最终签字要求。通过后先提交包含准确镜像、按执行顺序排列的迁移、认证修复、监控验收与回滚步骤的具体部署方案供 Owner 确认；本轮不部署、不生成 T0、不关闭 TUI-02。


## 9. 2026-10-20 候选 BF3 失败与后续独立修复

候选 `bf3e1d33f1a7c042c0be18cb9904f4e31fd4ed7c` 的标签 `tui02-rc-bf3e1d33f1a7` 保持原样。正式 RC `39423918977` 和累积范围的手动 Fast `39423907395` 均已实际失败；五组 push CI 的增量结果不能替代该完整 RC。BF3 的独立 Publication PostgreSQL `39423913267` 为 100 项通过、0 failure/error/skip，59 个必需身份及 5 份必需 XML 均核验；正式用户旅程为 89 项通过、0 failure/error/skip。这些只属于 BF3，不能移作下一 SHA 的资格。

本轮确认的阻断有三类。Fast 的 Python 3.11/3.13 在手动及正式 RC 中均为相同 5 failed / 5158 passed / 209 skipped：三项撤单失败由迁移测试未恢复最新 schema 引起，两项重置测试在进入主断言前先注入不完整成交回执。A 股已独立提交测试隔离与夹具顺序修复 `7336fed38c1e7a8aeda65f007a2f12ced51be1ad`，不放宽生产交易保护。Critical PostgreSQL 原事务清理组 55 项全部通过，但后续 982 个 current-data 节点在第二批因查询预算断言停止，所产 XML 为 48 passed / 1 failed；不能宣称全清单完成。测试将锁超时配置和共享 advisory lock 的控制 SELECT 计入业务查询。修复已独立提交 `897750c2e62ff6273051f7b2d60a408bf96fc6d7`，精确识别四条控制语句，保留其余直接 SELECT 总数 2、事实表和成员表各一次及 UPDATE 一次，SQLite 期望零控制语句。私有同源单项 SQLite 回归 1 passed，SQL 分类正反例通过；尚不代表 PostgreSQL 全门通过。

BF3 正式 RC 的 NoDB 实际为 120.47 秒，超过未改的 120 秒预算；同 SHA 的另外两次既有检查为 98.23 和 105.37 秒，选择集合与 12889 passed / 24 subtests passed 一致。这些对照不足以确定性能根因，不提高预算或重跑求绿。完整 Nightly 的单测阶段实际达到 35 分钟上限并中止，后续测试阶段未执行；生命周期记录的 21628 个收集项与已配对阶段不替代最终 pytest 汇总、覆盖率及 session-finish。热点静态分析确认完整清单存在重复构建；后续只考虑保留完整断言和独立反例的最小复用，必须先实测收益，不能提前宣称该超时已解决。

先完成必要修复和对应实测，再冻结全新不可变候选；在其同一 SHA 上重新完成必需 CI、完整 RC、独立 Publication PostgreSQL 及 fresh S6。测试 superuser 的自动创建授权保持，仅在该 fresh S6 disposable PostgreSQL 准备成功后执行，不再要求 Owner 输入口令；当前尚未创建。口令不写入 Git、文件、日志、argv、环境或聊天，合成身份不替代独立人类复核。仍先交付准确镜像、按执行顺序的迁移、认证及监控验收、回滚步骤供 Owner 确认；本轮不部署、不开始 T0、不关闭 TUI-02，14 天固定观察候选及低频逐项验收规则不变。

本机原件索引位于 Git 忽略目录 `.tmp/tui-rc4-followup/`：`bf3-fast-failure-evidence-r1/summary.json`（SHA-256 `27f8dd2a59a829b8947f7dac35238e87d0476452454ee66df7385b3035d7dcf8`）、`bf3-critical-pg-evidence-r1/receipt.json`（`0147f1fc19745f66fa9d573a39566dfe97413fd9329e374e36994ced7b8b0733`）、`bf3-nightly-evidence-r1/nightly-timing-analysis-r2.json`（`6b3c35bc9b701d7eae5f78380c51ca0a9684aa1270a66c6a82ca7db2068bb522`）、`bf3-pg-budget-local-qa-r1/receipt.json`（`88dde1d68204afdd1cf22f35c0b7c8d6ad29b7ca22f643e9cc9d8ba75519447a`）。这些是本机定位，不声称远端已持有原件；Nightly R1 的不可靠文本计数保留为历史，不作为依据。

清单复用的本机对照已实际完成：在 BF3 私有源码加独立查询预算 overlay 上，保持全部 9 个既有用例、分支覆盖率追踪和禁数据库 guard，按 A1/B1/B2/A2 顺序分别为 143.824/76.681/72.551/114.635 秒。四轮均为相同 9 个 JUnit 身份，9 passed / 0 failure/error/skip，退出码均为 0 且没有超时；基线均值 129.230 秒，候选均值 74.616 秒，本机减少 54.614 秒（约 42.3%）。修复仅让两个只读消费者复用一次真实仓库构建；独立源码移动与语义变化反例仍执行原三次构建，统一 CLI 门禁未改。对照阶段统一关闭重复报表生成以比较构建成本，正式 Nightly 的完整选择、三种覆盖率报告、覆盖率 ratchet 与 35 分钟门槛均不变。该本机收益不能投射为托管运行器的全量耗时，也不构成新候选 RC/S6 通过。对照后私有测试原像已恢复、CIM 确认所属进程为空；原件 `nightly-inventory-reuse-benchmark-r1/receipt.json` 的 SHA-256 为 `682708c691a40be37bd071a2e34e8b6dd0221ae1dbedb5bd9ca2784fb6506807`，四次日志、JUnit、覆盖率数据和哈希均保留在同一忽略目录。

## 10. 2026-10-20 候选 1be9 的正式 RC 失败与后续验证

候选 1be9cc15c48eed3636b471f6cae12aba6f8b3ce3（标签 tui02-rc-1be9cc15c48e）的正式 RC 39444763672 最终未通过。该 SHA 上的几项单独成功只绑定各自工作流，不能拼成完整 RC：

| 检查 | 运行 / 作业 | 实际结果 |
| --- | --- | --- |
| 手动 Fast | 39444746828 | Python 3.11 与 3.13 均为 5,163 passed、209 skipped、0 failure/error；NoDB pytest 72.70 秒、wrapper 82.34 秒。 |
| 独立 Publication PostgreSQL | 39444753800 / job 118703599577 | 100 cases 通过；59 个必需身份、5 份必需 XML 均核验。只证明该 SHA 的独立 PG 检查。 |
| 必需用户旅程 | job 118703625470 | 89 passed、2 deselected、0 failure/error/skip。 |
| Critical PostgreSQL | job 118703625852 | 五份 XML 合计 203 个 JUnit case：202 passed、1 failure、0 error/skip；其中 current-data.xml 仅运行 69 项（68 passed、1 failure），不是 982 节点全清单完成；失败测试尝试在 PostgreSQL wrapper 下连接 :memory:，psycopg 报数据库不存在。失败发生在 MigrationLoader / MigrationRecorder 检查阶段，早于迁移断言；这是隔离 SQLite migration fixture 与 PG 默认 backend 不匹配，不能记作迁移逻辑通过。 |
| Nightly full-unit | job 118703626059 | full-unit 进程以退出码 139 结束，没有最终 pytest summary 或完整 JUnit。15:32:55Z 的 faulthandler_timeout=30 诊断输出被截断在 File 行附近；根因未证实，不能推断全量测试已完成。 |
| Architecture layer guard | job 118703626294 | 作业取消，记录指向 checkout fetch 超过该 job 的时间上限；不构成检查通过。 |

Nightly 的后续私有诊断候选只把 full-unit 步骤的 faulthandler_timeout=30 改为 0，保留 35 分钟单测步骤上限、300 秒单例 timeout、完整测试选择、PYTHONFAULTHANDLER=1 和三种覆盖率报告。该单变量诊断尚未证明 segfault 根因或修复收益；必须在新冻结 SHA 上重新验收。首次 16:28 本机 harness 启动失败发生在测试断言前，随后修正并完成 16:40 本机定向复核；启动故障不计为测试断言失败，也不算 RC 通过。

2026-10-20 16:40 UTC（本地 10 月 21 日 00:40）的复核只验证私有来源 .tmp/qbf3-pg-r1（既有 bf3 源码加 query-budget overlay）中的 tests/unit/data_center/test_publication_evidence_migration.py 两个原测试，在 core.settings.critical_postgres_test 与 core.settings.development_sqlite 下各运行一次：两轮均为 2 passed、0 failure/error/skip，耗时分别 57.920 秒和 42.577 秒。测试文件前像为 156a38da73b7bb38b332c0c391ed876b7f00c70b08ba0b80a02223bed62f5189，定向 fixture after 为 c1687a94eb8d9b4171bb3cc792651a0e3453cd38933111304654479892def150。收据明确 native_postgresql_evidence=false，所以这不是原生 PostgreSQL 证明，也不是干净 1be9 全树或完整 RC 结果；它只说明该私有上下文中的两项 fixture 复核通过。16:28 启动失败后已修正的运行收据 SHA-256 为 a03ca4764fadc0ec11fcb1a58c0c827a88ebb1d10b994afe9390becf2311f6b5，独立回执复核 SHA-256 为 87bc6ff77ca686375467cb431a1922621b3eca8c9f1dbc230e0c6059955c27da。父代理确认所属进程族为空、源文件恢复到前像；这不扩大测试资格。

当前没有通过完整 RC 的新候选，也没有 fresh S6。后续修复须形成新的不可变 SHA，并在同一 SHA 上重新完成全部必需 CI、完整 RC、独立 Publication PostgreSQL 和 fresh S6；不得重用 1be9 的局部成功。继续遵守不部署、不生成 T0、暂不关闭 TUI-02 和 Owner 对当前测试阶段不制作备份的选择；第 6 节正式 Classic 退出所需备份、回滚和最终签字要求保持不变。达到资格后仍先把镜像、实际迁移顺序、兼容/回滚限制、监控和逐项验收步骤交 Owner 确认，未经确认不部署。
本段原件保存在本机 Git 忽略目录 `.tmp/tui-rc4-followup/`：正式 RC 汇总 `final-candidate-1be9cc15c48e/nightly-final-evidence-r1/rc-observation-summary.json`（SHA-256 `dc8429b2b87854cf5fa04c00b1797eccce0784dedcf079259598f117c5bc1cf2`）；本机两轮复核及独立审查位于 `1be9-legacy-migration-fixture-candidate-r1/qa-output/attempt-20261020T164000Z-bc41f662/`。这是本机原件索引，不声称远端已持有。

## 11. 2026-10-21 候选 9da 失败与下一批验证

不可变候选 9da00e86b3bbfc8de58e708c080888437eb81ba8（tui02-rc-9da00e86b3bb）正式 RC 39462393977 失败。Critical PostgreSQL 回归在 test_retention_member_evidence_failure_rolls_back_raw_delete 的 teardown/数据库 flush 中触发 Clock 权限代次单例行缺失；不是测试主体断言失败。Nightly full-unit 达到原 35 分钟步骤上限：收集 21,628 项，日志可见 21,625 passed、2 skipped，但没有最终 pytest summary 或 full-unit JUnit。生命周期记录的测试阶段进出均配对；最后 teardown 到步骤超时约 134 秒的空档只是诊断线索，不能证明 coverage 是根因，也不能从差额推断剩余项目状态。

同一 SHA 的 Fast、独立 Publication PostgreSQL 和 89 项 journey 有成功证据，但均不能抵消正式 RC 失败或移用于下一 SHA。9da 的两库局部复验（receipt 27206a…）在 PostgreSQL、SQLite 阶段各于 240 秒超时；只见迁移输出，没有 JUnit 或 pytest 结果。进程清理、源码恢复及源数据库前后不存在均有记录；不得据此声称 14 项通过或五次 flush 已验证。

两处测试模块导入既有 authority-generation flush fixture 已独立提交 `a4bf71241`；Nightly 诊断及既有 unit/component JUnit 输出已另行提交 `c2dcaab95`。诊断 payload manifest `3b5310e8…` 已通过独立静态复核；运行时 hook 探针尚未执行，新候选正式 CI 仍待固定 SHA 后验收，不构成通过资格。保留 35/25 分钟步骤预算、300 秒单例限制、完整选择和原有 skip 规则；不修改 trigger、flush helper 或 seed。现有同候选 CI 的对应节点预期 PG 为 13 passed/1 原有 skip、SQLite 为 12 passed/2 原有 skip，尚未观察；若 unit 失败导致 component 未执行，该组件仍属未验证。

新不可变 SHA 必须独立通过全部 CI、完整 RC 和 direct Publication PostgreSQL，之后才可准备 fresh S6。获授权的测试 superuser 只在该次 disposable PostgreSQL 中创建，凭据仅经内存→stdin→FD 3，不能进文件、日志、argv、环境或 Git；测试身份不代表独立人类复核，production_manifest_review_satisfied=false 保持不变。当前未建账户、未部署、未开始 T0，TUI-02 未关闭；本节仅补充 9da 状态，不替代 A1/5b31 历史失败记录；当前测试阶段免备份选择、14 天冻结和低频逐项验收规则不变，第 6 节正式退出所需备份/回滚条件仍保留。仍须先提交具体部署方案供 Owner 确认。


本节原件逐项索引位于本机 Git 忽略目录 `.tmp/tui-rc4-followup/9da-terminal-remediation-plan-appendix-r1/manifest-r2-corrected.json`（SHA-256 `5d3bcd9235c650b0930ffe79958977a936776e396d93b32e3a5ff8e7a9b1a267`）；其中包含各输入、运行结果、原件位置和摘要。本机原件未宣称已上传远端。

## 12. 2026-10-20 候选 E08 的正式 RC 失败与后续状态

候选 `e08dfa8e28c6bafcd615c6596ce9b032b8d677ff`（标签 `tui02-rc-e08dfa8e28c6`）没有取得完整 RC 资格。独立 user-journey 作业 `118848181644` 为 **89 passed / 0 failure / 0 error / 0 skipped**；独立 Publication PostgreSQL 作业 `118848137273` 的 8 份 XML 共 **100 个 testcase occurrences、92 个唯一身份、0 failure/error/skip**，其中政策要求的 59 个身份和 5 份必需 XML 均齐全。这些成功证据只属于 E08，不能抵消正式 RC 的失败。

同一 SHA 的手动 Full Fast 工作流 `39486483409` 为 success。独立复核确认 Python 3.11 和 3.13 两个作业各收集并输出 **5,455 个唯一用例身份：5,243 passed、212 skipped**。这份运行没有 JUnit 或 GitHub artifacts（artifact API 总数为 0），因此计数来自每项 console 输出，不称作 JUnit 结果。手动 NoDB 作业报告 **12,916 passed / 24 subtests passed**、pytest 用时 **73.53 秒**、suite wrapper **83.30 秒**。正式 RC 的 NoDB job `118848338268` 报告相同用例计数，但 wrapper 为 **124.62 秒**，超过既有 **120 秒**预算，故该必需 job 失败。

正式 RC 的 Critical PostgreSQL job `118848182099` 失败。迁移与前置步骤通过后，backfill/retention 阶段报告 100 passed、1 failure、2 teardown errors；日志显示 flush 守卫因默认 PostgreSQL 配置没有显式非空 `TEST.NAME` 而拒绝 teardown。现有私有接线候选只为两个既有步骤指定 `core.settings.critical_postgres_test` 和隔离测试库名 `test_agomtradepro_critical`。该候选的 manifest SHA-256 为 `53727ad17e055468b42813d1ba1f56209ddd426eff075b2bc1fa91029d2c38f8`，静态复核 SHA-256 为 `5a955d7fe38a892f95a45c9ce6feb078b20908a746785c01fa986ea797b8ec7f`；它仍是私有、未采用、未运行的配置草案，不构成验证结果。不得放宽 flush 守卫、trigger、测试选择或时限。

Nightly full-unit step 的配置上限仍为 **35 分钟**。该步骤于 `2026-10-20 20:09:43Z` 开始；截至 `20:25Z` 的快照，约运行 15 分钟，状态仍为 `in_progress`，尚无终态 summary。这个快照早于步骤上限，不能写成步骤已达到 35 分钟，也不能推断通过或失败。E08 已因其他必需正式 RC job 失败而不具备完整资格；Nightly 后续状态仍待实际终态证据。

本地 NoDB 调度 A/B 方案的独立静态审查为 **DEFERRED**：本地 Python/pytest 与 CI 版本不同，且本地缺少 `pytest-subtests`。不占用拟议的 780 秒窗口、不改变 `--dist`，也不根据这项本地方案决定 CI 默认值。

用户不额外制作备份的选择仅适用于本次测试与部署准备阶段，不取消正式 Classic 退出规范中既有的备份要求。当前不部署、不开始 T0、不关闭 TUI-02。后续修复必须形成新不可变候选，并重新完成其全部必需 CI、完整 RC、direct Publication PostgreSQL 和 fresh S6；S6 自动测试 superuser 只用于一次 disposable PostgreSQL rehearsal，随机口令经内存、stdin 和 FD 3 传递，不写入 Git、文件、日志、argv 或环境，也不代替人类独立复核。只有新候选与实际镜像、迁移顺序、兼容/回滚限制、停机和验收方案均可审查后，才交 Owner 最后确认。

本节完整原件和 SHA-256 索引仅在本机 `.tmp/tui-rc4-followup/e08-deployment-appendix-r2/manifest.json`，不声明远端已持有。此次仅有静态配置与源码字节核验，未运行新的 pytest、数据库回归或 S6。

**20:46Z 终态补记**：E08 正式 RC `39486503884` 与 Nightly job `118848182274` 均已 failure。Full Unit Tests 从 `20:09:43Z` 至 `20:44:55Z`，超过原 35 分钟步骤时限，后续测试步骤被跳过。Lifecycle 收集 21,674 项，setup/teardown 各 21,674、call 21,673，已记录的 hook enter/exit 配对；最后一个 teardown 于 `20:43:28Z` 正常结束。之后 coverage debug 有 combine/write 记录，但未观察到外层 `runtestloop_exit`、sessionfinish、terminal summary 或 unconfigure；质量制品没有 Nightly JUnit，不能据此声明完整通过数量或锁定超时根因。终态收据位于本机 `.tmp/tui-rc4-followup/final-candidate-e08dfa8e28c6/nightly-final-evidence-r1/final-observation.json`，SHA-256 `f4181bd920cc45bfe377fb93329344d5ba4c489c602cd8055af21391671ce215`。这次六行 PostgreSQL 配置接线仅修复已定位的隔离库前置缺失，未解决 NoDB 时限与 Nightly 收尾问题；新候选仍须实际通过全部门禁。

## 13. 2026-10-21 固定诊断的结果与资格边界

提交 `dc9227686341cf9b408dc3e524678e27b1e78e94` 是固定诊断输入，不是新的最终 RC 候选或资格标签。Push Fast run `39505159617` 只有 1 个变更文件；Fast 的 `logic_guardrails` 选择 8 个目标路径，Python 3.11 和 3.13 各为 74 passed。这是路径限定的 push 结果，不是累计 Manual Full Fast。

Nightly run `39505426996` 的 Full Unit 步骤于 22:27:48Z 开始，至 23:03:01Z 因原 35 分钟步骤上限终止，实际约 2,113 秒。21,713 项被收集；JSONL 中 setup/call/teardown 阶段的进入事件合计 65,138 次，退出事件合计 65,138 次。最后可见 teardown 为 23:02:50.252Z，末尾栈采样约在其后 10 秒显示主线程位于 pytest-cov 的 coverage summary/report/analysis 路径并执行 `ast.parse`，另一线程处于空闲 executor。未观察到 runtestloop exit、sessionfinish、unconfigure、Full Unit JUnit 或最终 pytest summary。这个采样只表明当时位置，不证明死锁、停滞根因或剩余测试结果。相关 artifact digest 为 `dfcaf1471e6884ab3b5bba986ca89b965d7c5bcc0604157c541e75752cc8dad9`。

该 Nightly 的 Critical Reliability PostgreSQL job `118913031657` 与独立 direct Publication PostgreSQL 是不同检查。按精确目标身份统计为 13 passed、1 个既有 SQLite-only skip；8 份 XML 合计 670 passed、1 skipped、0 failure/error，671 个 testcase occurrence、644 个唯一身份。另有 5 项 suite-level cleanup observations；它们与既有 55-node flush suite 分开记录，不从这些汇总推断 testcase 跨文件对应或因果关系。

Security run `39505159965` 失败：pip-audit 在 Pillow 12.3.0 上报告 8 项发现，报告列出的修复版本为 13.0.0。官方 PyPI 元数据显示，项目允许范围 `streamlit>=1.54.0` 内全部 16 个非撤回稳定版均要求 Pillow `<13`。当前官方依赖约束因此与所列修复版本冲突；不得忽略发现或假定降级 Streamlit 已安全。

第 12 节 E08 的正式 RC 失败及其 Nightly 收尾记录保持原样；本节不会替换或追认历史结果。当前没有完成资格的新冻结候选，没有创建 S6 账户、没有部署、没有开始 T0，也未关闭 TUI-02。后续必须在同一新冻结 SHA 上完成全部必需 CI、累计 Manual Full Fast、独立 direct Publication PostgreSQL、完整正式 RC 和 fresh S6。Nightly 的下一步应保留完整选集、覆盖率报告及验收门禁，量化 coverage 收尾成本、测试执行耗时和 runner 差异后再确定运行预算；本次栈采样不能作为 plugin 修复已证实的依据。
RC 通过后，fresh S6 可按用户本次授权在一次性测试 PostgreSQL 内自动创建随机 active superuser；口令只经内存、Docker stdin 与匿名 FD 3 传递，不写文件、环境变量、命令参数、日志、聊天或 Git。该合成账号的测试结果按测试证据处理，生产用户与 UAT 资格仍按原标准验收。

本机取证索引为 `.tmp/diagnostic-dc9227686341/nightly-final-evidence-r1/terminal-analysis-r2.json`（SHA-256 `2d8d901f56fc61335f03831df214c87d50bbc73aea9292e996c62bbee7a5faf4`），记录原始日志、ZIP 及生命周期文件的路径与校验值。完整副本保留在本机忽略目录，未提交 Git；对应官方运行见 [Nightly 39505426996](https://github.com/guiyinan/agomTradePro/actions/runs/39505426996)。


## 14. 2026-10-21 Research 收口与下一候选边界

固定诊断 `3b23636e2534d6901bd30107473cb9e1c8076718` 的 Nightly `39515132260` 中，Full Unit 已在 45 分钟预算内终态完成（21,711 passed、2 skipped）；Component 因 Research 子目录插件注册而收集失败。另一个 Critical PostgreSQL job 的 full-registry cleanup 步骤退出 139，未产该组 JUnit；用例身份及崩溃原因未证实，不能称为已定位的 teardown 故障。该问题仍须由适用的最终候选验证闭合。

R8 `3df3f7d45021a8bda4bba517dfb03558db68411c` 已修复 Security source guard。Research `23541c4f0474b0807cdf755189f9b895371e19ec` 已推送并独立复核，仅删除嵌套 conftest 的插件注册、在 V2 消费测试显式导入六个 fixture；业务及非 import AST 不变。私有 pytest 9.1.1 下 component 4,651 项、相邻 research/account 801 项收集通过，后者有一条 assert-rewrite warning；隔离 PostgreSQL 16.15 的 V2 目标实际 1 passed、0 failure/error/skip，测试后验空并停库。

235 的 push Fast `39537527106` 已成功，两 Python 版本各 313 passed、6 skipped，NoDB 为 12,916 passed、24 subtests passed；云端 V2 PG 目标实际跳过，不能当作 PG 执行。Architecture、Consistency、Engineering 成功。Security `39537527030` 失败：8 项均为 Pillow 12.3.0，报告修复版本为 13.0.0；gitleaks、Bandit、npm 通过。Streamlit 兼容范围决策和漏洞豁免均未获 Owner 新授权，不忽略发现或强装冲突组合。

A 股 W1 已提交并推送 `7e9ae20cc67bdc40ca29e405c5f2c0bee8775bbd`；后续按本计划文档更新→安全收口→不可变 SHA 冻结推进。W2 等后续开发不追入此候选，也不因此宣称 A 股完整能力通过。9 项外部未提交改动（其中含 CI/S6 脚本）仍归属不明，OBS 已确认非其持有；它们不算候选，也不作为冻结等待条件。正式 RC/S6 只从已提交固定源码构造。

显式 opt-in 的合成 Signal/M5 夹具可作消费者回归，不代表生产 UAT；当前不要求生产回填、真实交易或先完成 14 天观察。低频逐项验收、风险接受、独立复核及生产观察在后续获准部署阶段执行，每周开发和隔离 QA 可继续，观察候选保持冻结。最终同 SHA 用户旅程、完整回归、累计 Manual Full Fast、独立 direct Publication PostgreSQL、正式 RC、fresh S6 以及实际镜像、迁移执行顺序和兼容/恢复证据仍待完成。随机 active superuser 仅在 RC 通过后的 disposable S6 PG 中创建，凭据经内存→stdin→匿名 FD 3，不进入文件、环境、argv、日志、聊天或 Git。未部署、未开始 T0、TUI-02 未关闭；具体部署方案仍交 Owner 确认。

以下原件已复制到本机忽略的 `artifacts/` 并逐项校验，原临时副本保留，不宣称远端持有；各批次证据不转移为新 SHA 资格：

- Research 采用：`artifacts/tui02-research-235-20261021-r1/originals/tui-rc4-followup/research-r2-adoption-585-r1/postcommit-receipt.json`，SHA-256 `b37588c1766fa2423d4ca7f7ed762d6a164cd7d0e9c68d42e788d8b2a8649b02`。
- Research 回归：`artifacts/tui02-research-235-20261021-r1/originals/tui-rc4-followup/research-r2-adoption-585-r1/precommit-receipt.json`，SHA-256 `f450dfdb447347d96faeb053c425cf3991bc3a35217c2b58189c37d03943da97`。
- 235 Fast：`artifacts/tui02-research-235-20261021-r1/originals/tui-rc4-followup/research-r2-ci-235-r1/fast-terminal-summary.json`，SHA-256 `8e90524e8b03c5110da0241a1ab46ccc1789e0a36fcfabf1fd3ca2f6c43952a5`。
- 235 Security：`artifacts/tui02-research-235-20261021-r1/originals/tui-rc4-followup/research-r2-ci-235-r1/security-verified-summary.json`，SHA-256 `62734eb3053fbcab5fbc7c90c75666da545fbbbe6ee2ba527f884e828b3a6015`。
- 3b Nightly：`artifacts/tui02-research-235-20261021-r1/originals/diagnostic-3b23636e2534/nightly-terminal-evidence-r1/terminal-evidence-summary.json`，SHA-256 `d57a2e2f35e6e87d5659b4996273d3d059dbd4723317b82410ff9119bfa421cb`。
- 3b Critical PG：`artifacts/tui02-research-235-20261021-r1/originals/diagnostic-3b23636e2534/critical-pg-evidence-r1/independent-review.json`，SHA-256 `1d614d1e01499ca1ab2e6dd6f285d85bf5fe8d2a5754a6449f6522ee7618fa59`。
- 235 security jobs：`artifacts/tui02-research-235-20261021-r1/originals/tui-rc4-followup/research-r2-ci-235-r1/security-jobs.json`，SHA-256 `0515c171773c68709d4e7b12f93e8280d1e8316b4d3515b439e8d7f5564e1f9e`。

## 15. 2026-10-21 新范围授权与 Streamlit 等价验收

Owner 已明确批准“纳入退出范围，先补齐 TUI 验收”。这解决了第 14 节所记的兼容侧车范围待决问题；不表示接受漏洞豁免，也不批准部署。先补齐宏观四象限及真实源观测日、本人账户聚合资产历史和本人信号统计/最近已批准记录，再独立提交 Streamlit 源码、启动开关及无剩余调用方的依赖退出。保留数据 API、登录保护的 `/dashboard/` 入口和 Classic 兼容模板，本批不清理 Classic。

A 股已独立推送 W2a `54cd6b8d411ec6a8ca58424330e94a7971f4ff3e` 并交回 Source/Git 窗口；新有限候选显式以它为基点。其 Fast `39555434445` attempt 1 的 NoDB 所有断言通过，但 wrapper 超过原 120 秒预算；同 SHA、同选集、同预算的唯一 failed-job 重跑 attempt 2 成功。原失败保留，其余成功 job 沿用 attempt 1，不冒称全部重跑。W2b 继续为 A 股私有工作，不追入本批。

旧 `d7914d83c5afc99b085f321040bf1429db0841a7` 固定诊断 Nightly `39546102861` 已终态：Full Unit JUnit 为 21,727 个 `(classname, name)` 唯一用例、1 failure、0 error、2 skip；唯一失败为 `trade_repository.py` 169 行超过 150 行结构约束。后续 Component 步骤跳过。另一个 Critical PostgreSQL job 的 full-registry 55 项实际全通过、0 failure/error/skip，两项原生竞争场景各执行一次；不以此跨 SHA 宣称旧退出 139 原因已定位。并发保留组为 3 passed、1 个 SQLite-only 用例跳过。

同一 d791 的私有 Windows 完整用户旅程实际为 86 passed、3 setup errors、0 failure/skip（另有 2 deselected），不是全绿：一次缺少 pytest basetemp 的父目录；另两次由私有 harness 预建了日历 fixture 必须独占创建的目录。10,358 个源码文件后验哈希一致，服务端口已关闭。后续在新候选的全新隔离环境修正 harness 准备步骤；不改测试选择、权限、新鲜度、超时或通过规则，不复跑旧候选来伪装新候选资格。

上述 17 份原件的本机归档为 `artifacts/tui02-d791-diagnostic-20261021-r1/index.json`，SHA-256 `b027480a253bd97a6dde69b32105df8dabfb7a7ac5cbfb3f7c9e288968db57e5`；逐项哈希复核为 0 mismatch，原临时副本保留，不宣称远端持有。历史失败不改写，新 parity/退出批次仍须绑定最终同一干净 SHA 的完整回归、累计 Manual Full Fast、独立 Publication PostgreSQL、正式 RC 与全新 S6。测试账户、低频逐项验收、独立复核和观察仍遵守第 14 节；未部署、未启动 T0、TUI-02 未关闭。


## 16. 2026-10-21 可操作曲线与有限提交顺序

TUI 等价批次已推送 `26984881f25fa42ebd8d5b39fa111660b56c8d39`，显式百分比单位批次已推送 `7525c424193acd9a10c43250c84be8c88c6a7065`。269 的 push CI 五项成功，Security artifact 实际确认八项均为 Pillow 12.3.0，不能追认为安全通过；7525 的开发验证为 39 passed、浏览器新构建 3 passed、类型债务 0。原件及限制见[等价验收索引](../testing/tui-streamlit-parity-2026-10-21.md)。

后续真实浏览器检查发现沉浸式首页没有可达的组合区间输入：卡片“打开”只执行默认 ALL，动作栏已隐藏。这是迁移收口阻断，不用后台 API 或 metadata 检查代替用户操作。先独立修复卡片内的历史范围选择、面板更新和打开完整图表时保留已应用范围，再单独提交侧车退出。只让显式配置的 GET/read、无需确认的辅助图表使用安全 primary_selector，保留列表行为及写入/凭据隔离；不增加新页面、模式、接口或状态机。

剩余范围固定为当前操作修复与验收，以及随后 Streamlit 八个源码文件、旧启动开关和无保留调用的直接/传递依赖退出。两项已完成提交加上述两批构成四个有限 TUI 事项；不延伸到其他仪表盘业务、Prompt/Jinja 文案或 Classic 清理。测试专用 URLConf 继续验证保留的 Classic HTML、真实待执行 ORM 队列、告警和排名链接，生产 `/dashboard/` 改为受登录保护的 TUI 精确兼容跳转，既有 Classic 路由、模板和数据 API 继续保留。

A 股回报 W2b 原生 PostgreSQL 三分片 100+98+77 全部 passed，联合选集严格等于原 275；独立封档核对与本批操作修复的 commit/push 完成后，才可正式交出一次有界 Source/Git 窗口。仅接受该批已验收 W2b 三源及累计生成投影/限定文档；W2c 与后续扩展不进入该窗口。接回后显式登记实际返回 SHA 为新有限基点，再完成侧车退出；不得静默追动候选或把私有分片、269、7525 的证据拼接成最终发布资格。

依赖候选只从 pyproject 真源及官方投影脚本生成。Windows 解析曾错误移除 pywin32 marker，原失败候选保留但不采用；Linux Python 3.13 独立解析保留 128 个共同 pin 的版本，平台分支按上游依赖元数据解释，仍须正式安全审计及新环境回归。当前未采用退出锁、未部署或开始 T0，也未创建 S6 账户。所有批次完成后仍在同一干净不可变 SHA 上完成全部必需 CI、累计 Manual Full Fast、独立 Publication PostgreSQL、正式 RC 与 fresh S6，然后将具体镜像、迁移、回滚和逐项验收方案交 Owner 确认。14 天生产冻结、每周隔离开发/QA、低频逐项验收及独立人类复核规则不变。

## 17. 2026-10-22 侧车退出与最终候选前的窗口

可操作曲线修复已独立推送 `bba80735b71c013484b6048ebaf0e240d84f4811`。A 股随后按有限窗口完成 W2b 与等价时钟抽取，返回 `64f5255b86ed298af684d70d7d6eb85d0257f81c`。在 TUI 私有回归与依赖解析期间，双方又显式交接一次 W2c1 有限窗口；A 股仅提交并推送已验收的九路径补丁 `91d81fe8b82e9703d4330e8b460cf1bdba9092fe`，随后归还窗口。父代理独立核验提交、父提交、树、远端及九文件身份，38 个受保护路径、九项外部改动和索引均保持。当前 Source/Git/index 由 TUI 持有，以 91 为本批有限基点；A 股后续工作保持私有，最终候选冻结后不再追入其他开发。

已应用、尚未提交的退休补丁移除八个 Streamlit 文件、旧启动开关及两项直接依赖，保留数据 API、Classic 模板与其他路由；登录后的 `/dashboard/` 精确转入 TUI 总览。依赖文本已从 pyproject 真源通过官方脚本生成，生产锁尚未采用。原 97 项兼容回归的 94 passed、3 failed 记录保留；修复两项待处理队列合成夹具的所属账户关联、一项宏观合成夹具的真实发布指针，并纳入 19 项 Alpha 兼容入口回归后，新私有运行终态为 116 passed、0 failure/error/skip。父代理已逐项核对 JUnit 与收集身份、原失败节点和源码哈希；真实账户隔离、发布校验和业务断言未放宽。这是开发证据，不等同于最终 91 后继候选的同 SHA 资格。

兼容浏览器脚本同时补齐原有类型标注和页面初始化约束，四个修改的生产 Python 文件通过官方增量 mypy，新增及存量错误均为 0；该次全库默认债务检查也已终态通过，0 errors in 0 files，未修改基线。本机回归复核索引为 `.tmp/tui-rc4-followup/retirement-r4-parent-verification-r1.json`，SHA-256 `6997543d199fa0ca9545c82bb3ead15d4a346eca4cd55e829f3fe7ed9e2a2276`；原件仅在本机，不宣称远端已持有。

必要 API 修复独立成批：兼容 provider 状态路由传递其现有 DRF 元数据，并描述真实 `results` 响应；hedge 计算动作声明其已使用的请求 serializer。三个业务函数体未改，真实权限、限流及输入校验保留。全库类型门禁曾发现三个由第三方装饰器类型丢失引起的错误；R6 只在两个模块补本地 Protocol/cast 边界，保留原失败记录，不调整基线。修正后官方增量检查及全库默认债务检查均终态通过，0 errors；Black、isort、Ruff 及 Web→TUI inventory 检查通过。Windows 上五项 API 回归的全新 SQLite 迁移在首项 setup 达到原 300 秒限制，没有进入业务断言或产出 JUnit；不计为通过。现有 Push Fast 的 `logic_guardrails` 选择器保留两个直接修改的 API 测试文件，因此本批修复及投影独立提交，由既有双版本 Linux CI 执行回归；本地同五项 Linux Python 3.11 / 容器本地新库复验并行推进，保持选集、300 秒限制和运行准入夹具。两项运行均未有通过结论，开发提交不构成发布资格。

R6 的三份官方 OpenAPI 投影已重新生成并采用，语义一致且与 R5 输出逐字节相同；全部 1,440 个本地引用、响应及请求约束已核对。R1 到 R2 只有上述两接口所需的五处结构新增；相对历史投影的差异由 529 变为 536 个键值位置，其中含历史投影遗漏的已注册路径，不把这些计数当作新增业务缺陷数，也不据此追认全部历史业务变更。R6 生成索引为 `.tmp/tui-rc4-followup/official-eight-projections-base91-r1/official3schema-r3/reports/official3schema-final-manifest-r3.json`（SHA-256 `4988d714e9cb970ab917ceb4f06a551f959fe1ba0236422b471afa02f6744f04`）；父代理采用收据为 `.tmp/tui-rc4-followup/openapi-schema-r6-shared-adoption-r1/receipt.json`（`f6a338873aee4ba19ee193ccde4415956ac80b61e0f2548fb501150e1f924121`）。这些是开发阶段的本机证据，不构成同 SHA 的 RC/S6 资格。

Python 3.11.14 / Linux 私有离线锁解析已终态通过，候选锁 SHA-256 为 `f8175ef7fdf217306be3b7fae18a6e70bdc4f5cfd33c3463dd858a819ea1a825`，134 个固定版本均有已验证的官方缓存原件；尚未采用为生产锁。指定的 18 项升级全部匹配，Streamlit、Plotly 及不再需要的依赖退出。无新增忽略的原始审计退出 1，只报告 Twisted 26.4.0 的 `GHSA-8pqf-f4m5-798g`；沿用已提交的非暴露检查退出 0，不称为零漏洞。新隔离环境实际离线安装退出 0，134 个版本全部精确匹配，`pip check` 退出 0；原生 JS 探针因脚本错误未完成，原失败记录保留，修正后另验。原始审计与既有策略复核索引为 `.tmp/tui-rc4-followup/linux-lock-preflight-py311-cache-r3/parent-raw-audit-and-existing-policy-verification-r1.json`（SHA-256 `408eae97e311b760b228f697c7ce38b8bd652a0ea8572e8ac7f1ae91191b196b`）；安装原件为本机 `.tmp/tui-rc4-followup/lock-install-nativejs-qa-r2/reports/qa-result.json` (SHA-256 `567e37f6871e9a26ecfbbee8308d9a4b3f9094c14f0ae877d20f0e33d90efc96`)，其整体结果仍为 false。完整 QLib 镜像核验尚未执行。先前 Python 3.13 锁只作诊断，不用于生产构建。QLib 还会在基础锁之外引入依赖，因此基础锁安全检查不能替代最终镜像审计。完成有限修复、必要投影及本地验收后才形成最终不可变 SHA，并在该 SHA 上完成全部必需 CI、累计 Manual Full Fast、独立 Publication PostgreSQL、正式 RC 与 fresh S6。随后给 Owner 准确镜像、真实迁移顺序、认证验收及回滚方案确认。仍不部署、不生成 T0；14 天固定观察、每周隔离开发和低频逐项验收及独立复核规则保持。

## 18. 2026-10-22 API 回归与退出依赖的开发采用

API 与三份 OpenAPI 投影已独立推送 `f49bf850fa888d97e600b9b673fc760f1608803a`。其 Fast `39700649377` 的 Python 3.11、3.13 作业均实际完成，各为 4,344 passed、161 skipped；两份日志逐项确认五个待验 API 节点全部 passed。原件在本机 `.tmp/tui-rc4-followup/cloud-api-jobs-39700649377/`，对应 job `119568853721` 的日志 SHA-256 为 `5dc9a299fe3f1835c153535c1e57a420f06a2153104be88a02a0d3cb6ab85beb`，job `119568853752` 为 `23aebc0c3a00924c1fd2fbed1f270a5047693588fd0838360596732d75f813a8`。本地 Linux 复验在 360 秒总预算内未完成 pytest 初始化，退出 124、无 JUnit 或测试断言结果；不改变预算或把它追认为通过。f49 的 Fast 整体及 Consistency 均因同一生成清单过期而失败，其余 Security、Architecture、Engineering 和 direct Publication PostgreSQL 成功，不能称全部 CI 通过。

生成清单仅因 dashboard summary 文案变更而有一行引用需要更新；官方脚本针对 f49 的私有生成及检查均退出 0，6,070 条引用及其他所有区段不变。父代理独立比较后已提交 `1f278c56bd068eaccbff1d29420ee0b8a9168104`；该修正仍须在后继 SHA 上通过实际 CI。

退出批次将已验证的 134 项锁 `f8175ef7…a1a825` 逐字节采用为开发输入。另一次实际 venv 探针中，两种 MiniRacer 调用均返回 42，AkShare 导入通过；共享 Python 文件匹配 akracer 的 RECORD，实际 x86_64 原生库匹配 py-mini-racer 的 RECORD，不声称二者同名文件同时匹配两份 RECORD。父代理复核索引 `.tmp/tui-rc4-followup/lock-install-nativejs-qa-r2-runtime-probe-r1/reports/parent-runtime-verification-r1.json` 的 SHA-256 为 `738b14092ede04c07c28e7eaae201548a39fbbb0f5d66b9cb4b9212160aa14c2`，原 R2 整体 false 保留。第 17 节的 116 项兼容回归未配置逐项 300 秒限制，只保留为开发证据。

基础镜像实际还继承 pip 24.0、setuptools 79.0.1，额外 136 项完整原始审计报告八项发现：两者共七项可修复问题，以及原有 Twisted 无修复版本问题。原索引 `.tmp/tui-rc4-followup/linux-audit-installed-136-r1/final-audit-receipt-r1.json` 的 SHA-256 为 `4ed43835f22708eeab163db50015dd3bfb18f1d8c3048e5159d06270f6e688c7`，保留原失败结果。

退休批次已独立提交 `948430ac3bd53585f1eabb18afbc89dfbd05fd0f`，随后镜像安全补丁在 pyproject 的 `image-bootstrap` 可选组固定 pip 26.2.2、setuptools 83.0.0，普通应用依赖与 134 项锁不增加两者。两个生产 Dockerfile 从同一声明读取；默认离线模式不回退网络。运行层先卸载基础镜像继承的两项工具，再复制 builder，防止旧 dist-info 残留。私有隔离环境实际离线升级两项后，136 项精确匹配、`pip check`、两种原生 JS 调用与 AkShare 导入通过；完整无忽略审计只剩原 Twisted 发现，两项工具无剩余报告。索引 `.tmp/tui-rc4-followup/linux-audit-bootstrap-upgraded-136-r1/final-bootstrap-audit-receipt-r1.json` 的 SHA-256 为 `6620f61ce2c88bb9d9d31e4460115a162eb5454a4f59befea2858fb176c14e66`，父代理已独立复核原件哈希与实际安装/审计集合。

这不是从零构建完整 QLib 镜像的结果。冻结候选后，须验证真实最终镜像中的唯一工具版本、134 项锁是否保持、默认 QLib 导入、原生调用、完整依赖安全及启动行为，并在同一 SHA 上完成第 17 节全部门禁。累计 Fast/RC 沿用已验证祖先 `ecb59591e3696b89d0f66457a66993c07efe7e84` 作为 `base_ref`，不缩成最后一个提交。仍不部署、不创建 S6 账户、不启动 T0 或关闭 TUI-02。

## 19. 2026-10-22 RC 整改合批与 M1 用户闭环

固定候选 `465d1624a77a4e266540409593bc4ee019bd14ea` 的累计 Full Fast 与正式 RC 实际失败，原标签 `tui02-rc-465d1624a77a` 保留原结果。独立 Publication PostgreSQL 为 109 passed、6 deselected；它不能抵消 RC 失败。后续提交 `47c9b6badceedbc9798a98b184f53bd5829a5ab8` 仅刷新退出 Streamlit 后的架构生成投影，五项 push 工作流通过，尚不构成新的完整发布资格。

本轮按两个完整事项合批处理，先运行针对性回归，再短时占用共享 Git 窗口整合，不为每个小修复重复完整 RC 或制作一套文档、ZIP：

1. **测试隔离与启动注册**：SQLite 备份测试立即恢复同一 DATABASES 映射的原 ENGINE/NAME，避免后续事务清理访问临时备份源库；Equity 通过常规 Admin 自动发现入口转发唯一既有注册。早期费用 Admin URL 失败与后期数据库配置泄漏分别验收，不把此前通过的迁移测试写成失败。整合时从新父提交重建模块投影，保留已有数据库与权限守卫。
2. **TUI 完整任务契约**：按既有两阶段协议在静态编译时延后完整运行时图表 panel，运行时仍做严格验证；用官方构建器重新生成运行时清单。修正已过时的八 panel、Linux 依赖标记与 `/dashboard/` 跳转断言；等待实际页面就绪和信号创建成功结果。Beta 结果名称展示改用现有本地只读解析并支持代码回退；这条已确认的远程补名称路径尚未证明就是本轮卡住的根因。保留原 M5 业务断言、时限及完整选集，增加有上限且去敏的请求诊断；POSIX 自有服务线程采样只是尽力取证，不保证清理前一定产出。

M1 先验收普通用户在一个模拟账户上完成可读调仓计划，不等待完整 A 股平台建设或 TUI 最终观察退役结束。与 A 股后端对齐既有账户巡检入口及持久报告/建议契约；界面必须呈现有内容且可解释的数量、费用、现金和买卖依赖、来源时间与使用限制，未知或越权输入正确阻断。合成 fixture、Admin 访问和单纯 API 成功均不能代替这项普通用户动作；尚未完成实际验收时不得宣称 M1 通过。

独有源码、缓存和证据目录可并行轻量准备；重型数据库、浏览器、全量类型及镜像验证按资源排队，数据库、队列、端口与缓存隔离。共享源码、生成投影和 Git 只在协商窗口内短持；不覆盖 A 股或监控主线的未提交改动。独有副本针对性无数据库回归实际为 103 passed、0 failure/error/skip；Black、isort、Ruff 与官方 npm 构建/清单检查均为 0。三份 JS 生成内容仅有换行差异，清单内容哈希只改变 IA 输入；编译器与严格运行时契约回归通过。后续隔离数据库验证实际为备份 1 passed、原生 PostgreSQL 迁移业务守卫 1 skipped，早期 Admin/费用 7 passed；不得把 SQLite 上的跳过写成迁移业务通过。3 个生产文件增量类型与默认全库类型债务均为 0，官方架构/入口/模块投影及 Web 迁移清单均通过，两个 PID 测试数据库已清理。最初误传架构脚本参数的退出 2 保留，随后仅补跑正确官方静态检查，不重复或改写已有测试结果。本节候选尚未整合共享分支，不代表新 RC 资格；本地 Django 5.2.12 与最终锁定运行环境的差异仍由同候选 CI/S6 复核。

下一不可变候选保留累计基线 `ecb59591e3696b89d0f66457a66993c07efe7e84`，在同一 SHA 上实际通过必需 push CI、累计 Manual Full Fast、独立 Publication PostgreSQL 和完整正式 RC；其真实完整 QLib 镜像另验版本、导入、原生消费者和无过滤安全报告。通过后再运行 disposable PostgreSQL 的 fresh S6，测试口令仅经内存、stdin 与匿名 FD 3。最后提交包含镜像身份、当前 VPS/401 认证状态、迁移顺序、兼容回滚和验收动作的具体部署方案供 Owner 确认，当前不部署。

14 天生产观察候选保持固定，周度开发与隔离验收继续；低频任务逐项验收并由实际独立人员复核。`production_manifest_review_satisfied` 仍为 false，不开始 T0、不关闭 TUI-02。回滚按本轮独立业务提交处理，不能重置共享分支或跨 SHA 拼接成功结果。

本轮完整日志、JUnit 与候选源码仍保留在本机忽略目录，未声明已上传远端。无数据库验证索引 `.tmp/tui-rc4-followup/full-rc-diagnostic-work-r1/light-regression-r1/receipt.json` 的 SHA-256 为 `ecb70f2749ff095959a7570a1d27d67eba08b4fae06596fa10702fb1af27ee44`，JUnit SHA-256 为 `0e3a1bcbd355643ec479285480fd1078c7329bdd35677b4f6ebea1661282e90c`。465 终态索引为 `.tmp/tui-rc4-followup/final-candidate-465d1624a77a/ci-monitor-r1/final-receipt-r1.json`（SHA-256 `f2d59570175a55ebcc981a76caaa00261e3bbd7176f2699fa11232141dc7bac9`）。

两事项合批本机验证结论索引为 `.tmp/tui-rc4-followup/full-rc-diagnostic-work-r1/known-rc-fixes-validation-summary.json`（SHA-256 `72b136d7b33088339e4f35d7137d313e93f6384a76e5bc35227759ff8a464752`），包含每次真实输入、原始失败、修正命令、JUnit、版本与测试库清理状态；本节只在这些开发验证完成后补充文档结论，最终发布仍验证新的精确 SHA。

### 19.1 累计检查的格式兼容修正

候选 `6486369d12db11476e2785e1b79bb7418d98e465` 的五项常规 CI 通过；累计 Manual Full Fast `39745140913` 的增量检查实际失败：CI 使用 Black 26.10.1，本地原检查使用 26.3.1，三个 UAT 测试文件需重新格式化。独立 Publication PostgreSQL `39745309123` 通过，不替代该失败或正式 RC。原候选标签保留，不将后续修正算入原候选。

本次只调整这三个测试文件的换行和括号格式。父代理逐个核对 Git 原件、候选哈希及 AST 等价，保留 BOM 和 LF；使用精确候选配置及 Black 26.10.1 的三文件 CLI 检查实际通过。原累计 229 文件的同版本 Python API 复现恰好三处差异，替换后差异为零；这项结果明确为 API 检查，不宣称运行了 229 文件 CLI。生产代码和断言含义未变，本次无需数据库或生产增量类型检查。

本机原件索引 `.tmp/tui-rc4-followup/final-candidate-6486369d12db/format-fix/manifest.json` 的 SHA-256 为 `e569f614de3e61d726c3b34a3b792e4bdc6078a8cdd0d3ea83555c150a83cf2f`，同目录 `cli-three-receipt.json` 记录实际 CLI 退出 0。首次 BOM 解码失败和 CLI 配置预检拒绝均保留，未覆盖为成功。新提交仍需自己的累计验证；实际 M1、完整 RC、S6 和发布资格尚未因此通过。

### 19.2 服务端契约变化后的运行时清单修正

Calendar 提交 `ea49570f269cbc40bb34b002039ad3f19d2d8b95` 的自动 Fast `39802515256` 实际失败于 `Verify TUI Runtime bundles`：清单登记的 129 个文件中，仅本批修改的 `apps/terminal/interface/api_views.py` 哈希未同步。两项 Python 版本测试任务均通过，但不能抵消清单失败。该 SHA 的其余五组自动工作流成功仅属于原 SHA，不转记后续候选。

本次使用官方 `npm run build:tui` 重新生成，再运行 `npm run check:tui`，均退出 0；清单只改变来源提交、构建 ID 和一个输入哈希，三份 JS bundle 与父提交经 CRLF 规范化后相同。前端完整 184 项测试通过，无失败、跳过或取消。本地 Node 24.18.1、esbuild 0.25.12 与锁一致；新 SHA 的 Linux/Node 22 CI 仍须实际验证。另通过 stdlib `runpy` 执行既有纯清单契约断言，未加载 Django/数据库，不记作 pytest 运行。无生产 Python 改动，不重复数据库或类型回归。

本机精简索引 `.tmp/tui-rc4-followup/final-candidate-ea49570f269c/runtime-manifest-repair-r1.json` 的 SHA-256 为 `a91ce1840669a73e9b1c37ade1476d2c4571e30219322db8281daac7446453bb`，保留原失败日志、Node 测试日志、清单和受保护文件身份；原件未上传，不覆写原失败。

后续新 SHA 重新取得适用的自动 CI、累计 Manual Full Fast、独立 Publication PostgreSQL 和完整正式 RC。Publication 的 push 路径过滤不含本次清单文件，因此在新不可变标签上使用其既有手动入口运行完整契约，不拿旧 SHA 的成功补数。累计基线仍是 `ecb59591e3696b89d0f66457a66993c07efe7e84`。最终 ReDoc 实际渲染、完整 QLib 镜像、fresh S6、真实迁移顺序与兼容回滚仍待验证；测试 superuser 只在 RC 通过后的 disposable S6 中创建。当前不部署、不启动 T0、不关闭 TUI-02。
