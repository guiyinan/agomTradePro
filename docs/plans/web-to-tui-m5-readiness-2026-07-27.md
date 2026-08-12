# Web → TUI M5 Readiness 判定（2026-07-27）

## 当前结论

**M5 清理判定：DENY。**

> 2026-08-13 代码复核修正：此前仓内 108/108 UAT、108/108 cleanup 与本地 rollback
> 仅绑定旧 Markdown 摘要，未绑定最终 candidate commit、当前 matrix、published graph、
> schema、runtime version/build 和 runtime manifest，不能再记为通过。readiness 已改为对三类
> 证据要求完全一致的 candidate binding；当前旧证据均显示 `binding=false` 并失败关闭。
> 本节以下 7 月 27/28 的“通过”叙述保留为历史执行记录，不再代表当前候选 gate 状态。

M0–M4 的仓库实现已完成，迁移矩阵中的 17 个 B 类 route template 已全部迁入
TUI，B 类 backlog 为 0；但这不等于获得 Classic 删除授权。2026-07-28 只读生产
preflight 确认线上仍运行 `dev/next-development@2e399607977fea260436992952fae64565153213`，
该提交不包含当前迁移矩阵。2026-07-26 因而只能视为历史预定基线，不能回填为当前候选
观察起点。当前机器证据尚未绑定候选稳定版本及其起止时间，稳定窗口尚未开始；最早复审日
必须由真实候选部署后的机器窗口计算。证据见
`web-to-tui-m5-production-preflight-2026-07-28.md`。

2026-08-13 再次只读 preflight 已确认生产 release 更新为 `source-20260813002655`，因此上段
`2e399607…` 只保留为 7 月 28 日历史事实；但当前镜像 OCI revision 为 `unknown`，release 又无
`.git`/source manifest，仍无法绑定任何候选 commit。公开 health/ready 均为 200/ok 不改变
此结论。见 `web-to-tui-m5-production-preflight-2026-08-13.md`。

## 退出门槛快照

| 门槛 | 当前证据 | 判定 |
|---|---|---|
| 至少 1 个稳定版本且不少于 14 个自然日 | 当前 release 为 `source-20260813002655`，但 OCI revision=`unknown` 且无 source manifest，不能绑定候选；`stable_version`、`candidate_commit`、`released_at`、`observation_end` 尚未建立 | 未通过 |
| 计划内角色与主路径 UAT 100% | 历史覆盖为 108/108，但未绑定当前 candidate graph/runtime snapshot | 未通过；须对最终候选重跑并结构化回写 |
| 逐 route 清理条件 100% | 历史六类 scope 为 108/108，但缺当前 candidate binding；cleanup recorder 尚待补齐 | 未通过 |
| P0/P1 阻断缺陷为 0 | 尚无覆盖完整兼容窗口的缺陷报表 | 未通过 |
| 旧入口占比 ≤ 5% 或低频例外双签 | 已实现矩阵驱动的有界 Classic/TUI 同任务指标与 14 日 PromQL；尚无生产样本 | 未通过 |
| TUI 错误率不高于基线 0.5 个百分点 | 已把 Classic 同源 API execution 通过受审 Referer 归入固定 task，并实现 task request 对照和最小样本告警；101 个 comparable task 当前无生产窗口数据 | 未通过 |
| wave 级 graph/runtime 与 route/template 回滚演练 | 旧本地演练未绑定当前 candidate graph/runtime/build，且当前静态 drill baseline 已漂移 | 未通过；须修复并重跑最终候选演练 |
| 生产 registry 可校验备份 | 仓库外备份/恢复工具与集成测试已完成，但尚无绑定候选版本、commit、矩阵 SHA、外部 locator、完整性摘要和恢复验证的生产证据 | 未通过 |
| owner 与独立 reviewer 切换审批 | 尚无绑定候选版本、commit、矩阵 SHA 和经摘要校验评审快照的双签 | 未通过 |

## 当前已通过的实现门禁

### 2026-08-13：candidate binding 与 observation 防回填加固

- 新增统一 candidate binding：稳定版本/完整 commit、matrix SHA、published graph SHA、
  schema version、runtime version/build ID 与 runtime manifest SHA 必须完全一致。
- readiness 现在对 UAT、cleanup、rollback 和 production registry backup 重新核对当前 binding；
  仓内旧证据实测全部因 `binding=false` 为 FAIL，不再产生旧证据假阳性。
