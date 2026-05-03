# Changelog

All notable changes to AgomTradePro will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 新增 Dashboard Alpha candidate 到 `/equity/screen/` 的自动化回归覆盖：API 契约测试锁 `ROE / PE / PB / 营收增长 / 净利润增长` 字段，Playwright smoke 锁结果表最终渲染
- 新增 Alpha exit loop 后端主链，串起 `decision_rhythm` 退出建议、`signal` 查询、自动交易执行与任务投递，并补齐 `tests/unit/test_alpha_exit_loop_end_to_end.py` 等一组端到端回归
- Dashboard 新增 Alpha exit 细节面板、history/detail 页面与 metrics/stock API 入口，首页主工作流和 Decision Workspace 侧边栏现在都能复用同一套退出链上下文
- 新增 `scripts/select_quality_targets.py`、`.github/workflows/ci-fast-feedback.yml`、`.pre-commit-config.yaml` 与对应测试，用统一质量目标选择器驱动更快的 CI 反馈
- 新增一组 2026-05-01 / 2026-05-02 架构整改文档，覆盖 shared cleanup、Application write guard、account portfolio API、share application 与模块循环依赖回归说明
- 新增公共异步任务跟踪 helper `apps/task_monitor/application/tracking.py`，统一在 Celery worker pickup 前写入 `pending` 任务记录
- 新增聚焦回归脚本 `scripts/run_alpha_ops_regression.py`，覆盖 Alpha ops、Dashboard Alpha refresh、Policy RSS 和 Data Center decision reliability repair 的异步任务可见性
- 新增全仓治理检查脚本 `scripts/check_governance_consistency.py`，覆盖 MCP 工具数、关键文档计数、`docs/INDEX.md` 死链、模块 11 项形态、错位 `AppConfig`、单数 `dto.py` 与 Application 层 pandas/numpy 导入
- 新增 `governance/governance_baseline.json`，用 baseline 记录当前已知历史债务与模块形态分数，防止后续新增或倒退
- 新增 `docs/governance/ARCHITECTURE_GUARDRAILS.md`，说明增量架构门禁、全仓治理检查和历史债务 baseline 的关系
- 新增 guardrail 测试 `tests/guardrails/test_governance_consistency.py`，确保治理一致性脚本在 CI 中持续可运行
- 新增架构债治理公开摘要：README / README_EN 现在同步记录 2026-04-24 的架构边界收口、合同回归修复和 CI / Nightly 绿色状态
- Dashboard / SDK / MCP 的账户驱动 Alpha 候选读取现统一暴露 `pool_mode`（`strict_valuation` / `market` / `price_covered`）以及共享 `contract` 字段，明确区分可行动推荐、异步刷新中与兜底结果
- README 新增可日更维护的 `What's New` 区域，便于对外同步最近 1-7 天的重要变化
- Dashboard 增加可选浏览器级 Pulse 转向提醒（本地 Notification 开关）
- Regime 页面增加历史 `Regime + Pulse + Action` 三层叠加时序图
- 金融数据源运行时补入 QMT 行情接入，并提供统一 registry / factory 配置路径
- 新增本地回归入口与浏览器级 UAT harness，补充 Playwright 页面巡检脚本
- 新增架构门禁回归测试，锁定 2026-03-29 `Architecture Layer Guard` 命中的历史越层导入点
- Dashboard Alpha 卡片、`/api/alpha/scores/`、`/api/dashboard/alpha/stocks/` 和 MCP `get_alpha_stock_scores` 增加统一的 `reliability_notice` / 缓存使用提示元数据
- 新增正式库快照回归方案，可用 `db.sqlite3` 快照启动隔离实例并执行 Playwright 验收，不污染 live 数据
- 新增 Dashboard Alpha 用户隔离回归测试与 Qlib 退化路径回归测试
- Equity Detail 新增技术图表能力，补齐日线 / 分时数据读取、技术指标服务与前端图表呈现
- 宏观数据源中心新增运行时连接测试能力，可直接在页面对 Tushare / AKShare / QMT 等配置执行探针并查看日志
- 开发环境新增 `runserver` 文件日志持久化路径与对应测试覆盖，便于本地排查启动问题
- RSS 源配置页面新增 RSSHub、proxy、timeout、retry 等可视配置项
- 统一数据源中心补入跨系统 provider inventory 展示，集中展示 public / licensed / local-terminal / pending-config provider
- Dashboard Alpha 首页新增账户驱动候选运行快照与历史回溯模型，可按组合、日期、股票、阶段、来源查询每次候选评估记录与逐票理由
- Dashboard 新增 Alpha 推荐历史页与历史 JSON 接口，支持查看 run 详情、逐票买入理由、不买理由、证伪条件与建议仓位
- 新增 `shared/infrastructure/asset_analysis_registry.py`，将 `equity`、`fund`、`rotation` 与 `asset_analysis` 之间的只读协作 contract 收口到共享技术注册表

