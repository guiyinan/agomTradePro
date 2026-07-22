# Mypy 类型债务收口计划

更新时间：2026-07-19

## 当前证据

- `pyproject.toml` 开启 `strict = true`，但整模块 `ignore_errors` 初始覆盖 11 个模块。
- `governance/mypy_error_baseline.json` 另记录 8 个增量检查文件、合计 73 个历史错误。
- 当前本地开发环境缺少 Django、DRF、requests 等类型桩；完整依赖图会额外产生大量 `import-untyped` 噪音，不能把这些噪音混同为上述受管基线。

## 阶段策略

1. 优先处理不依赖 ORM 类型桩的 Application 模块，每完成一个就删除整个 `ignore_errors` 条目。
2. 对 8 个基线文件按 App 分组修复；错误减少后同步下调或删除 machine baseline，不允许只依赖“不得增长”。
3. Django/DRF Infrastructure 与 Interface 模块单独评估类型桩及 mypy plugin，不通过新增整模块豁免绕过。

## 第一批

- `apps.dashboard.application.alpha_homepage`：补齐用户 Protocol、构造函数类型和显式 repository 类型导出，移除整模块豁免。
- `apps.task_monitor.application.interface_services`：补齐 5 个泛型字典返回类型，从增量 mypy 基线删除整个文件条目，将历史错误总量从 73 降为 68。
- Task Monitor backup command 与 Celery health repository：补齐构造器、命令参数和 worker 列表类型，再消除 4 个历史错误，将基线降至 64。
- 新增治理测试，将整模块豁免上限从 11 降为 10、基线错误上限从 73 降为 64，并禁止已收口模块回流。

## 验证范围

- 定向 mypy：`alpha_homepage.py` 在项目 strict 配置与 `follow-imports=silent` 下零错误。
- Dashboard Alpha query/structure/runtime helper 单元测试。
- mypy 增量治理脚本测试、governance consistency、Ruff 与 diff check。

## 第一批验证结果

- `alpha_homepage.py` strict 定向 mypy：0 errors；Dashboard Alpha 及 mypy 治理相关回归：43 项通过。
- Task Monitor interface/API 与 mypy 治理回归：19 项通过。
- Task Monitor repository/backup/runtime degradation 与治理回归：27 项通过。
- 全部受管 baseline 文件复扫：恰好 64 个历史错误，0 regression；已无已删除的 9 个错误。
- Governance consistency：0 违规；依赖投影检查、Ruff 与 diff check 通过。

## 第二批

- `apps.macro.application.interface_services`：删除整模块豁免；为 Macro 持久化与读取边界增加 Application Protocol，补齐接口服务与数据管理用例类型。
- 支持同步指标的展示不再读取已退役同步用例的 `.adapters`，统一改读 Data Center 治理目录的 `indicator_rows`、`sync_supported` 与 `sync_source_type`。
- `apps.macro.application.tasks`：补齐返回容器、告警参数与 bound task 参数类型，消除 10 个非 Celery 插件型错误；仅保留 7 个本地环境无法判定的无类型 Celery 装饰器 `misc` 项。
- 治理预算同步收紧：整模块豁免上限从 10 降为 9，增量错误基线从 64 降为 54；禁止 Macro interface service 回流整模块豁免。

## 第二批验证范围

- `apps/macro/application/interface_services.py` strict 定向 mypy 必须为 0 errors。
- `apps/macro/application/tasks.py` 定向 mypy 必须只剩 7 个受管 Celery decorator `misc` 项。
- Macro interface、自动同步和周期任务单元测试。
- 全部受管 baseline 文件复扫、governance consistency、Ruff 与 diff check。
- Data Center 行为测试与结构契约测试保持独立 pytest 调用，避免已知的测试套件共享状态污染。

## 第二批验证结果

- Macro interface strict 定向 mypy：0 errors；Macro tasks 仅剩 7 个受管 Celery decorator `misc` 项。
- 全部受管 baseline 文件复扫：恰好 54 个历史错误，0 regression。
- Macro interface、自动同步、周期任务及治理护栏共 15 项通过。
- Data Center 治理目录行为测试 5 项通过；provider 抽象结构契约在独立 pytest 调用中 4 项通过。
- Governance consistency：0 违规；依赖投影检查通过。

## 第三批

