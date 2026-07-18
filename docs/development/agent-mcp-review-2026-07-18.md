# Agent → MCP 链路审视报告（2026-07-18）

> **审视范围**: `apps/agent_runtime`、`apps/ai_capability`、`apps/terminal`、`sdk/agomtradepro_mcp`、TUI metadata 及 agent 调用 MCP 全链路
> **审视方式**: 代码走查 + 真实 dry-run（进程内 MCP 工具调用、stage→resume 全流程复现、Django view probe)
> **测试基线**: 相关单测 713 个用例全绿（`test_terminal*` / `test_agent_runtime*` / `test_mcp*` / `test_tui*` / `sdk/tests/test_sdk/test_client.py`);`debug/` 下 4 份历史验收报告全绿
> **重要结论**: 本文档中的 Critical/High 级 bug **全部没有被现有测试捕获**。根因是单测普遍注入 fake repository / fake handler，绕过了真实装配。修复时必须同时补充"走真实装配"的集成测试，否则同类问题会再次出现。

## 复核与整改结果（2026-07-18）

本报告所列问题已按当前代码再次核验。结论不是 14 项全部成立：其中 **11 项成立、1 项部分成立、1 项为已明确记录的设计约束、1 项不成立**。成立的问题已在本次整改中修复或缓解，并补充真实装配、core-only MCP 注册、异步桥接和异常配置回归测试。

| # | 复核结论 | 整改结果 |
|---|----------|----------|
| 1 | 成立 | task governed handler 改为直接调用 SDK 的 agent runtime client，不再依赖被禁用的 legacy tool；补 core-only stage→resume 测试 |
| 2 | 成立 | `update_task_state`、`task_exists`、`get_health_summary` 归位到 `AgentTaskRepository`；补真实 repository/API 测试 |
| 3 | 成立 | `command.pk` 改为领域实体真实字段 `command.id`；各 capability source 独立失败、互不阻断 |
| 4 | 部分成立 | 同步 HTTP 自调用风险成立；“requests/urllib3 默认重试”表述不准确：SDK 业务请求显式配置重试，而审计 `requests.post` 本身没有默认重试。审批执行现通过 ContextVar 注入 Django 进程内 SDK transport，审计通过 Audit Application facade 本地持久化；transport 已覆盖 JSON、表单和有界 multipart，完整 stage→resume 测试会拦截所有 `requests.Session.request`，业务和审计均不再自调用 HTTP |
| 5 | 成立 | 单次工具调用内缓存 backend profile，角色和用户信息复用同一结果 |
| 6 | 成立 | 上下文快照改用现存模型和真实字段；原报告“全部无告警”表述不准确，多数分支原本已有 warning，本次补齐 freshness 告警和真实源测试 |
| 7 | 成立 | 三处同步/异步桥接统一为可在已有 event loop 中安全调用的共享实现 |
| 8 | 不成立 | `terminal.search.user_actions` 已在 terminal read capability owner 中注册并有测试，不做删除或替换 |
| 9 | 成立 | `.mcp.json` 解析合并到共享安全加载器，畸形 JSON 回退为空配置 |
| 10 | 设计约束 | 确认 token 有意绑定同一 MCP server 进程，现有 MCP 指南已明确；本次仅把错误信息改为明确提示必须在同一进程 resume |
| 11 | 成立 | 两处 MCP gateway 合并到 `shared.infrastructure.mcp_runtime` |
| 12 | 成立 | panel 默认值在校验前注入，删除 `raise` 后不可达代码 |
| 13 | 成立 | 外键改用 `settings.AUTH_USER_MODEL`；migration dry-run 无新增变更 |
| 14 | 成立 | 根 `pytest.ini` 纳入 `sdk/tests` |

附带清理：发布版 TUI operation graph 中过时的 market thermometer `NameError` 说明已删除。完整验证结果见本文末尾整改记录。

---

## 一、问题清单总览