### Changed
- `/equity/screen/` 结果表现在会为首页带入的 Dashboard Alpha 候选补齐最新 `ROE / PE / PB / 营收增长 / 净利润增长` 上下文，不再只显示综合评分
- Dashboard 退出链入口已统一：首页主工作流、Decision Workspace、Alpha history/detail 以及相关 API 现在经 `query_services` / `interface_services` / integration gateway 收口，不再依赖超大混合视图
- 运行时桥接与 provider 装配继续收口到 app-owned provider 与 `core/integration/*`，`shared/` 清理和跨模块 `infrastructure` 边界治理继续推进
- CI 质量门禁升级：`rc-gate`、`Architecture Layer Guard`、fast-feedback workflow 与工程护栏文档现统一使用质量目标选择逻辑，开发机也同步引入 pre-commit 基线
- 生产环境静态资源处理已加固，并清理一批冗余 vendored 前端静态包，减少部署时的历史包袱与告警噪音
- `main` 已拉齐到最新通过 CI 的 `dev/next-development`，公开主线现在包含 2026-04-29 宏观量纲治理与 2026-04-30 异步任务可见性修复
- Nightly、`scripts/run_full_regression.py` 与 README 中的默认 integration 口径现统一排除 `live_required`、`optional_runtime` 与 `diagnostic` 套件；需要 live server、可选运行时或脚本式诊断的测试改为显式单独执行
- GitHub Actions `Consistency Check` 现会运行全仓治理一致性检查，并上传 `reports/consistency/governance-consistency.json`
- 架构审计规则版本更新为 `2026-04-24.v1`，新增 Application 层 pandas/numpy 导入审计和错位 `AppConfig` 审计规则
- `pulse`、`realtime`、`alpha`、`sentiment`、`strategy` 的四层规范文件形态已补齐到当前治理基线；`strategy/application/dto.py` 已统一为 `dtos.py`
- MCP 工具数文档口径已同步到当前 `318` 个本地注册快照，系统模块覆盖口径同步为 `35/35`
- 本轮架构债治理将多个 Interface / Application 热路径收口到 application interface service、repository provider 与 infrastructure repository 边界，减少直接 ORM / Infrastructure 耦合
- `main` 与 `dev/next-development` 已对齐到同一提交，最新 push CI 与 Nightly 主链重新保持绿色
- Pulse 按需重算现在会在重建前刷新上游宏观输入，减少 stale / degraded 快照反复重算后继续输出低质量上下文的情况
- Alpha Qlib / cache 访问重新回收到 repository 边界内，应用层不再直接碰缓存模型，Architecture Layer Guard 与 Nightly 主链重新对齐
- Dashboard、Decision Workspace、SDK 与 MCP 现在使用一致的账户池语义和 Alpha 推荐契约，首页研究排序、待执行队列和真实 scoped 推荐的边界更清晰
- Dashboard 与顶部导航完成 redesign 收口，`beta_gate` / `alpha_trigger` / `decision_rhythm` 不再作为首页独立主入口暴露
- Dashboard 首页决策入口统一到新的 `decision/workspace` 6-step workflow，不再混用旧的 5-step 主流程表述
- SDK / MCP / 文档口径统一到当前 canonical 契约，补充 `client.pulse.*` 与 `decision_workflow_get_funnel_context(trade_id, backtest_id)` 使用说明
- 文档索引同步为当前事实：Regime Navigator + Pulse redesign Phase 1-3 已完成
- 预上线阶段将真实仓持仓主链直接切到统一账本：`/api/account/positions/*` 成为唯一 canonical 实仓持仓入口，移除单独的 `/api/account/unified-positions/`
- GitHub Actions 的日常门禁 workflow 现在对 `dev/**` 分支的 push / pull request 也会自动触发，不再只覆盖 `main`
- `strategy` 绑定链路改经 facade 收口，减少页面层直接耦合
- `decision/workspace` 推荐与执行主线进一步收口：第 5 步以账户级推荐刷新为主，第 6 步固定为执行入口，不再回退成审计主流程
- 文档与 README 对外口径同步到 35 个业务模块、个人投研平台
- 默认 pytest 收集范围从仅 `tests/` 扩展到 `tests/` + `apps/*/tests`
- `tests/uat/run_uat.py` 改为基于真实 JUnit XML 统计 Journey / API / Navigation 结果
- Playwright 运行时 `--base-url` 现在会同步覆盖全局测试配置，避免误打默认 `localhost:8000`
- 正式库中的 Qlib 路径配置已显式写回数据库，不再只依赖运行时代码 fallback
- 系统设置中心、管理员控制台、MCP Tools、服务日志、文档管理等后台页面已统一到共享管理界面风格
- `market_data` 的 provider 页面能力已回收至统一数据源中心，配置中心与 Provider 状态页口径保持一致
- Equity Detail 页面上下文继续补强，技术面、数据源与市场状态信息的组合展示更完整
- RSS 管理流不再依赖硬编码的旧 RSSHub 公网地址，初始化源与前端表单口径已统一到当前可用配置
- 统一账户 API / SDK / MCP 路径已在 2026-04-01 这轮收口中对齐到 canonical 契约
- 管理侧和配置侧文档已同步到当前事实：统一设置中心、统一数据源中心和最新页面入口结构
- Dashboard 首页 Alpha 不再固定查询 `csi300`，改为按当前激活组合解析账户驱动池，并允许随组合切换刷新候选
- Dashboard Alpha 首页文案与布局已改为三层视图：`Alpha Top 候选/排名`、`可行动候选`、`待执行队列`，不再把研究排序直接表述为“推荐股票”
- Alpha provider / cache / simple / Qlib 链路统一接收 `AlphaPoolScope`，缓存键扩展为 `scope_hash + trade_date + model`，避免不同账户池子共用同一份指数缓存
- `strategy` 与 `asset_analysis` 的跨 App 协作链进一步收口：资产池读取、名称解析与筛选组装统一改经 application facade、repository provider 与 shared registry，不再依赖 bridge 文件和跨 App ORM 直连