- `apps.account.application.interface_services`：补齐 ORM/queryset 边界函数的显式 opaque 类型，并为实际仓储所有者补充相应方法签名；删除整模块豁免。
- `apps.account.application.use_cases`：为行情、信号快照和回测查询增加 Application Protocol，修复内建 `any` 误用、Optional 参数、容器泛型、枚举持久化值和价格 Decimal 归一化；删除整模块豁免。
- Account Application 的整模块豁免由 2 个降为 0；全仓整模块豁免上限从 9 收紧到 7。

## 第三批验证范围

- 两个 Account Application 模块在项目 strict 配置与 `follow-imports=silent` 下均须为 0 errors。
- Account API edges、profile、分类/汇率、管理员、观察者权限和 Data Center 行情建仓回归。
- mypy 债务护栏、governance consistency、Ruff、依赖投影与 diff check。

## 第三批验证结果

- Account interface services 与 use cases strict 定向 mypy：均为 0 errors。
- Account API、profile、汇率、管理员、观察者权限、行情建仓和 mypy 护栏：`95 passed`。
- 全部受管 baseline 文件复扫：仍为 54 个历史错误，0 regression；本批未新增基线项。
- Governance consistency：0 违规；Ruff、依赖投影与 diff check 通过。

## 第四批

- `apps.task_monitor.application.tasks`：为 Celery signal handler、bound task、容器返回值和全局 repository cache 补齐类型，并将 cache 约束到 Domain `TaskRecordRepositoryProtocol`。
- `MultiChannelAlertService` 补齐真实的 `is_available()` 聚合语义，正式满足 Task Monitor 的 `AlertChannelProtocol`，不再依赖不兼容对象进入告警渠道列表。
- 对本地缺少 django-stubs 的单个 `timezone` 导入做精确忽略；不扩大模块豁免。
- Task Monitor tasks 基线从 32 项降至 9 项，剩余全部是 Celery signal/task 无类型装饰器；全仓受管基线从 54 收紧至 31。

## 第四批验证范围

- Task Monitor tasks 定向 mypy 必须只剩 9 个受管 Celery decorator `misc` 项。
- Task Monitor hooks、backup task、readiness daily task、API 与告警服务回归。
- 全部受管 baseline 复扫、governance consistency、Ruff、依赖投影与 diff check。

## 第四批验证结果

- Task Monitor tasks 定向 mypy：仅剩 9 个受管 Celery decorator `misc` 项。
- Task hooks、backup、readiness daily、API 与 mypy 护栏：`39 passed`；Windows 测试数据库 teardown 报告 1 条文件占用 warning，但没有测试失败或根目录数据库残留。
- 全部受管 baseline 文件复扫：恰好 31 个历史错误，0 regression。
- Governance consistency：0 违规；Ruff、依赖投影与 diff check 通过。

## 第五批

- `core/settings/base.py` 补齐 `ALLOWED_HOSTS` 类型，并将 environ/kombu 无桩导入约束为精确行级例外。
- Task Monitor backup service、repositories 与 management command 的 Django/django-celery-beat 无桩导入改为精确行级例外；命令基类仅保留一处可审计的 `misc` 例外。
- Data Center、Macro、Task Monitor 共 18 个 Celery task/signal 无类型装饰器改为装饰器行上的精确 `misc` 例外，不再作为文件级历史错误存在。
- 七个原受管 baseline 文件联合 strict 检查达到 0 errors；`governance/mypy_error_baseline.json` 清空，治理护栏要求 modules 永久保持空集合。

## 第五批验证范围

- 七个原 baseline 文件联合定向 mypy 必须为 0 errors。
- Data Center/Macro/Task Monitor Celery 注册、backup、settings 与 readiness 相关回归。
- 空 baseline 回归脚本、governance consistency、Ruff、依赖投影与 diff check。

## 第五批验证结果

- 七个原 baseline 文件联合 strict 定向 mypy：0 errors；回归脚本确认 legacy errors 为 0。
- Data Center/Macro/Task Monitor tasks、backup、readiness、Celery aliases、production settings 与治理护栏：`58 passed`。
- Governance consistency：0 违规；Ruff、依赖投影与 diff check 通过。

## 第六批

- 移除 Account Interface 剩余 5 个整模块豁免：`sizing_views`、`api_urls`、`profile_api_views`、`serializers`，以及 Macro `page_views`；对 Django/DRF 无桩边界改用精确行级例外，并补齐请求、响应、验证器与序列化方法类型。
- 移除 Account Infrastructure 最后 2 个整模块豁免：`models` 与 `repositories`；补齐模型属性、领域转换、Token/观察者生命周期、手工成交导入与系统设置仓储的类型契约。
- `pyproject.toml` 中业务模块 `ignore_errors` 数量由初始 11 个降至 0；治理护栏由“上限不得增长”收紧为必须保持空集合。
- ORM 相关定向检查使用 `strict + follow-imports=skip` 隔离本地缺少 `django-stubs` 造成的跨模块噪音；所有第三方无桩边界均保持可审计的精确行级例外，不新增文件或模块级豁免。

