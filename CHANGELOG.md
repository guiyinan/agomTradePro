# Changelog

All notable changes to AgomTradePro will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- README 新增可日更维护的 `What's New` 区域，便于对外同步最近 1-7 天的重要变化
- Dashboard 增加可选浏览器级 Pulse 转向提醒（本地 Notification 开关）
- Regime 页面增加历史 `Regime + Pulse + Action` 三层叠加时序图

### Changed
- Dashboard 与顶部导航完成 redesign 收口，`beta_gate` / `alpha_trigger` / `decision_rhythm` 不再作为首页独立主入口暴露
- Dashboard 首页决策入口统一到新的 `decision/workspace` 6-step workflow，不再混用旧的 5-step 主流程表述
- SDK / MCP / 文档口径统一到当前 canonical 契约，补充 `client.pulse.*` 与 `decision_workflow_get_funnel_context(trade_id, backtest_id)` 使用说明
- 文档索引同步为当前事实：Regime Navigator + Pulse redesign Phase 1-3 已完成
- 预上线阶段将真实仓持仓主链直接切到统一账本：`/api/account/positions/*` 成为唯一 canonical 实仓持仓入口，移除单独的 `/api/account/unified-positions/`
- GitHub Actions 的日常门禁 workflow 现在对 `dev/**` 分支的 push / pull request 也会自动触发，不再只覆盖 `main`

### Deprecated
- (TBD)

### Removed
- (TBD)

### Fixed
- Regime Navigator redesign 相关文档仍标记“待实施”的事实漂移
- SDK/MCP 集成测试计划中的认证描述，改回真实的 `Authorization: Token <token>` 口径
- GitHub `Consistency Check` 新增的 4 处文档路由漂移，已改为当前可解析的 canonical 路径表述
- `apps/signal/domain/invalidation.py` 改为 timezone-aware UTC 时间戳，消除 `datetime.utcnow()` 弃用警告
- 真实仓持仓的修改 / 保存 / 平仓链条统一走 `UnifiedPositionService`，派生字段重算、平仓写交易账本、旧账本 bootstrap 和 API 路径口径已一并收口

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
- **模块总数**: 从 30 个增加到 34 个业务模块
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
**Last Updated**: 2026-03-27
