# Account Portfolio API 架构整改（2026-05-01）

> 日期: 2026-05-01  
> 范围: `apps/account/interface/portfolio_api_views.py`, `apps/account/application/portfolio_api_services.py`, `apps/account/infrastructure/repositories.py`

## 背景

`apps/account/interface/portfolio_api_views.py` 此前把以下三类职责揉在一起：

1. 观察员访问权限判断
2. 组合与统一账本的迁移映射
3. 持仓 CRUD / 平仓 / 统计查询

结果是 Interface 层直接出现 `_default_manager.get/filter/create/delete/update_or_create/aggregate`、`get_model()` 和反向关系遍历，属于明确的四层架构越界。

## 本次改动

### 1. 新增 application service 边界

- 新增 `apps/account/application/portfolio_api_services.py`
- 统一承接：
  - 组合访问解析
  - 观察员 403 / 404 语义
  - 统一账本同步
  - 持仓创建、更新、删除、平仓
  - 组合持仓列表与统计 payload 组装

Interface 层现在只负责：

- 读取请求参数
- 调 serializer 做输入校验
- 调用 application service
- 返回 HTTP 响应与审计日志

### 2. 新增 infrastructure repository

- 在 `apps/account/infrastructure/repositories.py` 新增 `PortfolioApiRepository`

Repository 下沉了以下原先散落在 view 中的 ORM 行为：

- 组合/观察员授权查询
- portfolio ↔ unified account 映射创建与读取
- legacy position ↔ unified position 映射维护
- legacy projection upsert
- unified position 查询与删除
- position payload 构造
- portfolio statistics 聚合

### 3. 清理 interface 直连 ORM/`get_model()`

- 重写 `apps/account/interface/portfolio_api_views.py`
- 删除：
  - `django.apps.get_model()` 动态取模型
  - `_default_manager` 直查
  - `portfolio.positions.filter(...)`
  - `CapitalFlowModel` 聚合
  - 兼容迁移阶段遗留的 `perform_create` / `perform_update` 直写逻辑

### 4. 保持原有契约

本次整改保留了原接口的关键行为：

- 观察员读取允许，写操作返回 403
- 观察员授权撤销/过期仍区分 403
- 平仓后仍写入 legacy `TransactionModel`
- position list / retrieve 仍返回统一账本 payload

另外修复了一个回归风险：

- `POST /api/account/positions/` 现在先判组合权限，再做 serializer 校验
- 这样观察员创建持仓时继续返回 403，不会因为字段校验顺序变化先返回 400

## 验收

已通过：

- `python -m pytest tests/integration/test_portfolio_observer_access.py -q`
- `python -m pytest tests/integration/account/test_position_update_close_contract.py -q`

并确认：

- `apps/account/interface/portfolio_api_views.py` 不再出现 `_default_manager`
- `apps/account/interface/portfolio_api_views.py` 不再出现 `get_model()`
- `apps/account/interface/portfolio_api_views.py` 不再直接操作 `PortfolioModel/PositionModel/CapitalFlowModel`

## 后续切片补充（同日继续）

本轮继续处理了两个剩余的 Interface 热点：

### 1. `apps/account/interface/views.py`

- 注册页不再直接：
  - 查 `User` 是否存在
  - 创建 `User`
  - 判断系统是否已有管理员
  - 直接遍历 `request.user.portfolios`
- 新增 application helper 承接：
  - `username_exists()`
  - `register_user()`
  - `build_login_context()`
  - `get_active_portfolio_for_user()`

### 2. `apps/account/interface/performance_compat_views.py`

- 删除 `django_apps.get_model()` + `LedgerMigrationMapModel.objects.filter(...)`
- 改为调用 application service `get_unified_account_id_for_portfolio()`

### 3. 补充验证

额外通过：

- `python -m pytest tests/unit/test_account_admin_user_management.py -q`
- `python -m pytest tests/integration/test_account_performance_api.py -q`

## 仍需继续的整改点

这次已覆盖 `portfolio_api_views.py`、`views.py`、`performance_compat_views.py` 三个热点切片，`account` 模块仍有后续工作：

- `portfolio_api_services.py` 仍承担较多编排职责，后续可继续拆为：
  - access service
  - unified ledger sync service
  - position command/query service