## 第六批验证范围

- Account Interface、Macro page views、Account Infrastructure models/repositories 定向 strict mypy 均须为 0 errors。
- Account Token、观察者授权、手工成交导入、宏观仓位配置、分类/汇率与 API 边界行为回归。
- mypy 零豁免治理护栏、空错误基线、governance consistency、Ruff 与 diff check。
- Data Center 行为测试与结构契约继续保持独立 pytest 进程；本批不把两类测试混入同一调用。

## 第六批验证结果

- 7 个本批模块联合定向 strict mypy：0 errors；Ruff 通过。
- Account/Macro 模型、领域与页面单元回归：`113 passed`；Account API、仓位配置与手工成交导入集成回归：`51 passed`。
- 零豁免护栏、空错误基线与 governance consistency：`35 passed`，全仓治理扫描 `violation_count=0`。
- `account/infrastructure/models.py` 保持既有 1389 非空行预算，未通过抬高大文件基线吸收类型改动。
- 依赖投影 `--check` 通过；根目录临时数据库/日志与 `tmp/` vendored Python 文件均为 0。

## 第七批

- 启用 Django/DRF 类型桩与 mypy plugin 后，按排除测试和 migrations 的生产代码口径重新建立历史债务基线：`9420 errors / 986 files / 1816 source files`。
- 第一组从纯 Domain/Protocol 边界开始，补齐 shared repository 协议的标识符逆变、投资账本字典泛型、Share Interface opaque 返回类型，以及 Factor/Hedge/Rotation/Fund/Filter 值对象的显式返回与容器类型。
- 第二组收口同一批 Factor/Hedge/Rotation/Fund/Filter Domain services 的 Optional 参数、结构化字典、策略引擎分支赋值和显式浮点返回。
- 第三组收口 Task Monitor、Strategy、Simulated Trading、Signal Invalidation 与 Sentiment 的 Domain 类型，并将 Sentiment 默认时间改为 UTC aware。
- 第四组收口 Prompt Domain 的实体、规则、函数注册表与链执行计划类型，并修复循环依赖检测误把循环路径当作布尔值的问题。
- 第五组收口 Core 版本信息、可选运行时导入、资产市场注册表与运行时配置桥接类型。
- 本批不修改 ORM、HTTP 契约或金融计算行为，不新增模块级或文件级 mypy 豁免。

## 第七批验证结果

- 10 个目标源文件 strict 定向 mypy：`0 errors`；mypy regression：`0`。
- Factor、Hedge、Rotation、Fund、Filter 领域回归：`336 passed`。
- 第二组 5 个 Domain service 文件 strict 定向 mypy：`0 errors`；对应服务回归：`236 passed`。
- 第二组完成后同口径生产代码基线：`9381 errors / 971 files / 1816 source files`，较本批起点净减少 `39 errors / 15 files`。
- 第三组 18 个 Domain 源文件 strict 定向 mypy：`0 errors`；相关单元、API 与集成回归：`326 passed`。
- 第三组完成后同口径生产代码基线：`9345 errors / 961 files / 1816 source files`，较第二组净减少 `36 errors / 10 files`。
- 第四组 6 个 Prompt Domain 源文件 strict 定向 mypy：`0 errors`；Prompt 与 Agent Runtime 回归：`59 passed`。
- 第四组完成后同口径生产代码基线：`9309 errors / 957 files / 1816 source files`，较第三组净减少 `36 errors / 4 files`。
- 第五组 4 个 Core 源文件 strict 定向 mypy：`0 errors`；运行时配置、市场注册表与 TUI 回归：`206 passed`。
- 第五组完成后同口径生产代码基线：`9297 errors / 953 files / 1816 source files`，较第四组净减少 `12 errors / 4 files`。
- Ruff：通过。

## 第八批

