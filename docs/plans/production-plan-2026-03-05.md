│ AgomSAAF 生产可用性完善计划                                                                    │
│                                                                                                │
│ Context                                                                                        │
│                                                                                                │
│ AgomSAAF V3.4 已完成 98% 的功能开发，28 个业务模块全部具备完整的四层架构，无 501               │
│ 占位接口。但要在生产环境中真正使用（接入真实数据、服务真实用户），仍存在以下关键缺口：         │
│                                                                                                │
│ 1. 生产基础设施缺失 — 无数据库连接池、无错误追踪、无依赖锁文件                                 │
│ 2. 测试覆盖不足 — 8 个模块的 Domain 层缺少 services 测试（含高风险金融计算模块）               │
│ 3. 运维工具缺失 — 无统一初始化命令、Celery 任务配置不一致、无运维手册                          │
│ 4. 端到端验证不足 — 数据管道集成测试、性能基线测试缺失                                         │
│                                                                                                │
│ ---                                                                                            │
│ M0: 生产安全网 (第 1 周)                                                                       │
│                                                                                                │
│ 目标：确保系统在生产环境不会静默失败                                                           │
│                                                                                                │
│ M0.1 数据库连接池配置                                                                          │
│                                                                                                │
│ 问题：core/settings/production.py:70-72 的 DATABASES 未配置                                    │
│ CONN_MAX_AGE，每个请求都会重新建连，高并发下将耗尽 PostgreSQL 连接。                           │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - core/settings/production.py — DATABASES 添加连接池参数：                                     │
│ DATABASES = {                                                                                  │
│     'default': {                                                                               │
│         **env.db('DATABASE_URL', default='sqlite:///db.sqlite3'),                              │
│         'CONN_MAX_AGE': env.int('DB_CONN_MAX_AGE', default=600),                               │
│         'CONN_HEALTH_CHECKS': True,  # Django 4.1+ 自动检测断连                                │
│     }                                                                                          │
│ }                                                                                              │
│                                                                                                │
│ M0.2 错误追踪集成 (Sentry)                                                                     │
│                                                                                                │
│ 问题：生产错误仅写入日志文件，无集中式告警。未处理异常无法主动发现。                           │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - requirements-prod.txt — 添加 sentry-sdk[django,celery]>=2.0                                  │
│ - core/settings/production.py — 添加 Sentry 初始化（仅当 SENTRY_DSN 环境变量存在时启用）       │
│ - .env.example — 添加 SENTRY_DSN= 和 SENTRY_TRACES_RATE=0.1 示例                               │
│                                                                                                │
│ M0.3 依赖锁文件                                                                                │
│                                                                                                │
│ 问题：requirements-prod.txt 使用 >=                                                            │
│ 约束，不同时间安装可能得到不同版本，导致"我本地没问题"的生产事故。                             │
│                                                                                                │
│ 操作：                                                                                         │
│ - pyproject.toml — dev dependencies 添加 pip-tools                                             │
│ - 生成 requirements-prod.lock（通过 pip-compile requirements-prod.txt -o                       │
│ requirements-prod.lock）                                                                       │
│ - docker/Dockerfile.prod — 改用 lock 文件安装                                                  │
│                                                                                                │
│ M0.4 健康检查增强                                                                              │
│                                                                                                │
│ 问题：core/health_checks.py 仅检查 DB 和 Redis，缺少 Celery worker                             │
│ 存活检查和关键数据表非空检查。                                                                 │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - core/health_checks.py — 添加 check_celery() 和 check_critical_data() 函数                    │
│                                                                                                │
│ 验收标准：                                                                                     │
│ - 生产配置包含 CONN_MAX_AGE=600                                                                │
│ - 配置 SENTRY_DSN 后 Sentry 可捕获测试异常                                                     │
│ - requirements-prod.lock 存在且 Dockerfile 使用它                                              │
│ - /api/health/ 返回 celery worker 状态                                                         │
│                                                                                                │
│ ---                                                                                            │
│ M1: 金融关键模块测试补全 (第 1-2 周)                                                           │
│                                                                                                │
│ 目标：为 8 个缺少 Domain services 测试的模块补全测试，达到 ≥90% 覆盖                           │
│                                                                                                │
│ 现状分析                                                                                       │
│                                                                                                │
│ 以下 Domain services 已有测试（无需重复）：                                                    │
│ - ✅ regime, backtest, filter, ai_provider, prompt, audit, alpha_trigger, beta_gate,           │
│ decision_rhythm                                                                                │
│                                                                                                │
│ 以下 Domain services 缺少测试（按金融风险排序）：                                              │
│                                                                                                │
│ ┌───────────┬───────────────────────────────────┬──────┬─────────────────────────────────┐     │
│ │   模块    │               文件                │ 行数 │            风险等级             │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ hedge     │ apps/hedge/domain/services.py     │ 682  │ 🔴 对冲计算错误直接导致资金损失 │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ fund      │ apps/fund/domain/services.py      │ 507  │ 🔴 基金评分错误导致错误推荐     │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ factor    │ apps/factor/domain/services.py    │ 521  │ 🟡 因子计算影响 Alpha 信号      │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ rotation  │ apps/rotation/domain/services.py  │ 507  │ 🟡 轮动逻辑影响资产配置         │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ dashboard │ apps/dashboard/domain/services.py │ 586  │ 🟡 聚合逻辑错误误导用户         │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ sector    │ apps/sector/domain/services.py    │ —    │ 🟢 板块分析                     │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ equity    │ apps/equity/domain/services.py    │ —    │ 🟢 个股分析                     │     │
│ ├───────────┼───────────────────────────────────┼──────┼─────────────────────────────────┤     │
│ │ events    │ apps/events/domain/services.py    │ —    │ 🟢 事件总线（已有抽象+实现）    │     │
│ └───────────┴───────────────────────────────────┴──────┴─────────────────────────────────┘     │
│                                                                                                │
│ M1.1 测试工厂基础设施                                                                          │
│                                                                                                │
│ 问题：tests/factories/ 和 tests/fixtures/ 目录为空，每个测试文件独立构造数据，不一致且重复。   │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/factories/__init__.py                                                                  │
│ - tests/factories/domain_factories.py — 纯 Python Domain 实体工厂函数（不依赖 Django ORM）     │
│ - tests/factories/model_factories.py — ORM Model 工厂（用于集成测试）                          │
│                                                                                                │
│ M1.2 高优先级 Domain 测试 (hedge, fund, factor, rotation)                                      │
│                                                                                                │
│ 每个模块创建测试文件，覆盖：                                                                   │
│ - 正常路径计算                                                                                 │
│ - 边界条件（零值、负值、空列表）                                                               │
│ - 金融约束违规                                                                                 │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/unit/domain/test_hedge_services.py                                                     │
│ - tests/unit/domain/test_fund_services.py                                                      │
│ - tests/unit/domain/test_factor_services.py                                                    │
│ - tests/unit/domain/test_rotation_services.py                                                  │
│                                                                                                │
│ M1.3 中优先级 Domain 测试 (dashboard, sector, equity, events)                                  │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/unit/domain/test_dashboard_services.py                                                 │
│ - tests/unit/domain/test_sector_services.py                                                    │
│ - tests/unit/domain/test_equity_services.py                                                    │
│ - tests/unit/domain/test_events_services.py                                                    │
│                                                                                                │
│ 验收标准：                                                                                     │
│ - pytest tests/unit/domain/ --cov=apps/hedge/domain --cov=apps/fund/domain                     │
│ --cov=apps/factor/domain --cov=apps/rotation/domain 各模块 ≥ 90%                               │
│ - 所有 Domain 测试不导入 Django/pandas/numpy（架构合规）                                       │
│ - 新增测试数量 ≥ 150                                                                           │
│                                                                                                │
│ ---                                                                                            │
│ M2: 运维就绪 (第 2-3 周)                                                                       │
│                                                                                                │
│ 目标：提供运维团队部署、监控、恢复所需的工具                                                   │
│                                                                                                │
│ M2.1 统一初始化管理命令                                                                        │
│                                                                                                │
│ 问题：scripts/ 下有 11 个 init_*.py 脚本，但无统一入口，新部署时容易遗漏。                     │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - management/commands/init_all.py — 按依赖顺序调用所有 init 脚本                               │
│ - management/commands/healthcheck.py — CLI 健康检查（exit 0/1），可用于 Docker HEALTHCHECK     │
│ - management/commands/warmup_cache.py — 预热 regime 状态、宏观指标、alpha 分数缓存             │
│                                                                                                │
│ M2.2 Celery 任务加固                                                                           │
│                                                                                                │
│ 问题：apps/macro/application/tasks.py 有重试配置，但其他 task 文件配置不一致。                 │
│                                                                                                │
│ 审查并修改：所有 apps/*/application/tasks.py（约 13 个文件），确保每个 task 都有：             │
│ - max_retries, default_retry_delay, autoretry_for                                              │
│ - time_limit, soft_time_limit                                                                  │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - core/settings/base.py — 添加全局 Celery 安全配置：                                           │
│ CELERY_TASK_REJECT_ON_WORKER_LOST = True                                                       │
│ CELERY_TASK_ACKS_LATE = True                                                                   │
│                                                                                                │
│ M2.3 运维手册                                                                                  │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - docs/operations/runbook.md — 涵盖：                                                          │
│   - 首次部署检查清单                                                                           │
│   - 每日数据同步验证                                                                           │
│   - Celery 任务故障排查                                                                        │
│   - 数据库备份/恢复（引用 scripts/vps-backup.sh 和 scripts/vps-restore.sh）                    │
│   - 回滚流程（引用 scripts/rollback.sh）                                                       │
│                                                                                                │
│ M2.4 Docker Compose 生产加固                                                                   │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - docker/docker-compose.vps.yml — 添加资源限制、日志轮转配置                                   │
│                                                                                                │
│ 验收标准：                                                                                     │
│ - python manage.py init_all 成功初始化空数据库                                                 │
│ - python manage.py healthcheck 健康返回 0，异常返回 1                                          │
│ - 所有 Celery task 文件有一致的重试/超时配置                                                   │
│ - 运维手册覆盖所有关键场景                                                                     │
│                                                                                                │
│ ---                                                                                            │
│ M3: 集成测试与数据管道 (第 3-4 周)                                                             │
│                                                                                                │
│ 目标：验证端到端数据流程和外部数据源故障转移                                                   │
│                                                                                                │
│ M3.1 测试固件数据                                                                              │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/fixtures/macro_data.json — 12 个月宏观指标样本（PMI, CPI, M2）                         │
│ - tests/fixtures/market_data.json — 指数日线数据样本（回测用）                                 │
│ - tests/fixtures/alpha_scores.json — Alpha 分数缓存样本                                        │
│                                                                                                │
│ M3.2 数据管道集成测试                                                                          │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/integration/test_data_pipeline_flow.py — 测试完整链路：宏观数据采集 → Regime 计算 →    │
│ 信号生成 → 审计追踪（mock 外部 API）                                                           │
│ - tests/integration/test_failover_flow.py — 测试数据源故障转移：Tushare 失败 → AKShare 接管 →  │
│ 数据一致性校验                                                                                 │
│                                                                                                │
│ M3.3 性能基线测试                                                                              │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/performance/conftest.py — 预置大规模数据（1000+ 宏观数据点、500+ 信号）                │
│ - tests/performance/test_api_latency.py — 关键 API P95 延迟基线（regime                        │
│ 状态、信号列表、仪表盘数据）                                                                   │
│                                                                                                │
│ 验收标准：                                                                                     │
│ - 数据管道集成测试通过（mock 外部 API）                                                        │
│ - 故障转移测试验证优雅降级                                                                     │
│ - 性能测试建立延迟基线数据                                                                     │
│ - tests/fixtures/ 包含代表性测试数据                                                           │
│                                                                                                │
│ ---                                                                                            │
│ M4: 前端质量与 CI 加固 (第 4 周)                                                               │
│                                                                                                │
│ 目标：防止 UI 回归，强化发布门禁                                                               │
│                                                                                                │
│ M4.1 模板渲染测试                                                                              │
│                                                                                                │
│ 问题：97 个 HTML 模板仅有 2 个验收测试，模板渲染错误只能手动发现。                             │
│                                                                                                │
│ 创建文件：                                                                                     │
│ - tests/unit/test_template_rendering.py — 遍历所有模板，使用最小上下文渲染，验证无             │
│ TemplateSyntaxError                                                                            │
│                                                                                                │
│ M4.2 Playwright 测试纳入 CI                                                                    │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - .github/workflows/nightly-tests.yml — 添加 Playwright 测试步骤                               │
│                                                                                                │
│ M4.3 CI 覆盖率门禁                                                                             │
│                                                                                                │
│ 修改文件：                                                                                     │
│ - .github/workflows/rc-gate.yml — 添加 Domain 层覆盖率阈值检查（--cov-fail-under=70）          │
│                                                                                                │
│ 验收标准：                                                                                     │
│ - 模板渲染测试覆盖全部 97 个模板                                                               │
│ - Playwright 测试在 nightly CI 中运行                                                          │
│ - RC gate 在 Domain 覆盖率低于阈值时失败                                                       │
│                                                                                                │
│ ---                                                                                            │
│ 实施时序                                                                                       │
│                                                                                                │
│ 第 1 周:  M0（全部 4 项，可并行）+ M1.1（工厂基础设施）+ M1.2（4 个高优模块测试）              │
│ 第 2 周:  M1.3（4 个中优模块测试）+ M2.1（管理命令）                                           │
│ 第 3 周:  M2.2-M2.4（运维就绪）+ M3.1-M3.2（集成测试）                                         │
│ 第 4 周:  M3.3（性能基线）+ M4.1-M4.3（前端 + CI）                                             │
│                                                                                                │
│ 依赖关系：                                                                                     │
│ - M0 各项相互独立，可完全并行                                                                  │
│ - M1.2/M1.3 依赖 M1.1（工厂基础设施）                                                          │
│ - M2 与 M1 无依赖，可并行                                                                      │
│ - M3 依赖 M1.1（工厂函数复用）                                                                 │
│ - M4 完全独立                                                                                  │
│                                                                                                │
│ ---                                                                                            │
│ 关键文件索引                                                                                   │
│                                                                                                │
│ ┌──────────────────────────────────────────────┬──────┬────────────┐                           │
│ │                     文件                     │ 操作 │ 所属里程碑 │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ core/settings/production.py                  │ 修改 │ M0.1, M0.2 │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ core/health_checks.py                        │ 修改 │ M0.4       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ requirements-prod.txt                        │ 修改 │ M0.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ requirements-prod.lock                       │ 新建 │ M0.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ docker/Dockerfile.prod                       │ 修改 │ M0.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ .env.example                                 │ 修改 │ M0.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/factories/domain_factories.py          │ 新建 │ M1.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/factories/model_factories.py           │ 新建 │ M1.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_hedge_services.py     │ 新建 │ M1.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_fund_services.py      │ 新建 │ M1.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_factor_services.py    │ 新建 │ M1.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_rotation_services.py  │ 新建 │ M1.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_dashboard_services.py │ 新建 │ M1.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_sector_services.py    │ 新建 │ M1.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_equity_services.py    │ 新建 │ M1.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/domain/test_events_services.py    │ 新建 │ M1.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ management/commands/init_all.py              │ 新建 │ M2.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ management/commands/healthcheck.py           │ 新建 │ M2.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ management/commands/warmup_cache.py          │ 新建 │ M2.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ apps/*/application/tasks.py (13 files)       │ 修改 │ M2.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ core/settings/base.py                        │ 修改 │ M2.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ docs/operations/runbook.md                   │ 新建 │ M2.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ docker/docker-compose.vps.yml                │ 修改 │ M2.4       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/fixtures/*.json (3 files)              │ 新建 │ M3.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/integration/test_data_pipeline_flow.py │ 新建 │ M3.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/integration/test_failover_flow.py      │ 新建 │ M3.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/performance/test_api_latency.py        │ 新建 │ M3.3       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ tests/unit/test_template_rendering.py        │ 新建 │ M4.1       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ .github/workflows/nightly-tests.yml          │ 修改 │ M4.2       │                           │
│ ├──────────────────────────────────────────────┼──────┼────────────┤                           │
│ │ .github/workflows/rc-gate.yml                │ 修改 │ M4.3       │                           │
│ └──────────────────────────────────────────────┴──────┴────────────┘        