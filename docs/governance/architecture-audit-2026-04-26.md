# Architecture Audit Report — 2026-04-26g

> **审计日期**: 2026-04-26
> **系统版本**: AgomTradePro 0.7.0
> **审计轮次**: 第 8 轮（本地整改后）
> **审计员**: Codex
> **说明**: 本报告反映当前工作区状态，包含尚未提交的整改结果。

---

## 总览

| 类别 | 状态 | 数量 | 严重度 |
|------|------|------|--------|
| Application → 跨 App Infrastructure 导入 | **PASS** | 0 | — |
| Application → 同 App Infrastructure 导入 | **PASS** | 0 | — |
| Domain 层违规（django/pandas/numpy/requests） | **PASS** | 0 | — |
| shared/ 反向依赖（依赖 apps/） | **PASS** | 0 | — |
| Interface 非 admin 违规 | **PASS** | 0 | — |
| `.objects.` 直接 ORM 在 Application | **PASS** | 0 | — |
| `import requests` 在 Application | **PASS** | 0 | — |
| `from django.db.models` 在 Application | **PASS** | 0 | — |
| naive `datetime.now()` | **PASS** | 0 | — |
| Infrastructure 层循环依赖 | **PASS** | 0 对 | — |
| admin.py 直接导入 infrastructure.models / event_store | **PASS** | 0 | — |
| 跨 App Infrastructure 耦合 | **DEBT** | 62 条边 | 低 |

---

## 历史趋势

| 指标 | 第 1 轮 | 第 2 轮 | 第 3 轮 | 第 4 轮 | 第 5 轮 | 第 6 轮 | 第 7 轮 | 第 8 轮 |
|------|--------|--------|--------|--------|--------|--------|--------|--------|
| Application → Infrastructure 违规行 | 270 | 231 | 175 | 167 | 127 | 91 | 68 | **0** |
| 跨 App Application → Infrastructure 导入 | 92 | 92 | 0 | 0 | 0 | 0 | 0 | **0** |
| 同 App Application → Infrastructure 导入 | 未统计 | 未统计 | 175 | 167 | 127 | 91 | 68 | **0** |
| admin.py 直接导入 infrastructure | 20 | 20 | 8 | 0 | 0 | 0 | 0 | **0** |
| Infrastructure 循环依赖 | 0 | 1 对 | 1 对 | 0 | 0 | 0 | 0 | **0** |

补充压降节点：

- `68 -> 44`：清 `alpha`、`equity`
- `44 -> 33`：清 `dashboard`、`pulse`
- `33 -> 27`：清 `simulated_trading`
- `27 -> 19`：清 `macro`、`rotation`
- `19 -> 12`：清 `sentiment`、`setup_wizard`、`share`、`terminal`
- `12 -> 0`：清 `agent_runtime`、`alpha_trigger`、`asset_analysis`、`decision_rhythm`、`factor`、`filter`、`hedge`、`regime`

---

## 本轮累计已完成整改

### 1. 护栏与基线

- 跨 App `application -> infrastructure` 已清零并由 boundary 规则硬性阻断
- 同 App `application -> infrastructure` 已清零
- `verify_architecture --include-audit` 当前 `Audit violations = 0`
- `module cycles = 0`
- `admin direct infra imports = 0`

### 2. 主要整改手法

- 为各 App 的 `application` 增补或扩展 `repository_provider.py`
- 将 `providers/adapters/services/orm_handles` 的 concrete access 统一收口到 application composition root
- 对测试依赖的 patch surface 保持兼容，必要时将 provider/repository 改为 lazy import
- 将历史上的 inline / delayed infrastructure import 一并收掉，避免绕过审计

### 3. 已清零模块

- `account`
- `agent_runtime`
- `ai_capability`
- `ai_provider`
- `alpha`
- `alpha_trigger`
- `asset_analysis`
- `audit`
- `backtest`
- `dashboard`
- `data_center`
- `decision_rhythm`
- `equity`
- `events`
- `factor`
- `filter`
- `fund`
- `hedge`
- `macro`
- `policy`
- `prompt`
- `pulse`
- `regime`
- `rotation`
- `sector`
- `sentiment`
- `setup_wizard`
- `share`
- `signal`
- `simulated_trading`
- `strategy`
- `task_monitor`
- `terminal`

---

## 当前结论

截至当前工作区，**Application 层 DDD 边界审计已清零**：

- 跨 App `application -> infrastructure`: `0`
- 同 App `application -> infrastructure`: `0`
- `verify_architecture --include-audit`: `0`
- module cycles: `0`
- admin direct infra imports: `0`

剩余仍然算技术债的是 **跨 App Infrastructure 耦合图本身**，但它已经不再表现为 Application 越层导入，而是后续可以按领域边界逐步抽 facade / query service 的结构优化项。

---

## 建议后续动作

1. 将当前工作区整改提交为独立 commit，保留清晰审计节点。
2. 把 `verify_architecture --include-audit` 结果纳入常规 CI 输出，当前已适合转成“出现任何回流即失败”。
3. 下一阶段如果继续做严格 DDD，不再盯 `application -> infrastructure`，而应转向：
   - 跨 App Infrastructure hub 解耦
   - `shared/` 技术组件边界稳定化
   - `data_center` 统一查询能力与业务模块 facade 之间的职责划分

---

## 验证基线

本报告对应的当前命令结果：

```bash
python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text
python manage.py check
python -m pytest tests/guardrails/test_architecture_boundaries.py tests/guardrails/test_architecture_tooling.py -q
python -m pytest tests/api/test_alpha_api_edges.py tests/api/test_equity_api_edges.py -q
python -m pytest tests/api/test_dashboard_api_edges.py tests/api/test_pulse_api.py -q
python -m pytest tests/api/test_simulated_trading_api_edges.py -q
python -m pytest tests/api/test_macro_api_edges.py tests/api/test_macro_filter_compat_api.py tests/api/test_rotation_api_edges.py -q
python -m pytest tests/api/test_sentiment_api_edges.py tests/api/test_share_api_edges.py tests/api/test_terminal_api_edges.py -q
python -m pytest tests/api/test_regime_action_api.py tests/api/test_regime_api_edges.py tests/api/test_regime_navigator_api.py tests/api/test_decision_rhythm_api_edges.py tests/api/test_hedge_api.py tests/api/test_factor_api_edges.py tests/api/test_filter_api_edges.py tests/api/test_asset_analysis_pool_api_edges.py tests/api/test_alpha_trigger_api_edges.py -q
```

当前状态：

- boundary violations: `0`
- audit violations: `0`
- module cycles: `0`
- admin direct infra imports: `0`