| # | 级别 | 问题 | 影响面 | 状态 |
|---|------|------|--------|------|
| 1 | **Critical** | Terminal Agent 子进程禁用 legacy tools 后，`agent_task.*` governed capability 执行必炸 | Terminal Agent → MCP 创建/恢复/取消任务 | 已 live 复现 |
| 2 | **High** | `AgentTaskRepository` 缺 `update_task_state`/`task_exists`（错放到 `AgentTimelineRepository`) | `POST /tasks/{id}/resume/`、`/cancel/`、`POST /proposals/` 三个 API 500 | 已 live 复现 |
| 3 | **High** | `DjangoTerminalCapabilityGateway.list_active_commands` 读取不存在的 `command.pk`，并中断 capability 全量同步 | AI capability catalog 同步（mcp_tool/api source 被静默跳过） | 已 live 复现 |
| 4 | Medium | 进程内 MCP 调用做同步 HTTP 自调用（审计 + 会话登录），带 urllib3 默认重试 | 审批链路延迟、Daphne 线程池饿死风险 | 已 dry-run 实测 |
| 5 | Medium | MCP RBAC 每次工具调用都重新拉取 `api/account/profile/`，无缓存 | 每次 MCP 调用增加 1-3 次自调用 HTTP 开销 | 代码走查 + dry-run 佐证 |
| 6 | Medium | `DjangoContextSnapshotRepository` 引用 17 处不存在的模型名，快照静默降级 | Agent 上下文聚合能力实质失效（无报错） | 代码走查 |
| 7 | Low | `asyncio.run()` 出现在三个同步桥接点，调用方一旦变 async 即 `RuntimeError` | 潜伏性集成故障 | 代码走查 |
| 8 | Low | Agent 指令引用不存在的 capability `terminal.search.user_actions` | 模型按指令字面执行时必失败 | 代码走查 |
| 9 | Low | `mcp_proposal_executor` 的 `.mcp.json` 解析无 try/except（姊妹文件有） | 配置文件畸形时所有审批执行崩溃 | 代码走查 |
| 10 | Low | 确认 token 进程内存态，跨进程 stage→resume 报 `confirmation_not_found` | 跨进程/跨请求的确认流程 | dry-run 实测 |
| 11 | Low | 两处 MCP gateway 代码重复且已漂移 | 维护一致性风险 | 代码走查 |
| 12 | Low | `tui_metadata.py` `raise` 后存在不可达代码，p0 panel 默认值永不填充 | TUI metadata 注入 | 代码走查 |
| 13 | Low | `AgentTaskModel` 硬编码 `auth.User`，与 migration 的 `AUTH_USER_MODEL` 不一致 | 未来切换自定义用户模型时炸 | 代码走查 |
| 14 | Low | 根 `pytest.ini` 的 `testpaths` 不含 `sdk/tests` | SDK 测试在根目录裸跑时漏发现 | 已验证 |

叠加效应说明：**#1 与 #2 共同导致 agent 任务生命周期（create/resume/cancel）在两条入口上同时断裂**——Terminal Agent 走 MCP 子进程断在 #1,Web API 走视图直调断在 #2。建议作为一个修复主线一起处理。

---

## 二、Critical / High 级问题详情

### 1. Critical — Terminal Agent → MCP 任务类 capability 执行必炸

**现象**: capability 确认预览（stage）成功，确认执行（resume）时报 `capability_execution_failed: 'Legacy tool is not registered: start_research_task'`。

**根因链**:

- Terminal Agent 启动 MCP 子进程时显式设置 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false`
  - `apps/agent_runtime/infrastructure/terminal_agent_service.py:326`
- 但 `agent_task.create.task` / `agent_task.resume.task` / `agent_task.cancel.task` 的内部 handler 仍然委托给 legacy MCP 工具：
  - `sdk/agomtradepro_mcp/registry/runtime_handlers/owners/agent_runtime.py:260,285,309`
  - 注册声明：`sdk/agomtradepro_mcp/registry/modules/owners/agent_runtime_write_capabilities.py:198,234,263`

```python
# sdk/agomtradepro_mcp/registry/runtime_handlers/owners/agent_runtime.py:260
return _call_registered_tool(
    f"start_{task_domain}_task",   # legacy 工具，禁用时未注册
    {"task_type": task_type, "input_payload": payload},
)
```

**复现证据**（同一进程内 stage + resume,`AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false`、`AGOMTRADEPRO_MCP_ROLE=admin`):

```text
STAGED:   {"ok": false, "status": "confirmation_required", "confirmation_token": "...", "preview_result": {"success": true, ...}}
RESUMED:  {"ok": false, "status": "error",
           "error": {"code": "capability_execution_failed",
                     "message": "'Legacy tool is not registered: start_research_task'"},
           "capability_key": "agent_task.create.task"}
