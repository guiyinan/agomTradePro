# 外包开发验收方案（V3.4 后续路线图）

> 版本: 1.0  
> 日期: 2026-02-26  
> 适用范围: `docs/plans/post-v34-followup-roadmap-2026-02-26.md`

---

## 1. 验收目标

确保外包交付满足以下三点：

1. 主链路可用且无占位实现（尤其 501/TODO 主入口）。
2. 结果可追溯（执行、绩效、审计都有证据链）。
3. 可发布（通过 PR/Nightly/RC/PostDeploy 门禁）。

---

## 2. 验收组织与职责

1. 业务 Owner（你）  
- 锁定需求边界、确认业务可用性、最终签字。

2. 外包团队  
- 提交代码、测试、文档、验收证据包；修复缺陷。

3. 内部技术验收人  
- 代码审查、接口契约核验、风险评估、门禁判定。

4. QA  
- 执行自动化+手工验收，输出缺陷单与验收结论。

---

## 3. 验收范围（按阶段）

## Phase 1（第1-4周）验收项

1. `multidim-screen` 正式可用（不再 501）。
2. `strategy_execute` 接入真实执行链并产生日志。
3. 持仓创建不再使用价格占位值（`100.0`）。
4. 审计报告补齐 `regime_actual` 或返回明确错误。

## Phase 2（第5-8周）验收项

1. 自动交易引擎触发绩效更新链路。
2. 净值曲线/回撤口径统一为“现金+持仓市值”。
3. 巡检结果可形成再平衡执行草案。
4. 通知通道上线并具备重试与失败可观测性。

## Phase 3（第9-12周）验收项

1. `events/api/*` 从 placeholder 迁移为真实接口。
2. 回测关键指标（换手率/ICIR/旧权重）补齐。
3. RTM 关键项（除 PostDeploy）清零 Pending。
4. CI 加入“主链路禁止 501”守护检查。

---

## 4. 提测输入物（外包必须提交）

每个阶段提测必须一次性提交：

1. 变更清单（功能、文件、接口、迁移）。
2. 自测报告（执行命令、结果摘要、失败项说明）。
3. API 契约变更（OpenAPI diff 或字段对照表）。
4. 数据迁移说明（如有）。
5. 回滚方案（至少含 DB 与配置回滚路径）。
6. 风险清单（已知限制、临时方案、技术债）。

缺任一项不进入验收执行。

---

## 5. 验收门禁（强制）

## 5.1 PR Gate（必须）

1. 变更相关单元/集成测试通过。
2. 新增接口有合同测试。
3. 代码扫描通过（lint/type/security 最低门槛）。

## 5.2 Nightly Gate（必须）

1. 核心模块回归通过（asset/strategy/account/audit/simulated_trading）。
2. Playwright smoke 通过。

## 5.3 RC Gate（必须）

1. 关键旅程通过率 >= 90%。
2. 主导航 404 = 0。
3. P0 缺陷 = 0。
4. P1 缺陷 <= 2（且有明确修复计划）。
5. API 命名/路由规范覆盖率 = 100%。

## 5.4 PostDeploy Gate（上线后）

1. `/api/health/` 正常。
2. 核心读写路径可用。
3. Celery 关键任务执行成功。
4. 告警链路可触发。

任一失败触发回滚。

---

## 6. 验收执行流程

1. 资料完整性检查（输入物齐套）。  
2. 自动化验收（PR/Nightly/RC 对应测试集）。  
3. 手工验收（关键业务路径 + 风控断言）。  
4. 缺陷归档与分级（P0/P1/P2/P3）。  
5. 回归验证（只回归失败与受影响范围）。  
6. 结论签字（通过/有条件通过/不通过）。

---

## 7. 核心测试场景（最小集）

1. 环境->标的->执行全链路可跑通（无 501）。  
2. Beta Gate 拦截时返回可读原因。  
3. 策略执行产生真实执行日志与信号统计。  
4. 行情不可用时不脏写并有告警。  
5. 再平衡建议可生成执行草案。  
6. 审计报告含 `regime_predicted/regime_actual`。  
7. Events API publish/query/status 契约通过。  
8. 回测关键指标字段完整且数值合理。

---

## 8. 缺陷分级与处置规则

1. P0（阻断）  
- 主链断裂、数据错账、审计失真、不可回滚。  
- 规则：必须修复，未清零不得通过。

2. P1（严重）  
- 核心能力不可用或错误结果风险高。  
- 规则：最多遗留 2 个，且必须有修复排期与临时缓解。

3. P2（一般）  
- 不影响主链但影响效率或体验。  
- 规则：可带入下一迭代，需建单追踪。

4. P3（优化）  
- 文案、样式、低风险优化。  
- 规则：不阻塞发布。

---

## 9. 量化评分（用于“有条件通过”）

总分 100，建议阈值：

1. >= 90：通过  
2. 80-89：有条件通过（需 48 小时内补齐）  
3. < 80：不通过

评分项：

1. 功能完整性（30）
2. 数据与结果正确性（25）
3. 测试覆盖与证据质量（20）
4. 稳定性与可观测性（15）
5. 文档与回滚准备（10）

---

## 10. 交付证据包标准目录

建议目录：`reports/acceptance/{phase}/`

1. `01-change-log.md`
2. `02-self-test-report.md`
3. `03-api-contract-diff.md`
4. `04-test-run-raw.log`
5. `05-defect-list.csv`
6. `06-risk-register.md`
7. `07-rollback-plan.md`
8. `08-signoff.md`

---

## 11. 推荐验收命令基线

```bash
# 1) 核心回归（按变更裁剪）
pytest -q tests/integration

# 2) E2E 关键路径
pytest -q tests/playwright/tests/smoke/test_critical_paths.py
pytest -q tests/playwright/tests/uat/test_user_journeys.py -v

# 3) API/路由规范
pytest -q tests/uat/test_api_naming_compliance.py tests/uat/test_route_baseline_consistency.py
```

如涉及新增守护测试，必须补跑对应 guardrail。

---

## 12. 签字模板

1. 外包负责人：已按范围交付并完成自测。  
2. 内部技术验收：代码与架构风险可控。  
3. QA：测试结果与缺陷状态符合门禁。  
4. 业务 Owner：验收结论（通过/有条件通过/不通过）。

---

## 13. 与现有文档关系

1. 测试总策略：`docs/testing/master-test-strategy-2026-02.md`
2. 追踪矩阵：`docs/testing/requirements-traceability-matrix-2026-02.md`
3. 本轮开发路线图：`docs/plans/post-v34-followup-roadmap-2026-02-26.md`
4. 缺陷模板：`docs/testing/bug-report-template.md`
5. 测试结果模板：`docs/testing/test-results-template.md`