### Deprecated
- (TBD)

### Removed
- 已移除旧的 `core/integration/asset_analysis_market_sources.py` bridge，跨模块市场协作改由 app-owned provider + shared registry 暴露

### Fixed
- 修复运行时 bridge 与测试安全 provider 漂移，`runtime_settings` / `runtime_benchmarks` / `signal` 相关读链在测试环境和降级场景下重新恢复稳定
- 修复 workspace account id 非数字时的兼容性问题，Decision Workspace 相关读取不再因 ID 解析失败而中断
- 修复 Decision / Simulated Trading 之间的模块循环依赖，退出建议与持仓读取链现在通过 integration bridge 解耦
- 修复 GitHub Actions 中残留的 Node 20 shim warnings，CI 输出噪音已收敛
- 修复 Alpha ops、Dashboard Alpha refresh、Policy RSS 抓取和 Data Center decision reliability repair 这些关键异步入口在返回 `task_id` 后、worker `prerun` 前无法立即在 `task_monitor` 中看到 `pending` 记录的问题
- 修复 Alpha `provider_filter` 单点探测失败被误写成全局 `provider_unavailable` 告警的问题，运维页不再出现 `尝试顺序: simple` 这类误导性全局故障提示
- 修复 `docs/INDEX.md` 中 Regime Navigator 计划文档、Qlib 本地上传方案和 Alpha 快速开始等链接漂移
- 清理多个非 app-root 包中的错位 `AppConfig` 定义，避免 layer package 被误当作 Django app 配置入口
- `simulated_trading/application/performance_calculator.py` 去除 Application 层 pandas/numpy 依赖，改用标准库统计与纯 Python 回撤计算
- 修复 Alpha cache upload、Decision readiness、Policy notification task、Data Center integration provider 与 Share snapshot Decimal JSON guardrail 的合同漂移，恢复本轮 main / dev 对齐前的完整回归链路
- 修复 `/api/pulse/current/`、SDK `client.pulse.get_current()` 与 MCP `get_pulse_current()` 在 stale 快照触发刷新时，可能因当前 Regime 解析为 `Unknown` 而覆盖掉最近有效 Pulse 快照的问题
- 修复 Alpha Qlib 推理与 scoped cache 读取链的边界漂移；Dashboard、Decision、Simulated Trading 和 MCP 读取账户驱动候选时，缓存/回退路径已重新稳定
- 修复 Dashboard 首页 Alpha 榜单把 Qlib 多级索引 `(Timestamp, code)` 直接序列化进缓存导致股票名解析失败、详情链接 404、因子面板拿不到正确代码的问题；Alpha 缓存现统一写入/读取 canonical 股票代码，并补齐 `asof_date`
- 调整 Dashboard Alpha 首页为 `qlib -> cache -> simple -> etf` 的实时优先链路，并在使用缓存时显式展示缓存评分日、缓存写入时间和回退原因
- 新增 Dashboard 手动“实时刷新”入口，可显式触发当天 Qlib 刷新任务；同时对 Qlib 异步推理投递增加短时节流，避免首页重复刷新时连续堆积相同任务
- 修复 `tests/unit/test_ai_failover_helper.py` 与 AI provider 仓储新接口脱节的问题；`create_ai_policy_classifier()` 现在会防御性跳过空 API key，Nightly 的 failover 回归重新对齐当前 provider 过滤语义
- 修复 `Logic Guardrails` 直接复用全量 changed-module 测试清单导致超时的问题；工作流现改为使用轻量 `logic_guardrails` 测试选择 profile，排除 integration/e2e/stress 路径并增加合理超时余量
- 修复 Dashboard 首页将待分类政策 `PX` 直接传入策略配置矩阵导致告警与建议失败的问题；当前政策环境改为读取已生效档位，待分类事件不再污染首页配置建议
- 修复 Dashboard Alpha 榜单默认路径会优先触发 Qlib 健康检查与冷启动的问题；首页现改为优先走 cache/simple/etf 快速路径，避免登录后首屏长时间阻塞
- 修复 Celery Worker 未自动注册 `apps.regime.application.orchestration.*`、`apps.equity.application.tasks_valuation_sync.*` 以及若干 legacy dotted task 名称的问题；旧 beat 配置不再触发 `Received unregistered task`
- 修复 AI provider 在当前环境不可解密时仍会被运行时优先命中的问题；统一 AI 路由、Dashboard 和情感分析现在会自动跳过无可用凭据的 provider
- 修复 Pulse 默认指标配置与当前开发库宏观数据不一致导致的稳定性告警；默认映射已切到现有可用指标，`init_pulse_config --force` 也会停用旧指标码
- 清理 `docker-compose.yml` 与 `docker-compose-dev.yml` 顶层过时 `version` 字段，消除 Docker Compose v2 启动警告
- 修复 Alpha cache provider 在“当天精确缓存更旧”时仍压住更近历史缓存的问题；Dashboard 读取缓存时现会优先选择较新的 `asof_date`
- 修复 Dashboard Alpha 首页固定绑定 `csi300` 导致账户语义失真的问题；当前池子改为依据组合市场与可交易股票全集解析
- 修复 Dashboard Alpha 候选只显示分数、无法解释“为什么买/为什么不买/何时失效”的问题；首页现补齐结构化理由、证伪条件、风控闸门与建议仓位
- 修复 Dashboard Alpha 候选页只展示当前结果、无法回看历史判断依据的问题；每次首页评估现在都会持久化 run + snapshot 供后续检索
- 修复 `/dashboard/` 在月度快照 `total_value=0` 时触发 `ZeroDivisionError` 的问题，并补充回归测试
- 修复 `/admin/account/systemsettingsmodel/` 单例入口错误调用 `ModelAdmin.change_view()` 导致 `TypeError` 的问题，并补充回归测试
- 调整本地 Playwright UAT 巡检脚本：`Equity` 改为命中 canonical 页面，且 Django debug 500 页不再被误判为通过
- 修复 `tests/uat/run_uat.py` 导航检查的假失败：临时登录用户改为唯一用户名，`/policy/workbench/` 基线状态改为当前真实返回 `200`
- 修复 Pulse 数据链条会把过期/不可靠快照继续喂给仓位系数、决策失效模板和 Regime Action 的问题；相关读取链路现在会先校验可靠性，并在需要时按需重算
- 修复开发环境 Celery Beat 未固定使用 `DatabaseScheduler` 导致的调度源漂移；本地宏观/Regime 周期任务现在会在启动时统一回写到 `django-celery-beat`
- 修复宏观高频数据链仍指向已迁移 `apps.macro.application.tasks.*` 任务路径的问题；`high-frequency-generate-signal` 与 `high-frequency-recalculate-regime` 现已对齐到 `apps.regime.application.orchestration.*`
- 修复 `signal.daily_summary` 摘要查询读取不存在的 `created_by` 字段导致的 Celery 任务失败；摘要链现改为读取真实 ORM 字段 `user_id` 并补充回归测试
- 修复 `realtime-price-polling` 周期任务指向不存在 Celery task 的问题；新增 `apps.realtime.application.tasks` 包装任务，避免 Beat 派发后被 Worker 丢弃
- 修复 Celery 自动发现未覆盖 `apps/*/application/tasks.py` 的问题；`realtime-price-polling` 等 application-layer 任务现在会被 Worker 正常注册
- 修复 `apps.task_monitor.application.tasks` 中错误使用内建 `any` 类型注解导致的模块导入失败，避免新的 Celery 自动发现链被中途打断
- 修复 `Architecture Layer Guard` 在 `push` 事件遇到 force-push / rewritten history 时直接对不可达 `before SHA` 做 `git diff` 的误报问题；现在会自动回退到 `HEAD^..HEAD`
- 修复 Pulse 快照按 `observed_at` 重算时的重复落库问题；同一观测日现在只保留一条快照，并新增数据库唯一约束避免再次出现非确定性读取
- 修复 `sync_macro_then_refresh_regime` 链路只计算不落库的问题，Regime 定时同步后现在会持久化最新快照，避免健康检查继续读取旧的 `regime_log`
- 修复实时价格轮询写回模拟仓时错误使用 `current_value` / `cash` / `initial_cash` 等不存在字段，收盘后批量价格更新任务恢复成功
- AKShare 批量价格获取不再对缺失标的重复触发远端 spot loader，连接中断时的日志噪音和重复回退已收敛
- AI RSS 分类在数据库存在 provider 但健康检查失败时会自动禁用分类器，并输出明确根因，不再逐条刷出 `All providers failed. Last error: None`
- 未配置邮件收件人时，SLA 告警现在会跳过邮件通道并保留站内通知，不再重复写入 `No recipients for email`
- `/favicon.ico` 现在返回 204，消除开发环境浏览器自动请求造成的 404 告警
- Regime Navigator redesign 相关文档仍标记“待实施”的事实漂移
- SDK/MCP 集成测试计划中的认证描述，改回真实的 `Authorization: Token <token>` 口径
- GitHub `Consistency Check` 新增的 4 处文档路由漂移，已改为当前可解析的 canonical 路径表述
- `apps/signal/domain/invalidation.py` 改为 timezone-aware UTC 时间戳，消除 `datetime.utcnow()` 弃用警告
- 真实仓持仓的修改 / 保存 / 平仓链条统一走 `UnifiedPositionService`，派生字段重算、平仓写交易账本、旧账本 bootstrap 和 API 路径口径已一并收口
- `decision/workspace` Step 5 的 HTMX/Alpine 片段替换后函数未绑定问题，导致的 `loadTransitionPlanStep` / `generateTransitionPlan` / `submitTransitionPlanForApproval` 报错已修复
- `decision/workspace` 推荐空白时现在会触发真实刷新，并保留 `HOLD` / `BETA_GATE_BLOCKED` 等阻断原因而不是静默消失
- Pulse bootstrap、历史兼容路由、估值任务导入和若干 decimal / CI guardrail 回归已修复
- Playwright UAT 选择器已对齐当前页面结构，`Regime` 控件检查与 `Decision Workspace` 步骤检测恢复稳定
- 清理 `account` / `macro` / `simulated_trading` 热路径里的直接基础设施导入，修复历史 `Architecture Layer Guard` 失败根因
- Alpha 推荐链路现在会正确透传当前登录用户，避免 `/api/alpha/scores/` 有数据但 Dashboard 读不到用户级缓存
- 当本地 Qlib 数据停在旧交易日时，系统会显式返回 `degraded` 并前推最近一次可用缓存，而不是伪装成新鲜结果或抛出模糊运行时错误
- 命中前推 Qlib 缓存时，`staleness_days` 不再被错误写成 `0`
- AI provider 解密失败时现在会回退到规则建议，不再把无效 token 继续传给下游
- UAT 路由基线、导航断言和前端 API 契约检查已对齐当前真实系统路径与页面结构
- Feedparser RSS 抓取不再直接走无超时控制的 `feedparser.parse(url)`，RSS 源超时悬挂问题已修复
- 开发环境账号协作表单、个股页 fetch fallback 与若干安全扫描/Playwright 数据库清理回归已修复
- Qlib 运行时不可用时，Alpha 现在会自动复用最近有效缓存而不是直接失去结果
- `macro` 数据源配置相关 interface 越层导入已移回 application 边界，修复 2026-04-05 CI 中的架构门禁失败
- 统一数据源中心发布后的 `Architecture Layer Guard` / `Logic Guardrails` 已在后续修复提交中恢复为绿色
- 修复 `tests/unit` 下重复文件名在全量收集时触发 `import file mismatch` 的问题；相关测试目录现已补齐包入口，Nightly 全量 pytest 收集重新稳定
- 修复 Strategy 执行在 investable pool 尚未预热时的兼容性问题，现会回退读取 `asset_analysis` 最新评分缓存而不是直接中断主链
- 修复 Decision Workspace AI 证伪草稿接口使用旧 `generate_chat_completion()` 参数签名的问题，Nightly 主链已恢复绿色
- 一批 Domain / Application 的静默降级分支现已补齐显式日志，fallback 仍保留，但运行时故障不再被无痕吞掉

