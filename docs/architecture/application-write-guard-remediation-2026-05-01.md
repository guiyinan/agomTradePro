# Application 写边界整改（2026-05-01）

> 日期: 2026-05-01  
> 范围: `apps/signal/application/invalidation_checker.py`, `apps/events/application/decision_execution_handlers.py`, `apps/simulated_trading/application/unified_position_service.py`, `apps/account/application/rbac.py`, `apps/hedge/domain/services.py`, `shared/infrastructure/correlation.py`, `apps/audit/application/health_check.py`, `apps/fund/application/use_cases.py`, `apps/sector/application/use_cases.py`, `apps/regime/application/use_cases.py`, `apps/sentiment/application/services.py`, `apps/policy/interface/page_views.py`

## 背景

除 `share` 与 `account` 的大块 Interface/Application 越界外，项目里还残留两类更隐蔽的 Application 层写边界问题：

1. Application 直接对 ORM model 调 `save()`
2. Application 直接声明 `transaction.atomic()`

这类代码量不大，但会持续破坏“四层架构下写边界只能通过 Infrastructure Repository 落库”的约束。

## 本次改动

### 1. `signal/application/invalidation_checker.py`

旧实现里，`_invalidate_signal()` 为兼容旧调用者保留了一条 ORM model 分支：

- Application 直接改 `signal.status`
- Application 直接写 `signal.invalidated_at`
- Application 直接 `signal.save()`

本次整改：

- 在 `apps/signal/domain/interfaces.py` 增加 `persist_invalidation_outcome(...)`
- 在 `apps/signal/infrastructure/repositories.py` 实现该持久化方法
- `InvalidationCheckService` 不再直接 `save()`，统一委托 repository 落库

这样即使是 legacy ORM caller，也不会再让 Application 层直接碰持久化。

### 2. `events/application/decision_execution_handlers.py`

旧实现里：

- `DecisionExecutedHandler.handle()` 直接 `transaction.atomic()`
- `DecisionExecutionFailedHandler.handle()` 直接 `transaction.atomic()`

本次整改：

- 在 `apps/events/domain/interfaces.py` 新增 `DecisionExecutionSyncRepositoryProtocol`
- 在 `apps/events/infrastructure/repositories.py` 新增 `DecisionExecutionSyncRepository`
- 事务边界挪到 Infrastructure，由该 sync repository 统一协调：
  - `DecisionRequest` 执行状态回写
  - `AlphaCandidate` 执行状态回写

Application handler 现在只负责：

- 解析事件 payload
- 调用 sync repository
- 记录日志

## 测试

已通过：

- `python -m pytest tests/unit/test_signal_invalidation_checker.py -q`
- `python -m pytest tests/unit/test_decision_execution_handlers.py -q`
- `python -m pytest tests/unit/test_fault_injection.py -q`

补充说明：

- 测试结束时出现过一次 SQLite teardown `PermissionError` 警告，但用例本身已全部通过；这属于本地测试进程释放数据库文件句柄的环境性问题，不影响本次代码路径验证。

### 3. `simulated_trading/application/unified_position_service.py`

旧实现里：

- `create_position()` 在 Application 层直接 `transaction.atomic()`
- `close_position()` 在 Application 层直接 `transaction.atomic()`

本次整改：

- 在 `apps/simulated_trading/infrastructure/repositories.py` 新增 `DjangoPositionMutationRepository`
- 将“持仓 upsert + 买入成交记录创建”收口到 `create_or_merge_position_with_buy_trade(...)`
- 将“卖出成交记录创建 + 剩余持仓更新/删除”收口到 `close_position_with_sell_trade(...)`
- `UnifiedPositionService` 只负责计算 `position_defaults` / `trade_payload`，不再声明事务边界
- `default()` 通过 `repository_provider` 注入该 mutation repository

这样之后，Application 层不再承担多表写入事务协调职责。

### 4. `account/application/rbac.py`

旧实现里：

- Application 层直接 `from django.contrib.auth.models import User`
- RBAC helper 的类型定义绑定 Django ORM 用户类

本次整改：

- 去掉 `User` / `AnonymousUser` 具体类型依赖
- 改为 `SupportsRBACUser` / `SupportsAccountProfile` 协议类型
- Interface 层仍然可以直接传 `request.user`，但 Application 只依赖最小属性集：
  - `is_authenticated`
  - `is_superuser`
  - `account_profile.rbac_role`