```

**修复方向**（二选一，建议 a):

- a) 内部 handler 不再走 legacy 工具，直接调用 `client.agent_runtime.create_task / resume_task / cancel_task`(SDK 已有对应客户端方法）;
- b) 在 `LEGACY_TOOL_FALLBACKS` 中为 task 类工具补 SDK fallback。

**配套测试**: 增加一个集成测试，在 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS=false` 下对 `agent_task.create.task` 走完整 stage→resume，断言不出现 `Legacy tool is not registered`。

---

### 2. High — `AgentTaskRepository` 方法错放导致 resume/cancel/create-proposal 500

**现象**: 以下三个 API 在真实装配下必然 `AttributeError`:

- `POST /api/agent-runtime/tasks/{id}/resume/`
- `POST /api/agent-runtime/tasks/{id}/cancel/`
- `POST /api/agent-runtime/proposals/`(create)

**根因**: `update_task_state` 和 `task_exists` 被实现在 `AgentTimelineRepository` 上，但用例注入的是 `AgentTaskRepository`:

```python
# apps/agent_runtime/infrastructure/repositories.py:107-153
class AgentTimelineRepository:        # ← 方法错放在这个类上
    def update_task_state(self, task_id: int, *, status: str, ...): ...   # :136
    def task_exists(self, task_id: int) -> bool: ...                      # :152

# 调用方拿到的却是 AgentTaskRepository（repositories.py:27，无这两个方法）
# apps/agent_runtime/application/use_cases.py:328,387   (Resume)
# apps/agent_runtime/application/use_cases.py:453,498   (Cancel)
# apps/agent_runtime/application/proposal_use_cases.py:215 (CreateProposal)

# 视图全部使用默认装配：
# apps/agent_runtime/interface/views.py:456  ResumeTaskUseCase()
# apps/agent_runtime/interface/views.py:533  CancelTaskUseCase()
# apps/agent_runtime/interface/views.py:913  CreateProposalUseCase()
```

**live probe 证据**:

```text
Resume task_repo: AgentTaskRepository has update_task_state: False
Cancel task_repo: AgentTaskRepository has update_task_state: False
CreateProposalUseCase task_repo: AgentTaskRepository has task_exists: False
```

**修复方向**: 将 `update_task_state`/`task_exists` 移回 `AgentTaskRepository`（更符合语义：`get_health_summary` 也操作 `AgentTaskModel`，建议一并评估归属），或用例改为同时注入 timeline repository。移方法时注意 `AgentTimelineRepository` 上是否还有其他调用方依赖这两个方法。