### Security
- (TBD)

---

## [0.7.0] - 2026-03-23

### Added
- **Setup Wizard Module** (`setup_wizard`): 系统初始化向导，首次安装引导
  - 网页版安装向导，引导配置管理员密码、AI API、数据源
  - 密码强度实时检查
  - 已初始化系统需密码验证才能修改配置
- **AI Capability Module** (`ai_capability`): 系统级 AI 能力目录与统一路由
  - 支持四种能力来源：builtin/terminal_command/mcp_tool/api
  - 统一路由 API
  - 自动采集全站 API 并进行安全分层
- **Terminal Module** (`terminal`): 终端 CLI，终端风格 AI 交互界面
  - 支持可配置命令系统（Prompt/API 两种执行类型）
- **Agent Runtime Module** (`agent_runtime`): Agent 运行时，Terminal AI 后端
  - 任务编排和 Facade 模式

### Changed
- **模块总数**: 从 30 个增加到 35 个业务模块
- **项目状态**: 核心功能已完成 (99%)

---

## [0.6.0] - 2026-03-19

### Added
- **AI Capability Module** (`ai_capability`): 系统级 AI 能力目录与统一路由
  - 支持四种能力来源：builtin/terminal_command/mcp_tool/api
  - 统一路由 API
  - 自动采集全站 API 并进行安全分层