- observation 启动不再接受 caller 提交 `released_at/as_of`；只能读取仓库内 HEAD 已提交且
  byte-exact 的 production deployment preflight，核验 production release/source commit、OCI
  image/revision、health/readiness 200/ok 响应摘要及时区感知单调时钟。health/verification 必须在
  30 分钟内、部署不超过 24 小时，窗口从 `verified_at` 当日开始，不能回填证明前时段。
- 更换候选会清空 UAT、cleanup、defects、telemetry、rollback/backup、review snapshot 与审批。
- observation 合成测试 `15 passed`；candidate/readiness 相关全组在本机受慢速/临时目录权限影响
  未取得一次完整结束证明，但旧证据实际 readiness 输出已确认 DENY。
- UAT/cleanup/rollback candidate recorder 已实现：固定执行套件并重解析 JUnit，任何
  failure/error/skip 都拒绝写入；rollback 只接受 drill v2 exact binding，CLI 不接受自报
  `passed`。结构报告有独立 JSON Schema，专属测试 `5 passed`。
- 当前 cutover candidate 未建立，candidate recorder 实测按设计 FAIL 且不写 evidence，readiness
  仍安全 DENY。M5-B wave recorder 已补齐，但当前没有删除候选、部署 attestation 或 48h 原始
  生产记录，不能用 candidate cleanup report 冒充每波生产观察。

### 2026-08-13：candidate-bound rollback drill v2

- 删除易漂移的静态 baseline/new-path 清单；从代表 wave 的 migration anchor 唯一新增提交
  自动推导 baseline parent，candidate/ref 先解析为 immutable commit。
- patch、artifact manifest、graph/schema contract、runtime manifest 和矩阵 rollback commit 全部从同一
  candidate Git snapshot 重建；工作树不作为候选证据读取。
- 真实本地隔离 reverse/forward 演练通过：31 artifacts（3 added / 18 modified / 10 unchanged），
  graph actions `402 → 430`，runtime manifest 18 files 逐一验摘要，回滚与恢复后内容精确。
- 针对测试 `3 passed, 1 skipped`；skip 为当前环境缺 Django 的 registry publish/rollback/restore 往返用例。
  本地代表 wave 不替代生产 registry 备份/恢复、真实部署或全量 wave 验收，cutover 仍 DENY。

### 2026-08-13：M5-C 最终库存门禁

- `web_template_migration_inventory.py --require-finalized` 已与迁移期普通 `--check` 分离；普通检查语义不变。
- 最终模式精确要求 41 个 C 档物理模板，A/B/D 全部 `deleted`，并扫描已删模板的活 view/route literal、孤儿静态资产及 published legacy alias 的 canonical target 与生产代码消费者。
- 当前普通检查通过（196 行，A=131/B=17/C=41/D=7）；最终模式按设计 DENY，148 个 A/B 模板尚未完成 lifecycle。32 个 alias 中另有 11 个没有活生产代码引用，`capability-router.gateway` target dangling。
- 门禁专属测试 `10 passed`；当前机器缺 Django runtime，历史 inventory rebuild 的 Django resolver 用例未纳入本次专属测试。静态引用扫描不替代生产流量证明，真实 alias 删除仍须进入逐波观察与回滚证据。

### 2026-08-13：M5-B cleanup wave recorder

- recorder 从 candidate Git snapshot 重算每波新增删除、连续 wave、1–10 route、telemetry task coverage 与 rollback commit，不接受 caller 自报 scope 或 `passed`。
- 必须提供已提交的 production deployment preflight；stable version、source commit 与 OCI revision 均精确绑定删除候选，attestation commit 位于 candidate 之后且不晚于观察开始。
- candidate observation 必须发生在 deployment verification 之后且不少于 48 小时；telemetry、P0/P1 tracker 与 scheduled cycle 原始记录分别按 exact schema 重算，窗口/候选/任务集合不一致即失败。
- 三个 wave artifact 先写 SHA，cutover evidence 原子替换失败时回收本次 artifact；专属测试 `14 passed`，strict mypy、Black、isort、schemas、compile 与 diff check 通过。
- 当前仓库没有 M5-B 删除候选和对应生产证据，真实 CLI 保持 FAIL；本实现只关闭 recorder 缺口，不代表任何 wave 已观察或获准删除。

### 2026-08-13：发布 provenance fail-closed

- source-upload 拒绝 dirty worktree 和非完整 Git SHA；git-clone 在构建前后锁定并复核 exact candidate commit。
- 构建强制 OCI revision 等于源码 commit，并生成只读 exact-schema release manifest；deploy 在任何服务启动或 `current` 切换前复核 manifest、image ID 与 OCI revision。
- 相关本地回归 `44 passed`，strict mypy、格式、编译和三个生成 shell 的语法检查通过；Ruff 未安装。
- 代码整改尚未部署，当前生产仍是本页所述 OCI revision=`unknown`/无 manifest 状态。它不能替代真实候选部署、deployment attestation 或观察窗口，readiness 继续 `DENY`。