**配套测试**: 对 resume/cancel/create-proposal 各加一个使用真实 repository(开发库或测试库）的接口级测试，禁止再用 fake 替换装配。

---

### 3. High — `command.pk` AttributeError 中断 capability 全量同步

**现象**: `DjangoTerminalCapabilityGateway.list_active_commands()` 必然抛 `AttributeError: 'TerminalCommand' object has no attribute 'pk'`（已 live 复现）。

**根因**:

```python
# apps/terminal/application/ai_capability_gateway.py:26-40
def list_active_commands(self) -> list[dict[str, Any]]:
    return [
        {
            "id": str(command.id),
            "pk": str(command.pk),   # domain TerminalCommand 只有 id: str（entities.py:85），没有 pk
            ...
        }
        for command in get_terminal_command_repository().get_all_active()
    ]
```

**放大效应（比单点崩溃更严重）**: 调用方 `apps/ai_capability/application/sync_use_cases.py:102-127` 把四个同步源放在**同一个 try 块内串行执行**，顺序为 `builtin → terminal_command → mcp_tool → api`。`terminal_command` 一抛异常，整个循环中断，**`mcp_tool` 和 `api` 两个 source 被静默跳过**，最终只记录 `error_count=1`，表面上同步"完成"了。

**修复方向**:

1. `command.pk` 改为 `command.id`（或评估响应里是否还需要 `pk` 字段，下游 `sync_use_cases.py:169` 目前未使用 `pk`);
2. 同步循环改为**逐 source 隔离异常**(每个 source 独立 try/except，单源失败不波及其他源），这是防止同类单点故障再次拖垮全量同步的结构性修复。

**配套测试**: 集成测试调用真实 `DjangoTerminalCapabilityGateway().list_active_commands()`；另加一个"单 source 抛异常时其余 source 仍完成同步"的用例。

---

## 三、Medium 级问题详情

### 4. 进程内 MCP 调用的同步 HTTP 自调用

**链路**: 审批视图（`apps/agent_runtime/interface/views.py:1138`)→ `ApprovedMcpCapabilityExecutor`(`apps/agent_runtime/infrastructure/mcp_proposal_executor.py:50`）进程内执行 MCP 工具 → SDK 内部再同步 HTTP 打回本服务：

- 审计 POST:`sdk/agomtradepro_mcp/audit.py:408`,`requests.post(..., timeout=5)`,urllib3 默认重试
- 会话登录 GET（无 API token 时）:`sdk/agomtradepro/client.py:237`，每次 client 实例化都走表单登录（2 个请求）

**实测**: 本地服务未启动时，单次 MCP 工具调用在 urllib3 重试上浪费约 10-15 秒（`Max retries exceeded` 警告多次）。

**风险**:

- 延迟：生产环境每次审批执行固定附带 2+ 次自调用 HTTP 往返；
- 可用性：生产为 Daphne 单进程（`docker/entrypoint.prod.sh:196`),sync 视图跑在 ASGI 线程池（默认 5 线程）。线程 A 持有线程等自调用、自调用又需要新线程才能被服务 —— 并发审批时有线程池饿死/级联超时风险；
- 审计代码注释声称"网络错误不阻塞主流程"(`audit.py:436`)，但实际每次失败要阻塞到重试耗尽，与注释不符。

**修复方向**:

- 审计发送改为短超时（如 1s)+ 禁用重试，或改 fire-and-forget 后台队列；
- 进程内调用场景下，审计应直接写本地（走 application 层）而非 HTTP 自调用；
- SDK client 缓存会话登录结果，避免每次实例化重新登录。

### 5. MCP RBAC 无缓存重复拉取用户资料

`sdk/agomtradepro_mcp/rbac.py:389-414` 的 `_get_user_id()` / `_get_username()` 在**每次工具调用**都新建 client 请求 `api/account/profile/`，不受 `_BACKEND_ROLE_CACHE` 覆盖。叠加 #4 的会话登录问题，无 token 环境下单次工具调用最多触发 4 次自调用 HTTP（登录 GET + 登录 POST + profile GET + 审计 POST)。

**修复方向**: 将 user_id/username 解析纳入 `_BACKEND_ROLE_CACHE` 同一缓存生命周期。

### 6. `DjangoContextSnapshotRepository` 模型名大面积写错

`apps/agent_runtime/infrastructure/context_snapshot_repository.py:34-393` 引用了 17 处不存在的模型类名，全部被 try/except 吞掉，表现为每类上下文快照静默返回 `status: unavailable`。Agent 的上下文聚合能力实质失效且无任何报错信号。

错误引用与实际模型对照（节选，完整清单见审查记录）:

| 行号 | 错误名称 | 实际模型 |
|------|----------|----------|
| 38, 190, 369 | `RegimeRecord` | `RegimeLog` |
| 58 | `PolicyEvent` | `PolicyLog` |
| 100, 317, 383 | `InvestmentSignal` | `InvestmentSignalModel` |
| 143 | `BetaGateConfig` | `GateConfigModel` |
| 199 | `MacroDataPoint` | `MacroIndicator` |
| 227 | `AIProvider` | `AIProviderConfig` |
| 241 | `AuditRecord` | `OperationLogModel` |
| 258 | `PriceAlert` | `PriceAlertModel` |
| 283 | `SentimentRecord` | `SentimentIndexModel` |
| 353 | `SimulatedAccount` | `SimulatedAccountModel` |

另有 128、297 两处拿到的是 domain entity（无 `.objects`)，会走另一条失败路径。

**修复方向**: 逐一对照各 app `infrastructure/models.py` 修正类名；并在降级分支加 `logger.warning`（当前完全静默）；补一个断言快照 `status != "unavailable"` 的集成测试。

---

## 四、Low 级问题详情

