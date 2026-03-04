# AgomSAAF 系统治理改进计划（修订版）

## Context

本计划用于补强系统治理能力，聚焦三类能力：

1. 用户侧保护（限流、输入安全、请求边界）
2. 技术侧保护（异常治理、备份、可观测性）
3. AI 自动化治理（MCP 独立运行、权限与验收）

评估日期：2026-03-04  
系统版本：V3.4  
范围：现有业务模块 + SDK + MCP（以 `docs/INDEX.md` 当前口径为准）

---

## 0. 总体实施原则

1. 只做增量改造，不覆盖现有配置（尤其 `REST_FRAMEWORK`、`LOGGING`）。
2. P0/P1 不做破坏性协议变更（禁止直接把 `/api/*` 强切为 `/api/v1/*`）。
3. 每项必须同时给出：代码改动、测试、回滚方式、验收命令。
4. 生产变更默认灰度，至少保留一个发布窗口的兼容期。

---

## 一、P0（本周完成）

### P0-1 全局 API 异常处理器（增量接入）

问题：异常返回格式不统一，部分业务异常落到 DRF 默认结构。  

实施：

1. 在 `core/exceptions.py` 增加 `custom_exception_handler`。
2. `core/settings/base.py` 中以增量方式设置：
   - `REST_FRAMEWORK['EXCEPTION_HANDLER'] = 'core.exceptions.custom_exception_handler'`
3. 不改变既有认证、分页、渲染等配置项。

文件：

- `core/exceptions.py`（修改）
- `core/settings/base.py`（修改）

DoD：

1. `AgomSAAFException` 子类均返回统一结构。
2. 未识别异常仍由 DRF 默认 handler 处理。
3. 新增单测覆盖：业务异常、校验异常、未知异常。

---

### P0-2 分层限流（回测与写操作单独配额）

问题：昂贵操作与普通接口共享配额。  

实施：

1. 新建 `core/throttling.py`，定义：
   - `BacktestRateThrottle`（10/hour）
   - `WriteRateThrottle`（100/hour）
2. 在具体高成本接口绑定 `throttle_classes`，优先从回测入口开始。
3. 保留默认全局限流，不覆盖已有策略。

文件：

- `core/throttling.py`（新增）
- `apps/backtest/interface/views.py`（修改）
- `core/settings/base.py`（仅增量）

DoD：

1. 回测接口在超额请求时返回 429。
2. 普通读取接口不受回测限流影响。
3. 单测/集成测试覆盖“触发限流”与“未触发限流”。

---

### P0-3 CI 安全扫描（可执行门禁）

问题：缺少固定安全扫描门禁。  

实施：

1. 新建 `.github/workflows/security-scan.yml`。
2. 扫描包含：
   - Bandit（代码扫描）
   - 依赖漏洞扫描（工具按仓库现用方案接入）
3. 增加 baseline 机制：
   - 历史问题可告警
   - 新增高危问题阻断 PR

文件：

- `.github/workflows/security-scan.yml`（新增）

DoD：

1. PR 自动触发扫描。
2. 新增高危问题阻断合并。
3. 产出扫描报告 artifact（保留 30 天）。

---

## 二、P1（两周内）

### P1-1 MCP Server 独立入口与接入文档

问题：MCP 代码存在，但缺少标准入口和运维文档。  

实施：

1. 增加 `sdk/agomsaaf_mcp/__main__.py` 作为标准启动入口。
2. 提供 `sdk/.mcp/claude-desktop-config.json` 模板。
3. 新增 `sdk/docs/mcp-deployment.md`，包含：
   - 本地调试
   - Claude Code 配置
   - 常见故障排查

文件：

- `sdk/agomsaaf_mcp/__main__.py`（新增）
- `sdk/.mcp/claude-desktop-config.json`（新增）
- `sdk/docs/mcp-deployment.md`（新增）

DoD：

1. 本地 `python -m agomsaaf_mcp` 可启动。
2. Claude Code 按文档可成功调用工具。
3. RBAC 配置在文档中明确。

---

### P1-2 自动化数据库备份（跨平台可执行）

问题：仅有手动备份路径。  

实施：

1. 新建 `apps/task_monitor/management/commands/backup_database.py`。
2. 备份逻辑：
   - SQLite：使用 Python 文件复制（不依赖 `cp`）
   - PostgreSQL：调用 `pg_dump`，补充失败处理与日志
3. 定时任务接入 Celery Beat 前，先确认：
   - `CELERY_BEAT_SCHEDULE` 初始化安全
   - 失败告警策略（日志/告警）

文件：

- `apps/task_monitor/management/commands/backup_database.py`（新增）
- `apps/task_monitor/tasks.py`（修改）
- `core/settings/base.py`（修改）

DoD：

1. 每日备份任务自动执行。
2. 仅保留最近 7 天备份。
3. 完成一次恢复演练并留档。

---

### P1-3 请求体大小限制（DoS 基线）

实施：

在 `core/settings/base.py` 增量添加：

1. `DATA_UPLOAD_MAX_MEMORY_SIZE`
2. `FILE_UPLOAD_MAX_MEMORY_SIZE`
3. `DATA_UPLOAD_MAX_NUMBER_FIELDS`

DoD：

1. 超限请求返回 4xx 且不致服务异常。
2. 上传与普通 JSON 请求各有测试用例。