---

## [0.5.0] - 2026-03-17

### Added
- **Terminal Module** (`terminal`): 终端 CLI，终端风格 AI 交互界面
  - 支持可配置命令系统（Prompt/API 两种执行类型）
- **Agent Runtime Module** (`agent_runtime`): Agent 运行时，Terminal AI 后端
  - 任务编排和 Facade 模式

---

## [0.4.0] - 2026-03-04

### Added
- **API Route Migration**: Unified API route format `/api/{module}/{resource}/`
- **Migration Documentation**: Complete route migration guide and quick reference
- **Deprecation Headers**: Old routes now return deprecation warning headers
- **Migration Guide**: See [docs/migration/route-migration-guide.md](docs/migration/route-migration-guide.md)

### Changed
- **API Routes**: All API endpoints now use unified routing format
  - Old: `/{module}/api/{resource}/` or `/api/{module}/api/{resource}/`
  - New: `/api/{module}/{resource}/`
- **SDK Compatibility**: SDK v1.2.0+ automatically uses new routes

### Deprecated
- **Legacy API Routes**: Old route patterns deprecated, will be removed 2026-06-01

---

## [0.3.0] - 2026-02-26

### Added
- **Module**: `task_monitor` - Scheduled task monitoring
- **Testing**: Full regression test suite with CI gates (1,600+ test cases)
- **Documentation**: Complete module documentation structure