- M4：17/17 个 B 类 route template 已迁移，0 backlog；完整 TUI Workbench 加操作组
  非 sticky 回归现为 `240 passed`。
- AGENTS.md 固定其余三组最小回归：`35 passed`；IA 与归一化幂等：
  `7 passed`；inventory/static：`5 passed`；完整 Workbench `240 passed`。
- 迁移矩阵：196 行、117 个历史 route page，A/B/C/D 互斥校验通过。
- Django system check、ruff、增量 mypy 与全仓 architecture verify 通过。
- `web_to_tui_migration_events_total` 使用受审 route/action/screen 目录限制标签基数；
  14 日 Classic 占比、样本量和 execution 错误率 recording rules/alerts 已实现。
- M5 回滚演练通过：旧 graph 与当前 `tui-metadata.v3` 兼容；真实 patch 在临时目录
  完成 reverse/restore；pytest registry 发布/回滚/恢复为 `1 passed`。
- M5 浏览器套件 `15 passed`：覆盖账户读/详情、缺参、确认取消、operator/普通用户
  权限边界、3 个 viewport、108/108 migrated route 深链、71 个角色化直读 route、9 个
  参数化读取 route、策略和个人 AI 服务商创建→详情→更新、Policy 管理员创建，以及
  决策配额/Beta Gate/股票与基金筛选确认流程、Agent/Alpha/Audit/Backtest/Factor
  本地详情与生命周期，以及通过本地加密 Provider 真实执行的 Sentiment 与 Terminal
  Agent 外部 AI 主任务；并验证账户 P0 持仓读取不再同步创建默认账户。人工复核 console
  error 为 0。证据见
  `web-to-tui-m5-browser-uat-evidence-2026-07-27.md`。
- M5 机器 gate 已落地：`check_web_to_tui_cutover_readiness.py` 同时校验矩阵/catalog
  SHA、108 个 route UAT、101 个 production telemetry task、稳定窗口、P0/P1、低频
  双签、回滚、registry 备份和独立审批。当前输出为 `DENY`，不是待办文字推断。
- 2026-07-28 生产 preflight 通过公开健康/就绪探针和只读 SSH 核对了 release、Git commit、
  OCI revision 与容器状态：生产运行面健康，但部署版本仍为不含当前迁移矩阵的旧提交。
  该证据明确阻止观察窗口回填，不替代任何生产 cutover gate。
- 候选观察窗口启动器已落地：`start_web_to_tui_observation.py` 会把候选版本绑定到可解析且
  属于当前分支历史的完整 commit，并要求该 commit 内的迁移矩阵与当前矩阵一致、工作树干净；
  默认只 dry-run，显式 `--write` 才写入 14 日窗口。切换候选必须使用 `--replace`，旧候选
  的缺陷、生产遥测、生产 registry 备份、评审快照和审批会被清空，不能跨版本复用。
- 阻断缺陷 evidence 生成器已落地：`build_web_to_tui_defect_evidence.py` 只接受仓库内、绑定
  同一候选版本/完整 commit/矩阵 SHA/精确窗口的 GitHub/Jira/Linear 快照，并要求固定
  `created_or_open_during_candidate_window` 查询范围、无凭证 HTTPS 来源、查询人和快照 SHA。
  工具从 issue 生命周期分别推导 `new_p0/new_p1` 与 `open_p0/open_p1`；四项必须同时为 0，
  窗口内新增后关闭的缺陷仍阻断，不能只看结束时 open 数。默认 dry-run，真实非零快照可写入
  留痕，但 `--require-clear` 和 readiness 必须失败。当前没有候选缺陷快照。
- 生产遥测 evidence 生成器已落地：`build_web_to_tui_production_telemetry.py` 只接受仓库内
  经复核的 production Prometheus 快照，并要求候选版本、完整 commit、矩阵 SHA、精确 14 日
  窗口和 `classic_routes.task_key` 推导出的 101 个可比较任务完全一致；TUI-only action 不进入
  生产门禁分母。六条 PromQL、整数计数、5% Classic 占比、两侧各
  20 个 task request、0.5 个百分点错误率回退和低频独立双签均 fail closed；默认 dry-run，
  显式 `--write-evidence` 才更新 cutover evidence。runtime 分类器同时排除匿名登录跳转、
  匿名 TUI shell 和伪造 Referer 的公共 API 请求，只让已认证任务流量进入门禁。当前没有
  生产快照，仍为 0/101。