这一步虽然不涉及写库，但切掉了 Application 对 Django 用户 ORM 类型的直接感知。

### 5. `hedge/domain/services.py`

旧实现里：

- Domain 层直接 `from shared.infrastructure.correlation import ...`
- 实际依赖的是纯 Python 相关性算法，但挂在 Infrastructure 包名下

本次整改：

- 新增 `shared/domain/correlation.py`
- 将 `CorrelationMatrix`、`CorrelationResult`、`RollingCorrelationCalculator` 归位到 shared domain
- `shared/infrastructure/correlation.py` 改为复用 domain 算法，只保留 NumPy 优化外壳
- `apps/hedge/domain/services.py` 改为依赖 `shared.domain.correlation`

这样 `hedge` Domain 层不再跨层引用 Infrastructure 包名。

### 6. `audit/application/health_check.py`

旧实现里：

- Application 层直接 `from django.db import connection`
- Application 层直接执行 `cursor.execute("SELECT 1")`
- Application 层直接 new `DjangoAuditRepository()`

本次整改：

- 在 `apps/audit/domain/interfaces.py` 为 audit repository 增加 `get_database_health()`
- 在 `apps/audit/infrastructure/repositories.py` 实现数据库探活与连接元数据读取
- `AuditHealthChecker` 改为通过 `get_audit_repository()` 获取仓储
- `_check_database_connection()` 只消费 repository 返回的结果，不再直接碰 `django.db.connection`
- 额外为 `AuditHealthChecker` 增加依赖注入入口，便于单元测试和后续替换实现

这样数据库访问边界重新回到 Infrastructure，Application 只保留健康状态编排。

### 7. `fund/application/use_cases.py` 与 `sector/application/use_cases.py`

旧实现里：

- `apps/fund/application/use_cases.py` 直接在用例里调用 `shared.infrastructure.config_loader.get_fund_type_preferences`
- `apps/sector/application/use_cases.py` 顶层导入 `shared.infrastructure.config_loader.get_sector_weights`

本次整改：

- 在 `apps/fund/infrastructure/repositories.py` 增加 `get_fund_type_preferences_by_regime(...)`
- 在 `apps/sector/infrastructure/repositories.py` 增加 `get_sector_weights_by_regime(...)`
- `fund` / `sector` Application 用例改为调用各自 app 的 repository

这样至少把两个真实业务调用点从 `shared` 残留配置访问器上剥离下来，改为“拥有数据的 app 自己负责提供查询能力”。

### 8. `regime/application/use_cases.py` 与 `sentiment/application/services.py`

旧实现里：

- `apps/regime/application/use_cases.py` 直接导入 `shared.infrastructure.config_helper`
- `apps/sentiment/application/services.py` 直接导入 `shared.infrastructure.config_helper`

本次整改：

- 在 `apps/regime/infrastructure/repositories.py` 增加 `RegimeConfigRepository`
- 在 `apps/regime/application/repository_provider.py` 增加 `get_regime_config_repository()`
- `HighFrequencySignalUseCase` / `ResolveSignalConflictUseCase` 改为依赖注入 config repository
- 在 `apps/sentiment/infrastructure/repositories.py` 增加 `SentimentConfigRepository`
- 在 `apps/sentiment/application/repository_provider.py` 增加 `get_sentiment_config_repository()`
- `SentimentIndexCalculator` 改为依赖注入 config repository

这样 `regime` / `sentiment` 的 Application 层不再直接依赖 `shared.infrastructure.*`，配置读取统一退回各自 app 的 Infrastructure。

### 9. `policy/interface/page_views.py`

旧实现里：

- Interface 层直接 `django_apps.get_model(...)`
- 各页面 `get_queryset()` / `get_context_data()` 直接 `_default_manager.filter(...)`
- 页面统计也在 Interface 层直接做 ORM 聚合

本次整改：

- 在 `apps/policy/infrastructure/interface_repositories.py` 增加 `PolicyPageInterfaceRepository`
- 在 `apps/policy/application/interface_services.py` 增加 `PolicyPageInterfaceService`
- 在 `apps/policy/application/repository_provider.py` 增加 `get_policy_page_interface_service()`
- `apps/policy/interface/page_views.py` 改为通过 application service 获取：
  - RSS source 列表
  - keyword 列表
  - fetch log 列表与统计
  - RSS reader 列表与统计
  - policy event 列表
  - 页面常量选项