### Changed
- **Architecture**: Removed `apps/shared/`, moved to `shared/infrastructure/htmx/`
- **Dependencies**: Fixed architecture violations from `shared/` to `apps/`
- **Exceptions**: Unified exception handling via `core/exceptions.py`

### Fixed
- Sentiment module route configuration
- AI provider application layer
- 31 new unit tests added

---

## [0.2.0] - 2026-02-18

### Added
- **Factor Module**: Factor calculation, IC/ICIR evaluation
- **Rotation Module**: Sector rotation based on Regime
- **Hedge Module**: Futures hedge calculation and management
- **Alpha Module**: Deep integration with Qlib (Phase 1-5 complete)
  - Phase 1: Alpha 抽象层 + Cache Provider
  - Phase 2: Qlib 推理异步产出
  - Phase 3: 训练流水线
  - Phase 4: 评估闭环 + 监控
  - Phase 5: 宏观集成 + 全链路联调

---

## [0.1.0] - 2026-01-15

### Added
- **Audit Module**: Post-trade audit with Brinson attribution + 完整测试覆盖
- **Dashboard**: Streamlit integration for visualization
- **Beta Gate Module**: Market condition filtering
- **Decision Rhythm**: Decision frequency constraints
- **Alpha Trigger**: Discrete alpha signal triggering
- **Architecture**: Complete four-layer architecture (Domain/Application/Infrastructure/Interface)

### Changed
- **Architecture**: Complete four-layer architecture enforcement

---

## Version History Summary

| Version | Date | Key Changes |
|---------|------|-------------|
| 0.7.0 | 2026-03-23 | Setup Wizard, AI Capability, Terminal, Agent Runtime |
| 0.6.0 | 2026-03-19 | AI Capability Module |
| 0.5.0 | 2026-03-17 | Terminal CLI, Agent Runtime |
| 0.4.0 | 2026-03-04 | API route migration |
| 0.3.0 | 2026-02-26 | Task Monitor, architecture fixes, 1,600+ tests |
| 0.2.0 | 2026-02-18 | Factor, Rotation, Hedge, Qlib integration |
| 0.1.0 | 2026-01-15 | Audit, Dashboard, Beta Gate, four-layer architecture |

---

**Maintained by**: AgomTradePro Team
**Last Updated**: 2026-04-30
