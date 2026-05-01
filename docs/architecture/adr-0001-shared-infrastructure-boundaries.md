# ADR-0001: shared.infrastructure 边界判定

## 状态

已接受

## 日期

2026-05-02

## 背景

项目历史上把多类能力都沉积到了 `shared.infrastructure.*`，其中混杂了：

- 纯技术组件
  - 如 `htmx`、`crypto`、`sdk_bridge`、`tushare_client`
- 运行时边界服务
  - 如 `alert_service`、`notification_service`、`cache_service`
- 带业务语义或配置语义的实现
  - 如 `config_helper`、`models`、`asset_analysis_registry`

这导致 `shared.infrastructure.*` 在评审时长期处于灰区：

- 有人把它当“通用技术库”
- 有人把它当“跨 app 的临时逃生门”

结果是四层架构虽然写着清楚，实际边界却不断回退。

## 决策

### 1. `shared/` 的唯一定位

`shared/` 只承载**纯技术性、无业务归属**的能力。

允许保留在 `shared/` 的内容：

- 与具体业务模块无关的技术 helper
- 可被多个 app 复用的纯适配工具
- 不包含业务默认值、业务配置语义、业务 ORM、业务规则的基础设施

明确禁止继续留在 `shared/` 的内容：

- Django ORM Model
- 业务配置真源
- 业务默认规则
- 业务注册表
- 依赖具体业务 app 才有意义的“通用层”

### 2. Application 层对 `shared.infrastructure.*` 的规则

Application 层**默认不允许**直接依赖 `shared.infrastructure.*`。

例外仅限：

- 已被明确认定为“纯技术边界服务”的共享组件
- 且当前没有更合适的 owning app facade / `core.integration.*` bridge

但这些例外必须满足：

- 不能承载业务规则
- 不能承载业务配置真源
- 不能绕过 owning app 的 repository / facade / gateway

换句话说：

- `shared.infrastructure.htmx` 这类 UI 技术组件可留在 Interface 使用
- `shared.infrastructure.config_helper`、`shared.infrastructure.models`、`shared.infrastructure.asset_analysis_registry` 这类带业务归属语义的组件，必须迁回 owning app 或专门的 integration/config 模块

### 3. admin 与 app-root `models.py` shim 的规则

app-root `models.py` 仅被定义为 Django bootstrap shim。

允许：

- `admin.py` 导入 `apps.<app>.models`
- Django 自身通过 app 配置发现模型

不允许：

- Application / Interface / Management / Domain 把 `apps.<app>.models` 当公共入口使用

### 4. 事务和动态模型解析的归属

以下能力不属于 Application：

- `transaction.atomic`
- `django_apps.get_model`
- `apps.get_model`

这些能力应留在：

- Infrastructure
- Admin
- Migrations
- 明确的 Django integration boundary

## 后果

### 正面

- 评审标准从“看人理解”变成“有明确边界”
- 可以把 `shared` 的存量债按类型拆解，而不是反复口头争论
- 能为后续 CI 规则提供明确依据

### 代价

- 部分当前仍在运行的 `shared.infrastructure.*` 调用会被标记为治理债
- 后续需要做一次 `shared` 专项搬迁
- 个别旧模块需要补 facade / gateway / integration bridge

## 执行要求

1. 新增代码必须遵守本 ADR。
2. 现存 `shared.infrastructure.*` 调用按专项清单分批迁移。
3. 新的架构规则与 CI 门禁以本 ADR 为解释基准。