这样 page view 的读路径不再直接碰 ORM；剩余 form/create/update 链路后续再继续收口。

### 10. `policy/interface/rss_api_views.py`、`policy/interface/serializers.py`、`policy/interface/forms.py`

旧实现里：

- `apps/policy/interface/rss_api_views.py` 直接 `django_apps.get_model(...)`
- `RSSSourceConfigViewSet` / `RSSFetchLogViewSet` / `PolicyLevelKeywordViewSet` 直接依赖 `_default_manager` 与 `ModelViewSet`
- `apps/policy/interface/serializers.py` 通过 `ModelSerializer` 直接绑定 ORM model
- `apps/policy/interface/forms.py` 通过 `ModelForm` 直接绑定 ORM model
- `apps/policy/interface/page_views.py` 的 create/update 页面通过 `CreateView` / `UpdateView` 直接走 ORM 保存

本次整改：

- 在 `apps/policy/infrastructure/interface_repositories.py` 增加 `PolicyRssApiInterfaceRepository`
- 在 `apps/policy/application/interface_services.py` 增加 `PolicyRssApiInterfaceService`
- 在 `apps/policy/application/repository_provider.py` 增加 `get_policy_rss_api_interface_service()`
- `apps/policy/interface/rss_api_views.py` 改为 service-backed `GenericViewSet`：
  - list/retrieve 通过 application service 取数
  - create/update/delete 通过 application service 调用 repository 持久化
  - `trigger_fetch` 里的对象读取不再通过 `self.get_object()` 触发 ORM queryset 默认路径
- `apps/policy/interface/serializers.py` 去掉 `django_apps.get_model(...)` 与 `ModelSerializer`，改为普通 DRF `Serializer`
- `apps/policy/interface/forms.py` 去掉 `ModelForm`，改为普通 `Form`
- `apps/policy/interface/page_views.py` 的 create/update 页面改为 `FormView` + application service 提交
- 为 `PolicyPageInterfaceRepository` / `PolicyPageInterfaceService` 补充 `create_policy_event(...)`

这样 `policy/interface` 这组页面/API 的读写入口都回到了 Application/Infrastructure，Interface 层只剩表单校验、HTTP 交互和消息提示。

补充清理：

- `apps/policy/interface/audit_api_views.py` 不再通过 `import_module("apps.policy.infrastructure.repositories")` 取 repository，改为走 `get_current_policy_repository()`
- `apps/policy/interface/event_api_views.py` 不再通过字符串 import 直接拿 infrastructure repository / alert service，改为走 application provider
- 新增 `apps/policy/models.py` 作为 app 根模型公开入口，`apps/policy/interface/admin.py` 不再使用 `django_apps.get_model(...)`

### 11. 安全清理

- 已将 `.agents/skills/mcp-remote-agomtradepro/SKILL.md` 中示例里的明文 token 改为占位值 `${AGOM_REMOTE_API_TOKEN}`

## 测试补充

新增通过：

- `python -m pytest tests/unit/test_unified_position_service.py -q`
- `python -m pytest tests/unit/test_account_admin_user_management.py -q`
- `python -m pytest tests/unit/test_audit_health_check.py -q`
- `python -m pytest tests/unit/sector/test_sector_use_case_regime_fallback.py -q`
- `python -m pytest tests/unit/regime/test_config_threshold_regression.py -q`
- `python -m pytest tests/unit/test_high_frequency_indicators.py -q`
- `python -m pytest tests/unit/test_sentiment.py -q`

补充说明：

- `policy/interface/page_views.py` 本轮暂无现成页面测试，已完成 `py_compile` 与文本级检查，确认文件内不再出现 `_default_manager` / `django_apps.get_model`
- `python -m pytest tests/api/test_policy_api_edges.py -q`
- `python -m pytest tests/test_all_pages.py -q`

## 仍待处理

仍然建议优先继续收口的高价值点：

- `apps/backtest/domain/services.py` 仍在 Domain 层读取 `shared.infrastructure.config_helper`
