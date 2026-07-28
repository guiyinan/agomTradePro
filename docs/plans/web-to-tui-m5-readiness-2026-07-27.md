# Web → TUI M5 Readiness 判定（2026-07-27）

## 当前结论

**M5 清理判定：DENY。**

M0–M4 的仓库实现已完成，迁移矩阵中的 17 个 B 类 route template 已全部迁入
TUI，B 类 backlog 为 0；但这不等于获得 Classic 删除授权。2026-07-26 是预定观察
基线，当前机器证据尚未绑定候选稳定版本及其起止时间，因此稳定窗口不能视为已经有效
计时。即使后续证据确认从该日计时，最早也只能在 2026-08-09 重新评审；候选版本变更
或 P0/P1 修复触发重置时继续顺延。

## 退出门槛快照

| 门槛 | 当前证据 | 判定 |
|---|---|---|
| 至少 1 个稳定版本且不少于 14 个自然日 | 预定观察基线 2026-07-26；`stable_version`、`candidate_commit`、`released_at`、`observation_end` 尚未绑定 | 未通过 |
| 计划内角色与主路径 UAT 100% | 108/108 矩阵深链 smoke 通过；71 个无需 fixture 的直读 route、9 个参数化读取 route、策略/个人 AI 服务商生命周期、Policy 创建、治理/筛选、本地详情/生命周期及 2 个受控外部 AI 流程已真实执行，去重后机器 gate 登记 108/108 | 通过 |
| 逐 route 清理条件 100% | 六类 scope 均为 108/108；回滚映射由 3 个真实迁移提交生成，并通过当前分支 ancestry 与 evidence 一致性校验 | 通过（108/108） |
| P0/P1 阻断缺陷为 0 | 尚无覆盖完整兼容窗口的缺陷报表 | 未通过 |
| 旧入口占比 ≤ 5% 或低频例外双签 | 已实现矩阵驱动的有界 Classic/TUI 同任务指标与 14 日 PromQL；尚无生产样本 | 未通过 |
| TUI 错误率不高于基线 0.5 个百分点 | 已把 Classic 同源 API execution 通过受审 Referer 归入固定 task，并实现 task request 对照和最小样本告警；101 个 comparable task 当前无生产窗口数据 | 未通过 |
| wave 级 graph/runtime 与 route/template 回滚演练 | 本地隔离 reverse/restore 与 registry publish/rollback/restore 已通过，见回滚演练证据 | 通过（本地） |
| 生产 registry 可校验备份 | 仓库外备份/恢复工具与集成测试已完成，但尚无绑定候选版本、commit、矩阵 SHA、外部 locator、完整性摘要和恢复验证的生产证据 | 未通过 |
| owner 与独立 reviewer 切换审批 | 尚无绑定候选版本、commit、矩阵 SHA 和经摘要校验评审快照的双签 | 未通过 |

## 当前已通过的实现门禁

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
  窗口和 101 个 catalog task 完全一致。六条 PromQL、整数计数、5% Classic 占比、两侧各
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
  fail-closed 单测 `19 passed`；同时覆盖逐 route 清理 scope/回滚映射、备份保留期与
  观察窗口结束后审批时序。
- Classic cleanup guard 已接入 consistency CI：固定识别 7 个 M0-D 审计基线；任何新增
  `deleted` 行必须保留 A/B lifecycle、进入 M5-B wave，并由完整 readiness checker 返回
  ALLOW，否则 CI 直接失败。
- A/B route 即使在 M5-B 标为 `deleted`，仍保留在 108-route UAT/清理范围和 telemetry
  catalog 中；对应回归证明删除状态不能缩小证据分母或绕过历史任务监测。
- 逐 route 兼容面首批证据 `2 passed`：展开 108 route 的 118 个 URL pattern，验证匿名认证
  边界、模板继承/include 后的审核 TUI 目标和 Terminal 精确重定向；修复 5 个匿名 200、
  2 个认证前对象查询及 7 个手写提示漂移。当前只关闭 `legacy_url`，不冒充完整权限/状态证据。
- Registry 备份/恢复命令已落地：备份只能写到仓库外并原子生成 JSON + SHA-256 sidecar；
  恢复默认 dry-run，显式批准时还要求匹配当前 active source hash，并记录 rollback ancestry。
  这只证明工具可用，不代表已经取得生产 registry 备份。
- Published metadata 收口为 12 screens / 399 actions；删除 8 个无 screen/panel/矩阵消费者且
  缺少必填参数的旧 auto action。全新迁移 SQLite + staff 用户 + 同库 localhost 下，read/AI
  action smoke 为 `380 total / 238 ok / 142 needs_input / 0 error`；Regime、Pulse 首装空态返回
  200，AI Provider 未配置返回受控 503，不再依赖历史开发数据冒充通过。

## 机器判定快照

```text
Web-to-TUI M5 cutover: DENY (as of 2026-07-28)
PASS source_consistency
FAIL stable_version_window: commit=missing_or_unresolvable
PASS route_task_uat: covered=108/108; evidence=true
PASS route_cleanup_readiness: covered=108/108; scope_counts=empty_state:108,error_state:108,legacy_url:108,permission:108,primary_task:108,rollback:108; scopes=true; rollback=true; lifecycle=true; evidence=true
FAIL blocking_defects: evidence=false
FAIL production_telemetry: covered=0/101; production_evidence=false
PASS rollback_drill
FAIL production_registry_backup: evidence=false; integrity=false; restore_verified=false
FAIL cutover_approvals
```

日常一致性检查：

```bash
python scripts/check_web_to_tui_cutover_readiness.py
```

候选版本部署并形成干净提交后，先执行 dry-run，再显式开始观察：

```bash
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD>
python scripts/start_web_to_tui_observation.py \
  --stable-version <version> --candidate-commit <full-commit> \
  --released-at <YYYY-MM-DD> --write
```

当前工作树仍包含未提交迁移成果，候选 commit 也尚未部署；该命令必须 fail closed，不能用
当前 `HEAD` 或工作树内容冒充稳定候选。

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

允许：按上述启动器绑定并部署候选稳定版本、采集按任务区分的 Classic/TUI 访问量与错误率、执行
其余空态/错误态和旧 URL 行为、登记 P0/P1 缺陷、在预生产复核 graph/runtime 与 route/template
回滚、为 Classic 入口占比低频任务准备 owner/reviewer 双签例外。该例外不能豁免
Classic/TUI 两侧各 20 个 task request 的错误率样本要求。

禁止：删除兼容模板、view、route、菜单或共享 partial；把矩阵
`observability_evidence` 改为完成；移除 Classic 出口；归档本计划；将 M5 或总完成
定义标记为完成。

## 下次评审输入

2026-08-09 或之后重新评审时，必须提供稳定版本标识、完整 commit 与时间窗、逐任务 UAT
报告、覆盖权限/空态/错误态/旧 URL/回滚的 108/108 route 清理证据、带查询条件/时间/SHA-256 的 P0/P1 缺陷快照、带 production 采集证明的旧入口占比和
Classic/TUI 错误率对照、可校验且已 dry-run 恢复的生产 registry 备份、回滚演练记录，
以及绑定同一版本/commit/矩阵 SHA 的 owner 与独立 reviewer 审批和所有低频例外双签。
任一项缺失，M5 继续保持 DENY。
