# AgomTradePro RC E2E/UAT + AI-MCP 执行手册（外包测试版）

- 文档版本: v1.0
- 编制日期: 2026-03-05
- 适用阶段: Release Candidate (RC) 放行前
- 适用环境策略: `Staging 全量` + `Prod-like 冒烟`
- 门禁策略: `严格阻断`

---

## 1. 目标与放行标准

本手册用于指导外包测试团队在 RC 前完成以下验证：

1. 业务端到端（E2E/UAT）关键链路可用。
2. AI 通过 MCP 调用系统能力可用、可控、可追溯。
3. 满足 RC 强门禁后才能进入发布流程。

### 1.1 RC 放行硬门禁（任一失败即阻断）

1. P0 缺陷数 = 0。
2. 主导航 `404 = 0`。
3. 主链路 `501 = 0`。
4. Journey 通过率 `>= 90%`。
5. MCP 基础能力测试全部通过（tools/resources/prompts/RBAC/audit）。
6. AI->MCP 关键场景通过率 `>= 95%`。
7. MCP 调用审计日志可追溯率 `= 100%`（每条调用均可定位 `request_id`）。

### 1.2 条件放行规则

1. P1 缺陷允许最多 2 个，且必须有 workaround、责任人、修复时间（24h 内）。
2. P2/P3 不阻断 RC，但必须入库并进入版本排期。

---

## 2. 测试组织与分工

### 2.1 角色

1. 外包 QA 执行组: 执行测试、记录证据、提交缺陷。
2. 内部 QA Owner: 统一口径、缺陷分级仲裁、放行建议。
3. 开发 Owner（Backend/Frontend/SDK）: 缺陷定位与修复。
4. DevOps: 环境稳定性、CI Gate 执行与报告归档。

### 2.2 执行节奏（T-5 ~ T-0）

1. T-5: 环境冻结、账号与测试数据确认。
2. T-4: Staging 全量 E2E/UAT。
3. T-3: Staging MCP + AI-MCP 全量。
4. T-2: Prod-like 冒烟。
5. T-1: 缺陷回归与复测。
6. T-0: RC Gate 最终跑批与签字。

---

## 3. 环境、账号、数据前置条件

### 3.1 环境矩阵

| 环境 | 用途 | 执行范围 | 通过要求 |
|---|---|---|---|
| Staging | 全量回归 | E2E/UAT + MCP + AI-MCP + Guardrails | 必须通过 |
| Prod-like | 发布前验证 | 高风险主链路冒烟 | 必须通过 |

### 3.2 前置检查

1. 服务可访问：Web、API、DB、Redis、Celery。
2. SDK 已安装：`pip install -e sdk/`。
3. 必要环境变量已配置：
   - `AGOMTRADEPRO_BASE_URL`
   - `AGOMTRADEPRO_API_TOKEN`
   - `AGOMTRADEPRO_MCP_ENFORCE_RBAC=true`
4. 测试账号具备四类角色：`admin`、`owner`、`analyst`、`read_only`。
5. 审计日志查询页面/API可访问（用于追溯验证）。

---

## 4. 执行入口与基线资产（必须复用）

1. UAT 入口: `tests/uat/run_uat.py`
2. Playwright UAT: `tests/playwright/tests/uat/test_user_journeys.py`
3. MCP 验收: `tests/acceptance/test_mcp_server.py`
4. SDK 连通: `tests/acceptance/test_sdk_connection.py`
5. MCP 单测: `sdk/tests/test_mcp/`
6. CI 门禁: `.github/workflows/rc-gate.yml`
7. 结果模板: `docs/testing/test-results-template.md`
8. 缺陷模板: `docs/testing/bug-report-template.md`

---

## 5. 详细执行动作（外包团队逐条勾选）

本节为“动作级SOP”，每条必须记录：`执行人`、`开始时间`、`结束时间`、`结果(PASS/FAIL)`、`证据路径`。

### 5.1 Step A: 基础健康检查（阻断项）

#### A-01 服务健康
1. 执行：
```powershell
python -c "import requests;print(requests.get('http://127.0.0.1:8000/api/health/', timeout=8).status_code)"
```
2. 期望：返回 `200`。
3. 证据：终端输出截图，文件名 `A-01-health-YYYYMMDD-HHMM.png`。
4. 失败处理：立即停止，提 P0“环境不可用”阻断单。

#### A-02 API根路径
1. 浏览器访问 `/api/`、`/api/docs/`、`/api/schema/`。
2. 期望：页面可打开，无 5xx。
3. 证据：3 张截图（URL栏可见）。

### 5.2 Step B: E2E/UAT 全量（Staging）

#### B-01 自动化回归
1. 执行：
```powershell
python tests/uat/run_uat.py
pytest tests/playwright/tests/uat/test_user_journeys.py -v
pytest tests/uat/test_independent_uat.py -v
pytest tests/uat/test_route_baseline_consistency.py -v
```
2. 期望：
1. 命令退出码为 0（或可解释的 skip）。
2. Journey 总通过率 >= 90%。
3. route baseline 无不一致阻断项。
3. 证据：完整日志输出文件 + 报告文件路径。

