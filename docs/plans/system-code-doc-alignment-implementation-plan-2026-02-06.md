# 系统代码巡检与文档对齐实施方案（2026-02-06）

## 1. 背景与目标

本方案基于 2026-02-06 的代码巡检结果，目标是把“代码事实”和“文档声明”对齐，降低多 Agent 并行开发下的认知偏差与变更冲突。

范围：
- `apps/` 模块结构与四层架构一致性
- 核心入口文档准确性（版本、模块数、完成度、测试状态）
- 文档链接有效性

---

## 2. 巡检结论（代码事实）

### 2.1 模块与分层

- 业务模块数：`27`（不含 `shared`）
- 四层目录完整：`26/27`
- 唯一结构例外：`apps/ai_provider` 缺少 `application/` 目录

### 2.2 系统健康

- `python manage.py check`：通过（0 issues）
- Domain 层禁用依赖扫描：
  - 在 `apps/**/domain/*.py` 中未发现 `django/pandas/numpy/requests/rest_framework` 导入

### 2.3 文档主要问题类型

- 状态冲突：不同文档中的版本号、完成度、测试覆盖数字互相冲突
- 结构过期：部分文档仍写“19 模块/28 模块”或“dashboard/events 不完整”
- 链接失效：存在跨目录相对路径错误、历史文件迁移后未更新

---

## 3. 本次已完成修复

### 3.0 执行状态

- Phase A：已完成（文档口径与自动校验状态已补齐）
- Phase B：已完成（`docs/**/*.md` 链接校验通过，失效链接 0）

### 3.1 已更新文档

- `docs/INDEX.md`
  - 修正失效链接（`alpha-quickstart`、Regime 文档入口）
  - 统一项目状态表述为“持续迭代”
  - 根据代码扫描更新四层完整性描述（`26/27`，`ai_provider` 为例外）

- `docs/development/quick-reference.md`
  - 移除易过期的硬编码完成度/测试数量描述
  - 明确 API 以运行时 OpenAPI（`/api/schema/`、`/api/docs/`）为准

- `docs/architecture/SYSTEM_OVERVIEW.md`
  - 修正文档头部与摘要中的版本/模块数/测试描述冲突
  - 统一模块总数为 `27`

- `docs/development/module-dependency-graph.md`
  - 将“19 模块”更新为“27 模块”口径
  - 增补决策流与 Alpha 相关模块项
  - 标注 `ai_provider` 的分层例外

---

## 4. 下一阶段实施计划

### Phase A（1-2 天）：文档基线固化

目标：所有入口文档采用统一口径，避免继续产生冲突。

任务：
- 在 `docs/INDEX.md` 增加“文档口径来源”小节（代码扫描日期、扫描脚本位置）
- 给 `SYSTEM_OVERVIEW.md` 与 `module-dependency-graph.md` 加“自动校验状态”标识
- 将“完成度百分比”改为里程碑状态（避免数字漂移）

验收标准：
- 入口文档不再出现冲突版本号/模块总数
- 文档中的模块口径与 `core/settings/base.py` 一致

### Phase B（2-3 天）：文档链接治理

目标：清理高频访问文档中的失效链接。

任务：
- 优先修复以下目录：`docs/INDEX.md`、`docs/architecture/`、`docs/development/`、`docs/business/`
- 将绝对站内路由（如 `/api/docs/`）与文件链接语义区分
- 输出一份 `docs/testing/doc-link-check-report.md`

验收标准：
- 目标目录 Markdown 链接可用率达到 100%
- 链接检查报告可复现

### Phase C（2-4 天）：自动化守护

目标：把文档一致性检查纳入日常开发流程。

任务：
- 新增脚本：`scripts/check_docs_consistency.ps1`
  - 检查模块总数与四层完整性
  - 检查关键文档中的版本/模块口径
  - 检查 Markdown 相对链接有效性
- 在 CI 中加入文档一致性检查（失败即阻断）

验收标准：
- PR 阶段可自动识别文档与代码偏差
- 团队可在本地一键执行巡检脚本

---

## 5. 风险与应对

- 风险：历史文档体量大，完全一次性修复成本高
- 应对：先治理入口文档与高频路径，再分批清理长文档

- 风险：多人并行更新导致文档回退
- 应对：引入“文档一致性检查”作为 PR 必检项

- 风险：完成度数字难以长期维护
- 应对：使用“里程碑状态 + 验证命令输出”替代固定百分比

---

## 6. 建议执行顺序

1. 先落地 Phase A，建立统一口径
2. 再推进 Phase B，清理链接与导航
3. 最后用 Phase C 自动化固化流程