- 生产证据已改为强绑定：候选版本必须带可在本仓库解析的完整 commit；UAT、回滚、缺陷与遥测必须有
  仓库内证据及与实际文件一致的 SHA-256，缺陷/遥测还要求查询或采集时间；registry 备份
  必须带证据/payload/graph SHA-256、generation、schema/runtime、恢复验证、验证人和
  保留期，并绑定候选版本、commit 与矩阵 SHA；owner 与独立 reviewer 的批准还必须绑定
  经 SHA-256 校验的同一评审快照。占位字符串、摘要不匹配、过期审批、路径穿越或缺失
  证据文件、虚构 commit、本地占位 locator 或非正 generation 均不能放行，对应
  fail-closed 单测 `29 passed`；同时覆盖候选提交内矩阵、结构化快照重建、逐 route 清理
  scope/回滚映射、备份 attestation/保留期与观察窗口结束后审批时序。
- 2026-07-28 checker 再次收紧：候选 commit 还必须属于当前分支并实际包含当前矩阵；108 条
  route rollback mapping 必须逐值等于矩阵，不再只验 SHA 可解析；缺陷与遥测 gate 会重新解析
  JSON 快照并调用生成器重建 evidence，摘要匹配的 Markdown、手工改写计数或跨候选快照均不能通过。
- `build_web_to_tui_review_snapshot.py` 只在其余 8 个 gate 全通过时冻结精确 gate 结果，并清空
  旧签字；`record_web_to_tui_cutover_approval.py` 分别生成 owner/reviewer 角色绑定 attestation，
  强制不同身份、候选/矩阵/快照摘要一致和窗口结束后签署。Checker 会重建 review snapshot 并
  逐份核对 attestation；工具只记录真实审批，不能代替或伪造审批人决定。
- 2026-08-13 修复 cleanup guard 的 SHA 不可达循环：不再把删除后 matrix 交给变更前的
  full readiness，而是先从 pre-cleanup candidate Git blobs 重放 final review snapshot 与外部
  owner/reviewer attestations，再逐 M5-B wave 重建删除后 matrix/catalog/graph/runtime binding。
- 每波强制精确删除范围、≤10 route、物理删除、legacy URL policy、独立复核、rollback manifest
  和串行 commit lineage；外部 SHA observation ledger 还必须覆盖≥48 小时及至少一次定时周期，
  P0/P1 全 0，基线/候选请求各≥20，错误率回退≤0.5 个百分点；前波完成观察后才能开始后波，
  最后一波必须绑定当前 snapshot。caller 自写 `passed=true` 会因 exact schema 失败。
- cleanup guard 针对测试 `15 passed`；当前尚无正式 cleanup wave/rollback manifest/observation
  ledger recorder，因此真实新删除仍保持 DENY。
- A/B route 即使在 M5-B 标为 `deleted`，仍保留在 108-route UAT/清理范围和 telemetry
  catalog 中；对应回归证明删除状态不能缩小证据分母或绕过历史任务监测。
- 逐 route 兼容面首批证据 `2 passed`：展开 108 route 的 118 个 URL pattern，验证匿名认证
  边界、模板继承/include 后的审核 TUI 目标和 Terminal 精确重定向；修复 5 个匿名 200、
  2 个认证前对象查询及 7 个手写提示漂移。当前只关闭 `legacy_url`，不冒充完整权限/状态证据。
- Registry 备份/恢复命令已落地：备份只能写到仓库外并原子生成 JSON + SHA-256 sidecar；
  恢复默认 dry-run，显式批准时还要求匹配当前 active source hash，并记录 rollback ancestry。
  `build_tui_registry_backup_evidence` 会再次验证 bundle/sidecar、当前 active generation/hash、
  restore payload、候选窗口和保留期，只把不含 payload 的结构化 attestation 写入仓库；checker
  要求 attestation 与 cutover projection 精确相等。这只证明工具可用，不代表已经取得生产备份。
- Published metadata 收口为 12 screens / 399 actions；删除 8 个无 screen/panel/矩阵消费者且
  缺少必填参数的旧 auto action。全新迁移 SQLite + staff 用户 + 同库 localhost 下，read/AI
  action smoke 为 `380 total / 238 ok / 142 needs_input / 0 error`；Regime、Pulse 首装空态返回
  200，AI Provider 未配置返回受控 503，不再依赖历史开发数据冒充通过。

## 机器判定快照