#### B-02 主导航人工验证（按账号 `admin`）
1. 登录后逐个访问：
`/dashboard/`, `/macro/data/`, `/regime/dashboard/`, `/signal/manage/`, `/policy/workbench/`, `/equity/screen/`, `/fund/dashboard/`, `/backtest/create/`, `/simulated-trading/dashboard/`, `/audit/reports/`, `/ops/`
2. 每页动作：
1. 页面完整加载。
2. 点击一个主操作按钮或Tab。
3. 打开浏览器控制台确认无阻断 error。
3. 期望：无 404、无阻断级JS异常、无空白页。
4. 证据：每页 1 张截图 + 控制台截图（如有error必须单独留证）。

#### B-03 Journey关键动作人工补测
1. Journey A：未登录访问受限页应跳登录；登录后进入 dashboard。
2. Journey B：Regime 页进行一次筛选或日期切换；Policy 页查看当前状态。
3. Journey C：Signal 页检查创建/审批入口；Decision Workspace 打开并加载。
4. Journey D：模拟盘页面查看账户指标和持仓表。
5. Journey E：Backtest 页面从列表到详情（或创建页）链路可走通。
6. 期望：动作可完成，页面响应正常。
7. 证据：每个 Journey 至少 2 张截图。

### 5.3 Step C: MCP + SDK（Staging）

#### C-01 SDK 连通
1. 执行：
```powershell
pytest tests/acceptance/test_sdk_connection.py -q
```
2. 期望：核心连接能力通过，失败项可定位。
3. 证据：`sdk_connection.log` 或终端完整输出。

#### C-02 MCP 基础能力
1. 执行：
```powershell
pytest tests/acceptance/test_mcp_server.py -q
```
2. 重点核查：
1. list_tools > 0
2. list_resources 成功
3. list_prompts/get_prompt 成功
4. SDK client from MCP 初始化成功
3. 证据：完整输出日志。

#### C-03 MCP 单测（RBAC/Audit/执行）
1. 执行：
```powershell
pytest sdk/tests/test_mcp -q
```
2. 期望：RBAC、audit、tool registration、tool execution 通过。
3. 证据：pytest 汇总结果。

### 5.4 Step D: AI->MCP 真实调用场景（Staging）

每个场景均需记录：`输入提示词`、`MCP工具调用名`、`返回摘要`、`request_id`、`审计检索截图`。

#### D-01 查询类（5条）
1. 查询当前 Regime。
2. 查询 Policy 状态。
3. 查询 Signal 列表。
4. 查询 Macro 指标列表。
5. 查询 Backtest 列表。
期望：返回结构正确、字段可读、无异常中断。

#### D-02 写操作与权限（3条）
1. `admin/owner` 创建 Signal（成功）。
2. `read_only` 创建 Signal（拒绝）。
3. `analyst` 调用受限写工具（按RBAC预期通过/拒绝）。
期望：权限行为与角色矩阵完全一致。

#### D-03 Resource/Prompt（2条）
1. list_prompts + get_prompt。
2. read_resource(`agomtradepro://regime/current`)。
期望：返回非空且语义正确。

#### D-04 异常路径（2条）
1. 使用错误 token 调用任一工具。
2. 模拟后端异常（如依赖服务短时不可用）并调用工具。
期望：返回可解释错误，不可静默失败。

#### D-05 审计追溯（每个场景都做）
1. 在审计页或审计API按 request_id 查询。
2. 校验字段：tool_name、role、status、timestamp、request_params(脱敏)。
3. 期望：追溯率 100%，敏感字段脱敏。

### 5.5 Step E: Prod-like 冒烟（高风险链路）

#### E-01 Web 高风险链路
1. 登录 -> Dashboard。
2. 打开 Regime/Policy/Signal/Decision Workspace。
3. 打开 Simulated Trading 和 Backtest 关键页。
期望：全部可用、无 404/500。

#### E-02 MCP 高风险链路
1. `list_tools`。
2. 1 个读工具调用（例如 get_current_regime）。
3. 1 个写工具调用或拒绝场景（依角色）。
4. 审计回查 3 条记录。
期望：工具调用和审计均正常。

### 5.6 结果记录规范（必须执行）

#### 5.6.1 证据目录结构

```text
reports/quality/outsource/
  YYYYMMDD/
    logs/
    screenshots/
    ai-mcp-transcripts/
    audit-evidence/
```

#### 5.6.2 证据命名规则

1. 截图：`<步骤ID>-<场景>-<YYYYMMDD-HHMMSS>.png`
2. 日志：`<步骤ID>-<场景>.log`
3. 对话记录：`<场景ID>-prompt-response.md`

#### 5.6.3 单条执行记录模板

```md
- Step ID: D-02
- Executor: <name>
- Start/End: <time>
- Role: <admin/read_only/...>
- Input: <prompt/command>
- Expected: <expected>
- Actual: <actual>
- Result: PASS/FAIL
- Evidence: <relative path>
- Request ID: <id>
```

---

## 6. 测试用例清单（执行勾选）

