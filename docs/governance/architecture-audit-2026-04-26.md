# Architecture Audit Report — 2026-04-26e

> **审计日期**: 2026-04-26
> **系统版本**: AgomTradePro 0.7.0
> **审计轮次**: 第 6 轮（本地整改后）
> **审计员**: Codex
> **说明**: 本报告反映当前工作区状态，包含尚未提交的整改结果。

---

## 总览

| 类别 | 状态 | 数量 | 严重度 |
|------|------|------|--------|
| Application → 跨 App Infrastructure 导入 | **PASS** | 0 | — |
| Domain 层违规（django/pandas/numpy/requests） | **PASS** | 0 | — |
| shared/ 反向依赖（依赖 apps/） | **PASS** | 0 | — |
| Interface 非 admin 违规 | **PASS** | 0 | — |
| `.objects.` 直接 ORM 在 Application | **PASS** | 0 | — |
| `import requests` 在 Application | **PASS** | 0 | — |
| `from django.db.models` 在 Application | **PASS** | 0 | — |
| naive `datetime.now()` | **PASS** | 0 | — |
| Application → 同 App Infrastructure 导入 | **DEBT** | 91 | 中 |
| Infrastructure 层循环依赖 | **PASS** | 0 对 | — |
| admin.py 直接导入 infrastructure.models / event_store | **PASS** | 0 | — |
| 跨 App Infrastructure 耦合 | **DEBT** | 62 条边 | 低 |

---

## 历史趋势

| 指标 | 第 1 轮 (04-25) | 第 2 轮 (04-26a) | 第 3 轮 (04-26b) | 第 4 轮 (04-26c) | 第 5 轮 (04-26d) | 第 6 轮 (04-26e) |
|------|-----------------|-------------------|-------------------|-------------------|-------------------|-------------------|
| Application → Infrastructure 违规行 | 270 | 231 | 175 | 167 | 127 | **91** |
| 跨 App Application → Infrastructure 导入 | 92 | 92 | 0 | 0 | 0 | **0** |
| 同 App Application → Infrastructure 导入 | 未统计 | 未统计 | 175 | 167 | 127 | **91** |
| `import requests` 在 Application | 1 | 0 | 0 | 0 | 0 | **0** |
| `from django.db.models` 在 Application | 1 | 1 | 0 | 0 | 0 | **0** |
| naive `datetime.now()` | 5 | 0 | 0 | 0 | 0 | **0** |
| Infrastructure 循环依赖 | 0 | 1 对 | 1 对 | 0 | 0 | **0** |
| admin.py 直接导入 infrastructure | 20 | 20 | 8 | 0 | 0 | **0** |

---

## 本轮累计已完成整改

### 1. 断开 `macro -> data_center.infrastructure`

已移除 `macro` 对 `apps.data_center.infrastructure.*` 的直接依赖：

- `apps/macro/infrastructure/adapters/akshare_adapter.py`
- `apps/macro/infrastructure/adapters.py`
- `apps/macro/infrastructure/adapters/failover_adapter.py`
- `apps/macro/infrastructure/secrets_loader.py`

采取的做法：

- 将 AKShare SDK bridge 下沉到 `shared/infrastructure/sdk_bridge.py`
- 通过 `apps.data_center.application.repository_provider` 暴露只读配置访问函数
- `macro.infrastructure` 不再直接 import `data_center.infrastructure`

结果：

- `check_module_cycles.py` 当前结果为 `Bidirectional pairs: 0`, `Cycle components: 0`

### 2. 清理 admin 层直接 infrastructure 导入

已完成以下统一整改：

- 所有 `admin.py` 不再直接导入 `infrastructure.models`
- `events/interface/admin.py` 不再直接导入 `infrastructure.event_store`
- `task_monitor/infrastructure/admin.py` 已迁移为 `task_monitor/interface/admin.py`
- 为缺失模块补充了 app-root shim：
  - `apps/ai_capability/models.py`
  - `apps/alpha_trigger/models.py`
  - `apps/audit/models.py`
  - `apps/backtest/models.py`
  - `apps/beta_gate/models.py`
  - `apps/data_center/models.py`
  - `apps/decision_rhythm/models.py`
  - `apps/signal/models.py`
  - `apps/simulated_trading/models.py`
  - `apps/terminal/models.py`
  - `apps/events/event_store.py`

结果：

- `admin.py` 中直接 `infrastructure.models` / `infrastructure.event_store` 导入数量已降为 `0`

### 3. 为同 App Application → Infrastructure 建立稳定审计规则

已新增 audit 规则：

- `apps_application_no_same_app_infrastructure_imports_except_repository_provider`

规则口径：

- Application 层禁止直接导入本 App `infrastructure.*`
- `application/repository_provider.py` 明确豁免，作为 composition root

### 4. 已清零的模块

以下模块的同 App Application → Infrastructure 违规已清零：

- `ai_provider`
- `events`
- `prompt`
- `account`
- `ai_capability`
- `audit`
- `backtest`
- `task_monitor`

### 5. 已显著压降的模块

以下模块已完成主要收敛，但仍有少量尾项：

- `regime`: `11 -> 2`
- `signal`: `10 -> 0`（直接 infra import 已清，剩余审计不在 signal）