### 7. `asyncio.run()` 同步桥接的潜伏故障

三处： `apps/agent_runtime/infrastructure/terminal_agent_service.py:133`、`apps/ai_capability/application/mcp_runtime_gateway.py:108`、`apps/agent_runtime/infrastructure/mcp_proposal_executor.py:50`。当前调用方都是 sync 视图所以未发作；一旦任一调用方改为 async(ASGI 原生视图、Celery 的某些 pool、Jupyter)，立即 `RuntimeError: asyncio.run() cannot be called from a running event loop`。建议封装 loop-aware 的执行工具（如有运行中的 loop 则 `nest_asyncio` 或新建线程跑 loop)，或在调用方规约中显式禁止 async 调用。

### 8. Agent 指令引用不存在的 capability

`apps/agent_runtime/infrastructure/terminal_agent_service.py:389` 指示模型搜索 `terminal.search.user_actions`，目录中不存在该 capability，模型按字面执行会 search 落空。修正指令文案或补齐该 capability。

### 9. `.mcp.json` 解析缺异常保护（单点不一致）

`apps/agent_runtime/infrastructure/mcp_proposal_executor.py:36` 的 `json.loads` 无 try/except；姊妹文件 `apps/ai_capability/application/mcp_runtime_gateway.py:31-34` 已有保护。两处实现对齐即可。

### 10. 确认 token 进程内存态

`agom_confirmation_resume` 的 token 存于进程内存，跨进程（或 MCP server 重启）后 stage→resume 报 `confirmation_not_found`。`ApprovedMcpCapabilityExecutor` 同进程完成两步所以不受影响；但外部 agent 经 stdio 子进程时若 stage 与 resume 落在不同进程会失败。至少在文档/错误信息中明确 token 的生命周期约束；如有跨进程需求，考虑落库或带 TTL 的共享存储。

### 11. MCP gateway 代码重复且已漂移

`_ensure_sdk_on_path` / `_load_mcp_env_from_repo_config` / `call_sdk_mcp_tool` 在 `apps/ai_capability/application/mcp_runtime_gateway.py` 与 `apps/agent_runtime/infrastructure/mcp_proposal_executor.py` 各有一份，实现已不一致（`sys.path` 一个用 `setdefault` 式判重、一个先移除再置顶；异常保护一个有、一个没有——见 #9)。建议下沉到单一共享位置（如 `shared/infrastructure/` 或 SDK 侧暴露官方入口），两个 app 复用。

### 12. TUI metadata 校验存在不可达代码

`apps/terminal/application/tui_metadata.py:476-481`:`raise TuiMetadataValidationError(...)` 之后紧跟三行 `panel.setdefault("status"/"note"/"layout_area", "")`，永远不会执行，p0 panel 的默认值填充逻辑实际缺失。把 setdefault 移到 raise 之前（或确认该默认值不再需要后删除死代码)。

### 13. `AgentTaskModel` 硬编码 `auth.User`

`apps/agent_runtime/infrastructure/models.py:9` 直接 `from django.contrib.auth.models import User`，而 migration 使用 `settings.AUTH_USER_MODEL`。当前用默认用户模型不发作，切换自定义用户模型即外键指错表。改为 `settings.AUTH_USER_MODEL`。

### 14. 根 `pytest.ini` 未覆盖 `sdk/tests`

`testpaths = tests apps`,SDK 测试需显式传路径才会跑。CI 若依赖根目录裸跑 `pytest`,SDK 测试全程缺席。将 `sdk/tests` 加入 `testpaths`（注意 SDK 自身 `sdk/pyproject.toml` 的独立配置保持不变）。

---

## 五、排查中排除的误报（避免开发团队重复排查）

1. **`AgentTaskViewSet(viewsets.ReadOnlyModelViewSet)` 路由缺失——不是 bug**。子类显式定义的 `create` 会被 DRF router 按 `hasattr` 正常绑定（实测 `task-list` 绑定 `['get','post']`,`task-detail` 绑定 `['delete','get','patch','put']`);`update/partial_update/destroy` 返回 405 是 FROZEN 设计（`views.py:404-432`)，状态变更故意只走 resume/cancel。
2. **TUI metadata 记录的 "market-thermometer/history NameError"——已过时**。`config/tui/published/tui_operation_graph.published.json:9628` 的 `deferred_examples` 称该端点有 NameError，实测 `/api/data-center/market-thermometer/history/` 返回 200。建议同步清理该条 metadata 注释。