- 新增 `scripts/check_mypy_debt_ceiling.py` 与 `governance/mypy_debt_baseline.json`，按生产代码文件和错误码精确锁定全仓 mypy 债务；变更文件零新增门禁继续保留。
- `ci-fast-feedback` 使用目标分支 baseline 阻止在同一 PR 中抬高债务上限，nightly 复核当前代码与基线完全一致；债务下降但未同步收紧基线同样失败。
- AGENTS 与工程护栏补齐裸泛型、Optional、Any 边界、局部 ignore 和基线刷新规则。
- 收口 `core/cache_utils.py` 与 `core/throttling.py` 的 18 个历史错误，并补齐缓存 pattern invalidation 的完整返回路径。
- 收口 `core/exception_utils.py` 与 `core/exceptions.py` 的 27 个历史错误，补齐 ParamSpec 装饰器、异常元组和上下文管理器契约，并修复 `logging.extra` 使用保留字段 `module` 导致异常处理路径再次抛错的问题。

## 第八批验证结果

- 全仓门禁初始锁定：`9297 errors / 953 files`；首组 Core 修复后收紧为 `9279 errors / 951 files`。
- 两个 Core 目标文件定向 mypy：`0 errors`；缓存与限流回归：`44 passed`。
- 第二组 Core 异常工具目标文件定向 mypy：`0 errors`；新增异常工具行为回归：`8 passed`；基线继续收紧为 `9252 errors / 949 files`。
- 门禁、增量 mypy 与仓库治理契约：`12 passed`；Governance consistency：`0` 违规。

## 第九批

- 收口 `shared/infrastructure/resilience.py` 的重试、超时、熔断、降级、缓存和数据源健康状态类型契约，清除该模块 43 个历史错误。
- 装饰器工厂改为在装饰器应用阶段推断 `ParamSpec`，避免 mypy 在调用工厂时将参数签名提前收窄为 `Never` 并向 Fund、通知服务等调用方传播新增错误。
- 修复通知发送路径在恢复方法体检查后暴露的 Optional 邮箱传播，验证后先绑定并收窄收件地址，不把新错误码转存为历史基线。
- Windows 等不提供 `SIGALRM` 的平台改为记录告警并执行原函数，避免访问不存在的 signal 属性导致运行时异常。
- 为重试耗尽、回调、熔断、降级、缓存失效/统计、缓存过期、健康恢复和无 `SIGALRM` 路径补齐行为测试。

## 第九批验证结果

- Shared resilience 定向 mypy：`0 errors`；全仓门禁无错误类别反弹，基线从 `9252 errors / 949 files` 收紧为 `9204 errors / 948 files`。
- Resilience、Account 通知与 Policy 通知回归：`53 passed`；共享通知交付集成回归：`23 passed`。

## 第十批

- 收口 `shared/infrastructure/metrics.py` 的指标值、label key、单例状态、容器、Alpha 指标记录、告警管理和延迟装饰器类型契约，清除该模块 36 个历史错误。
- 延迟装饰器使用 `ParamSpec` 保留被装饰函数签名、名称和文档，并以裸 `raise` 保留原始异常 traceback；完整类型继续向 Alpha 监控任务传播并额外消除 1 个下游错误。
- 修复 Prometheus histogram bucket 文本缺少引号闭合与右花括号的问题，覆盖有基础标签和无基础标签两种导出格式。

## 第十批验证结果

- Shared metrics 定向 mypy：`0 errors`；全仓基线从 `9204 errors / 948 files` 收紧为 `9167 errors / 947 files`，无文件或错误码反弹。
- Metrics 单元与 Alpha monitoring 集成回归：`37 passed`；Ruff 通过。

## 第十一批

- 收口 `shared/infrastructure/cache_service.py` 的缓存键、payload、监控信息和通用缓存装饰器类型契约，清除 24 个历史错误。
- 四组业务缓存写入不再把 Django 标准 backend 的 `set() -> None` 误作为业务返回值，成功写入后按公开契约返回 `True`。
- 默认 TTL 仅在调用方传入 `None` 时生效，保留 `timeout=0` 的显式语义；读取端拒绝并记录非字典的异常缓存值，避免错误形状进入 Regime 恢复路径。
- 通用缓存装饰器使用 `ParamSpec` 保留调用签名、函数名与 docstring。

## 第十一批验证结果

- Shared cache service 定向 mypy：`0 errors`；全仓基线从 `9167 errors / 947 files` 收紧为 `9143 errors / 946 files`，无文件或错误码反弹。
- Cache Service、Regime 激活一致性、Regime 用例和 Data Center macro provider 回归：`28 passed`；Ruff 通过。

## 第十二批

