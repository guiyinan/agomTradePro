# AgomSAAF 外包全量回归执行方案（2026-02-26）

> 版本: 1.0
> 适用对象: 外包执行团队 + 内部技术验收 + QA + 业务 Owner
> 执行模式: 分层分阶段
> 环境基线: SQLite + Docker/Postgres 双环境
> 交付节奏: 每日增量 + 周汇总

---

## 1. 目标与通过标准

### 1.1 回归目标
1. 主链路可用：宏观->准入->信号->执行->审计全流程无阻断。
2. SDK/MCP 可用：模块接口、工具注册/执行、RBAC 全通过。
3. 发布可控：满足 PR/Nightly/RC/PostDeploy 门禁。

### 1.2 强制通过门槛
1. P0 缺陷 = 0。
2. P1 缺陷 <= 2（且必须有修复计划与截止日期）。
3. 主导航 404 = 0。
4. 主链路 501 = 0。
5. 关键旅程通过率 >= 90%。

---

## 2. 范围定义

### 2.1 在范围
1. `tests/unit`, `tests/integration`, `tests/guardrails`, `tests/uat`, `tests/playwright`。
2. `sdk/tests/test_sdk/*`, `sdk/tests/test_mcp/*`。
3. 健康检查、关键异步任务、上线后冒烟验证。

### 2.2 不在范围
1. 新功能开发。
2. 大规模性能压测（仅保留基线抽样）。
3. 生产数据修复（本轮只做验证与报告）。

---

## 3. 双环境执行策略

### 3.1 环境 A（SQLite）
用途：快速增量回归、高频反馈。
要求：每日必须执行 L0-L4 + SDK/MCP 核心集。

### 3.2 环境 B（Docker + Postgres + Redis + Celery）
用途：发布级验收、RC 门禁、PostDeploy 演练。
要求：每周必须执行 L0-L7 全链路 + SDK/MCP 全集。

### 3.3 数据规则
1. 每次执行前重建/校验测试基线数据。
2. 测试必须可重复，不依赖残留状态。
3. 禁止手工改库“修绿”。

---

## 4. 分层分阶段执行计划（周循环）

### D1-D2：PR Gate（增量）
1. Guardrail + 变更影响范围回归。
2. 关键 policy/regime/signal 测试。
3. SDK/MCP 快速集（注册、核心模块、RBAC）。

### D3-D4：Nightly Gate（全量自动化）
1. 全量 unit + 核心 integration。
2. Playwright smoke + UAT 关键旅程。
3. SDK 扩展端点 + MCP 执行全集。

### D5：RC Gate（发布候选）
1. 双环境结果对齐复跑（SQLite vs Docker）。
2. 门禁指标核验、缺陷清零决策。
3. 输出周汇总证据包并提交签字。

---

## 5. 执行命令基线

### 5.1 系统健康
```bash
python manage.py check
python manage.py migrate --plan
```

### 5.2 核心回归
```bash
pytest -q tests/guardrails
pytest -q tests/unit
pytest -q tests/integration
pytest -q tests/uat/test_api_naming_compliance.py tests/uat/test_route_baseline_consistency.py
pytest -q tests/playwright/tests/smoke/test_critical_paths.py
pytest -q tests/playwright/tests/uat/test_user_journeys.py -v
```

### 5.3 SDK/MCP 回归
```bash
pytest -q sdk/tests/test_sdk/test_extended_modules.py sdk/tests/test_sdk/test_extended_module_endpoints.py
pytest -q sdk/tests/test_mcp/test_tool_registration.py sdk/tests/test_mcp/test_tool_execution.py sdk/tests/test_mcp/test_rbac.py
```

---

## 6. 缺陷分级与处置

1. P0：24 小时内修复并回归；未清零不得通过 RC。
2. P1：48 小时内修复或书面豁免（含排期）。
3. P2/P3：进入下一迭代，必须建单追踪。
4. 每个缺陷必须附：复现步骤、失败日志、影响范围、回归用例ID。

---

## 7. 交付物标准（外包必须提交）

建议目录：`reports/regression/<yyyy-mm-dd>/`

1. `01-manifest.json`
2. `02-defects.csv`
3. `03-evidence-index.md`
4. `04-gate-status.md`
5. `05-self-test-report.md`
6. `06-risk-register.md`
7. `07-rollback-plan.md`
8. `08-signoff.md`

### 7.1 manifest.json 最低字段
- `build_id`
- `commit`
- `env`
- `suite`
- `passed`
- `failed`
- `skipped`
- `duration_sec`
- `owner`

### 7.2 defects.csv 最低字段
- `defect_id`
- `severity`
- `module`
- `case_id`
- `summary`
- `status`
- `assignee`
- `eta`
- `retest_result`

---

## 8. 交付节奏

### 8.1 每日增量（18:00 前）
提交：
1. `manifest.json`
2. `defects.csv`
3. `gate-status.md`

必须包含：
1. 新增失败项
2. 已关闭缺陷
3. 阻断项与解除计划

### 8.2 周汇总（周五）
提交完整证据包，并给出结论：
1. 通过
2. 有条件通过（48小时补齐清单）
3. 不通过

---

## 9. 门禁判定模板

### PR Gate
- [ ] Guardrail 通过
- [ ] 变更影响测试通过
- [ ] 新增接口合同测试通过

### Nightly Gate
- [ ] 全量 unit 通过
- [ ] 核心 integration 通过
- [ ] Playwright smoke 通过

### RC Gate
- [ ] 关键旅程通过率 >= 90%
- [ ] 主导航 404 = 0
- [ ] 主链路 501 = 0
- [ ] P0 = 0
- [ ] P1 <= 2（有计划）

### PostDeploy Gate
- [ ] `/api/health/` 正常
- [ ] 核心读写路径可用
- [ ] Celery 关键任务成功
- [ ] 告警链路可触发

---

## 10. 签字流程

1. 外包负责人：确认交付完整且可复现。
2. 内部技术验收：复核门禁与失败项真实性。
3. QA：确认缺陷闭环与回归完成。
4. 业务 Owner：最终验收结论签字。

---

## 11. 已锁定默认值（本轮执行）

1. 执行模式：分层分阶段。
2. 环境：双环境都要（SQLite + Docker/Postgres）。
3. 节奏：每日增量 + 周汇总。
4. 测试数字口径：当日快照，最终以最新 CI/本地执行结果为准。
5. 阻断升级：环境阻断 2 小时内必须升级并附日志。