```text
Web-to-TUI M5 cutover: DENY (as of 2026-07-28)
PASS source_consistency
FAIL stable_version_window: commit=missing_or_source_mismatch
PASS route_task_uat: covered=108/108; evidence=true
PASS route_cleanup_readiness: covered=108/108; scope_counts=empty_state:108,error_state:108,legacy_url:108,permission:108,primary_task:108,rollback:108; scopes=true; rollback=true; rollback_matrix=true; lifecycle=true; evidence=true
FAIL blocking_defects: evidence=false; structured_snapshot=false
FAIL production_telemetry: covered=0/101; production_evidence=false; structured_snapshot=false
PASS rollback_drill
FAIL production_registry_backup: evidence=false; structured_attestation=false; integrity=false; restore_verified=false
FAIL cutover_approvals: owner=missing; reviewer=missing; snapshot=false; attestations=false
```

日常一致性检查：

```bash
python scripts/check_web_to_tui_cutover_readiness.py
```

release owner 明确选定并部署包含当前矩阵的干净候选提交后，先执行 dry-run，再显式开始观察：

```bash
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD>
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD> --write
```

本地 M5 实现已形成可审计提交，但尚未推送或部署为候选；生产仍运行
`2e399607977fea260436992952fae64565153213`。该命令必须 fail closed，不能用当前 `HEAD`、
本地文档状态或旧生产版本冒充稳定候选。

观察窗口结束并把不含密钥的 issue-tracker 快照存入仓库后，先 dry-run，再写入 evidence：

```bash
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --require-clear
python scripts/build_web_to_tui_defect_evidence.py \
  --snapshot <repo-relative-defect-snapshot.json> --write-evidence --require-clear
```

快照必须使用 `web-to-tui-blocking-defect-snapshot.v1`，登记 candidate/source/window、
`created_or_open_during_candidate_window`、tracker system/project/HTTPS endpoint/query filter/
queried_by，以及每条 P0/P1 的 `id`、`priority`、`state`、`created_at`、`closed_at`。

观察窗口结束并把不含密钥的 Prometheus 快照存入仓库后，先 dry-run，再写入 evidence：

```bash
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json>
python scripts/build_web_to_tui_production_telemetry.py \
  --snapshot <repo-relative-production-snapshot.json> --write-evidence
```

逐 route rollback 证据必须由矩阵中的真实 commit 生成，不得手工复制占位值：

```bash
# owner/wave commit 写入矩阵后执行；本轮已实际运行
python scripts/build_web_to_tui_rollback_catalog.py --write-evidence
python scripts/build_web_to_tui_rollback_catalog.py
```

该工具要求 40 位 commit 在本仓库存在且是当前 `HEAD` 的祖先，并要求 evidence 中的
108 条映射与矩阵完全一致。本轮真实运行返回
`Web-to-TUI rollback catalog: PASS - routes=108 commits=3`；89 个 A 类模板、17 个 B 类
模板及 2 个由后端重定向/运行时实现承接的 route 均绑定到对应迁移提交，没有生成或写入
任何伪造提交。

只有总门禁命令 `python scripts/check_web_to_tui_cutover_readiness.py --require-allow`
成功退出，才允许进入 Classic 清理。

## 到期前允许与禁止的动作

允许：在获得明确发布授权后选定并部署候选稳定版本，再按上述启动器绑定观察窗口；采集按任务
区分的 Classic/TUI 访问量与错误率、登记 P0/P1 缺陷、在预生产复核 graph/runtime 与
route/template 回滚、为 Classic 入口占比低频任务准备 owner/reviewer 双签例外。该例外不能豁免
Classic/TUI 两侧各 20 个 task request 的错误率样本要求。

禁止：删除兼容模板、view、route、菜单或共享 partial；把矩阵
`observability_evidence` 改为完成；移除 Classic 出口；归档本计划；将 M5 或总完成
定义标记为完成。

## 下次评审输入

候选部署并完成机器计算的 14 日窗口后重新评审时，必须提供稳定版本标识、完整 commit 与时间窗、逐任务 UAT
报告、覆盖权限/空态/错误态/旧 URL/回滚的 108/108 route 清理证据、带查询条件/时间/SHA-256 的 P0/P1 缺陷快照、带 production 采集证明的旧入口占比和
Classic/TUI 错误率对照、可校验且已 dry-run 恢复的生产 registry 备份、回滚演练记录，
以及绑定同一版本/commit/矩阵 SHA 的 owner 与独立 reviewer 审批和所有低频例外双签。
任一项缺失，M5 继续保持 DENY。