### 6. 本轮采取的主要收敛手法

- 为 `application` 增补或扩展 `repository_provider.py`
- 将 `providers/adapters/services` 访问收口到 app-level composition root
- 将重型 concrete service 改为 lazy factory，避免 Django 启动期循环导入
- 保持业务流程不变，只调整依赖进入点

---

## 当前剩余核心问题

## 问题 1：Application 层同 App Infrastructure 导入（91 处）

**严重度**: 中
**状态**: 遗留技术债，已被稳定审计

### 按模块统计（当前）

| 模块 | 违规数 |
|------|--------|
| alpha | 12 |
| equity | 12 |
| data_center | 8 |
| dashboard | 6 |
| simulated_trading | 6 |
| pulse | 5 |
| macro | 4 |
| rotation | 4 |
| agent_runtime | 3 |
| fund | 3 |
| policy | 3 |
| sector | 3 |
| strategy | 3 |
| asset_analysis | 2 |
| decision_rhythm | 2 |
| hedge | 2 |
| regime | 2 |
| sentiment | 2 |
| setup_wizard | 2 |
| share | 2 |
| alpha_trigger | 1 |
| factor | 1 |
| filter | 1 |
| terminal | 1 |

### 当前最重的文件

| 文件 | 违规数 |
|------|--------|
| `apps/alpha/application/tasks.py` | 5 |
| `apps/dashboard/application/queries.py` | 5 |
| `apps/alpha/application/services.py` | 4 |
| `apps/equity/application/use_cases.py` | 4 |
| `apps/data_center/application/interface_services.py` | 3 |
| `apps/data_center/application/price_service.py` | 3 |
| `apps/policy/application/use_cases.py` | 3 |
| `apps/pulse/application/use_cases.py` | 3 |
| `apps/strategy/application/execution_gateway.py` | 3 |

### 模式判断

当前 91 处主要集中在四类：

- `infrastructure.providers`
- `infrastructure.adapters`
- `infrastructure.services`
- `infrastructure.*` 的内部 runtime helper

这说明下一轮整改仍然应按“工厂入口 / facade”批量收敛，不适合逐行散修。

---

## 问题 2：跨 App Infrastructure 耦合（62 条边）

**严重度**: 低
**状态**: 可优化，但不应抢在同 App 技术债前面

说明：

- 真正危险的跨 App Application → Infrastructure 已经清零
- 当前剩余是 Infra/Integration 层面的结构耦合

---

## 下一轮整改清单

### P1：清理 `alpha`、`equity`、`data_center`

原因：

- 三者已成为最高计数模块（12 / 12 / 8）
- `alpha/tasks.py`、`alpha/services.py`、`equity/use_cases.py`、`data_center/price_service.py` 都是集中导入点

建议落点：

- `alpha/application/tasks.py`
- `alpha/application/services.py`
- `equity/application/use_cases.py`
- `data_center/application/interface_services.py`
- `data_center/application/price_service.py`
- `data_center/application/registry_factory.py`

### P2：清理 `dashboard`、`simulated_trading`、`pulse`

原因：

- 都是中等规模热点（6 / 6 / 5）
- 用户面影响较高，适合在 P1 后继续收口

### P3：清理 `macro`、`rotation`、`agent_runtime`、`policy`

原因：

- 数量不大，但能进一步把总数从两位数早期压低
- 适合按模块批量扫尾

---

## 验证基线

本报告对应的当前命令结果：

```bash
python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text
python -m pytest tests/guardrails/test_architecture_boundaries.py tests/guardrails/test_architecture_tooling.py -q
python manage.py check
python -m pytest tests/api/test_account_api_edges.py tests/api/test_account_profile_api_edges.py tests/api/test_events_api_edges.py tests/api/test_prompt_api_edges.py -q
python -m pytest tests/api/test_ai_capability_api_edges.py tests/unit/test_ai_capability -q
python -m pytest tests/api/test_audit_api_edges.py tests/api/test_signal_api_edges.py tests/unit/test_signal_tasks.py tests/unit/test_audit_failure_counter.py tests/unit/test_audit_permissions.py tests/unit/application/audit -q
python -m pytest tests/api/test_regime_action_api.py tests/api/test_regime_api_edges.py tests/api/test_regime_navigator_api.py tests/unit/test_regime_orchestration.py tests/unit/core/test_current_regime.py -q
python -m pytest tests/api/test_backtest_api_edges.py tests/unit/test_backtest_data_center_adapter.py tests/unit/domain/test_backtest_services.py -q
python -m pytest tests/api/test_task_monitor_api.py tests/unit/test_task_monitor.py -q
```

当前状态：

- boundary violations: `0`
- same-app audit violations: `91`
- module cycles: `0`
- admin direct infra imports: `0`

---

## 结论

当前项目的“高风险跨 App 越层”已经压住了，`macro/data_center` 循环已解除，`admin` 这条线也已清干净。剩下最该做的事情，是沿着现有 audit 规则，按模块批量消化剩余 `91` 处同 App Application → Infrastructure 技术债。

下一轮应直接从 `alpha`、`equity`、`data_center` 三组开始。
