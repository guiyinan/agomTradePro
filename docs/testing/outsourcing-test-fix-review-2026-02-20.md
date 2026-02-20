# 外包测试与修复批次审查报告（2026-02-20）

## 1. 审查范围

- 审查时间：2026-02-20
- 分支：`main`
- 重点提交：
  - `2f8d4bb` Fix full regression blockers after UI/UX merge
  - `a854a03` Fix template regressions and runtime UI/API errors
  - `d3302ed` 修正首页 regime css
  - `9653106` 2026年2月20日glm更新（大整合提交）

## 2. 结论摘要

- 结论：本轮修复整体可接受，未发现立即阻断上线的问题。
- 风险等级：`低-中`（主要来自少量健壮性细节和提交粒度过大）
- 建议：允许进入下一轮联调/灰度，但需补充 1 个防御性修复和 1 项流程整改。

## 3. 发现项（按严重级别）

### 3.1 中等：提交粒度过大，回滚与追责成本高

- 位置：提交 `9653106`
- 现象：单个提交混入模块重构、迁移、模板、路由、文档等多类变更。
- 风险：
  - 回滚时容易误伤无关修复。
  - 问题归因困难，影响后续外包质量管理与验收。
- 建议：
  - 外包后续提交按“单目标”拆分：`bugfix`、`refactor`、`docs`、`migration` 分开。
  - 每个提交附最小验证清单（通过的命令和结果摘要）。

### 3.2 低：Regime 页面数据解析缺少防御性处理

- 位置：`apps/regime/interface/views.py:64`、`apps/regime/interface/views.py:65`
- 现象：`float(item.get('value', 0))` 直接转换。
- 风险：当上游返回 `None`、空字符串或非法值时，可能触发异常并进入错误分支。
- 建议：
  - 在转换前做 `None/""` 归零或 `try/except ValueError, TypeError` 保护。
  - 增加对应单元测试，覆盖脏数据场景。

## 4. 核验证据

### 4.1 框架检查

- 命令：`python manage.py check`
- 结果：`System check identified no issues (0 silenced).`

### 4.2 回归测试（关键集）

- 命令：
  - `pytest -q tests/unit/test_alpha_trigger_services.py tests/unit/test_beta_gate_entities.py tests/unit/test_beta_gate_services.py tests/unit/test_decision_rhythm_services.py tests/unit/test_currency_conversion.py tests/unit/test_volatility_control.py`
  - `pytest -q tests/unit/test_equity_config_loader.py tests/unit/test_secrets_registry.py tests/unit/test_shared_htmx.py`
- 结果：
  - 第一组：`67 passed`
  - 第二组：`31 passed`

### 4.3 路由与模板联动抽查

- 已确认：
  - `core/templates/dashboard/index.html` 中改动后的 API 路径与 `apps/dashboard/interface/urls.py` 一致。
  - `apps/audit/templates/audit/indicator_performance.html` 中 URL 名称 `audit:threshold_validation` 与 `apps/audit/interface/urls.py` 一致。
  - `core/templates/regime/dashboard.html` 的 `POST /macro/api/quick-sync/` 与 `apps/macro/interface/urls.py` 一致。

## 5. 外包批次验收建议（后续执行标准）

1. 提交规范：单提交只做一类变更，提交信息写清“问题-修复-验证”。
2. 测试门禁：至少附 `manage.py check` + 对应模块单测结果。
3. 回归门禁：涉及模板和路由改动时，必须附 URL 对照表。
4. 健壮性门禁：涉及外部数据解析时，必须包含空值/非法值处理和测试。

## 6. 当前判定

- 判定：`通过（附整改项）`
- 必改项：
  - 补齐 `apps/regime/interface/views.py` 的数值解析防御性处理。
  - 下一轮外包开始执行“提交粒度与验证清单”约束。