| 用例ID | 模块 | 场景 | 优先级 | 通过标准 |
|---|---|---|---|---|
| UAT-A-001 | Journey A | 未登录访问受限页跳登录 | P0 | 302/跳转正确 |
| UAT-B-001 | Journey B | Regime 页面可加载并可筛选 | P0 | 页面无404/报错 |
| UAT-C-001 | Journey C | Signal 管理页关键操作入口可见 | P0 | 入口存在 |
| UAT-D-001 | Journey D | 模拟盘主页与持仓页可访问 | P0 | 页面可用 |
| UAT-E-001 | Journey E | Ops 中心链接无断链 | P0 | 404=0 |
| NAV-001 | Navigation | 主导航关键路由全通 | P0 | 404=0 |
| GRD-001 | Guardrail | 主链路无 501 | P0 | 501=0 |
| MCP-001 | MCP | list_tools 返回工具集合 | P0 | 数量>0 |
| MCP-002 | MCP | list_resources/read_resource 可用 | P0 | 返回有效内容 |
| MCP-003 | MCP | list_prompts/get_prompt 可用 | P1 | 返回有效内容 |
| MCP-004 | RBAC | read_only 执行写操作被拒绝 | P0 | 返回拒绝 |
| MCP-005 | Audit | 每次调用有审计日志 | P0 | 追溯率100% |
| AIMCP-001 | AI-MCP | 查询类任务执行 | P0 | 结果正确 |
| AIMCP-002 | AI-MCP | 写操作类任务执行或拒绝 | P0 | 行为符合权限 |
| AIMCP-003 | AI-MCP | 错误 token 行为 | P1 | 返回认证失败 |
| AIMCP-004 | AI-MCP | 后端异常可解释返回 | P1 | 错误可诊断 |

---

## 7. 缺陷管理规范（外包必须遵守）

### 7.1 缺陷分级

1. P0: 发布阻断（核心流程不可用、数据错误、权限失控、审计丢失）。
2. P1: 高风险（有 workaround 但影响主要流程）。
3. P2: 中风险（局部功能问题）。
4. P3: 低风险（文案/UI细节）。

### 7.2 缺陷提交要求

每个缺陷必须包含：

1. 复现步骤（可稳定复现）。
2. 期望结果与实际结果。
3. 环境信息、角色信息、测试数据。
4. 错误日志或截图/录屏。
5. 影响范围与建议优先级。

模板使用：
`docs/testing/bug-report-template.md`

### 7.3 SLA

1. P0: 2小时内响应，24小时内修复并回归。
2. P1: 当日确认与排期，下一轮回归必须关闭或给出豁免单。

---

## 8. 报告与交付物要求

## 8.1 每日回报（D-Report）

每日 18:00 前提交：

1. 当日执行用例数、通过率、阻断项。
2. 新增缺陷（按 P0/P1/P2/P3 分类）。
3. 未关闭风险与次日计划。

建议文件名：
`reports/quality/outsource-daily-report-YYYYMMDD.md`

## 8.2 最终验收包（RC-UAT Package）

必须包含：

1. 测试总结报告（基于 `test-results-template.md`）。
2. 缺陷清单（含状态、owner、ETA）。
3. 关键证据包（截图、日志、命令输出）。
4. Go/No-Go 建议与理由。

建议文件名：
`reports/quality/rc-uat-ai-mcp-final-YYYYMMDD.md`

---

## 9. RC 最终签字清单（T-0）

1. [ ] 所有 P0 已关闭。
2. [ ] P1 <= 2 且均有书面豁免或修复完成。
3. [ ] UAT Journey 通过率 >= 90%。
4. [ ] Navigation 404 = 0。
5. [ ] Main chain 501 = 0。
6. [ ] MCP 基础验收通过。
7. [ ] AI->MCP 场景通过率 >= 95%。
8. [ ] 审计追溯率 = 100%。
9. [ ] 最终报告已归档并由 QA Owner 审核通过。

---

## 10. 附录 A：推荐命令清单（一次性复制执行）

```powershell
# 1) 健康检查
python -c "import requests;print(requests.get('http://127.0.0.1:8000/api/health/', timeout=8).status_code)"

# 2) UAT/E2E
python tests/uat/run_uat.py
pytest tests/playwright/tests/uat/test_user_journeys.py -v
pytest tests/uat/test_independent_uat.py -v
pytest tests/uat/test_route_baseline_consistency.py -v

# 3) MCP/SDK
pytest tests/acceptance/test_sdk_connection.py -q
pytest tests/acceptance/test_mcp_server.py -q
pytest sdk/tests/test_mcp -q

# 4) RC Gate
# 在 GitHub Actions 触发 RC Gate (workflow_dispatch 或 rc tag)
```

---

## 11. 附录 B：外包团队提交格式（最小模板）

```md
# RC Daily Report - YYYY-MM-DD

## Summary
- Executed: XX
- Passed: XX
- Failed: XX
- Blockers (P0): X

## Key Failures
1. [ID] [Title] [Severity] [Owner]

## Risks
1. [Risk description + impact]

## Plan for Tomorrow
1. [Action]
```
