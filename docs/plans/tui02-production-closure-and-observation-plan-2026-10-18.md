# TUI-02 收口、观察与测试部署方案



> 历史验收原件已迁出 Git；原路径、逐文件哈希和恢复方式见[归档索引](../testing/evidence-archive-2026-10-19.md)。历史结论与当时失败记录保持不变。



> 本轮执行边界（2026-10-19）：Owner 最新要求是“通过后把具体部署方案给我确认，先不要部署”。因此本轮只做分批提交、隔离回归和同候选 RC/S6；不执行 VPS 部署、生产迁移、release 切换或观察 T0。下文保留的既往测试升级授权及历史候选不是本轮执行许可。具体候选、镜像、迁移/回滚证据和部署步骤齐备后，提交可审阅方案给 Owner 确认。



方案创建：2026-10-18；状态更新：2026-10-20。必要 TUI 修复已完成本地预览；A1 不可变候选的完整 RC 已失败，正在修正测试夹具并准备新候选。已实际完成隔离 PostgreSQL 两项 API、SQLite 两项 API 和一项末尾单测诊断；这些组件结果不代替最终同 SHA 的完整 RC/S6。尚未创建 S6 测试账户、部署或开始观察 T0，TUI-02 未关闭。

当前整合基线为 `ab02035a4b3e27240b1ee71b6a596330870c1cf0`；本轮待采用的夹具修正和 CI 诊断将在此基线上独立提交，再固定新不可变候选。下列早期批次及后续组件证据只适用于其实际输入，不拼成最终发布资格：

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

独立 CI 小补丁仅把 full-unit 非终止性 `faulthandler_timeout` 从 600 秒改为 30 秒，以便下一轮在截止前留下阶段栈；35 分钟步骤、300 秒单例、完整选集和覆盖率不变，不宣称性能问题已解决。官方 test-tier 投影须在不含外来 WIP 的干净私有来源中生成/复核后采用。A 股后续 G2B 私有业务补丁不进入本轮冻结范围；以后 dev 提交不得移动该标签。最终同候选完整 RC、独立 Publication PostgreSQL 和 fresh S6 仍待实际执行，测试身份不得替代独立人类复核。

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



此前本地候选 `505848aa14a51a843b67bfa793870bc64ea06344` 及中间整合基线 `e18c796a7413aa2007bfa5545b47f71f39383bc6` 已被后续修复链取代，不得继续按其旧标签发布。当前仍在分批合入修复，尚未固定最终候选。待必要修复和方案说明提交后，由统一 RC 入口固定最终提交和新标签。发布包只能来自已验证的干净提交，不能从共享脏树或私有 overlay 打包；本节占位标签必须替换为真实、同源码验证的标签后才可执行。旧 CI、不同 SHA 的局部结果或本地通过均不能替代新候选资格。



目标：由 `AGOM_VPS_HOST` 指向已核查测试 VPS；user/port 取环境，不在方案保存密码；target `/opt/agomtradepro`（必须与环境一致），compose project `agomtradepro`。方式：`upgrade`、code-only、明确 `-SkipPreDeployBackup`；保留 PostgreSQL/Redis/媒体/Prometheus 数据卷、加密密钥及旧 release/image。无 wipe、SQLite 导入、数据库恢复、凭据轮换、实盘开关、下单、付费 AI、额外回填或 Alpha/decision-repair。



以历史只读核查的 VPS 源码 `d3fdbd6f…` 为比较起点，到已提交 `e18c796a7…` 的 Git 新增迁移为 28 份：account0067—0068，data_center0090—0103，risk_center0010—0011，simulated_trading0024—0033。E 没有模型或迁移改动。实际待执行数仍须重新只读读取目标 `django_migrations`，不能以 Git 数量或旧 VPS 版本替代线上事实。新纳入的 account0068 分类历史券商回执为未核实；simulated_trading0031—0033增加估值、现金、成本/费用知识状态，其中现金迁移分类既有账户，历史成本保持 unknown。这些迁移带反向丢失保护，不能假定所有 DDL 可撤销；预检须确认旧镜像在新 schema 与 unknown 状态下的行为兼容，不能仅证明字段可读。



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