- 收口 `shared/infrastructure/notification_service.py` 剩余的发件地址、站内通知模型注入、告警通道初始化与默认通道组装类型契约，清除该模块最后 9 个历史错误。
- 站内通知以最小 `Protocol` 描述注入模型及 manager，不依赖具体 ORM Model；发送时局部绑定并收窄 Optional 模型，避免把新增 `union-attr` 转存为历史债务。
- 发件地址在配置边界归一化为非空字符串，邮件 MIME 与 Django backend 获得一致的 `str` 契约；完整通道类型额外消除 Simulated Trading task 的 1 个下游错误。

## 第十二批验证结果

- Shared notification service 在完整依赖目标下定向 mypy 无本模块错误；全仓基线从 `9143 errors / 946 files` 收紧为 `9133 errors / 945 files`，无文件或错误码反弹。
- Resilience、Account/Policy 通知与共享通知交付集成回归：`76 passed`；Ruff 通过。

## 第十三批

- 收口 `shared/infrastructure/htmx/decorators.py` 的权限、请求类型限制、响应头、消息、按用户缓存和组合装饰器类型契约，清除 45 个历史错误。
- 统一以 `HttpResponseBase` 表达 Django 视图响应边界，显式标注可变路由参数；缓存命中值在外部 cache 边界完成局部 cast，不向业务视图传播 Any。
- HTMX redirect 使用安全的 `url` 属性读取，保留重定向响应兼容性；新增协议行为测试覆盖 HTMX/AJAX 限制、默认/自定义 trigger、HX-Redirect 与按用户缓存复用。

## 第十三批验证结果

- Shared HTMX decorators 定向 mypy：`0 errors`；全仓基线从 `9133 errors / 945 files` 收紧为 `9088 errors / 944 files`，无文件或错误码反弹。
- HTMX decorators 与原共享 HTMX 回归：`18 passed`；Ruff 通过。

## 第十四批

- 收口 `shared/infrastructure/alerts.py` 的告警消息、HTTP payload、多渠道聚合、便捷发送和环境变量组装类型契约，清除 18 个历史错误。
- `AlertMessage` 改为在构造阶段通过 `default_factory` 生成 UTC-aware 时间和独立 metadata 字典，发送通道不再依赖事后 Optional 补值。
- Slack 异构 payload 在外部 HTTP 边界显式建模；全局服务直接按 `AlertChannel` 注册各实现，避免循环复用局部变量造成错误类型收窄。

## 第十四批验证结果

- Shared alerts 定向 mypy：`0 errors`；全仓基线从 `9088 errors / 944 files` 收紧为 `9070 errors / 943 files`，无文件或错误码反弹。
- 告警默认值隔离、通道故障隔离、Slack payload 与邮件时间格式回归：`4 passed`；Ruff 通过。

## 第十五批

- 收口 `shared/infrastructure/htmx/views.py` 的 Django CBV、QuerySet、删除/局部视图配置、权限 mixin 和 cooperative response mixin 类型契约，清除 19 个历史错误。
- 删除视图在缺少 model 或 success URL 时抛出明确的 `ImproperlyConfigured`，不再访问 `None.objects` 或把空 URL 传给 redirect；局部视图同样要求显式 template。
- 表单失败响应按 Django `ErrorList` 的真实字符串结构序列化，不再把错误项误当字典；Django 泛型 CBV 仅在三行运行时不可下标的类型桩边界保留精确 `type-arg` 说明。

## 第十五批验证结果

- Shared HTMX views 定向 mypy：`0 errors`；全仓基线从 `9070 errors / 943 files` 收紧为 `9051 errors / 942 files`，无文件或错误码反弹。
- HTMX views、decorators 与原共享 HTMX 回归：`22 passed`；模块运行时导入、Ruff 均通过。

## 第十六批

- 将 `shared/sanitization.py` 确立为唯一清洗实现，`shared/infrastructure/sanitization.py` 缩为兼容导出层，消除两套 XSS allowlist 和 URL scheme 规则长期漂移的风险。
- 清洗装饰器使用 `ParamSpec` 保留被包装函数签名，字段值在显式 Any 输入边界处理；两个模块合计清除 9 个历史错误。

## 第十六批验证结果

- 两个 Shared sanitization 模块联合定向 mypy：`0 errors`；全仓基线从 `9051 errors / 942 files` 收紧为 `9042 errors / 940 files`，无文件或错误码反弹。
- Plain/rich text、属性、URL scheme、字段与装饰器安全回归：`26 passed`；Ruff 通过。