---

### P1-4 输入文本消毒（白名单字段分批上线）

问题：文本字段存在 XSS 风险。  

实施：

1. 新增 `shared/infrastructure/sanitization.py`。
2. 不做 `apps/*` 全量一次性替换，先做字段白名单：
   - 第一批：`signal`、`policy` 等高风险输入点
3. 富文本与纯文本使用不同策略。

文件：

- `shared/infrastructure/sanitization.py`（新增）
- `requirements.txt`（如需新增依赖）
- 指定模块 serializer（按白名单修改）

DoD：

1. 恶意脚本字符串被过滤。
2. 合法文本不被误删（含回归测试）。
3. 白名单覆盖清单可追踪。

---

## 三、P2（独立里程碑，禁止与 P0/P1 混改）

### P2-1 日志聚合（Loki/ELK 二选一）

实施要求：

1. 结构化日志先在控制台落地，再接外部系统。
2. 增加 trace/request-id 贯穿。
3. 先在非生产验证吞吐与查询性能。

DoD：

1. Grafana（或等效）可检索关键链路日志。
2. 日志接入不影响主请求延迟预算。

---

### P2-2 SDK E2E 测试补全

实施要求：

1. 每个主模块至少 1 条 happy path E2E。
2. 关键模块补充失败路径与鉴权路径。

DoD：

1. CI 可稳定跑通，不依赖手工前置步骤。
2. 覆盖率目标按“关键模块覆盖率”单列，不与全仓库覆盖率混淆。

---

### P2-3 API 版本化（兼容迁移项目）

说明：该项是高影响改造，不得按“8h 快速改造”执行。  

实施分期：

1. Phase A：并行支持 `/api/*` 与 `/api/v1/*`（无破坏）
2. Phase B：SDK/MCP/前端全部切换到 `/api/v1/*`
3. Phase C：公告下线窗口后再移除旧路径

DoD：

1. 迁移期间无客户端中断。
2. 提供兼容期监控与下线前流量证明。

---

## 四、工时与风险（修订）

| 优先级 | 改进项 | 预计工时 | 风险 |
|--------|--------|----------|------|
| P0 | 全局异常处理器 | 4h | 低 |
| P0 | 分层限流 | 6h | 低 |
| P0 | CI 安全扫描门禁 | 4h | 中 |
| P1 | MCP 独立入口与文档 | 6h | 低 |
| P1 | 自动化备份 + 恢复演练 | 10h | 中 |
| P1 | 请求体大小限制 | 2h | 低 |
| P1 | 输入消毒（白名单第一批） | 10h | 中 |
| P2 | 日志聚合 | 16h | 中 |
| P2 | SDK E2E 补全 | 20h | 中 |
| P2 | API 版本化（兼容迁移） | 40h+ | 高 |

---

## 五、统一验收标准

### P0 验收 ✅ (2026-03-04 完成)

- [x] API 异常结构统一且回退路径正常
- [x] 回测限流生效（429 可复现）
  - **修复**: BacktestRateThrottle 仅对 POST 生效，GET 不受影响
  - **修复**: 移除自定义 get_rate()，使 settings/env 配置生效
- [x] CI 安全扫描接入并对新增高危问题阻断

### P1 验收 ✅ (2026-03-04 完成)

- [x] MCP 可按文档独立启动并被调用
- [x] 备份任务自动执行 + 已完成恢复演练
  - **演练文档**: `docs/operations/database-restore-drill.md`
- [x] 超限请求被拒绝且服务稳定
- [x] 白名单字段完成消毒并通过回归
  - **接入**: `apps/signal/interface/serializers.py` - logic_desc, invalidation_logic
  - **接入**: `apps/policy/interface/serializers.py` - title, description

### P2 验收 (待实施)

- [ ] 日志平台可查询关键链路
- [ ] SDK E2E 在 CI 稳定通过
- [ ] API 版本化按三阶段完成，兼容期无中断

---

## 六、关键文件路径

| 文件 | 用途 |
|------|------|
| `core/exceptions.py` | 自定义异常处理 + DRF 异常处理器 |
| `core/throttling.py` | 业务限流类（含方法过滤） |
| `core/settings/base.py` | 全局配置增量接入 |
| `.github/workflows/security-scan.yml` | 安全扫描门禁 |
| `sdk/agomsaaf_mcp/__main__.py` | MCP 标准入口 |
| `sdk/.mcp/claude-desktop-config.json` | Claude Desktop 配置模板 |
| `sdk/docs/mcp-deployment.md` | MCP 部署文档 |
| `shared/infrastructure/sanitization.py` | 输入消毒模块 |
| `apps/signal/interface/serializers.py` | Signal 接入消毒 |
| `apps/policy/interface/serializers.py` | Policy 接入消毒 |
| `apps/task_monitor/management/commands/backup_database.py` | 数据库备份命令 |
| `docs/operations/database-restore-drill.md` | 恢复演练文档 |
| `tests/unit/test_throttling.py` | 限流单元测试 |
| `tests/unit/test_sanitization.py` | 消毒单元测试 |

---

## 七、回滚策略（必须执行）

1. 所有配置项改动保持可开关（feature flag 或最小化回滚 patch）。
2. P0/P1 每项都要有“单项回滚步骤”。
3. API 版本化在 Phase A/B 完成前禁止删除旧路由。
