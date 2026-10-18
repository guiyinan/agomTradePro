# TUI-02 收口、观察与测试部署方案

方案创建：2026-10-18；本地收尾更新：2026-10-19。状态：本地三批实现已提交；本任务未执行远端变更，TUI-02 未关闭。

## 1. 已批准的决策与边界

Owner 在本聊天批准“一次 14 天生产冻结例外，低频任务逐项验收和独立复核”，要求与 A 股协调、认证修复和验收规则分批提交，具体部署方案再确认。通用政策批准不能代替实际任务 UAT 或单项风险接受。

已独立核实 Owner 在“观测开发进程”的补充：“现有的vps部署可以随时更新，因为没有实际投入生产”及“不用备份”。因此当前 VPS 按测试/演示环境处理：普通升级不等待每周窗口或正式 Classic 退出资格，本次不创建、下载或校验备份；保留数据卷和密钥。此前备份下载及本地校验没有完成，不记作已验证恢复点。

正式迁移观察仍采用已批准的同候选 14 天冻结，真实 T0 加 1,209,600 秒得到 eligible instant；容器启动、部署时间和 up 样本都不能代替 T0。观察对象被升级时，真实重置或结束本轮，不能跨候选拼接。无需再次批准相同冻结政策；目标资格、候选身份、真实采集和逐任务验收仍须成立。本聊天要求的具体部署确认保留。

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

A 股协调会话：`codex://threads/01a14268-4d88-75e2-812a-fdbdd60b1b24`。共享 `dev/next-development`，使用独立提交；不新建开发分支、不覆盖 A 股脏树、用户文件或 intent-to-add 状态。双方各最多一个重型 QA；TUI 仅获准指定 scripts/schema/tests/docs，不使用共享 DB，不写 registry 或共享生成投影；Git/index 窗口串行移交。

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

## 5. 具体测试部署提案（确认前不执行）

固定代码候选：`505848aa14a51a843b67bfa793870bc64ea06344`。本文件后续 doc-only commit 不纳入该源码候选，以免自引用 SHA。该 SHA 是本次本地可审阅候选，尚不能称为部署就绪；若 A 股 CI 修复形成新 SHA，必须重新固定并验证后再给出最终发布身份。候选内容为已提交 TUI 升级、认证、两阶段低频契约、A 股基线及期间独立工程仪表盘提交；不从共享脏树打包，不包含未提交 ASH03-B。

目标：由 `AGOM_VPS_HOST` 指向已核查测试 VPS；user/port 取环境，不在方案保存密码；target `/opt/agomtradepro`（必须与环境一致），compose project `agomtradepro`。方式：`upgrade`、code-only、明确 `-SkipPreDeployBackup`；保留 PostgreSQL/Redis/媒体/Prometheus 数据卷、加密密钥及旧 release/image。无 wipe、SQLite 导入、数据库恢复、凭据轮换、实盘开关、下单、付费 AI、额外回填或 Alpha/decision-repair。

从线上 `d3fdbd6f…` 到已提交 `94130f88…` 有 24 份新增迁移：account0067，data_center0090—0103，risk_center0010—0011，simulated_trading0024—0030。实际待执行数须只读读取 django_migrations，不能以 Git 数量替代。后续候选再核对迁移差异；未提交 account0068、simulated_trading0031 不自动进入。position knowledge 迁移有反向丢失保护，不能假定所有 DDL 可撤销。

执行顺序与停止条件：

1. A 股交还 VPS 写窗口后，先只读核对 release/commit/image、数据卷、密钥文件权限、数据库已应用迁移和任务开关。身份与计划不一致先停止并更新范围，不能盲目覆盖。
2. 确认后为固定 SHA 发布不可变 Git tag `tui02-observation-505848aa14a5`（已有同名但不同指向则停止，绝不覆盖）；从该 tag 的独立干净源码准备同镜像构建、迁移计划、旧镜像在新增 schema 上兼容性验证及官方 release rehearsal/receipt。不得用其他 SHA 的 CI/S6。当前没有可用的新镜像/receipt，制品验证失败就不切换；不创建备份来替代兼容性证明。
3. 真实源码确认 cold-start 带 `--preserve-protected-schedules-disabled`；但后续 `setup_macro_daily_sync` 会把 daily-sync-and-calculate、check-data-freshness、high-frequency-generate-signal、high-frequency-recalculate-regime 设为 enabled。四项现态和参数必须已启用且语义一致，否则停止并另给最小修复。Celery 与 queued worker 沿用既有授权；wrapper 默认 Celery=true 不能直接覆盖现态。
4. 使用仓库发布入口 `scripts/deploy-vps.ps1 -Upgrade -SkipPreDeployBackup -GitBranch tui02-observation-505848aa14a5`，固定源码 SHA、真实 prebuilt tag/image、manifest/receipt、目标日期、universe/provider/settings 摘要和 GitHub run。wrapper从干净候选 HEAD 获取 `--expected-source-commit`，远端 clone 必须精确匹配；tag 指向与固定 SHA 不同则停止，不能临时改用脏树上传或绕证据。保留自动代码回滚，禁用 Alpha/decision-repair 引导。必要的迁移、静态资源、能力目录、TUI registry、bootstrap、周期配置与 superuser reconciliation 均是明确写入，预计短暂停机。
5. 认证 preflight 失败时不进入停服务或迁移。新服务失败时仅按已验证的 schema 兼容性恢复旧镜像/release；不能反向删除保留数据或自动数据库恢复。无法安全回滚时停止服务并报告事实。
6. 发布后核对 health/ready、容器和不可变身份、HTTPS/QLib 身份、数据 freshness、Caddy 账号与认证矩阵、up/rules/保留，以及普通任务与专业入口。匿名/错误凭据 401，正确 query/query_range 200；9090 继续不公开，decision-ready 的独立限制不掩盖。
7. 只读核查迁移原始序列；需要验证埋点的实际安全读取任务列入手工 UAT。不得通过下单、导入或付费调用凑样本。采集缺失保持缺失并定位，不开始虚假 T0。

后续确认对象是上述固定候选的测试升级范围、免备份方式及失败停止线；当前制品和发布前置未齐，不请求现在确认上线。制品和兼容性预检是执行前的必需工作，未执行不得报告“部署就绪”。若预检产生范围变化、额外任务启用或不可安全回滚，应带具体差异再确认；不能把计划批准当作任意部署授权。

## 6. 正式观察与 TUI-02 完成标准

测试部署成功不等于正式生产资格。目标资格、同候选身份、认证与真实采集成立后，按已批准冻结例外生成官方 deployment attestation、retained checkpoint 和绑定，开始真实 14 天。开发、隔离 QA、下一版构建继续；观察对象冻结，紧急修复或升级按真实重置处理。

eligible instant 后以 `python scripts/check_web_to_tui_cutover_readiness.py --require-allow` 的真实结果验收九项前置与同候选批准。普通任务用统计，低频逐项 UAT/风险接受/独立复核，未通过的任务继续阻断。ALLOW 后再逐波执行 Classic 退出，每波独立候选、至少 48 小时及计划周期、无阻断缺陷、独立复核和回滚，最终 `check_web_to_tui_cleanup_guard.py --require-allow`。

TUI-02 只有在 registry 全部退出项、应完成波次和观察、正式备份/回滚与 sole-owner 最终签字均成立后关闭；不能以认证恢复、本地测试、等待满 14 天或普通测试升级替代。当前未删除 Classic，未生成任何实际 UAT 或任务批准，未关闭 TUI-02。
