# 模块依赖回归整改说明（2026-05-02）

## 背景

2026-05-02 复核发现两类依赖回归：

1. `regime -> macro`
   - 虽未重新形成双向环，但 `regime` 重新直接引用了 `macro` 的 domain entity 与 Celery task。
   - 这违反了“跨 App 调用优先使用 Protocol / Facade / Gateway”的约束。
2. `account -> decision_rhythm -> alpha -> account`
   - `check_module_cycles.py` 检出 1 个三节点 cycle component：`account, alpha, decision_rhythm`。

## 本次整改

### 1. 清除 `regime -> macro` 静态依赖

- `apps/regime/domain/protocols.py`
  - 新增 regime 自有的只读读模型：`PeriodType`、`MacroIndicator`
- `apps/regime/infrastructure/macro_data_provider.py`
  - 不再导入 `apps.macro.domain.entities`
  - Data Center 适配器统一返回 regime 自有读模型
- `apps/regime/application/use_cases.py`
  - 删除对 `RegimeSensitivity` 的无效导入
  - 删除“为了补前值而临时构造 macro 实体”的做法，直接补值
- `apps/regime/infrastructure/macro_sync_gateway.py`
  - 改为按任务名构造 Celery signature
  - 不再直接导入 `apps.macro.application.tasks.sync_macro_data`

### 2. 清除 `alpha -> account` 静态依赖

- `apps/alpha/application/services.py`
  - 固定 provider 与 qlib runtime 配置统一通过 `core.integration.runtime_settings` 获取
- `apps/alpha/application/ops_services.py`
  - 移除对 `apps.account.application.config_summary_service` 的直接依赖
  - Alpha 运维页、Qlib 数据运维页统一通过 runtime settings bridge 读取配置

这一步直接打断了 `account -> decision_rhythm -> alpha -> account` 环。

### 3. 降低 `account -> decision_rhythm` 管理命令耦合

- `apps/account/management/commands/bootstrap_cold_start.py`
  - 删除对 `DecisionModelParamConfigModel` 的静态 import
  - 改为通过 Django app registry 按需取 model 做存在性检查

### 4. 顺手修复现存架构审计点

- `apps/regime/application/repository_provider.py`
  - `RegimeConfigRepository` 改从 `infrastructure.providers` 暴露
  - 清除 `Application -> infrastructure.repositories` 审计告警

## 验证结果

### 依赖图

执行：

```bash
python scripts/check_module_cycles.py --allowlist-file governance/module_cycle_allowlist.json --fail-on-cycles --format text
```

结果：

- `Bidirectional pairs: 0`
- `Cycle components: 0`

### 架构护栏

执行：

```bash
python scripts/verify_architecture.py --rules-file governance/architecture_rules.json --format text --include-audit
```

结果：

- `Boundary violations: 0`
- `Audit violations: 0`

### 相关测试

执行通过：

```bash
pytest tests/unit/test_alpha_comparability.py apps/alpha/tests/test_ops_interface_contracts.py tests/unit/regime/test_config_threshold_regression.py tests/guardrails/test_architecture_boundaries.py tests/guardrails/test_architecture_tooling.py -q
pytest tests/unit/test_regime_data_center_macro_provider.py tests/unit/test_regime_orchestration.py tests/unit/core/test_runtime_settings.py -q
```

合计：`26 passed`

## 为什么已有 CI 和开发规范，问题还是会回来

### 1. 现有 cycle CI 只覆盖“成环”，不覆盖“单向违规依赖”

这次 `regime -> macro` 不是环，所以 `check_module_cycles.py` 不会报警。
但它依然是架构回退，因为跨 App 边被重新写回来了。

### 2. lazy import / gateway 容易制造“已经解耦”的错觉

把 import 挪进函数体，确实能降低运行时循环导入崩溃风险；
但对模块依赖图而言，边仍然存在。
如果 review 只看“会不会炸”，不看“依赖边还在不在”，回归就会混进来。

### 3. 规则是分散的，开发时优先级容易被功能压力覆盖

项目里已经有 AGENTS、治理文档、guardrail 脚本，但开发者实际做局部修复时，
最容易优先满足的是“先让功能能跑、测试能过”，而不是“依赖图必须继续收敛”。

### 4. 当前 CI 对“允许哪些跨 App 边”缺少白名单式治理

现在 CI 能很好抓住：

- layer 违规
- ORM 越界
- cycle component

但还不能表达：

- `regime` 是否允许直接 import `macro.domain.entities`
- `alpha` 是否允许再出现 `account` 级依赖

也就是说，CI 更擅长抓“明显错误”，对“拓扑回退”还不够严格。

## 后续建议

1. 在 `check_module_cycles.py` 之外，再加一层“app 级依赖白名单/黑名单”审计。
2. 对已声明为“基础模块/被依赖模块”的 app（如 `macro`、`regime`、`alpha`）增加定向拓扑断言测试。
3. Code review 时把“删除静态边”作为验收项，明确 lazy import 不等于解耦完成。
4. 对历史已清零的整改项建立回归测试，而不是只保留一次性整改报告。