---

## 六、修复主线建议（按 Git 工作流拆分）

按 AGENTS.md 主线切分要求，建议拆三条独立分支，不要混在一个批次：

| 分支 | 内容 | 对应问题 |
|------|------|----------|
| `dev/fix-agent-mcp-execution` | Critical + #2，打通 agent 任务生命周期两条入口 | #1、#2 |
| `dev/fix-capability-sync-isolation` | `command.pk` 修复 + 同步源异常隔离 | #3 |
| `dev/fix-mcp-self-call-overhead` | 自调用开销、RBAC 缓存、审计重试策略 | #4、#5 |

#6(快照模型名）量大米碎，可单独开 `dev/fix-context-snapshot-models`;#7-#14 作为小收口附在对应主线的独立 commit 中。

**每条主线合并前必须运行最小回归包**(AGENTS.md 第 6 节）:

```bash
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q
```

并补充本文档要求的新增集成测试（走真实装配），否则"fake 掩盖装配错误"的问题会第三次发生。

---

## 七、审视过程记录（可复核）

- 测试 dry-run:713 passed(220s)，无 skip/xfail;`manage.py check` 无问题；三个关键 app `compileall` 通过。
- MCP 工具清单 dry-run：进程内列出 9 个核心工具（`agom_bootstrap`、`agom_get_agent_contract`、`agom_capability_search/schema/call`、`agom_confirmation_resume`、`agom_workflow_start/status` 等）。
- 工具调用 dry-run:`agom_get_agent_contract` 返回完整 contract(`ok: True`)；期间观察到审计与登录自调用失败重试（问题 #4/#5 的实测证据）。
- Critical 复现：同进程 stage→resume 完整走通，确认预览成功、执行报 `Legacy tool is not registered`。
- High #2/#3:live probe 直接实例化用例/gateway 验证 `hasattr` 与实际异常，视图默认装配链路经代码确认。

---

## 八、整改验证记录（2026-07-18）

**已验证**:

- 复核相关定向测试：56 passed。
- `terminal_agent_service`、SDK client、internal SSL redirect 最小回归包：33 passed。
- Ruff：本次 Python 改动全部通过。
- `python manage.py check`：通过，无 system check issue。
- `python manage.py makemigrations agent_runtime --check --dry-run`：无新增 migration。
- `python -m compileall` 与 `git diff --check`：通过。
- 继续整改的本地 SDK transport、审计 sink、异步/同步桥接、SDK/MCP 及原有提案扩展回归：65 passed。
- 完整审批 `stage→resume` 真实集成已通过，并在测试中禁止所有 `requests.Session.request`；若业务或审计回退到 HTTP 会直接失败。
- `account.import.broker_trades` 是现存 governed multipart 能力，并非未来假设；真实集成已验证其从内存 trades 生成 CSV、multipart 解析、交易落库的全链路。单文件大小、文件数、请求总大小、文件名和有界流读取均有进程内约束测试。
- 架构边界、架构工具和架构回归护栏：19 passed。
- 完整 TUI、Terminal Agent service、internal SSL redirect 固定回归：231 passed。
- SDK 测试配置现在把本仓库 `sdk/` 放到 `sys.path` 首位，避免根目录测试误导入其他 checkout 的同名包。

**剩余边界**:

- 进程内 transport 只在 Django 审批执行上下文启用；外部 SDK 和独立 MCP 进程继续通过正式 HTTP API 通信，这是预期边界。
- 进程内 transport 已支持 requests 风格的单值 multipart 文件参数，并复用 Django 的 `FILE_UPLOAD_MAX_MEMORY_SIZE`、`DATA_UPLOAD_MAX_MEMORY_SIZE` 与 `DATA_UPLOAD_MAX_NUMBER_FILES` 限制；当前 governed broker trade 导入闭环已覆盖。多值同名文件、磁盘临时文件流等尚无业务需求，不在本轮扩展范围内。
- 本轮并行生成的 TUI runtime/frontend 改动保留原状；其当前完整 Python 契约回归已通过，但不归属于本次 Agent→MCP 代码整改。
