# shared 残留清理专项（2026-05-02）

## 目标

一次性把 `shared/` 从“历史杂物间”收敛回“纯技术组件层”。

## 本轮进度

### 已完成（Batch 1 第一段）

- 删除 `shared.infrastructure.models`
- 删除 `shared.infrastructure.config_helper`
- 删除 `shared.infrastructure.config_loader`
- 删除 `shared.infrastructure.admin`
- `shared/admin.py` 改为空边界，不再把 `shared` 当业务模型宿主
- 业务代码改回 owning app model / regime-owned config helper

### 已完成（Batch 2 第一段）

- 删除 `shared.infrastructure.asset_analysis_registry`
- 新增 `core.integration.asset_analysis_market_registry`
- `asset_analysis / equity / fund / rotation` 全部改用 core runtime integration registry
- 审计规则禁止再导入 `shared.infrastructure.asset_analysis_registry`
- `shared.infrastructure.fixtures.system_config` 迁到 `apps.regime.infrastructure.fixtures.system_config`

这意味着：

- `shared` 不再承担业务模型兼容层
- `RiskParameterConfigModel` 配置读取正式回归 `apps/regime/infrastructure/config_helper.py`
- `shared` 的“业务捷径”路径已经从代码面切断

## 为什么这项债优先级高

当前 `shared.infrastructure.*` 同时承担了：

- 技术工具
- 配置读取
- 业务注册表
- 运行时通知
- 历史 ORM 残留

这会持续制造三类问题：

1. Application / Domain 容易把 `shared` 当作绕过 owning app 边界的捷径。
2. CI 很难直接判断“这个 shared import 到底是技术组件还是业务逃生门”。
3. 文档与实现长期不一致，导致整改后又回归。

## 现状分组

### A. 纯技术组件，可保留在 shared

候选示例：

- `shared.infrastructure.htmx`
- `shared.infrastructure.crypto`
- `shared.infrastructure.sdk_bridge`
- `shared.infrastructure.tushare_client`
- `shared.infrastructure.resilience`

处理策略：

- 保留
- 补注释/文档，明确“技术组件”身份
- 不允许再混入业务配置或业务语义

### B. 运行时边界服务，优先迁到 `core/integration/*` 或 owning app facade

候选示例：

- `shared.infrastructure.alert_service`
- `shared.infrastructure.notification_service`
- `shared.infrastructure.cache_service`
- `shared.infrastructure.metrics`

处理策略：

- 若是系统级 runtime bridge，迁到 `core/integration/*`
- 若主要服务单一业务域，迁回 owning app

### C. 业务语义强、必须迁回 owning app 的组件

候选示例：

- `shared.infrastructure.config_helper`
- `shared.infrastructure.models`
- `shared.infrastructure.asset_analysis_registry`

处理策略：

- 明确 owning app
- 在 owning app 暴露 application facade / provider；跨 app 运行时注册表则迁到 `core/integration/*`
- 删掉 shared 版本或保留短期兼容壳并标注退役计划

## 建议批次

### Batch 1

- `shared.infrastructure.models`
- `shared.infrastructure.config_helper`

原因：

- 这两类最容易直接破坏四层架构
- 对 review 和 CI 造成的歧义最大

### Batch 2

- `shared.infrastructure.metrics`
- `shared.infrastructure.cache_service`

原因：

- 除 `asset_analysis_registry` 已完成迁移外，这些组件已经跨越多个业务 app
- 若不收口，很容易继续演化成隐性平台层

### Batch 3

- `shared.infrastructure.notification_service`
- `shared.infrastructure.alert_service`

原因：

- 需要先判断它们属于系统级 runtime，还是某个业务域的侧向能力

## 本轮不直接做的事

- 不在本次提交里全面搬迁 `shared` 存量
- 不强上会让现有大量模块立刻红掉的全量规则

原因不是这些问题不重要，而是需要先有 ADR 和专项清单，再按批次推进，否则容易半途引入更大的回归面。

## 完成标准

1. `shared/` 不再包含业务 ORM、业务配置真源、业务注册表。
2. Application / Domain 不再把 `shared.infrastructure.*` 当业务捷径。
3. 对 `shared` 的允许边界可以被 CI 规则直接表达。
