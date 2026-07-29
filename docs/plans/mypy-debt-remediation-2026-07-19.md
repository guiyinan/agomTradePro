# Mypy 类型债务收口计划

更新时间：2026-07-23

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

## 第十七批

- 收口 `shared/infrastructure/alert_service.py` 的 requests 边界和异构告警通道组装契约，清除最后 4 个历史错误。
- 默认服务的 channel 容器显式声明为 `list[AlertChannel]`，Slack、Email、Console 不再因首个 append 被错误收窄；移除通道参数限定为 AlertChannel 子类。

## 第十七批验证结果

- Shared alert service 定向 mypy：`0 errors`；全仓基线从 `9042 errors / 940 files` 收紧为 `9038 errors / 939 files`，无文件或错误码反弹。
- 异构默认通道组装、通道移除与 Policy 通知回归：`31 passed`；Ruff 通过。

## 第十八批

- 收口 `core/views.py` 的请求/响应、页面 context、文档分类和资产代码聚合类型契约，清除该文件 55 个历史错误。
- 补齐 Policy application provider 的 7 个工厂返回类型，使仓储、页面服务、通知服务和 AI 分类器不再以隐式 `Any` 向调用方传播；完整类型额外消除 48 个下游 `no-untyped-call` 等历史错误。
- 类型传播暴露出两个既有运行时契约缺口：Policy 告警工厂返回的服务缺少用例要求的通用 `send_alert()`，Sentiment task 调用了不存在的 `PolicyEvent.id` 和仓储 `get_by_id()`；本批补齐通用告警交付与按持久化 ID 查询，并以领域实体已有的标题和日期记录日志。
- Provider 的 application 协议仅在 `TYPE_CHECKING` 下导入，避免与现有 use case 反向引用形成运行时循环依赖。

## 第十八批验证结果

- Core views 与 Policy provider 联合定向 mypy：`0 errors`；全仓基线从 `9038 errors / 939 files` 收紧为 `8935 errors / 936 files`，净减少 `103 errors / 3 files`，无文件或错误码反弹。
- Core health、decision workspace、Config Center、Policy 通知与 Policy repository 回归：`103 passed`；Django system check、Ruff 通过。

## 第十九批

- 收口决策漏斗主链路 `core/api_views_decision_funnel.py`、`core/views_decision_funnel.py` 与 `core/application/decision_context.py` 的 DRF serializer、HTTP 请求/响应、页面上下文和延迟仓储类型契约，清除 31 个直接历史错误。
- Audit、Backtest 与 Regime application provider 显式公开其仓储返回类型；Regime navigator 两个构造器补齐可选 macro repository 类型，使完整类型沿 Dashboard、Regime API、任务和查询服务传播，额外消除 40 个下游历史错误。
- DRF 声明式 `data` 字段和 drf-spectacular 未类型化装饰器各保留一行精确 ignore，不使用文件级豁免。
- 类型传播发现 Dashboard 调用了不存在的 `DjangoRegimeRepository.get_current_regime()`；改为仓储已有的 `get_latest_snapshot()` 公共契约，并增加回归测试锁定当前 Regime 摘要读取路径。

## 第十九批验证结果

- 决策漏斗 3 个目标文件联合定向 mypy：`0 errors`；全仓基线从 `8935 errors / 936 files` 收紧为 `8864 errors / 933 files`，净减少 `71 errors / 3 files`，无文件或错误码反弹。
- Decision context、六步漏斗 E2E、Dashboard Regime 摘要、Regime navigator 与 API 回归：`13 passed`；Django system check、Ruff 通过。

## 第二十批

- 收口 `core/admin_log_views.py` 的管理员日志页面、流式响应、导出响应、debug token/IP 边界和认证装饰器类型契约，清除 13 个历史错误。
- Debug API 从 `HttpRequest.META` 与动态 settings 读取的值先归一化为字符串；认证装饰器使用 `ParamSpec + Concatenate` 保留被包装视图签名，避免把 header/settings 的 Any 传播到 `hmac.compare_digest`。
- 收口 `core/schema.py` 的 OpenAPI endpoint tuple、fallback serializer、API view 动态 serializer 和路径参数推断类型，清除 12 个历史错误；仅在 drf-spectacular 确实缺少类型信息的类基座与装饰器各保留一行精确 ignore。

## 第二十批验证结果

- Admin log views 与 OpenAPI schema helper 联合定向 mypy：`0 errors`；全仓基线从 `8864 errors / 933 files` 收紧为 `8839 errors / 931 files`，净减少 `25 errors / 2 files`，无文件或错误码反弹。
- OpenAPI schema 可访问性与管理员日志页面契约回归：`2 passed`；Ruff 通过。

## 第二十一批

- 收口 `core/integration/data_center_business_sources.py` 的 Macro、Fund、Equity、Sector 业务桥接返回类型，清除该文件 10 个历史错误。
- 补齐 Fund 三类 adapter、Equity 财务 gateway、Macro legacy series 的 application provider/query 返回契约，使 Data Center price service、AKShare/Tushare provider adapter 和 gateway 获得真实类型，额外消除 10 个下游历史错误。
- 类型传播一度暴露 Tushare 财务事实构造的 60 个参数错误：原实现以 `dict[str, object]` 通过 `**common` 注入 dataclass，无法保证字段与值类型一一对应；改为绑定期间公共字段的强类型构造器，未将这些新错误写入基线。
- 新增 Tushare 财务事实映射回归，覆盖十类指标、期间类型、单位、来源与 provider 元数据。

## 第二十一批验证结果

- Data Center 业务桥接定向 mypy：`0 errors`；全仓基线从 `8839 errors / 931 files` 收紧为 `8819 errors / 929 files`，净减少 `20 errors / 2 files`，无文件或错误码反弹。
- Data Center Phase 3 provider adapter 回归：`27 passed`；Ruff 通过。

## 风险与杠杆优先级重排（2026-07-22）

- 在 `8819 errors` 快照上按错误码聚合：`no-untyped-def=3324`、`type-arg=1533`、`no-untyped-call=1143`，适合后续按类型桩、插件和统一签名批量治理。
- 真实风险池优先覆盖 `arg-type=442`、`assignment=263`、`union-attr=171`、`return-value=30`，合计 `906 errors`（10.3%）；不再单纯按单文件总数排序。
- 公共依赖杠杆按生产文件引用数衡量：Account repository provider 被 16 个文件引用、Regime 14 个、Equity 12 个；serializer 中 Strategy 被 6 个文件引用且自身有 39 项历史债务。
- 选择下一批时优先满足“风险错误密度高 + repository/serializer/decorator 公共边界”两个条件；低风险 `no-untyped-def/import-untyped/misc` 在公共边界稳定后集中治理。

## 第二十二批

- 按风险与杠杆矩阵优先收口 `apps/equity/infrastructure/fundamentals_repository.py`，该文件同时是 Equity 公共 repository 切片和全仓风险错误密度最高的模块。
- 为 mixin 显式声明 Data Center 财务/估值 repository、按需服务及宿主 helper 契约，消除组合类中 15 个被隐式依赖遮住的属性错误。
- 将十类 `FinancialFact` 从 `dict[str, object] + **common` 改为强类型构造器，清除 60 个 `arg-type`；Optional 指标先局部绑定再取值，清除 3 个 `union-attr`。
- QuerySet TypedDict 与页面 context 字典使用不同变量和 `Mapping` 边界，清除剩余 assignment/misc/typeddict 错误；行情数值通过 `safe_float` 归一化，不把 ORM 动态值直接交给 `float()`。

## 第二十二批验证结果

- Equity fundamentals repository 在定向和全量上下文均为 `0 errors`；全仓基线从 `8819 errors / 929 files` 收紧为 `8734 errors / 928 files`，净减少 `85 errors / 1 file`，无文件或错误码反弹。
- Equity repository Data Center 映射与 Equity API 边界回归：`22 passed`；Django system check、Ruff 通过。

## 第二十三批

- 按风险错误密度优先收口 `apps/terminal/application/tui_workbench_result_models_specialized.py`：该工作台公共结果模型集中承载 Advisor、AI Router 与 MCP 自助接入的用户态展示，原有 91 项债务全部属于 `attr-defined`、`union-attr`、`no-any-return` 风险类别。
- 为 specialized mixin 在 `TYPE_CHECKING` 分支显式声明组合宿主提供的标题、状态、文本和阻断原因格式化契约，不增加运行时占位实现，清除 49 个隐式宿主属性错误及 3 个 Any 返回错误。
- 新增统一的映射 payload 归一化 helper；每个动态子结构只读取一次并收窄为 `dict[str, Any]`，清除 39 个重复 `.get()` 无法保持类型收窄导致的 Optional 访问错误，同时让畸形 API 数据继续安全降级为空映射。

## 第二十三批验证结果

- Terminal specialized result model 定向 mypy：`0 errors`；全仓基线从 `8734 errors / 928 files` 收紧为 `8643 errors / 927 files`，净减少 `91 errors / 1 file`，无文件或错误码反弹。
- TUI Workbench、Terminal Agent、SDK Client 与内部 SSL redirect 固定回归包：`229 passed`；Ruff 通过。

## 第二十四批

- 按风险与公共聚合杠杆收口 `apps/dashboard/application/use_cases.py`：以 Account、Portfolio、Regime、Signal 和 Dashboard Overview Protocol 替代六组 `Any` 仓储依赖，补齐 Dashboard DTO 的 Optional 与 `default_factory` 契约，该文件在全量上下文清除全部 59 项历史错误。
- 类型传播发现默认组合快照可能为 `None` 却被直接解引用，且真实 `PortfolioSnapshot` 不存在历史代码读取的 `initial_capital` 属性；现对缺失快照抛出结构化 `ResourceNotFoundError`，回退本金优先取 Account Profile，并在 Profile 缺失时由总资产与累计收益反推。
- Signal repository provider 与 infrastructure factory 补齐具体返回类型，连带清除 Dashboard、Signal application 的历史 Any 传播；Dashboard composition provider 改为显式工厂导出，避免公共函数依赖隐式借名导入。
- 类型传播同时暴露自动交易信号校验接错接口：引擎原调用返回领域实体的 `get_signal_by_id()`，随后却按字典执行 `.get()`；现统一调用 repository 已有的 `get_signal_snapshot()` 字典契约，并以布尔归一化处理有效状态。
- Allocation Service 的持仓输入改为只读 `Sequence[PositionLikeProtocol]`，Protocol 属性改为只读 property，使真实 Domain `Position` 在不复制、不强转的情况下满足结构契约。

## 第二十四批验证结果

- Dashboard use case 在定向和全量上下文均为 `0 errors`；全仓基线从 `8643 errors / 927 files` 收紧为 `8560 errors / 925 files`，净减少 `83 errors / 2 files`，无文件或错误码反弹。
- Dashboard、Strategy Allocation、Auto Trading Engine/Task wiring 与 Alpha exit-loop 回归：`30 passed`；Ruff 通过。

## 第二十五批

- 收口公共 `DjangoSignalRepository` 与 `UnifiedSignalRepository` 的 ORM QuerySet、动态 values payload、时间区间、统计返回值和 Optional 参数契约，Signal repository 在全量上下文清除全部 48 项历史错误。
- `InvestmentSignal` 领域实体允许缺省的 `invalidation_logic/rejection_reason`，但对应 ORM TextField 仅允许空字符串、不允许数据库 NULL；保存与更新路径现统一在持久化边界归一化为 `""`，并增加真实数据库回归锁定约束。
- `.values()` 返回的具体 TypedDict 行显式复制为普通 `dict[str, Any]` payload，避免把 QuerySet 的只读精确行类型冒充可变通用字典；统一信号模型 helper 补齐返回类型，使 provider、query service 与 unified service 获得完整类型传播。

## 第二十五批验证结果

- Signal repositories 定向与全量上下文均无本文件错误；全仓基线从 `8560 errors / 925 files` 收紧为 `8488 errors / 923 files`，净减少 `72 errors / 2 files`，无文件或错误码反弹。
- Repository、Signal Query、Unified Signal 与 Auto Trading Engine 回归：`53 passed`；Ruff 通过。

## 第二十六批

- 按真实风险密度收口 Alpha 四层降级链路中的 `SimpleAlphaProvider`：以 TypedDict 分离基本面数值、字段完整性和数据质量统计，不再把嵌套布尔元数据伪装成 `dict[str, float]`。
- 估值与财务 Optional 记录先局部绑定 PE/PB/股息率/ROE 字段，再执行正值检查和默认值降级；实时行情动量行同样使用强类型结构，避免动态 key 与 `object -> float` 转换掩盖空值或错误形状。
- 本批清除该 adapter 全部 `arg-type`、`assignment`、`operator`、`union-attr` 等 32 项历史错误；仅保留基类/装饰器未类型化造成的 2 项低风险 `misc`，留待 decorator 公共治理批次统一处理。

## 第二十六批验证结果

- Simple Alpha adapter 的真实风险错误归零；全仓基线从 `8488 errors / 923 files` 收紧为 `8456 errors / 923 files`，净减少 `32 errors`，无文件或错误码反弹。
- Simple Adapter、Alpha cache fallback 与 Alpha provider 回归：`36 passed`；Ruff 通过。

## 第二十七批

- 按真实风险与公共边界杠杆收口 Account 交易成本链路：新增 `TypedDict + Protocol` 契约统一资产元数据、费率配置、交易成本记录和高成本分析结果，Application 用例改为通过 provider factory 注入，不再直接依赖 concrete repository。
- 强类型传播暴露并修复两个真实运行缺陷：历史分析代码把映射记录误写成 `t.notional`，会在有交易数据时触发 `AttributeError`；平均成本率跳过零金额交易却仍以全部交易数为分母，会系统性低估结果。无效交易方向现在也会被明确拒绝，不再静默按卖出计税。
- Infrastructure repository 在 ORM 出口把 FloatField 费率显式归一化为 `Decimal(str(value))`，避免金额计算重新引入二进制浮点误差；交易记录和资产元数据出口改为精确 TypedDict。
- 补齐公共 Account repository provider 的 parser、行情、通知、备份与 repository factory 返回契约，并清理 ORM 插件已能推断出的冗余 cast/失效 ignore；类型传播连带清除 Manual Trade Sync、Stop Loss 和 Account Task 调用侧债务。

## 第二十七批验证结果

- 6 个变更生产文件通过增量 mypy：`0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8456 errors / 923 files` 收紧为 `8412 errors / 919 files`，净减少 `44 errors / 4 files`，无文件或错误码反弹。
- Transaction Cost、Manual Trade Sync、Stop Loss 与 DB Backup 回归：`19 passed`；架构 guardrail：`19 passed`；Django system check、Ruff 通过。

## 第二十八批

- 按真实风险密度收口 `apps/agent_runtime/application/services/timeline_service.py`：以最小 repository Protocol 固定事件写入参数和主键返回值，所有异构 event payload 显式使用 `dict[str, Any]` 边界，不再因首个字符串字段被错误收窄。
- 抽取统一任务身份解析，拒绝把 `id=None` 的未持久化 `AgentTask` 写入非空 timeline 外键；状态变更入口从宽泛 `object` 收紧为 `str | TaskStatus`。
- 修正 timeline trace 完整性：canonical `request_id` 现在最后写入 payload，调用方提供的同名键不能覆盖稳定追踪 ID；新增回归覆盖伪造 request ID 和未持久化任务两种失败场景。

## 第二十八批验证结果

- Timeline service 定向与增量 mypy：`0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8412 errors / 919 files` 收紧为 `8396 errors / 918 files`，净减少 `16 errors / 1 file`，无文件或错误码反弹。
- Timeline service 回归：`22 passed`；架构 delta 扫描 `1 file / 63 added lines / 0 violations`；Ruff 通过。

## 第二十九批

- 收口 `apps/decision_rhythm/application/decision_execution_use_cases.py` 的模拟盘与账户执行输入：按执行目标建立不可空的内部 DTO，在进入交易用例或 Account repository 前统一校验账户、资产、动作、数量和价格，不再把 Optional 字段直接传入公共写入边界。
- 修复三个真实失败模式：未知 action 原先静默进入卖出路径；模拟盘缺字段会在下游以无关 Mock/数值异常失败；账户缺字段会抛出未捕获的 `decimal.InvalidOperation`。现在均返回结构化执行失败并回写 FAILED 状态。
- Signal ID 只接受 `int | str`，拒绝 bool 和任意动态对象；Beta Gate 的 `bool | None` 明确归一化，买卖用例使用独立局部变量，消除错误的方法签名传播。
- 补齐四个 Application 用例构造器和事件发布入口的参数/返回类型，目标文件 22 项历史债务全部归零，并连带减少 interface dependency 的 4 个未类型调用。

## 第二十九批验证结果

- Decision execution 定向与增量 mypy：`0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8396 errors / 918 files` 收紧为 `8370 errors / 917 files`，净减少 `26 errors / 1 file`，无文件或错误码反弹。
- Decision execution、workflow 与结构回归：`21 passed`；架构 delta 扫描 `1 file / 149 added lines / 0 violations`；Ruff、diff check 通过。

## 第三十批

- 按“真实风险密度 + 公共 decorator 边界”收口 `apps/simulated_trading/application/tasks.py`：为 Celery `shared_task` 建立局部强类型适配器，统一普通任务、绑定任务、别名 `.run()` 和 retry 契约，清除装饰器向 15 个异步入口传播的未类型调用与返回值债务。
- ORM 单账户查询先完成 `None` 分支处理，再构造账户列表；通知与再平衡 payload 的账户、提案和用户标识统一经过非 bool 整数校验，不再把动态 `Any` 或可空值直接传入交易与通知边界。
- 实时行情轮询和绩效计算器只在动态 composition boundary 局部收窄构造器类型；日常巡检通过 repository provider 获取依赖，不新增 Application 对 concrete repository 的直接依赖。
- 删除任务模块内与共享通知实现不一致的同名配置类，改为复用并兼容导出统一 `NotificationConfig`，避免运行时配置对象形状与通知通道契约漂移。

## 第三十批验证结果

- Simulated Trading tasks 定向与增量 mypy：`0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8370 errors / 917 files` 收紧为 `8321 errors / 916 files`，净减少 `49 errors / 1 file`，该文件全部十类历史错误归零且无错误码反弹。
- Celery 注册别名、自动交易 wiring、持仓失效、通知投递和再平衡流程回归：`52 passed`；架构 delta 扫描 `1 file / 129 added lines / 0 violations`；Ruff、diff check 通过。

## 第三十一批

- 按风险密度和公共 repository 杠杆收口 Simulated Trading 净值链路：`ports.py` 为每日净值写入、完整记录、上一日记录及账户/持仓/交易依赖建立 TypedDict 与 Protocol 契约；`DjangoDailyNetValueRepository` 在 ORM 出口构造精确记录，不再向 Application 传播裸字典。
- `DailyNetValueService` 以异构 `PerformanceMetrics` 保留 `winning_trades: int`，避免指标字典把整数字段宽化成 float；净值曲线、回撤和夏普计算统一消费强类型记录。
- 类型传播修复三个真实失败模式：零初始本金计算累计收益率时原会除零；允许空用户的账户目标原会执行 `int(None)`；ORM 保存后主键仍为空时原会把 `None` 当作成功 ID 返回。现在分别安全降级、保留可空用户标识并在持久化边界显式失败。
- 同步收口公共 Account/Position/Trade/Fee/Inspection repository 的 Decimal 到 Domain float 映射、可空主键、动态 payload、日期参数和聚合返回类型；下游 `query_services.py` 收窄账户 ID 和净值序列化契约，消除 repository 类型增强引出的调用侧回归。

## 第三十一批验证结果

- 4 个变更生产文件的直接与增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8321 errors / 916 files` 收紧为 `8251 errors / 912 files`，净减少 `70 errors / 4 files`，并连带减少 interface service 的 2 个未类型调用。
- 每日净值、策略自动交易、模拟交易、绩效曲线、任务 wiring、持仓失效、通知/再平衡、Dashboard、readiness 和持仓查询回归共 `127 passed`；架构 delta 扫描 `4 files / 373 added lines / 0 violations`；Django system check、Ruff、diff check 通过。

## 第三十二批

- 按可空访问风险收口 `apps/equity/infrastructure/financial_source_gateway.py`：财务指标从 `metric_map` 单次读取并通过统一 helper 返回数值或显式默认值，不再重复执行 `get()` 后解引用可能为空的事实对象。
- Decimal 边界补齐参数类型与精确异常处理，非数值、NaN 和 Infinity 统一归一化为有限零值；Tushare 网关构造器补齐返回类型。
- 新增稀疏财务事实回归，验证仅有收入指标时仍能生成完整记录，缺失增长率保持 `None`，金额与比率使用明确默认值。

## 第三十二批验证结果

- Equity financial source gateway 的直接与增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8251 errors / 912 files` 收紧为 `8240 errors / 911 files`，净减少 `11 errors / 1 file`。
- 财务网关回归：`6 passed`；架构 delta 扫描 `1 file / 29 added lines / 0 violations`；Ruff、diff check 通过。

## 第三十三批

- 收口 AI Capability 公共 Interface Service 的 MCP 工具 DTO 参数和 toggle 返回契约，页面 payload 入口明确接收 `CapabilityDefinition`，公共切换函数明确返回更新后的领域实体或 `None`。
- 删除 `replace(capability, **{flag: ...})` 动态字段更新；Application 层自身现在只允许 `enabled_for_routing` 与 `enabled_for_terminal`，非法字段直接拒绝，避免调用者绕过 HTTP Interface 白名单后修改其他布尔治理字段。
- 新增非法字段回归，验证 `requires_confirmation` 等非白名单字段不会被公共 facade 更改。

## 第三十三批验证结果

- AI Capability interface service 的直接与增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8240 errors / 911 files` 收紧为 `8228 errors / 910 files`，净减少 `12 errors / 1 file`。
- MCP tools 页面与切换回归：`6 passed`；架构 delta 扫描 `1 file / 19 added lines / 0 violations`；Ruff、diff check 通过。

## 第三十四批

- 按“真实风险 + 公共链路杠杆”收口 Realtime 的 Repository、Provider composition、Polling Service 与 Interface：Redis、Tushare、AKShare 和 Data Center 行情出口统一构造 `Decimal` 领域价格，不再把字符串价格带入持仓、提醒和推送链路。
- 修复缓存反序列化的零值语义：`change=0` 与 `change_pct=0` 现在保持为 `Decimal("0")`，不再因 truthy 判断被误写成缺失值；新增专门回归锁定价格精度与零涨跌值。
- 为提醒、订阅和 Channels notifier concrete repository 显式实现领域 ABC；Provider 列表、模拟持仓更新结果和 API payload 分别使用 Protocol、TypedDict 与局部动态边界，消除 composition 中隐式 `Any` 和名义协议不匹配。
- Interface 层统一校验已认证用户具有持久化主键，并补齐 Django/DRF handler 参数、市场汇总异构 payload 和健康检查状态类型，避免把 `pk=None` 传入 owner-scoped repository。
- 共享 AkShare SDK bridge 改为带 `ModuleType` 返回值的动态导入边界，同时保留 Realtime 可 patch 的加载接缝；类型传播连带清除 Alpha、Data Center、Equity 和 Realtime 其他调用点的 18 项 `no-untyped-call`。模拟交易任务中因此失效的冗余 cast 同步删除。

## 第三十四批验证结果

- 7 个变更生产文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8228 errors / 910 files` 收紧为 `8131 errors / 902 files`，净减少 `97 errors / 8 files`，无文件或错误码反弹。
- Realtime repository、AKShare/Data Center provider、Polling、Interface、价格交付与模拟交易 task wiring 回归共 `32 passed`；架构 delta 扫描 `7 files / 202 added lines / 0 violations`，Django system check、Ruff 和 diff check 通过。

## 第三十五批

- 按风险矩阵优先收口 `apps/equity/infrastructure/stock_info_repository.py`：为组合 mixin 显式声明 Data Center 五类 repository、EastMoney 配置和宿主 helper 契约，清除 21 个隐式属性错误及其传播出的 Any 返回。
- 修正 Equity 主数据契约：Data Center 的 canonical `AssetMaster.list_date` 与最小行情降级路径均允许上市日期未知，`StockInfo` 和 `EquityAssetScore` 现统一使用 `date | None`，序列化安全输出 `null`，不再用错误的必填类型掩盖真实缺失数据。
- 在开发依赖真源加入 `types-requests` 并同步生成 `requirements-dev.txt`，一次消除 Dashboard、Data Center、Equity、Policy 与 Terminal 多个请求调用点的 `import-untyped`；类型桩生效后同步删除共享告警中的失效 ignore。
- `feedparser` 无可用官方/第三方桩，改在 Policy Infrastructure 内以 `ModuleType + Protocol + cast` 建立局部动态边界；入口字段统一归一化，并把 feed 的 UTC `struct_time` 转成 timezone-aware datetime，修复原先生成 naive datetime 的运行风险。

## 第三十五批验证结果

- 5 个变更生产 Python 文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8131 errors / 902 files` 收紧为 `8082 errors / 895 files`，净减少 `49 errors / 7 files`，无文件或错误码反弹。
- Equity stock context/scoring/structure、Policy RSS 与共享告警回归共 `33 passed`；依赖投影检查通过，架构 delta 扫描 `6 files / 107 added lines / 0 violations`，Ruff 通过。

## 第三十六批

- 延续 Equity 组合仓储公共边界，收口 `apps/equity/infrastructure/market_data_repository.py`：显式声明 Data Center on-demand service、PriceBar repository 和宿主数值/代码 helper 契约，清除 16 个 mixin 隐式属性错误。
- 将 Data Center `PriceBar` 与远端 Gateway `HistoricalPriceBar` 分成两类强类型序列，替换六处裸 `list`；Tushare 兼容适配器只在局部 composition boundary 收窄构造器，不把动态构造类型扩散到行情算法。
- Data Center 的成交量允许 `float | None`，Equity `TechnicalBar` 要求整数手数；转换边界现显式归一化为 `int`，避免浮点成交量进入技术指标领域对象。日收益率映射同步补齐精确键值类型。

## 第三十六批验证结果

- Market Data repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8082 errors / 895 files` 收紧为 `8059 errors / 894 files`，净减少 `23 errors / 1 file`，无文件或错误码反弹。
- Equity 日线、远端 fallback、技术 K 线与 stock context 回归共 `15 passed`；架构 delta 扫描 `1 file / 50 added lines / 0 violations`，Ruff、diff check 通过。

## 第三十七批

- 收口 Equity 组合仓储的分时切片：为快照 freshness 常量、最近数据源状态、数值/时间/代码 helper 和 Quote repository 补齐强类型契约，清除分时主备源、校验价格与缓存快照链路中的 15 个隐式属性错误。
- Pandas 仅在 Infrastructure 第三方边界通过 `ModuleType` 动态加载，避免无桩类型扩散；分时源状态显式使用 `str | None`，不再把首次字符串赋值错误收窄为不可空状态。
- 类型传播发现同一个 `_dc_quote_repo` 在 StockInfo 与 Intraday mixin 使用了两套不完整协议；现把 `get_series` 纳入 Data Center 唯一 `QuoteSnapshotRepositoryProtocol`，两个 mixin 共用领域契约，连带清除组合 repository 的 assignment 冲突。

## 第三十七批验证结果

- Data Center Quote Protocol 与 Equity Intraday repository 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8059 errors / 894 files` 收紧为 `8038 errors / 893 files`，净减少 `21 errors / 1 file`，无文件或错误码反弹。
- Equity 分时主源、本地快照、fallback、一致性拒绝与结构回归共 `12 passed`；架构 delta 扫描 `2 files / 28 added lines / 0 violations`，Ruff、diff check 通过。

## 第三十八批

- 收口 Equity 组合仓储根 `DjangoStockRepository`：on-demand service 构造参数改为显式可空服务契约，数值转整数先经字符串边界，避免把任意 object 直接交给 `float()`。
- 市场时间转换先接受原生 datetime，否则只调用可调用的 `to_pydatetime`，并验证第三方返回值确为 datetime；异常形状现在抛出 `DataValidationError`，不再从 typed 方法泄漏 Any。

## 第三十八批验证结果

- Equity stock repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8038 errors / 893 files` 收紧为 `8035 errors / 892 files`，净减少 `3 errors / 1 file`。
- Equity 分时、日线与结构回归共 `16 passed`；架构 delta 扫描 `1 file / 15 added lines / 0 violations`，Ruff、diff check 通过。

## 第三十九批

- 收口 AI Capability 路由公共用例：legacy MCP catalog loader 通过具名动态边界读取和替换，保留现有测试 patch 接缝，同时清除跨模块私有属性访问传播的 13 个 `attr-defined`。
- Capability retrieval 使用真实 `RetrievalScore` 序列；MCP 执行前强制验证 `tool_name` 为非空字符串，避免把 `None/Any` 传入 SDK 与 builtin tool registry。
- Chat fallback 只依赖局部 AI client/factory Protocol，并保留 typed `AIClientFactory` callable 兼容接缝；动态 response content 显式归一化为字符串。Answer-chain steps 使用异构 payload 类型，避免先按字符串字典推断后写入技术详情列表。
- Regime adapter 补齐日期参数和 payload 返回类型，suggestion reply 在进入 `RoutingDecision` 前收窄为字符串。

## 第三十九批验证结果

- AI Capability use cases 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8035 errors / 892 files` 收紧为 `8013 errors / 891 files`，净减少 `22 errors / 1 file`。
- Routing、semantic sync 与 SDK catalog 定向测试先通过 `60` 项并暴露一个兼容 patch 接缝，修复后完整 routing suite `6 passed`；架构 delta 扫描 `1 file / 119 added lines / 0 violations`，Ruff、diff check 通过。

## 第四十批

- 收口 Filter Application 编排：DTO 的列表字段统一使用 `default_factory`，不再用 `None` 违背声明类型或共享可变默认值；比较结果与序列化 payload 补齐异构字典类型。
- Repository provider 使用显式同名导出保留 Application composition boundary；HP adapter 构造器只在局部 typed factory 收窄，避免 concrete infrastructure 的未类型构造传播。
- Compare 用例先验证成功响应确实携带 `FilterSeries` 再序列化，修复“success=True 但 series=None”时的可空参数风险；滤波配置和输出映射补齐键值类型。

## 第四十批验证结果

- Filter use cases 与 provider 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `8013 errors / 891 files` 收紧为 `7995 errors / 890 files`，净减少 `18 errors / 1 file`，无错误码反弹。
- Filter API edge 回归 `8 passed`；架构 delta 扫描 `2 files / 36 added lines / 0 violations`，Ruff、diff check 通过。

## 第四十一批

- 按“公共 Repository 边界 + 真实风险错误码”收口 Share 快照编排：在 consumer-owned Domain 接口中补齐分享链接、免责声明、决策请求、审批响应、推荐和特征快照的只读 Protocol，替换跨 App 查询返回的裸 `object`，不新增 Application 对其他 App Infrastructure 的依赖。
- 决策链不再通过 `getattr(..., Any)` 读取推荐和特征字段；响应缺失、可空 recommendation、Decimal 价格、异构 JSON payload 和日期序列化都在明确契约内收窄。公共函数返回类型向 Interface 继续传播，连带减少 2 个未类型化调用。
- 修复两个运行风险：空 `asset_code` 不再成为持仓索引键；实时快照刷新失败保留 best-effort 行为但写入异常日志，不再静默吞掉故障。

## 第四十一批验证结果

- Share interface service 与 Domain interfaces 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7995 errors / 890 files` 收紧为 `7941 errors / 889 files`，净减少 `54 errors / 1 file`，无文件或错误码反弹。
- Share 页面、快照 Decimal/JSON guardrail 与架构治理回归共 `46 passed`；Black、Ruff、diff check 通过。

## 第四十二批

- 按“异步任务入口 + 公共 Provider 杠杆”收口 Alpha/Qlib 链路：Repository Provider 以显式 `__all__` 固定公开 API，并为四类 repository factory 补齐返回契约，消除 facade 仅靠隐式 re-export 导致的跨模块类型漂移。
- 新增共享 Celery typed adapter，完整描述 task 的 `run`、`delay`、`apply/apply_async`、bound request 与 retry 表面；Alpha 的预测、训练、评估、缓存、每日批处理和运行时数据刷新任务统一使用该适配器，任务 body 的输入与 JSON 返回全部具化。
- Prediction proxy 保留既有 patch/inspection 接缝，同时把 Qlib 动态实现限制在局部 `Callable` 边界；scoped inference 的 portfolio ref、scope、queued/skipped payload 和 refresh result 均显式分型。
- 类型传播修复两个真实风险：fresh-cache 分支在读取 `asof_date` 前明确排除空 cache；IC trend 构建不再复用循环变量 `row`，避免可空查找结果与源记录变量发生错误赋值覆盖。

## 第四十二批验证结果

- 4 个变更生产文件的增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7941 errors / 889 files` 收紧为 `7826 errors / 885 files`，净减少 `115 errors / 4 files`，无文件或错误码反弹。
- Alpha 预测、缓存 fallback、Ops、Qlib 训练、任务结构/别名、Alpha cache 与架构治理回归共 `67 passed`；Black、Ruff、diff check 通过。

## 第四十三批

- 按高风险密度收口 TUI workbench catalog mixin：使用仅在类型检查阶段可见的宿主契约声明 `_operator_text`、确认判断、view-model 路径解析、action 标题和账户选项缓存，不向运行时 MRO 注入占位实现。
- 三处动态整数转换先显式排除 `None` 与空字符串，再进入 `int()` 边界；账户 ID 缓存保持 `dict[int, list[dict[str, Any]]]`，消除动态宿主属性带来的 Any 返回传播。
- Catalog 的 screen/action/field 投影逻辑和现有 TUI metadata 行为保持不变，类型契约仅固定横向 mixin 与最终 `TuiWorkbenchService` 的组合要求。

## 第四十三批验证结果

- TUI workbench catalog 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7826 errors / 885 files` 收紧为 `7794 errors / 884 files`，净减少 `32 errors / 1 file`，无文件或错误码反弹。
- TUI workbench、TUI contract、Terminal Agent、SDK client、SSL redirect 固定回归包与架构治理共 `251 passed`；Black、Ruff、diff check 通过。

## 第四十四批

- 修复 Data Center 公共 composition root：以显式 `__all__` 固定 repository、provider registry、SDK bridge、PIT factory 和配置读取 API，替代“导入即隐式导出”的不稳定契约。
- 类型传播一次清除 Data Center interface service、price service、AKShare provider adapter/网关、ETF adapter、SSE investor accounts 与 Macro data-management 的公共导出和未类型调用债务。
- PIT Manifest Gateway 的 `build(**kwargs)` 过宽协议改为与真实 repository 一致的 keyword-only 参数契约；连接测试动态实现通过局部 typed callable 收窄，legacy AKShare bridge 使用显式同名导出。

## 第四十四批验证结果

- Data Center composition、PIT use cases 与 legacy SDK bridge 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7794 errors / 884 files` 收紧为 `7755 errors / 882 files`，净减少 `39 errors / 2 files`，无文件或错误码反弹。
- Data Center use cases、市场网关、PIT research integrity、provider abstraction/adapters 与架构治理回归共 `115 passed`；Black、Ruff、diff check 通过。

## 第四十五批

- 按“真实运行风险 + 聚合服务杠杆”收口 `apps/signal/application/unified_service.py`：以消费方 Protocol 固定 Alpha、Factor、Hedge 的最小契约，以 TypedDict 固定聚合计数和 Regime 配置结构，动态数据只保留在 JSON/第三方边界。
- 类型检查揭示 Rotation 调用的是不存在的 `get_all_configs()` 与 `generate_signal()`；现改为调用 Rotation Application 已发布的批量生成入口，并对批次、信号、资产代码和权重逐层校验，避免模块启用后持续退化为 best-effort 错误。
- Alpha 类型不直接导入对方 Domain 实体，而由 Signal 声明最小只读形状；架构门禁曾捕获直接导入引入的 `signal -> alpha` 新依赖和模块环，撤回后恢复为 `199 edges / 0 cycles`，没有用类型治理换取跨 App 耦合。
- `get_unified_signals(min_priority=...)` 现在实际执行最低优先级过滤，修复参数长期声明但未生效的查询语义缺陷；新增 Rotation 正式入口和优先级过滤回归。

## 第四十五批验证结果

- Signal unified service 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7755 errors / 882 files` 收紧为 `7720 errors / 881 files`，净减少 `35 errors / 1 file`，其中目标文件 32 项全部归零，并连带清除 Signal Interface 的 3 项未类型调用。
- Unified Signal 单元与 Alpha 全链路集成回归共 `24 passed`；模块依赖门禁 `199 edges / 0 cycles`，全仓架构边界违规为 `0`。完整架构审计仍报告 Realtime repository provider 的 7 条既存审计债务，与本批改动无关；Ruff、diff check 通过。

## 第四十六批

- 按“公共 Repository composition + Application 真实风险”收口 Decision Rhythm workspace：`repository_provider.py` 用显式同名导出和 `__all__` 固定 9 类 repository、4 类 provider factory 及查询 API，不再依赖 mypy 禁止的隐式 re-export。
- Workspace Application 全部改走 repository factory，不再直接构造 concrete repository；审批、估值、推荐和交易计划出口使用领域实体返回契约，动态 ORM 返回只在 composition 边界局部收窄。
- 修复冷却期 Optional 访问：先计算稳定的剩余小时数，再生成失败原因，不再依赖 `cooldown_ok=False` 间接假设对象非空。执行状态仓储显式接收 `ExecutionStatus | str`、aware datetime 和 JSON execution ref。
- 类型传播揭示 `get_aggregated_workspace_payload` 真实返回推荐列表却声明为字典；现纠正为 `list[dict[str, Any]]`，与 Workspace API 的实际响应契约一致。

## 第四十六批验证结果

- Workspace service、Decision Rhythm repository provider 与 rhythm repository 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7720 errors / 881 files` 收紧为 `7677 errors / 878 files`，净减少 `43 errors / 3 files`，三文件历史债务全部归零。
- Workspace 推荐/API、模拟持仓、交易计划和审批链回归共 `30 passed`；模块依赖门禁保持 `199 edges / 0 cycles`，Ruff、Black、diff check 通过。

## 第四十七批

- 按“返回值风险 + 通知公共边界”收口 Signal 证伪检查器：为宏观观测、宏观 repository、研究完整性 recorder、通知服务和通知结果建立最小 Protocol，动态依赖不再向规则编排扩散 `Any`。
- 类型检查揭示通知代码把领域契约 `checked_conditions: list[dict[str, Any]]` 错当对象访问；真实发送证伪邮件时会触发 `AttributeError`。现统一按映射读取 `is_met/indicator_code/description/actual_value/threshold`，缺失描述时安全回退到指标代码。
- 未持久化的 `InvestmentSignal(id=None)` 不再进入失效写入；批量检查结果也只返回非空信号 ID。管理员邮箱配置先验证容器和字符串元素，避免动态 settings 值污染收件人列表。
- Signal repository Protocol 的失效详情从裸 `dict` 收紧为 `dict[str, Any]`，与 concrete repository 和 Application payload 一致。

## 第四十七批验证结果

- Signal invalidation checker 与 Domain repository interfaces 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7677 errors / 878 files` 收紧为 `7662 errors / 876 files`，净减少 `15 errors / 2 files`，两文件历史债务全部归零。
- Signal 证伪检查、Data Center 宏观读取、legacy repository 路径和通知映射渲染回归共 `14 passed`；Ruff、Black、diff check 通过。

## 第四十八批

- 验证并落地 Django Admin 公共类型模式：Simulated Trading 的 9 个 `ModelAdmin` 通过 `TYPE_CHECKING` 泛型基类别名绑定具体 ORM Model，静态侧获得精确对象类型，运行时仍继承不可下标的普通 `ModelAdmin`，避免为 mypy 引入应用启动 `TypeError`。
- 28 处旧式 `method.short_description = ...` 动态属性全部迁移到 Django 官方 `@admin.display(description=...)`；展示方法补齐具体模型参数与字符串返回，AdminSite URL、dashboard view 和只读权限 handler 补齐 Django 请求/响应与 URL pattern 契约。
- 类型迁移同步发现费率展示字符串多输出一个 `%`，现统一为单个百分号，并以展示函数回归锁定用户可见结果。

## 第四十八批验证结果

- Simulated Trading Admin 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7662 errors / 876 files` 收紧为 `7593 errors / 875 files`，净减少 `69 errors / 1 file`，目标文件历史债务全部归零。
- Admin display metadata、费率展示、自定义 dashboard 路由和全项目路由兼容回归共 `29 passed`；Django system check、Ruff、Black、diff check 通过。

## 第四十九批

- 将已验证的 Django Admin 类型模式推广到 Policy：6 个 `ModelAdmin` 使用 `TYPE_CHECKING` 泛型基类别名绑定具体 ORM Model，43 处展示列/动作动态属性迁移到 `@admin.display` 与 `@admin.action`，保留运行时不可下标 `ModelAdmin` 的兼容性。
- Policy Admin 的展示、批量动作、权限、changelist、queryset 和自定义 AdminSite 全部补齐 `HttpRequest`、`HttpResponse`、`QuerySet[Model]`、具体模型及 `get_app_list(app_label)` 覆盖契约；公共 `_policy_admin_service()` 显式返回 `PolicyAdminInterfaceService`。
- 强类型传播发现审核动作可能把 `reviewer_id=None` 或 `AnonymousUser` 传入 Application/ORM。新增统一持久化管理员校验，未认证或未保存用户现在抛出 `PermissionDenied`，审核记录只接受真实 Django User。

## 第四十九批验证结果

- Policy Admin 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7593 errors / 875 files` 收紧为 `7487 errors / 874 files`，净减少 `106 errors / 1 file`，目标文件历史债务全部归零。两批 Admin 公共根因治理累计清除 `175 errors / 2 files`。
- Policy decorator metadata、匿名审核拒绝、真实 Admin changelist、RSS fetch 与权威源初始化回归共 `10 passed`；Django system check、Ruff、Black、diff check 通过。

## 第五十批

- 将 Admin 类型模式抽成共享 `TypedModelAdmin[Model]` 与 `TypedModelForm[Model]`：类型检查阶段继承 django-stubs 泛型，运行时继承普通 Django 基类并通过 `Generic` 保持可下标，不要求生产环境安装或 monkeypatch django-stubs。
- Account 真实 Admin 入口从动态 `django_apps.get_model()` 改为 public model facade 的具体模型导入，16 个 Admin 与系统设置表单全部使用共享泛型基类；11 处动态 display metadata 迁移到 `@admin.display`，权限和 changelist 补齐 Django 请求/响应契约。
- 删除无任何引用、不会被 Django autodiscover 的 `apps/account/infrastructure/admin.py`；该文件与 `apps/account/interface/admin.py` 重复注册同一批模型，继续补类型只会维持两套实现漂移。
- ModelForm 的 `clean()` 明确处理 Django 允许返回 `None` 的边界，再访问备份密码字段。`AGENTS.md` 新增 Django Admin 类型规范，禁止裸 `ModelAdmin/ModelForm`、旧式动态 metadata 和重复 Admin 注册入口。

## 第五十批验证结果

- Account Interface Admin 与共享 Django Admin typing 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；删除重复 Admin 后，全仓基线从 `7487 errors / 874 files` 收紧为 `7381 errors / 872 files`，净减少 `106 errors / 2 files`。
- 共享泛型运行时、Account 系统设置 Admin、用户管理与路由兼容回归共 `34 passed`；Django system check、Ruff、Black、diff check 通过。

## 第五十一批

- 将共享 `TypedModelAdmin[Model]` 推广到 Events、Alpha Trigger 与 Beta Gate 三个真实 Admin 入口；所有展示列和批量动作改用 Django 官方 `@admin.display` / `@admin.action`，并补齐具体模型、`HttpRequest`、`QuerySet[Model]`、权限 handler 与返回值契约。
- Events 相关事件查询在构造 correlation ID 集合时显式过滤 `None`；不再依赖 ORM 的 `isnull=False` 让静态类型检查器猜测字段已收窄，repository 入口只接收真实字符串标识。
- 新增三模块 Admin 注册与 decorator metadata 回归，锁定共享泛型基类迁移后 Django autodiscover 的真实注册关系和用户可见列标题。

## 第五十一批验证结果

- 三个 Admin 文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7381 errors / 872 files` 收紧为 `7316 errors / 869 files`，净减少 `65 errors / 3 files`，其中 `attr-defined`、`no-untyped-def`、`type-arg` 全部归零。
- Events task、Alpha Trigger repository、Beta Gate activation 与 Admin migration 回归共 `13 passed`；Django system check、Ruff、diff check 通过。

## 第五十二批

- 按“真实风险优先 + 公共契约杠杆”纵向收口 Beta Gate：将 `GateConfig` 的 Regime、Policy、Portfolio 约束改为构造后必定非空的领域不变量，移除 `InitVar is_valid` 与同名 property 的冲突；`GateDecision.evaluated_at` 同样固定为非空 aware datetime。
- Application UseCase 以 selector、event publisher、universe builder Protocol 取代动态依赖；配置查询服务在 ORM 边界构造 `GateConfigViewData` / `GateDecisionViewData`，不再向表单和视图传播 `Any | None`。
- Repository、typed QuerySet、ORM 转换、DRF serializer/form/view 全链路具化。类型传播修复四类真实故障：决策保存不再写入空 `decision_id`；Universe 保存不再因 eager `getattr` fallback 访问不存在的 `created_at`；决策 API 不再对数据库字符串状态调用 `.value`；detail 路径缺少 ID 和 Universe 非整数 `policy_level` 会返回 400，而不是查询字符串 `None` 或触发 500。
- 删除两个无引用的视图内 helper，并把批量评估配置选择器提升为显式 repository adapter；成功响应必须同时持有非空配置，版本回滚也处理目标在查询与激活之间消失的竞态。

## 第五十二批验证结果

- Beta Gate Domain、Application、Infrastructure、Serializer/Form/View 共 9 个生产文件的增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7316 errors / 869 files` 收紧为 `7184 errors / 860 files`，净减少 `132 errors / 9 files`，其中 Beta Gate 本身清除 131 项，并连带清除 Decision Rhythm 1 项未类型调用。
- Beta Gate API edges、领域实体/服务、repository typing contract、激活一致性与 Decision Platform 集成回归共 `66 passed`；Django system check、架构增量门禁 `0 violations`、模块依赖门禁 `199 edges / 0 cycles`，Ruff、Black、diff check 通过。

## 第五十三批

- 按高风险 `call-arg` 与公共事件底座优先收口 Event Store：区分事件总线的“处理结果快照”与事件溯源的“聚合状态快照”，新增不可变 `AggregateSnapshot` 值对象，SnapshotStore 的 latest/exact 读取统一返回正确领域类型。
- 修复原实现把 `snapshot_id/aggregate_type/aggregate_id/version/state/created_at` 传给完全不同的 `EventSnapshot(event/processed_at/handler_id/...)` 所导致的必现运行时 `TypeError`；新增真实数据库保存、latest/exact 读取往返测试。
- Database/InMemory Event Store、SnapshotStore、ReplayHandler 补齐模型、指标字典、构造器和 subscriber 契约。Celery legacy replay 在没有显式 handler class 时现在安全失败；动态 handler 必须继承 `EventHandler`，不再把 `None` 或任意对象传入重放器。

## 第五十三批验证结果

- Event Store 与 Events Domain 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7184 errors / 860 files` 收紧为 `7160 errors / 859 files`，净减少 `24 errors / 1 file`，其中 Event Store 清除 22 项，并连带清除 Account notification 与 Event Bus initializer 各 1 项未类型调用。
- Events task、Aggregate Snapshot 数据库往返和 Events API contract 回归共 `23 passed`；Django system check、架构增量门禁 `0 violations`、Ruff、Black、diff check 通过。

## 第五十四批

- 按高风险 Application 编排优先收口 Alpha provider registry/service：修复 `_get_runtime_qlib_config()` 与导入桥接函数同名造成的无限自递归；Qlib 启用配置现在真正读取 runtime integration，而不是触发 `RecursionError` 后静默跳过 Qlib Provider。
- 修复 fallback 告警误用标准库 `datetime.timezone.now()` 的运行时错误，统一使用 Django aware timezone；该异常此前被非阻塞副作用包装器吞掉，会让既有降级告警无法更新且只留下 debug 日志。
- 将 AlphaMetrics 边界、provider health 可空状态、单例初始化状态、provider filter、attempted providers、用户动态边界和 provider status payload 全部具化；多副作用 tuple lambda 收口为单一 `_record_provider_metrics`，保持 provider 调用、cache hit 与 coverage 指标语义。

## 第五十四批验证结果

- Alpha Application service 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7160 errors / 859 files` 收紧为 `7135 errors / 858 files`，净减少 `25 errors / 1 file`，目标文件全部历史错误码归零。
- Alpha runtime config、fallback alert、providers、interface service、monitoring 与 integration 回归共 `88 passed`；Django system check、架构增量门禁 `0 violations`、Ruff、Black、diff check 通过。

## 第五十五批

- 按高风险密度收口 Policy RSS ingestion：删除 `domain/rules.py` 中与 `domain/entities.py` 重复的 `PolicyLevelKeywordRule` 定义，数据库规则、默认规则和 `PolicyLevelMatcher` 统一使用单一领域类型真源。
- 单源抓取先显式排除不存在/停用 source，再构造非空列表；AI classifier 使用正式 `PolicyClassifierProtocol`，成功结果中的 category、audit status、risk impact 仍为空时回退到明确领域默认值，内容重试前再次验证 classifier 非空。
- Domain `ProxyConfig` 在进入 Infrastructure content extractor 时显式转换为字典；抓取状态更新把可空错误消息收窄为字符串。同步补齐规则归一化 tuple 与仓位配置字典类型，消除公共规则传播的 Any 返回。

## 第五十五批验证结果

- Policy RSS UseCase 与 Domain Rules 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7135 errors / 858 files` 收紧为 `7119 errors / 856 files`，净减少 `16 errors / 2 files`，并连带清除 Policy Application service 2 项参数/赋值债务。
- RSS 两阶段落库、逻辑护栏、Policy workbench integration 与模块结构回归共 `34 passed`；Django system check、架构增量门禁 `0 violations`、Ruff、Black、diff check 通过。

## 第五十六批

- 按“高风险返回契约 + 公共 Repository 杠杆”纵向收口 Hedge：`check_hedge_effectiveness()` 不再用正常/错误两种不兼容的动态字典表达结果，统一返回不可变 `HedgeEffectiveness | None`；Application、Signal 聚合与 API 序列化边界改用显式字段契约。
- Hedge View UseCase 以消费侧 Protocol 固定 pair、correlation、snapshot 与 alert 仓储最小表面；已解决告警筛选不再固定返回空列表，而是由 repository 按 `is_resolved` 真正查询。
- 补齐 `CorrelationHistoryModel.to_domain()`、全部 Hedge ORM 转换和字符串方法类型。未知持久化告警类型改为 `HedgeAlertType.UNKNOWN`，不再错误映射为“相关性失效”。
- 修复 `HedgePerformanceRepository` 使用不存在的 `pair/trade_date/daily_return/volatility/max_drawdown` 字段所导致的必现 `FieldError`；Integration Service 现在构造并持久化与真实模型一致的 `HedgePerformance`，包括期间收益、风险降低、有效性和相关性指标；错位或含零前值的价格序列按共同有效区间计算，不再触发索引或除零异常。

## 第五十六批验证结果

- 9 个变更生产文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7119 errors / 856 files` 收紧为 `7021 errors / 849 files`，净减少 `98 errors / 7 files`，并连带清除 Hedge Interface View 的 3 项未类型调用。
- Hedge 领域、Application、API 与持久化回归共 `99 passed`；Unified Signal 契约传播回归 `4 passed`；Django system check、架构边界 `0 violations`、模块循环回归 `5 passed`，Ruff、Black、diff check 通过。
- 完整架构审计仍报告 11 条既存 audit 债务（4 条共享 Admin import、7 条 Realtime repository provider import），与本批变更无关；普通强制边界规则保持通过。
- Governance consistency 仍报告 2 条既存大文件债务（AI Capability use cases 与 Simulated Trading repository 超过 1200 非空行且未进入允许基线），与本批变更无关。

## 第五十七批

- 按“持久化身份不变量 + Repository 公共杠杆”收口 Agent Runtime handoff/proposal 链：新增 `require_persisted_id()` 领域断言，handoff、提交审批与执行在任何写操作前显式验证数据库身份，不再把 `int | None` 传给 repository 或用 `int(None)` 隐式失败。
- 修正 execution record 的任务关联契约：ORM 明确支持 standalone approved capability，因此 repository 的 `task_id` 同步改为 `int | None`；proposal 关联仍要求真实持久化 ID。Timeline event 的 task 关联按非空模型约束收紧为 `int`。
- Agent Runtime ORM 的领域转换和字符串方法全部补齐返回类型；Operator repository 的 QuerySet、详情、分页、choices 与时间参数具化，动态 values row 在 ORM 边界转换为普通字典。
- Repository provider 使用显式同名导出固定公开类型表面；Interface service 在 ORM 输出边界使用显式 opaque 类型，并统一把 proposal timeline 物化为列表，避免空列表与 QuerySet 复用同一变量。

## 第五十七批验证结果

- 7 个变更生产文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `7021 errors / 849 files` 收紧为 `6929 errors / 843 files`，净减少 `92 errors / 6 files`，并连带清除 Facade、通用 UseCase、Page View、Agent Runtime View 与 Terminal API 的未类型调用。
- Agent Runtime 领域、审批、handoff、operator 与 API 完整联合回归 `164 passed`；Django system check、架构边界 `0 violations`、模块循环回归 `4 passed`。
- Ruff、Black、diff check 通过；Agent Runtime repository 仅剩 2 项 Django plugin `misc` 历史债务，其余高风险、Any 返回和未类型调用债务归零。

## 第五十八批

- 收口 TUI workbench result-model 横向 mixin 的组合契约：通过仅在 `TYPE_CHECKING` 下可见的宿主方法声明，固定整数路径/参数读取、空表格文案与字段人性化方法；运行时类定义和 MRO 保持不变。
- 该模式与已收口的 Catalog mixin 一致，静态检查器现在能验证最终 `TuiWorkbenchService` 的 mixin 组合要求，不需要在任一 mixin 中复制占位实现。

## 第五十八批验证结果

- TUI result-model 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6929 errors / 843 files` 收紧为 `6918 errors / 842 files`，净减少 `11 errors / 1 file`。
- TUI workbench、Terminal Agent、SDK client 与 SSL redirect 固定最小回归包 `229 passed`；Black、Ruff、diff check 通过。

## 第五十九批

- 收口 Policy workbench Application：所有默认 repository 统一通过 Application provider 获取，不再直接构造未标注的 concrete repository；构造器的可空依赖全部使用显式 `T | None`。
- `WorkbenchItemsOutput.items` 改用 `default_factory=list`，消除可空列表和跨实例共享默认值；summary 的兼容输入显式建模为 Optional。
- 旧 Workbench repository 的最后抓取时间在 Application 边界局部收窄为 `Callable[[], datetime | None]`，动态 Infrastructure 类型不再向 `WorkbenchSummary` 传播。

## 第五十九批验证结果

- Policy workbench UseCase 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6918 errors / 842 files` 收紧为 `6901 errors / 841 files`，净减少 `17 errors / 1 file`。
- Policy workbench 单元、结构、集成与 API 回归 `48 passed`；Black、Ruff、diff check 通过。

## 第六十批

- 按“真实执行风险 + 公共 Provider 契约”收口 AI Strategy Executor：改用 AI Provider 与 Prompt 模块正式导出的 factory、DTO 和 repository provider，不再从实现模块导入未公开符号。
- Prompt 策略执行现在注入真实 Macro/Regime adapter；原先传入 `None` 会在模板需要宏观或 Regime 上下文时导致执行失败。
- ApprovalMode 在进入字符串过滤边界前显式转换为枚举值；Prompt/Chain 模式在构造请求前验证必需 ID，缺失配置返回明确错误，不再把 `None` 传播到下游查询。
- Pending approval queue 与可选上下文 loader 补齐容器和调用签名，固定队列元素类型及动态边界。

## 第六十批验证结果

- AI Strategy Executor 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6901 errors / 841 files` 收紧为 `6889 errors / 840 files`，净减少 `12 errors / 1 file`。
- AI Strategy Executor 单元回归 `20 passed`；Black、Ruff、diff check 通过。
- 刷新后债务中 `no-untyped-def/type-arg/no-untyped-call` 共 `5125` 项，约占全部债务 `74%`；`arg-type/return-value/assignment/union-attr` 共 `490` 项，后续优先按真实契约风险治理，而不是按文件机械清扫。
- 公共依赖热点分析显示 Policy repository provider 被 `25` 个生产文件直接引用；其 Infrastructure repository 仍有 `3 arg-type + 3 assignment + 1 return-value`，因此列为下一批高杠杆目标。

## 第六十一批

- 按“高风险错误码 + 公共 Repository 杠杆”收口 Policy repository：`save_event()` 使用 overload 区分默认领域实体与显式 ORM 返回，调用方不再依赖动态返回类型；更新查找结果使用 `ExistingPolicyRecord` 固定持久化 ID 与日期契约。
- ORM `values()` 结果在 Infrastructure 边界局部转换为现有 `dict[str, Any]` 消费契约；近期政策查询补齐 aware `datetime` 参数，RSS source、fetch log、keyword rule 的可空参数、动态 ORM kwargs 与容器元素全部显式建模。
- 最新政策排序不再依赖 Django mypy plugin 无法解析的临时 annotate 字段名，改为语义等价的 `Case` 排序表达式；计数、聚合、删除与更新结果在 ORM 边界收窄为 `int` / `bool`。

## 第六十一批验证结果

- Policy repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6889 errors / 840 files` 收紧为 `6865 errors / 839 files`，净减少 `24 errors / 1 file`。
- 目标文件的 `3 arg-type + 3 assignment + 1 return-value` 等 22 项债务全部清零，并连带清除 Policy repository provider 与 Decision Rhythm feature provider 各 1 项 `no-untyped-call`，验证了公共契约修复的跨模块杠杆。
- Policy integration、Signal policy influence 与 RSS/Sentiment repository 回归共 `41 passed`；Ruff、Black、diff check 通过。

## 第六十二批

- 按高风险错误密度收口 Sentiment repository：日志 provider/model/response time/source ID 与 cache clear 文本参数改为显式可空；告警 metadata、JSON keywords 和 sector sentiment 在 ORM/JSON 边界完成类型收窄。
- `SentimentIndex.index_date` 现在严格按领域 `datetime` 转为 ORM `date`，读取时恢复为 UTC-aware `datetime`；修复原先 `datetime.combine()` 产生 naive datetime、违反 `USE_TZ=True` 的真实时间比较风险。
- ORM count/delete 与动态 ConfigHelper 返回在 Infrastructure 边界收窄为 `int` / `float`，provider 消费方不再接收 `Any`。

## 第六十二批验证结果

- Sentiment repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6865 errors / 839 files` 收紧为 `6856 errors / 838 files`，净减少 `9 errors / 1 file`。
- 目标文件的 `7 assignment + 1 type-arg` 全部清零，并连带清除 Sentiment interface service 1 项 `arg-type`。
- Sentiment 单元与 Decision Rhythm feature provider 回归共 `56 passed`；新增 UTC-aware index date 断言，Ruff、Black、diff check 通过。

## 第六十三批

- 按“公共 ORM→Domain 转换 + Repository 返回契约”纵向收口 Rotation：两个 `to_domain()` 与全部 ORM `__str__()` 补齐返回类型，JSON asset universe、strategy params、regime allocations 与 momentum periods 在模型边界收窄为领域类型。
- Rotation Interface Repository 的 QuerySet、template/config、choice、导出行和页面字典全部具化；声明返回 `list` 的 Signal、Momentum、Portfolio 查询现在真正物化列表，不再把 lazy QuerySet 冒充 list。
- URL/query 中的 account/config 标识在进入关系字段查询前显式转换为整数；非法标识返回空结果，修复原先可能由 Django field conversion 抛出 `ValueError` 并形成 500 的风险。

## 第六十三批验证结果

- Rotation models/repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6856 errors / 838 files` 收紧为 `6799 errors / 836 files`，净减少 `57 errors / 2 files`。
- Rotation repository 38 项、models 9 项全部清零，并连带让 Application interface service 的 `no-untyped-call` 从 14 项降到 4 项，再减少 10 项公共契约传播债务。
- Rotation Repository/Integration、分页排序与 API edges 回归共 `31 passed`；新增非法关系过滤器回归，Ruff、Black、diff check 通过。

## 第六十四批

- 按“公共 API 输入输出边界 + 高风险 assignment”收口 Equity serializers：全部 DRF `Serializer` 声明实例泛型，响应 serializer 使用真实 Application Response DTO，输入与 JSON payload 使用字典边界，估值配置 ORM 兼容边界局部保留 `Any`。
- `source` 与 `errors` 这 5 个 API 字段会与 DRF `Field.source` / `Serializer.errors` 基类属性发生静态覆盖冲突；改由 `get_fields()` 注册，保留外部 JSON 字段名、required/default/allow_null 行为，不使用 `type: ignore`。
- 首次统一为 `dict` 泛型后，全仓门禁准确拦截 Analysis/Config 调用方新增的 7 项 `arg-type`；随后按真实 DTO/ORM instance 类型修正，证明增量文件归零不能替代全仓传播门禁。

## 第六十四批验证结果

- Equity serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6799 errors / 836 files` 收紧为 `6756 errors / 835 files`，净减少 `43 errors / 1 file`，且跨文件无新增。
- 目标文件的 `5 assignment + 2 no-untyped-def + 36 type-arg` 全部清零。
- 保留字段名契约测试 `5 passed`；Equity API、Valuation Repair API 与配置集成回归 `44 passed`；Ruff、Black、diff check 通过。

## 第六十五批

- 按同类公共 API 边界收口 Audit serializers：StrictFields 输入校验与全部普通 serializer 声明 `dict[str, Any]` instance 契约，三个 validate/to_internal_value 方法补齐输入输出和 DRF 动态返回收窄。
- Operation Log/Query/Ingest 与 Decision Trace 的 `source`、Export Operation Logs 的 `data` 会覆盖 DRF 基类属性；统一通过 `get_fields()` 注册，保持既有外部字段名、默认值和可选行为，不新增 ignore。
- 与 Equity 响应 DTO 场景不同，Audit 的真实调用方全部传入字典/read-model payload；全仓传播门禁确认该泛型不会收窄跨文件调用。

## 第六十五批验证结果

- Audit serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6756 errors / 835 files` 收紧为 `6728 errors / 834 files`，净减少 `28 errors / 1 file`。
- 目标文件的 `5 assignment + 3 no-untyped-def + 20 type-arg` 全部清零，跨文件无新增。
- 字段契约、Audit API edges、内部日志写入、阈值验证/配置和归因治理回归共 `27 passed`；Ruff、Black、diff check 通过。

## 第六十六批

- 按 Policy API/Workbench/RSS 公共边界收口 serializers：输入和 read-model 使用字典 instance，PolicyEvent 与 WorkbenchSummary 使用真实领域实体，PolicyLog/RSS Source/Keyword/FetchLog 作为 ORM 边界局部使用 `Any`。
- `PolicyLevelField` 显式建模 `object -> PolicyLevel -> str` 往返；OpenAPI schema decorator 通过保留函数签名的 typed wrapper 使用，不再让两个 SerializerMethodField 退化为 untyped。
- Policy/Create、RSS Fetch、Workbench Fetch 的 `errors` 及 RSS Fetch Log 的 `source` 改由 `get_fields()` 注册，保留既有外部字段名和 required/read-only 语义；WorkbenchSummary 直接读取领域枚举，不再动态 getattr/hasattr。

## 第六十六批验证结果

- Policy serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6728 errors / 834 files` 收紧为 `6678 errors / 833 files`，净减少 `50 errors / 1 file`，跨文件无新增。
- 目标文件的 `4 assignment + 2 misc + 11 no-untyped-def + 33 type-arg` 全部清零。
- Policy 字段/枚举契约、Policy API edges 与完整 Workbench API 回归共 `34 passed`；Ruff、Black、diff check 通过。

## 第六十七批

- 按 Prompt 模板、链执行与 Agent Runtime 公共 API 边界收口 serializers：输入和普通 JSON payload 使用字典 instance，执行响应使用真实 Application DTO，Prompt/Chain 的领域与 ORM 兼容输出边界局部使用 `Any`。
- PromptTemplate/ChainConfig 的构建、验证、更新和领域枚举序列化补齐显式契约；Application facade 的动态返回仅在 Interface 边界收窄，不向调用方传播 `Any`。
- Placeholder 的 `required` 与 Chat/ChatSession 的 `context` 会覆盖 DRF 基类状态属性；统一通过 `get_fields()` 注册，保持既有外部字段名、默认值、读写方向与 JSON 行为。

## 第六十七批验证结果

- Prompt serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6678 errors / 833 files` 收紧为 `6631 errors / 832 files`，净减少 `47 errors / 1 file`，跨文件无新增。
- 目标文件的 `3 assignment + 6 no-untyped-call + 16 no-untyped-def + 19 type-arg + 3 union-attr` 全部清零。
- `required/context` 字段契约与 Prompt API edges 回归共 `13 passed`；mypy 治理护栏 `10 passed`，架构增量门禁 `1 file / 89 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第六十八批

- 按 Agent 协议的批量输入边界收口 Broker Execution serializers：所有 preview/commit、Agent 心跳、租约、事件、快照与命令 payload 统一声明字典 instance，六个跨字段验证器补齐显式输入输出契约。
- 事件、持仓、快照订单与成交批次改为显式 `ListField(child=...)`，保留 200/5000 条上限和嵌套校验语义，同时消除 nested serializer 构造参数不受类型桩支持的问题。
- 快照订单的默认成交数量由整数 `0` 改为 `Decimal("0")`，使默认值与 `DecimalField` 的运行时和静态契约一致。

## 第六十八批验证结果

- Broker Execution serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6631 errors / 832 files` 收紧为 `6592 errors / 831 files`，净减少 `39 errors / 1 file`，跨文件无新增。
- 目标文件的 `1 arg-type + 4 call-arg + 10 no-untyped-call + 11 no-untyped-def + 13 type-arg` 全部清零。
- Broker 权限/API、Agent 事件批次与完整 Fake Agent 事件/快照流程回归共 `30 passed`；mypy 治理护栏 `10 passed`，当前联合改动的架构增量门禁 `2 files / 133 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第六十九批

- 按 Alpha 评分上传与执行结果公共 API 边界收口 serializers：请求 payload 使用字典 instance，StockScore/AlphaResult 输出与创建使用真实领域实体，StrictFields 的动态 DRF 返回在 Interface 边界显式收窄。
- 修复 `AlphaResultSerializer.create()` 把公开字段 `stocks` 原样传给领域构造器的必现 `TypeError`；现在明确转换为领域字段 `scores`，并新增真实 `.save()` 回归。
- 三个公开 `source` 字段通过 `get_fields()` 注册，保留评分、结果与上传 API 字段名和默认值，同时避免覆盖 DRF `Field.source`；批量评分改为显式 `ListField(child=...)` 并保持 1000 条上限。

## 第六十九批验证结果

- Alpha serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6592 errors / 831 files` 收紧为 `6579 errors / 830 files`，净减少 `13 errors / 1 file`，跨文件无新增。
- 目标文件的 `3 assignment + 2 call-arg + 1 no-untyped-def + 7 type-arg` 全部清零。
- Alpha serializer 创建/默认值、上传权限与用户隔离、Alpha API edges 回归共 `27 passed`；mypy 治理护栏 `10 passed`，当前联合改动的架构增量门禁 `3 files / 180 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十批

- 按动态 ORM registry 与 DRF 输出边界收口 Agent Runtime serializers：全部 ModelSerializer 声明显式动态 ORM instance，全部请求/查询/错误 serializer 声明字典 payload。
- 保持 Interface 层不导入 Infrastructure 模型；运行时 `django_apps.get_model()` 返回值不再被误当作静态类型别名，四个反向关系计数在动态 ORM 边界显式收窄为整数。
- 新增独立 serializer 契约测试，覆盖 steps、proposals、artifacts 与 timeline events 四个计数器。

## 第七十批验证结果

- Agent Runtime serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6579 errors / 830 files` 收紧为 `6550 errors / 829 files`，净减少 `29 errors / 1 file`，跨文件无新增。
- 目标文件的 `4 attr-defined + 4 no-any-return + 17 type-arg + 4 valid-type` 全部清零。
- Agent Runtime serializer、API、RBAC 与真实 repository 组装回归共 `43 passed`；mypy 治理护栏 `10 passed`，当前联合改动的架构增量门禁 `4 files / 393 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十一批

- 按 AI Capability routing、MCP governance 与 Web Chat 公共 API 边界收口 serializers：普通请求和 read-model payload 使用字典 instance；Capability summary 的 `many=True` 调用保持局部动态边界，避免把 DRF stub 的列表构造限制传播到调用方。
- MCP verification 的 `label/detail`、Route/Web Chat 的 `context`、Suggested Action 的 `label/description` 与 Answer Chain 的 `label` 统一通过 `get_fields()` 注册，保持既有公开字段、默认值和读写语义，同时避免覆盖 DRF Field/Serializer 内部属性。
- 完整传播扫描曾准确暴露 Capability list 调用方的 1 项 `arg-type`；最终通过收窄 serializer 的多实例动态边界消除，不把 API View 的既存历史债务纳入本批或新增 ignore。

## 第七十一批验证结果

- AI Capability serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6550 errors / 829 files` 收紧为 `6529 errors / 828 files`，净减少 `21 errors / 1 file`，跨文件无新增。
- 目标文件受管的 `2 assignment + 19 type-arg` 全部清零；直接 strict 检查同时确认所有公开字段覆盖冲突均已消除。
- 字段契约、AI Capability routing/API use cases 与 API edges 回归共 `27 passed`；mypy 治理护栏 `10 passed`，架构增量门禁 `1 file / 69 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十二批

- 扩大为 Account Interface 同 App 双文件收口：主 serializers 的动态 ORM ModelSerializer 使用显式 `Any` instance，普通 ledger、统计、宏观仓位与 MCP payload 使用字典 instance；classification serializers 同步补齐分类树、币种、汇率与配置统计契约。
- 删除主 serializers 中 33 个已经失效的行级 `type: ignore`，包括 ModelSerializer、普通 Serializer 与 Django timezone/import 边界；不以新增 ignore 替代类型治理。
- Position 的 `source`、Observer Grant 的 `is_valid` 与 MCP access-level 的 `label` 通过 `get_fields()` 注册，保留公开字段且避免覆盖 DRF 内部状态；Position 的 `many=True` 列表输出保持局部动态边界，完整传播门禁不再向 Portfolio API View 新增 `arg-type`。
- 分类树动态反向关系在 ORM 边界具化，ExchangeRate 校验参数改用 Decimal；新增 Account serializer 字段契约测试。

## 第七十二批验证结果

- Account 主 serializers 与 classification serializers 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6529 errors / 828 files` 收紧为 `6453 errors / 826 files`，净减少 `76 errors / 2 files`，跨文件无新增。
- 主文件的 `2 assignment + 31 type-arg + 33 unused-ignore` 与分类文件的 `2 no-untyped-def + 8 type-arg` 全部清零。
- Account 字段契约、API/Profile edges、分类/汇率、观察者权限与 MCP 自助页面回归共 `71 passed`；mypy 治理护栏 `10 passed`，当前第七十一、七十二批联合架构增量门禁 `3 files / 198 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十三批

- 按 Strategy 配置、仓位规则与执行查询公共 API 边界收口 serializers：动态 registry 获取的 ORM ModelSerializer 使用显式 `Any` instance，普通请求与响应 payload 使用字典 instance，所有验证器补齐精确输入输出契约。
- `PositionManagementEvaluateInputSerializer.context` 改由 `get_fields()` 注册，保留公开 JSON 字段名和写入语义，同时避免覆盖 DRF Serializer 的内部 context 状态。
- OpenAPI method-field decorator 通过保留函数签名的 typed wrapper 使用；规则计数在动态 ORM 边界显式收窄为整数，严格参数 serializer 的动态返回在 Interface 边界局部收窄。
- 新增 Strategy serializer 契约测试，覆盖仓位评估 context、未知参数拒绝、当前日期执行和规则计数。

## 第七十三批验证结果

- Strategy serializers 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6453 errors / 826 files` 收紧为 `6414 errors / 825 files`，净减少 `39 errors / 1 file`，跨文件无新增。
- 目标文件的 `1 assignment + 3 misc + 1 no-any-return + 20 no-untyped-def + 14 type-arg` 全部清零。
- Strategy serializer 契约与 API edges 回归共 `16 passed`；mypy 治理护栏 `10 passed`，架构增量门禁 `1 file / 216 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十四批

- 扩大为 Data Center 与 Decision Rhythm 两个公共 API serializer 文件联合收口：普通请求 payload 使用字典 instance，领域实体输出保留精确方法参数，兼容 `many=True` 的列表输出在 DRF 构造边界局部使用动态 instance。
- Data Center 的 provider 配置脱敏方法补齐递归 JSON 边界与具体字典返回类型，并删除 3 个已失效的 override ignore；Capital Flow 严格查询的动态 DRF 返回在 Interface 边界显式收窄。
- Decision Rhythm 的四个领域枚举字段具化 DRF Field 泛型，Quota、Cooldown 与 Decision Request 输出方法声明真实领域实体；五个请求字段验证器补齐字符串输入输出。
- 完整传播扫描曾识别 Data Center、Macro 和 Decision Rhythm 六个调用文件中的 10 个 `many=True` 列表构造类型冲突；最终通过 serializer 的局部动态 instance 契约消除，调用方无新增债务。
- 新增两个 serializer 契约测试文件，覆盖递归密钥脱敏、Capital Flow 未知参数/日期顺序、领域枚举往返以及 priority、quota period、execution target 标准化。

## 第七十四批验证结果

- Data Center 与 Decision Rhythm serializers 增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6414 errors / 825 files` 收紧为 `6352 errors / 823 files`，净减少 `62 errors / 2 files`，跨文件无新增。
- Data Center 的 `1 no-any-return + 3 no-untyped-def + 26 type-arg + 3 unused-ignore` 与 Decision Rhythm 的 `5 no-untyped-def + 24 type-arg` 全部清零。
- 两组 serializer 契约与 API edges 回归共 `42 passed`；mypy 治理护栏 `10 passed`，架构增量门禁 `2 files / 65 added lines / 0 violations`，Ruff、Black、diff check 通过。

## 第七十五批

- 按 Simulated Trading 账户、持仓、交易、巡检、绩效和估值公共 API 边界联合收口两个 serializer 文件：普通请求与 read-model payload 统一声明 `dict[str, Any]` instance，绩效日期查询和基准成分列表验证器补齐具体容器签名。
- 主 serializers 的 26 项 `type-arg` 与 performance serializers 的 21 项 `type-arg` 全部清零；两个文件的增量 mypy 均为 `0 errors / 0 legacy errors / 0 regressions`。
- 新增 serializer 契约测试，覆盖初始资金 Decimal、批量删除正整数约束、绩效日期顺序和非空基准成分。
- 全仓债务基线从 `6352 errors / 823 files` 精确收紧为 `6305 errors / 821 files`，净减少 `47 errors / 2 files`。

## 第七十五批验证结果

- 新建仓库内 `agomtradepro/` Python 3.12 venv，并从 `pyproject.toml` 安装完整 `.[all]` 依赖；Django `5.2.16`、DRF `3.17.1`、Qlib `0.9.7`、LightGBM `4.7.0` 和 mypy `1.14.1` 可导入，`pip check`、Django system check、migration dry-run 与依赖投影检查通过。
- 本地 NumPy 使用仍满足项目约束的 `2.2.6`，避免 NumPy 2.5 类型桩的 Python 3.12-only type statement 与项目 mypy `python_version = 3.11` 冲突；目标文件增量 mypy 为 `0 errors / 0 regressions`。
- Serializer 契约与 Account Performance API 回归 `53 passed`；mypy 治理脚本单测 `6 passed`；Black 与 Ruff 通过。
- Simulated Trading API edges 联合回归最初为 `58 passed / 1 failed`；后续修复 `UnifiedPositionService` 默认全平仓路径的 `float × Decimal` 运算并增加回归，目标单元与 API edges 合计 `11 passed`；目标文件 mypy 再减少 `1 arg-type + 1 no-untyped-def`，全仓基线收紧到 `6303 errors / 821 files`。
- Governance consistency 最初因两个 HEAD 已存在的未登记大文件失败；后续为 `apps/ai_capability/application/use_cases.py` 与 `apps/simulated_trading/infrastructure/repositories.py` 补齐 owner、拆分类型、目标、优先级和 review date，未放宽全仓 1200 行阈值。
- 当前 `pyproject.toml` 锁定 mypy `1.14.1`，但已提交的全仓债务基线无法由该版本完整复现；隔离 mypy `1.17.1` 扫描仍受 11 个第三方类型环境差异影响。为避免虚假大幅降债，本批仅删除两个已定向清零的 baseline 条目，未接受环境性计数变化。

## 第七十六批

- 按“Strategy 公共 Application 契约 + 跨模块执行传播”纵向收口：新增 `interface_contracts`，用 Protocol 明确 Strategy interface repository、assignment、execution log、executor 与 portfolio provider 契约；ORM QuerySet 仅在 DRF 动态边界保留显式 `Any`。
- Strategy repository provider 不再向 Application 类型面暴露具体 Infrastructure 返回类型；Infrastructure provider 的仓储 re-export 改为显式导出，模拟盘 facade 懒加载、执行适配器输入和工厂返回全部具化。
- 修正 `StrategyExecutionGateway` 的旧协议：实际 executor 接收 `portfolio_id` 并返回 `StrategyExecutionResult`，执行时间契约恢复为 timezone-aware `datetime`；完整传播扫描同步清除 Prompt Gateway 及 7 个 Strategy Interface 调用方的无类型调用债务。
- 收口 `UnifiedPositionService` 的 repository/mutation Protocol、容器和生命周期方法返回类型；加仓合并前统一将生产仓储返回的 float 数量量化为 Decimal，修复 `float + Decimal` 的运行时风险；构造 `SimulatedTrade` 时仅在领域实体边界转回 float。

## 第七十六批验证结果

- 6 个变更生产文件增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6303 errors / 821 files` 收紧为 `6199 errors / 816 files`，净减少 `104 errors / 5 files`，跨文件无新增。
- Strategy provider/serializer/API、绑定与执行、Gateway/Executor，以及统一仓位生命周期回归共 `61 passed`；mypy 治理与仓库治理契约 `12 passed`。
- 全仓架构扫描 `1848 files / 0 violations`；Ruff、Black 与 diff check 通过。

## 第七十七批

- 继续沿 Strategy 纵向主线收口核心 Infrastructure repository：Strategy、Rule Condition、Execution Log、Param Version、Order Intent、Gateway 与 Interface Repository 的 ORM→Domain、QuerySet、动态模型、容器及返回契约全部具化。
- Strategy Interface Repository 的关联查询继续使用既有 `select_related`，并为各模型 QuerySet、分页结果、配置列表、assignment 与 execution log 明确具体泛型；不把 lazy QuerySet 冒充 list，也不在 Application/Interface 新增 Infrastructure 依赖。
- 动态 Portfolio OrderIntent 模型保留在明确的 `Any` ORM registry 边界，仓储通过结构化协议兼容；两个 feature flag 改为安全的 `getattr` 布尔读取，保存主键、删除/更新计数和 research promotion 结果在 Infrastructure 边界收窄。
- OrderIntent 的 Decision/Sizing/Risk Snapshot JSON→Domain 映射拆入独立 mapper，主 repository 从治理扫描的 1238 个非空行降至 1197 行，不新增大文件例外。
- 新建 Rule Condition 现在显式要求 `strategy_id`，避免把 Domain 的可空草稿状态传入非空数据库外键；参数 JSON、Decision/Sizing/Risk Snapshot 与 Position Rule context 均使用具化字典契约。

## 第七十七批验证结果

- Strategy repository 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6199 errors / 816 files` 收紧为 `6138 errors / 815 files`，净减少 `61 errors / 1 file`，跨文件无新增。
- OrderIntent 幂等、分页排序、策略绑定/执行与 Strategy API edges 回归共 `31 passed`。
- 全仓架构扫描 `1848 files / 0 violations`，governance consistency `29 passed`；Ruff 与 Black 通过。

## 第七十八批

- 按 Data Center 宏观数据入口收口 AKShare adapter：延迟加载的 AKShare 模块、各指标 fetcher、支持指标映射、生命周期方法与公开 `fetch()` 返回值全部具化，不再向 Provider、Failover 和连接测试传播无类型调用。
- 原始 fetcher 结果先停留在明确的 `object` 边界，再统一验证为 `list[MacroDataPoint]`；非列表或混入非领域实体的结果会抛出 `DataSourceUnavailableError`，避免第三方或自定义 fetcher 的动态值静默进入 Application。
- 移除仅用于名义继承、但在 `follow_imports=skip` 下退化为 `Any` 的 `BaseMacroAdapter` 基类；将其数据点校验、排序与日期去重语义原样保留在 adapter 内，未改变公开构造与调用方式。
- 新增 AKShare adapter 契约测试，参数化覆盖 `SUPPORTED_INDICATORS` 的全部路由，并覆盖非法返回类型、非法元素类型、字段校验、排序及同日去重。

## 第七十八批验证结果

- AKShare adapter 增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6138 errors / 815 files` 收紧为 `6071 errors / 814 files`，净减少 `67 errors / 1 file`，跨文件无新增。
- 目标文件的 `54 no-any-return + 10 no-untyped-def` 全部清零；同时清除 Provider adapter、Failover adapter 与连接测试传播的 `3 no-untyped-call`。
- AKShare 路由/契约、既有 adapter、fetcher 韧性、财务与日期处理、Data Center provider adapter 回归共 `155 passed`。
- 全仓架构扫描 `1849 files / 0 violations`；governance baseline 升级为 `2026-07-23.v162`，静态测试函数计数提升至 `7171`，governance consistency `35 passed`；Ruff 与 Black 通过。

## 第七十九批

- 按“Account portfolio API Application 边界 + Simulated Trading 组合根”纵向收口：新增 `portfolio_api_contracts`，用 Protocol 明确 Portfolio、Legacy/Unified Position、Observer Grant、迁移映射、可访问 QuerySet、读仓储、写仓储与统一持仓生命周期契约。
- `portfolio_api_services` 不再通过无类型 helper 调用 ORM/跨 App 实现；QuerySet 仅保留 `select_related`、`filter` 与迭代所需的最小 Application 契约，Portfolio/Position 实体只暴露编排实际使用的字段，没有新增 Infrastructure import 或 ORM 访问。
- 创建、校准、删除、全量/部分平仓、legacy bootstrap、observer access 与只读查询统一使用具化端口；`None / ""` 组合参数改为显式分支收窄，账户到 Portfolio 的映射和 observer 列表使用具体容器类型。
- Simulated Trading gateway 使用泛型 `_require` 保留已注册 provider 的实际 Callable 类型；portfolio repository 与 unified position service 工厂改为显式跨 App Protocol，组合根在具体实现实例化处完成局部 cast，避免动态工厂返回继续向 Account API 传播 `Any`。

## 第七十九批验证结果

- 4 个目标生产文件增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6071 errors / 814 files` 收紧为 `6012 errors / 811 files`，净减少 `59 errors / 3 files`，跨文件无新增。
- `portfolio_api_services` 的 `2 arg-type + 5 no-any-return + 40 no-untyped-call + 7 no-untyped-def` 全部清零；Account gateway 的 `2 no-any-return` 与 Simulated Trading composition root 的 `3 no-untyped-def` 同步清零。
- Account portfolio/position、观察者权限、统一账本、更新/平仓、只读查询、手工成交同步、Unified Position Service 与 Simulated Trading API edges 回归共 `57 passed`。
- 全仓架构扫描 `1850 files / 0 violations`；governance consistency、repository governance 与 Account repository structure `38 passed`；Ruff、Black 与 diff check 通过。

## 第八十批

- 按“Decision Rhythm Interface 依赖组装 + Submit/Quota Application 契约”纵向收口：将 `interface/dependencies.py` 中对 5 个 App Infrastructure 的动态组装迁入既有 App 级 `composition.py`，Interface 只保留稳定兼容重导出，不再直接解析或构造 Infrastructure repository。
- composition root 为 Decision Request read/write、Quota query/management、Cooldown、Account、Candidate tracking、Unified Recommendation 与资产名称解析建立具化 Protocol；跨 App 动态加载仅停留在组合边界，并在具体实现进入 Application 前局部收窄。
- 修复预检查构造器传入不存在的 `beta_gate_repo` 参数导致端点直接 `TypeError/500` 的运行时缺陷；当前 builder 仅注入构造器真实支持且实际执行的 Candidate、Quota 与 Cooldown 仓储。
- 收口 Decision Quota、Management 与 Submit Workflow 的 Rhythm/Quota/Scheduler、事件发布、Request write、Recommendation write 和 Candidate tracking 契约；所有构造器、内部事件方法与返回投影具化，不把组合根错误迁移为新的 Application 债务。
- 新增 composition/re-export 与 precheck builder 契约测试；将集成测试从容忍 `400/404/500` 收紧为候选不存在时必须返回 `200`、`candidate_valid=false` 和明确业务错误。

## 第八十批验证结果

- 5 个目标生产文件增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `6012 errors / 811 files` 收紧为 `5931 errors / 807 files`，净减少 `81 errors / 4 files`，跨文件无新增。
- Decision Quota 的 `1 no-any-return + 9 no-untyped-def`、Management 的 `2 no-untyped-def`、Submit Workflow 的 `3 no-any-return + 4 no-untyped-def`、Interface dependencies 的 `1 call-arg + 47 no-untyped-call + 13 no-untyped-def` 全部清零；完整传播额外清除 Workflow API View 的 `1 attr-defined`。
- Composition、Decision Rhythm API edges、Submit/Quota workflow、Domain service、Decision execution、集成执行闭环与错误映射回归共 `90 passed`。
- 全仓架构扫描 `1850 files / 0 violations`；governance baseline 升级为 `2026-07-23.v163`，静态测试函数计数提升至 `7173`；governance consistency、repository governance 与 Decision Rhythm 反向依赖/仓储/用例结构 `45 passed`；Ruff、Black 与 diff check 通过。

## 第八十一批

- 按“Regime 核心宏观输入边界 + Application 用例传播”纵向收口：Data Center 宏观事实适配器、PIT 查询、CPI 口径归一、数据源配置、同步任务 Gateway 与 Repository Provider 的动态 ORM/JSON 边界全部显式收窄。
- `DjangoDataSourceConfig`、`DataCenterMacroRepositoryAdapter`、`DjangoMacroDataProvider` 与兼容 `MacroRepositoryAdapter` 的指标映射、缓存、日期和值序列、查询结果及生命周期方法全部具化；ORM Model/QuerySet 仅在 Infrastructure 边界保留局部 `Any`。
- Application 新增最小 `MacroRepositoryAdapterProtocol`，明确增长/通胀序列、完整观测、精确日期、最近观测及可用日期契约；编排层不再调用 provider 私有 `_get_repository()`，统一从 composition provider 获取稳定端口。
- Regime 高频信号、收益率曲线、冲突解决、V1 历史回算和 V2 主用例构造器全部使用结构化端口；运行时阈值配置与历史快照回退也改为最小 Protocol，响应 JSON 容器和缺失数据填充结果具化。
- Infrastructure provider 显式重导出诊断仓储；Celery signature 返回限定在动态任务边界，避免名义 Protocol 在 `follow_imports=skip` 下退化为 `Any` 并继续传播。

## 第八十一批验证结果

- 4 个直接目标文件增量 mypy 为 `0 errors / 0 legacy errors / 0 regressions`；全仓基线从 `5931 errors / 807 files` 收紧为 `5829 errors / 801 files`，净减少 `102 errors / 6 files`，跨文件无新增。
- Macro provider 的 `3 assignment + 5 no-any-return + 20 no-untyped-call + 16 no-untyped-def + 12 type-arg`、Repository Provider 的 `1 attr-defined + 5 no-untyped-def`、Regime Use Cases 的 `4 assignment + 2 no-untyped-call + 5 no-untyped-def + 1 return-value + 8 type-arg + 1 var-annotated` 与 Sync Gateway 的 `1 no-untyped-def` 全部清零。
- 完整传播额外清除 `current_regime`、`interface_services`、`navigator_use_cases`、`orchestration`、`query_services` 与 `recalculate_regime` 的 `18 no-untyped-call`；Regime/Data Center provider、guardrail、PIT selection、orchestration、V2 domain、workflow 与 API edges 回归 `54 passed`。
- 全仓硬边界扫描 `1850 files / 0 violations`；mypy debt ceiling、Ruff、Black 与 diff check 通过。
- 治理/架构联合测试为 `52 passed / 1 failed`：失败来自 audit 模式识别出的 11 个既存软违规（4 个 Interface Admin 引用共享 typed-admin 基类、7 个 Realtime Application provider 引用 Infrastructure repository），不属于本批改动且硬边界扫描仍为零；该高影响架构债务列为下一批优先整改对象。

## 第八十二批

- 优先清除第八十一批暴露的 11 个全仓架构 audit 违规：将 Realtime 的价格仓储、价格源链、watchlist、告警、订阅与 Channels notifier 具体组装从 `application/repository_provider.py` 迁入 App 根级 `composition.py`。
- Application repository provider 保留原公开函数名的稳定重导出，Interface、Celery、轮询服务与跨 App 注册调用无需依赖具体 Infrastructure，也不破坏既有导入契约。
- 修正 Interface audit 规则与项目 Admin 强制规范之间的冲突：仅精确放行 `shared.infrastructure.django_admin` 技术适配器，继续禁止 Interface 导入任何业务 App Infrastructure；新增规则单测证明共享 typed-admin 被允许而具体仓储仍被拦截。
- 没有通过豁免 Realtime 或降低审计严格度掩盖真实问题；7 个 Realtime Application→Infrastructure import 已从源代码实际移除。

## 第八十二批验证结果

- 全仓架构扫描从 `1850 files / 0 boundary / 11 audit violations` 收口为 `1851 files / 0 boundary / 0 audit violations`，上一批遗留的架构联合测试失败已消除。
- Realtime watchlist、HTTP views、tasks、Data Center/AKShare provider、Celery 注册、轮询、WebSocket、仓储、readiness、告警、交付链路与 API 回归 `84 passed / 1 skipped`。
- Architecture tooling/boundaries、governance consistency 与 repository governance `54 passed`；governance baseline 升级为 `2026-07-23.v164`，静态测试函数计数提升至 `7174`。
- Realtime composition 与兼容 provider 增量 mypy 为零；本批是架构债务收口，不虚报 mypy 数量下降，全仓债务基线保持 `5829 errors / 801 files`。
- Ruff、Black、完整 mypy debt ceiling 与 diff check 通过。

## 第八十三批

- 沿第八十二批建立的 Realtime composition 边界继续纵向清零整个模块：Domain 实体 JSON 投影、价格更新服务时间契约、Celery 任务、DRF serializers、Token authentication、OpenAPI extension、WebSocket authentication/consumer 与 Infrastructure 动态边界全部具化。
- DRF 输入 serializer 使用具体字典泛型，领域实体输出停留在明确的动态 instance 边界；`source` 公开字段通过 `get_fields()` 注册，避免覆盖 DRF `Field.source` 内部状态。
- Channels、Celery 与 drf-spectacular 缺少完整类型元数据的位置仅使用错误码级局部 ignore；Settings feature flag 改为安全 `getattr`，AKShare 模块和 watchlist 返回在 Infrastructure 边界完成运行时校验/收窄。
- 发现并删除 `apps/realtime/interface/__init__.py` 中误复制的整套 Regime Celery 任务；真实任务已由 `apps/regime/application/tasks.py` 提供，Realtime Interface 包入口恢复为无副作用声明，消除潜在重复任务注册和虚假 Realtime→Regime 依赖。

## 第八十三批验证结果

- Realtime 目标目录直接 mypy 为零；全仓基线从 `5829 errors / 801 files` 收紧为 `5795 errors / 792 files`，净减少 `34 errors / 9 files`，整个 Realtime 模块退出 mypy 债务基线。
- 清零项包括 `7 misc + 4 import-untyped + 7 no-untyped-def + 1 no-any-return + 1 assignment + 14 type-arg`，完整传播无新增。
- Realtime watchlist、views、tasks、provider、Celery 注册、轮询、WebSocket、仓储、readiness、告警、交付与 API 回归 `84 passed / 1 skipped`。
- 删除错误的 Regime 任务副本后，App import edge 从 `199` 降至 `198`、Realtime outbound 从 `3` 降至 `2`、Regime inbound 从 `23` 降至 `22`；module cycle baseline 收紧为 `2026-07-23.v15`，`0 bidirectional pairs / 0 cycles / 0 stale budgets`。
- 全仓扫描 `1851 files / 0 boundary / 0 audit violations`；architecture boundaries `4 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十四批

- 按“AI Provider 公共管理 API + 系统模型配置入口”收口 admin provider、personal provider、usage log、当前配额与管理员批量配额六组 DRF ViewSet。
- 所有 ViewSet 具化 DRF instance 泛型，list/retrieve/create/update/partial update/destroy、自定义 action、请求参数、路由主键、可变参数和 Response 返回契约全部显式声明。
- Provider 列表输出不再依赖无类型 helper：`_get_provider_or_404()` 返回具体 `ProviderListItemDTO`，公开投影使用 `dict[str, Any]` JSON 边界；配额 Decimal→float 转换声明可空输入输出。
- 动态 serializer class 选择保留在 DRF framework 边界，不向 Application 传播 `Any`；View 继续只调用既有 Application UseCase，没有新增 ORM、Infrastructure import 或业务规则。

## 第八十四批验证结果

- AI Provider API View 直接 mypy 为零；全仓基线从 `5795 errors / 792 files` 收紧为 `5734 errors / 791 files`，净减少 `61 errors / 1 file`，跨文件无新增。
- 目标文件的 `26 no-untyped-call + 29 no-untyped-def + 6 type-arg` 全部清零。
- AI Provider adapters、用户路由、加密 guardrail、配置模式、Domain service/entity 与 API edges 回归 `81 passed`。
- 全仓扫描 `1851 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十五批

- 按项目高风险链路优先级收口 Terminal/TUI 公共 API：覆盖 legacy command 410、Terminal Agent chat/SSE、MCP proposal 审批执行、审计日志、Workbench registry/catalog/bootstrap/screen/action 与 operator home/governance queue。
- 所有 APIView/ViewSet handler 具化 DRF `Request`、路由参数、`Response` 或 `StreamingHttpResponse` 契约；SSE generator 使用 `Iterator[str]`，事件 JSON 和 Agent request payload 使用明确字典边界。
- `_get_terminal_agent_service()` 通过 Application `TerminalAgentService` Protocol 收窄；proposal reject 与 execute 分支使用各自输出变量，修复静态类型揭示的联合分支错误，避免错误读取不存在的 execution 字段。
- Terminal repository provider 为 TUI metadata、action executor、runtime settings 与 command HTTP client 建立最小 Protocol；Infrastructure provider 删除 wildcard re-export，改为显式工厂导出，类型收益继续传播至 services/query/interface gateway。

## 第八十五批验证结果

- 3 个直接目标文件 mypy 为零；全仓基线从 `5734 errors / 791 files` 收紧为 `5664 errors / 787 files`，净减少 `70 errors / 4 files`，跨文件无新增。
- Terminal API 的 `1 assignment + 2 attr-defined + 12 no-untyped-call + 39 no-untyped-def + 1 type-arg`、Application provider 的 `1 attr-defined + 5 no-untyped-def` 与 Infrastructure provider 的 `1 no-untyped-def` 全部清零。
- 完整传播额外清除 `ai_capability_gateway`、`interface_services`、`query_services` 与 `services` 的 `8 errors`。
- 项目规定的 TUI Workbench、Terminal Agent、SDK client、internal SSL redirect，加上 Terminal API/operator/API edges 回归共 `254 passed`。
- 全仓扫描 `1851 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十六批

- 按“Share 公开链接 + 密码访问 + 金额脱敏安全边界”收口管理 API、匿名 API、公开页面、分享管理页面与全局免责声明配置。
- Share visibility mixin 的 session 验证、客户端 IP、访问审计、snapshot 脱敏、公开 context 与 performance chart 全部使用具化 JSON 容器；嵌套 `first_of()` helper 明确 source/default 契约，不再向模板上下文传播无类型调用。
- DRF ModelViewSet/ViewSet 与 Django page view 分别使用准确的 `Request/Response` 和 `HttpRequest/HttpResponse`；公开 short code、持久化 user/share ID 与表单整数都通过显式 helper 校验。
- 修复表单边界隐患：账户 ID、编辑链接 ID、分享链接 ID 不再直接对可空输入调用 `int()`；创建密码与更新密码拆为独立变量，保持 `str | None` 语义准确。

## 第八十六批验证结果

- Share View 在直接和全仓传播模式下均为零；全仓基线从 `5664 errors / 787 files` 收紧为 `5600 errors / 786 files`，净减少 `64 errors / 1 file`，跨文件无新增。
- 目标文件的 `7 arg-type + 3 no-any-return + 16 no-untyped-call + 33 no-untyped-def + 5 type-arg` 全部清零。
- Share/Simulated Trading 依赖方向与 Share API owner scope、外部账户拒绝、公开 snapshot 金额/证据/证伪逻辑脱敏回归 `5 passed`。
- 全仓扫描 `1851 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十七批

- 按“Dashboard Alpha 首页聚合 + 决策链/退出监控导航”收口跨 Alpha、Account、Decision 与 Celery 的高扇入用户首页上下文。
- 新增统一 JSON object/list 守卫，将 Application service、Alpha metrics/query 与可注入 loader 的动态返回在 Interface 边界验证为字符串键字典或字典列表；无效动态 payload 安全降级为空结构。
- Alpha readiness、decision-chain overview、stock scores/meta、provider status、coverage、IC trends、factor panel 与 async refresh lock 全部使用具化容器和明确用户/loader 参数。
- 退出监控 detail/entry/navigation 的 item、recommendation snapshot、account ID 与 asset code 完成显式规范化，避免模板与深链 URL 直接消费不明 `object`。

## 第八十七批验证结果

- Dashboard Alpha context 在直接和全仓传播模式下均为零；全仓基线从 `5600 errors / 786 files` 收紧为 `5547 errors / 785 files`，净减少 `53 errors / 1 file`，跨文件无新增。
- 目标文件的 `6 arg-type + 4 call-overload + 1 misc + 2 no-any-return + 18 no-untyped-def + 20 type-arg` 全部清零；完整传播额外清除 Dashboard main views 的 `2 attr-defined`。
- Dashboard view structure、regression guardrails、MCP tools、Alpha homepage structure、Domain services 与 API edges 回归 `89 passed`。
- 全仓扫描 `1851 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十八批

- 按“模拟盘绩效/估值公共 API + 账户/观察员权限边界”收口区间业绩、时点估值、净值时间线、基准配置和管理员历史回填。
- 新增 Simulated Trading App 根级 `composition.py`，集中组装账户、观察者授权、日净值、统一现金流、基准、行情、交易历史、估值快照和 Capital Flow 九类具体仓储。
- Interface 删除 `import_module()` 动态加载 Infrastructure 的绕行做法，仅依赖 Application 层九个 Repository Protocol；账户仓储动态结果在权限边界验证为字符串键字典。
- 观察员授权显式拒绝未持久化用户 ID；drf-spectacular 缺失类型元数据仅在六个 schema decorator 使用错误码级局部 ignore。

## 第八十八批验证结果

- Simulated Trading composition 与 performance views 直接 mypy 为零；全仓基线从 `5547 errors / 785 files` 收紧为 `5500 errors / 784 files`，净减少 `47 errors / 1 file`，跨文件无新增。
- 目标 View 的 `1 arg-type + 6 misc + 29 no-untyped-call + 11 no-untyped-def` 全部清零。
- Account performance Domain/API、绩效曲线精度、账户 scope 与 Simulated Trading API edges 回归 `122 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第八十九批

- 按“Agent Runtime 任务生命周期 + 提案审批执行 + Operator 可观测面”收口核心公共 API，覆盖任务创建、列表、详情、恢复、取消、时间线、工件、移交、待人工处理、上下文快照、提案审批执行与健康检查。
- DRF permission、ViewSet、action 与 handler 全部具化 `Request`、路由参数、可变参数和 `Response` 契约；只读任务 ViewSet 补齐框架泛型，动态 ORM 模型继续限定在 Interface composition 边界。
- Serializer 的动态返回值在公开 JSON 边界验证为 `Mapping` 后转为字符串键字典；时间值使用可调用检查后格式化，任务 request ID 与批量主键在进入 Application query 前完成显式收窄。
- 缺失详情主键显式进入既有 `DoesNotExist` 错误契约，避免对可空路由参数直接调用 `int()`；未改变任务 owner scope、operator 权限、状态机或审批业务规则。

## 第八十九批验证结果

- Agent Runtime 核心 views 在直接和全仓传播模式下均为零；全仓基线从 `5500 errors / 784 files` 收紧为 `5456 errors / 783 files`，净减少 `44 errors / 1 file`，跨文件无新增。
- 目标文件的 `3 arg-type + 2 no-any-return + 1 no-untyped-call + 32 no-untyped-def + 1 type-arg + 4 union-attr + 1 valid-type` 全部清零。
- Agent Runtime API、serializer、任务生命周期、RBAC 与 MCP proposal execution 回归 `64 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十批

- 按“全局运行时配置真源 + Qlib/Alpha 训练控制面 + Token/备份下游读取”纵向清零整个 Config Center，覆盖模型、仓储、Application provider/use case、权限策略、App composition、Admin、DRF API/serializer 与配置页面。
- Config Center Application 为系统设置、训练模板、训练运行和 Alpha Universe 四类仓储补齐完整 Protocol 签名；actor、profile、run 与 JSON payload 只在明确动态边界使用 `Any`，不向 Domain 扩散。
- 系统配置模型补齐 singleton 读取、密码加解密、备份到期、Qlib fallback、运行时 benchmark/asset proxy/visual token 与默认配置类型；`QLIB_SETTINGS` 通过运行时 Mapping 守卫读取，不依赖未声明 settings 属性。
- Admin 迁移到 `TypedModelAdmin[ConcreteModel]`，页面与 API 保持 staff-read / superuser-write 权限；DRF Request/Response、serializer 字典、表单 cleaned data、路由参数和动态 ORM 输出均在 Interface 边界具化。
- 训练并发锁、PENDING/RUNNING 拒绝、Qlib 路径校验、Alpha Universe 解析和现有 API 响应契约保持不变；全仓传播同时清除 Account 管理/注册/备份/配置摘要与 Core encryption readiness 对无类型 Config Center API 的依赖。

## 第九十批验证结果

- Config Center 25 个生产源码直接 mypy 为零，全仓传播模式同样为零；全仓基线从 `5456 errors / 783 files` 收紧为 `5300 errors / 770 files`，净减少 `156 errors / 13 files`，跨文件无新增。
- Config Center 自身清除 `142 errors`：`81 no-untyped-def + 22 no-untyped-call + 13 type-arg + 12 no-any-return + 7 misc + 3 union-attr + 2 arg-type + 1 assignment + 1 return-value`；完整传播额外清除 `14 no-untyped-call`。
- Config Center 单元、API、Token 权限、只读快照、Core bridge、MCP catalog 与 Account runtime settings 回归 `67 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十一批

- 按“账户身份入口 + Portfolio/Position owner scope + 资金与交易数据”收口 Account 页面 views 和 Portfolio API ViewSet；覆盖注册登录、个人设置、Token 自助/管理、资金流水、回测应用、波动率、管理员审批/RBAC、观察员门户、组合与持仓 CRUD。
- Django 页面统一具化 `HttpRequest/HttpResponse`、路由整数和 token payload；DRF ViewSet 具化 `Request/Response`、泛型、serializer、路由参数和可变参数，审计客户端 IP 明确为 `str | None`。
- 页面与 API 分别增加持久化 authenticated user ID 守卫，在进入 Application service 前把 `int | None` 收窄为 `int`；未持久化身份分别使用 Django `PermissionDenied` 和 DRF `NotAuthenticated`，不允许可空用户主键进入 owner-scope 查询。
- Position 创建显式验证 portfolio ID 只能为整数或字符串；统一账本列表在 DRF pagination stub 边界局部收窄，不把 QuerySet 假设传播到 Application 返回的 JSON projections。
- 类型恢复发现波动率历史接口长期读取不存在的 `VolatilityMetrics.date` 和 `rolling_volatility_30d`；现按领域实体真实契约投影 `as_of_date` 与 30 日窗口 `annualized_volatility`，并增加 API 契约回归。

## 第九十一批验证结果

- Account 页面 views 与 Portfolio API 在直接和全仓传播模式下均为零；全仓基线从 `5300 errors / 770 files` 收紧为 `5233 errors / 768 files`，净减少 `67 errors / 2 files`，跨文件无新增。
- 目标文件的 `54 no-untyped-def + 5 no-untyped-call + 4 arg-type + 2 type-arg + 2 attr-defined` 全部清零。
- Account API edges、统一账户、Portfolio/Position owner scope、观察员授权、资料/MCP/注册、管理员用户管理、认证和 TUI 跳转回归最终 `110 passed`；其中新增波动率字段契约测试 `1 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；governance baseline 升级为 `2026-07-23.v165`，静态测试函数计数提升至 `7175`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十二批

- 按“Data Center 高扇出 Application facade + 决策数据修复编排”收口 `application/interface_services.py`；该入口被 Core health、Terminal、Dashboard、Macro、Regime、Pulse、Equity、Account、Broker Execution 与 Decision Rhythm 等至少 20 条跨模块链路直接依赖。
- 为动态注册的 Alpha scope、homepage payload 与异步任务建立最小 Protocol，明确 scope instrument/universe/hash、portfolio ID、recommendation metadata 与 task ID 契约；第三方运行时动态值只在 gateway 边界局部 `cast`。
- Realtime price 与通用 JSON payload 在 Application 边界验证为 Mapping 后转换为字符串键字典，覆盖宏观治理、生产 coverage、市场温度计、行情同步与 skipped snapshot 返回；无效动态形状不进入消费者。
- Provider registry 收窄到 Domain `ProviderRegistryProtocol`；连接测试 composition 的动态结果在持久化健康状态前强制验证为 `ConnectionTestResult`，避免异常基础设施对象污染 provider health。
- Pulse/Alpha refresher 与 status reader 具化 Callable 签名；Kombu 无类型导入仅保留精确行级 `import-untyped` 例外，provider ID 在公开返回前显式转换为可空整数。

## 第九十二批验证结果

- Data Center interface facade 在直接和全仓传播模式下均为零；全仓基线从 `5233 errors / 768 files` 收紧为 `5200 errors / 767 files`，净减少 `33 errors / 1 file`，跨文件无新增。
- 目标文件的 `14 no-untyped-call + 13 no-untyped-def + 4 type-arg + 1 import-untyped` 全部清零；完整传播额外清除 decision reliability repair command 的 `1 no-any-return`。
- Data Center interface、Alpha runtime、decision readiness、market thermometer、provider connection、API、Macro facade、repair command、on-demand、Realtime/Regime provider 与 Account 行情建仓回归 `91 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十三批

- 按“Policy Application facade + 审批工作台 API + RSS/政策事件页面”纵向收口高影响用户入口，覆盖工作台概览、Bootstrap、事件审批/驳回/回滚、Gate 配置、人工 override、RSS 源/关键词/抓取日志/阅读器和政策事件页面。
- Application interface service 为 Admin、Workbench、页面和 RSS API 仓储补齐构造器、参数与返回契约；动态 JSON payload 统一在边界验证为字符串键 Mapping，计数、布尔值和可空主键在公开返回前显式规范化。
- Workbench API 使用 DRF `Request/Response`、持久化 authenticated user ID 守卫、具体 Repository factory 与 Application service 返回类型；未持久化身份统一进入 `NotAuthenticated`，不允许可空用户主键进入审批和配置写入。
- Django 页面补齐 List/Form View handler、表单、路由、context 与 response 类型；由于当前 Django 运行类不支持泛型下标，基类保持运行时安全的原生 `ListView/FormView`，仅在基类声明处保留 `type-arg` 精确例外，实际方法签名仍全部具化。
- 回归阶段识别并修复 `ListView[Any]` / `FormView[T]` 导致 Policy URLConf 导入时报 `TypeError` 的运行时风险；`manage.py check` 和完整 Policy HTTP 流程确认页面模块可正常加载。

## 第九十三批验证结果

- 三个直接目标在 governed mypy 与增量 regression 两种模式下均为零；全仓基线从 `5200 errors / 767 files` 收紧为 `5097 errors / 764 files`，净减少 `103 errors / 3 files`，跨文件无新增。
- 目标文件的 `60 no-untyped-def + 15 no-untyped-call + 13 no-any-return + 11 type-arg` 全部清零；完整传播额外清除 `application/repository_provider.py` 的 `4 no-untyped-call`。
- Policy 单元、工作台 API、集成契约与 API 边界回归共 `212 passed`；Django system check 为 `0 issues`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；architecture/governance/repository guardrails `54 passed`，Ruff、Black 与完整 mypy debt ceiling 通过。

## 第九十四批

- 按最新“风险错误数 × 用户影响面”排序收口 Strategy HTML 主流程页面；该文件在剩余债务中风险错误数最高，直接承载策略列表、创建、详情、编辑、启停，以及规则、脚本、AI 配置和仓位规则联动保存。
- 为账户档案、策略记录、AI 配置、脚本配置和仓位规则建立页面所需的最小 Protocol；动态 `get_model()` 仅保留为运行时 Model 边界，不再被误当作类型，serializer/ORM 动态返回在访问字段前验证为已持久化策略记录。
- 登录用户 ID 与 owner account profile 使用独立守卫；登录但缺失持久化 ID/账户档案时明确返回 403，不再通过 `request.user.account_profile.id` 直接解引用形成 500。
- JSON 规则、脚本可保留哨兵、表单 JSON、validated rule 容器和默认配置全部具化；策略、配置与页面 helper 的参数/返回契约覆盖完整表单链路。
- 删除策略列表端点重复的第二层 `login_required`；owner scope、事务原子性、DRF serializer 校验与现有页面响应契约保持不变。
- 新增“登录但无账户档案必须 fail closed 为 403”集成契约，防止身份边界回退为属性异常。

## 第九十四批验证结果

- Strategy 页面在 governed mypy 与增量 regression 两种模式下均为零；全仓基线从 `5097 errors / 764 files` 收紧为 `5052 errors / 763 files`，净减少 `45 errors / 1 file`，跨文件无新增。
- 目标文件的 `10 attr-defined + 1 no-any-return + 18 no-untyped-def + 4 type-arg + 6 union-attr + 6 valid-type` 全部清零。
- Strategy 页面保存/结构、API edges、serializer/Application、执行、绑定与幂等回归共 `143 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；governance baseline 升级为 `2026-07-23.v166`，静态测试函数计数提升至 `7176`。

## 第九十五批

- 按“决策主链风险 × 公共 API 影响面”收口 Decision Workspace 推荐与执行 API，覆盖聚合工作区、交易计划生成/详情/更新、执行预览、审批/驳回、推荐列表/动作/刷新、冲突和模型参数。
- Recommendation API 不再从 `workspace_api_support` 间接重导入 DRF 类型、DTO 与 Application service，改为从正式 owner 模块导入；Enum filter 使用泛型 Enum 契约，请求字段、用户审计名与响应 DTO 全部具化。
- Execution Preview 将 plan、unified、legacy 三条分支的 request ID 分离命名，消除函数级重复定义；推荐、审批、风险检查和状态机使用正式 Domain/Application 类型，不再把不同实体统一视为动态对象。
- 所有 DRF handler 具化 `Request/Response`；请求体统一验证为字符串键 Mapping，account/recommendation/plan ID 规范化为空安全字符串，`recommendation_ids` 严格校验为非空字符串列表。
- 修复审批状态更新返回 `None` 时仍尝试发布 approved/rejected 事件的行为：只有持久化更新成功并返回最新审批单时才发布领域事件，避免虚假候选状态同步。
- 类型恢复发现 `RecommendationConsolidationService` 使用 `Decimal fair_value × float position_size_pct`，多建议合并会在运行时抛出 `TypeError`；现将权重和加权求和统一为 Decimal，确保公允价值结果精确且符合领域实体契约。
- 新增非法 recommendation ID 列表、空状态更新不发布事件、Decimal 加权公允价值三项回归。

## 第九十五批验证结果

- 两个 API 与 Domain 估值服务在 governed、silent propagation 和增量 regression 三种 mypy 模式下均为零；全仓基线从 `5052 errors / 763 files` 收紧为 `4993 errors / 760 files`，净减少 `59 errors / 3 files`，跨文件无新增。
- 直接清除 Recommendation API 的 `12 attr-defined + 1 no-any-return + 8 no-untyped-def`、Execution API 的 `15 attr-defined + 2 no-redef + 4 no-untyped-call + 12 no-untyped-def`，以及估值服务的 `1 arg-type + 1 no-untyped-def + 1 operator`。
- 完整传播额外清除 `application/decision_workspace_use_cases.py` 的 `2 no-untyped-call`。
- Decision Workspace API、错误映射、统一推荐、审批链、执行集成、决策漏斗、DTO 与估值服务回归共 `113 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；governance baseline 升级为 `2026-07-23.v167`，静态测试函数计数提升至 `7179`。

## 第九十六批

- 按“真实订单/成交/对账链路风险 × 公共 API 影响面”收口 Broker Execution 的人机 API 与核心 Django Repository，覆盖订单目录/详情/动作、Kill Switch、Agent 连接与同步、对账、审计、账户授权、凭据、执行设置，以及机器端心跳、订单租约、回报和命令。
- 全部 DRF handler 与机器端统一入口具化 `Request/Response`，Agent serializer 基类使用 DRF 泛型契约，保留签名认证、scope 校验和无 session cookie 的既有安全边界。
- 仓储账户范围查询使用具体 QuerySet 泛型；动态用户模型改为单次最小字段投影，身份、角色和管理员状态在基础设施边界规范化，不向 Application 传播动态 Model。
- 修复两个可空外键隐患：未分配 Agent 的订单不再依赖 `agent_id` 推断关联对象存在；授权管理员被删除并由 `SET_NULL` 清理后，账户授权目录不再解引用空对象。
- 对账目标的 ORM TypedDict 投影转换为明确的 `dict[str, int]`，保持 Application 层账本投影输入稳定。
- 新增未分配 Agent 订单目录、授权管理员删除后目录展示两项回归。

## 第九十六批验证结果

- Broker Execution API 与 Repository 在 silent propagation 和增量 regression 两种 mypy 模式下均为零；全仓基线从 `4993 errors / 760 files` 收紧为 `4952 errors / 758 files`，净减少 `41 errors / 2 files`，跨文件无新增。
- 直接清除 Repository 的 `1 arg-type + 3 attr-defined + 3 no-untyped-def + 2 union-attr`，以及 API 的 `6 assignment + 26 no-untyped-def`。
- Broker Execution API 权限与生命周期局部回归 `31 passed`；完整 Broker Execution 单元/集成回归 `67 passed`。
- 全仓扫描 `1852 files / 0 boundary / 0 audit violations`；governance baseline 升级为 `2026-07-23.v168`，静态测试函数计数提升至 `7181`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十七批

- 按“真实资金主流程风险 × 公共入口影响面”收口 Simulated Trading 主页面与核心 API，覆盖账户列表/创建/详情/删除、持仓、交易记录、绩效、手动交易、费率、净值曲线、自动交易和日更巡检。
- Django 页面具化 `HttpRequest/HttpResponse` 和路由参数；DRF handler 与构造器具化 `Request/Response`、可变参数和返回契约，登录用户主键在进入账户创建/查询用例前显式收窄，未持久化身份 fail closed。
- 为 drf-spectacular schema decorator 建立最小泛型 Protocol，使 governed skip-import 与 silent propagation 两种 mypy 模式共享同一装饰器签名，不引入 `misc` 或 `unused-ignore` 债务。
- 买入/卖出用例使用独立变量，消除跨分支类型污染和错误调用契约；账户访问结果在 Interface 动态 ORM 边界收窄为最小持久化账户 Protocol。
- 修复页面账户创建对非法字符串及 `NaN` 初始资金抛出 500 的问题，现安全提示并拒绝创建。
- 修复交易列表分页口径：`total_trades` 返回完整过滤结果数，与买卖统计及总盈亏保持一致，返回数组仍受 limit 限制。
- 修复 Simulated Trade ORM Mapper 将零已实现盈亏误转为 `None` 的问题；API 现保留数值零，手动交易响应同样使用显式可空判断。
- 将 Simulated Trade Domain/ORM 映射从超大 Repository 拆到独立 `infrastructure/trade_mapper.py`；统一四处账户公开 JSON 投影为 `_account_payload()`，消除重复字段漂移并在不抬高治理允许值的前提下通过大型文件门禁。
- 新增非法/非有限初始资金和交易列表分页零盈亏两组回归。

## 第九十七批验证结果

- Simulated Trading 主 views 与交易 Repository 在 governed、silent propagation 和增量 regression 三种 mypy 模式下均为零；全仓基线从 `4952 errors / 758 files` 收紧为 `4915 errors / 757 files`，净减少 `37 errors / 1 file`，跨文件无新增。
- 目标 View 的 `1 assignment + 1 call-arg + 34 no-untyped-def + 1 type-arg` 全部清零。
- Simulated Trading API edges、单元、账户/绩效/通知/再平衡和集成流程回归共 `117 passed`。
- 全仓扫描 `1853 files / 0 boundary / 0 audit violations`；governance baseline 升级为 `2026-07-23.v169`，静态测试函数计数提升至 `7183`；architecture/governance/repository guardrails `39 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十八批

- 按“交易前置风控风险 × 系统级影响面”纵向清零 Risk Center，覆盖全局风险底线、风险模板、账户风险策略、风险例外、交易前检查、投后检查、每日风险报告和账户访问范围。
- Risk Center Admin 全部迁移到 `TypedModelAdmin[ConcreteModel]`，移除动态 `get_model()` 形成的无类型 Admin 注册入口；模型风险参数投影具化为字符串键 JSON 边界。
- DRF Serializer 补齐字典泛型和 validate 契约；`field_name` 与 DRF 基类内部属性同名的框架边界局部收窄为 `Any`，保留既有 API 字段名和校验行为，不用宽泛 ignore 掩盖。
- 所有 Risk Center API handler 和内部更新入口具化 `Request/Response`、路由整数与 partial 标志；未改变认证、staff 管理权限、owner scope、异常映射或响应结构。
- 动态账户模型解析收窄为 `type[Model]`，保留延迟解析以避免 Risk Center 对 Simulated Trading 模型的硬导入；账户存在性、用户范围和风险偏好查询恢复为可验证的 ORM 布尔/列表契约。

## 第九十八批验证结果

- Risk Center 5 个生产源码在 silent propagation 和增量 regression 两种 mypy 模式下均为零；全仓基线从 `4915 errors / 757 files` 收紧为 `4869 errors / 752 files`，净减少 `46 errors / 5 files`，跨文件无新增。
- 目标文件的 `1 assignment + 2 no-any-return + 4 no-untyped-call + 25 no-untyped-def + 14 type-arg` 全部清零。
- Risk Center 策略解析、交易前检查、页面权限和 API 契约回归共 `25 passed`。
- 全仓扫描 `1853 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-23.v170`，静态测试函数计数保持 `7183`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第九十九批

- 按“用户首页影响面 × 聚合查询扇出 × 风险错误密度”收口 Dashboard 主链，覆盖跨 App Application Gateway、Interface facade、核心 Repository 与首页 View，连接账户、持仓、政策、宏观、Alpha、风险和市场温度计数据。
- Dashboard Application Gateway 对跨 App 动态返回统一执行 Mapping/JSON rows 验证，账户汇总显式收窄为浮点映射；不再把外部 Application 的 `Any` 直接传播到 Dashboard Repository。
- Dashboard Interface facade 补齐 DashboardData、Alpha/Decision query factory、日期、用户和 JSON payload 契约；Alpha 首页缺失认证用户时明确进入既有降级响应，不再依赖后续属性异常触发 fallback。
- 首页 View 补齐 `HttpRequest/HttpResponse`、Dashboard DTO、DecisionPlaneData、模板 JSON 和 helper 契约；登录用户缺少持久化 ID 时 fail closed 为 403，Streamlit settings 使用可选运行时配置读取。
- 修复 Dashboard 用户偏好方法错误归属于 `AlphaRecommendationHistoryRepository` 的结构缺陷：读取、创建、更新、卡片显隐/折叠/排序和 Domain Mapper 全部恢复到 `DashboardPreferencesRepository`，列表更新使用复制后持久化，避免原地 JSON 变更漂移。
- Alpha portfolio ID 从页面 query/pool 动态值进入退出观察导航前统一校验为正整数；非法值降级为无 portfolio scope，不再把字符串 ID 传入强类型导航 helper。
- 新增持久化偏好映射和偏好方法归属/卡片写入两项回归。

## 第九十九批验证结果

- Dashboard 4 个高扇出生产源码在 governed、silent propagation 和增量 regression 三种 mypy 模式下均为零；全仓基线从 `4869 errors / 752 files` 收紧为 `4778 errors / 748 files`，净减少 `91 errors / 4 files`，跨文件无新增。
- 目标文件的 `2 arg-type + 1 attr-defined + 6 dict-item + 18 no-any-return + 2 no-untyped-call + 28 no-untyped-def + 34 type-arg` 全部清零。
- Dashboard 首页结构、Alpha 候选/历史、市场温度计、MCP、API edges、Domain 服务和偏好仓储回归共 `187 passed`。
- 全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-23.v171`，静态测试函数计数提升至 `7185`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第一百批

- 按“审计合规风险 × 用户复核入口影响面”收口 Audit 主 View 与权限边界，覆盖归因图表/摘要、指标表现、阈值验证、审计工作台、操作日志、决策链、推荐执行关联、健康检查、失败计数和 Prometheus 指标。
- 所有 DRF handler 具化 `Request/Response`、路由参数和导出 `HttpResponse` 契约；TemplateView context 与 dispatch 具化模板字典、`HttpRequest`、可变参数和响应类型。
- `IsAuditAdmin`、操作日志 owner-scope、内部 HMAC 和 self-or-admin 权限全部具化请求、视图、对象与布尔返回；角色字段在权限边界规范化为字符串，不再由无类型权限调用向 View 传播。
- 审计 owner-scope 页面和 API 增加持久化用户 ID 守卫，未持久化身份 fail closed；手动交易复盘、我的操作日志、我的决策链和用户级列表不再把 `int | None` 传入 Application。
- 归因详情只接受 URL 路由解析后的整数报告 ID；Audit Summary 将原始 query string 与规范化 `int/date` 变量分离，避免跨类型覆盖。
- 修正 drf-spectacular 查询参数示例的 `parameter_only` 契约，并使用最小泛型 Protocol 保留装饰器方法签名。
- 决策链 `page/page_size` 和执行关联 `limit` 增加正整数与上限校验；非法值从未捕获 `int()` 异常导致的 500 改为稳定 400，并新增 4 组 API 边界回归。

## 第一百批验证结果

- Audit View 与权限文件在 governed、silent propagation 和增量 regression 三种 mypy 模式下均为零；全仓基线从 `4778 errors / 748 files` 收紧为 `4729 errors / 746 files`，净减少 `49 errors / 2 files`，跨文件无新增。
- 目标文件的 `2 arg-type + 1 assignment + 9 no-untyped-call + 37 no-untyped-def` 全部清零。
- Audit 归因、阈值验证、权限、操作日志、决策链、执行关联、健康检查、失败计数、Domain/Application 和内部写入回归共 `335 passed`。
- 全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v172`，静态测试函数计数提升至 `7186`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第一百零一批

- 按“投资决策入口影响面 × 剩余错误密度”收口 Factor 用户入口，覆盖因子定义、组合配置、评分计算、股票解释、组合生成及 HTML 页面。
- DRF ViewSet 与 Django page view 全部具化请求、响应、路由参数和内部更新方法契约；第三方 DRF 泛型仅在框架动态模型边界保留局部 `Any`。
- 因子定义与组合配置分页输入在 DRF stub 边界显式收窄，不再由列表分页产生错误类型传播。
- 新增共享正整数路由 ID 守卫；因子定义和组合配置的缺失、非数字、零及负数 ID 统一 fail closed 为 404，不再由 `int()` 异常形成 500。
- HTML 组合动作缺失 action 时规范化为空字符串并交由既有 Application 校验，不再把 `str | None` 传播到强类型服务。
- 新增 4 组因子定义/组合配置非法详情 ID API 回归。

## 第一百零一批验证结果

- Factor View 在增量 regression mypy 下为零；全仓基线从 `4729 errors / 746 files` 收紧为 `4687 errors / 745 files`，净减少 `42 errors / 1 file`，跨文件无新增。
- 目标文件的 `2 arg-type + 38 no-untyped-def + 2 type-arg` 全部清零。
- Factor API、页面、实体与 Domain 服务回归共 `102 passed`。
- 全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v173`，静态测试函数计数提升至 `7187`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Ruff、Black 与 diff check 通过。

## 第一百零二批

- 沿 Factor 决策链继续收口 Application Facade、UseCase、ORM Model 与 Repository，覆盖因子评分、组合配置、页面读模型、因子暴露和持仓持久化。
- Application 新增因子定义、组合配置与集成服务 Protocol；组合配置只通过只读投影进入用例，Facade 在 composition boundary 显式组装 concrete repository，不再把 ORM 类型扩散到 Application。
- View response DTO 的 factors、stats、choices、calculation results 和 score rows 全部具化容器元素；可空交易日、依赖注入 constructor 与 action payload 契约同步收窄。
- ORM `to_domain` 与字符串表示补齐返回类型，并通过 postponed annotations 避免 Django App 初始化时解析前向类型。
- Repository 的写入 payload、统计、分类 choices、暴露与持仓查询全部具化；QuerySet 在 repository 边界物化为 list，模板临时字段使用局部 Protocol 投影。
- 类别统计改为单次读取类别值后本地计数，规避 django-stubs 无法解析动态 annotation 字段，同时保持固定一次查询。
- 空因子选择在进入 Domain 权重校验前规范化为空结果，避免除零或“权重和不为 1”的异常；新增 Application 回归。

## 第一百零二批验证结果

- Factor Facade、UseCase、Model 与 Repository 在增量 regression mypy 下均为零；全仓基线从 `4687 errors / 745 files` 收紧为 `4617 errors / 741 files`，净减少 `70 errors / 4 files`，跨文件无新增。
- Factor Application、Domain、API、页面与 Repository 相关回归共 `103 passed / 7 skipped`。
- 隔离提交全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v174`，静态测试函数计数提升至 `7188`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Django system check、Ruff、Black 与 diff check 通过。

## 第一百零三批

- 完成 Factor 模块剩余生产代码收口，覆盖计算 Integration Service、数据适配器、DRF Serializer、DTO、初始化命令与 API/page URL 装配。
- Factor 数据适配器将估值与财务 QuerySet/row 分支彻底分离，消除 ORM 类型串线；价格服务通过 Protocol 注入，因子缓存具化并真正写入计算结果。
- 修复 Beta 因子此前不满足 momentum/volatility 外层条件而永远无法进入 benchmark 计算分支的问题，并增加缓存复用与 Beta 可达性回归。
- Integration Service 移除不存在的 `StockInfoRepository` 导入，统一通过 Equity ORM 边界读取股票展示信息；不再把上市日期误填入市值字段。
- 评分、组合、因子定义和配置 payload 全部具化 JSON 容器；holding score 输入改为协变 Sequence，DRF 动态返回仅在 serializer 边界局部 cast。
- Serializer 泛型、查询参数校验、管理命令 parser/options、APIView/Page URL 请求响应全部具化；Factor DTO holdings 补齐 JSON 元素类型。

## 第一百零三批验证结果

- `apps/factor` 受管生产代码 `26 source files` mypy 全部为零；全仓基线从 `4617 errors / 741 files` 收紧为 `4580 errors / 734 files`，净减少 `37 errors / 7 files`，Factor 模块生产 mypy 债务清零。
- Factor Application/Infrastructure/Domain/API/页面回归合计 `105 passed / 7 skipped`。
- 隔离提交全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v175`，静态测试函数计数提升至 `7190`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Django system check、Factor Ruff、Black 与 diff check 通过。

## 第一百零四批

- 按“投资决策入口影响面 × 用户操作频率”收口 Alpha Trigger Interface、Serializer 与核心 UseCase，覆盖触发器/候选查询、状态更新、创建、证伪、评估、候选生成、页面与性能数据。
- DRF ViewSet/APIView 和 Django page view 全部具化请求、响应、路由参数与 constructor；缺失 route ID 通过统一守卫转换为稳定 ValidationError，不再把 `str | None` 传入 Repository。
- 触发器与候选统计共享 `days` 查询契约，限制为 `1..365`；非整数、零和超上限从未捕获转换异常导致的 500 改为稳定 400。
- Enum Field 与 Serializer 补齐 DRF 四参数泛型及实例边界；many 模式保留在 DRF 动态边界，手写 representation 与 query parsing 使用精确 JSON 类型和局部 cast。
- drf-spectacular `extend_schema` 通过泛型 Protocol 保留被装饰 handler 签名，消除全仓模式下的 untyped decorator 扩散。
- Application 新增 Trigger/Candidate Repository 与 EventPublisher Protocol，四个 UseCase constructor、事件发布 helper 和混合类型 current_data 全部具化；Interface 不再调用无类型 Application 对象。
- 新增触发器与候选统计非法 days 的 6 组 API 边界回归。

## 第一百零四批验证结果

- Alpha Trigger View、Serializer 与 UseCase 在增量 regression mypy 下均为零；全仓基线从 `4580 errors / 734 files` 收紧为 `4512 errors / 731 files`，净减少 `68 errors / 3 files`，另带动 Subscriber 与 Dashboard 查询各减少 1 条调用债务。
- Alpha Trigger API、Domain、事件订阅与决策平台页面回归共 `76 passed`。
- 隔离提交全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v176`，静态测试函数计数提升至 `7191`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Django system check、Ruff、Black 与 diff check 通过。

## 第一百零五批

- 完成 Alpha Trigger 模块剩余生产代码收口，覆盖 Domain Candidate、事件 Handler/Subscriber、页面 Query Service、App 启动、ORM Model/QuerySet、Repository 与模板过滤器。
- Candidate 状态从动态 `Any` 收窄为 `CandidateStatus | str` 兼容契约，通过 `status_value` 向持久化和序列化输出稳定字符串；缺失 `time_horizon` 时从日期窗口推导有效天数，默认创建/更新时间改为 UTC-aware。
- ORM QuerySet 使用具体 Model 泛型，字符串表示、模型校验、Repository constructor、日期参数与统计窗口全部具化；`timezone.timedelta` 改为标准库 `timedelta`。
- 修复候选更新先覆盖状态再比较、导致 `status_changed_at` 永不更新的问题；更新前保留旧状态，并将可空 entry/exit/risk/time horizon 规范化到 ORM 非空契约。
- 修复 Trigger/Candidate Domain 已移除 `custom_data/metadata` 后仍动态挂载或读取属性的问题，ORM 兼容字段明确写入空 JSON，不再污染 Domain 实体。
- 修复证伪 Handler 订阅不存在的 `ALPHA_TRIGGER_TRIGGERED` 枚举，改为系统实际发布的 `ALPHA_TRIGGER_FIRED`；候选晋升向 Repository 传递 `CandidateStatus` 而非裸字符串。
- 决策拒绝通过候选模型现有终态 `CANCELLED` 持久化，消除访问不存在 `CandidateStatus.REJECTED` 的运行时异常；新增事件、晋升、拒绝、时间窗口和时区默认值回归。

## 第一百零五批验证结果

- `apps/alpha_trigger` 受管生产代码 `34 source files` mypy 全部为零；全仓基线从 `4512 errors / 731 files` 收紧为 `4447 errors / 720 files`，净减少 `65 errors / 11 files`。
- Alpha Trigger 直接清除剩余 `58` 条债务；完整传播额外清除 Decision Rhythm Feature Provider 的 `4 no-untyped-call` 与 Event Replay 的 `3 no-untyped-call`。
- Alpha Trigger API、Domain、事件处理、订阅、Repository 与服务回归共 `72 passed`。
- 隔离提交全仓扫描 `1854 files / 0 boundary / 0 governance violations`；governance baseline 升级为 `2026-07-24.v177`，静态测试函数计数提升至 `7196`；architecture/governance/repository guardrails `54 passed`，完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百零六批

- 按“资产配置决策影响面 × 债务集中度”启动 Rotation 纵向收口，首批覆盖 DRF/Django View、Application Interface Service、页面 UseCase、DTO 与 Repository Provider，直接承载资产池、轮动配置、信号、推荐、比较、相关性、模板和账户级配置。
- DRF ViewSet、action 与 HTML page view 全部具化请求、响应、路由参数和 serializer/queryset 边界；动态 ORM 对象仅保留在 Interface/Repository 交界，不向页面 UseCase 传播。
- Application 为页面查询建立 Rotation View Repository/Integration Protocol，并对动量分数、轮动信号和页面读模型使用最小结构投影；三个页面 UseCase constructor 不再依赖无类型 concrete service。
- DTO 的资产、配置、信号、分类和排名容器全部具化；批量信号生成内部使用 TypedDict 保证计数与 signals 列表可安全更新，同时保留跨模块既有 `dict[str, Any]` Callable 返回契约。
- Repository Provider 的 concrete 类型改为显式重导出，保留 `RotationIntegrationService` 既有 patch/import 表面，不因类型收口破坏测试和外部调用。
- Correlation API 与 Compare API 对齐，严格校验非空字符串资产列表、最多 20 项及 `1..500` 天窗口；Generate Signal API 将 ISO 日期解析前置，非法类型或日期稳定返回 400，不再把字符串传入 date 契约。
- 新增相关性非法参数与无效信号日期两组 API 回归。

## 第一百零六批验证结果

- Rotation 五个目标文件在 governed/完整传播 mypy 下为零；全仓基线从 `4447 errors / 720 files` 收紧为 `4366 errors / 714 files`，净减少 `81 errors / 6 files`。
- 直接清除 DTO、Interface Service、Provider、UseCase 与 View 的 `80` 条债务；完整传播额外清除 Application Integration Service 的 `1 attr-defined`。
- Rotation API 回归 `27 passed`。
- governance baseline 升级为 `2026-07-24.v178`，静态测试函数计数提升至 `7198`。

## 第一百零七批

- 完成 Rotation 模块剩余生产代码收口，覆盖 Integration Service、DRF Serializer、初始化命令、AppConfig、API/page URL 装配，并同步收紧共享相关性计算器。
- Rotation 信号生成结果、批量调度计数、价格序列、数据质量与资产收益容器全部具化；Integration Service 在找不到 ORM 配置模型时仍返回已经成功计算的信号，不再因跳过持久化而隐式返回 `None`。
- Serializer 为配置与信号建立最小记录 Protocol，所有 DRF Serializer 补齐泛型及方法契约；Regime 配置权重现在拒绝布尔值、字符串和其他非数字输入，并规范化为浮点数，避免在求和阶段触发未捕获异常。
- 初始化命令的模板规格、parser、options、查询集合和象限配置全部具化；AppConfig 与 URL helper 补齐请求响应类型。
- 共享相关性计算器显式收窄动态 NumPy 边界，并保证 NumPy 不可用时回退实现已经初始化；Rotation 不再因调用无类型共享构造器产生传播债务。
- 新增“缺少 ORM 配置仍返回信号”及“拒绝非数字配置权重”两组回归。

## 第一百零七批验证结果

- `apps/rotation` 受管生产代码 `31 source files` 与共享相关性计算器 mypy 全部为零；全仓基线从 `4366 errors / 714 files` 收紧为 `4306 errors / 707 files`，净减少 `60 errors / 7 files`，Rotation 模块生产 mypy 债务清零。
- Rotation 直接清除剩余 `56` 条债务，共享相关性计算器清除 `4` 条债务。
- Rotation readiness、API 与 Domain 回归共 `113 passed`。
- governance baseline 升级为 `2026-07-24.v179`，静态测试函数计数提升至 `7200`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百零八批

- 按“推荐生成前置影响面 × 跨模块调用扇出”继续收口 Decision Rhythm，首批清零统一推荐的 Feature Provider 聚合入口，覆盖 Regime、Policy、Beta Gate、舆情、资金、技术、基本面、Alpha 信号与候选。
- 为 Alpha 查询、交易日解析及六类延迟加载依赖建立精确 Callable/Protocol/具体边界类型；所有 provider constructor、repository/use-case getter 与 Alpha 查询返回契约具化。
- Composite Provider 的 Beta Gate 方法与父类保持可替换签名，并将动态 Regime confidence 通过共享安全数值入口收窄；Alpha 排名结果改为直接使用已具化的 Domain 实体字段。
- 修复 Policy `P0/P1/P2/P3` 字符串可能直接进入要求整数的 Beta Gate 请求的问题；`P*` 与 `LEVEL_*` 现统一规范化为受限 `0..3`，未知值安全回退为 0。
- Alpha 候选分数使用 `safe_float` 拒绝非法值、NaN 与无穷值，继续保持中性分数降级。
- 新增 Policy 档位规范化参数化回归。

## 第一百零八批验证结果

- Decision Rhythm Feature Provider mypy 清零；全仓基线从 `4306 errors / 707 files` 收紧为 `4273 errors / 706 files`，净减少 `33 errors / 1 file`，跨文件无新增。
- Feature Provider 与统一推荐用例回归共 `49 passed`。
- governance baseline 升级为 `2026-07-24.v180`，静态测试函数计数提升至 `7201`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百零九批

- 沿统一推荐事件链继续收口 Decision Rhythm handlers，覆盖决策批准/拒绝、Alpha 触发、配额监控与信号冷却处理。
- 为配额管理、冷却管理与事件发布建立最小 Application Protocol；三个 handler constructor、内部分发方法与配额检查全部具化，并允许 composition root 暂未注入 event bus 时安全跳过发布。
- 补齐事件系统已被 handler 引用但此前不存在的 `QUOTA_WARNING` 类型，避免订阅或告警路径运行时访问不存在枚举。
- 修复配额监控读取不存在的 `remaining/total` 字段而使用默认 `0/1`、导致正常配额也被误判为告警的问题；现对齐 Domain 的 `remaining_decisions/max_decisions`，并防止零配额除法。
- 修复信号冷却处理调用不存在 `CooldownManager.get_remaining_cooldown()` 的问题；现通过实际 `get_cooldown().decision_ready_in_hours` 契约判断，并拒绝缺失资产代码的事件。
- 新增配额告警和信号冷却两组行为回归。

## 第一百零九批验证结果

- Decision Rhythm handlers mypy 清零；全仓基线从 `4273 errors / 706 files` 收紧为 `4253 errors / 704 files`，净减少 `20 errors / 2 files`。
- handlers 直接清除 `14` 条债务，完整传播额外清除 subscribers 与 core event replay 各 `3 no-untyped-call`。
- handlers 与统一推荐相关回归共 `18 passed`。
- governance baseline 升级为 `2026-07-24.v181`，静态测试函数计数提升至 `7203`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十批

- 按“估值决策入口影响面 × AI 证伪草稿安全性”收口 Decision Rhythm 估值快照、重新计算、系统证伪模板与 AI 草稿 API，并同步具化跨 Prompt/Terminal/Decision Rhythm 共用的 AI chat helper。
- DRF handler 全部具化 `Request/Response`；请求体统一要求 JSON object，security code 与 valuation method 规范化，估值方法限制为 Domain 支持集合。
- 估值重新计算拒绝零值、负值、非法数字及非对象 `input_parameters`，不再把可空 Decimal 或任意动态容器传入 Application。
- AI 草稿的 existing rule 必须为对象；AI content 在解析前规范化为字符串，解析异常只捕获明确类型，AI 返回非对象 meta 时重建审计 metadata，避免成功响应路径触发 500。
- AI chat helper 为 client/factory 建立 Protocol，动态 signature 参数具化，Repository Provider 通过 `__all__` 明确公开 composition factory，保留既有 `AIClientFactory` patch/import 契约。
- 新增非对象请求体、非正估值、未知方法、错误 input parameters 与异常 AI meta 回归。

## 第一百一十批验证结果

- Decision Rhythm 估值 API 与 AI chat helper mypy 清零；全仓基线从 `4253 errors / 704 files` 收紧为 `4238 errors / 702 files`，净减少 `15 errors / 2 files`。
- 两个目标文件直接清除 `14` 条债务，完整传播额外清除 workspace API support 的 `1 attr-defined`。
- Decision Rhythm API edges `18 passed`，证伪模板集成回归 `2 passed / 3 deselected`。
- governance baseline 升级为 `2026-07-24.v182`，静态测试函数计数提升至 `7206`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十一批

- 沿“统一推荐持久化影响面 × 审批链溯源正确性”收口 Decision Rhythm Unified Recommendation Repository，覆盖推荐、特征快照、用户动作、执行匹配、参数配置与审计日志。
- Repository 所有 Domain 输入输出具化为 `UnifiedRecommendation`、`DecisionFeatureSnapshot`、`UserDecisionAction`、`ModelParamConfig` 与 `ModelParamAuditLog`，移除 Domain 实体字段上的动态 `hasattr/getattr`。
- 推荐状态、用户动作与来源 ID 直接使用 Domain 契约持久化；Application 中因 Repository 返回具化而变成冗余的历史 cast 同步删除，完整传播不接受新增债务。
- 修复 mapper 将 Django ForeignKey 数据库整数主键写入 Domain `feature_snapshot_id` 的溯源错误；现返回关联快照业务 `snapshot_id`。
- 账户推荐与冲突推荐列表统一 `select_related("feature_snapshot")`，避免业务快照 ID 修复后产生 N+1 查询。
- 新增业务快照 ID 映射回归。

## 第一百一十一批验证结果

- Unified Recommendation Repository mypy 清零；全仓基线从 `4238 errors / 702 files` 收紧为 `4229 errors / 701 files`，净减少 `9 errors / 1 file`，跨文件无新增。
- 审批执行链回归 `9 passed`，推荐模型与仓储结构回归 `22 passed`。
- governance baseline 升级为 `2026-07-24.v183`，静态测试函数计数提升至 `7207`；完整 mypy debt ceiling、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十二批

- 按“决策写入风险 × 配额控制影响面”收口 Decision Rhythm workflow、quota 与 command API，覆盖预检查、执行、取消、配额更新/重置/趋势、单笔/批量提交和节奏摘要。
- 所有 APIView/ViewSet handler、路由 request ID 与 ViewSet constructor 具化 `Request/Response` 和可变参数；`OpenApiTypes` 改用 drf-spectacular 明确公开模块。
- 在共享 API helper 建立泛型 `typed_extend_schema` 边界，保留被装饰 handler 的完整签名，消除三个文件的装饰器传播债务。
- workflow 的未预期异常统一进入共享 internal error helper；500 响应只返回稳定业务错误消息，详细异常继续写日志，不再向客户端泄漏数据库、配置或内部实现文本。
- 新增内部异常不泄漏回归。

## 第一百一十二批验证结果

- Decision Rhythm workflow/quota/command API mypy 清零；全仓基线从 `4229 errors / 701 files` 收紧为 `4207 errors / 698 files`，净减少 `22 errors / 3 files`。
- Decision Rhythm API 与错误映射回归 `23 passed`，执行工作流回归 `21 passed`。
- governance baseline 升级为 `2026-07-24.v184`，静态测试函数计数提升至 `7208`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十三批

- 按“Advisor Sheet 用户决策展示影响面 × 推荐绩效归因正确性”收口 advisor sheet context、intent 与 performance 服务。
- Context mixin 显式声明风险闸门、数据健康、敞口、推荐跟踪、推荐绩效和归因上下文六类 Provider Protocol 属性，消除运行时注入依赖的隐式成员。
- Intent 替换改用 `dataclasses.replace`，并继续防御性复制价格带、风险提示、来源推荐、冲突处置、风险闸门、数据时点、决策卡、跟踪和确认等嵌套可变字段。
- 去重 helper 接受 `Iterable[str]`，安全覆盖生成器调用；绩效用户动作与可用窗口在计算前显式收窄，避免可空推荐及 Decimal 运算传播。

## 第一百一十三批验证结果

- Advisor Sheet 三个目标文件 mypy 清零；全仓基线从 `4207 errors / 698 files` 收紧为 `4188 errors / 695 files`，净减少 `19 errors / 3 files`。
- Advisor Sheet 核心与结构回归 `26 passed`，API guardrail `4 passed`。
- governance baseline 升级为 `2026-07-24.v185`，静态测试函数计数保持 `7208`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十四批

- 按“决策调度公平性 × 配额与冷却核心规则影响面”收口 Decision Rhythm 的 Rhythm Entity、Domain Service 与 ORM Model。
- 冷却检查先显式收窄最后决策/执行时间，杜绝可空时间参与运算；批量响应和队列优先级统计容器全部具化。
- 修复同优先级请求按最新时间优先、导致旧请求可能长期饥饿的问题，调度器现按“高优先级优先、同优先级 FIFO”选择。
- 配额状态继续以结构化 JSON 快照贯穿 Domain 与 ORM，不再压成字符串；响应 mapper 使用 Domain request 业务 ID，不再误把数据库外键整数暴露为 request ID。
- ORM 工厂为缺少业务 ID 的配额和冷却实体生成非空稳定前缀 ID，避免把 `None` 写入非空字段；请求与响应默认时间改为 UTC-aware。
- `create_request` 的动态可选字段改为 `TypedDict + Unpack` 契约，四个 ORM Model 移除过时的宽泛 mypy ignore。

## 第一百一十四批验证结果

- Decision Rhythm Rhythm Entity、Domain Service 与 ORM Model mypy 清零；全仓基线从 `4188 errors / 695 files` 收紧为 `4169 errors / 692 files`，净减少 `19 errors / 3 files`。
- Decision Rhythm Domain、Scheduler、ORM mapper 与模型结构回归 `34 passed`。
- governance baseline 升级为 `2026-07-24.v186`，静态测试函数计数提升至 `7212`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十五批

- 按“用户决策工作台主流程 × 执行审批风控安全性”收口 Decision Workspace 用例，覆盖估值快照、聚合建议、执行预览、批准与拒绝。
- 为估值快照、推荐、审批、配额、冷却、Regime 与事件发布建立最小 Application Protocol；五个 UseCase constructor、推荐格式化和风险检查全部具化。
- 响应 DTO 直接使用 ValuationSnapshot 与 ExecutionApprovalRequest，账户分组、聚合结果和风险检查容器显式收窄，不再依赖无类型对象传播。
- 配额或冷却依赖异常时改为风险检查失败，不再以“检查失败（跳过）”静默放行；显式传入零市场价格时仍进入审批校验，不再因 truthy 判断绕过价格检查。
- 新增风险依赖异常 fail-closed 与零市场价格不得跳过校验两组回归。

## 第一百一十五批验证结果

- Decision Workspace UseCase mypy 清零；全仓基线从 `4169 errors / 692 files` 收紧为 `4162 errors / 691 files`，净减少 `7 errors / 1 file`。
- Decision Workspace 安全回归、结构与工作流用例共 `18 passed`。
- governance baseline 升级为 `2026-07-24.v187`，静态测试函数计数提升至 `7214`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十六批

- 按“估值快照持久化影响面 × 审批价格审计正确性”收口 Decision Rhythm valuation models，覆盖估值快照、投资建议和执行审批 ORM。
- 三个 ORM Model 与 Django imports 移除已经失效的宽泛 mypy ignore，恢复真实类型门禁。
- 执行审批 mapper 使用显式 `is not None` 判断审核价格，修复合法零值被错误映射为缺失值的问题，保持审计记录原义。
- 新增零审核价格 ORM-to-Domain 映射回归。

## 第一百一十六批验证结果

- Decision Rhythm valuation models mypy 清零；全仓基线从 `4162 errors / 691 files` 收紧为 `4156 errors / 690 files`，净减少 `6 errors / 1 file`。
- Workspace 安全与模型结构回归 `5 passed`。
- governance baseline 升级为 `2026-07-24.v188`，静态测试函数计数提升至 `7215`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十七批

- 按“推荐持久化溯源影响面 × 执行审批安全性”纵向收口 Recommendation Model、Repository 与 Workspace Service 传播链。
- Decision Feature Snapshot、Unified Recommendation 与 Execution Link ORM 移除失效的宽泛 mypy ignore；估值快照、投资建议、调仓计划和执行审批 Repository 的 Domain 输入输出全部具化。
- 推荐写入遇到不存在的估值快照时明确失败，不再静默保存并丢失估值溯源；推荐与审批列表统一 `select_related` 所需关联，消除序列化阶段 N+1。
- 估值快照和待审批聚合键查询不再捕获所有异常并伪装成“无数据”，数据库与实现错误可由上层按既有异常边界处理。
- 统一推荐无法计算出正数可执行数量时拒绝创建审批，避免绕过 ORM 的数量约束形成不可执行审批单。
- 精确 Repository 返回类型向 Workspace Service 传播，删除 11 个历史 cast；配额、冷却依赖异常统一 fail-closed，调仓计划逐资产冷却检查失败也会阻断审批。
- 新增缺失估值快照、推荐列表单查询、零数量审批、推荐与调仓计划风险依赖异常五组回归；同时规范化 Recommendation Repository 历史混合换行。

## 第一百一十七批验证结果

- Recommendation Model、Repository 与 Workspace Service mypy 清零；全仓基线从 `4156 errors / 690 files` 收紧为 `4143 errors / 687 files`，净减少 `13 errors / 3 files`。
- 推荐持久化、审批链、调仓计划与 Workspace 风险回归共 `15 passed`。
- governance baseline 升级为 `2026-07-24.v189`，静态测试函数计数提升至 `7220`；完整 mypy debt ceiling、Django system check、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十八批

- 按“审批事件状态传播影响面 × 启动完整性”收口 Decision Rhythm subscriber 与 AppConfig 注册入口。
- 三个 handler factory 具化为 `Callable[[], EventHandler]`，移除只记录后重新抛出的宽泛异常包装；AppConfig `ready()` 补齐返回类型。
- 修复 EventSubscriberRegistry 按 `(module_name, event_type)` 去重时，三个 `DECISION_APPROVED` handler 使用相同模块名导致互相覆盖的问题；核心、配额监控与冷却处理器改用独立订阅身份并按 `50/55/60` 优先级全部保留。
- subscriber 注册与 AppConfig 启动不再捕获所有异常后继续运行，注册失败会阻止不完整事件链静默上线。
- 新增审批事件保留三个 handler、factory 契约和注册失败不得静默三组回归。

## 第一百一十八批验证结果

- Decision Rhythm subscriber 与 AppConfig mypy 清零；全仓基线从 `4143 errors / 687 files` 收紧为 `4138 errors / 685 files`，净减少 `5 errors / 2 files`。
- Subscriber wiring、handler、事件总线与仓储结构回归共 `37 passed`，Django system check 通过。
- governance baseline 升级为 `2026-07-24.v190`，静态测试函数计数提升至 `7223`；完整 mypy debt ceiling、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百一十九批

- 按“决策查询入口影响面 × 冷却状态输入安全性”收口 Decision Request 与 Cooldown 两组 DRF ViewSet，并同步强化查询 serializer。
- ViewSet constructor、Request、route ID 与 action handler 全部具化；请求 ID 缺失或超过 64 字符时稳定返回 400，不再把空 ID传入 Application。
- 列表与统计查询天数限制为 `1..3650`，避免超大时间窗口造成日期溢出或非必要数据库负载；资产代码限制为 32 字符。
- 按资产冷却路径参数统一去空格并转大写，空值与超长值在进入 UseCase 前拒绝。
- 新增请求/统计超大天数、剩余小时与路径资产代码超长四组 API 回归。

## 第一百一十九批验证结果

- Decision Request 与 Cooldown API mypy 清零；全仓基线从 `4138 errors / 685 files` 收紧为 `4130 errors / 683 files`，净减少 `8 errors / 2 files`。
- Decision Rhythm API edge 与错误映射回归共 `27 passed`。
- governance baseline 升级为 `2026-07-24.v191`，静态测试函数计数提升至 `7227`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十批

- 按“Advisor Sheet 用户行动意图正确性 × 真实下单数量安全性”收口 advisor sheet intent 构造。
- Mixin 显式声明 Risk Gate 与 Execution Guard Provider Protocol；缺价买入在除法前通过可空价格收窄，避免价格缺失路径参与数量计算。
- 修复持仓已不高于 15% 时仍生成零差额 REDUCE 意图的问题，此时改为 HOLD 并说明当前权重已满足上限。
- 修复持仓已达到或超过 20% 加仓上限时仍生成零差额 ADD 意图的问题，此时保留当前权重并改为 HOLD。
- 新增低权重 REDUCE、高权重 ADD 与缺价 BUY 三组 intent 回归。

## 第一百二十批验证结果

- Advisor Sheet intent 构造 mypy 清零；全仓基线从 `4130 errors / 683 files` 收紧为 `4127 errors / 682 files`，净减少 `3 errors / 1 file`。
- Advisor Sheet intent、核心、结构与 API 回归共 `33 passed`。
- governance baseline 升级为 `2026-07-24.v192`，静态测试函数计数提升至 `7230`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十一批

- 按“模拟交易退出链路影响面 × 持仓退出建议匹配正确性”收口 Decision Rhythm exit advisor。
- 为统一推荐与调仓计划仓储建立最小 Application Protocol，构造函数、仓储返回值和数值解析边界全部具化。
- 持仓、统一推荐和调仓计划中的证券代码统一去空格并转大写，修复大小写不一致导致 SELL/EXIT 建议静默失配的问题。
- 推荐源与调仓计划源按明确的可恢复异常独立降级，单一来源故障时仍保留另一来源的退出建议。
- 推荐价格通过共享 `safe_float` 收窄，Domain 实体字段改为直接类型访问，不再依赖宽泛动态属性读取。
- 新增推荐代码大小写匹配与推荐源故障时调仓计划继续生效两组回归。

## 第一百二十一批验证结果

- Decision Rhythm exit advisor mypy 清零；全仓基线从 `4127 errors / 682 files` 收紧为 `4124 errors / 681 files`，净减少 `3 errors / 1 file`。
- 退出建议与模拟交易自动退出链路回归共 `14 passed`。
- governance baseline 升级为 `2026-07-24.v193`，静态测试函数计数提升至 `7232`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十二批

- 按“自动交易核心执行影响面 × 错误订单防护安全性”收口 simulated trading auto trading engine。
- 账户、持仓、交易、资产池、价格、信号、退出建议与前置风控依赖全部使用精确 Protocol；每日交易结果、候选载荷、价格区间和执行时间边界完成具化。
- 修复减仓建议缺少数量时被当成全量清仓的问题；减仓数量缺失、为零或为负时不再执行，清仓建议仍严格按当前持仓数量处理。
- 策略模式买卖数量必须为正数；候选证券代码缺失时在查询价格和下单前拒绝，证券代码统一大写以避免重复持仓。
- 价格提供者返回的零值、负值、NaN 或无穷值统一视为不可交易；候选分数与价格触发带通过共享 `safe_float` 收窄。
- 持仓与候选、持仓与退出建议均按标准化证券代码匹配，修复大小写差异导致重复买入或退出建议失配。
- 新增缺失减仓数量、空证券代码、持仓大小写去重与非正价格四组安全回归。

## 第一百二十二批验证结果

- simulated trading auto trading engine mypy 清零；全仓基线从 `4124 errors / 681 files` 收紧为 `4105 errors / 680 files`，净减少 `19 errors / 1 file`。
- 自动交易、Alpha 退出闭环、任务装配、Decision Rhythm exit advisor 与策略集成回归共 `27 passed`。
- governance baseline 升级为 `2026-07-24.v194`，静态测试函数计数提升至 `7236`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十三批

- 按“持仓证伪自动退出影响面 × 状态持久化真实性”收口 simulated trading position invalidation checker。
- 修复 Position Domain 实体中的证伪规则为 JSON 字符串、检查器却直接按字典解析的问题；历史路径会捕获 `TypeError` 后静默跳过，现改为显式 JSON 解码、对象形态收窄后再构造 Domain Rule。
- 宏观观测与持仓持久化建立最小 Application Protocol，构造函数支持依赖注入；批量结果、已证伪持仓摘要、检查时间和仓储返回值全部具化。
- 规则 JSON 无效与宏观指标读取失败增加可定位日志；指标缺失仍按既有安全策略不触发卖出。
- `mark_invalidated` 返回失败时不再把持仓计入成功结果，避免调度任务虚报“已证伪”但数据库状态未落地。
- `mark_invalidation_checked` 写入失败增加告警，证伪日志仅在状态真正持久化后输出。
- 新增 JSON 规则真实触发与证伪状态写入失败不得虚报两组回归。

## 第一百二十三批验证结果

- simulated trading position invalidation checker mypy 清零；全仓基线从 `4105 errors / 680 files` 收紧为 `4096 errors / 679 files`，净减少 `9 errors / 1 file`。
- 持仓证伪、定时任务、自动交易与 Alpha 退出闭环回归共 `19 passed`。
- governance baseline 升级为 `2026-07-24.v195`，静态测试函数计数提升至 `7238`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十四批

- 按“模拟账户绩效口径影响面 × 历史截面无后视偏差”收口 simulated trading performance calculator。
- 为账户、交易历史与价格服务建立最小 Application Protocol；绩效指标和净值曲线使用 TypedDict，交易分组、持仓数量、时间范围及价格边界全部具化。
- 修复年化收益使用账户中旧 `total_return` 缓存值的问题，现基于本次实时总资产计算出的总收益年化；账户归零时稳定返回 `-100%`，不再产生复数。
- 夏普与胜率查询严格截止到调用方指定的 `trade_date`，历史绩效不再读取未来交易。
- 胜率分母只统计存在已实现盈亏的平仓交易，不再把 BUY 交易计入并稀释胜率；零盈亏平仓仍保留在分母中。
- 历史价格统一通过 `safe_float` 收窄，零值、负值、NaN 和无穷值均明确拒绝，避免污染净值和回撤。
- 卖出后持仓数量小于等于零时清理曲线持仓，绩效更新日志使用本次持久化的新指标而非旧账户值。
- 新增实时年化收益、历史截止日胜率和非法历史价格三组边界回归。

## 第一百二十四批验证结果

- simulated trading performance calculator mypy 清零，并消除 interface service 的一条传播债务；全仓基线从 `4096 errors / 679 files` 收紧为 `4079 errors / 678 files`，净减少 `17 errors / 1 file`。
- 绩效边界、历史净值准确性与 simulated trading 集成回归共 `30 passed`。
- governance baseline 升级为 `2026-07-24.v196`，静态测试函数计数提升至 `7241`；完整 mypy debt ceiling、Django system check、架构与治理检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百二十五批

- 按“模拟交易资金安全影响面 × 费用配置唯一真源”收口买卖下单 UseCase、Domain Rule 与默认费率 Repository。
- 买卖费用统一从按资产类型启用的默认 `FeeConfig` 读取，最低佣金、印花税、过户费和滑点不再由下单用例硬编码；缺少有效默认配置时明确拒单。
- 资产专用默认费率优先于 `all` 通用配置，未命中专用配置时才回退通用配置，避免通用配置因默认排序抢占专用费率。
- 买入资金校验与实际扣款使用同一份费用计算结果，修复最低佣金未进入资金校验、验证通过后现金变负的风险。
- 买卖价格必须为正数；已证伪持仓禁止继续加仓；部分卖出只扣减原可卖数量，不再把 T+1 冻结数量错误释放。
- 自动交易显式传递业务交易日，历史重跑不再以机器当天日期落账；交易 ID 更新改用 dataclass `replace`，信号证伪读取失败增加可定位日志。
- 账户绩效胜率分母同步收紧为已平仓交易，零盈亏平仓仍计入分母；持仓成本服务数量类型与 Domain 实体保持一致。
- 新增配置最低佣金资金边界、缺配置拒单、非正价格、冻结数量、历史交易日、证伪加仓和专用费率优先级回归。

## 第一百二十五批验证结果

- simulated trading order use cases 与 interface service mypy 清零；全仓基线从 `4079 errors / 678 files` 收紧为 `4068 errors / 676 files`，净减少 `11 errors / 2 files`。
- 模拟交易下单、绩效、策略、净值与 Decision Rhythm 执行回归共 `62 passed`，持仓成本领域服务 `2 passed`。
- 完整 mypy debt ceiling、governance consistency、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过；主工作树并行测试治理批次正在更新 governance baseline，本批不覆盖该未提交真源。

## 第一百二十六批

- 按“实盘账户映射影响面 × 账本同步幂等性”收口 simulated trading 账户—组合桥接 Repository。
- Portfolio、观察授权、旧持仓、统一持仓、映射和分类币种 ORM 输入输出全部具化，QuerySet 边界保留惰性查询语义。
- `ensure_real_account` 改为在事务内锁定来源组合并复查映射，避免并发首次同步创建重复真实账户。
- 发现映射目标账户已不存在时，不再返回悬空账户 ID；现创建新的真实账户并原位修复映射。
- 新增悬空映射修复与重复调用幂等回归，验证映射、目标账户和账户数量一致。

## 第一百二十六批验证结果

- simulated trading account portfolio repository mypy 清零；全仓基线从 `4068 errors / 676 files` 收紧为 `4048 errors / 675 files`，净减少 `20 errors / 1 file`。
- 账户桥接、手工交易同步和 simulated trading 集成回归共 `22 passed`。
- 完整 mypy debt ceiling、Django system check、架构检查、改动文件 Ruff 与 diff check 通过；主工作树并行测试治理批次仍在更新 governance baseline，本批继续不覆盖该未提交真源。

## 第一百二十七批

- 按“组合基准绩效影响面 × 历史序列日期一致性”收口 performance report UseCase、绩效 Repository 与动态账本模型桥接。
- 修复部分基准成分缺行情时仍发布不完整组合收益的问题；任一配置成分缺失时组合收益、超额收益和派生指标明确返回空值并给出 warning。
- 多基准日收益不再按数组下标拼接，改为按实际交易日求交集，并与账户日收益日期对齐后计算 Beta、Alpha、Tracking Error 和 Information Ratio。
- 修复缺失成分导致后续成分收益与前一成分权重错配的问题；组合累计收益严格使用代码对应的原始权重。
- 业绩报告拒绝反向日期区间；历史估值现金显式收窄为浮点值，净值时间线现金流变量不再与记录字典串型。
- 行情缺失只降级明确的数据获取异常，数据库与实现错误不再被宽泛异常伪装成“无行情”；真实账户现金流查询同样移除静默吞错。
- 动态账本模型 helper 补齐边界返回标注，连带消除 Alpha Repository 与账本迁移命令的传播型未标注调用债务。
- 新增多基准日期错位、缺失成分和反向日期三组回归。

## 第一百二十七批验证结果

- performance UseCase、performance Repository 与 account ledger bridge mypy 清零；全仓基线从 `4048 errors / 675 files` 收紧为 `4026 errors / 672 files`，净减少 `22 errors / 3 files`。
- 绩效 UseCase、Domain 与账户绩效 API 回归共 `103 passed`。
- 完整 mypy debt ceiling、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过；主工作树并行测试治理批次仍在更新 governance baseline，本批继续不覆盖该未提交真源。

## 第一百二十八批

- 按“每日检查调仓建议影响面 × 不可执行数量安全性”收口 simulated trading daily inspection service。
- 账户、持仓与辅助方法输入输出完成具化，动态仓储返回值在 Application 边界显式收窄。
- 目标资产代码统一去空格并转大写，修复持仓代码大小写不同导致同一资产同时生成卖出与重复买入建议的问题。
- 目标权重仅接受有限且位于 `0..1` 的数值，NaN、无穷值、负权重与超配权重不再进入调仓计算；负漂移阈值统一收紧为零。
- 持仓价格缺失或非正时不再用 `0.01` 伪价格放大建议数量；建议保留金额口径并明确标记数量不可用，新增目标资产同样不再把金额误当作数量。
- 新增资产代码规范化、无效目标权重与缺价数量三类回归。

## 第一百二十八批验证结果

- daily inspection service mypy 清零；全仓基线从 `4026 errors / 672 files` 收紧为 `4021 errors / 671 files`，净减少 `5 errors / 1 file`。
- 日检服务与再平衡建议集成回归共 `25 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff 与 diff check 通过；主工作树并行测试治理批次仍在更新 governance baseline，本批继续不覆盖该未提交真源。

## 第一百二十九批

- 按“模拟交易读模型影响面 × 自动交易候选真实性”收口 simulated trading Facade 与资产池查询服务。
- Facade 使用最小 Application Protocol，不再从 provider 模块隐式导入 Infrastructure 实现类型；账户与持仓读依赖完成具化。
- 持仓仓储故障不再被伪装为空仓或“不存在”，避免上层在数据源故障时据此重复买入；账户概览改为基于当前持仓重算市值与总资产，不再混用可能滞后的账户缓存市值。
- 基金等资产的小数份额不再被强制转换为整数，避免策略读模型丢失真实持仓数量；零初始资金不再被静默替换为一百万元。
- 资产池类型、资产代码与数量上限完成输入规范化；无效分数和非正 limit 不再进入仓储查询，单次候选查询上限收紧为 500。
- 修复信号仓储实际返回 `id`、服务却读取 `signal_id` 导致候选增强失败的问题；同资产多个倒序信号只保留第一条最新信号，不再被旧信号覆盖。
- 资产池与信号按标准化证券代码连接，增强结果使用副本，不再原位污染仓储返回字典。

## 第一百二十九批验证结果

- simulated trading Facade 与 asset pool query service mypy 清零；隔离口径从 `4021 errors / 671 files` 收紧为 `4015 errors / 669 files`，净减少 `6 errors / 2 files`。
- 合入期间并行测试治理提交先把统一全仓基线收紧至 `3916 errors / 658 files`；最终集成复核再移除资产池服务的一条陈旧记录，统一基线收紧为 `3915 errors / 657 files`。
- Facade、资产池和 strategy provider 读服务回归共 `6 passed`。
- 增量 mypy、隔离与集成 mypy debt ceiling、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十批

- 按“账户自动风控执行影响面 × 重试幂等性”收口账户止损、止盈、波动率 Celery 任务、止盈用例和相关 Repository Protocol。
- 组合止损止盈任务增加可序列化阶段检查点；止损阶段成功而止盈阶段失败时，Celery 重试只执行未完成的止盈阶段，不再重复运行已成功止损。
- 分批止盈执行改为在事务内锁定止盈配置和关联持仓，通过预期档位比较避免并发重复成交；每次成交后消费已触发档位，最后一档完成时自动停用配置。
- 已平仓持仓、已停用配置或档位已被其他任务推进时不再重复卖出，也不虚报本次触发成功。
- 止盈用例返回全部已检查结果，未触发持仓也进入检查计数，修复任务的 `checked_count` 长期等同于触发数的问题。
- Celery 动态边界、账户风控输出、通知 helper 与 Domain Repository Protocol 完成具化，保留的 Celery decorator ignore 精确限定为第三方 `misc` 边界。
- 新增组合任务断点重试、分批档位消费、未触发计数和真实 ORM 连续三档止盈回归。

## 第一百三十批验证结果

- account risk tasks、stop-loss/take-profit use cases 与 Domain interfaces mypy 清零；全仓基线从 `3915 errors / 657 files` 收紧为 `3869 errors / 654 files`，净减少 `46 errors / 3 files`。
- 账户周期任务、止损止盈用例与真实 Repository 执行回归共 `13 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十一批

- 按“组合级自动减仓资金影响面 × 并发重试安全性”收口账户波动率分析与调整执行链路。
- 波动率配置、历史快照、持仓与批量执行结果建立精确 Domain Protocol / TypedDict，Application 只依赖 provider 暴露的抽象边界。
- 波动率、容忍度、最大降仓幅度、快照总值、持仓数量和成交价格统一拒绝 NaN、无穷值、非正值与越界配置，避免非法数值进入成交。
- 调整用例在写库前完成全部持仓指令校验；任一持仓无效时整批拒绝，不再出现前序持仓已卖、后续持仓失败的部分成功。
- 批量减仓以组合行锁串行化并在同一事务内执行全部持仓，任一成交失败即整体回滚。
- 基于组合、快照日期和调整参数生成确定性幂等键；相同分析快照重复或并发执行时复用已有成交结果，不再重复减仓，也不虚报本次已减仓持仓。
- 波动率分析用例正确使用注入的分析依赖，不再在执行方法内绕过测试或 composition root 新建具体用例。
- 新增非法控制参数、无效成交价格、确定性幂等键、真实 ORM 重复执行和事务整体回滚回归。

## 第一百三十一批验证结果

- account volatility use cases、Domain services/interfaces 与 position repository mypy 清零；全仓基线从 `3869 errors / 654 files` 收紧为 `3858 errors / 653 files`，净减少 `11 errors / 1 file`。
- 波动率领域服务、调整用例、真实 Repository、周期任务和账户 API 回归共 `49 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十二批

- 按“手工券商成交导入影响面 × 跨账本一致性”收口 manual trade import 用例与持久化事务边界。
- 每条导入记录在 Infrastructure 提供的原子上下文内串行锁定所属组合，统一持仓变更、旧账本投影、成交记录和建议匹配任一步失败时整行回滚。
- 重复成交键检查移入组合锁和事务内部，关闭并发任务同时通过预检后重复变更持仓的窗口。
- Application 动态 parser、账本兼容桥接和推荐匹配返回值在边界显式标注、收窄，不再把兼容构造器的动态类型传播到业务编排。
- 新增成交记录写入失败回归，验证统一持仓、旧持仓和成交记录均不残留部分成功状态。

## 第一百三十二批验证结果

- account manual trade sync mypy 清零；全仓基线从 `3858 errors / 653 files` 收紧为 `3846 errors / 652 files`，净减少 `12 errors / 1 file`。
- 手工成交导入、重复导入、建议匹配和失败回滚回归共 `6 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十三批

- 按“实盘委托资金影响面 × 风险结论与并发控制”收口 broker execution 订单草稿创建和 kill switch 持久化边界。
- 订单数量、限价、账户资产、可用资金、持仓市值和行情价格统一拒绝 NaN、无穷值、负值及非正关键值；计划输入错误直接拒绝，服务端行情失真则生成风险拒绝草稿。
- 风险引擎明确返回 `passed=False` 时不再因 violations 文本为空而被重写为通过，风险结论改为“原始通过且无违规”才可进入待审批状态。
- 订单标的与方向标准化，空幂等键在 Application 边界拒绝；Decimal 原始数量和价格保留到持久化层，避免先转 float 导致大整数精度改变。
- 订单创建在事务内锁定账户绑定，并以锁内最新配置重新验证授权、白名单、单笔限额、价格偏离、当日累计限额和 kill switch。
- 下单与 kill switch 使用同一账户绑定锁顺序；停盘操作锁定全部目标绑定后再写控制状态，关闭停盘与下单并发穿透窗口。
- 幂等结果在获取账户锁后再次查询；相同幂等键的并发后到请求返回先到请求的持久化结果，不再尝试创建第二张订单。
- 新增风险引擎空违规拒绝、非法数值、NaN 行情/账户快照、锁后限额变化和锁后幂等重放回归。

## 第一百三十三批验证结果

- broker execution live-order use cases mypy 清零；全仓基线从 `3846 errors / 652 files` 收紧为 `3839 errors / 651 files`，净减少 `7 errors / 1 file`。
- broker execution 风险、权限、kill switch、幂等和关键订单安全回归共 `56 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十四批

- 按“实盘权限管理影响面 × Agent 凭据与限额配置并发安全”收口 broker execution 管理写用例和持久化边界。
- 账户绑定、访问授权、凭据轮换/吊销、连接同步、执行设置和对账处置用例统一依赖 BrokerExecution Repository Protocol，清除动态返回和隐式可空构造参数。
- 所有提交幂等键统一去空格并拒绝空值；账户、用户、Agent、credential、reason 和 reconciliation resolution 在 Application 边界完成规范化与白名单校验。
- 布尔配置只接受真实 bool，不再把字符串 `"false"` 按 Python truthiness 转成 True；绑定激活必须提供 broker account reference。
- 凭据轮换在事务内锁定 Agent 与目标账户绑定，以锁内最新状态复核全部 account scope；绑定在轮换窗口失效时不再签发带失效范围的 secret。
- 凭据轮换在取锁后再次查询幂等结果，并发后到请求只返回脱敏重放结果，不创建第二份 credential 或泄露第二个 token。
- 执行设置更新锁定与下单相同的账户绑定行，并在锁内重查幂等结果；金额、价格偏离、数量和布尔配置统一拒绝 NaN、无穷、越界和错误类型。
- 新增字符串布尔、凭据范围锁内失效、凭据锁后幂等重放和设置写入边界回归。

## 第一百三十四批验证结果

- broker execution management use cases mypy 清零；全仓基线从 `3839 errors / 651 files` 收紧为 `3831 errors / 650 files`，净减少 `8 errors / 1 file`。
- broker execution 管理 API、权限、凭据、Agent 恢复和 fake-agent 全流程回归共 `41 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十五批

- 按“机器凭据认证影响面 × Agent 请求失败关闭”收口 broker execution Agent authentication 与 machine-only use cases。
- Agent credential ID 在进入 Django UUIDField 查询前必须解析为规范 UUID；格式错误但自行签名正确的 token 不再抛 ORM ValidationError/500，而是稳定返回认证失败。
- Agent ID、request ID、nonce、timestamp、signature、secret 和 required scope 增加长度、格式与完整性约束，避免超长 header 在 nonce/audit 落库时触发数据库错误。
- 认证失败审计对非法 UUID 不再执行 UUIDField 查询，仍可记录脱敏 credential、Agent、来源 IP 和有界 failure code。
- Agent 上下文统一收窄并校验正整数 agent/account scope；空 scope、负账户或非法 Agent 主键不得进入 Repository。
- 订单/命令租约参数由静默 clamp 改为显式拒绝，事件批次必须为 1..200；提交确认和命令完成要求非空标识与真实 bool，不再把字符串 `"false"` 解释为成功。
- Agent machine use cases 全部依赖 BrokerExecution Repository Protocol，移除动态返回与隐式可空构造参数。
- 新增签名正确但 credential UUID 非法、Agent scope 越界、静默 limit clamp、字符串成功标志和空事件批次回归。

## 第一百三十五批验证结果

- broker execution agent auth 与 machine use cases mypy 清零；全仓基线从 `3831 errors / 650 files` 收紧为 `3823 errors / 648 files`，净减少 `8 errors / 2 files`。
- Agent 认证/API 回归 `39 passed`，关键恢复与 fake-agent 流程回归 `14 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十六批

- 按“买入资金真实性 × 交易费用配置唯一真源”收口模拟交易最低手续费校验。
- 买入用例在资金校验前读取按资产类型生效的数据库费率配置，并以配置中的佣金、过户费和滑点计算完整所需现金；缺少生效配置时失败关闭。
- Domain 买入约束不再允许省略 `FeeConfig` 后回退到账户级费率，关闭绕过最低手续费和其他交易费用的调用旁路。
- `FeeConfig.min_commission` 与 ORM 新建字段取消 `5.0` 运行时默认值，Repository 创建费率配置时要求显式提供最低手续费；已有数据库值不变。
- 新增迁移 `0019_require_explicit_min_commission`，确保后续通过 ORM/Admin 新建费率配置时必须明确填写最低手续费。
- 新增非 5 元最低手续费资金不足回归，以及 Domain/ORM 均无最低手续费默认值的契约回归。

## 第一百三十六批验证结果

- 模拟交易订单、Domain 规则与买入信号追踪回归 `21 passed`。
- 全仓 mypy debt ceiling 保持 `3823 errors / 648 files`，本批未新增类型债务。
- Django migration state、Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十七批

- 按“实盘人工审批完整性 × Agent 提交前最终校验”收口 broker execution 审批摘要。
- 审批摘要新增绑定 Agent、市场、预计金额、完整风险快照和审批模式；账户、标的、方向、委托类型、数量、限价、有效期、风险策略及来源证据继续纳入摘要。
- `estimated_amount` 不再游离于审批摘要之外，审批后降低预计金额无法再绕过 Agent 提交前的现金与限额复核。
- 风险快照使用排序 JSON、来源 ID 使用排序元组生成稳定摘要，等价输入顺序变化不会造成误失效。
- 摘要失效后的撤销审批改为先在事务中持久化，再向 Agent 返回冲突；修复原先“保存后在原事务抛错”导致撤销状态被整体回滚的问题。
- 审批投影的整数与数组边界显式验证，broker execution Domain services 清除动态迭代和整数转换类型债务。
- 新增全部执行关键字段篡改摘要变化、JSON/来源顺序稳定性，以及真实 ORM 修改预计金额后撤销审批回归。

## 第一百三十七批验证结果

- broker execution Domain services、entities 与 rules mypy 清零；全仓基线从 `3823 errors / 648 files` 收紧为 `3820 errors / 647 files`，净减少 `3 errors / 1 file`。
- broker execution 审批、权限、风险、对账与 Agent 提交回归共 `56 passed`。
- 增量 mypy、Django system check、架构检查、改动文件 Ruff 与 diff check 通过。

## 第一百三十八批

- 按“个股估值资金影响面 × Equity 核心读链路覆盖面”收口 Equity 核心 Application use cases、repository provider、Domain services 与市场/Regime/股票池适配器。
- Equity Application 增加股票读取、Regime 历史和评分配置 Protocol，移除按 `TypeError` 文本猜测 Repository 是否支持 `hydrate` 的动态重试；缓存读取、远端补数和返回实体均通过显式契约编排。
- 股票筛选自定义规则增加有限数值、非负市值、1..100 数量与字符串行业列表校验；NaN、无穷、布尔冒充数字和错误容器不再进入 Domain 筛选。
- DCF 当前价改为最新日线收盘价，不再使用错误的 `总市值 / PS` 伪造股价；每股内在价值按 `总市值 / 当前价` 推导总股本后计算。
- DCF 对非有限/负自由现金流、无效预测期、非有限增长率和“折现率不高于永续增长率”失败关闭；Decimal 计算由字符串构造，避免二进制浮点误差进入现金流折现。
- 无估值、市值或真实收盘价时 DCF 返回明确失败，不再输出表面成功但不可解释的 `None`/伪价格结果。
- Regime 相关性使用构造函数注入的历史 Repository，不再绕过依赖注入另建适配器；空历史或首个真实快照之前的日期保持未知，不再整段伪造为 `Recovery`。
- Equity provider 补齐显式规则导出和仓储返回类型；适配器补齐构造器、DataFrame/JSON/缓存边界类型，并对缓存股票池执行字符串白名单归一化。

## 第一百三十八批验证结果

- Equity use cases、provider、Domain services 与 adapters 定向/增量 mypy 清零；其类型改善同时消除下游 Interface、Alpha 和估值任务调用债务。
- 全仓基线从 `3820 errors / 647 files` 收紧为 `3756 errors / 643 files`，净减少 `64 errors / 4 files`。
- Equity 核心用例、估值、Regime、Domain、页面导航回归 `103 passed`；包含 Equity API 边界的扩展回归 `54 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百三十九批

- 按“股票评分配置真实性 × 激活版本一致性”收口 Equity 配置仓储和 ORM 配置约束。
- 股票筛选不再在缺少数据库配置时使用代码内置评分权重；没有启用配置会返回明确失败，数据库读取异常继续向上暴露，不再伪装成正常评分结果。
- 评分权重查询由任意取首条改为要求唯一激活记录；历史重复激活数据不再被静默忽略。
- 评分权重保存和估值修复配置激活进入事务边界，切换前锁定并停用旧版本。
- `ScoringWeightConfigModel` 与 `ValuationRepairConfigModel` 增加数据库条件唯一约束，保证每类配置最多一个 `is_active=True` 版本。
- 新增迁移 `0009_enforce_single_active_configs`：约束建立前按更新时间和主键保留最新激活版本，并停用其余历史重复记录。
- 新增缺配置失败关闭、数据库故障不吞异常、评分配置原子切换、数据库唯一约束和估值修复激活切换回归。

## 第一百三十九批验证结果

- Equity 配置仓储、ORM models 与筛选 use case 定向/增量 mypy 清零；全仓基线从 `3756 errors / 643 files` 收紧为 `3711 errors / 641 files`，净减少 `45 errors / 2 files`。
- Equity 配置仓储、筛选用例、评分 Domain 与估值修复配置 API 回归 `27 passed`。
- Django migration state/plan、Django system check、架构检查通过。

## 第一百四十批

- 按“估值与财务数据新鲜度影响面 × Celery 任务状态真实性”收口 Equity 同步任务及兼容别名。
- 估值同步、质量校验、同步校验扫描与财务同步入口增加正整数上限、动态数据源标识、股票代码、股票池和回看窗口校验；布尔冒充整数、空值、越界和错误容器不再进入用例。
- 数据源只校验通用标识格式，继续由数据库配置决定可用 provider，不在任务代码中硬编码数据源名单。
- 估值同步成功响应必须包含有效 payload 且实际写入至少一条记录；写入 0 条时任务失败关闭，不再继续执行质量校验和估值修复扫描。
- 质量门禁只接受真实布尔值 `True`，字符串等 truthy 值不能误放行扫描。
- 财务同步显式空股票列表不再回退为全市场同步；股票代码去重采用有界集合，批量上限固定为 5000 项。
- 财务同步校验 `stored_count` 为非负整数；全部股票失败返回失败，部分失败显式返回 `partial_success=True`，不再统一伪报成功。
- Celery 兼容别名补齐精确返回契约；任务通过 Application provider factory 获取仓储，不再依赖未显式导出的 concrete class。

## 第一百四十批验证结果

- Equity 估值/财务同步任务与兼容别名定向 mypy 清零；全仓基线从 `3711 errors / 641 files` 收紧为 `3676 errors / 639 files`，净减少 `35 errors / 2 files`。
- 同步任务、估值同步用例、质量门禁、Celery 注册别名与调度配置回归 `18 passed`。

## 第一百四十一批

- 按“政策闸门影响面 × 定时任务破坏性操作安全”收口 Policy Celery tasks。
- 政策日志、RSS 日志和审核队列清理任务增加 1..36500 天边界；负数、零、布尔值和错误类型在访问 Repository 前失败，不再把截止日期推进到未来后扩大删除范围。
- 审核自动分配增加 1..1000 单人上限，非法容量不再进入分配循环。
- RSS 单源抓取要求正整数 source ID，非法 ID 不再进入外部数据抓取与 AI 分类链路。
- Signal 重评严格校验 P0..P3 档位和 ISO 日期；非法上下文不再进入 Regime 查询与下游信号拒绝逻辑。
- Signal 重评失败改为将 Celery retry 异常继续抛出，不再用宽泛 `except Exception` 把已安排的重试吞掉并伪报普通错误结果。
- 所有政策定时任务补齐有界输入、精确 payload 返回和 Celery 动态边界类型，通知服务继续通过延迟 factory 获取。

## 第一百四十一批验证结果

- Policy Celery tasks 定向 mypy 清零；全仓基线从 `3676 errors / 639 files` 收紧为 `3645 errors / 638 files`，净减少 `31 errors / 1 file`。
- 政策状态、转档通知、清理、审核分配、SLA、闸门刷新与 Signal 重评回归 `29 passed`。

## 第一百四十二批

- 按“对冲风险配置影响面 × API 写权限与计算资源边界”收口 Hedge DRF views 和 serializers。
- Hedge Pair 创建、修改、删除、启停，以及组合全量更新、监控执行和告警解决改为仅管理员可操作；普通已登录用户仍可读取目录、快照、告警和执行纯计算。
- Hedge HTML 页面要求登录，启停对冲对、更新组合、执行监控和解决告警等写入口要求 staff，关闭仅靠 CSRF 但允许匿名/普通用户操作的权限缺口。
- 相关性矩阵限制为 2..50 个不同资产、2..5000 天窗口；资产代码去空格、转大写并保持首次出现顺序，重复资产不能伪装成有效矩阵输入。
- 两资产相关性计算拒绝相同资产、空代码和超大窗口；近期告警查询限制为 1..3650 天，不再把非法 days 静默回退为 7 天。
- 对冲比率 pair name 增加长度与空值校验；原有缺参错误文本继续保持兼容。
- 告警解决通过路由对象取得并转换真实整数主键，不再把 `str | None` 直接传入 Application。
- Hedge ViewSet、页面 handler 与 Serializer 补齐 DRF Request/Response、HttpRequest/HttpResponse、泛型和 payload 边界类型。

## 第一百四十二批验证结果

- Hedge views 与 serializers 定向 mypy 清零；隔离并行工作区改动后，全仓基线从 `3645 errors / 638 files` 收紧为 `3607 errors / 636 files`，净减少 `38 errors / 2 files`。
- Hedge API 权限、相关性输入、快照/告警契约与路由兼容回归 `44 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与 diff check 通过。

## 第一百四十三批

- 按“AI 凭据与配额影响面 × 持久化失败关闭”收口 AI Provider repositories。
- 非标准密文、损坏密文和当前环境无法解密的凭据统一失败关闭，不再把加密字段内容当作明文 API Key 使用；已有无前缀但可正常解密的历史密文继续兼容。
- Provider 创建与更新增加可写字段白名单，禁止调用方直接注入 `api_key_encrypted`；user scope 必须绑定 owner，切换 scope 时在事务内锁定并基于最新记录复核。
- Usage 日志拒绝空模型、负数/布尔 token、负延迟、非有限或负成本、非法状态与非法 provider scope；总 token 不得小于 prompt 与 completion 之和。
- Usage 日志写入与 provider `last_used_at` 更新进入同一事务，任一步失败均不留下部分成功状态。
- 用户 fallback 日/月配额拒绝负数、NaN 和无穷值；批量应用在单事务中完成，避免部分用户已更新而后续用户失败。
- 近期日志 limit 限制为 1..1000，避免无界 ORM 查询。
- Repository 用户参数与实际默认 Django `User` 模型对齐，日期聚合别名显式化，清除 ORM 查询类型债务。

## 第一百四十三批验证结果

- AI Provider repositories 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3607 errors / 636 files` 收紧为 `3578 errors / 635 files`，净减少 `29 errors / 1 file`。
- AI Provider 凭据、用户路由、Usage/Quota 持久化和 API 边界回归共 `40 passed`。
- Django system check、架构检查、改动文件 Ruff 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十四批

- 按“宏观滤波配置影响面 × API 持久化权限与预览无副作用”收口 Filter API。
- Filter API 根信息、指标、历史结果、配置读取和纯计算统一要求登录；健康检查继续明确允许匿名探活。
- 普通用户仅可使用 `save_results=false` 执行无副作用滤波计算，默认持久化或显式持久化请求在进入用例前返回 403；管理员继续可以写入计算结果。
- Filter 配置 PATCH/DELETE 改为仅管理员可操作，普通登录用户保留配置读取权限。
- Kalman 计算仅在 `save_results=true` 时持久化增量状态；Compare 和普通用户预览不再以“未保存结果”为名修改 Kalman state。
- Apply 成功但缺少 series 时失败关闭并返回 500，不再把可空结果传入序列化边界。
- Compatibility Repository、ViewSet、APIView、Request/Response 和序列化 helper 补齐精确类型，清除 Filter API 视图类型债务。

## 第一百四十四批验证结果

- Filter API views 与相关 use case 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3578 errors / 635 files` 收紧为 `3552 errors / 634 files`，净减少 `26 errors / 1 file`。
- Filter API 权限、契约和 Kalman 状态副作用回归共 `13 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十五批

- 按“全局 AI 能力路由影响面 × MCP 治理输入边界”收口 AI Capability API。
- 能力目录 `enabled_only` 只接受明确的 `true/false`，不再把任意字符串静默解释为包含禁用能力。
- 管理员同步入口只接受 `full/incremental` 和已注册的 builtin、terminal command、MCP tool、API 来源；错误类型、未知来源在进入同步用例前返回 400，避免伪成功同步日志。
- MCP 工具目录 limit 改为严格 1..300 整数边界，非法、零值或超上限不再静默回退或截断。
- Web 显式执行 action 只接受非空字符串 capability key，容器或其他 truthy 动态值不能进入能力执行链。
- API handler、Request/Response、路由 payload 和 Capability ViewSet 补齐精确类型；仅提供自定义 list 的重复 ReadOnlyModelViewSet 改为 ViewSet，避免伪 ORM queryset 契约。
- Catalog governance 增加 Repository 与 API collector Protocol，composition factory 显式返回采集契约，并同步清除下游同步、管理命令和界面调用债务。

## 第一百四十五批验证结果

- AI Capability API、governance service 与 repository provider 增量 mypy 清零；下游调用同步受益。隔离并行工作区改动后，全仓基线从 `3552 errors / 634 files` 收紧为 `3518 errors / 631 files`，净减少 `34 errors / 3 files`。
- AI Capability 权限、同步范围、目录参数、路由上下文与搜索回归 `17 passed`。
- MCP 相关固定最小回归包：TUI workbench、Terminal agent service、SDK client、内部 SSL redirect 共 `229 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十六批

- 按“全局 Prompt/Chain 行为影响面 × AI 执行日志敏感性”收口 Prompt interface。
- Chain 配置创建、全量/部分更新和删除改为仅管理员可操作；普通登录用户仍可读取与执行已审核 Chain。
- Execution Log 包含渲染 Prompt、占位符、AI 输出和错误上下文，统一收紧为仅管理员可读取；recent limit 严格限制为 1..200，非法值返回 400。
- Prompt 管理 HTML 页面增加 staff 门禁，普通登录用户不能绕过 API 权限直接进入管理面。
- Chat 历史限制为最多 50 条、单条最多 20000 字符，仅允许 user/assistant 角色；调用方不能通过 history 注入 system 消息覆盖治理 Prompt，且视图复制历史后再追加当前消息。
- Chat/Agent session、输入、模型、system prompt、token、temperature、轮次、context scope 和 tool name 数量增加有界校验，防止无界请求进入 AI 与工具执行链。
- Prompt/Chain ViewSet、APIView、Request/Response、权限和页面 handler 补齐精确类型，所有执行类 API 显式声明登录权限。

## 第一百四十六批验证结果

- Prompt views 与 serializers 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3518 errors / 631 files` 收紧为 `3493 errors / 630 files`，净减少 `25 errors / 1 file`。
- Prompt 模板、Chain 权限、执行日志、Chat 历史、Agent 资源边界和 provider/model 契约回归共 `21 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十七批

- 按“投资信号可执行性影响面 × 状态变更权限”收口 Signal HTML 与 DRF interfaces。
- HTML 信号管理页、准入信息、指标目录和 AI 证伪解析要求登录；创建、审批、拒绝、证伪、删除、单条证伪检查和批量检查统一要求 staff。
- DRF Signal 创建、全量/部分更新、删除、审批、拒绝和证伪统一要求管理员；普通登录用户保留列表、详情、统计、准入检查和只读验证。
- Unified Signal collect 与 executed 状态写入改为仅管理员可操作；列表、摘要、待执行与资产查询继续要求登录。
- Unified 日期、优先级和回看窗口改为严格 ISO 日期、1..100 priority 与 1..3650 天边界，非法值返回 400，不再静默回退到今天或无限扩展查询。
- HTML 状态写入口拒绝空 signal ID；DRF 拒绝/证伪原因必须为 1..1000 字符字符串，容器、空值和超长文本不能进入持久化。
- Signal ViewSet、页面 handler、Request/Response、权限与动态兼容构造边界补齐精确类型。

## 第一百四十七批验证结果

- Signal HTML views 与 DRF API views 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3493 errors / 630 files` 收紧为 `3449 errors / 628 files`，净减少 `44 errors / 2 files`。
- Signal 页面委托、状态权限、准入、Unified 查询/采集/执行和 API 契约回归共 `19 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十八批

- 按“生产数据连接验收影响面 × 运维命令退出状态真实性”收口 `test_data_connections` 管理命令。
- 每个测试组执行后同时检查方法返回值与新增诊断记录；只要内部记录任意 error，即使测试方法误返回 True，整组仍判定失败。
- 测试组未生成任何诊断记录时不再计为通过，而是记录 Runner error，关闭空实现、提前返回或漏记证据造成的“空通过”。
- PMI 同步返回 `success=false` 改为 error，不再降级成 warning 后让命令整体成功；Regime 计算等内部异常同样由统一结果聚合识别。
- 命令在任一测试组失败时抛出 `CommandError`，为 CI、readiness 和自动化调用提供真实非零退出码。
- 新增 `--output` 与 `--no-write` 控制；JSON 证据包含 `overall_success`，通过同目录临时文件原子替换，避免中断后留下半写入报告。
- 异常详情落盘前脱敏 token、API key、secret 和 password 值，降低诊断报告进入仓库或交接材料时泄露凭据的风险。
- Diagnostic status/result、stdout、测试函数、CLI options 和所有命令方法补齐精确类型，并使用 `UTC` 生成时区感知时间。

## 第一百四十八批验证结果

- `test_data_connections` 管理命令增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3449 errors / 628 files` 收紧为 `3376 errors / 627 files`，净减少 `73 errors / 1 file`。
- 内部 error 聚合、空证据失败、凭据脱敏、原子证据输出、命令非零退出和 `--no-write` 回归共 `6 passed`。
- Django system check、架构检查、改动文件 Ruff、Black 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百四十九批

- 按“Alpha 评分生产链路影响面 × Qlib 运行失败真实性”收口 Qlib 初始化与预测运行时。
- Qlib 关闭时预测改为显式失败，不再返回空列表伪装成成功但无候选股票；模型文件缺失、模型不支持 `predict()`、股票池为空和预测无有限分数均保持失败关闭。
- `top_n` 增加 1..5000 严格整数边界，布尔值、零值和超大请求在访问 Qlib、模型文件或行情数据前拒绝。
- 预测结果统一过滤 NaN 与正负无穷；同一股票的不同代码格式归一化后只保留最高有限分数，避免重复标的挤占排名。
- Qlib region、交易日、股票池、handler、运行配置和 JSON-safe 转换边界补齐精确类型；动态第三方对象仅在 Qlib/Pandas/NumPy 边界使用局部收窄。
- Pandas 兼容补丁与 Qlib 初始化标记继续保持进程内幂等，同时不再依赖未声明的函数动态属性类型。

## 第一百四十九批验证结果

- Qlib 初始化与预测运行时增量 mypy 清零，并同步减少 artifact runtime 的一个下游调用债务；隔离并行工作区改动后，全仓基线从 `3376 errors / 627 files` 收紧为 `3318 errors / 625 files`，净减少 `58 errors / 2 files`。
- Qlib 运行契约、训练组件和集成回归共 `69 passed`；覆盖禁用失败、结果上限、非有限分数过滤、代码去重、训练和数据集适配。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十批

- 按“策略执行资金影响面 × 投资组合归属边界”收口 Strategy 执行、评估与模拟脚本接口。
- 页面立即执行改为调用 Application 层已有的 assignment-aware 执行服务；传入的 `portfolio_id` 必须属于该策略的活跃绑定，不能再把任意有效账户主键直接交给执行器。
- 不指定组合时仍执行当前用户自有策略的全部活跃绑定；无活跃绑定明确返回 400，不再把零次执行伪报为成功。
- Assignment ViewSet 的列表、详情、按组合查询、启停、创建和修改统一按“策略所有者 + 账户所有者”双重归属收口；普通用户看不到或修改不了其他用户绑定，跨用户策略/账户不能组成新绑定。
- Assignment 创建者改为只读并始终由服务端当前账户资料写入，调用方不能伪造 `assigned_by`；staff 保留全局读取能力但不能借创建/修改接口替其他用户拼接绑定。
- 执行请求只接受 `portfolio_id`，并严格要求正整数；JSON 数组、未知字段、超大请求体和布尔冒充整数均在进入执行链前拒绝。
- 策略执行内部异常不再把原始异常文本返回给用户，避免数据库、路径或运行配置细节泄露；预期的绑定/输入错误继续返回可操作的 400。
- 执行评估对价格、权益、持仓市值、止损价、ATR、成交量、日内盈亏和交易次数增加正值/非负值/有限值及合理上限校验；NaN 和无穷不能进入仓位与风险引擎。
- 模拟脚本接口限制 JSON 请求体和脚本长度，只接受字符串脚本；测试 Strategy 的 hybrid 脚本分支恢复实际预览，脚本失败不再被吞掉后伪报成功空信号。
- Mock provider、HttpRequest/JsonResponse、JSON payload、settings 边界和执行结果补齐精确类型，Interface 继续仅编排 Application/Domain 服务。

## 第一百五十批验证结果

- Strategy 执行、Assignment API 与评估 serializer 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3318 errors / 625 files` 收紧为 `3286 errors / 623 files`，净减少 `32 errors / 2 files`。
- Strategy API 边界、执行全流程、serializer、脚本引擎、视图结构、repository 生命周期和自动交易集成回归共 `64 passed`；新增跨用户绑定拒绝、未绑定组合不落执行日志、非有限资金输入和超大脚本请求覆盖。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十一批

- 按“用户脚本执行可用性影响面 × 策略运行资源边界”收口 Strategy Script Engine。
- 未知 `security_mode` 改为失败关闭，不再把拼写错误或未注册模式静默解释为权限最宽的 `relaxed`。
- 脚本引擎统一限制源码最多 50000 字符、AST 最多 2000 节点、单个 `range` 最多 10000 项、单次最多输出 1000 条信号；接口预检与核心引擎共享同一源码长度真源。
- 禁止 `while`、函数/异步函数、类和 lambda，关闭无限循环与递归在当前进程内长期占用 worker 的直接路径；受控 `range` 在实际迭代前验证整数和规模。
- `itertools` 与 `random` 从允许模块中移除，避免无界迭代器及不可复现随机分支进入策略脚本；多 import 语句逐个检查，不再只验证第一个模块。
- Script API 对指标代码、资产池 limit、信号代码/动作/权重/置信度/原因增加类型、长度、有限值和范围校验；provider 返回的有效信号与持仓最多向脚本暴露 1000 项。
- RestrictedPython 编译结果必须收窄为真实 `CodeType`，旧版结果仅接受有效嵌套 code；异常返回对象不能直接进入 `exec`。
- Provider callback、safe globals/builtins、动态 import、编译结果、本地变量和信号 payload 补齐精确类型，第三方 Any 仅保留在 RestrictedPython 动态边界。

## 第一百五十一批验证结果

- Strategy Script Engine 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3286 errors / 623 files` 收紧为 `3268 errors / 622 files`，净减少 `18 errors / 1 file`。
- Strategy API、执行全流程、script engine、serializer、视图结构、repository 生命周期和自动交易集成回归共 `71 passed`；新增未知模式、无限循环、递归、超大 range、源码、AST、资产池、非有限信号与输出数量覆盖。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十二批

- 按“策略信号生成影响面 × 执行证据完整性”收口 Strategy Executor 与 Rule Evaluator。
- 策略 ID 和组合 ID 在访问仓储或数据提供者前严格要求正整数，布尔值、零值和负值不再进入执行链。
- 宏观、Regime、资产池、组合和有效信号任一必需上下文读取异常或返回畸形结构时失败关闭，不再用空字典、空列表或零现金继续执行并伪报成功。
- 组合现金必须是非负有限数，持仓、信号和资产池结构在进入规则引擎前收窄；降级资产、畸形质量元数据、空资产代码和非有限评分不能生成推荐。
- 执行日志持久化失败时结果改为失败并清空信号，防止上层消费无法审计的策略建议。
- 同一资产被多条规则或混合执行分支重复命中时，只保留先执行的高优先级建议，避免重复或冲突信号进入下游。
- 规则分数比较增加运行时数值校验；批量评估拒绝没有持久化 ID 的规则，避免 `None` 键覆盖结果。
- Strategy Executor、Rule Evaluator 的容器、动态值、执行结果和批量映射补齐精确类型。

## 第一百五十二批验证结果

- Strategy Executor 与 Rule Evaluator 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3268 errors / 622 files` 收紧为 `3252 errors / 620 files`，净减少 `16 errors / 2 files`。
- 规则评估、策略执行、执行全流程、自动交易集成和 Strategy API 边界回归共 `78 passed`；覆盖上下文不可用、非有限现金、审计失败、无效主键和重复信号。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十三批

- 按“Alpha 降级链影响面 × 历史评分前视偏差”收口 Alpha Provider Base 与 Cache Provider。
- 缓存选择同时限制 `intended_trade_date` 和 `asof_date` 不得晚于请求交易日；账户池使用宽基 Qlib 缓存裁剪时执行同一限制，未来生成的缓存不能进入历史评分。
- 缓存健康检查改用真实 `asof_date` 计算新鲜度，并对未来 `asof_date` 失败关闭，不再按计划交易日把未来缓存判为可用。
- 数据库缓存行的 `asof_date` 与 `intended_trade_date` 成为评分审计时间唯一真源，行内 JSON 不能覆盖为另一个未来时间。
- 缓存评分过滤空代码、重复代码、NaN/无穷、越界 score/confidence、非法 rank 和布尔数值；同一标准代码只保留首个有效结果。
- `top_n`、最大陈旧天数、清理保留天数、日期查询跨度、股票池标识和账户池交易日增加严格边界；布尔值、零负值、超大请求与跨期 scope 在查询前拒绝。
- Provider 异常结果不再向上层暴露数据库或运行时原始异常文本；详细信息仅进入服务端日志。
- Provider 装饰器使用 ParamSpec/TypeVar 保留被装饰函数签名，并同步清除 Simple、ETF 与 Qlib 调用侧的装饰器类型债务。

## 第一百五十三批验证结果

- Alpha Provider Base 与 Cache Provider 增量 mypy 清零，并同步消除 Simple/ETF/Qlib 装饰器下游债务；隔离并行工作区改动后，全仓基线从 `3252 errors / 620 files` 收紧为 `3212 errors / 617 files`，净减少 `40 errors / 3 files`。
- Alpha Cache、代码归一化、Simple/ETF/Qlib Provider、任务、服务与集成回归共 `115 passed`；覆盖未来缓存、未来行内时间、非法结果上限、跨期 scope、非有限评分和重复代码。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十四批

- 按“账户资金流水影响面 × 跨组合写入与账本完整性”收口 Transaction、Capital Flow 与券商成交导入接口。
- 创建交易统一验证 portfolio 属于当前用户；省略可选 position 时不能再向他人组合写入交易记录。
- 关联 position 必须同时属于目标组合、属于当前用户且资产代码一致，避免把一个持仓的成交挂到另一组合或另一资产。
- Transaction API 改为追加型账本，仅保留创建、列表和详情；未声明的 PUT/PATCH/DELETE 不再开放，历史成交不能被原地改写或删除。
- Capital Flow API 禁用 PUT/PATCH，继续保留创建、列表、详情和契约已声明的删除；创建 serializer 显式接收正整数 portfolio ID 并由服务端解析归属。
- 交易数量拒绝 NaN/无穷、布尔、零负值和超大值；价格、手续费和资金流水金额必须为有效 Decimal，未来交易时间拒绝；成交金额使用 Decimal 并按分四舍五入，不再经过二进制浮点。
- 券商文件只接受 CSV/XLSX/XLS、最大 10 MiB、组合 ID 必须为正整数；单次最多 5000 行，畸形 parser payload 失败关闭。
- 券商成交导入行内部异常只写服务端日志，API 返回稳定通用错误，不再泄露数据库或账本异常文本。
- ViewSet、Request/Response、Serializer、上传文件与认证用户 ID 边界补齐精确类型。

## 第一百五十四批验证结果

- Account Transaction API 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3212 errors / 617 files` 收紧为 `3197 errors / 616 files`，净减少 `15 errors / 1 file`。
- Account API 边界、手工成交同步与券商成交导入集成回归共 `51 passed`；覆盖跨组合无持仓写入、资产错配、非有限金额、账本不可改写、资金流水创建/删除、文件类型/大小与行数上限。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十五批

- 按“外部网络抓取影响面 × 政策配置与凭据边界”收口 Policy RSS API。
- RSS source 配置、抓取日志、政策关键词 CRUD、单源触发和全量抓取统一要求 staff；普通登录用户不能修改外部 URL/代理、读取抓取诊断或触发网络任务。
- RSSHub custom access key 改为 write-only，创建和详情响应均不再回显密钥；已有 proxy password 继续保持 write-only。
- 手动抓取不再记录可能含认证信息的 Celery broker URL，日志只记录 eager 模式与无敏感信息的任务 ID。
- 同步抓取、Celery 调度和顶层触发异常不再把数据库、网络、broker 或运行配置原文返回客户端，详细堆栈仅保留在服务端日志。
- 单源不存在继续保持 404，不再被宽泛异常捕获改写成 500。
- 任务入队后监控登记失败不再把已成功投递的任务伪报为调度失败，避免调用方重试产生重复抓取。
- Fetch-all source ID 严格要求正整数；空值仍明确表示抓取全部启用源。
- Generic ViewSet、Request/Response、serializer class、对象查询与任务 ID 补齐精确类型。

## 第一百五十五批验证结果

- Policy RSS API 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3197 errors / 616 files` 收紧为 `3174 errors / 615 files`，净减少 `23 errors / 1 file`。
- Policy 单元、serializer、RSS 抓取用例与 API 权限/调度回归共 `131 passed`；覆盖 staff 门禁、密钥不回显、404 保真、同步/异步错误脱敏与任务追踪。
- Django system check、架构检查、改动文件 Ruff、Black、diff check 与隔离 staged tree 的全仓 mypy debt ceiling 通过。

## 第一百五十六批

- 按“实盘订单与对账副作用影响面 × 异步任务重试安全”收口 Broker Execution Application 边界。
- 维护任务、对账任务、Agent 心跳和成交事件上报统一通过失败安全的告警转发器接入 Task Monitor；畸形告警、监控写入失败或意外异常只记录失败计数，不再反向抛错触发已完成业务写入的重试。
- 告警转发严格验证 level、task name、title、message、metadata 和 task ID 结构，调用结果同时返回成功告警 ID 与失败数量，避免监控降级被静默掩盖。
- 对账目标在生成任何对账记录前验证 user/account 为正整数并拒绝重复账户，防止畸形 composition 数据生成错误归属的资金、持仓或自动停单证据。
- 订单、对账和审计查询统一限制 limit 为 1..500；账户 ID 必须为正整数，状态过滤最多 32 字符并去除首尾空白。
- 订单详情在访问仓储前把 UUID 路由值或字符串规范为 canonical UUID；畸形标识明确返回验证错误，不再向 ORM 边界透传。
- Celery 任务改用共享 typed task adapter，Query Service 显式依赖 Repository Protocol，并保留注入的 falsy repository fake，清除动态装饰器和构造参数债务。

## 第一百五十六批验证结果

- Broker Execution tasks 与 Query Service 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3174 errors / 615 files` 收紧为 `3171 errors / 613 files`，净减少 `3 errors / 2 files`。
- Broker Execution 应用边界、Agent 安全、API 权限和风险对账回归共 `68 passed`；覆盖监控异常隔离、畸形告警、非法对账目标、查询上限、过滤规范化与 UUID 边界。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和隔离 staged tree 的全仓 mypy debt ceiling。

## 第一百五十七批

- 按“投资信号写入影响面 × 证伪表达式正确性”收口 Signal serializers 与 API 错误边界。
- 证伪逻辑清洗在移除标签和控制字符后恢复真实 `<`/`>` 比较运算符，`PMI < 50` 不再以 `PMI &lt; 50` 进入解析器并产生错误规则。
- 创建、更新和准入检查的资产代码统一去空白、转大写并限制为安全的 1..20 字符标识；资产类别必须来自运行时 eligibility registry，方向与目标 Regime 使用 Domain 真源选择。
- 信号逻辑限制为 5..5000 字符，证伪逻辑限制为 5..2000 字符；创建与更新继续要求量化证伪关键字，超长或清洗后过短文本不能进入 parser 或数据库。
- 创建、更新、准入与列表 serializer 拒绝未知字段；调用方不能通过被静默忽略的 status、user ID 或拼写错误参数误判写入结果。
- 准入请求必须提供资产代码，signal ID 必须为正整数，证伪阈值拒绝 NaN 与正负无穷；列表状态、方向、搜索长度和 limit 使用严格边界。
- serializer validation error 恢复 DRF 标准 400 流程，不再被宽泛异常捕获改写为 500；验证、准入和统计的意外异常仅写服务端日志，响应不再泄露数据库或运行时原文。
- Serializer generic、schema decorator、动态读取对象、validated payload 和 API many serializer 边界补齐精确类型。

## 第一百五十七批验证结果

- Signal serializers 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3171 errors / 613 files` 收紧为 `3155 errors / 612 files`，净减少 `16 errors / 1 file`。
- Signal serializer、API 边界、页面契约与查询服务回归共 `49 passed`；覆盖比较运算符保真、未知字段、动态资产类别、方向/Regime、文本上限、非有限阈值、400 保真与内部错误脱敏。
- 改动文件 Ruff、Black、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和隔离 staged tree 的全仓 mypy debt ceiling。

## 第一百五十八批

- 按“证伪判断正确性 × 政策重评状态完整性”收口 Signal Domain parser、invalidation rules 与 Application use cases。
- 证伪 parser 按关键字长度优先识别运算符，`<=`/`>=`、`低于等于`/`高于等于` 不再被较短的 `<`/`>`、`低于`/`高于` 抢先解释。
- 旧证伪用例改为复用结构化 parser 与 Domain evaluator，并把请求指标别名映射到 canonical indicator code；不再拿字典第一个数值评估另一个指标的条件。
- Invalidation threshold 和实际观测值拒绝布尔、NaN 与正负无穷，非有限数据不能触发证伪；无法解析或缺失规则明确返回未评估原因。
- Signal 准入对未知 Regime、越界政策档位和非法置信度失败关闭，避免缺失或畸形宏观上下文被当作中性环境放行。
- Policy 重评严格验证 policy level、current regime、confidence 与持久化 signal ID，移除用目标 Regime 冒充当前 Regime 的回退。
- InvalidationCheckService 继续独占 `INVALIDATED` 状态写入；重评不再随后覆盖成 `REJECTED`，并在响应中分别报告 rejected 与 invalidated 数量和 ID。
- 拒绝状态仓储写入失败、证伪检查异常和无持久化 ID 均向上失败，不再记录数量后伪报成功；重试可据此继续收口。
- Repository、invalidation checker Protocol、DTO 容器、列表和 Domain parser 返回值补齐精确类型，并同步消除 Policy gateway 与 Signal query service 的下游调用债务。

## 第一百五十八批验证结果

- Signal use cases、parser 与 rules 增量 mypy 清零，并同步减少 Policy gateway 与 Signal query service 下游债务；隔离并行工作区改动后，全仓基线从 `3155 errors / 612 files` 收紧为 `3139 errors / 608 files`，净减少 `16 errors / 4 files`。
- Signal Application、Domain、完整工作流与 Policy→Signal 重评回归共 `110 passed`；覆盖长运算符、具名指标、非有限值、无效上下文、状态不覆盖、仓储失败与检查异常传播。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和隔离 staged tree 的全仓 mypy debt ceiling。

## 第一百五十九批

- 按“异步证伪状态变更影响面 × 任务成功真实性”收口 Signal Celery tasks 与每日通知边界。
- 批量证伪任务在发布成功前验证 checked/invalidated/rejected 为非负整数、ID 列表合法、数量与 ID 一致且状态变化数不超过检查数；畸形结果不再因日志索引或宽松返回伪装成成功。
- 单信号证伪在访问仓储前要求正整数 signal ID；数据重试耗尽后的任务结果使用稳定通用错误，不再把数据库或数据源异常原文写入 Celery result backend。
- 旧证伪清理窗口限制为 1..3650 天，布尔、零负值和超大跨度不能进入仓储查询。
- 每日摘要删除无效的 pending 计数查询，并显式返回 notification_sent；存在收件人但所有通知失败时任务真实失败，不再仅记录 warning 后返回成功摘要。
- 邮件中的资产代码、逻辑描述和证伪原因统一限制长度并 HTML 转义，遗留数据库中的标签不能进入 HTML 邮件内容。
- 通知收件人支持单字符串或 iterable 配置，使用 Django email validator、统一小写去重并限制最多 100 个；字符串不再被按字符展开。
- Celery tasks 改用共享 typed task adapter，BoundTask、summary TypedDict、动态详情与 helper 容器补齐精确类型。

## 第一百五十九批验证结果

- Signal tasks 增量 mypy 清零；隔离并行工作区改动后，全仓基线从 `3139 errors / 608 files` 收紧为 `3129 errors / 607 files`，净减少 `10 errors / 1 file`。
- Signal task、通知和真实 ORM 每日摘要回归共 `69 passed`；覆盖结果不一致、非法 ID/天数、通知失败、HTML 转义、单字符串收件人和原有证伪任务契约。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和隔离 staged tree 的全仓 mypy debt ceiling。

## 第一百六十批

- 按“买入资金真实性 × 最低佣金配置唯一真源”补强 Account 与 Simulated Trading 交易费用边界。
- 模拟交易买入继续从按资产类型启用的数据库 `FeeConfig` 读取最低佣金，并使用同一份完整费用结果执行资金校验和实际扣款；缺少生效配置时失败关闭。
- Account `TradingCostConfig` Domain 实体及组合费率、市场费率两类 ORM 模型取消最低佣金运行时默认值；新建配置必须显式提供，不再把 `5.0` 当作代码规则。
- 账户设置页面把最低佣金改为必填；HTTP 输入和 Application 保存服务均不再为空值补 `5.0`，缺失输入不会覆盖已有配置。
- 交易成本估算移除 Repository 中整套硬编码默认费率；找不到对应市场/资产类别的启用配置时明确拒绝估算，避免用隐式 5 元产生可执行错觉。
- 组合费率与市场/资产类别费率均注册到类型安全的 Django Admin，运维人员可显式维护运行时配置，不需要通过代码常量恢复功能。
- 新增迁移 `0033_require_explicit_minimum_commission`：保留已有数据库费率值，只收紧新建契约；同时在历史 shared 迁移删除旧表后按当前显式字段契约恢复 `transaction_cost_config` 表，并对已有表安全跳过。
- 新增非 5 元模拟买入资金边界、Domain/ORM 无默认值、页面缺失最低佣金不写入、成本估算缺配置拒绝等回归。

## 第一百六十批验证结果

- Account 相关改动文件增量 mypy 清零，并清除两个文件的遗留 `unused-ignore`；全仓基线从 `3129 errors / 607 files` 收紧为 `3119 errors / 605 files`，净减少 `10 errors / 2 files`。
- Account 成本估算、费率 Domain、账户辅助服务、组合费率 API/页面、Admin 注册和模拟交易订单约束回归共 `90 passed`；新建测试数据库完整迁移通过。
- Django system check、迁移漂移检查、架构 delta、改动文件 Ruff、Black 与全仓 mypy debt ceiling 通过。

## 第一百六十一批

- 按“Signal 跨入口查询影响面 × 仓储边界一致性”收口 Signal Query Service。
- 管理页、API 和跨 App 调用共享的资产代码、状态、方向、Regime、搜索词、ID、limit、priority 与时间跨度统一在访问仓储前规范化和限界；布尔、非正 ID、超长文本和超大查询不再进入 ORM。
- 创建与更新统一验证资产类别、方向、目标 Regime、审批标志、有限阈值、证伪规则结构和文本长度；空更新明确拒绝，不再产生无意义写入。
- 持久化 Signal 的 ID、资产代码、状态、方向、Regime、置信度和证伪字段在返回调用方前再次校验，畸形历史行失败关闭。
- 未知当前 Regime 不再给出推荐或中性资产，统一返回 hostile；统计结果拒绝布尔、负数和非整数计数。
- 执行标记、批量证伪 ID 和 active-by-asset 查询统一使用正整数 canonical ID、去重与上限；批量 ID 最多 500 个。
- 同步规范化上一批 Signal tasks 的 CRLF Git blob，消除提交级 trailing-whitespace 噪声，不改变运行逻辑。

## 第一百六十一批验证结果

- Signal Query Service 增量 mypy 清零；全仓基线从 `3119 errors / 605 files` 收紧为 `3111 errors / 604 files`，净减少 `8 errors / 1 file`。
- Signal 单元与 API 边界回归共 `105 passed`；覆盖非法过滤、无效持久化 ID、空更新、查询上限、批量 ID、未知 Regime、非有限阈值和畸形统计/持久化记录。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十二批

- 按“政策影响进入投资信号的决策影响面 × 动态 JSON 安全”收口 Policy Influence Service。
- 政策影响返回值改为明确的 `TypedDict` 契约，黑白名单标志、受影响政策、风险调整和建议不再被推断为不安全的混合容器。
- `structured_data` 只在真实 JSON object 时读取；字符串、列表、空值等遗留畸形数据按空对象处理，不再因调用 `.get()` 中断整条信号决策链。
- 板块影响列表只接受非空字符串数组；字符串或其他动态结构不能被按字符迭代并产生伪板块命中。
- Policy Influence Service 的构造、返回值和中间容器补齐精确类型。

## 第一百六十二批验证结果

- Policy Influence Service 增量 mypy 清零；全仓基线从 `3111 errors / 604 files` 收紧为 `3101 errors / 603 files`，净减少 `10 errors / 1 file`。
- Signal 单元与 API 边界回归共 `106 passed`；覆盖黑白名单、板块/舆情影响、畸形结构化数据及既有证伪与查询契约。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十三批

- 按“预测账本不可变证据影响面 × 发布/评估/结果跨层契约”收口 Signal Forecast Ledger。
- Forecast Gateway 的评估与最终结果方法改为精确关键字协议，composition root 不再依赖无法满足的泛型 `**kwargs` 契约。
- 发布入口严格拒绝未知/缺失字段，统一规范 entry ID、资产代码、方向、signal ID、版本标识、来源和 Regime；布尔概率、NaN/无穷、越界概率、naive 时间和反向 horizon 在写账前拒绝。
- 评估入口限制最多 1000 个正整数数据版本和 500 条条件；重复/布尔/非正版本、非布尔 triggered、超长缺失原因和超过 64 KiB 的组合条件证据不能进入 append-only ledger。
- 最终结果拒绝 NaN/无穷收益与 neutral band，限制 evidence 为 JSON object 且不超过 64 KiB；未知 outcome type 和非法 entry ID 在访问仓储前失败。
- Infrastructure 在锁定 ledger entry 后校验 `checked_at/finalized_at` 不早于发布时间，关闭发布前评估或结算的时间顺序旁路。
- Forecast API 复用严格字段 serializer，补齐 Request/Response 类型；signal ID、列表上限与缺失原因在 Interface 层提前限界。

## 第一百六十三批验证结果

- Forecast composition 与 API view 增量 mypy 清零；全仓基线从 `3101 errors / 603 files` 收紧为 `3094 errors / 601 files`，净减少 `7 errors / 2 files`。
- Signal、Forecast Ledger component、Forecast API 与研究完整性回归共 `134 passed`；覆盖未知字段、非有限数值、重复版本、畸形条件、超大 JSON 和发布前事件。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十四批

- 按“Signal 共同持久化边界 × direct ORM 写入旁路”收口 InvestmentSignalModel。
- InvestmentSignalModel 的所有 `save()` 在落库前执行完整字段和业务校验；`objects.create()`、Admin、任务或仓储直接写入不再绕过方向、状态、长度、数值和证伪规则约束。
- 新结构化证伪规则统一复用 Domain `InvalidationRule.from_dict()`；布尔、NaN/无穷阈值、空条件、未知 indicator type/operator/logic、非法 duration 和 compare target 在 ORM 边界拒绝。
- 旧证伪格式继续保留兼容校验；新格式优先且不再由 Infrastructure 维护一套更宽松的重复规则。
- 证伪阈值、回测分数和平均收益必须有限；回测分数限制 0..100、回测次数不得为负数。
- 持久化遗留行若包含损坏的新证伪 JSON，转换 Domain 时明确失败关闭，不再静默丢弃规则并把有证伪条件的信号当作无规则信号。
- Domain → ORM 映射把可空描述与拒绝理由显式规范为空字符串；Unified Signal 的字符串方法补齐类型，执行标记只更新必要字段。

## 第一百六十四批验证结果

- Signal 核心 ORM models 增量 mypy 清零；全仓基线从 `3094 errors / 601 files` 收紧为 `3085 errors / 600 files`，净减少 `9 errors / 1 file`。
- Signal 单元、核心 model、repository、task、query、API 与 forecast 回归共 `143 passed`；覆盖 direct ORM 非法规则/状态/数值、Domain round-trip 和损坏持久化 JSON。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十五批

- 按“Signal 全局准入配置影响面 × 启动初始化真实性”收口 eligibility matrix provider。
- 修复初始化调用不存在的 `signal_rules.set_eligibility_matrix_provider` 且被 `AppConfig.ready()` 静默吞掉的问题；provider 现在注册到实际拥有矩阵真源的 Regime Domain 模块。
- AppConfig 启动只注册惰性数据库 provider，不访问尚未迁移的表，因此移除宽泛异常吞噬；初始化编程错误不再静默导致数据库配置永久失效。
- 数据库 loader 明确验证 model 可用性、资产类别、四种 Regime、Eligibility 枚举和重复组合；畸形行使整次 provider 加载失败并由 Domain 回退完整默认矩阵，不生成部分错误矩阵。
- 无任何 active 配置时 loader 明确失败，Domain 使用完整默认矩阵；空数据库不再返回空矩阵并让所有资产类别变成未知。
- `refresh_domain_config` 移除不存在于所有 Django cache backend 的 `delete_pattern` 调用；当前 eligibility provider 无该缓存键，刷新只需重新注册惰性 provider。

## 第一百六十五批验证结果

- Signal config init 与 AppConfig 增量 mypy 清零；全仓基线从 `3085 errors / 600 files` 收紧为 `3078 errors / 598 files`，净减少 `7 errors / 2 files`。
- Signal 配置初始化专用回归 `6 passed`，完整 Signal 单元、model、repository、task、API 与 forecast 回归共 `149 passed`；覆盖有效注入、畸形行、空库回退和跨 cache backend 刷新。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十六批

- 按“模拟交易费用真源 × 默认费率原子性”收口 Simulated Trading ORM models。
- FeeConfigModel 在持久化前验证所有佣金、印花税、过户费和滑点费率为 0..1 的有限数值，最低佣金与最低过户费为非负有限数值；布尔、NaN、无穷和负数不能进入运行时费用配置。
- direct ORM 写入在 Django FloatField 类型转换前先验证原始 Python 类型，关闭 `True` 被静默转换为 `1.0` 的旁路。
- 默认费率切换改为先完整验证新配置，再在同一事务中取消旧默认并保存新默认；新配置验证失败不再留下没有默认费率的状态。
- 数据库增加按 `asset_type` 的条件唯一约束，QuerySet.update、bulk 或并发写入不能绕过“每类最多一个默认费率”；迁移先按 active、更新时间和主键确定性收敛历史重复默认项。
- Rebalance Proposal、通知历史、账本迁移及账户/持仓/成交等 ORM helper 补齐精确返回类型和 JSON 容器类型。
- 修复遗留集成测试夹具仍省略最低佣金的问题；测试配置现在显式声明 `min_commission`，不再依赖已移除的 5 元默认值。

## 第一百六十六批验证结果

- Simulated Trading ORM models 增量 mypy 清零；全仓基线从 `3078 errors / 598 files` 收紧为 `3065 errors / 597 files`，净减少 `13 errors / 1 file`。
- 模拟交易 Domain、费用、买卖订单、仓位、净值、任务和集成回归共 `220 passed`；覆盖非法费率、失败替换保留旧默认、原子默认切换和数据库绕过约束。
- 迁移漂移检查通过；改动文件 Ruff、Black 与增量 mypy 通过，提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十七批

- 按“账户压力测试结果可信度 × 外部行情动态数据边界”收口 Historical Stress Testing Application。
- 压力测试持仓输入在计算前收窄为明确的 `TypedDict`：资产代码必须为非空且唯一，权重必须为正有限数；重复标的、布尔、NaN、无穷和非正权重不再进入收益聚合。
- 历史行情的交易日与涨跌幅在第三方 DataFrame 边界逐项校验；NaN、无穷、布尔和低于 `-100%` 的不可能收益不再污染净值、波动率与 VaR。
- VaR 置信度必须为 0 到 1 之间的有限数，收益序列必须全部有限；最大回撤拒绝负数或非有限净值曲线，避免错误风险指标被当作有效结果。
- Position Repository 改为通过 Application provider factory 和精确 Protocol 注入，不再在用例构造器中直接实例化具体仓储。
- 情景与结果 DTO 改为不可变 dataclass；回撤 tuple、日期集合、动态行情映射和持仓容器补齐精确类型。

## 第一百六十七批验证结果

- Account Historical Stress Testing 增量 mypy 清零；全仓基线从 `3065 errors / 597 files` 收紧为 `3060 errors / 596 files`，净减少 `5 errors / 1 file`。
- Account 单元回归共 `86 passed`；覆盖非法置信度、非有限收益/净值、重复资产、非法权重、无行情与既有历史情景聚合。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十八批

- 按“统一价格真实性 × 下单与估值公共上游影响面”收口 Data Center Unified Price Service 与 Simulated Trading Price Provider。
- 实时价、历史收盘价、最近收盘价和基金净值统一要求为正有限数；零、负数、布尔、NaN 与无穷不能进入 `PriceLookupResult` 或下游订单、净值和资金计算。
- 实时来源返回非法价格时继续尝试有效最近收盘价；所有来源均非法时返回 unavailable，`require_*` 入口抛出标准 `PRICE_UNAVAILABLE`，不再把畸形数值伪装成可执行价格。
- 价格结果要求非空 requested/normalized code、可审计数据来源、合法日期和受控 freshness；空来源记录不能进入业务模块。
- Data Center 的 `PriceBar.close`、`QuoteSnapshot.current_price` 与 `FundNavFact.nav` Domain 实体同步要求正有限数，阻断新畸形事实进入标准化存储。
- AKShare 基金净值 fallback 同时校验价格和日期；非法日期或数值按无可用数据处理，不再在转换后产生不受控异常或错误结果。
- Unified Price Service 通过 Domain Repository Protocol 与 composition factory 组装仓储；价格、基金净值 payload、repository helper 返回值和模拟盘可空日期补齐精确类型。

## 第一百六十八批验证结果

- Unified Price Service 与 Simulated Trading Price Provider 增量 mypy 清零；全仓基线从 `3060 errors / 596 files` 收紧为 `3048 errors / 594 files`，净减少 `12 errors / 2 files`。
- Data Center 与 Simulated Trading 单元回归共 `289 passed`；覆盖无效实时价回退、无来源价格拒绝、Domain 价格实体约束、标准错误和既有行情/订单路径。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百六十九批

- 按“Data Center 价格事实持久化旁路 × 公共模型契约影响面”收口 Data Center ORM models。
- Price Bar、Quote Snapshot 与 Fund NAV 的 direct ORM 保存会先验证新增价格约束；`objects.create()` 不能写入零/负价格、空资产代码或空来源。
- 三类价格事实增加数据库 CheckConstraint；`QuerySet.update`、bulk 或并发写入不能绕过正价格、非空代码和非空来源约束。
- 新迁移 `0040_enforce_executable_price_facts` 只增加约束，不自动删除或改写历史事实；若已有脏数据，迁移明确失败并要求先审计处置，避免静默破坏行情证据。
- 保存钩子只执行约束验证，不对现有 float 输入执行 DecimalField 小数位校验；保持既有同步入口由数据库 DecimalField 量化的兼容行为。
- Provider、全局数据源配置、覆盖范围、Publisher 与 Market Thermometer 模型的 `to_domain()` 补齐精确返回类型，singleton `save()` 补齐 Django 边界参数类型。
- Market Thermometer 持久化 JSON 的数值、布尔和非负天数显式收窄；字符串 `"false"` 不再被 Python truthiness 转为 `True`，NaN/无穷和畸形整数明确失败。

## 第一百六十九批验证结果

- Data Center ORM models 增量 mypy 清零，并连带清除 Provider State 与 Market Thermometer Repository 下游债务；全仓基线从 `3048 errors / 594 files` 收紧为 `2998 errors / 591 files`，净减少 `50 errors / 3 files`。
- Data Center 单元、component、API 与统一价格服务回归共 `340 passed`；覆盖 direct ORM 拒绝、数据库 update 绕过、严格 JSON 布尔和既有同步/查询路径。
- 迁移漂移检查、Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 仍被本批未修改的 `broker_execution/infrastructure/repositories.py` 大文件增长和 `strategy/infrastructure/repositories.py` 缺少大文件基线两项阻断，留待对应模块拆分/治理批次处理。

## 第一百七十批

- 按“策略配置跨账户隔离 × 执行入口结果真实性”收口 Strategy aggregate API。
- Script Config 查询新增 owner/staff access facade 与 Repository 契约；普通用户的列表、详情、更新和删除不再暴露其他账户的策略脚本。
- Script Config 与 AI Config 的创建、更新统一验证目标 strategy 的访问权；即使请求直接提交其他账户 strategy ID，也不能建立或改绑跨账户配置。
- 策略执行日志分页改用严格 Serializer：offset 必须非负，limit 限制 1..200，未知参数、非整数和超限请求返回 400，不再触发 500 或无界查询。
- 激活/停用写入若 Application 返回未更新，不再回退旧对象并伪报成功，统一返回 404。
- 缺少 Account Profile 的策略创建与“我的策略”入口明确返回权限错误，不再访问匿名/缺失属性。
- DRF action 与 schema decorator 通过局部类型保持 wrapper 暴露，ViewSet、Request、Response、Serializer 与 owner access context 补齐精确类型。

## 第一百七十批验证结果

- Strategy aggregate API 增量 mypy 清零；全仓基线从 `2998 errors / 591 files` 收紧为 `2979 errors / 590 files`，净减少 `19 errors / 1 file`。
- Strategy API、结构和绑定一致性回归共 `45 passed`；覆盖脚本配置 owner 隔离、Script/AI 跨账户写入、分页限界、激活失败真实性和既有执行/读模型契约。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百七十一批

- 按“策略真实执行开关 × SDK 结果真实性”收口 Strategy SDK Contract Actions 与公共 Application facade。
- `execute_strategy_for_assignments` 在加载 assignment 和调用 executor 前验证 strategy ID、可选 portfolio ID 与数据库 active 状态；停用或不存在的策略不能再通过 SDK 执行动作运行。
- 每个执行器结果必须与请求的 strategy/portfolio 一致，并要求非负耗时、timezone-aware 执行时间、真实布尔成功标志和列表型 signals；错配或畸形结果不再汇总成成功响应。
- Signal 与 Performance 读取在展开历史 JSON 前验证 signals 为对象列表；字符串、混合列表或其他损坏结构返回标准数据校验错误，不再被按字符/键计数或触发不受控异常。
- Performance 拒绝布尔或负执行耗时，避免生成负平均时长；Position 与 Trade 读模型要求每项为对象，动态 provider 不能向 SDK 泄漏非结构化值。
- SDK mixin 使用最小 ViewSet Protocol 与类型保持 action wrapper，Request、Response、pk 和 owner-scoped `get_object()` 补齐精确类型。

## 第一百七十一批验证结果

- Strategy SDK Contract Actions 增量 mypy 清零；全仓基线从 `2979 errors / 590 files` 收紧为 `2969 errors / 589 files`，净减少 `10 errors / 1 file`。
- Strategy SDK Application、API、结构与绑定一致性回归共 `52 passed`；覆盖停用策略、执行结果 ID 错配、负耗时、损坏 signal JSON 和既有执行/读模型契约。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百七十二批

- 按“策略规则可变权限 × 执行日志敏感信息隔离”收口 Strategy Rule 与 Execution Log API。
- RuleCondition 列表、详情、筛选、更新、删除和启停统一按 strategy owner 隔离；普通用户不能再查看或修改其他账户的策略规则。
- PositionManagementRule 与 RuleCondition 的创建、更新统一验证请求中 strategy 的访问权；直接提交其他账户 strategy ID 不能建立或改绑规则。
- Rule enable/disable 的 Application 写入返回空值时不再回退旧对象伪报成功，统一返回 404。
- Execution Log 列表与详情要求关联的 strategy 和 portfolio 同时属于调用者；`by_strategy`、`by_portfolio` 使用相同双归属查询，staff/superuser 才能查看全局日志。
- 日志作用域参数改用严格 Serializer，拒绝缺失、非整数、非正 ID 与未知字段；动态字符串不能再直接进入 Repository filter。
- 修复 `signals_count` 把 `list.__len__` 方法对象交给 IntegerField、导致正常日志列表 500 的既有错误；现在显式计算真实列表长度并拒绝畸形持久化 JSON。
- 两类 ViewSet 的 QuerySet、Serializer、Request、Response 和 decorator 补齐精确类型。

## 第一百七十二批验证结果

- Strategy Rule 与 Execution Log API 增量 mypy 清零；全仓基线从 `2969 errors / 589 files` 收紧为 `2954 errors / 587 files`，净减少 `15 errors / 2 files`。
- Strategy SDK、Rule、Execution Log、结构和绑定一致性回归共 `59 passed`；覆盖跨账户规则写入/启停、双归属日志隔离、staff 覆盖、作用域参数与 signals count。
- 改动文件 Ruff、Black 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百七十三批

- 按“策略风控参数持久化旁路 × 执行审计真实性”收口 Strategy ORM 数值不变量。
- Strategy 的单资产上限、总仓位上限与可选止损比例增加数据库范围约束；直接 ORM 更新不能写入 0..100 之外的风险参数。
- AI 策略的 temperature、max tokens 与 confidence threshold 增加组合约束；仓位规则价格精度、规则目标权重与组合覆盖参数同步受数据库保护。
- Strategy Execution Log 的执行耗时必须非负；`QuerySet.update()`、bulk 或并发写入不能绕过 Application 层校验制造负耗时审计记录。
- 新迁移 `0011_enforce_strategy_numeric_invariants` 只增加约束，不自动改写历史策略配置；若存在越界存量数据，迁移会明确失败并要求先审计处置。
- Strategy ORM 模型的字符串表示与动态兼容导出补齐精确返回类型，清除该公共模型文件的全部 mypy 债务。

## 第一百七十三批验证结果

- Strategy ORM models 增量 mypy 清零；全仓基线从 `2954 errors / 587 files` 收紧为 `2945 errors / 586 files`，净减少 `9 errors / 1 file`。
- Strategy unit、component、API 与 integration 回归共 `88 passed`；覆盖 direct ORM 越界更新拒绝、仓储生命周期、策略规则与执行日志既有路径。
- 迁移漂移检查、改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百七十四批

- 按“Strategy 动态入口边界 × 模块债务完整收口”清理 Strategy 剩余启动注册、兼容导出、API 根视图和初始化命令。
- Prompt Gateway 返回三个精确 Domain Provider Protocol，不再由未标注方法向 Prompt 上下文注册表传播动态类型。
- Django App ready hook、兼容 serializer/model 动态导出和 API Root Request/Response 补齐边界类型，不改变既有注册与路由契约。
- 仓位规则初始化模板改用 `TypedDict` 描述变量与表达式必需字段；模板缺字段或字段形状漂移会在增量类型门禁中暴露，不再以裸 dict 静默进入 ORM payload。
- Management Command parser、可变参数与返回值补齐 Django 边界类型；`Any` 只保留在命令行/ORM 动态选项边界。

## 第一百七十四批验证结果

- Strategy 剩余 6 个生产文件增量 mypy 清零；全仓基线从 `2945 errors / 586 files` 收紧为 `2937 errors / 580 files`，净减少 `8 errors / 6 files`，Strategy 模块当前已无登记 mypy 债务。
- Financial Configuration Command、Strategy API 与结构回归共 `37 passed`；覆盖仓位规则 dry-run/create/skip/force、API 权限边界和入口归属。
- 改动文件 Ruff 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百七十五批

- 按“统一账本迁移作用域 × 资金历史数据影响面”收口 `migrate_account_ledger`。
- 修复 `user_id=0`、负数、布尔或畸形值因 truthiness 判断退化为全用户迁移的高风险漏洞；非法 scope 现在在任何查询和写入前抛出 `CommandError`。
- 三阶段 Portfolio、Position、Transaction 查询统一使用显式 `is not None` 过滤，指定用户迁移不会因假值分支扩大作用域。
- Migration Stats 使用 `TypedDict` 固定计数器与告警结构；Command parser、动态 options、各迁移阶段和摘要输出补齐边界类型。
- Capital Flow 汇总改用直接导入的 `Sum`，去除运行时动态导入；合并持仓进入公共计算函数前显式收窄 Decimal/float 边界。

## 第一百七十五批验证结果

- Account Ledger Migration 增量 mypy 清零；全仓基线从 `2937 errors / 580 files` 收紧为 `2926 errors / 579 files`，净减少 `11 errors / 1 file`。
- Ledger Unification Acceptance 回归共 `11 passed`；新增覆盖 0、负数、布尔和字符串 user scope，保留多组合独立迁移、非整数份额、幂等和统一平仓链路。
- 改动文件 Ruff 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta、diff check 和全仓 mypy debt ceiling。

## 第一百七十六批

- 按“观察员持仓隐私 × 授权对象级访问影响面”收口 Account Observer Grant API。
- 观察员列表只接受 `as_observer=0|1` 与 `status=active|revoked|expired`；歧义值和未知参数返回 400，不再静默退化到 owner 视角或产生不可审计空结果。
- 授权详情、更新、撤销与持仓动作统一使用已验证的正整数用户主键比较，不再依赖动态 User 对象相等判断。
- 无关用户访问授权详情现在稳定返回显式 403，兑现 ViewSet 的对象存在但无权限契约；owner 与 observer 的合法详情访问保持不变。
- 创建和更新钩子要求 serializer 返回真实持久化对象；缺失实例不再继续审计或序列化伪成功响应。
- 审计日志入口、客户端 IP、Request/Response、Serializer、QuerySet 与 DRF action wrapper 补齐精确边界类型。

## 第一百七十六批验证结果

- Account Observer Grant API 增量 mypy 清零；全仓基线从 `2926 errors / 579 files` 收紧为 `2908 errors / 578 files`，净减少 `18 errors / 1 file`。
- Account API、Observer Permission 与 Observer Model 回归共 `89 passed`；新增覆盖歧义 scope 参数和无关用户详情访问，保留 owner/observer、过期、撤销和持仓权限链路。
- 改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百七十七批

- 按“MCP Token 副作用入口 × 外部代理访问影响面”收口 Account MCP Self-Service 与 Admin Governance API。
- 当前用户身份在读取状态、创建 Token 和撤销 Token 前统一收窄为正整数 user ID；缺失或畸形认证主体不能进入 Application 服务。
- Self-Service token revoke 与 Admin 用户详情、Token 创建、批量撤销、单 Token 撤销、能力开关统一拒绝 0 或非正路径 ID，非法主键在任何轮换/撤销副作用前返回 400。
- 新 Token 的 copy-ready Agent Prompt 接受只读 Mapping，并显式收窄 base URL；动态 payload 不能再把非字符串值传播到接入 Prompt。
- 所有 MCP API Request/Response 与辅助函数补齐精确类型，`Any` 不再从 DRF request 或 URL 参数扩散到 Token 治理服务。

## 第一百七十七批验证结果

- Account MCP API 增量 mypy 清零；全仓基线从 `2908 errors / 578 files` 收紧为 `2888 errors / 577 files`，净减少 `20 errors / 1 file`。
- Account API 回归共 `48 passed`；新增覆盖 Self-Service 与五类 Admin MCP 非正路径 ID，保留 Token 创建、Prompt 生成、管理员列表和既有账户 API 契约。
- 改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百七十八批

- 按“资产分类物化树 × 多币种估值真实性”收口 Account Classification、Exchange Rate 与 Portfolio Allocation API。
- Asset Category API 创建节点时由 Repository 统一生成 `level/path`；父节点重命名或移动在事务内级联刷新全部后代物化路径。
- 分类更新拒绝把节点移动到自身或后代下，阻断循环树；Application 返回的结构错误转为明确 400，不再形成 500 或损坏分类层级。
- 修复 Category Allocation Serializer 要求不存在 `currency_code`、导致非空分类配置响应失败的问题；真实持仓分类现在可正常序列化。
- Currency Allocation 缺失 FX rate 时不再把外币金额静默按 1:1 当作基准币金额，改为明确失败，避免组合总值和配置比例被系统性高估或低估。
- 同币种转换也必须验证币种已注册且启用；汇率写入拒绝相同币种对和停用币种，最新汇率路径统一规范化货币代码。
- Portfolio allocation 只接受 `category|currency` 维度和已声明查询参数；分类、汇率 ViewSet 与 DRF 动态边界补齐精确类型。

## 第一百七十八批验证结果

- Account Classification API 与 Classification Repository 增量 mypy 清零；全仓基线从 `2888 errors / 577 files` 收紧为 `2855 errors / 575 files`，净减少 `33 errors / 2 files`。
- Account API 回归共 `54 passed`；覆盖分类树创建、父节点重命名级联、循环拒绝、非空分类序列化、缺失汇率失败、非法币种对和严格配置维度。
- 改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百七十九批

- 按“交易费用配置真实性 × 买入资金公共计算影响面”收口 Account Trading Cost Domain、Serializer 与 Portfolio Repository。
- 佣金率、最低手续费、印花税率和过户费率在 Repository 两条保存路径统一要求为非负有限数；`NaN`、正负无穷、布尔和越界值不能再绕过 Python 比较进入持久化。
- API 保存按 `portfolio_id + actor_user_id` 同时定位所属组合，不再先读取任意组合后比较 owner，避免不存在与他人组合走不同数据访问路径。
- `TradingCostConfig` Domain 实体在构造时校验 portfolio/config ID、active 标志和全部费率范围；内部调用无法用损坏配置参与买入资金或卖出所得计算。
- 买卖费用计算要求成交金额为正有限数且交易所标志为真实布尔；零、负数、NaN、无穷或布尔金额不再产生最低佣金或畸形总费用。
- DRF 费率配置与试算 Serializer 同步拒绝非有限数，确保 API、设置页、Application 和 Domain 多层边界一致。
- Account Portfolio Interface Repository 的查询、授权和动态模型返回值补齐边界类型，并收窄可空持仓数值的输出转换。

## 第一百七十九批验证结果

- Account Portfolio Interface Repository 增量 mypy 清零；全仓基线从 `2855 errors / 575 files` 收紧为 `2840 errors / 574 files`，净减少 `15 errors / 1 file`。
- Trading Cost Domain、API 与 Account Macro Sizing 回归共 `92 passed`；覆盖非有限费率、最低手续费、非法成交金额、归属保护和既有买卖费用计算。
- 改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百八十批

- 按“账户身份字段校验 × 宏观仓位配置唯一真源”收口 Account Profile 与 Macro Sizing API。
- 修复 Profile API 从原始 request payload 读取 email、绕过 Serializer 的问题；email 现在经过正式格式校验，未知字段明确返回 400，不能借 Profile 更新提交未声明权限字段。
- Regime、Pulse、Drawdown 与 Market Temperature tier Domain 值对象新增有限数、范围、区间顺序、布尔和非空 band 不变量。
- Macro Sizing Config 要求所有档位集合非空、warning factor 为 0..1 有限数、version 为正整数、市场温度 band 不重复。
- Macro Sizing Serializer 验证嵌套 tier 的对象结构、数值类型、有限性、factor 范围和 Pulse 区间顺序；Repository 在切换 active 版本前构造完整 Domain 配置复核。
- 持久化模型增加全表最多一个 active Macro Sizing Config 的条件唯一约束；数据迁移保留最新版 active，并将旧 active 版本转为 inactive，消除排序碰巧选中配置的歧义。
- Profile、Macro Sizing、Asset Metadata、Health、User Search 与 Trading Cost ViewSet 的 Request/Response、权限、Serializer 和 action wrapper 补齐精确类型。

## 第一百八十批验证结果

- Account Profile API 增量 mypy 清零；全仓基线从 `2840 errors / 574 files` 收紧为 `2827 errors / 573 files`，净减少 `13 errors / 1 file`。
- Profile、Macro Sizing、Trading Cost 与 Account Macro Domain 回归共 `87 passed`；覆盖无效 email、未知 Profile 字段、非有限/越界档位、倒置 Pulse 区间和第二个 active 配置数据库拒绝。
- 迁移漂移检查、改动文件 Ruff、diff check 与增量 mypy 通过；提交前继续执行 Django system check、架构 delta 和全仓 mypy debt ceiling。

## 第一百八十一批

- 按“长期访问凭证泄露影响面 × MCP/SDK 认证失败关闭”收口 Account Token Authentication。
- 新建访问 Token 只在创建响应和受控密文中保留原始值；数据库检索列改存 SHA-256 指纹，认证 Repository 对调用方提交的原始 Token 做同算法检索，数据库泄露不再直接暴露可用凭证。
- 增加数据迁移，将历史明文 Token 检索列原位转换为指纹；现有加密副本继续支持系统明确允许时的受控展示。
- 普通 Token 和内部签名认证都要求用户存在启用 MCP 的账户配置；配置缺失、关闭或用户停用时统一拒绝，不再因缺失关联对象失败开放。
- 只读 Token 的 POST 豁免只接受字符串集合/序列形式的显式 action；标量字符串等畸形 metadata 不再利用 Python 包含判断误获写权限。
- Token 缺失 `allows_write` 能力时默认拒绝写操作；内部认证密钥类型异常和非正用户 ID 在用户查询前明确失败。
- Authentication、Token Model 与 Registration Repository 的动态返回、请求和 ORM 边界补齐类型。

## 第一百八十一批验证结果

- Account Token Authentication、Identity Model 与 Registration Repository 增量 mypy 清零；全仓基线从 `2827 errors / 573 files` 收紧为 `2805 errors / 570 files`，净减少 `22 errors / 3 files`。
- Token Authentication、Admin User Management 与 Account API 回归共 `70 passed`；新增覆盖哈希落库、历史明文迁移后原始 Token 认证、缺失账户配置、内部认证禁用和畸形只读 action 声明。
- 另行确认模拟交易最低佣金来自启用的 `FeeConfig` 而非硬编码，资金校验边界回归 `7 passed`，其中使用 `7.5` 元最低佣金验证配置值会进入所需资金。
- 迁移漂移检查、Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 仍被本批未修改的 `broker_execution/infrastructure/repositories.py` 大文件增长和 `strategy/infrastructure/repositories.py` 缺少大文件基线两项阻断，留待对应模块拆分/治理批次处理。

## 第一百八十二批

- 按“持仓隐私对象级权限 × 匿名身份失败关闭”收口 Account Observer Permission。
- 基础权限和对象权限统一把认证主体收窄为非布尔正整数主键；匿名、未持久化或畸形用户不能进入 owner 比较和观察授权查询。
- 对象权限不再依赖动态 User 对象相等判断，改为比较已验证的 `portfolio.user_id`；Position 仍通过所属 Portfolio 执行同一授权边界。
- 缺失 portfolio/owner、布尔或非正 owner ID 的畸形对象统一拒绝；对象权限钩子即使被单独调用，也不依赖上层已经执行基础权限检查。
- 可访问组合辅助查询对匿名或无效用户显式抛出 `NotAuthenticated`，不再把空 ID 传播到 Application 查询边界。
- RBAC、Observer Request/View/Object 与查询返回边界补齐类型。

## 第一百八十二批验证结果

- Account Observer Permission 增量 mypy 清零；全仓基线从 `2805 errors / 570 files` 收紧为 `2800 errors / 569 files`，净减少 `5 errors / 1 file`。
- Observer Grant Component 与 Integration 回归共 `44 passed`；新增覆盖匿名对象权限、畸形资源对象和匿名组合查询拒绝，保留 owner、observer、过期、撤销及只读访问链路。
- Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。

## 第一百八十三批

- 按“数据库全量导出泄露影响面 × 无会话下载链接可重放”收口 Account Database Backup Download。
- 备份下载令牌新增数据库持久化 SHA-256 nonce 指纹、明确到期时间和消费时间；数据库不保存可直接使用的链接 nonce。
- 每次生成新链接都会原子替换当前指纹并清空消费状态，因此新邮件链接自动撤销旧链接；历史无持久化状态的链接升级后失败关闭。
- 下载 Repository 在事务内锁定系统配置行，校验签名、settings ID、接收邮箱、当前指纹、持久化到期时间、启用状态和未消费状态，再原子标记已消费，阻断并发重放。
- 令牌 payload 对正整数配置 ID、非空邮箱、nonce、时间戳和正数 TTL 显式收窄，畸形签名内容不再以动态字典传播。
- SQLite 备份不再关闭 Django 活跃连接后直接读取数据库文件，改用 SQLite online backup API 生成一致性临时快照，并在读取后确定性清理临时文件。
- 备份包 metadata、邮件连接、签名 payload 和加密字节边界补齐精确类型；Application Provider 移除已失效的动态 cast。

## 第一百八十三批验证结果

- Account Backup Service 增量 mypy 清零；全仓基线从 `2800 errors / 569 files` 收紧为 `2795 errors / 568 files`，净减少 `5 errors / 1 file`。
- Database Backup Email 回归共 `7 passed`；新增覆盖下载后重放拒绝、新链接撤销旧链接、持久化到期拒绝，并由同一测试证明 SQLite 备份后数据库连接仍可继续处理请求。
- 迁移漂移、Django system check、架构 delta、diff check、改动文件 Ruff 与全仓 mypy debt ceiling 通过。

## 第一百八十四批

- 按“首次部署配置完整性 × 初始化失败不得伪装成功”收口 Account Cold-Start Bootstrap Command。
- 每个 bootstrap step 新增显式 `optional` 语义；只有开发环境专用的 MCP cold-start seed 可在 `CommandError` 后记录跳过，分类、风控、调度、因子、Prompt、决策参数等必需步骤失败会携带步骤名终止命令。
- 修复 Alpha bootstrap 成功执行后未增加 applied 计数的问题，最终摘要现在与真实副作用数量一致。
- `decision-env` 在命令内部再次限定为 `auto|dev|test|prod`，防止测试、代码调用或未来入口绕过 argparse choices。
- Alpha Top N 要求非布尔正整数；决策行情最大年龄要求正有限数，零、负数、NaN、无穷和布尔不再传播到网络/数据修复子命令。
- 启用 Alpha 时 universe 参数必须是非空字符串并去除首尾空白；决策修复 kwargs 使用显式对象字典，避免字符串资产代码污染数值推断。
- Bootstrap Step、CommandParser、动态 options、子命令 kwargs、动态模型和 readiness 返回边界补齐类型。

## 第一百八十四批验证结果

- Account Cold-Start Bootstrap Command 增量 mypy 清零；全仓基线从 `2795 errors / 568 files` 收紧为 `2782 errors / 567 files`，净减少 `13 errors / 1 file`。
- Initialization Command Edge 与 Scheduler Initialization 回归共 `29 passed`；新增覆盖必需步骤失败中止、可选 MCP seed 跳过、非法环境、Top N 与非有限行情年龄，并保留完整幂等编排。
- Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。

## 第一百八十五批

- 按“全量初始化入口退出真实性 × 多数据库部署影响面”收口 Account `init_all` Command。
- 必需初始化步骤失败仍先进入结构化 summary，但随后抛出 `CommandError` 产生非零退出状态；命令不再继续展示启动服务、访问后台等误导性下一步。
- 可选网络宏观同步仍可失败后记录 skip，不阻断离线初始化；必需/可选语义与下层 cold-start 命令保持一致。
- `--step` 改为解析唯一的完整命令名或短别名；未知、空白、非字符串或歧义选择在任何子命令副作用前拒绝，不再静默跳过全部步骤并返回成功。
- 计划展示和真实执行复用同一个 target command 解析结果，避免 UI 显示范围与实际执行范围漂移。
- 数据库状态检查不再查询 SQLite 专属 `sqlite_master`，改用 Django connection introspection，兼容正式生产 PostgreSQL。
- Initialization Step/Results 使用 TypedDict 固定必需字段和 optional 策略；CommandParser、options、确认、计划、执行、summary 与 next-step 边界补齐类型。

## 第一百八十五批验证结果

- Account `init_all` Command 增量 mypy 清零；全仓基线从 `2782 errors / 567 files` 收紧为 `2760 errors / 566 files`，净减少 `22 errors / 1 file`。
- Initialization Command Edge 回归共 `13 passed`；新增覆盖未知 step 拒绝、必需失败非零退出且不展示下一步，并验证 Django introspection 输出。
- Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。

## 第一百八十六批

- 按“决策建议输入新鲜度 × 主动数据修复副作用范围”收口 Data Center Decision Reliability Repair Command。
- 用户与组合 scope 只接受非布尔正整数；显式用户不存在或已停用时立即失败，不再静默退化为无用户 Alpha skip。
- 默认用户只选择 active superuser；启用 Alpha 修复但系统无有效用户时在构造 Provider/发起网络同步前返回 `CommandError`。
- 目标日期使用 Django 当前时区的 local date；空白、畸形 ISO 日期和未来日期明确拒绝，避免为未来交易日生成伪新鲜数据。
- 行情最大年龄要求正有限数；零、负数、NaN、无穷和布尔不再传播到 quote readiness 判定。
- 资产与宏观指标代码统一去空白、转大写、保持顺序去重，并校验字符、单码长度和最多 200 个唯一代码，阻断畸形或无界外部同步范围。
- scoped quote sync 只捕获 Data Center 声明的可恢复异常；编程错误不再被包装为普通 failed payload 后继续执行。
- Alpha queue task ID 收窄为字符串；Pulse/Alpha refresher、status reader、动态用户、结果 payload、CommandParser 与 options 边界补齐类型。
- Cold-start 的显式 decision repair 调用固定传递 `strict=True`；修复报告仍阻断时部署初始化失败，不再因命令默认非严格模式伪成功。

## 第一百八十六批验证结果

- Decision Reliability Repair Command 增量 mypy 清零；全仓基线从 `2760 errors / 566 files` 收紧为 `2745 errors / 565 files`，净减少 `15 errors / 1 file`。
- Repair Command Component 与 Initialization Command Edge 回归共 `20 passed`；新增覆盖代码规范化/上限、非法 scope ID、失效用户、非有限行情年龄、未来日期和 cold-start strict 传播。
- Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。

## 第一百八十七批

- 按“宏观金融事实真实性 × 多条决策输入传播影响面”收口 Data Center Financial Fetcher 与公共宏观数据校验。
- LPR、SHIBOR、存款准备金率、外汇储备、新增信贷、人民币存贷款、DR007 和公开市场净投放改用显式语义列契约；第三方返回列漂移时失败关闭，不再按位置猜列并静默写入错误序列。
- LPR 与 SHIBOR 对齐当前 AKShare `TRADE_DATE/LPR1Y`、`日期/O/N-定价` 契约；非法日期行转为缺失并跳过，不再中止整批有效数据。
- 存款准备金率改用“生效时间 + 大型金融机构调整后”口径，不再把公布时间和调整前数值发布为当前政策水平。
- `CN_RMB_DEPOSIT` 改为“新增人民币存款总额”流量口径，并明确选取“新增存款-数量”；不再优先取“新增储蓄存款”子项却标记为人民币存款余额。
- 数据迁移同步修正人民币存款目录名称、描述、流量语义与图表策略；历史 AKShare 错口径事实不删除，统一标记为 `error` 并保留原质量和失效原因，等待正确口径重同步，迁移回滚可恢复原质量。
- 所有必需金融数值通过 `safe_float` 收窄为有限数；缺失标记、畸形字符串、NaN 与正负无穷不再回退为零。公共宏观数据校验器进一步拒绝任何 fetcher 遗漏的非有限事实。
- Financial Fetcher 的第三方模块、校验回调、排序回调和返回边界补齐精确类型；仅在 pandas 外部库边界保留定点 `import-untyped` 注释。

## 第一百八十七批验证结果

- Financial Fetcher 与 Macro Source Base 增量 mypy 清零；全仓基线从 `2745 errors / 565 files` 收紧为 `2728 errors / 563 files`，净减少 `17 errors / 2 files`。
- Financial Fetcher、Macro Fetcher Resilience、公共 Adapter、迁移和指标治理回归共 `82 passed`；新增覆盖当前 AKShare 列契约、RRR 生效后值、人民币存款总额、非法日期、schema 漂移、无效数值跳过和历史事实可逆隔离。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 仍被本批未修改的 `broker_execution/infrastructure/repositories.py` 大文件增长和 `strategy/infrastructure/repositories.py` 缺少大文件基线两项阻断，留待对应模块拆分/治理批次处理。

## 第一百八十八批

- 按“增长与融资宏观事实 × Regime/Pulse 公共输入影响面”收口 Data Center Economic Fetcher。
- 工业增加值、社零当月值及同比、GDP 累计值及同比、固定资产投资累计值及派生同比、社会融资增量及派生同比统一改用显式语义列契约；第三方列漂移时失败关闭，不再按位置猜测并误用其他指标列。
- 工业增加值明确读取“同比增长”，社零明确区分“当月”和“同比增长”，GDP 明确区分累计绝对值和同比增长，固定资产投资只使用“自年初累计”，社会融资只使用“社会融资规模增量”。
- 中文月度和季度标签改为完整匹配；非法月份、第五季度、倒置季度区间和带尾随垃圾的标签不再被部分正则接受或默认映射到第四季度。
- 固定资产投资派生同比要求当前和上年同月累计值均为正数；零或负累计基数不再产生失真同比。
- 所有经济指标数值统一通过必需数值解析与公共有限性校验，Fetcher 的第三方模块、校验回调、排序回调、数据点列表与返回边界补齐精确类型。

## 第一百八十八批验证结果

- Economic Fetcher 增量 mypy 清零；全仓基线从 `2728 errors / 563 files` 收紧为 `2717 errors / 562 files`，净减少 `11 errors / 1 file`。
- Macro Fetcher Resilience 回归共 `29 passed`；新增覆盖工业增加值命名列、GDP schema 漂移拒绝、非法季度标签和固定资产投资非正累计值跳过，保留 GDP、社零、社融及派生口径回归。
- Django system check、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百八十九批

- 按“PMI/CPI/PPI/M2 核心 Regime 输入 × 单位治理唯一真源”收口 Data Center Base Fetcher 与公共解析辅助。
- 制造业 PMI、CPI 指数及六类城乡同比/环比、PPI 指数及同比、M2 余额及同比、非制造业 PMI 全部改用显式语义列契约；第三方列漂移时失败关闭，不再按位置猜测。
- CPI 细分路由从列序号映射改为指标代码到正式列名映射；未知 CPI 细分代码明确拒绝，不再返回空列表伪装成无数据。
- 月份解析改为完整匹配并校验 1..12；非法月份行转为缺失后跳过，保留同批有效事实。
- M2 Fetcher 删除硬编码 `/10000` 换算，直接发布 AKShare 原始“亿元”值；新增 `CN_M2 + akshare + 亿元` 单位规则，由统一治理链路按 `100000000` 转换为 canonical 元存储并按万亿元展示。
- 公共必需数值解析改用 `safe_float`，统一拒绝缺失标记、畸形值、NaN 与无穷；source unit 模式必须找到精确启用的单位规则，否则在事实构造前失败关闭。
- Base Fetcher 与公共 helper 的第三方 DataFrame、回调、列表和返回边界补齐精确类型。

## 第一百八十九批验证结果

- Base Fetcher 与 Common Helper 增量 mypy 清零；全仓基线从 `2717 errors / 562 files` 收紧为 `2704 errors / 560 files`，净减少 `13 errors / 2 files`。
- Base Fetcher、Macro Fetcher Resilience、日期和指标治理回归共 `60 passed`；新增覆盖全部核心命名列、六类 CPI 细分、M2 原始亿元值、单位规则、schema 漂移、非法月份和未知 CPI 代码拒绝。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十批

- 按“PMI 领先分项长期空数据 × Pulse/Regime 领先指标影响面”收口 Data Center PMI Subitems Fetcher。
- 修复手工数据路径从不存在的 `apps/data_center/data/pmi_subitems_manual.json` 读取的问题；Fetcher 现在准确定位既有 `apps/macro/data/pmi_subitems_manual.json`，六类 PMI 分项不再永久静默返回空列表。
- 手工文件事实来源改为 `manual_pmi_subitems`，不再错误标记为 `akshare`；指标目录补齐国家统计局、NBS publisher code、official provenance 和 manual-file access channel。
- 数据迁移把历史误标为 akshare 的 PMI 分项事实改为手工来源并补审计 metadata；若 canonical 手工事实已存在，则保留冲突行并标记 `error`，避免唯一键覆盖，迁移回滚可恢复原来源与质量。
- 缺失可选文件仍返回空列表；文件不可读、JSON 损坏、根结构错误、缺失/非数组 data 或非对象记录改为明确 `DataValidationError`，不再把损坏数据伪装成“无数据”。
- reporting period 必须是 ISO 月末日期；布尔、缺失、NaN、无穷及 0..100 外的 PMI 指数跳过；反向日期范围在文件 I/O 前拒绝。
- 六个公开 fetch 方法复用统一字段转换入口，单位由指标治理元数据解析；动态 JSON、回调、记录、列表和返回边界补齐精确类型。

## 第一百九十批验证结果

- PMI Subitems Fetcher 增量 mypy 清零；全仓基线从 `2704 errors / 560 files` 收紧为 `2694 errors / 559 files`，净减少 `10 errors / 1 file`。
- PMI Subitems、provenance migration 与指标治理回归共 `26 passed`；新增直接读取真实默认文件的六分项覆盖，以及损坏 JSON、结构错误、缺失文件、非法月末、越界值、来源修复和冲突隔离回归。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十一批

- 按“高频宏观事实口径 × Pulse/Regime/Risk 多链路传播影响面”收口 Data Center High Frequency Fetcher。
- 中美国债收益率改用当前 AKShare 的显式中文列契约；删除基于 `2Y/5Y/10Y` 子串的模糊列识别，避免运算符优先级和英文同期限列把美国收益率误写为中国收益率。
- 10Y-2Y 期限利差只从同一 DataFrame、同一日期的中国 10Y 与 2Y 基础收益率派生并转换为 BP；数据源为空时直接返回，不再继续访问空对象列。
- 识别并关闭两条错口径发布路径：`macro_china_commodity_price_index` 不是南华商品指数，`fx_spot_quote` 的即期买价也不是人民币中间价；`CN_NHCI` 与 `CN_FX_CENTER` 在取得可信数据源前失败关闭。
- 数据迁移将上述两项的 `governance_sync_supported` 设为 false，并把历史 AKShare 错口径事实标记为 `error`、保留原质量和隔离原因；回滚可恢复先前目录标志与事实质量。
- 同步更正 Regime Phase 0 与滞后改进文档中把 CN_NHCI、CN_FX_CENTER 标为已实现/部分实现的过时结论，明确历史错口径数量不计入有效覆盖。
- Fetcher 的第三方模块、校验回调、排序回调、数据点列表和返回边界补齐精确类型，仅在 pandas 外部库边界保留定点 `import-untyped` 注释。

## 第一百九十一批验证结果

- High Frequency Fetcher 增量 mypy 清零；全仓基线从 `2694 errors / 559 files` 收紧为 `2685 errors / 558 files`，净减少 `9 errors / 1 file`。
- 高频 Fetcher、Regime 观察指标、高频信号规则及语义隔离迁移回归共 `40 passed`；新增覆盖中美国别/期限精确列、同日利差派生、schema 漂移、空数据异常路径、错误商品/汇率端点禁止调用和历史事实隔离。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十二批

- 按“就业/房价/能源事实真实性 × Regime 增长与通胀输入影响面”收口 Data Center Other Fetcher。
- 城镇调查失业率对齐当前 AKShare `date/item/value` 契约，只读取“全国城镇调查失业率”；删除按位置回退到 `item` 列和解析失败默认 0 的逻辑，避免把指标名称文本发布成 0% 失业率。
- 全国失业率要求为 `(0, 100]` 有限百分点；AKShare 官方样例中的 0 缺失占位和其他无效值跳过，历史 AKShare 0 值事实由迁移标记为 `error` 并保留原质量和原因。
- 新建商品住宅价格改用“日期/城市/新建商品住宅价格指数-同比”显式列契约，只选择北京并将目录名称、描述和 geographic metadata 明确为北京单城市序列，不再冒充全国房价。
- 成品油价格改用“调整日期/汽油价格”显式列契约并保持上游元/吨原值；删除运行时硬编码的 1360 升/吨密度假设，目录和单位规则统一为元/吨。
- 数据迁移把历史 AKShare 元/升油价按旧运行时除数可逆还原为元/吨，并记录修复前值、单位和转换依据；迁移回滚可恢复旧目录、单位规则、油价事实和失业率质量。
- Other Fetcher 的第三方模块、回调、DataFrame、数据点列表与返回边界补齐精确类型，仅在 pandas 外部库边界保留定点 `import-untyped` 注释。

## 第一百九十二批验证结果

- Other Fetcher 增量 mypy 清零；全仓基线从 `2685 errors / 558 files` 收紧为 `2678 errors / 557 files`，净减少 `7 errors / 1 file`。
- Other Fetcher、Macro Fetcher Resilience、目录治理命令与语义修复迁移回归共 `37 passed`；新增覆盖正式 AKShare 列契约、全国指标项筛选、0/缺失值拒绝、北京/上海隔离、schema 漂移、油价原始单位和历史事实修复。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十三批

- 按“海关贸易事实 × 增长判断与外需输入影响面”收口 Data Center Trade Fetcher。
- 出口额、出口同比、进口额、进口同比统一使用当前 AKShare 海关数据的“月份/当月出口额-金额/当月出口额-同比增长/当月进口额-金额/当月进口额-同比增长”显式列契约；删除所有列序号回退。
- 月份标签改为完整匹配并校验 1..12；schema 漂移明确失败，单行缺失标记或畸形金额只跳过该行，不再中断同批有效月份。
- 出口和进口金额删除运行时 `/100000` 硬编码换算，按上游原始“千美元”值发布；新增三条 `akshare + 千美元` 单位规则，由统一治理链路按 1000 转换为 canonical 元存储并按亿美元展示。
- 贸易差额不再读取 Jin10 发布日接口并把发布日期误作 reporting period；现在从同一海关 DataFrame、同一统计月份的当月出口额减当月进口额派生，目录补齐 derivation method 和上下游指标。
- 数据迁移将历史 AKShare 贸易差额事实标记为 `error` 并保留原质量和错位原因，等待同月海关口径重同步；单位规则、目录 metadata 和事实质量均支持精确回滚。
- Trade Fetcher 的第三方模块、回调、动态行、数据点列表与返回边界补齐精确类型，仅在 pandas 外部库边界保留定点 `import-untyped` 注释。

## 第一百九十三批验证结果

- Trade Fetcher 增量 mypy 清零；全仓基线从 `2678 errors / 557 files` 收紧为 `2671 errors / 556 files`，净减少 `7 errors / 1 file`。
- Trade Fetcher、Macro Fetcher Resilience、目录治理命令与海关单位迁移回归共 `40 passed`；新增覆盖当前列契约、原始千美元、同月贸易差额、schema 漂移、单行错误隔离、三条单位规则、历史事实隔离和反向迁移。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十四批

- 按“代理指标语义污染 × Regime 中期验证输入影响面”收口 Data Center Weekly Indicator Fetcher。
- 确认并停止四条不具同义性的代理发布：全社会用电量不是发电量、钢铁股票指数不是高炉开工率、BDI 干散货指数不是 CCFI、BCI 海岬型干散货指数不是 SCFI。
- 四个既有 fetch 路由保留接口兼容，但在取得语义一致数据源前统一失败关闭且不调用代理端点；避免下游仅凭指标代码把代理值当成目标事实。
- 指标目录将四项标记为 `unsupported_proxy` 且 `governance_sync_supported=false`；治理初始化真源同步携带该状态，后续运行初始化不会把自动同步重新打开。
- 数据迁移将历史 AKShare 代理事实统一标记为 `error`，保留原质量和隔离原因；目录描述、同步标志、治理状态及事实质量支持精确回滚。
- 全面更正 Regime 滞后改进文档中“已实现/代理可用/有效记录”的过时结论，历史 33/155/156/155 条代理记录不再计入有效覆盖。
- Weekly Fetcher 的第三方模块、回调和返回边界补齐精确类型；移除不再需要的 pandas 外部边界。

## 第一百九十四批验证结果

- Weekly Indicator Fetcher 增量 mypy 清零；全仓基线从 `2671 errors / 556 files` 收紧为 `2665 errors / 555 files`，净减少 `6 errors / 1 file`。
- Weekly Fetcher、Phase 2 Seed、目录治理命令与代理隔离迁移回归共 `17 passed`；新增覆盖四条错误端点零调用、同步持续关闭、历史事实隔离和反向迁移。
- Django system check、迁移漂移检查、架构 delta、diff check、改动文件 Ruff、增量 mypy 与全仓 debt ceiling 通过。
- 完整 governance consistency 的两项既有大文件阻断未发生变化。

## 第一百九十五批

- 按“最低佣金唯一真源 × 买入资金真实性”补齐模拟交易费用配置的外部调用闭环。
- 核心买入链路继续从按资产类型启用的数据库 `FeeConfig.min_commission` 读取最低佣金，并以包含佣金、过户费与滑点的完整费用执行资金校验和实际扣款；非 5 元配置值会直接改变所需现金。
- SDK `create_trading_cost_config`、MCP legacy tool、内部 handler 与 fallback 创建入口删除 `5.0` 默认值，最低佣金改为显式必填参数，避免调用方省略参数时重新注入硬编码。
- `account.create.trading_cost_config` 能力清单将 `min_commission` 纳入 required contract；缺参在预览或写入前以 `missing_required_arguments` 失败关闭。
- SDK 与架构文档同步删除最低佣金 5 元运行时默认口径，明确该值必须来自券商/资产费率配置；历史迁移中的 5 元仅用于保留既有数据库演进记录，不作为当前运行时默认值。

## 第一百九十五批验证结果

- 模拟交易余额边界、Account 费用 Domain/API、SDK client 与 MCP capability 回归共 `87 passed`；覆盖 `7.5` 元最低佣金进入资金校验、SDK 显式透传 `2.5` 元和 MCP 缺参拒绝。
- Django system check、架构 delta、改动文件 Ruff、diff check 与全仓 debt ceiling 通过；全仓生产代码基线保持 `2665 errors / 555 files`，本批不抬高债务。
- SDK 独立严格 mypy 仍被跨模块历史债务阻断，共 `176 errors / 34 files`；本批改动未产生参数顺序、缺参或调用签名相关类型错误，后续按 SDK 专项债务批次治理。

## 第一百九十六批

- 按“事件分发唯一实例 × 风控/决策 handler 启动完整性”收口全局 Event Bus 初始化链路。
- 修复启动器单独创建 Celery/内存总线、而发布用例和 Celery task 继续读取 Domain 第二个全局总线的问题；完整注册并启动的 concrete bus 现在安装为 `apps.events.domain.services.get_event_bus()` 的唯一进程级实例。
- `INSTALLED_APPS` 将 `events` 调整到 `decision_rhythm`、`alpha_trigger` 与 `beta_gate` 之后，修复 Beta Gate 在事件总线初始化完成后才写 registry、两个关键订阅永久缺失的问题。
- 初始化器改为线程安全且幂等；registry 订阅使用稳定 ID 并保留声明优先级，handler 的 follow-up event bus 注入与发布方使用同一实例。总线被测试/运维 reset 后再次初始化会重建完整订阅，不复用已清空的假健康实例。
- Registry、handler 构造或订阅失败不再逐项吞掉；Events、Alpha Trigger 与 Beta Gate 的关键启动链路统一失败关闭，避免 Django 在缺失风控、触发或执行一致性 handler 时继续提供服务。
- `EventBus` 抽象补齐 start/stop 生命周期；全局替换会停止旧实例，reset 会关闭线程池。订阅查询改为不可共享列表容器的浅快照，修复 bus-aware handler 因内部 `RLock` 无法 deepcopy 导致健康查询崩溃的问题。
- 同步更新事件总线集成设计，明确 App 启动顺序、唯一实例与失败关闭契约。

## 第一百九十六批验证结果

- Event Bus Domain、初始化器、异步 task、Alpha/Beta/Decision Rhythm 订阅 wiring、决策执行 handler 与 Events API 回归共 `83 passed`；启动日志确认完整注册 `18 handlers`，并显式覆盖 Beta Gate 订阅存在、全局实例同一性、幂等、reset 重建和构造失败不安装。
- Event Bus、Beta Gate 启动链路及相关 Domain 增量 mypy 清零；全仓基线从 `2665 errors / 555 files` 收紧为 `2626 errors / 549 files`，净减少 `39 errors / 6 files`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第一百九十七批

- 按“异步事件不丢投递 × 健康状态真实性”收口 Events Celery task、health checker、Celery adapter 与受控重放 composition contract。
- 单事件异步发布严格解析 timezone-aware ISO 时间；显式非法或 naive 时间直接失败，不再记录 warning 后改用当前时间，避免事件发生时间被静默篡改。
- Celery 重试在持久化前按 `event_id` 查询：已存在且内容一致的事件继续完成投递，修复 worker 在“已入库、尚未 publish”窗口失败后永久丢投递的问题；同 ID 不同 payload、metadata、类型或显式时间失败关闭。
- 批量发布的 `success` 改为只在零失败时为 true，并校验事件类型、payload、metadata、ID 与时间边界；初始化 event store/bus 失败走 Celery 重试，不再返回假成功。
- Replay 的 since/until 必须含时区且顺序有效，limit 必须大于零；无效 handler 路径和类型属于确定性输入错误，不消耗基础设施重试。
- Events/Snapshot 清理、指标采集和健康任务补齐真实重试契约；非法保留期和批大小直接拒绝，数据库等瞬时故障在达到 max retries 后返回失败证据。
- 健康计算修复空闲总线 `0 failed < 0 processed` 被误判 unhealthy 的问题；现在以实际失败率计算，并要求总线运行、订阅数大于零。无 handler 或缺失决策批准/执行成功/执行失败关键 handler 均为 ERROR，不再降级为 WARNING。
- Celery adapter 从 DomainEvent metadata 读取 correlation/causation ID，修复访问不存在实体属性的运行时错误；受控 Replay Protocol 改为与 concrete store/repository 一致的精确签名。

## 第一百九十七批验证结果

- Event task、health checker、Celery transport、受控 replay、Domain bus、初始化器、决策执行 handler 与 Events API 回归共 `91 passed`；覆盖 naive 时间拒绝、已持久化重试续投、ID 冲突、批量失败状态、清理失败、空闲健康和零订阅不健康。
- Events async/health/adapter/composition 增量 mypy 清零；全仓基线从 `2626 errors / 549 files` 收紧为 `2601 errors / 545 files`，净减少 `25 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第一百九十八批

- 按“Prompt 四层边界 × AI 模板写入入口唯一性”清理 `apps/prompt/infrastructure/__init__.py`。
- 确认该文件是早期遗留的完整 DRF Serializer 影子副本：位于 Infrastructure 层却承载 Interface 职责，创建模板/链时直接实例化 concrete Repository，并与当前正式 Serializer 的名称唯一性、输入上限、provider_ref、更新和 Application facade 契约持续分叉。
- 全仓静态调用审计确认没有生产或测试调用者依赖该影子入口；删除旧 Serializer 实现，将 Infrastructure 包恢复为无 ORM/DRF 导入副作用、无 shortcut export 的 package marker。
- `apps/prompt/interface/serializers.py` 保持唯一 Serializer 真源；新增边界回归禁止 Infrastructure 重新暴露模板/链 Serializer。
- 修复 ChatRequest 既有测试在输入校验收紧后仍构造缺失 content 历史消息的问题；合法夹具改为完整 role/content，并新增缺 content 必须拒绝的安全契约。
- 同步更新 Prompt 架构文档，明确 DRF、Application facade 与 Infrastructure 的职责边界。

## 第一百九十八批验证结果

- Prompt Infrastructure 边界、Interface Serializer、Prompt API edge、Evaluation Gate 与初始化命令一致性回归共 `31 passed`。
- Prompt Infrastructure package 增量 mypy 清零；全仓基线从 `2601 errors / 545 files` 收紧为 `2577 errors / 544 files`，净减少 `24 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第一百九十九批

- 按“Alpha 质量指标真实性 × Qlib 工件可复现性”收口 Qlib artifact/training/evaluation runtime。
- 模型评估只从独立验证区间内按日期和证券代码对齐的真实标签计算横截面 Rank IC；每个横截面至少要求 10 只有效证券。标签缺失、索引无法对齐或样本不足时失败关闭，不再根据预测分数变异系数编造 IC、ICIR 和 Rank IC。
- 删除已弃用且返回虚构指标的 `get_default_metrics` 生产导出，训练运行记录和模型注册表只接收真实评估结果。
- `Alpha158` / `Alpha360` 改为显式支持列表，未知特征集直接拒绝；LightGBM 专属默认参数不再注入 GRU、LSTM 和 MLP，日期范围和独立验证集划分在训练前校验。
- 模型工件改为不可覆盖的原子目录发布；先写同级临时目录，写入模型、配置、真实指标、实际特征/标签 metadata 与数据版本后，最后生成含逐文件 SHA-256 和字节数的 `manifest.json` 并原子改名。路径逃逸和同版本覆盖均失败关闭。
- 删除与实际 Alpha158/Alpha360 不一致的硬编码示例特征和标签；`feature_schema.json` 只发布本次训练配置中真实存在的 feature set、label 和显式 feature columns。

## 第一百九十九批验证结果

- Qlib runtime、Alpha infrastructure edge、task structure 与 training component 回归共 `48 passed`；覆盖真实标签指标、标签缺失失败、工件清单哈希、不可覆盖和实际 schema。
- Qlib artifact/scientific runtime 及其 Application 导出增量 mypy 清零；全仓基线从 `2577 errors / 544 files` 收紧为 `2553 errors / 542 files`，净减少 `24 errors / 2 files`。
- Django system check、迁移漂移检查、架构 delta、改动文件 Ruff、diff check 与增量 mypy 通过。

## 第二百批

- 按“Alpha 监控证据真实性 × Qlib 运维误报影响面”收口 Alpha monitoring tasks。
- 覆盖率删除 CSI300/手动结果固定 300 分母；只从缓存 `scope_metadata.pool_size`、`metrics_snapshot.universe_count/pool_size` 或 AlphaResult metadata 读取可审计分母。缺少分母时返回 unavailable，不发布猜测值；评分数超过股票池规模时标记 invalid。
- 队列积压改为读取 Celery worker 的 reserved 任务，不再把 active 执行中任务当作 backlog；inspect 异常或无 worker 响应时返回 unavailable 且不写入 0，避免监控失联被误报为无积压。
- IC 漂移将最新有效 IC 与其之前最多 20 个有效历史值比较，不再把当前值混入自身历史均值；有效滚动历史不足两点时明确 skipped。
- 清理任务拒绝零、负数和布尔保留期，避免未来 cutoff 大范围删除缓存；旧任务名统一调用 canonical task body。
- Application 通过 repository provider factory 获取仓储，所有任务、结果、日统计和辅助入口补齐精确类型。

## 第二百批验证结果

- Alpha/Qlib runtime contracts 与 Alpha monitoring integration 回归共 `48 passed`；覆盖真实覆盖率分母、IC 历史排除当前值、队列 unavailable 不写假 0、reserved 计数和非法保留期拒绝。
- Alpha monitoring tasks 增量 mypy 清零；全仓基线从 `2553 errors / 542 files` 收紧为 `2535 errors / 541 files`，净减少 `18 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check 与增量 mypy 通过。

## 第二百零一批

- 按“Qlib 训练入口唯一性 × 新模型指标归属真实性”收口 `train_qlib_model` management command 与 canonical task 配置。
- 删除 CLI 内独立的 Qlib 初始化、训练、评估、pickle 保存和 ORM Registry 写入实现；同步执行与异步投递现在都调用 `qlib_train_model` canonical task，统一使用真实标签评估、原子不可变 artifact、manifest 和 repository 写入。
- 删除“新模型真实评估失败后读取另一旧模型缓存 IC/ICIR 并写入新 Registry”的错误回填路径；评估异常现在使训练失败，不再跨模型冒用质量指标。
- canonical task 将本次训练的日期、股票池、特征集和标签组成 effective config，同时传给训练、评估、artifact 和 Registry；修复此前评估使用默认日期/Alpha360、而训练使用另一配置的错位。
- CLI `learning-rate/epochs` 改为模型专属 `model_params`：LightGBM 使用 `learning_rate/num_boost_round`，GRU/LSTM/MLP 使用 `lr/n_epochs`；非正数、非有限数和非法轮数在任务投递前拒绝。
- 股票池、特征集、标签与模型目录省略时交由 Config Center 提供，不再由 CLI 硬编码运行时默认值；历史 `v1` 特征集别名规范化为真实 `alpha360`，未知特征集失败关闭。
- `--force` 不再伪装为可用选项；不可变 artifact 禁止覆盖，显式使用时返回 CommandError。

## 第二百零一批验证结果

- Qlib runtime contracts、training component 与 mock fallback remediation 回归共 `48 passed`；覆盖同步/异步同配置、模型专属参数、v1 规范化、真实评估 effective config 和影子保存器移除。
- Qlib training command 及相关 task/runtime 增量 mypy 清零；全仓基线从 `2535 errors / 541 files` 收紧为 `2517 errors / 540 files`，净减少 `18 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check 与增量 mypy 通过。

## 第二百零二批

- 按“中央 AI Provider 路由 × 凭据轮换与故障接管影响面”收口 `AIClientFactory`。
- 删除 `_ScopedAIClient` 按 provider ID 永久缓存适配器的逻辑；每次请求均使用本次从数据库解析出的最新 Base URL、API Key、默认模型、API mode 与 fallback 设置构建适配器，配置或密钥轮换无需等待进程重启。
- 适配器构建或调用抛出的异常统一转换为安全的标准失败结果并写入使用日志；日志只保留 provider 名称和异常类型，不向调用方或审计记录复制可能含凭据、地址或第三方响应正文的原始异常消息。单个 provider 异常后继续尝试后续个人或系统候选，不再中断整条 failover 链。
- 个人 provider 与系统 provider 统一执行自身日/月预算限制；个人配置达到预算后跳过并进入受用户 fallback quota 约束的系统兜底，不再绕过 provider 级预算。
- 显式传入的非法或不存在用户引用改为失败关闭，不再解析为匿名请求后使用不计用户额度的 system-global provider。
- 补齐中央 factory、scoped client、adapter contract 与 chat completion application protocol 的精确类型；删除未使用的 legacy null client，并让 Prompt、Valuation、Terminal 与 AI Capability 消费端共享同一可检查契约。

## 第二百零二批验证结果

- AI Provider Domain/Adapter/配置/加密/预算/路由/API、Prompt/Valuation API 与 Terminal Agent 回归共 `151 passed`；新增覆盖 provider 抛异常后的接管、异常消息脱敏、缓存 client 下配置和 API Key 轮换即时生效、非法用户 ID 拒绝及个人预算执行。
- AI client factory 与 application chat contract 增量 mypy 清零；类型传播同时消除 AI Capability facade 与 Terminal chat router 的既有未类型调用，全仓基线从 `2517 errors / 540 files` 收紧为 `2497 errors / 539 files`，净减少 `20 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零三批

- 按“AI Provider 管理 scope 隔离 × 配置写入与连接测试影响面”收口 Provider Application use cases。
- 系统管理调用与个人管理调用改为显式的互斥 scope：未传 actor 的管理员链路只能管理 system provider，传入 actor 的个人链路只能管理该用户自己的 user provider；更新、删除、启停、统计、预算和连接测试统一复用同一解析规则。
- 修复管理员 system API 可凭个人 provider ID 修改或删除个人配置、个人 API 可凭 system provider ID 操作系统配置的越权边界；跨 scope 请求在数据库写入、API Key 解密或外部连接前统一按 not found 失败关闭。
- 连接测试不再从 Application use case 导入 concrete Infrastructure adapter，改由 Application repository provider 暴露的 adapter factory 组装，恢复四层依赖边界。
- Provider 管理用例的 actor、owner、动态更新字段及仓储注入边界补齐类型，保持 ORM 动态对象仅停留在 Application/Infrastructure 交界。

## 第二百零三批验证结果

- AI Provider Domain/Adapter/配置/加密/预算/路由/API 回归共 `102 passed`；覆盖管理员/个人双向跨 scope 拒绝、合法系统连接测试和既有 CRUD 契约。
- Provider use cases 增量 mypy 清零；全仓基线从 `2497 errors / 539 files` 收紧为 `2484 errors / 538 files`，净减少 `13 errors / 1 file`。
- 架构 delta 无违规，改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零四批

- 按“AI Provider 配置输入可信度 × 密钥读接口最小披露”收口 Provider Serializer 与写入校验。
- Read Serializer 删除 Interface 层自行读取加密设置、解密 API Key 并输出后四位的重复密钥实现；Application DTO 只发布 `api_key_configured` 布尔状态，API 的兼容 `api_key` 字段仅返回固定 `****`，不再暴露可用于关联凭据的后四位。
- Provider 日/月预算改用有精度和非负约束的 Decimal 输入；HTTP Serializer 与直接 Application UseCase 同时拒绝负数、布尔、NaN、Infinity 和畸形预算，避免绕过 API 后写入不可比较或无限预算值。
- 零预算保持为有效的“禁止消费”限制；预算状态查询不再用 truthiness 把 `0` 错当成未配置，路由与管理视图对零预算的判断保持一致。
- 用户 fallback quota 与批量额度 Serializer 同步增加非负约束；Chat request 的 temperature 限定在 `0..2`，max_tokens 必须大于零。
- `extra_config` 必须是 JSON object，禁止数组、字符串等无法按配置键读取的结构进入运行时。
- Update UseCase 禁止修改既有 provider 的 scope 或 owner；即使绕过 HTTP Serializer，个人 provider 也不能抬升为 system provider 或转移给其他用户。
- 全部 DRF Serializer 补齐泛型参数和字段校验签名，密钥状态由 Application 查询服务生成，不把解密职责重新放回 Interface。

## 第二百零四批验证结果

- AI Provider Domain/Adapter/配置/加密/预算/路由/API 回归共 `107 passed`，并单独复跑配置模式 `11 passed`；新增覆盖固定密钥掩码、无凭据指纹、负预算、NaN、零预算持续生效、非对象 extra config、非法 Chat 参数和直接 UseCase scope 抬升拒绝。
- Provider Serializer 目标 mypy 清零；全仓基线从 `2484 errors / 538 files` 收紧为 `2474 errors / 537 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零五批

- 按“AI Provider 管理页面可恢复性 × 日志查询输入边界”收口 Provider page views。
- 日志页面不再直接对 `provider` 与 `limit` 查询参数调用 `int()`；非数字、零和负数 provider 过滤器改为不筛选，非法或非正 limit 回到 100，超大 limit 截断为 500，避免用户构造 URL 导致 500 或无界查询。
- 日志 status 只接受正式状态集合，未知值不再下传仓储；页面回显使用规范化后的过滤值，避免界面显示了未实际执行的条件。
- 系统 Provider 管理页改为包含停用配置；管理员可以从同一管理入口重新启用已停用 provider，不再把可恢复配置隐藏在唯一操作页面之外。
- 页面 request、response、provider DTO、动态更新 payload 与辅助解析函数补齐精确类型。

## 第二百零五批验证结果

- AI Provider 页面与 API edge 回归共 `20 passed`；覆盖畸形/负数/超大日志过滤参数、状态规范化和停用系统 provider 可见性。
- Provider page views 目标 mypy 清零；全仓基线从 `2474 errors / 537 files` 收紧为 `2465 errors / 536 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零六批

- 按“API Key 表单回显 × 浏览器页面凭据泄露影响面”收口 Provider Forms。
- Provider API Key 的 PasswordInput 关闭 `render_value`；当 JSON、URL、预算或其他字段校验失败时，用户刚提交的密钥不再重新写入 HTML value，避免通过页面源代码、浏览器插件、截图或前端日志泄露。
- 编辑页留空表示不修改的既有语义保持不变，表单仍只在有效提交时把新密钥交给 Application 写入。
- Provider form 的动态 provider 输入、构造参数和 JSON object 清洗返回值补齐类型。

## 第二百零六批验证结果

- Provider Forms 与管理页面回归共 `5 passed`；新增覆盖表单校验失败后 HTML 不含原始 API Key。
- Provider Forms 目标 mypy 清零；全仓基线从 `2465 errors / 536 files` 收紧为 `2461 errors / 535 files`，净减少 `4 errors / 1 file`。
- 改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零七批

- 按“Django Admin 密钥写入绕过 × 高权限配置入口”收口 AI Provider Admin。
- Admin fieldset 删除 deprecated 明文 `api_key` 与加密字段，改为只读 `masked_api_key`；管理员不能再绕过 Repository/API 加密链路把新凭据直接写入模型明文字段，密钥更新统一走正式页面或 API。
- Admin 与 Application 展示服务统一使用固定 `****` 掩码，不再解密后输出末四位；未配置时明确显示 `Not configured`，避免凭据指纹泄露。
- 三个 Admin 类改为项目统一的 `TypedModelAdmin[ConcreteModel]`，显示列使用 `@admin.display`；Usage Log 的 add/change 权限 handler 补齐 HttpRequest、具体模型与返回类型。
- Admin 仍由既有唯一 `interface.admin` 入口注册，未新增重复注册路径。

## 第二百零七批验证结果

- AI Provider Admin 与加密 guardrail 回归共 `9 passed`；覆盖 Admin 不出现明文/密文字段、固定掩码不泄露后四位和 Repository 加密落库。
- Provider Admin 与密钥展示 Application service 增量 mypy 清零；全仓基线从 `2461 errors / 535 files` 收紧为 `2453 errors / 533 files`，净减少 `8 errors / 2 files`。
- 架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零八批

- 按“Data Center Provider 健康真实性 × 九类事实同步影响面”收口统一 sync use cases。
- 补齐 Fund NAV、财务报表、估值、板块成分、新闻和资金流六类同步的健康写入；这些能力成功时更新成功次数、平均延迟与最后成功时间，失败时更新连续失败数、最后错误与 degraded 状态，并同步通知运行时 Provider Registry。
- 六类同步统一通过 Base UseCase 的 outcome 入口同时写 Provider 健康与 RawAudit；避免各能力分别拼装导致健康和审计状态分叉，Macro、历史价格和实时报价既有行为保持不变。
- 代表性新闻同步回归证明成功与 TimeoutError 都同时更新持久化 health_metrics、运行时 registry 和 raw audit，不再出现同步持续失败但健康面板保留旧状态。
- Fact source 规范化改为保留具体 Fact 类型的泛型入口；Macro Fact 列表、动态 dataclass replace 和 RawAudit request mapping 补齐精确类型。
- 新增 outcome 复用后同步文件保持 `798` 个非空行，低于既有 `800` 行结构预算；未通过提高阈值接受文件膨胀。

## 第二百零八批验证结果

- Data Center Phase 3 sync、结构预算、按需同步回归共 `12 passed`，Data Center API integration 共 `6 passed`。
- Data Center sync use cases 目标 mypy 清零；全仓基线从 `2453 errors / 533 files` 收紧为 `2445 errors / 532 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、结构预算、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百零九批

- 按“Data Center Provider Response 最小披露 × 分层安全契约”收口 Provider 配置响应 DTO。
- `ProviderResponse` 删除原始 `api_key/api_secret` 字段与 `to_dict()` 输出，改为只携带 `has_api_key/has_api_secret`；Application 调用者、任务和日志即使绕过 Interface Serializer，也无法从响应对象取得凭据。
- Provider catalog use case 在 Domain 配置进入响应边界时立即折叠为布尔状态，不再把秘密一路传到 Interface 后才删除。
- Provider List Serializer 原生消费 Application 布尔状态，同时保留对旧字典输入的兼容读取；nested extra_config 的 token/secret/password 递归清理保持不变。

## 第二百零九批验证结果

- Data Center Provider 应用与 Serializer 回归共 `39 passed`，Provider connection governance 与 API integration 共 `9 passed`；覆盖 Application Response 不含秘密、HTTP 创建/详情不回显凭据及嵌套配置脱敏。
- 三个改动生产文件增量 mypy 清零；全仓 debt ceiling 保持 `2445 errors / 532 files`，本批未抬高债务。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十批

- 按“舆情指数真实性 × Celery 异步任务可靠性”收口 Sentiment 每日指数、单事件分析、批量分析与新鲜度检查链路。
- 每日指数、单政策事件和新鲜度任务的 `max_retries` 不再只是装饰配置；运行时仓储、AI 或持久化异常会实际调用 Celery `retry()`，而非法日期和非法事件 ID 等永久输入错误在进入任务主流程前直接拒绝，避免无效重试。
- AI Adapter 返回失败、超时或空内容时生成显式失败结果，并优先保留正式 `error_message`；失败结果不再被当作 0 分中性数据缓存、通过 API 返回或写入每日指数。每日任务遇到 AI 分析失败会在持久化前请求重试，防止“服务不可用”伪装成“市场中性”。
- Data Center 已存新闻情绪在进入指数前必须是有限数；`NaN`、正负无穷和布尔值不会被夹成极端分数。AI 动态关键词只允许非空字符串进入 Domain，数字、空值和其他 JSON 类型被丢弃。
- Sentiment Analyzer、配置仓储、AI Adapter、市场新闻 Provider 和四个 Celery task 补齐 Protocol、具体集合与返回类型；统一使用共享 typed Celery boundary，并改用 AI Provider 正式 Application provider 入口。

## 第二百一十批验证结果

- Sentiment 单元与 API edge 回归共 `43 passed`；覆盖真实重试调用、永久输入不重试、批量任务错误穿透、AI 失败不缓存/不落指数、上游错误信息保留、非有限评分拒绝及动态关键词收窄。
- 四个改动生产文件增量 mypy 清零；全仓基线从 `2445 errors / 532 files` 收紧为 `2415 errors / 528 files`，净减少 `30 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十一批

- 按“回测任务状态真实性 × 异步失败恢复与批量清理影响面”收口 Backtest Celery tasks。
- 回测执行、旧结果清理和报告生成统一使用 typed Celery boundary 与 canonical repository provider；永久输入或业务错误直接失败，运行时异常调用真实 `retry()`，重试期间数据库状态保持 running，只有最终失败才写 failed，避免 Celery 显示成功或尚在重试而业务记录提前失败。
- 任务配置严格校验正整数 ID、日期、布尔值、有限数和 PIT 覆盖结构；Domain 同步拒绝非有限初始资金与交易费率，避免 `NaN`、无穷值或 Python truthiness 进入回测。
- 异步任务和同步页面共用 execution-scoped regime/price reader；单次回测只初始化一次仓储与价格适配器，不再按每个交易日重复读取密钥和构建客户端。
- 旧回测清理拒绝布尔、零、负数及超大保留期，并下沉为数据库 bulk delete；只删除 cutoff 前已完成记录，不逐条加载和删除，也不误删失败或运行中记录。
- 报告任务对不存在或未完成回测抛出正式错误，不再返回包含 `error` 的字典却让 Celery 把任务标记为成功。
- 回测实体、服务、Application provider/interface 和 Infrastructure repository 补齐精确集合与返回类型；类型传播同时消除 Interface views 的既有未类型调用。

## 第二百一十一批验证结果

- Backtest use case、adapter、Domain、API edge、任务与 integration 回归共 `89 passed, 1 skipped`；另行复核模拟交易最低手续费配置链路 `39 passed`，确认买入资金校验读取 `FeeConfig.min_commission`，生产代码无硬编码 `5`。
- Backtest 改动文件增量 mypy 清零；全仓基线从 `2415 errors / 528 files` 收紧为 `2372 errors / 522 files`，净减少 `43 errors / 6 files`。
- Django system check、架构 delta、改动文件 Ruff、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十二批

- 按“归因证据完整性 × Regime 准确率真实性”收口 Audit attribution application use case。
- 回测仓储当前使用 JSONField 保存权益曲线与 Regime 历史；归因用例现同时支持原生 JSON list 和历史 JSON text，不再对原生列表误调用 `json.loads()` 后静默清空真实证据。
- 权益曲线统一收窄为有日期的有限数值点，兼容 ISO 日期与历史毫秒时间戳；畸形、`NaN` 和无穷值在进入 Domain 前丢弃并按日期排序。
- Regime 历史统一验证日期、非空象限和有限置信度；归因准确率改用标准化权益曲线计算区间收益，并统一使用大写枚举比较，修复 `.upper()` 后与混合大小写常量永远不匹配、结果错误回落到中性 `0.5` 的缺陷。
- 行情适配器初始化和单资产读取失败只记录异常类型；Application 响应不再复制可能含凭据、地址或第三方正文的原始异常消息。
- Backtest 查询通过 Application Protocol 注入，动态 ORM 对象只在转换边界保留 `Any`；请求、响应、回测归因数据、Regime 记录、资产收益和审计摘要补齐精确类型。

## 第二百一十二批验证结果

- Audit Application/Domain 回归 `86 passed`，新增归因真实性与 Application 回归 `43 passed`，Audit 数据库 workflow、实际 Regime、治理与 API integration 回归 `50 passed`；分组存在既有测试重叠，均独立通过。
- Attribution application use case 增量 mypy 清零；全仓基线从 `2372 errors / 522 files` 收紧为 `2357 errors / 521 files`，净减少 `15 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十三批

- 按“归因结果可读取性 × 阈值写入防绕过”收口 Audit interface services 与 repository provider。
- 归因生成 payload 只有在 use case 明确成功、返回有效 report ID 且报告能够立即读回时才返回成功；修复缺少 ID 或写后读不到记录仍发布 `success=true` 的错误语义。
- 归因图表 payload 通过 repository 实际查询 LossAnalysis 与 ExperienceSummary，不再因为主报告 serializer 不含 nested 字段而固定返回两个空列表。
- 归因生成、预览与图表入口拒绝非正 ID；报告方法过滤器只接受空值、heuristic 或 brinson，未知值规范化为空过滤器，不把任意字符串下传数据库。
- 阈值更新和预览在 Application 边界再次校验非空指标、有限数与 `level_low < level_high`；直接 use case/内部调用不能绕过 DRF Serializer 写入 `NaN`、无穷值或反向区间。验证预览与执行同步拒绝反向日期范围。
- Backtest repository、阈值响应、动态 ORM 页面上下文和 Audit failure counter/provider 补齐精确返回类型；provider 类型传播同时清除 Audit health check 的既有未类型调用。

## 第二百一十三批验证结果

- Audit interface invariants 与 manual trade helper 回归 `11 passed`；Audit API endpoints、归因治理、验证 API 和阈值配置 API integration 回归 `42 passed`。
- 两个改动 Application 文件增量 mypy 清零；全仓基线从 `2357 errors / 521 files` 收紧为 `2331 errors / 519 files`，净减少 `26 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十四批

- 按“公开健康接口最小披露 × 运维状态真实性”收口 Audit health check。
- 健康接口不再返回数据库名称、数据库引擎、原始异常消息或最近失败 reason；数据库与表检查只发布 passed/error type，失败计数接口只发布总数和按组件聚合，避免公开接口泄露 DSN、SQL、内部地址或第三方响应。
- 显式 `warning_threshold=0` 不再被 Python truthiness 替换为默认 10；阈值必须是非负整数且 error 严格大于 warning，非法查询参数返回 400，不再静默使用默认值或触发 500。
- 健康检查器不再跨调用缓存首个阈值配置；每次请求按本次参数构建，避免后续调用实际使用旧阈值。
- 指标采集失败会增加 `audit_metrics=ERROR` 检查并把 overall status 置为 ERROR，不再出现 metrics 已不可用但总体仍为 OK；错误 payload 只保留异常类型。
- `failure_rate` 改为失败数除以成功日志与失败数之和，保持在 `0..1`，不再用失败数直接除以成功日志数而产生大于 100% 的伪比率。
- Audit Repository Protocol 补齐 operation log count，并清理全部裸集合类型；Health Checker、Failure Stats 与 Counter 使用精确 Protocol。

## 第二百一十四批验证结果

- Audit health、failure counter 与 interface invariants 回归 `42 passed`，公开健康响应专项回归 `14 passed`；Audit API edge、API integration 与 endpoints 回归 `48 passed`。
- Health check 与 Audit Domain interface 增量 mypy 清零；全仓基线从 `2331 errors / 519 files` 收紧为 `2322 errors / 517 files`，净减少 `9 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十五批

- 按“操作审计凭据保密 × 审计查询授权完整性”收口 Audit operation log 全链路。
- 新写入日志对结构化请求与响应递归脱敏，并同步清理响应正文、响应消息、异常堆栈和含查询参数的请求路径；覆盖 Bearer Token、URL 凭据、私钥、API Key、密码及 OpenAI 风格密钥，不再只保护 JSON 字段。
- Repository 在列表、详情和决策追踪读取边界再次脱敏，历史遗留的未清理记录也不会直接返回；摘要生成只使用清理后的响应内容。
- 日志写入与查询失败不再把数据库异常正文复制到 API、失败计数或应用日志，只保留稳定错误文案与异常类型。
- 普通用户缺少可信用户 ID 时，日志列表、详情和决策追踪默认拒绝，不再把空用户过滤条件解释为全量查询；导出与统计在 Application 边界要求显式管理员上下文。
- 查询排序、分页、导出格式、日期范围、统计分组和行数上限在 Application 边界统一校验，内部调用不能绕过 Interface Serializer 向 ORM 传入任意排序字段。
- Operation Log entity、factory、use case 与 repository 补齐具体集合、ORM 和序列化返回类型；归因周期集合改用协变只读接口，保持 Brinson 调用方类型兼容。

## 第二百一十五批验证结果

- Audit operation log Domain、failure counter 与安全不变量回归 `46 passed`；Audit internal ingest 与 API integration 全组 `21 passed`，另对历史记录读取脱敏和签名写入做定点复核 `2 passed`。
- 七个相关生产文件增量 mypy 清零；全仓基线从 `2322 errors / 517 files` 收紧为 `2297 errors / 513 files`，净减少 `25 errors / 4 files`。
- 改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十六批

- 按“归因统计真实性 × 投研判断影响面”收口 Audit heuristic attribution Domain service。
- Regime 预测与实际值在双方带日期时按共同日期对齐，不再按列表位置比较；输入顺序变化不会制造错误命中率，大小写统一后再计算准确率与混淆矩阵。
- Regime 周期先验证日期、非空象限和有限置信度并按日期排序，畸形观察不会进入归因；权益曲线过滤非有限值，周期起始净值必须大于零，避免除零或发布 `NaN` 收益。
- 信息比率要求基准收益数与权益曲线区间数严格一致，不再用零填充缺失基准；零或非有限净值、非有限基准直接返回不可计算。
- 资产收益只聚合有限数，交易成本总额必须有限；损坏数据不再静默形成看似有效的归因数字。
- 通过最小只读 Protocol 接受正式 BacktestResult 与 Audit Application 的不可变简化结果，服务函数补齐具体集合、返回 DTO 和内部变量类型。

## 第二百一十六批验证结果

- Attribution service、performance analyzer 与新增真实性不变量回归共 `90 passed`。
- Attribution Domain service 增量 mypy 清零；全仓基线从 `2297 errors / 513 files` 收紧为 `2282 errors / 512 files`，净减少 `15 errors / 1 file`。
- 改动文件 Ruff、Black、isort、diff check、增量 mypy与全仓 debt ceiling 通过。

## 第二百一十七批

- 按“指标验证批次隔离 × 动态权重调整影响面”收口 Audit indicator performance persistence。
- `IndicatorPerformanceModel` 新增可空、带索引的 `validation_run_id`，并以条件唯一约束保证同一批次每个指标至多一份报告；阈值验证生成批次后把同一 ID 传给每个指标评估并随报告落库，报告查询实际按批次过滤，不再忽略已有参数。
- 动态权重调整只读取指定验证批次的报告；没有批次关联报告、缺少激活阈值配置或报告关键指标不完整时默认拒绝，不再按相同日期区间混入其他运行或历史报告。
- 指标表现、Regime 日志和页面上下文序列化统一使用 `is not None` 与有限数收窄；合法的 `0.0` F1、精确率、召回率、稳定性、权重、置信度和衰减率不再被错误发布为缺失。
- 指标表现写入拒绝空指标、反向日期、负混淆矩阵计数和非有限指标；阈值更新只允许激活配置，权重必须有限且处于该指标配置的最小/最大范围，水平阈值必须有限且 `low < high`。
- Macro Fact 查询先投影为明确的候选 DTO，再调用统一来源选择规则；返回值统一为有限浮点数，不再把 Django Decimal 模型硬塞入不兼容的选择协议。
- 补充迁移 `0009_indicatorperformancemodel_validation_run_id.py`；Audit ORM model 的字符串与 Domain 转换方法补齐返回类型，F1 缺失时字符串展示为 `N/A`，不再因格式化 `None` 抛错。

## 第二百一十七批验证结果

- Audit unit、Domain、Application、integration 与 Macro Fact 组件完整相关回归 `301 passed`；Interface、validation 与 threshold config 定点回归另有 `20 passed`。
- `makemigrations --check --dry-run` 无漂移，Django system check 与架构 delta 通过。
- Indicator use case、repository 与 Audit models 增量 mypy 清零；全仓基线从 `2282 errors / 512 files` 收紧为 `2257 errors / 509 files`，净减少 `25 errors / 3 files`。
- 改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十八批

- 按“基金研究状态真实性 × 配置唯一真源 × API 输入边界”收口 Fund 研究链路。
- 基金筛选同时读取数据库中按 Regime 配置的基金类型与投资风格；调用方显式条件可覆盖数据库偏好，未配置基金类型时失败关闭，不再使用代码内置的类型或风格列表制造筛选依据。
- Dashboard 缺少或损坏 Regime、Policy、Sentiment 数据时明确发布未知或未配置；不再用 Recovery、P1 或中性情绪伪装缺失状态。
- 基金表现记录的起止日期改为实际净值证据覆盖区间；反向日期、未来排名日期、非有限门槛和非法 Regime 在 Application 边界拒绝。
- Fund detail、分析、表现、净值、持仓和多维筛选 API 统一要求认证；请求 serializer 拒绝未知字段并验证日期、数值范围和筛选上下界。
- 多维筛选要求显式提供 Regime、Policy 与有限 Sentiment，不再补默认宏观环境；无匹配结果返回稳定的 `count=0` 结构并正确映射 404，内部异常不再复制到 API。
- Application 通过 Repository Protocol 与 provider factory 访问持久化实现，基金代码、日期、动态 ORM 与外部数据在边界完成类型收窄。

## 第二百一十八批验证结果

- Fund API edge、Domain、Repository、Application 与配置命令相关回归 `116 passed`。
- 八个核心改动文件增量 mypy 清零；适配器保留的 `16` 个历史错误无新增；全仓基线从 `2257 errors / 509 files` 收紧为 `2182 errors / 502 files`，净减少 `75 errors / 7 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百一十九批

- 按“估值研究输入真实性 × 内部错误最小披露”收口 Equity 估值修复与数据同步 API。
- 财务数据同步和估值修复列表改为实际执行已发布的 request serializer；未知字段、非法 phase、越界数量不再被静默忽略或绕过校验。
- 估值同步拒绝反向日期区间和相同的主备来源；数据源名称只校验动态标识符格式，不把供应商目录硬编码进 Interface。
- 估值修复、同步、质量、新鲜度和快照接口不再复制底层异常正文；质量 gate 等明确业务失败保留稳定语义，其他异常统一发布固定错误。
- 财务同步任务的逐股票失败结果只返回股票代码和稳定失败文案，provider 异常原文仅以异常类型进入内部日志，不再通过任务/API payload 泄露。
- Equity compatibility facade、valuation action、DRF action 与 OpenAPI decorator 增加精确类型边界，在保持既有 monkeypatch 与路由契约的同时清除未类型调用。

## 第二百一十九批验证结果

- Equity valuation repair、sync、serializer 与 task 相关完整回归 `127 passed`；最终严格输入和错误披露边界集 `41 passed`。
- Equity facade 与 valuation action 增量 mypy 清零；全仓基线从 `2182 errors / 502 files` 收紧为 `2152 errors / 500 files`，净减少 `30 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十批

- 按“个股分析输入契约 × 用户研究入口影响面”收口 Equity analysis actions。
- 个股筛选、DCF、综合估值、技术图表、分时图和 Regime 相关性请求统一使用严格字段 serializer；未声明的 body 或 query 参数不再被静默忽略。
- 技术图表、分时图和 Regime 相关性查询改为把完整 query 交给 serializer，再注入路径股票代码；避免只挑选已知参数后掩盖调用方拼写错误。
- Analysis mixin 明确发布组合 viewset 所需仓储属性、DRF Request/Response 和方法签名，并复用已类型化的 action/schema decorator；保持现有路由与 OpenAPI 契约不变。

## 第二百二十批验证结果

- Equity API edge 与 serializer contract 回归 `34 passed`，覆盖六类分析端点的未知输入拒绝。
- Equity analysis action 增量 mypy 清零；全仓基线从 `2152 errors / 500 files` 收紧为 `2137 errors / 499 files`，净减少 `15 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十一批

- 按“估值来源真实性 × 同步结果真实性 × 质量门禁影响面”收口 Equity 估值同步与质量链路。
- Data Center provider 选择服务同时返回数据库 provider ID 与实际配置名称；估值读取按 canonical fact 的 `extra.provider_name` 精确匹配，不再把动态配置名称误当固定 `akshare` / `tushare` 来源，也不再因 canonical `source_type` 覆盖名称而读不到已同步数据。
- 估值同步根据数据库启用的 provider 动态构造读取 gateway；主备来源配置缺失、名称非法或相同均失败关闭，不在业务代码硬编码 provider 目录。
- 显式空股票列表不再被扩展为全部活跃股票；股票代码、日期区间、未来日期和 `days_back` 在 Application 边界统一校验。
- 单股失败只发布稳定错误文案，底层异常仅以类型进入日志；零写入和回填中任一批次失败均返回失败，不再把“全部失败”或“部分失败”包装成成功。
- 质量快照记录实际 provider 名称；新鲜度检查只接受估值日期当天的质量证据，旧快照和未来估值日期均失败关闭，避免用过期质量结果放行当前数据。
- 估值仓储只读 Protocol 改用协变 `Sequence`，正式 ORM 仓储与管理命令调用进入类型检查；同步、质量、回填 DTO 与内部集合补齐精确类型。

## 第二百二十一批验证结果

- 估值同步、质量门禁、来源 gateway、任务、修复 API、管理命令和 Data Center provider 选择相关合并回归 `58 passed`；格式后核心不变量定点复核 `19 passed`。
- 七个关联生产文件增量 mypy 清零；全仓基线从 `2137 errors / 499 files` 收紧为 `2119 errors / 498 files`，净减少 `18 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十二批

- 按“估值修复状态真实性 × 批量扫描结果真实性”收口 Equity 估值修复 Application 用例。
- 单股状态与百分位历史在 Application 边界校验股票代码和回看窗口，批量扫描校验窗口与数量上限，内部调用不再依赖 Interface 才能阻止非法输入。
- 估值历史使用 `is not None` 转换 PE/PB，合法的 `0` 不再被错误改写为缺失值。
- 批量扫描存在任一股票失败时明确返回失败和失败计数，不再把部分失败包装为成功；逐股和整体异常只记录异常类型，对外使用稳定错误文案。
- `all_active` 股票池通过明确 Repository Protocol 读取，移除运行时 `hasattr` 和不受控降级查询；股票、质量快照、修复快照与股票池依赖均收窄为只读 Protocol。
- 状态、历史、列表响应和阶段计数补齐具体集合类型；质量快照分支显式收窄，正式 API、任务和仓储装配进入增量类型检查。

## 第二百二十二批验证结果

- 估值修复 API、配置集成、同步任务及新增真实性不变量回归 `42 passed`。
- 估值修复 Application 用例及其主要调用方增量 mypy 清零；全仓基线从 `2119 errors / 498 files` 收紧为 `2106 errors / 497 files`，净减少 `13 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十三批

- 按“质量覆盖率真实性 × ORM 边界完整性”收口 Equity 估值修复与质量快照仓储。
- 质量快照按股票代码去重后计算同步数、有效数、异常数和主备来源数，同一股票重复记录不再虚增覆盖率或改变质量 gate。
- 质量快照拒绝负预期股票数、空主来源和缺失或错误类型的快照日期；主来源去除首尾空白后再持久化和比较。
- 修复状态写入使用明确 Domain 实体，修复快照列表使用具体 ORM Model，质量 payload 与批量快照映射补齐键值类型；移除仓储内部重复的延迟 model import。

## 第二百二十三批验证结果

- 估值质量、修复用例和修复 API 相关回归 `31 passed`，覆盖重复股票不重复计数。
- 估值修复仓储及主要调用方增量 mypy 清零；全仓基线从 `2106 errors / 497 files` 收紧为 `2101 errors / 496 files`，净减少 `5 errors / 1 file`。
- 改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十四批

- 按“估值配置管理接口类型完整性 × 管理操作授权面”收口 Equity 估值修复配置 ViewSet。
- 配置列表、详情、创建、更新、删除、激活、回滚和清缓存 handler 补齐 DRF Request/Response 与路由主键类型，动态 Application 返回值只在 Interface 边界保留 `Any`。
- 激活和回滚复用内部类型化 helper，避免直接调用经 DRF decorator 包装的方法而破坏方法绑定；OpenAPI 与 action 统一复用项目已有类型化 decorator 适配层。
- 审计操作者通过认证用户的标准 `get_username()` 获取，不再依赖具体 User Model 的动态 `username` 属性；管理员权限、路由和响应契约保持不变。

## 第二百二十四批验证结果

- 估值修复配置集成与 serializer 契约回归 `16 passed`。
- 配置 ViewSet 及兼容 facade 增量 mypy 清零；全仓基线从 `2101 errors / 496 files` 收紧为 `2089 errors / 495 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十五批

- 按“Policy 公共查询边界 × 工作台与 RSS 管理影响面”收口 Policy interface repositories。
- 页面和 API 的可选布尔过滤统一解析 `true/false/1/0`；修复 HTML 页面常用 `is_active=1` 被错误解释为 `False` 的查询语义，并拒绝含糊布尔值。
- RSS 来源外键过滤统一解析为正整数；空值表示不过滤，零、负数、小数和非数字不再直接交给 ORM 隐式转换。
- Policy 趋势聚合使用 `values(day=TruncDate(...))` 声明派生日期列，保持按日分组 SQL 语义并让 Django ORM 类型系统识别 annotation。
- 页面、RSS API、工作台查询补齐具体 QuerySet Model 类型；values/aggregate 结果在 Infrastructure 边界复制为普通字典，不再把 Django TypedDict QuerySet 声明成不兼容的可变字典列表。
- 通用布尔 QuerySet helper 使用协变 Model TypeVar 保持输入输出模型一致；管理统计、工作台详情、RSS 状态等现有查询契约保持不变。

## 第二百二十五批验证结果

- Policy 页面、RSS API、工作台、Application 装配及新增布尔/ID 边界回归 `55 passed`；派生日期查询调整后工作台与边界定点复核 `35 passed`。
- Policy interface repository 增量 mypy 清零；全仓基线从 `2089 errors / 495 files` 收紧为 `2072 errors / 494 files`，净减少 `17 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十六批

- 按“Policy 事件写入授权 × 查询输入完整性 × 内部错误最小披露”收口 Policy event API。
- 状态、历史和事件 ID 查询新增严格 serializer；未知参数、反向日期范围、非法档位和非正 event ID 在进入用例与仓储前返回稳定 400，不再依赖手写字符串转换或静默忽略拼写错误。
- 创建、更新、删除继续要求 staff，读取继续要求认证；权限实例、DRF Request/Response、路径日期和 schema decorator 补齐精确类型。
- 创建事件的意外异常不再把数据库、通知服务或其他内部异常正文复制进 `errors`；全部异常日志只在固定消息中附带异常类型，API 返回稳定错误文案。
- 状态、历史、创建和更新响应使用明确 JSON payload 边界，修复嵌套事件字典写入被错误推断为标量的问题；OpenAPI 类型从正式 `drf_spectacular.types` 入口导入。

## 第二百二十六批验证结果

- Policy 事件 API 与 serializer 契约回归 `14 passed`，覆盖未知查询、反向日期、非正事件 ID、权限和内部异常脱敏。
- Policy event API 与 serializers 增量 mypy 清零；全仓基线从 `2072 errors / 494 files` 收紧为 `2055 errors / 493 files`，净减少 `17 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十七批

- 按“Policy 档位变更副作用真实性 × 中心 ORM 类型完整性”收口 Policy models 与信号派发。
- 原 `post_save` 通过查询更早日期的另一条事件判断档位变化，导致只修改描述也可能重复触发全量信号重评；现由 `pre_save` 捕获同一行持久化前的档位，仅真实档位变化才进入派发。
- 信号重评改为事务成功提交后调度，避免 worker 在数据尚未提交时读取旧状态；`PX` 和其他非 P0–P3 档位不会再执行 `int(level[1])` 而抛错。
- 信号异常日志只发布异常类型，不复制 Celery、数据库或配置异常正文；非变更保存、真实 P1→P2 变化和 P1→PX 三种路径均新增回归。
- Policy ORM 的字符串展示、单例配置读取和 RSSHub URL 构造补齐具体返回与 Optional 类型；单例查询统一使用 `_default_manager`，不再从未类型 `objects` 传播 Any。

## 第二百二十七批验证结果

- Policy 模型信号、任务边界和事件 API 回归 `25 passed`。
- Policy models 增量 mypy 清零，并传播清除 workbench repository 2 项债务；全仓基线从 `2055 errors / 493 files` 收紧为 `2037 errors / 492 files`，净减少 `18 errors / 1 file`。
- `makemigrations --check --dry-run` 无 schema 漂移；Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十八批

- 按“Policy 关键词分类真实性 × 风险档位决策影响面”收口 Policy Application matcher service。
- 关键词规则在构建 matcher 时拒绝空关键词、非正权重和 P1–P3 之外的档位；空字符串不再因属于所有标题而把每条新闻误判为命中。
- 同一规则内的关键词先去空白、统一大小写并去重，重复配置不再重复累加权重；关键词映射、逐档详情和解释 payload 使用明确 TypedDict 与 tuple 类型。
- 多个档位得分相同时按更高严重度 P3→P2→P1 决胜，不再因字典插入顺序默认选择低风险 P1；无正分时仍明确返回未匹配。
- 匹配日志改为参数化固定消息，不复制完整 RSS 标题；普通匹配与解释型匹配共享相同规范化和风险决胜规则。

## 第二百二十八批验证结果

- Policy 内容、事件、RSS Application 与任务回归 `14 passed`，覆盖空关键词、非法权重/档位、重复关键词和同分高严重度决胜。
- Policy Application services 增量 mypy 清零；全仓基线从 `2037 errors / 492 files` 收紧为 `2027 errors / 491 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百二十九批

- 按“Policy 审核队列公平性 × 状态与审计原子性”收口 Policy workbench repository。
- 审核队列优先级改为数据库 `Case` 表达式按 urgent/high/normal/low 排序后再应用 limit，同批最紧急事项不再因先截断、后内存排序而被排除。
- 批准、拒绝、回滚和豁免的事件状态写入与 `GateActionAuditLog` 写入统一进入同一事务；审计落库失败时事件状态一并回滚，不再留下无审计凭据的变更。
- 摄入配置更新只接受五个公开运行参数，未知字段在访问数据库前拒绝；写入前执行 Model validation，禁止通过动态 `setattr` 覆盖 `save` 等模型方法或非公开字段。
- 审核分配与清理时间使用 aware datetime 契约，日统计嵌套映射、事件状态快照和审计前后状态补齐具体类型；workbench 构造函数与最新抓取时间返回值进入类型检查。

## 第二百二十九批验证结果

- Policy workbench repository、审核 use case、工作台 API 与集成回归 `40 passed`；排序、事务回滚和配置字段边界定点复核 `3 passed`。
- Workbench repository 增量 mypy 清零，并传播清除 audit use case 与 repository provider 4 项债务；全仓基线从 `2027 errors / 491 files` 收紧为 `2011 errors / 490 files`，净减少 `16 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、diff check、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十批

- 收口 Policy 公共 repository provider 的最后一项导出债务。
- `PolicyDiagnosticRepository` 在 Infrastructure provider 中改为显式同名 re-export，Application composition root 与约 25 个 Policy 生产调用方不再依赖未声明的隐式符号。

## 第二百三十批验证结果

- Policy repository 导出契约与 use case 回归 `6 passed`。
- Policy repository provider 增量 mypy 清零；全仓基线从 `2011 errors / 490 files` 收紧为 `2010 errors / 489 files`，净减少 `1 error / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十一批

- 按“首页投资候选真实性 × 缺失上下文失败关闭 × 非有限数值隔离”收口 Dashboard Alpha 首页候选链路。
- 组合候选缺少宏观仓位上下文时不再使用 `1.0` 中性系数继续生成可行动建议；结果明确降级为仅供研究，建议金额归零并发布稳定阻断原因。
- Regime、Pulse、组合快照或市场温度上下文不可用，以及市场温度明确降级时，候选不再进入可行动阶段；原始可靠性阻断原因继续保持为对外主原因。
- Alpha 评分、置信度、排名、仓位系数、市场温度和待执行金额统一拒绝 `NaN`、`Inf`、越界值与负数；非法评分和置信度以缺失发布，不再伪装为中性 `0`。
- 因子依据中的非有限数值明确显示为“不可用”；待执行请求不再发布虚构的 `0` 分和 `0` 置信度，数量恢复为整数语义。
- Candidate mixin 明确声明仓储、决策、仓位和风控依赖，评分与仓位上下文参数收窄为正式实体/DTO；仓位上下文加载失败仅在内部日志保留堆栈，对外保持稳定降级语义。

## 第二百三十一批验证结果

- Dashboard Alpha 查询、视图、上下文仓储和 mixin 结构回归 `91 passed`，覆盖宏观仓位上下文缺失、非有限评分和非有限因子不能形成可行动建议。
- Dashboard Alpha candidate mixin 增量 mypy 清零；全仓基线从 `2010 errors / 489 files` 收紧为 `1995 errors / 488 files`，净减少 `15 errors / 1 file`。
- Django system check、架构规则、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十二批

- 按“生产 readiness 证据真实性 × 直接调用输入边界 × 探针数据可追溯性”收口个人 readiness 取证命令。
- Readiness 总状态正式纳入 quote pre-readiness 调度器状态；任一未识别状态失败关闭，不再把 `unknown` 或调度器错误包装成整体 `ok`。
- 命令函数的直接调用与 CLI 使用相同边界：拒绝未收盘目标日、非正用户/账户 ID 和负 Qlib 新鲜度窗口，定时任务或内部调用不再绕过 CLI 校验。
- 系统宏观上下文缺少 Regime 或 Pulse 字典时写入明确错误检查项，不再把动态 `None` 注入 readiness checks；健康状态只计算一次并与保存证据一致。
- 预交易 readiness 探针只使用实际持仓代码和实际正价格；没有可追溯标的或价格时返回不可用警告，不再硬编码 `510300.SH` 或用 `1.0` 伪造报价。
- 探针订单金额严格限制在现金的 1% 与账户权益的 0.5% 内；数值解析拒绝 `NaN` 和 `Inf`，避免非有限资产、现金或价格进入风控证据。
- 延迟导入的 Dashboard、模拟交易、Qlib 和券商 readiness 边界使用明确集合/日期类型，管理命令 parser、系统检查合并和动态 provider 返回值全部进入增量类型检查。

## 第二百三十二批验证结果

- Readiness 取证命令、日常任务、证据修复和窗口验收回归 `57 passed`；核心命令定点回归 `22 passed`。
- 个人 readiness 取证命令增量 mypy 清零；全仓基线从 `1995 errors / 488 files` 收紧为 `1983 errors / 487 files`，净减少 `12 errors / 1 file`。
- Django system check、架构规则、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十三批

- 按“Regime 四象限语义真实性 × 快照持久化完整性 × 变化通知结果真实性”收口 Regime 定时编排链路。
- 高频日度用例输出的是 `BULLISH/BEARISH/NEUTRAL` 方向信号，月度结果输出的是四象限 Regime；编排层不再把两套不可比较的枚举送入冲突解析器并发布虚假 `HYBRID` 结论。
- 日度方向通过完整性校验后作为独立上下文证据发布，最终四象限继续使用可审计的月度结果；在 Domain 尚未提供方向到四象限的正式映射前不擅自推断象限或改写置信度。
- 日度方向、强度和置信度必须完整、有限且位于合法范围；成功标记但 payload 缺失、含 `NaN`/`Inf` 或越界时明确返回错误，不再进入融合链路。
- V2 快照持久化前验证 PMI/CPI 动量有限、置信度在 `[0, 1]`、四个 canonical Regime 概率完整非负且总和为 1；非法计算结果不会写入 Regime 真源。
- Macro 同步结果只有显式 `success`、`partial` 或 legacy `success=True` 才允许继续计算；错误和未知结构失败关闭，不再因缺少 `success` 字段而被默认视为成功。
- 通知输入验证 canonical Regime、有限置信度和有效日期；无变化时明确 `notified=false`，只有实际通知结果成功才发布已通知，需通知但全部失败时状态为 warning。
- Celery task 返回值、V2 结果和快照使用具体类型；共享任务 decorator 使用局部错误码豁免，不再让整个编排函数退化为未类型代码。

## 第二百三十三批验证结果

- Regime 编排、持久化、任务契约、Macro 周期调度和 Celery 注册回归 `15 passed`；核心编排定点回归 `10 passed`。
- Regime orchestration 增量 mypy 清零；全仓基线从 `1983 errors / 487 files` 收紧为 `1970 errors / 486 files`，净减少 `13 errors / 1 file`。
- Django system check、架构规则、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十四批

- 按“Dashboard 决策配额真实性 × 单次快照一致性 × 用户页面可解释降级”收口 DecisionPlane 导航与页面上下文。
- 决策平面一次执行只读取一次周度配额，不再分别查询总额、已用和剩余后拼接可能来自不同时间点的三项数据。
- 配额总额、已用和剩余必须是非负整数，且满足 `used <= total` 和 `remaining = total - used`；布尔值、小数、负数和勾稽不一致的 payload 均判为不可用。
- 配额查询缺失、异常或不一致时发布 `quota_available=false` 与零值占位，不再硬编码“总额 10、剩余 10”制造虚假可用额度。
- Dashboard 页面新增明确的配额可用状态；不可用时总额和剩余显示“不可用”，进度条保持空白，不把占位零解释为真实零额度。
- DecisionPlane DTO、Interface fallback 和兼容 navigation facade 统一使用同一可用性语义；旧测试/兼容对象缺少新字段时按不可用处理，避免乐观推断。

## 第二百三十四批验证结果

- Dashboard Alpha 查询与结构回归 `38 passed`，页面与 HTMX 相关回归 `47 passed`，覆盖单次配额读取、三项勾稽失败和页面兼容渲染。
- Dashboard navigation context 增量 mypy 清零；全仓基线从 `1970 errors / 486 files` 收紧为 `1958 errors / 485 files`，净减少 `12 errors / 1 file`。
- Dashboard queries 保留既有 `6` 项历史类型债务且无新增；Django system check、架构规则、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十五批

- 按“全局股票池写入授权 × 筛选配置唯一真源 × 缺失指标真实性”收口 Equity 股票池 API。
- 股票池读取显式要求认证；全局股票池刷新改为仅 staff 可执行，普通登录用户不再能够改写所有用户共用的池快照。
- Pool GET query 与 refresh body 使用严格空请求 serializer；任何未知字段在查询或筛选前返回 400，不再被静默忽略。
- Refresh 不再传入硬编码 `max_count=50`；`ScreenStocksRequest.max_count` 改为可选，调用方未显式覆盖时使用数据库中当前 Regime 的筛选规则数量。
- 当前 Regime 缺失、降级或不是 canonical 四象限时刷新失败关闭；筛选结果为空时返回 422 并保留现有池，不再用空列表覆盖有效快照。
- 股票池读取优先发布快照自身记录的 Regime；快照没有 Regime 且当前判定不可用时发布空值，不再使用 `Unknown` 伪装成业务状态。
- 缺失 ROE、PE、PB、增长率和尚未实现的评分统一发布 `null`；平均 ROE/PE 只按真实有效观测计算，`NaN`/`Inf` 被隔离，不再以 `0` 冒充实测值或稀释平均数。
- 股票池异常响应不再复制 ORM、配置或筛选异常正文；日期使用 Django 本地交易日语义，Mixin 仓储属性、Request/Response 和 provider 公共类型导出补齐精确声明。

## 第二百三十五批验证结果

- Equity Pool API、API edge、用例和模块结构回归 `43 passed`，覆盖普通用户禁止刷新、未知字段拒绝、空筛选保留旧池、配置数量不硬编码和缺失指标发布为空。
- Equity pool actions 增量 mypy 清零；全仓基线从 `1958 errors / 485 files` 收紧为 `1948 errors / 484 files`，净减少 `10 errors / 1 file`。
- Django system check、架构规则、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十六批

- 按“Agent Runtime 公共快照可用性 × 单源故障隔离 × 内部错误最小披露”收口 context facade 基类。
- Application 层新增完整的 context snapshot repository Protocol；基类构造函数、八项公共读取和各领域扩展仓储能力不再通过未类型动态对象传播 `Any`。
- 快照构建对 Regime、Policy、组合、信号、决策、风险、任务健康和数据新鲜度逐项隔离；任一 fetch 抛异常只将对应摘要降级，不再中断整个 Agent 上下文。
- 仓储返回的 `unavailable` / `unsupported` 摘要在 facade 出口统一替换为稳定错误码 `source_fetch_failed`；数据库地址、连接错误和其他内部异常正文只进入服务端日志。
- fetch 返回非字典结构时失败关闭为该来源不可用，避免异常动态结果直接进入 API/MCP 快照。

## 第二百三十六批验证结果

- Agent Runtime facade 回归 `28 passed`，context repository 与 MCP 资源回归 `25 passed`，覆盖 fetch 异常隔离、错误详情脱敏和其他来源继续可用。
- 6 个 context facade 文件增量 mypy 清零；同时传播清除 facade factory 的未类型调用债务，全仓基线从 `1948 errors / 484 files` 收紧为 `1938 errors / 482 files`，净减少 `10 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十七批

- 按“数据中台公共 API 输入可靠性 × 市场温度用户边界 × Provider 健康数据真实性”收口 Data Center API views。
- 行情新鲜度小时数除正数外必须为有限值；`NaN`、`Inf` 和 `-Inf` 在进入报价用例前返回稳定 400，不再绕过比较并污染决策新鲜度。
- 市场温度个人阈值布尔开关、历史天数和指标/发布机构 active filter 的非法查询值统一返回带正确字段名的 400，不再由未捕获 `ValueError` 形成 500 或误报为其他参数。
- 个人市场温度 override 的 GET、写入和删除统一从认证请求提取已持久化的正整数用户 ID；缺少有效身份时失败关闭，不再向 Application 传递可空 ID。
- Provider 健康快照的持久化延迟和连续失败数使用共享安全数值解析；非数字、非有限、负数和非整数遥测不再导致状态 API 500 或发布非法数值。
- Provider 配置列表/创建 serializer 分离变量，健康快照和 provider payload 使用明确 JSON 边界类型；接口动态用户对象只在 composition 边界保留 `Any`。

## 第二百三十七批验证结果

- Data Center route cleanup 与市场温度 API 回归 `39 passed`，覆盖非有限新鲜度、非法布尔/天数、损坏的 provider 遥测和个人 override CRUD。
- Data Center API views 增量 mypy 清零；全仓基线从 `1938 errors / 482 files` 收紧为 `1925 errors / 481 files`，净减少 `13 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百三十八批

- 按“基金外部数据边界稳定性 × 无数据返回契约 × 来源脏日期隔离”收口 Tushare fund adapter。
- 适配器新增最小 Tushare fund client Protocol；延迟初始化返回已收窄 client，六个基金 API 调用不再从可空动态对象传播未类型调用。
- Tushare 的 `None` 无数据响应统一规范化为空 DataFrame，各公开 fetch 方法继续稳定返回 DataFrame，不再把 `None` 送入基金仓储和 Data Center 映射链路。
- 非 DataFrame 的异常 SDK 返回明确拒绝，不再在后续列访问处产生含糊异常；返回帧先复制，日期规范化不会原地修改 SDK 共享对象。
- 基金持仓和场内日线日期与其他基金接口统一使用 `errors="coerce"`；来源脏日期隔离为缺失值，不再使整批基金数据同步失败。
- Pandas 第三方无 stub 边界使用精确 `import-untyped` 豁免，适配器内部和 Tushare client 能力保持完整类型检查。

## 第二百三十八批验证结果

- 基金适配器契约回归 `5 passed`，Tushare 统一 provider 的 fund NAV 映射回归 `1 passed`，覆盖无数据空帧和无效来源日期。
- Fund Tushare adapter 增量 mypy 清零；全仓基线从 `1925 errors / 481 files` 收紧为 `1910 errors / 480 files`，净减少 `15 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。
- 扩展运行整个 `test_phase3_provider_adapters.py` 时，既有 CPI 细分测试因测试帧列名被规范化为 `column_0...` 而失败；单独复跑同样失败，调用栈不经过本批基金适配器，未混入本批修复。

## 第二百三十九批

- 按“全局任务运维授权 × 查询输入边界 × 内部异常最小披露”收口 Task Monitor API。
- 任务状态、列表、统计、Celery 健康和 Dashboard 都读取全局任务/基础设施状态，且任务记录没有用户归属字段；权限由普通登录收紧为 staff-only，避免普通账户枚举全局任务运行信息。
- 列表 `limit` 和统计 `days` 严格要求正整数；`failures_only` 仅接受明确布尔值，`status` 仅接受 Domain 已定义的七种任务状态，非法输入稳定返回 400。
- 状态、列表、统计和 Dashboard 的意外异常正文不再复制到 API；服务端保留异常堆栈，对外统一稳定 `INTERNAL_ERROR`。Celery 健康降级继续返回 503 结构化状态，但错误字段固定为 `health_check_failed`。
- 五个 handler 补齐 DRF Request/Response 类型；OpenAPI 类型从正式 `drf_spectacular.types` 入口导入，Dashboard schema 不再使用裸 `dict`。
- Application provider 的 repository/health checker 等四项能力改为显式同名 re-export，Task Monitor 调用方不再依赖隐式模块属性。

## 第二百三十九批验证结果

- Task Monitor API 回归 `26 passed`，覆盖普通用户禁止访问、非法 limit/days/status/boolean、内部异常脱敏和 Dashboard/Celery 正常契约。
- Task Monitor views 的 `attr-defined` 与未类型 handler 债务清零，并传播清除 query service 的隐式 provider 属性债务；全仓基线从 `1910 errors / 480 files` 收紧为 `1902 errors / 479 files`，净减少 `8 errors / 1 file`。
- 全仓口径仍保留该 views 文件 `5` 项 DRF decorator `misc` 历史债务；本批未通过宽泛 ignore 掩盖，后续结合 serializer 泛型治理处理。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十批

- 按“首次安装高权限写入防护 × 向导步骤完整性 × 配置异常最小披露”收口 Setup Wizard。
- 移除步骤 POST 路由的 `csrf_exempt`；管理员创建、AI 密钥和数据源密钥写入重新受 Django CSRF 防护，跨站请求不能再触发初始化副作用。
- 已存在管理员时，每个步骤 POST 都要求 `setup_wizard_authenticated` session；不再只有 GET 页面检查认证而让调用方绕过页面直接提交配置。
- welcome 之后的步骤必须与服务端 session 当前步骤一致；直接跳到 data source 不会再保存密钥、跳过前置步骤或调用 `CompleteSetupUseCase`。
- 动态 `getattr` handler 改为 WizardStep 到精确 Callable 的显式映射；SetupState、HttpRequest 和 HttpResponse 全部进入类型检查。
- 管理员、AI Provider 和数据源保存异常只在服务端日志保留堆栈，对用户返回稳定失败文案，不再在消息框暴露数据库、文件系统或密钥存储异常正文。
- 八个用例构造函数及安全密钥 provider 补齐返回类型，并将 `ensure_all_keys` 的既有 `dict[str, bool]` 契约传递到 Application。

## 第二百四十批验证结果

- Setup Wizard HTTP 安全与流程回归 `18 passed`，Application/Domain/集成回归 `52 passed`，覆盖 CSRF、既有安装认证、禁止跳步和正常完整流程。
- Setup Wizard provider、use cases 与 views 增量 mypy 清零，并传播清除 TUI metadata repository 的 7 项过期豁免债务；全仓基线从 `1902 errors / 479 files` 收紧为 `1874 errors / 475 files`，净减少 `28 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十一批

- 按“Prompt 公共执行链成功真实性 × Domain/Application 结果一致性 × 配置唯一真源”收口 Prompt execution use cases。
- 修复所有成功 Prompt 链在返回前重复传入 `total_time_ms`、必然触发 `TypeError` 并被包装成失败的问题；使用 dataclass `replace` 只更新实测总耗时。
- 单步执行不再用 `or` 覆盖显式 `temperature=0`，模型未指定时传递 `None` 交由 AI Provider 当前配置决定，不再硬编码 `gpt-4`。
- 串行、并行、tool calling 和 hybrid 四种模式统一把 Application `ExecutePromptResponse` 转换为 Domain `PromptExecutionResult`；ChainExecutionResult 不再混入错误层级的 DTO。
- 结构化步骤输出缺少 `content` 时按稳定字符串发布，不再由最后一步字典索引触发异常；并行线程池使用运行库受控默认并发上限，不再按数据库步骤数无界扩张 worker。
- 链执行意外异常只在服务端日志保留堆栈，对外返回稳定 `chain_execution_failed`，不再暴露数据库地址、Provider 或 SDK 异常正文。
- 报告链和信号验证链按数据库唯一名称 `investment_report_chain` / `signal_validation_chain` 解析活动配置与真实主键，不再硬编码主键 `1` / `2`。
- AI client factory compatibility provider 改为显式同名 re-export；provider、user、step context、累积输出和序列化结果补齐精确边界类型。

## 第二百四十一批验证结果

- Prompt 核心执行与最终输出回归 `5 passed`，Prompt API、装配、Domain 与初始化一致性回归 `81 passed`，覆盖零温度、成功链返回、结构化末步、异常脱敏和按名称解析链。
- Prompt use cases 增量 mypy 清零，并传播清除 AI Capability、Prompt interface services 与 Terminal chat/service 的隐式 AI factory 属性债务；全仓基线从 `1874 errors / 475 files` 收紧为 `1853 errors / 474 files`，净减少 `21 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十二批

- 按“AI 生成信号真实性 × 证伪逻辑硬约束 × 非法输出失败关闭”收口 Prompt GenerateSignal 链路。
- 删除无论 AI 输出内容都固定发布 `NEUTRAL / 待完善 / MD / 0.5` 的伪信号逻辑；信号字段只从链中真实的结构化 `parsed_output` 获取。
- 有效结果必须同时满足 LONG/SHORT/NEUTRAL 方向、非空投资逻辑、非占位证伪逻辑、有限证伪阈值、canonical 四象限 Regime 和 `[0, 1]` 置信度。
- 链失败、缺少结构化输出、证伪逻辑为“待完善”、非有限/缺失阈值、非法 Regime 或越界置信度统一失败关闭；不再用业务默认值补造可行动信号。
- GenerateSignal 响应新增 `success`、`must_not_use_for_decision` 和稳定 `error_code`；失败时发布空业务字段、零占位置信度并明确禁止用于决策。
- API 对不可行动结果返回 422，不再以 200 表示生成成功；成功结果继续返回 200。
- Chain step 序列化保留真实 `parsed_output` 和步骤错误码，GenerateSignal 不依赖最终自然语言文本反向猜测结构。

## 第二百四十二批验证结果

- GenerateSignal、Prompt execution 与 Prompt API 回归 `28 passed`，Prompt serializer、装配、Domain 和初始化一致性回归 `64 passed`。
- Data DTO、Application、serializer 和 view 增量 mypy 清零且无新增债务；全仓基线保持 `1853 errors / 474 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十三批

- 按“公共资产评分配置正确性 × 资产池查询确定性 × 金融数值失败关闭”收口 Asset Analysis Domain 与 ORM 仓储。
- 权重配置按资产类型降级时只选择无市场条件的默认配置；不再因其他市场条件配置优先级较高而串用危机、极端情绪等专用权重。通用降级同样要求市场条件为空。
- Domain 与 ORM 模型同时拒绝 `NaN`、`Inf` 等非有限权重；仓储在写库前先构造 `WeightConfig` 验证，不再允许非法金融参数绕过比较和总和校验进入数据库。
- `ScoreContext.score_date` 改用实例化时的 `default_factory`，长生命周期进程不再持续沿用模块首次导入日期；活动信号改为协变只读序列，并同步收窄 SignalMatcher 动态属性边界。
- 可投池与评分缓存查询统一规范化资产类型，拒绝空类型、非有限最低分和非正 limit，并在仓储边界限制最大返回 500 条。
- 资产名称解析对输入去空白、统一大写并去重；同一代码存在多条活跃记录时确定性选择最新入池记录，不再依赖数据库无序结果覆盖。
- Asset Repository factory、权重配置、池候选、资产主数据行、日志 payload 与告警解决时间补齐精确类型；公共 repository、model、value object 与 SignalMatcher 的既有 mypy 债务清零。

## 第二百四十三批验证结果

- Asset Analysis Domain、仓储、日志告警、Pool API、多维筛选、模拟交易与 Strategy provider 回归 `75 passed`，覆盖权重条件隔离、非有限权重拒绝、最新名称解析和非法池查询失败关闭。
- Asset Analysis repositories、models、value objects 与 SignalMatcher 增量 mypy 清零；全仓基线从 `1853 errors / 474 files` 收紧为 `1819 errors / 470 files`，净减少 `34 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十四批

- 按“Regime 历史替换原子性 × 决策快照数值真实性 × Navigator 历史错误最小披露”收口 Regime 持久化仓储。
- 范围重算写入前验证起止日期、每条快照所属区间和观测日期唯一性；区间外或重复日期的替换集在删除任何既有历史前失败，不再发生先删后越界写入或唯一键冲突。
- 单条保存改为事务内 `update_or_create`，消除先查后写的竞态窗口；范围替换继续在一个数据库事务内删除并批量写入。
- Regime 快照写入前拒绝未知四象限、`NaN`/`Inf`、越界置信度、负概率、空分布及缺少主导象限的分布，非法决策状态不再进入历史真源。
- 历史分页对非正 limit 和负 offset 返回空结果，不再触发 ORM 负切片异常；最早/最新日期聚合结果在仓储边界收窄为真实日期。
- 活动阈值配置缺少 PMI/CPI 上下界或 PMI 趋势配置时返回不可用，不再将 ORM 可空字段传入计算配置；非有限阈值同样失败关闭。
- Navigator 仓储查询补齐模型与 QuerySet 返回契约；历史查询异常仅在服务端记录堆栈，对外发布稳定 `history_query_failed`，不再复制数据库连接等内部错误。

## 第二百四十四批验证结果

- Regime 仓储、Navigator、编排与 API edge 回归 `28 passed`，覆盖越界/重复替换集不删除历史、非有限快照拒绝、非法分页和 Navigator 异常脱敏。
- Regime repository 与 Navigator history 增量 mypy 清零，并传播清除重算命令的未类型调用债务；全仓基线从 `1819 errors / 470 files` 收紧为 `1799 errors / 468 files`，净减少 `20 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十五批

- 按“Qlib 激活模型唯一性 × Alpha 缓存新鲜度真实性 × QuerySet 公共契约”收口 Alpha 核心 ORM 模型与仓储。
- Qlib 模型注册表新增条件唯一约束，数据库强制全局最多一个 `is_active=True`；迁移先确定性保留最新激活模型并关闭其余历史脏数据，再建立约束。
- 模型激活在事务内锁定并关闭其他 active 记录，随后只更新激活审计字段；不再仅依赖无约束的批量更新承诺唯一性。
- Alpha 缓存新鲜度改用 Django `timezone.localdate()`，与项目配置时区一致；未来日期年龄钳制为零，负 `max_days` 明确拒绝，不再产生负陈旧天数或反向阈值。
- `scores` 即使为空也必须是列表，空字典不能绕过模型验证进入评分缓存。
- Qlib QuerySet 不再覆写 Django `latest(*fields)` 并改变其异常契约；新增语义明确的 `latest_registered()` 返回可空最新注册模型，标准 ORM `latest("created_at")` 保持可用。
- 两个自定义 QuerySet、四个 Alpha ORM 模型和缓存仓储日期/轻量行查询补齐精确类型；TypedDict ORM 投影在仓储边界显式收窄。

## 第二百四十五批验证结果

- Alpha 新增模型不变量回归 `7 passed`，既有 Qlib 注册、激活/回滚和缓存新鲜度回归 `14 passed`；覆盖数据库双 active 拒绝、本地日期、负阈值、空字典 scores 与 Django latest 契约。
- `makemigrations --check --dry-run` 无漂移；Alpha models 与 repositories 增量 mypy 清零。全仓基线从 `1799 errors / 468 files` 收紧为 `1776 errors / 466 files`，净减少 `23 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十六批

- 按“Terminal/Agent 输入结构可靠性 × 内部异常最小披露 × 响应字段真实性”收口 Terminal serializers 与 chat API。
- Terminal chat 的 `context` 从任意 JSON 收紧为对象；数组等异常结构在进入 DTO 前返回 400，不再由 `dict(...)` 转换触发 500。
- 活跃 chat 与 approval 请求使用严格字段校验，未知字段不再被 DRF 静默忽略；`provider_ref` 与兼容别名 `provider_name` 同时提交时明确拒绝，避免优先级不透明。
- 消息、session、provider 和 model 字段增加技术性长度上限；超大消息在进入 Agent/Provider 前被拒绝。
- provider reference 从任意 JSON 收紧为字符串边界，同时继续兼容数字输入由 DRF 规范化为字符串。
- 非流式 Agent 异常固定返回 `terminal_agent_unavailable`，SSE 异常固定发布 `terminal_agent_stream_failed`；数据库地址、Provider SDK 和其他内部异常正文只进入服务端日志。
- `param_count` 改为真实 `SerializerMethodField`，始终按 parameters 计算，不再信任调用方或缺省丢失；命令响应字段统一发布真实 `prompt_template_id`。
- 全部 Terminal serializer 补齐 DRF 泛型、字段校验器和 schema decorator 类型；审计列表在 DRF many 边界局部收窄。

## 第二百四十六批验证结果

- Terminal serializer 与 API edge 回归 `9 passed`，覆盖计算参数数量、超长消息、非法 context、未知字段、Provider 别名冲突和普通/SSE 异常脱敏。
- 固定 Terminal/TUI 最小回归包全部通过：TUI Workbench `197 passed`、Terminal Agent `11 passed`、SDK client `22 passed`、SSL redirect `2 passed`。
- Terminal serializers 与 API views 增量 mypy 清零；全仓基线从 `1776 errors / 466 files` 收紧为 `1756 errors / 465 files`，净减少 `20 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十七批

- 按“公开分享访问上限原子性 × 快照版本并发一致性 × 外部请求失败关闭”收口 Share serializer 与 repository。
- 访问计数改为单条条件更新：仅 active、未过期且尚未达到 `max_access_count` 的链接才能原子消费一次访问；使用数据库 `F` 表达式避免并发丢计数或突破上限。
- Public access 与 snapshot API 必须成功消费访问额度后才返回数据；并发竞争失败、撤销、过期或达到上限统一返回稳定 403 `access_limit_reached`，同时记录拒绝日志。
- 快照创建在事务内锁定所属分享链接，再读取最新版本并创建下一版本；同一链接的并发快照不再共享“先查再加一”的无锁窗口。
- 创建、更新和公开密码请求启用严格字段校验；`owner_id` 等未知或越权注入字段不再被 DRF 静默忽略。
- 创建 serializer 缺少已认证 request/owner 时失败关闭，不再跳过账户归属校验；账户必须由 Application gateway 证明属于当前用户。
- Share ModelSerializer、公开 payload、可见性映射、账户/决策 gateway、免责声明和 ORM QuerySet 全部补齐精确类型；Infrastructure 对 Application Protocol 的返回在边界显式收窄。

## 第二百四十七批验证结果

- Share repository、API edge、Domain 与依赖边界回归 `27 passed`，覆盖访问额度不超限、撤销链接拒绝、快照版本递增、未知字段和缺失所有者身份失败关闭、公开字段过滤。
- Share serializers 与 repositories 增量 mypy 清零且无跨层回归；全仓基线从 `1756 errors / 465 files` 收紧为 `1726 errors / 463 files`，净减少 `30 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十八批

- 按“首页宏观状态失败关闭 × 阻断行动不可执行 × 外部数值边界可靠性”收口 Dashboard Regime 上下文。
- Regime、Pulse 或联合行动建议缺失时明确发布不可用于决策状态；不再把缺失 Pulse 伪装为 `moderate`，也不再把缺失行动建议标成未阻断。
- 联合行动建议已阻断时清空资产权重、风险预算和单仓上限；Regime 资产指引不再绕过阻断状态回填可执行风险预算。
- 风险预算、仓位上限、权重和置信度统一验证为有限且位于 `[0, 1]` 的比例；非法值不再作为百分比进入首页。
- 市场温度分数、变化值和组件贡献统一使用安全数值解析；`NaN`、`Inf`、非法字符串、未知温度档位及异常组件结构失败关闭，不再触发比较或排序异常。
- 无转折预警时关闭浏览器通知开关；不再发布“已启用但 payload 为空”的矛盾状态。
- Dashboard Macro 组件、DTO、Domain entity、市场温度 payload 与页面 context 补齐精确类型，消除裸容器和未类型函数边界。

## 第二百四十八批验证结果

- Dashboard 失败关闭新增回归与结构测试 `8 passed`，Dashboard 主回归 `47 passed`；覆盖缺失组件、阻断行动、非有限分数、非法市场温度变化值和空通知。
- Dashboard Regime context 增量 mypy 清零；全仓基线从 `1726 errors / 463 files` 收紧为 `1709 errors / 462 files`，净减少 `17 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百四十九批

- 按“Alpha 手动刷新异常最小披露 × 同步/异步刷新响应契约 × 用户入口类型完整性”收口 Dashboard Alpha 股票交互。
- 手动刷新意外异常只在服务端日志保留堆栈，对外返回稳定 `alpha_refresh_failed`；数据库连接、Provider SDK 和任务异常正文不再进入响应。
- 异常响应明确发布 `must_not_use_for_decision=True`，调用方不能把刷新失败误认作新评分结果。
- 刷新失败后的锁释放增加独立异常保护；清理锁失败只记录服务端日志，不再覆盖原始失败响应。
- Alpha 排名页、手动刷新、同步推理、股票列表、因子面板和退出观察面板补齐精确请求、日期、组合池与 HTTP 响应类型。
- 动态 Dashboard compatibility facade 在模块边界显式收窄，冲突响应转换为正式 HTTP 契约，不再传播未类型调用。

## 第二百四十九批验证结果

- Dashboard Alpha 手动刷新局部回归 `10 passed`，完整 Alpha views 回归 `48 passed`；覆盖同步/异步刷新、重复任务锁、账户专属池和内部异常脱敏。
- Dashboard Alpha stock views 增量 mypy 清零；全仓基线从 `1709 errors / 462 files` 收紧为 `1695 errors / 461 files`，净减少 `14 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十批

- 按“资产配置图数值真实性 × 非法持仓数据失败关闭 × 组合入口类型完整性”收口 Dashboard Portfolio views。
- 资产配置聚合统一通过安全数值解析读取持仓市值，拒绝缺失、非法字符串、`NaN`、`Inf` 和负市值；不再让异常金融数值进入 JSON 或图表比例。
- 任一持仓市值无效时，配置图整体返回稳定 503 `allocation_data_unavailable` 和 `must_not_use_for_decision=True`；不再静默忽略问题持仓并发布低估的部分资产配置。
- 资产类别仅接受非空字符串，缺失或异常类别统一进入“其他”，避免不可哈希动态值破坏聚合。
- 持仓详情、列表、JSON、配置图和业绩图入口补齐精确 HttpRequest/HttpResponse 类型；动态 Dashboard facade 边界显式收窄。

## 第二百五十批验证结果

- Dashboard Portfolio 数值边界回归 `7 passed`，Dashboard 全模块及相关组件回归 `115 passed`；覆盖正常聚合、字符串数值、缺失/非法/非有限/负市值和配置图失败关闭。
- Dashboard Portfolio views 增量 mypy 清零；全仓基线从 `1695 errors / 461 files` 收紧为 `1682 errors / 460 files`，净减少 `13 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十一批

- 按“Alpha 指标首页可见性 × 动态指标结构失败关闭 × IC 查询资源上限”收口 Dashboard Alpha metrics views。
- 指标查询统一返回强类型 `AlphaVisualizationData`；Provider 状态、覆盖率、IC 趋势及元数据在进入页面/API 前分别收窄为字符串键映射或 JSON 行列表。
- 修复 Dashboard 上下文只接受 Mapping、把正常 dataclass 和降级对象吞成空字典的问题；DTO 现在通过受控公开字段归一化，首页可以稳定读取 Provider、覆盖率和 IC 状态。
- Provider、覆盖率或 IC 元数据结构异常时整体降级到明确 fallback 数据；不再以默认 `available/live` 掩盖畸形查询结果。
- IC 趋势查询天数拒绝布尔值、动态容器、非正数和超过 3650 天的无界请求，避免异常或超大历史查询进入 Application。
- 三个指标 API handler、query factory Protocol 和动态 payload 补齐精确类型。

## 第二百五十一批验证结果

- Alpha metrics 映射契约与资源边界回归 `3 passed`，首页兼容回归 `1 passed`，Dashboard 全模块及相关组件回归 `118 passed`。
- Dashboard Alpha metrics views 增量 mypy 清零，Dashboard Alpha context 保持零回归；全仓基线从 `1682 errors / 460 files` 收紧为 `1669 errors / 459 files`，净减少 `13 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十二批

- 按“Alpha 历史用户隔离前置条件 × 非法详情标识失败关闭 × 历史入口类型完整性”收口 Dashboard Alpha history views。
- 历史页面、列表和详情在调用 Application 前验证当前认证主体具有持久化正整数用户 ID；匿名、未保存或异常身份不再以可空 ID进入用户隔离查询。
- 历史详情在访问仓储前拒绝非正 `run_id`，返回稳定 400；不再对无意义主键执行查询并混同为“记录不存在”。
- 正整数参数解析拒绝布尔值和动态容器，避免 Python 隐式把 `True` 当作主键 `1`。
- Alpha Homepage query factory、Dashboard compatibility facade 以及三个历史 handler 补齐精确类型；动态 singleton 调用在 Callable 边界显式收窄。

## 第二百五十二批验证结果

- Alpha history 局部回归 `4 passed`，Dashboard 全模块及相关组件回归 `119 passed`；覆盖历史筛选、用户隔离参数、详情快照和非法 run ID 查询前拒绝。
- Dashboard Alpha history views 增量 mypy 清零；全仓基线从 `1669 errors / 459 files` 收紧为 `1657 errors / 458 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十三批

- 按“回测所有者隔离 × 创建归属原子性 × 失败响应真实性”收口 Backtest 公共页面、API、Application 与 Repository。
- 回测列表、详情、统计、删除和重跑检查统一传递当前认证用户 ID；普通用户不能再读取、统计或删除其他用户及系统级回测。
- 页面列表、创建和详情增加登录保护，详情查询按所有者过滤；独立统计 API 改用 DRF 认证，Token/API 调用与 Session 调用均保持受保护。
- 普通回测创建在首次数据库写入时直接保存 `user_id`；不再先创建无主记录。Decision replay 同样改为原子绑定所有者，不再创建后二次更新。
- Repository 的单条查询、状态列表、全部列表、删除和统计新增可选 owner scope；收益率最大值、最小值和均值也使用同一用户过滤后的 QuerySet。
- 修复 ViewSet create 未移除 serializer 默认 `run_async=False`、导致同步回测构造请求时出现未知参数并失败的问题；参数现在在统一 Application boundary 清理。
- 回测执行失败不再把数据库、Provider、PIT 或引擎异常原文返回客户端；统一发布稳定 `backtest_execution_failed`。Decision replay 失败同样返回稳定错误码。
- 尚未实现的 rerun 不再返回“Rerun initiated”虚假成功，改为明确 501 `backtest_rerun_not_implemented`。
- limit、path ID 和认证用户 ID 统一要求正整数，列表 limit 上限为 500；非法参数在进入 Application/ORM 前返回 400。

## 第二百五十三批验证结果

- Backtest API 安全与契约回归 `9 passed`，Application/Repository 定向回归 `27 passed`，API、Domain 与执行扩展回归 `41 passed`。
- 覆盖跨用户列表/详情/删除隔离、创建 owner 传递、内部异常脱敏、重跑非虚假成功、非法参数、PIT 失败关闭和完整执行链。
- Backtest views、use cases 与 decision replay 增量 mypy 清零；全仓基线从 `1657 errors / 458 files` 收紧为 `1636 errors / 455 files`，净减少 `21 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十四批

- 按“决策执行事件负载完整性 × 跨模型写入失败关闭 × Provider 边界类型化”收口 Events decision execution handlers。
- `request_id`、单个/批量 `candidate_id` 统一要求非空且长度受限的字符串；批量候选只要包含一个异常元素，整条事件在任何写入前失败关闭，不再发生部分候选已更新、后续候选才报错。
- `execution_ref` 只接受字符串键 JSON object；数组、字符串或非字符串键不再进入 DecisionRequest 执行引用。失败事件的 `error_message` 同样拒绝动态容器。
- Approved、Rejected、Executed 和 ExecutionFailed 四类 handler 统一使用已验证 payload；缺失或畸形请求标识不再通过 truthy/隐式转换进入 Repository。
- 三个默认 Repository provider 通过精确 Callable/Protocol boundary 组装；四个 handler 构造函数补齐 event bus 和返回类型。
- 修正故障注入健康检查“只启动空 EventBus 却声称已初始化”的测试前置条件；测试现在通过正式 `EventBusInitializer` 注册关键 handler 后再验收。

## 第二百五十四批验证结果

- Decision execution handlers 与 EventBus 初始化回归 `24 passed`，新增畸形候选集合、非法 execution_ref 和异常 candidate_id 失败关闭覆盖；健康检查隔离回归 `1 passed`。
- Decision execution handlers 增量 mypy 清零；全仓基线从 `1636 errors / 455 files` 收紧为 `1626 errors / 454 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十五批

- 按“Filter 页面 GET 无副作用 × 指标/滤波器严格选择 × 图表金融数值真实性”收口 Filter dashboard view。
- 页面增加登录保护；匿名访问不能再触发指标查询、滤波计算或结果写入。
- 删除页面层 legacy Repository compatibility wrapper，直接使用 Application provider 暴露的正式仓储契约；Application UseCase 不再收到错误的 wrapper 类型。
- 可用指标完全来自数据库；没有指标时明确提示先配置数据中心，不再硬编码 `CN_PMI` 作为虚假默认。请求的指标不在当前可用集合时失败关闭。
- `filter_type` 只接受 `hp` / `kalman`；未知值不再静默映射为 Kalman。
- 页面 GET 在缺少已保存结果时只执行 `save_results=False` 的只读回退计算；不再因打开页面删除/重写滤波结果或 Kalman 状态。
- 图表输出要求 dates、原值、滤波值和 slope 长度一致，并拒绝 `NaN` / `Inf`；JSON 序列化禁用非标准非有限值。
- Repository、UseCase 或图表异常只在服务端记录堆栈，对用户返回稳定错误文案，不再展示数据库、数据源或算法异常正文。

## 第二百五十五批验证结果

- Filter 页面与 API 回归 `15 passed`，图表数值/序列边界回归 `7 passed`；覆盖认证、未知滤波器、GET 不持久化、异常脱敏、NaN/Inf 和错位序列。
- Filter dashboard view 增量 mypy 清零；全仓基线从 `1626 errors / 454 files` 收紧为 `1614 errors / 453 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十六批

- 按“AI 政策分类失败关闭 × 非有限金融数值拒绝 × Provider 异常最小披露”收口 Policy AI classifier。
- AI 响应无法解析为 JSON object 时不再伪造 `other`、`confidence=0.3` 并返回成功；统一返回稳定失败结果，避免虚假政策分类进入审核队列。
- `info_category`、`risk_impact` 和可选 `policy_level` 必须匹配 Domain 枚举；未知枚举不再被默认值或忽略逻辑掩盖。
- `confidence` 必须是 `[0, 1]` 内有限数值；可选情绪分数一旦提供，必须是 `[-1, 1]` 内有限数值。`NaN`、`Inf`、非法字符串和越界值全部失败关闭。
- `structured_data` 必须是 JSON object；字符串字段、字符串列表和受影响行业/股票等动态数据在构造 Domain entity 前完成结构收窄。
- 自动通过和拒绝阈值限制在 `[0, 1]`，且拒绝阈值必须低于通过阈值；异常运行时配置回退到安全默认阈值。
- Provider 失败与解析失败不再向调用方返回 SDK/网络异常正文或原始 AI 输出；仅发布稳定错误文案和机器错误码，详细异常保留在服务端日志。
- AI Provider、usage repository、failover helper compatibility factory 和使用日志入口补齐返回类型，JSON 解析结果在 Infrastructure 边界显式收窄。

## 第二百五十六批验证结果

- Policy adapter 与 AI failover 定向回归 `14 passed`；覆盖 Provider 异常脱敏、无效 JSON、未知枚举、异常容器、非字符串列表、`NaN`/`Inf` 和越界置信度失败关闭。
- Policy AI classifier 增量 mypy 清零；全仓基线从 `1614 errors / 453 files` 收紧为 `1603 errors / 452 files`，净减少 `11 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十七批

- 按“对冲金融规则归位 × 组合所有者隔离 × 无有效行情零写入”收口 Policy hedging calculation、execution 与 effectiveness analysis。
- 对冲比例、工具代码、工具类型和估算费率从 Application 硬编码迁出；Domain 只接受外部配置提供的 `HedgePolicyConfig`，不再内置过期的 `IF2312` 合约或固定费率。
- 对冲计算金融逻辑迁入纯 Domain；政策档位必须匹配正式枚举且不能处于待分类状态，缺少唯一规则时失败关闭。
- 组合总值必须为有限正数，权益敞口必须为有限非负数且不超过组合总值；比例和成本费率同样执行有限值及范围校验。
- 对冲执行和效果分析都要求正整数 `user_id`，并在读取行情、查询对冲记录或写入前通过 Account-owned repository 验证组合归属；跨用户访问统一拒绝。
- 行情缺失、非正、`NaN` 或 `Inf` 时不再创建 `pending` 记录并返回带当前时间的伪执行结果；现在保持零写入并明确失败。
- 对冲记录持久化真实政策档位与配置提供的工具类型；执行结果与数据库记录共用同一 `executed_at`，不再产生两个不同时间点。
- Beta 回写同时按 `hedge_id + portfolio_id` 限定，避免只凭全局主键更新；回写失败不再被当成成功分析。
- 成本、收益、Beta 和对冲比例统一拒绝非有限值，成本额外要求非负；仓位数据缺失时不再伪造 `beta_before=beta_after=1.0`。
- Application 的 Account、Realtime 与 Hedge repository 边界改为精确 Protocol/TypedDict，Hedge repository 的 Decimal/datetime 参数补齐类型。

## 第二百五十七批验证结果

- Policy 全模块回归 `155 passed`，对冲定向回归 `7 passed`；覆盖配置驱动计算、未知政策/非法敞口、跨用户执行与分析拒绝、无效行情零写入、非有限成本失败关闭和 portfolio-scoped Beta 回写。
- Policy hedging Application 与 repository 增量 mypy 清零；全仓基线从 `1603 errors / 452 files` 收紧为 `1592 errors / 450 files`，净减少 `11 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十八批

- 按“通知送达状态真实性 × 批量收件人隔离 × 站内信事务一致性”收口 Policy notification Domain contract 与 Infrastructure service。
- 邮件服务禁用、无有效收件人、未配置 `EMAIL_BACKEND`、SMTP 异常或后端未确认送达时统一返回失败；不再降级到日志后把“仅写日志”伪装成邮件成功。
- 邮件批量发送不再把所有内容合并后发给收件人并集；每条消息保持独立收件人集合，避免定向政策内容跨用户泄露。
- 通知日志只记录渠道、优先级和收件人数；标题、正文、邮箱/用户名及 Provider 异常正文不再写入普通日志。
- 站内信单条定向通知使用一次 `bulk_create`，批量消息在同一事务内统一持久化；任一数据库失败时整批返回零成功，不再留下部分通知。
- 站内信 Manager 改为构造注入，Factory 统一使用模块级 settings；避免只读 `_default_manager` 测试替换和内部重复 import 绕过配置注入。
- `NotificationMessage` 改为 frozen Domain value object，严格验证标题、正文、渠道、正式优先级和收件人；收件人去空白并去重，提供了定向对象但无有效收件人时不再误转为全局通知。
- P2 告警优先级从模型不支持的 `warning` 统一为 `high`；通用 `warning/warn/error` 在 Infrastructure 边界映射到正式优先级。
- 未配置任何通知渠道时不再返回成功；SLA 数量拒绝布尔值和负数，档位变更摘要要求完整非空字符串字段。
- Batch result、transition payload、消息 metadata、服务方法和 Factory reset 补齐精确 TypedDict/容器/返回类型。

## 第二百五十八批验证结果

- Policy 通知定向回归 `40 passed`，Policy 全模块回归 `165 passed`；覆盖 SMTP 失败、缺少收件人、内容日志脱敏、批量收件人隔离、站内批量零部分成功、消息契约、无渠道告警和非法 SLA/档位变更。
- Policy notification Domain interfaces 与 Infrastructure service 增量 mypy 清零；全仓基线从 `1592 errors / 450 files` 收紧为 `1578 errors / 448 files`，净减少 `14 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百五十九批

- 按“人工审核双重授权 × 审核写入审计完整性 × API 输入与异常最小披露”收口 Policy event/audit Application、Repository 与 API。
- 审核队列、单条审核、批量审核和自动分配 API 全部改为 `IsAdminUser`；普通登录用户不再能读取审核队列、改变政策审核状态或触发全局任务分配。
- Application 再次要求审核主体具有持久化正整数 ID、active 与 staff 状态；不依赖 Interface 权限作为唯一防线。
- Repository 在事务内锁定“仍为 pending 且明确分配给当前审核人”的队列项；未分配、分配给他人、已完成或并发失效的条目统一拒绝，不再仅凭全局 `policy_log_id` 审核。
- 审核状态更新与 `GateActionAuditLog` 写入、队列删除处于同一事务；审计日志失败时政策状态和队列完整回滚。
- 审核日志记录操作前后状态、operator、approve/reject action 和原因；旧审核入口不再绕开正式操作审计链。
- 新增严格 DRF serializers：审核状态/优先级、limit、approved、notes、modifications、批量 ID 数量/唯一性和自动分配上限在进入 Application/Repository 前验证，未知 mutation 字段拒绝。
- 批量审核限制为 1-200 个唯一正整数 ID，并真实发布部分失败状态；不再无条件返回顶层 `success=True`。
- API 的 ValidationError 返回稳定 400，内部数据库/Repository 异常返回稳定机器错误码；异常正文不再进入客户端响应。
- Policy event 创建在保存前完成纯规则计算，避免已写入事件却因后续规则异常返回整体失败；当前政策查询、创建和更新失败响应移除数据库/Provider 异常正文。
- Policy event DTO 使用 `default_factory`，更新路径增加正式事件字段和正整数 ID 校验；Generic history 空集合补齐精确实体类型。

## 第二百五十九批验证结果

- Policy 审核、Repository、事件与 API 安全定向回归 `21 passed`，Policy 全模块回归 `172 passed`；覆盖普通用户 403、非法请求写入前 400、内部异常脱敏、跨审核人拒绝、审计日志生成及审计写入失败原子回滚。
- Policy event/audit Application 与 audit API 增量 mypy 清零；全仓基线从 `1578 errors / 448 files` 收紧为 `1565 errors / 445 files`，净减少 `13 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十批

- 按“事件入口失败关闭 × 查询契约无歧义 × 内部异常最小披露”收口 Events serializers 与 API views。
- 发布、查询、订阅和受控重放请求统一拒绝未声明字段；非对象请求不再进入字段解析。
- 管理员发布入口不再允许主动创建 `UNKNOWN` 事件；`UNKNOWN` 继续仅作为未知外部事件的安全归类值，避免人为发布不可解释的业务事件。
- 事件 payload 与 metadata 必须是可序列化的有限 JSON object，分别限制为 256 KiB 和 64 KiB；`NaN`、`Inf`、动态对象和超限负载在进入 Application/Event Store 前拒绝。
- 查询接口拒绝同时提供 `event_type` 与 `event_types`、空集合、重复事件类型、反向时间窗口、空白或超长 correlation ID，避免歧义条件进入仓储。
- 受控重放拒绝 `UNKNOWN` 和反向时间窗口；提交前确认认证主体具有持久化主键，不再把可空用户 ID 传给重放审计链。
- 发布、查询、指标、总线状态和重放异常统一返回稳定错误文案；UseCase、Provider、注册目标和底层异常正文不再进入客户端响应，视图日志仅记录异常类型。
- Events 请求/响应 serializers、APIView handler 和 DTO 转换边界补齐精确泛型、请求与返回类型。

## 第二百六十批验证结果

- Events Domain、受控重放、API 边界与集成契约回归 `82 passed`；覆盖未知字段、歧义查询、反向时间窗口、`UNKNOWN` 发布、非有限 JSON、权限、幂等发布、重放和内部异常脱敏。
- Events serializers 与 views 增量 mypy 清零；全仓基线从 `1565 errors / 445 files` 收紧为 `1546 errors / 443 files`，净减少 `19 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十一批

- 按“回测金融输入真实性 × 未知参数失败关闭 × 请求边界类型完整性”收口 Backtest serializers。
- 回测配置、运行和决策重放请求统一拒绝未声明字段；拼错或过期参数不再被 DRF 静默丢弃后按默认值执行。
- 本金和交易成本字段拒绝布尔值、`NaN` 与 `Inf`；本金必须严格大于零，交易成本保持 Domain 已有的有限非负规则，不在 Interface 新增业务费率或默认值。
- 决策重放 `portfolio_id` 必须为正整数，初始本金必须是有限正 Decimal；无效标识和金额在进入 Application 与组合查询前拒绝。
- PIT verified 的 manifest、配置哈希、代码提交、引擎版本、研究试验和决策快照要求统一由共享校验函数执行，避免配置与运行入口规则漂移。
- 动态 ORM model、请求 serializers、统计响应和三个 validate handler 补齐精确 Model、Application DTO、泛型容器与返回类型。

## 第二百六十一批验证结果

- Backtest API 边界回归 `16 passed`，Backtest API、Application、Domain、tasks 与报告回归 `77 passed`；覆盖未知字段零执行、零本金、布尔/非有限金融值、非正组合 ID、所有者隔离、失败脱敏和执行配置。
- Backtest serializers 增量 mypy 清零，调用 views 保持零回归；全仓基线从 `1546 errors / 443 files` 收紧为 `1535 errors / 442 files`，净减少 `11 errors / 1 file`。
- Django system check、架构边界、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十二批

- 按“滤波参数金融有效性 × API 请求失败关闭 × Provider 异常最小披露”收口 Filter Domain、Application、serializers 与 API views。
- 应用滤波、读取结果、对比和配置更新请求统一拒绝未声明字段；拼错的 lambda、方差或查询参数不再被 DRF 静默忽略。
- 三类滤波请求统一拒绝反向日期窗口；Compare limit 收紧到 1-1000，和 Apply 的资源上限保持一致。
- HP lambda、Kalman 方差和配置写入值拒绝布尔、负数、`NaN` 与 `Inf`；观测方差必须严格大于零，避免零噪声参数进入矩阵更新。
- Domain 的 `HPFilterParams`、`KalmanFilterParams` 和 `FilterResult` 增加有限值不变量；即使历史数据库配置或非 API 调用绕过 serializer，异常参数和非有限滤波结果仍会失败关闭。
- 配置 PATCH 拒绝空请求和未知字段；配置路径 indicator code 在 ORM 前执行非空和 50 字符长度校验。
- Apply、Get 和 Compare 的无数据、查询、计算与比较失败发布稳定机器错误码；数据库、Provider 和算法异常正文不再进入客户端响应，视图按失败类型返回 404、400 或 500。
- Filter 请求/响应 serializers、有限浮点字段、日期验证和配置响应补齐精确泛型与返回类型。

## 第二百六十二批验证结果

- Filter API、Application、Domain 与 Dashboard 回归 `75 passed`；覆盖未知字段零执行、反向日期、Compare 资源上限、空/非法配置更新、非有限参数、历史坏配置、Domain 结果不变量和异常脱敏。
- Filter serializers 增量 mypy 清零，Application、Domain 与 API views 保持零回归；全仓基线从 `1535 errors / 442 files` 收紧为 `1523 errors / 441 files`，净减少 `12 errors / 1 file`。
- Django system check、架构边界、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十三批

- 按“板块排名权重真实性 × 非有限输入失败关闭 × Provider 异常最小披露”收口 Sector Domain、Application、serializers 与 API views。
- 修复 `rank_sectors_by_regime` 内局部板块适配值覆盖请求参数 `regime_weight` 的错误；此前总分实际使用板块适配值的平方，请求中的 Regime 权重未生效，现在三项请求权重按原始契约参与总分。
- 三项评分权重统一要求有限、位于 `[0, 1]` 且总和为 1；`NaN` 不再利用浮点比较特性绕过校验，布尔、无穷、负值和错误总和全部失败关闭。
- 持久化板块 Regime 适配值要求有限且位于 `[0, 1]`；评分归一化拒绝非有限输入，历史坏配置和异常行情不再生成可排序的伪分数。
- Analyze、Rotation、Score 和数据更新请求统一拒绝未知字段；Regime 使用正式枚举，数据更新拒绝反向日期。
- 数据更新先解析并验证完整日期窗口，再调用 Provider 或保存分类；仅提供 end date 时按该日期向前取一年，未来 start date 不再在部分分类写入后才失败。
- 板块基准收益率拒绝布尔、`NaN` 与 `Inf`，无效 Provider 数据进入明确 fallback；Provider 异常日志只记录异常类型。
- 分析和数据更新异常发布稳定机器错误码；数据库、行情 Provider、DataFrame 和适配器异常正文不再进入 API 响应。
- Application 改用 Sector repository/adapter Protocol，不再依赖 concrete repository 类型；市场收益 gateway、UseCase、serializers 和 views 补齐精确泛型、请求、容器与返回类型。

## 第二百六十三批验证结果

- Sector API、Application、Domain、Adapter 与集成回归 `80 passed`；覆盖权重公式、`NaN/Inf`、异常适配值、未知 Regime/字段、反向日期、未来日期零 Provider/写入、行情 fallback 和异常脱敏。
- Sector market gateway、use cases、serializers 与 views 增量 mypy 清零；全仓基线从 `1523 errors / 441 files` 收紧为 `1499 errors / 437 files`，净减少 `24 errors / 4 files`。
- Django system check、架构边界、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十四批

- 按“情绪金融数值真实性 × API 查询失败关闭 × AI/异常内容最小披露”收口 Sentiment Domain、Application、serializers 与 API views。
- 情绪评分、综合指数、置信度和行业情绪统一拒绝布尔、`NaN` 与 `Inf`；指数置信度要求位于 `[0, 1]`，行业情绪要求位于 `[-3, 3]`，来源计数不得为负。
- AI 返回缺失、畸形或非有限评分时不再伪造“中性 0 分”成功结果；本次分析明确标记为不可用，避免错误中性数据进入缓存、日志和决策链。
- AI 失败告警不再持久化原始文本片段、Provider 错误正文或凭据相关信息；失败结果、API 响应和页面上下文仅发布稳定文案与机器错误码。
- 情绪指数权重要求有限、非负且总和为 1；输入评分要求位于 Domain 正式区间，历史坏配置或异常数据不再生成可发布指数。
- 单条、批量、单日、日期范围和最近天数请求统一使用严格 serializers；未知字段不再被静默丢弃，空批次、去空白后重复文本、倒置日期和 `days` 范围外参数在调用 Application/Repository 前拒绝。
- 最近天数非法值不再静默改为 30 天；客户端收到 400 并可修正请求，避免实际查询窗口与用户意图不一致。
- `drf-spectacular` schema 装饰器通过保持身份签名的类型包装器接入，APIView handler 同时满足 Django 基类覆盖契约与完整 mypy 门禁。

## 第二百六十四批验证结果

- Sentiment API、Application、Domain、页面与实体回归 `129 passed`，新增边界小回归 `41 passed`；覆盖未知字段、重复付费工作、倒置日期、非法 days、畸形 AI 输出、`NaN/Inf`、异常配置与错误脱敏。
- Sentiment serializers 与 views 增量 mypy 清零；全仓基线从 `1499 errors / 437 files` 收紧为 `1482 errors / 435 files`，净减少 `17 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十五批

- 按“Dashboard 用户配置输入失败关闭 × 布局标识唯一性 × Serializer 类型契约”收口 Dashboard serializers。
- 用户偏好、卡片可见性、卡片折叠和强制刷新四类 mutation 请求统一拒绝未知字段；拼错或过期字段不再被 DRF 静默丢弃后返回表面成功。
- 用户偏好空请求明确拒绝；刷新周期要求正整数，避免无操作写入和非正定时周期进入持久化边界。
- 隐藏卡片、折叠卡片、卡片排序和指定刷新组件统一拒绝重复标识，避免同一卡片或组件在一次请求中形成歧义状态。
- 9 个 Domain/Service result serializer、4 个动态 ModelSerializer 和 5 个请求/响应 serializer 补齐精确泛型；动态 Django model 仅在 ORM serializer 边界收窄为 `Model`。

## 第二百六十五批验证结果

- Dashboard serializer 新契约回归 `11 passed`；Dashboard API、页面结构与回归护栏组合包 `37 passed, 1 failed`。
- 唯一失败为既有 Dashboard Alpha 历史写入在 `alpha_score=None` 时触发 NOT NULL，随后污染测试事务；失败链不经过本批 serializers，留作下一独立高优先级批次处理。
- Dashboard serializers 增量 mypy 清零；全仓基线从 `1482 errors / 435 files` 收紧为 `1464 errors / 434 files`，净减少 `18 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十六批

- 按“Dashboard Alpha 历史写入原子性 × 失败隔离 × 既有快照保全”修复批次 265 回归中暴露的事务污染。
- `replace_snapshots` 在 Infrastructure Repository 内使用独立原子 savepoint；删除旧快照与批量创建新快照成为同一事务单元。
- 任一新快照违反数据库契约时，局部事务完整回滚并恢复旧快照；调用方捕获异常后，外层 Dashboard 请求或测试事务仍可继续查询，不再连锁触发 `TransactionManagementError` 和页面 500。
- Application 的既有失败降级语义保持不变；本批不伪造缺失 Alpha 分数，也不改变推荐结果，只隔离失败持久化副作用。

## 第二百六十六批验证结果

- Alpha 历史原子替换测试与此前失败的 Dashboard 真实页面回归 `2 passed`；覆盖坏快照写入、旧快照保留、外层事务可继续查询和待处理队列正常渲染。
- Dashboard history repository 增量 mypy 保持清零；本批为运行时安全修复，全仓基线保持 `1464 errors / 434 files`，未虚报债务下降。
- Django system check、架构 delta、改动文件 Ruff、Black、isort 与增量 mypy 通过。

## 第二百六十七批

- 按“Alpha 回测持仓守恒 × PIT 信号完整性 × 最终清算口径一致”收口 Backtest Alpha Domain 与执行用例。
- 修复卖出路径先从 portfolio 删除、后读取退出价格的问题；持仓退出行情缺失、非正或非有限时整次回测失败关闭，不再让仓位凭空消失且没有现金回款。
- 持仓估值和最终清算同样要求有限正价格；候选股票买入行情无效时保持零交易，已持有资产行情无效时不发布不完整收益结果。
- 最终持仓改为持有到请求 `end_date` 后清算，不再在最后一次再平衡日提前退出；最终卖出佣金、最终卖出笔数、真实持有天数和末端净值统一进入结果。
- 净值曲线末点与最终资金保持一致；`total_rebalances` 统计实际执行记录而非计划日期，`avg_holding_period` 使用逐笔真实持有天数，不再固定报告 30 天。
- Alpha 分数要求有限且位于 `[-1, 1]`，股票代码非空；`asof_date` 必须存在且不晚于再平衡日，`intended_trade_date` 必须与交易日一致，缺失或前视信号不得进入历史决策。
- 初始资金必须有限正数，评分阈值、最大持仓数、佣金率和滑点率执行正式范围校验；起止基准价格缺失、非正或非有限时不再伪造零基准收益。
- Alpha service、score/result 和 repository 改为精确 Protocol；可选服务初始化不再用布尔值混入依赖类型，异常响应与持久化失败状态统一脱敏。

## 第二百六十七批验证结果

- Alpha 回测金融不变量与 Backtest Domain 回归 `29 passed`，Alpha 回测集成与 Backtest API 回归 `19 passed`；覆盖资本/费率边界、PIT、缺失退出价、双边佣金、最终净值、服务不可用和异常脱敏。
- `alpha_backtest.py` 增量 mypy 清零；全仓基线从 `1464 errors / 434 files` 收紧为 `1452 errors / 433 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十八批

- 按“通用股票回测持仓守恒 × 真实成交表现 × 日历与风险配置可信”收口 `StockSelectionBacktestEngine`，并同步保持 Alpha 子类契约一致。
- 修复通用引擎与 Alpha 相同的先删仓后读退出行情问题；持仓退出、估值或最终清算价格缺失、非正或非有限时失败关闭，不再发布资产凭空消失的收益结果。
- 最终持仓统一持有到请求结束日，双边佣金、最终清算交易数、实际再平衡次数和终端净值进入同一结果口径。
- 内部逐笔表现记录改为精确 TypedDict，持久保留真实入场/退出日期、价格、收益率和持有天数；删除固定持有 30 天、固定退出价 100 和用 entry price 冒充 entry date 的伪造整理逻辑。
- 配置统一验证起止日期、有限正本金、正持仓上限、正式权重方法、佣金/滑点和年化无风险利率；夏普计算从配置读取无风险利率，不再在算法内硬编码 3%。
- 月度与季度再平衡使用日历安全的月份推进；1 月 31 日等月末日期会按目标月末收敛，不再因不存在的 2 月 31 日抛错。
- 缺失 Regime、缺失对应筛选规则或全程无可执行观测时失败关闭，不再默认假设 Recovery 或发布零收益的伪有效回测。
- 市值权重只接受有限正市值；风险指标在仅有一个收益观测时返回零波动，不再调用样本标准差触发异常。

## 第二百六十八批验证结果

- 通用/Alpha 回测金融不变量与 Backtest Domain 回归 `40 passed`，完整回测指标、Alpha 集成与 Backtest API 回归 `27 passed`。
- `stock_selection_backtest.py` 增量 mypy 清零，Alpha 子类保持清零；全仓基线从 `1452 errors / 433 files` 收紧为 `1448 errors / 432 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百六十九批

- 按“Dashboard Alpha 用户决策可信度 × 动态元数据边界收窄 × 后台异常最小披露”收口 Alpha 首页运行时。
- Alpha service、候选池与结果边界改为精确 Protocol 和 Domain 实体契约；Provider 全部不可用时返回明确的 unavailable result，不再依赖隐式可空分支。
- 元数据、可靠性提示和自动刷新状态统一先验证为 JSON object；畸形动态值不再触发首页渲染异常。
- 日期解析先识别 `datetime` 再识别 `date`，统一返回普通日期；避免 Python 的继承关系让带时间值进入日期减法。
- `staleness_days` 只接受非布尔的非负整数；布尔值、负数、字符串和非有限动态值不再被解释为有效陈旧天数。
- 自动刷新轮询周期统一收敛到正整数；Worker 不可用、任务入队失败和 Celery 健康检查异常发布稳定状态，不再把 Broker、Provider 或凭据相关异常正文进入页面 metadata。
- 生产日志只记录异常类型；缓存锁释放和 Celery 健康检查不再附带完整异常堆栈或敏感底层正文。
- Dashboard Alpha 测试候选池与不可用结果改为真实 `AlphaPoolScope`、`AlphaResult`，避免不完整 `SimpleNamespace` 掩盖正式实体契约。

## 第二百六十九批验证结果

- Alpha 运行时新增边界回归 `7 passed`；Alpha 查询、视图、首页结构与 API 边界完整回归 `101 passed`。
- `alpha_homepage_runtime.py` 与调用入口增量 mypy 清零；全仓基线从 `1448 errors / 432 files` 收紧为 `1436 errors / 431 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十批

- 按“Dashboard 宏观局部视图契约 × 用户作用域失败关闭 × 兼容导出面类型完整性”收口 Regime、Pulse、行动建议和今日关注四个 HTMX 入口。
- 主 Dashboard 兼容模块通过精确 Protocol 描述宏观组件加载、上下文构造、Dashboard DTO 和持仓补全方法；局部视图不再依赖无类型动态模块调用。
- 四个入口补齐 `HttpRequest`、`HttpResponse` 和模板上下文类型；局部 typed decorator 在 DRF 动态装饰器边界恢复函数签名，不扩大通用认证装饰器的类型假设。
- 今日关注入口要求认证主体具有非布尔的正整数持久化 ID；匿名态之外的未保存用户、零值、负值和字符串 ID 不再进入 Dashboard 数据与持仓查询链。
- 保持现有 `apps.dashboard.interface.views` monkeypatch/兼容导出面不变，避免破坏已有测试、插件和 Dashboard 内部调用者。

## 第二百七十批验证结果

- 宏观局部视图新增契约回归 `10 passed`；真实宏观路由、静态读认证、Regime/Pulse 端到端和 Dashboard 兼容回归 `35 passed`。
- `macro_views.py` 增量 mypy 清零；全仓基线从 `1436 errors / 431 files` 收紧为 `1427 errors / 430 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十一批

- 按“ETF 降级信号 PIT 真实性 × Alpha 评分域一致 × 配置真源无硬编码”收口 Alpha ETF fallback adapter。
- 本地持仓查询同时要求报告期不晚于计划交易日、且数据在该日期前已进入系统；今天导入的历史季报不再回填过去的 Alpha 推荐。
- 历史计划交易日缺少本地 PIT 数据时禁止调用当前远端接口补数；远端持仓同样要求可解析报告期且不晚于计划交易日，避免未来季报进入历史决策。
- ETF 持仓占比从百分数转换为 `[0, 1]` Alpha 分数，原始百分比只保留在 factor；`NaN`、`Inf`、非正和超过 100% 的持仓比例不再生成评分。
- 删除代码内 `csi300/csi500/sse50/csi1000` 到具体 ETF 代码的默认映射；仅接受运行时正式配置或有真实持仓的基金自动发现，不再把资产代码沉积在 Provider 实现。
- 健康检查不再无条件返回可用：存在真实本地持仓才为 available，仅有映射为 degraded，无数据且无映射为 unavailable。
- 本地/远端读取与持久化异常日志只保留异常类型；底层 Provider、数据库或网络异常正文不再进入普通日志和失败结果。
- ETF payload、成分股、元数据、候选池、用户参数和动态 DataFrame 边界补齐精确类型，非法 payload shape 与值失败关闭。

## 第二百七十一批验证结果

- ETF PIT、评分与配置真源新增回归及既有 adapter 契约 `12 passed`；Alpha Provider、ETF 集成和服务注册完整回归 `40 passed`。
- `etf_adapter.py` 增量 mypy 清零；全仓基线从 `1427 errors / 430 files` 收紧为 `1415 errors / 429 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十二批

- 按“Alpha 告警逐标签真实性 × 持续状态可达 × 单事件通知去重”收口 Alpha monitoring 告警链。
- 定时任务不再每次构造新的通用 `AlertManager`；通过 Application provider factory 获取进程内稳定的 Alpha Manager，使告警持续时间能跨周期累计，9 条 Alpha 专用规则真实进入调度链。
- 指标注册表新增逐序列读取接口；告警按 Provider、队列等 labels 分别评估，不再把同名指标相加后让健康 Provider 掩盖故障 Provider。
- 非有限指标不再参与规则比较，并清除对应待确认状态；`NaN`、`Inf` 不会形成虚假告警或把旧事件延续到后续有效观测。
- 每个规则/labels 组合在一次连续异常期间只通知一次；指标恢复后清理首次触发与已通知状态，再次恶化才形成新事件。
- `AlphaAlertConfig.get_all_rules()` 每次返回独立规则副本；测试或运行时修改 duration 不再污染后续 Manager。
- 支持通过 `ALPHA_ALERT_RULE_OVERRIDES` 覆盖 threshold、duration 和 severity；非有限阈值、布尔 duration、负 duration 和非法严重级别失败关闭并回退正式 catalog。
- 删除未接入运行链、依赖无类型 `django-environ` 且会制造配置已生效错觉的 `AlertThresholds` 死代码。
- 告警通知改为 frozen value object，要求有限指标、非空标识和 timezone-aware 时间；通知保留规范化 labels，摘要按标签发布真实序列。
- 通知 handler 失败日志只记录异常类型；底层渠道异常正文、凭据和完整堆栈不再进入普通日志。

## 第二百七十二批验证结果

- Alpha 告警新增边界与既有配置/通知/调度定向回归 `20 passed`；完整 monitoring、stress 和 full-flow 告警回归 `35 passed`。
- `alerts.py` 增量 mypy 清零，Application monitoring、provider factory 与共享 metrics 保持清零；全仓基线从 `1415 errors / 429 files` 收紧为 `1402 errors / 428 files`，净减少 `13 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十三批

- 按“Qlib 股票池配置真源 × Provider 行情真实性 × 构建边界失败关闭”收口 Tushare Qlib builder 与 Config Center 股票池配置。
- 删除构建器内 `csi300/csi500/sse50/csi1000` 到 Tushare 指数代码的硬编码映射；Config Center 新增 `tushare_index` 来源类型，并通过数据迁移初始化四个内置股票池的正式数据库配置。
- Alpha Infrastructure 仅调用 Config Center Application facade 获取股票池定义与成员，不再直接实例化其他 App 的 Infrastructure repository。
- 指数权重查询窗口从 60 天扩展到 140 天，覆盖季度调仓间隔；仅采用不晚于目标日的最新有效权重，缺列、坏日期和非法成分代码失败关闭。
- universe ID、显式股票代码、目标日期、回看窗口和重试参数统一验证；路径型 ID、畸形 Tushare 代码、未来目标日、非正或超限窗口不再进入 Provider 或文件系统。
- 股票与指数日线统一验证请求代码、日期窗口、有限正 OHLC、OHLC 关系、有限非负成交量和有限涨跌幅；Provider 返回的越界日期、串码和坏行情不再推进 Qlib 本地可用日期。
- 复权因子要求有限正数；非有限 scale、价格和计算结果不再写入二进制特征，避免 `NaN/Inf` 或错误缩放污染训练与推理数据。
- 股票池、日线、复权因子和指数行情异常日志只记录异常类型；Provider 原始错误正文与可能包含的凭据不再进入普通日志。
- Tushare client、重试调用、NumPy 数组和动态 pandas 边界补齐精确 Protocol、泛型与第三方边界类型；删除无类型 pandas 直接导入。

## 第二百七十三批验证结果

- Qlib builder 与 Config Center Alpha universe API 回归 `21 passed`，管理命令、Alpha 运维 API 与运行时刷新调用链回归 `10 passed`；覆盖数据库指数映射、超过 60 天的季度权重、配置归一化、非法代码/路径、未来日期、资源上限、越界/串码/坏 OHLC、非有限复权因子和异常脱敏。
- `qlib_builder.py` 增量 mypy 清零，Config Center 新增 facade 与改动生产文件保持清零；全仓基线从 `1402 errors / 428 files` 收紧为 `1391 errors / 427 files`，净减少 `11 errors / 1 file`。
- Django system check、迁移一致性、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十四批

- 按“Qlib 推理信号真实性 × 异常最小披露 × 动态股票池契约”收口 Alpha Qlib adapter 与 Provider 通用安全装饰器。
- 缓存评分统一拒绝布尔、非有限或超出 `[-1, 1]` 的分数、非法排名、非有限或越界置信度；因子字典仅保留有限数值。
- 缓存信号 `asof_date` 晚于计划交易日时失败关闭，不再让未来信号进入 Alpha 结果；模型审计字段改为一次性构造新 frozen `StockScore`，删除列表内查找替换。
- 因子暴露与同步预测丢弃 `NaN/Inf`；预测股票代码统一规范化，动态 pandas/Qlib 返回边界不再直接混入 Domain 结果。
- 删除 `csi300/csi500/sse50/csi1000` 身份映射；安全 universe ID 直接交给 Qlib 本地市场目录解析，支持 Config Center 新增股票池而无需修改 adapter。
- universe ID、`top_n` 与 scoped pool 交易日期在缓存和任务前验证；路径型 ID、非正或超限数量、scope 日期错配保持零缓存与零任务副作用。
- 异步投递、同步推理、活动模型、缓存、日历、队列、因子、股票池、模型加载和预测异常日志仅记录异常类型；通用 `qlib_safe/provider_safe` 删除原始正文、traceback 与 `exc_info`。
- 推理失败告警不再持久化原始异常正文；内联任务失败只发布稳定错误码，成功结果只白名单发布 status/count，Celery 动态 payload 不再直接进入结果 metadata。
- 活动模型改为精确 `TypedDict`，日历输入、原始评分、模型状态与同步预测容器补齐类型；Qlib/pandas 通过动态第三方边界加载，删除四条无类型直接导入。
- 同步更新批次 272 后遗留测试，使告警调度断言使用正式 `get_alpha_runtime_alert_manager` provider factory。

## 第二百七十四批验证结果

- Qlib adapter 金融真实性、既有契约、Provider 集成、基础边界与降级日志回归 `30 passed`；完整 Qlib runtime contracts `14 passed`，仅保留 pandas 未来弃用警告。
- `qlib_adapter.py` 增量 mypy 清零，通用 adapter base 保持清零；全仓基线从 `1391 errors / 427 files` 收紧为 `1382 errors / 426 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十五批

- 按“资产池阈值数据库真源 × 类别一致性 × 非有限评分失败关闭”收口 Asset Pool Domain、Application、Repository 与 API。
- 删除 `AssetPoolClassifier` 内股票、基金和债券阈值硬编码；分类器只接受 Infrastructure 从 `AssetPoolConfig` 读取的活动配置，不再出现数据库表存在但运行时完全不生效的双真源。
- 新增数据迁移：仅当对应类别没有活动 investable 配置时初始化股票、基金和债券阈值；已有用户配置保持不变，阈值后续可通过数据库治理。
- 同一类别存在多个活动配置时失败关闭并返回稳定 503；缺少类别配置同样不再回退 Domain 默认值，避免配置错误被静默掩盖。
- `AssetType` 到 `PoolCategory` 使用正式枚举映射；不支持的 sector 不再静默当作 equity，批次声明类别与资产实际类别不一致时拒绝整批结果。
- 分类前统一要求资产代码、名称非空，五项评分有限且位于 `[0, 100]`；`NaN/Inf` 和越界总分不再利用比较语义落入 candidate 池。
- `PoolConfig` 增加阈值不变量：分数阈值有限且在正式区间，禁投阈值不得高于准入阈值，观察区间必须递增，可选风险/估值阈值必须有限非负。
- Pool entry 直接使用 `AssetScore` 正式字段；市值、PE、PB 只从显式 `custom_scores` 读取，不再用不存在的动态属性制造配置已参与风控的错觉。
- 评分上下文、筛选、配置和摘要异常响应统一为稳定文案与机器错误码；数据库、筛选器和配置异常正文不再进入 API 响应或普通日志。
- Pool service、Domain `to_dict`、统计容器、摘要和 DRF handler 补齐精确类型；修复批内原有 `any` 误用与无类型列表/字典。

## 第二百七十五批验证结果

- Asset Pool Domain、Application、Repository 与 API 回归 `21 passed`；覆盖数据库种子阈值真实生效、重复/缺失配置、未知类别、类别错配、`NaN` 评分、非法阈值和稳定 503 契约。
- pool service、Domain pool 与 pool views 增量 mypy 清零；全仓基线从 `1382 errors / 426 files` 收紧为 `1365 errors / 423 files`，净减少 `17 errors / 3 files`。
- Django system check、迁移一致性、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十六批

- 按“宏观单位转换真实性 × 元数据真源保护 × 非有限观测失败关闭”收口 Macro indicator service。
- catalog `extra` 先合并，正式名称、中英文名、分类、单位和描述后覆盖；动态扩展字段不再反向篡改核心指标身份与量纲。
- 单位转换统一拒绝非有限存储值；转换失败时保留真实 storage unit，不再把未转换数值标成请求的 original unit。
- 展示精度只接受 0-10 的非布尔整数；单位规则 multiplier 必须有限正数且 storage unit 非空，零、负数、`NaN/Inf` 与缺失量纲失败关闭。
- 指标归一化输入必须有限；删除 `multiplier or 1.0` 让零倍率被静默解释为 1 的错误。
- available、detail 与 history 输出通过 `safe_float` 收窄；`NaN/Inf` 最新值不再发布，非有限统计降为 unavailable，坏历史值或非日期报告期被剔除。
- 历史 periods 限制为 1-1200 的非布尔整数，避免负窗口、空窗口和无界查询进入 Repository。
- alias 安全检查在一次 metadata snapshot 上完成；同次请求不再为每个候选重复查询 catalog，避免性能放大与配置切换期间语义不一致。
- Macro indicator 的 metadata、配置、列表、详情、历史与前端投影补齐精确泛型；精确返回类型同步消除 Alpha Trigger 下游已经冗余的 cast，不接受新增债务。

## 第二百七十六批验证结果

- Macro indicator 数值/单位真值与既有服务回归 `17 passed`；Macro facade、策略消费者与系统配置组件回归 `22 passed`。
- `indicator_service.py` 增量 mypy 清零，Alpha Trigger 消费者保持清零；全仓基线从 `1365 errors / 423 files` 收紧为 `1356 errors / 422 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十七批

- 按“HP 趋势语义正确性 × Filter 持久化保真 × 宏观输入失败关闭”收口 Filter repository 与数值 adapter。
- 修复 statsmodels `hpfilter` 返回 `(cycle, trend)` 却被反向解包的错误；此前扩张窗口实际把周期项发布为趋势，现在只写入真实 trend。
- HP lambda 必须有限非负，全部观测必须有限；`NaN/Inf` 不再进入 statsmodels 或被写成趋势结果。
- Filter result 保存和读取统一用 `is not None` 判断 slope；合法零斜率不再被误写/误读为缺失值。
- Filter config 更新在保存前执行 `full_clean`；即使非 API 调用绕过 serializer，ORM 字段约束仍在持久化边界执行。
- 宏观事实查询统一验证非空指标代码、正向日期窗口和 1-2000 的非布尔 limit；修复 limit=0 因 `[-0:]` 意外返回全量数据的问题。
- Data Center 多源一致性选择前通过正式 Protocol 收窄 ORM fact；选中结果仅发布有限数值，不一致来源继续失败关闭。
- 指标目录查询只物化一次规范化 code 列表，并使用 `_default_manager`；空代码不再进入 catalog 查询或结果。
- 删除无类型 statsmodels 直接导入，使用动态第三方边界与精确 callable Protocol；宏观点位用 `MacroIndicatorPoint` TypedDict 在进入 Application 前收窄日期和值。
- Kalman state 直接从 ORM 精确构造 Domain entity，不再调用无类型 model helper；repository 参数、返回容器和 adapter 状态补齐精确类型。

## 第二百七十七批验证结果

- Filter repository、UseCase 与 API 定向回归 `38 passed`；完整 Filter Dashboard、Domain、UseCase、Repository 与 API 回归 `83 passed`。
- `repositories.py` 增量 mypy 清零，Filter use cases 保持清零；全仓基线从 `1356 errors / 422 files` 收紧为 `1346 errors / 421 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十八批

- 按“Regime 状态展示真源 × 风险参数空值保真 × ORM 类型边界”收口 Regime 核心配置模型。
- 删除与 Django choices 自动方法冲突的自定义 `get_dominant_regime_display`；四种 Regime 的中文名称改由字段 choices 原生标签发布，模板调用契约保持不变。
- 新增状态迁移同步 choices 标签；不修改数据库存储值，`Recovery/Overheat/Stagflation/Deflation` 规范代码及既有约束保持不变。
- 风险参数 JSON 判断改为显式 `is not None`；合法空对象 `{}` 与空数组 `[]` 不再被误判成“未配置”。
- 所有 Regime 模型字符串表示、约束验证与风险参数取值补齐精确返回类型；JSONField 的动态值在 ORM 边界收窄，不向调用方泄漏 `Any`。
- `validate_constraints` 使用与 Django 基类一致的 `Collection[str] | None` 契约；激活配置切换的既有约束豁免与事务行为不变。
- 精确的 `get_value` 签名同步消除 `config_helper.py` 的下游无类型调用债务。

## 第二百七十八批验证结果

- Regime 原生中文显示、空 JSON 配置、仓储安全与激活一致性回归 `13 passed`；Regime API、重算命令与财务配置回归 `18 passed`，合计 `31 passed`。
- `models.py` 增量 mypy 清零，并同步清除 `config_helper.py` 下游债务；全仓基线从 `1346 errors / 421 files` 收紧为 `1334 errors / 419 files`，净减少 `12 errors / 2 files`。
- Django system check、迁移一致性、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百七十九批

- 按“宏观期间语义 × 兼容日期契约 × ORM 类型边界”收口 Macro 历史持久化模型。
- 期限数据识别从“任意以 M/Y 结尾的字符串”收紧为“数字期限 + M/Y”；`3M/10Y/24M/2Y` 保持期限数据，`CUSTOM/FAMILY` 不再被误分类。
- 标准期间、扩展期间和未知期间的显示语义保持不变；未知值继续原样发布，不伪造业务标签。
- `reporting_date` 与 `observed_at` 兼容别名显式返回 `date`，时点、期间和期限判断显式返回 `bool`。
- Macro indicator、汇率和指标配置模型的字符串表示补齐精确返回类型，删除模型方法向调用链传播的无类型调用。

## 第二百七十九批验证结果

- Macro 期间显示、期限分类、日期别名、Application/汇率边界与配置持久化回归 `27 passed`。
- `models.py` 增量 mypy 清零；全仓基线从 `1334 errors / 419 files` 收紧为 `1324 errors / 418 files`，净减少 `10 errors / 1 file`。
- Django system check、迁移一致性、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十批

- 按“账户组合核心持久化边界 × 抑制项真实性”收口 Portfolio、Position、Transaction、资金流水与券商导入模型。
- 审查确认该文件 10 项债务全部来自已失效的 Django `type: ignore`，当前类型桩已能正确识别 User、ORM、聚合函数和七个模型基类。
- 删除失效的 import/misc 抑制，不用宽泛忽略掩盖未来真实回归。
- 本批不改动持仓数量、成本、市值、盈亏、交易金额、费用、快照或资金流水的任何计算和持久化语义。

## 第二百八十批验证结果

- Account 模型结构与手工券商交易同步回归 `10 passed`。
- `portfolio_models.py` 增量 mypy 清零；全仓基线从 `1324 errors / 418 files` 收紧为 `1314 errors / 417 files`，净减少 `10 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十一批

- 按“审计监控真实性 × Prometheus 类型安全 × 异常最小披露”收口 Audit metrics。
- Counter/Histogram 重复注册只复用名称和 collector 类型同时匹配的实例；同名 Gauge 等错误类型不再被当作目标指标返回。
- 审计延迟只接受有限非负秒数；负值与 `NaN/Inf` 被跳过，不再污染 Histogram bucket、sum 和后续告警。
- Histogram buckets 与 label names 补齐精确 Sequence 契约；可选延迟显式使用 `float | None`。
- 指标摘要使用稳定 TypedDict 和浮点计数口径；Application provider 在跨层边界显式转换为普通字典。
- 摘要、导出与记录失败只发布稳定错误码或异常类型，不再把数据库、registry 等原始异常正文写入响应或普通日志。
- Prometheus 导出显式验证第三方结果必须为 bytes，再按 UTF-8 解码；异常返回稳定不可用注释。

## 第二百八十一批验证结果

- Audit metrics 非法延迟、collector 冲突、异常脱敏与导出边界回归 `9 passed`；Prometheus AuditMetrics 集成与 API 端点回归 `4 passed`。
- `metrics.py` 与 Application provider 增量 mypy 清零；全仓基线从 `1314 errors / 417 files` 收紧为 `1305 errors / 416 files`，净减少 `9 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十二批

- 按“Regime 公共 API 输入真实性 × 查询资源边界 × 异常最小披露”收口八个 API handler 与五个 Serializer。
- history 与 distribution 共用序列化日期验证；反向日期区间统一返回 400，不再进入 Repository。
- distribution 将已解析的 `date` 传入 Application facade，修复此前把查询字符串直接传给 `date | None` 契约的类型与运行语义错位。
- navigator history 的 months 严格限制为 1–120 的整数；非法文本、零、负数、小数和超限窗口不再静默回退或扩大查询。
- navigator/action 的非法日期响应不再反射原始输入；所有 API 内部失败只返回稳定 `regime_service_unavailable` 错误码。
- health 保留 503 unhealthy 契约，但不再发布底层数据库或服务异常正文；日志只记录 endpoint 与异常类型。
- 八个 DRF handler 补齐 `Request -> Response` 契约；五个 Serializer 补齐载荷泛型，动态 `to_internal_value` 在 DRF 边界显式收窄。

## 第二百八十二批验证结果

- Regime 日期、分页、distribution、纯计算、导航窗口、异常脱敏、权限与宏观数据契约回归 `27 passed`。
- `api_views.py` 与 `serializers.py` 增量 mypy 清零；全仓基线从 `1305 errors / 416 files` 收紧为 `1291 errors / 414 files`，净减少 `14 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十三批

- 按“公开分享副作用前验证 × 快照 JSON 真实性 × 可空更新契约 × 本地日期一致性”收口 Share Application 用例。
- 创建公开链接在 Repository 写入前验证标题、主题、分享级别、密码长度、时区感知未来过期时间、正整数访问上限和 6–16 位字母数字短码。
- 修复非法 theme/share level 先落库、随后实体枚举转换才失败的问题；自定义短码复用 Domain `validate_short_code`，路径字符不再进入公开路由键。
- 五类快照 payload 必须为可序列化 JSON 对象且不得包含 `NaN/Inf`；数据来源结束日不得早于起始日。
- 修复 Asia/Shanghai 午夜窗口：账户 `auto_now_add` 使用本地日期，快照结束日改用 `timezone.localdate()`，不再因 UTC 日期仍在前一天而阻断实时快照。
- 访问日志结果必须属于正式 `AccessResultStatus`；日志查询 limit 限制为 1–1000 的非布尔整数。
- Update 用显式未提供哨兵区分“字段省略”和“提交 null”；公开 API 只传实际提交字段，`subtitle/expires_at/max_access_count` 现可清空且省略时保持原值。
- 快照、最新快照、访问日志和访问统计容器补齐精确泛型，删除八处裸 `dict` 债务。

## 第二百八十三批验证结果

- Share 用例安全与 API 边界回归 `22 passed`；ShareLink 既有用例及管理页主题/密码更新回归 `33 passed`；扩展 Share views/API 回归 `26 passed`。
- `use_cases.py`、`interface_services.py` 与 Share views 增量 mypy 清零；全仓基线从 `1291 errors / 414 files` 收紧为 `1283 errors / 413 files`，净减少 `8 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十四批

- 按“资产评分输入真实性 × 情景覆盖边界 × 响应 DTO 一致性”收口 Asset Analysis Serializer 与 multidim-screen API。
- 请求只接受正式字段；未知字段失败关闭，客户端不再能通过未声明的 `active_signals` 伪造系统信号上下文。
- Regime、Policy 与 Sentiment 情景覆盖纳入 Serializer 正式契约；视图只读取 `validated_data`，不再从原始 `request.data` 绕过验证。
- 权重键必须完整等于 `regime/policy/sentiment/signal`；每项必须为非布尔、有限且位于 `[0, 1]`，总和使用 `math.fsum/isclose` 验证为 1。
- Sentiment 覆盖必须为有限数值且位于 `[-3, 3]`；布尔、`NaN/Inf` 不再进入 `ScoreContext`。
- 修复响应 DTO 与 Serializer 长期错位：DTO 发布嵌套 `scores`，Serializer 不再读取不存在的扁平 `regime_score/.../total_score`。
- 嵌套评分及自定义评分在输出边界再次验证有限性；非有限内部结果失败关闭，不发布非法 JSON 数值。
- 六个 Serializer 补齐精确泛型，DRF `style/context` 同名基类边界显式收窄；三个 API handler 与上下文构建器补齐请求、响应和 Domain 返回类型。

## 第二百八十四批验证结果

- Asset Analysis Serializer 安全契约与 multidim-screen API 回归 `19 passed`，覆盖真实嵌套评分序列化、情景覆盖、未知字段及非有限权重。
- `serializers.py` 与 `views.py` 增量 mypy 清零；全仓基线从 `1283 errors / 413 files` 收紧为 `1269 errors / 411 files`，净减少 `14 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt ceiling 通过。

## 第二百八十五批

- 按“Alpha 历史审计连续性 × 查询物化边界 × 异常最小披露”收口 Dashboard Alpha 首页历史 Application mixin。
- 历史 Repository 与上下文 Repository 补齐显式依赖类型，运行列表通过只读 Protocol 在 Application 边界收窄，不向聚合逻辑传播 ORM 动态类型。
- `scope` 与 `alpha_result` 使用正式 Domain 实体契约；历史持久化、列表序列化及临时容器补齐精确参数和返回类型。
- 请求日和有效数据日兼容 `date` 或 ISO 日期字符串；格式损坏时不再导致整次历史记录静默丢失，而是将对应列置空并在历史元数据写入稳定字段名告警，原始 Alpha 元数据继续保留。
- 历史详情只物化一次快照集合，避免同一请求重复执行 related-manager 查询；数据中心回填的非字符串名称在输出前统一规范为字符串。
- 持久化失败日志只记录异常类型，不再写入底层异常正文或 traceback，避免数据库连接信息等敏感内容进入普通日志。
- 历史运行主键在输出前验证为非布尔整数；未持久化的异常主键不再从 Application 返回。

## 第二百八十五批验证结果

- Dashboard Alpha 历史持久化、结构及事务回归 `5 passed`；历史 API 用户隔离、名称回填与只读契约回归 `3 passed`。
- `alpha_homepage_history.py` 增量 mypy 清零；全仓基线从 `1269 errors / 411 files` 收紧为 `1261 errors / 410 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百八十六批

- 按“全局异步任务可观测性 × 指标标签有界性 × 运维异常最小披露”收口 Core Celery Prometheus signal handlers 与追踪装饰器。
- 五个 Celery signal handler 补齐显式参数与返回类型；第三方无类型 signal decorator 只在精确边界使用 `misc` 抑制，不向业务函数扩散动态类型。
- 任务 ID 为空时不再向全局开始时间表写入无效键；postrun 仅对有效 ID 执行 pop，避免无 ID 信号相互覆盖计时状态。
- 动态任务名统一验证字符串、去除空白并限制为 200 字符；异常对象或空名称统一发布稳定 `unknown` 标签，重试原因仅发布类型名，避免原始错误正文造成敏感信息泄露和 Prometheus 标签基数无界增长。
- 队列统计只接受 worker 到任务列表/元组的映射；异常 worker payload 不参与计数，仅有 reserved task 的在线 worker 也能被正确计入。
- 队列指标读取失败只返回稳定 `queue_metrics_unavailable`，所有 handler 日志只记录异常类型，不再泄露 Redis URL、认证信息或 traceback。
- Prometheus Gauge 更新前显式验证数值；错误字符串不再传入 `.set()`。追踪装饰器使用 `ParamSpec + TypeVar` 保持被装饰任务的参数和返回契约。

## 第二百八十六批验证结果

- Celery 指标边界与 Prometheus 集成回归 `21 passed`，覆盖空任务 ID、reserved-only worker、异常与重试原因脱敏、任务名上限及装饰器返回契约。
- `core/celery_metrics.py` 增量 mypy 清零；全仓基线从 `1261 errors / 410 files` 收紧为 `1253 errors / 409 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百八十七批

- 按“统一监控统计真实性 × Prometheus 标签基数 × 指标异常最小披露”收口 Core Metrics 统一入口。
- API、Celery 与 Audit 记录器统一验证有限非负时长；负数、布尔值和 `NaN/Inf` 不再进入 Histogram，计数指标仍按合法标签记录。
- API 方法、端点、视图名、任务名、状态、模块及来源标签统一去空白并限制长度；未知 Celery 状态归一为 `unknown`，非标识符形式的原始重试正文归一为 `other`。
- API 装饰器优先使用 Django `resolver_match.route`，动态资源 ID 不再直接形成 Prometheus endpoint 标签；缺少路由信息时保留有界 path 回退。
- 修复指标摘要漏计 4xx 的问题：`api_requests.total` 现在统计全部 API 请求，错误量继续由 `api_error_total` 独立累计。
- 摘要和三个子域使用稳定 TypedDict 与浮点计数口径；Prometheus sample 值显式转换后聚合，不再因整型初始化变量接收浮点值产生契约错位。
- Metrics 记录与摘要失败只记录异常类型；摘要返回稳定 `metrics_summary_unavailable`，不再向健康检查响应或日志发布数据库、Redis 等底层异常正文。
- API 与 Celery 装饰器使用 `ParamSpec + TypeVar` 保持被装饰函数的参数和返回类型，异常路径继续原样抛出，不改变业务控制流。

## 第二百八十七批验证结果

- Core Metrics 边界与 Prometheus 集成回归 `20 passed`，覆盖非有限延迟、原始重试原因、未知状态、4xx 总数、摘要异常脱敏及 resolver route 标签。
- `core/metrics.py` 增量 mypy 清零；全仓基线从 `1253 errors / 409 files` 收紧为 `1248 errors / 408 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百八十八批

- 按“生产 readiness 验收真实性 × 连续窗口唯一性 × 可空证据边界”收口个人 readiness 窗口核心校验器。
- 证据文件加载结果先保留可空边界，再显式收窄为 `_EvidenceRecord` 列表；交易日过滤、连续窗口、质量摘要与清单构建不再传播可空记录。
- `required_days` 必须为正整数；零、负数和布尔值在读取证据及计算投影前失败关闭，不再因 `remaining_days == 0` 形成虚假的 `accepted` 状态。
- 连续窗口按交易日聚合证据记录；同一目标日存在多份有效 JSON 时不再由字典覆盖顺序任意选择一份，而是发布 `duplicate evidence records` 阻断项并保持窗口 `in_progress`。
- 重复日阻断项保留目标日和全部冲突文件路径，便于运维人员定位并清理证据，同时不把任一冲突记录纳入 accepted evidence、质量统计或验收清单。
- 缺失日、失败日、交易日历推进及 scheduler clean suffix 的既有连续窗口语义保持不变。

## 第二百八十八批验证结果

- 个人 readiness 窗口校验完整回归 `29 passed`，覆盖正向连续窗口、缺失/失败证据、日历回退、形式化证据质量、非法窗口及重复目标日。
- `readiness_window_validation_core.py` 增量 mypy 清零；全仓基线从 `1248 errors / 408 files` 收紧为 `1242 errors / 407 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百八十九批

- 按“决策到成交追溯真实性 × 推荐匹配数值边界 × 跨表写入一致性”收口统一推荐执行关联 bridge。
- 用精确 Repository Protocol 替代两个 recorder 中的 `Any` 依赖；匹配、用户动作更新、执行关联写入及返回 payload 在跨 App 边界显式收窄。
- 模拟盘与导入成交统一验证正整数 transaction/account ID、非空证券代码和 timezone-aware 成交时间；非法标识或 naive datetime 不再进入推荐时间窗匹配。
- 证券代码在匹配和持久化前去空白并转为大写；实际动作仍只接受 `buy/sell`，不扩大现有业务枚举。
- 修复 `match_confidence or 0.85` 覆盖合法 `0.0` 的问题；缺失值才使用默认匹配置信度，布尔、非数值、`NaN/Inf` 及 `[0, 1]` 外数值失败关闭。
- 匹配推荐必须提供非空 recommendation ID；用户动作更新返回“推荐不存在”时不再继续写入孤立执行关联。
- 已匹配成交的“标记 ADOPTED + 写执行关联”放入同一数据库原子块；后一步失败时不再遗留只有采纳状态、没有成交证据的半完成记录。
- Repository 返回值必须为映射，执行关联列表必须为字典列表；动态对象不再直接作为公共审计 payload 返回。
- 模拟盘记录失败日志只发布 transaction ID 和异常类型，不再记录 recommendation ID、数据库连接信息或原始异常正文。
- 审计列表入口验证 1–200 的非布尔 limit，过滤参数统一去空白；非管理员无有效用户身份或请求越权账户时继续返回空列表。

## 第二百八十九批验证结果

- 决策执行关联 Domain bridge 回归 `13 passed`；Audit execution-link 与券商导入集成回归 `2 passed`。
- `decision_execution_links.py` 增量 mypy 清零；全仓基线从 `1242 errors / 407 files` 收紧为 `1236 errors / 406 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十批

- 按“宏观数据源切换真实性 × 主备一致性验证 × 异常最小披露”收口 Data Center macro-source failover 与多源合并适配器。
- Failover/MultiSource 构造器改用协变 `Sequence[MacroAdapterProtocol]` 并固化为 tuple；容差必须为有限、非布尔且位于 `[0, 1]`。
- 数据源成功结果、失败异常、已选来源和适配器索引补齐精确类型；不同具体适配器不再通过可变 list 推断互相冲突的类型。
- 删除“最后一个适配器成功即直接返回”的捷径；主源失败后选中备用源时会继续尝试后续来源执行交叉验证。
- 主源成功但备用源不一致时保留主源并明确告警，不发生静默切换；主源失败且多个备用源不一致时失败关闭，不使用无法确认的宏观数据。
- 只有一个备用源可用时仍保持自动 failover，但明确发布“没有其他可用数据源执行交叉校验”告警，不再把未验证切换描述为一致性通过。
- 一致性校验按指标代码分组、按观测日期比较；不同指标或没有共同日期的数据不再被错误判定为一致。
- 主备数据中的非有限值直接判为不可验证；最大差异比例继续使用 Domain 对称相对误差与运行时配置容差。
- MultiSource 去重容器补齐 `(code, observed_at)` 键类型；`published_at=None` 使用稳定最小日期比较，不再在多源合并时触发 `None > date`。
- 数据源读取、抓取及初始化失败日志只记录来源和异常类型；Token、HTTP URL、数据库错误正文不再进入普通日志或最终不可用异常。

## 第二百九十批验证结果

- Macro failover、MultiSource 与一致性 Domain 规则回归 `44 passed`，覆盖非法容差、主备偏差、单备用源未验证切换、多备用源冲突、无重叠序列及空发布时间。
- `failover_adapter.py` 增量 mypy 清零；全仓基线从 `1236 errors / 406 files` 收紧为 `1229 errors / 405 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十一批

- 按“Terminal 页面登录边界 × staff 配置权限 × TUI 模式持久化”收口 Terminal 页面 views。
- `_staff_required` 使用 `ParamSpec + Concatenate` 保留被装饰视图的 request、位置参数、关键字参数与响应契约；`functools.wraps` 统一保留函数元数据。
- staff 装饰器显式接收 `HttpRequest` 并返回 `HttpResponseBase`；匿名用户继续由 `login_required` 重定向，普通登录用户返回 403，staff 或 superuser 才能进入命令配置页。
- Terminal、配置页、TUI workbench 三个 class-based GET handler 及三个函数式兼容入口补齐精确请求和响应类型。
- TUI 模板 context 收窄为字符串字典；响应继续写入 `agom_ui_mode=tui`、一年 max-age 与 `SameSite=Lax`，不改变用户首屏或路由。
- 新增真实客户端页面回归，覆盖三个匿名入口、普通用户 Terminal/TUI 访问、配置页拒绝、staff/superuser 配置访问及 TUI cookie。
- 同步修正 Terminal chat 组件测试的过期异常契约：实现与 API 安全测试已返回稳定 `terminal_agent_unavailable`，组件测试不再要求把 Agent 原始异常正文反射给用户。

## 第二百九十一批验证结果

- Terminal 页面、组件与 API 边界回归 `31 passed`；项目固定 TUI workbench 与 Terminal Agent 最小回归包 `208 passed`。
- `views.py` 增量 mypy 清零；全仓基线从 `1229 errors / 405 files` 收紧为 `1221 errors / 404 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十二批

- 按“多数据源共享契约 × 标准行情序列化 × 原始载荷动态边界”收口 Data Center 市场网关标准实体。
- 行情、资金流、新闻、技术指标、历史 K 线与 Provider 状态的 `to_dict` 返回值统一声明为 `dict[str, object]`；调用方不再接收缺失键值类型的裸字典。
- `RawPayload.payload` 将动态类型限制在外部 Provider 原始响应边界，并显式声明为 `dict[str, Any]`；动态数据不再由无参数容器类型向其他标准 DTO 扩散。
- 保持现有价格、资金流、指标和 Provider 健康状态业务语义不变，本批不引入未经正式规则确认的行情取值约束。
- 补齐技术指标 Decimal 序列化、历史 OHLCV 标准字段与嵌套原始 Provider 载荷回归，覆盖此前缺少测试的共享 DTO。

## 第二百九十二批验证结果

- 市场网关实体与 Provider 回归 `44 passed`。
- `market_gateway_entities.py` 增量 mypy 清零；全仓基线从 `1221 errors / 404 files` 收紧为 `1214 errors / 403 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十三批

- 按“东方财富主网关 × 外部数值可信边界 × 历史行情重试契约”收口 AKShare/EastMoney 市场数据 Gateway。
- 历史 K 线 fetcher 使用精确 `Callable` 和 DataFrame 可空返回契约；直接网络上下文管理器补齐 `Iterator[None]`，批量行情行统一收窄为只读字符串键映射。
- Pandas 无类型依赖只在模块导入边界使用精确抑制，并删除函数内重复导入；动态第三方类型不再造成生产函数签名缺失。
- 整数解析复用统一 `safe_float`，外部源的空值、格式错误、`NaN/Inf` 不再触发整数转换异常；Decimal 解析同步拒绝非有限值和零缩放。
- 保持行情请求、东方财富批量兜底、腾讯降级和历史 K 线解析流程不变，新增非有限数与零缩放回归。

## 第二百九十三批验证结果

- Data Center 市场网关实体、Provider 与解析器回归 `69 passed`。
- `akshare_eastmoney_gateway.py` 增量 mypy 清零；全仓基线从 `1214 errors / 403 files` 收紧为 `1207 errors / 402 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十四批

- 按“本地券商行情接入 × 动态 SDK 最小协议 × 历史交易日确定性”收口 QMT/XtQuant 市场数据 Gateway。
- 为动态加载的 XtQuant 模块定义实时 Tick 与历史行情最小 Protocol；`_load_xtdata`、历史 DataFrame 提取和交易日解析补齐精确返回类型，下游连接探测不再调用无类型 Gateway。
- 实时 Tick 顶层载荷必须为字典；SDK 返回列表等异常结构时发布稳定类型告警并安全返回空结果，不再依赖 `AttributeError` 进入宽泛异常路径。
- 整数解析复用统一 `safe_float`，Decimal 解析显式拒绝 `NaN/Inf`；异常外部数值不再进入标准行情实体。
- 数字时间戳使用浮点秒值并按 UTC 转换为交易日，消除服务器本地时区造成的日期漂移和整型变量接收浮点值的契约错位。
- Pandas 无类型依赖只在模块导入边界精确抑制；原始历史载荷在递归转为 DataFrame 前保持 `object`，动态类型不再扩散到标准返回值。

## 第二百九十四批验证结果

- Data Center 市场网关实体、Provider 与解析器回归 `71 passed`。
- `qmt_gateway.py` 增量 mypy 清零，并同步消除连接测试的一项无类型调用债务；全仓基线从 `1207 errors / 402 files` 收紧为 `1199 errors / 401 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十五批

- 按“Terminal 用户路由 × Regime 来源真实性 × 答案链权限展示”收口旧版 Terminal chat router。
- 四类答案链步骤使用统一 TypedDict，管理员专属 `technical_details` 成为显式可选字符串列表；Router、readiness、Regime 与普通聊天链不再由字符串字典推断后接收列表值。
- system-status chain 显式接收 readiness 检查映射；Regime chain 使用正式 `CurrentRegimeResult` 与 `PolicyLevel`，chat chain 使用精确意图决策参数。
- 修复市场 Regime 用户响应读取不存在的 `source` 属性而长期显示 `N/A` 的问题；正文和管理员技术详情统一使用正式 `data_source` 字段。
- 新增 Regime 响应来源及权限展示回归：普通用户答案链继续隐藏技术详情，管理员链显示正式 Regime 来源和政策档位。

## 第二百九十五批验证结果

- Terminal chat router 局部回归 `2 passed`；连同固定 TUI Workbench 与 Terminal Agent 最小回归包共 `210 passed`。
- `chat_router.py` 增量 mypy 清零；全仓基线从 `1199 errors / 401 files` 收紧为 `1192 errors / 400 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十六批

- 按“Terminal 高风险确认 × 一次性令牌原子消费 × 参数摘要契约”收口确认令牌服务。
- 参数哈希与令牌校验使用只读字符串键映射；令牌详情使用稳定 TypedDict，命令名、风险等级、模式和参数摘要不再通过裸字典传播。
- 修复 nonce 的“读取 unused 后再写 used”并发重放窗口：校验通过字段绑定后使用缓存 `add` 原子创建独立消费标记，仅首个请求能够成功消费令牌。
- 保留原 nonce 状态用于兼容已签发令牌和既有错误语义；原子消费标记失败时统一返回 `Token already used`，确认流程失败关闭。
- 新增一次消费、身份不匹配不消费及陈旧 unused 状态并发窗口回归。

## 第二百九十六批验证结果

- Terminal 确认令牌局部回归 `3 passed`；连同固定 TUI Workbench 与 Terminal Agent 最小回归包共 `211 passed`。
- `confirmation.py` 增量 mypy 清零；全仓基线从 `1192 errors / 400 files` 收紧为 `1188 errors / 399 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十七批

- 按“Terminal Domain 共享契约 × JSON 持久化边界 × 实体可变状态隔离”收口命令与参数实体。
- 参数和命令的生命周期钩子补齐返回类型；JSON 序列化与反序列化统一使用字符串键动态值字典，动态参数默认值被限制在正式持久化边界。
- 缺失参数临时集合补齐 `CommandParameter` 元素类型，命令路由不再依赖空列表推断。
- 参数 `options` 与命令 `tags` 在序列化时返回副本；调用方修改持久化/API payload 不再反向篡改领域实体内部列表。
- 补齐公共序列化方法文档，并新增参数选项隔离、标签隔离及命令参数/治理字段 round-trip 回归。

## 第二百九十七批验证结果

- Terminal Domain 新增测试与治理组件回归 `68 passed`；固定 TUI Workbench 与 Terminal Agent 最小回归包连同新增测试 `211 passed`。
- `entities.py` 增量 mypy 清零；全仓基线从 `1188 errors / 399 files` 收紧为 `1182 errors / 398 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十八批

- 按“AI 能力目录真实性 × DRF 路由动作绑定 × 权限可见性优先级”收口 API Capability Collector。
- ViewSet 方法发现改为优先读取当前 URL callback 的 `actions` 映射；列表路由不再虚构 DELETE，详情路由不再虚构 POST 等只存在于同类其他 URL 的能力。
- callback 动作只接受已知 HTTP 方法、字符串 action 且 ViewSet 确实实现对应方法；输出方法排序稳定，能力同步不再受集合迭代顺序影响。
- 无 View class 的安全路径在排除 unsafe 后直接启用路由，删除不可能成立的二次 unsafe 比较。
- Permission class 收窄为类型列表，并按 Admin/Staff 高于 Authenticated 的顺序判断；混合权限声明不再因列表顺序把管理员接口降为 internal。
- Tag 去重保持路径首次出现顺序；Serializer schema 使用显式 properties 字典，字段名和 help text 在动态边界收窄，检查失败只记录视图名与异常类型。
- 补齐 Collector 临时容器、视图类、权限类、docstring 和 schema 返回契约，并新增列表/详情 action、权限优先级与稳定 tag 回归。

## 第二百九十八批验证结果

- API Collector 专项回归 `4 passed`，AI Capability 单元目录 `508 passed`，API 边界回归 `17 passed`。
- `api_collector.py` 增量 mypy 清零；全仓基线从 `1182 errors / 398 files` 收紧为 `1175 errors / 397 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第二百九十九批

- 按“AI 能力值对象快照隔离 × 路由分值真实性 × 同步审计时间边界”收口 Capability Domain 实体。
- Capability、RoutingLog 与 RoutingDecision 的枚举归一化钩子补齐返回类型；RoutingContext 和 SyncLog 增加显式初始化校验与快照处理。
- Capability 构造时复制 tags、使用场景、示例、输入 schema 和执行目标；序列化时再次复制，调用方修改输入对象或输出 payload 不再回写能力目录实体。
- RoutingLog、RoutingDecision、RoutingContext 与 SyncLog 同步隔离候选列表、上下文、答案链及汇总 payload 等可变值。
- 路由 `confidence` 按实际“加权排序分值”契约验证为有限非负数，不错误限制在 `[0, 1]`；`NaN/Inf`、负数和布尔值失败关闭，合法权重分值可大于 1。
- Capability priority weight 必须为有限非负数；Capability 审计时间、RoutingLog 创建时间及 SyncLog 起止时间必须 timezone-aware。
- SyncLog 禁止结束时间早于开始时间，发现、创建、更新、禁用及错误计数必须为非布尔非负整数。

## 第二百九十九批验证结果

- AI Capability Domain 专项回归 `27 passed`；完整 AI Capability 单元与组件回归 `681 passed`。
- `entities.py` 增量 mypy 清零；全仓基线从 `1175 errors / 397 files` 收紧为 `1172 errors / 396 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百批

- 按“全局登录防爆破 × 客户端 IP 信任边界 × 缓存计数原子性”收口 Core lockout authentication backend。
- 客户端 IP 默认只使用连接的 `REMOTE_ADDR`；仅当 `LOGIN_LOCKOUT_TRUST_X_FORWARDED_FOR=True` 时读取首个 XFF，直连客户端不再通过伪造转发头轮换锁定键。
- 新增环境配置示例并明确只有公共流量全部经过会覆盖 XFF 的可信代理时才可开启。
- 用户名在生成锁定键前执行 NFKC 归一化和去空白；不会把兼容 Unicode 写法拆成不同计数键，同时保留大小写语义。
- 最大尝试次数和窗口必须为正整数；布尔、非数字、零和负数回退 `5 / 900` 安全默认值，不再形成全员立即锁定或无效过期窗口。
- 首次失败使用缓存原子 `add` 建立带 TTL 的计数，已有键再执行 `incr`；并发首批失败不再因多个 `set(1)` 相互覆盖而漏计。
- 缓存计数只接受非负整数或整数字符串，布尔、负数和异常结构按零处理；Redis 读取、递增和删除失败日志只发布异常类型，不泄露连接串或认证信息。
- Authentication backend 补齐 Django request、用户名、密码、动态 kwargs 与默认 User 返回契约；可选 Redis 异常类型不再依赖宽泛 ignore。

## 第三百批验证结果

- Core Security 与认证强化 Guardrail 回归 `13 passed`。
- `core/security.py` 增量 mypy 清零；全仓基线从 `1172 errors / 396 files` 收紧为 `1167 errors / 395 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零一批

- 按“全局 HTTPS 强制 × 内部服务豁免真实性 × Host/XFF 欺骗防护”收口选择性 SSL redirect middleware 与生产安全配置。
- HTTPS 豁免不再只匹配客户端可控 Host；请求必须同时满足白名单 Host、无 XFF 转发链、来源 IP 位于内部 CIDR，才能通过容器内 HTTP 自调用。
- Host 改用 Django `request.get_host()` 解析并执行 ALLOWED_HOSTS 校验；DisallowedHost、空 Host、非字符串和格式损坏来源一律不豁免。
- 默认内部网段显式限定为 IPv4 loopback/RFC1918 与 IPv6 loopback/ULA；生产环境可通过 `SECURE_SSL_REDIRECT_EXEMPT_NETWORKS` 收紧，非法网段配置被忽略并发布稳定告警。
- 外部来源伪装 `Host: web`、经反向代理携带 XFF 的公网请求、未进入配置网段的容器来源均继续执行 HTTPS redirect。
- Host 与网段配置在 middleware 初始化时规范为不可变集合/tuple；无效配置类型不再传播到请求热路径。
- Middleware 构造器、请求处理和内部判定补齐 Django request/response 契约；生产设置中的可选 Sentry imports 使用精确第三方缺失边界抑制。

## 第三百零一批验证结果

- 内部 SSL redirect、生产设置、Core Security 与认证强化 Guardrail 回归 `31 passed`。
- `core/middleware/security.py` 与 `core/settings/production.py` 增量 mypy 清零；全仓基线从 `1167 errors / 395 files` 收紧为 `1160 errors / 393 files`，净减少 `7 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零二批

- 按“全局模板上下文 × 告警数据真实性 × 请求热路径开销”收口 Core context processors。
- UI mode、认证页默认视觉、市场视觉和全局告警入口补齐 Django request 与精确返回契约；告警使用包含布尔 dismissible 的稳定 TypedDict，不再误声明为纯字符串字典。
- 同一页面请求内 Decision Rhythm 与 Alpha Trigger alert service 各只构造一次，再分别隔离各查询失败；原实现的重复 factory 调用被消除。
- 配额百分比通过统一 `safe_float` 收窄，`NaN/Inf` 不再触发告警；计数只接受非布尔非负整数，布尔、负数和异常动态值按零处理。
- 匿名请求在加载任何业务告警服务前直接返回空列表；认证用户的单项服务失败仍不阻断其他告警或页面渲染。
- 市场视觉、配额、冷却期、候选、触发器、高优先级请求和 Beta Gate 失败日志统一只记录操作名与异常类型，不再发布数据库 URL、认证信息、底层异常正文或 traceback。
- 新增匿名短路、服务单次复用、非法计数、非有限配额和日志脱敏回归。

## 第三百零二批验证结果

- Context processor 专项、TUI mode、系统设置视觉与路由文档回归 `26 passed`。
- `core/context_processors.py` 增量 mypy 清零；全仓基线从 `1160 errors / 393 files` 收紧为 `1155 errors / 392 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零三批

- 按“全局结构化日志 × Trace 上下文真实性 × Extra 敏感字段脱敏”收口 Core logging utilities。
- `StructuredLoggerAdapter` 使用精确 Logger 泛型和标准 MutableMapping process 契约；绑定字段、调用级 extra 与线程 trace_id 在新映射中合并，不再原地修改调用方 kwargs 或嵌套 extra。
- `bind_logger` 改为返回正式 StructuredLoggerAdapter，线程 trace_id 现在真实进入 LogRecord；调用级字段覆盖同名绑定字段，线程 trace_id 保持权威。
- StructuredFormatter 对 extra 中 password、secret、token、API/encryption/private key、credential、authorization 和 cookie 后缀字段递归遮蔽；嵌套 mapping/collection 支持循环与深度上限。
- `token_count` 等非敏感统计键保持可观测，不因包含普通 token 单词前缀被误遮蔽。
- Thread-local trace ID 读取显式收窄为非空字符串；手工设置只接受 1–128 位字母、数字、连字符或下划线，空白、斜线、空格和超长值失败关闭。
- Structured logger 检测现有 handler 时包含祖先链，避免根 logger 已配置时重复添加 StreamHandler。
- 日志级别只接受标准 Python level 名称；未知环境值回退规范化 default，default 也非法时回退 INFO，避免 logging 配置启动失败。
- 新增敏感 extra、非法 trace ID、Adapter 上下文合并无副作用及非法日志级别回归。

## 第三百零三批验证结果

- 结构化日志、Trace middleware、Celery/Development 日志配置回归 `48 passed`。
- `core/logging_utils.py` 增量 mypy 清零；全仓基线从 `1155 errors / 392 files` 收紧为 `1150 errors / 391 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零四批

- 按“板块定时任务可重试性 × Application 依赖边界 × 异步结果稳定契约”收口 Sector Celery 任务。
- 两个任务改为通过 Application provider factory 获取仓储与行情适配器，不再从 provider 模块导入并直接构造 Infrastructure 实现。
- 新增类型化 Celery decorator 边界、任务返回 TypedDict 及板块评分 payload，补齐参数、可空 Regime 和返回类型；任务文件增量 mypy 清零。
- 更新任务在访问仓储或行情源前构造并验证请求，非法板块级别不再触发外部依赖；最近七日窗口继续以同一业务日期计算。
- 移除吞掉所有异常并返回底层异常正文的任务级捕获；provider/组装异常现在可到达既有 `autoretry_for`，恢复 Celery 自动重试并避免把数据库或数据源异常细节写入任务结果。
- 更新与轮动分析统一返回稳定字段；业务失败保留 `error_code`、状态、数据来源及 warning 诊断，成功结果也携带完整 provenance。
- 新增 provider factory 组装、非法输入短路、基础设施异常传播、成功排名序列化和业务失败诊断回归。

## 第三百零四批验证结果

- Sector 相关单元、API、集成与依赖边界回归 `80 passed`。
- `apps/sector/application/tasks.py` 增量 mypy 清零；全仓基线从 `1150 errors / 391 files` 收紧为 `1142 errors / 390 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零五批

- 按“Regime 核心调度契约 × 宏观状态数据真实性 × 健康监控失败关闭”收口 Regime 计算、变更通知与健康检查 Celery 任务。
- 三个任务统一使用类型化 Celery decorator、Mapping 输入边界及专用 TypedDict 结果，补齐任务参数、返回值和动态字段收窄；任务文件增量 mypy 清零。
- 上游同步状态只接受真实布尔值；同步失败时不再把可能含数据源异常或凭据的完整 payload 回写任务结果和日志。
- 日期、`use_pit`、Regime 名称及置信度在访问计算器或仓储前验证；布尔伪装、空名称、非法日期、`NaN/Inf` 及区间外置信度失败关闭。
- Regime 计算结果中的增长、通胀动量 Z 值改为透传统一解析器真实结果，不再固定伪造为 `0.0`；distribution 与 warnings 在序列化时隔离复制。
- 变更通知先验证完整成功契约再读取历史快照，日志不再拼接任意上游错误正文；历史置信度也执行有限概率校验。
- 健康检查为快照缺失和非法置信度提供稳定 `error_code`，并保留陈旧、低置信度和最新日期等可观测字段。
- 补充上游错误脱敏、异常状态类型、非法日期前置短路、通知字段验证和持久化 `NaN` 置信度回归。

## 第三百零五批验证结果

- Regime 相关单元、组件、API、集成与跨模块依赖回归 `251 passed`。
- `apps/regime/application/tasks.py` 增量 mypy 清零；全仓基线从 `1142 errors / 390 files` 收紧为 `1135 errors / 389 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零六批

- 按“Pulse 核心计算边界 × 快照可靠性参数 × 异常日志脱敏”收口 Pulse Application 用例及 provider factory。
- 在 Pulse Application 定义数据读取与快照仓储 Protocol，provider factory 补齐精确返回契约；用例不再从无类型 factory 接收 Any。
- Consumer-owned Regime gateway 新增最小 `PulseRegimeContext` Protocol，动态注册器和解析入口不再向 Pulse 用例传播 Any，同时保持跨 App 依赖由 gateway 隔离。
- 当前 Regime 解析、Pulse 计算、最新快照读取与持久化返回值完成类型收窄；`use_cases.py` 与 `repository_provider.py` 增量 mypy 清零。
- `require_reliable`、`refresh_if_stale` 必须为真实布尔值，`max_age_days` 必须为非布尔非负整数；非法可靠性控制在仓储访问及按需重算前失败关闭。
- Data Center 修复、指标 provider、计算与仓储异常日志只记录操作和异常类型，不再拼接可能包含数据库 URL、Token 或底层响应的异常正文。
- Pulse 成功日志改为参数化结构，保留 composite、strength 与 transition warning 可观测字段；既有“不可用返回 None”契约保持不变。
- 新增可靠性参数前置短路及 provider 凭据异常脱敏回归。

## 第三百零六批验证结果

- Pulse 相关单元、组件、API、集成与跨模块依赖回归 `61 passed`。
- `apps/pulse/application/use_cases.py` 与 `apps/pulse/application/repository_provider.py` 增量 mypy 清零；全仓基线从 `1135 errors / 389 files` 收紧为 `1127 errors / 387 files`，净减少 `8 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零七批

- 按“字段级凭据加密 × 动态密码学边界 × 密钥掩码防泄露”收口共享 FieldEncryptionService。
- 模块算法说明从错误的 AES-256-GCM 修正为实际 Fernet 契约（AES-128-CBC + HMAC-SHA256），避免运维与审计依据失真。
- Django 动态 setting 只接受非空字符串；错误类型失败关闭，显式空 key 不再回退到其他配置来源，防止调用方以为禁用加密却使用了隐式密钥。
- 保留既有非标准 key 的 SHA-256 确定性派生以兼容存量密文；有效 Fernet key、环境变量优先级及 `encrypted:v1:` 格式保持不变。
- 对 `cryptography` 的 encrypt、decrypt、generate_key 动态返回值统一验证为 bytes，第三方边界异常不再以 Any 穿过字符串返回契约。
- 加解密错误日志只发布稳定操作名与异常类型，不再拼接可能包含凭据、密文或底层响应的异常正文。
- `FieldEncryptionService.mask` 和 `mask_api_key` 拒绝负数、布尔等非法可见长度；显式处理 `show_suffix=0` 的 Python `[-0:]` 全量切片陷阱，零可见策略始终完全遮蔽。
- 新增空 key、错误 setting 类型、动态库错误返回、日志脱敏、非法可见长度、零后缀与零可见掩码回归。

## 第三百零七批验证结果

- Crypto、AI Provider 加密/路由/Admin 与 Dashboard 凭据降级回归 `66 passed`。
- `shared/infrastructure/crypto.py` 增量及整仓上下文 mypy 清零；全仓基线从 `1127 errors / 387 files` 收紧为 `1123 errors / 386 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零八批

- 按“AKShare 财务事实真实性 × 缺失值语义 × 公告日期可审计性”收口 Data Center 统一 AKShare provider adapter。
- 财务事实改为逐字段显式构造，不再通过 `dict[str, object]` 展开到强类型实体；FinancialFact 参数边界和整仓 mypy 清零。
- `periods` 只接受非布尔正整数，并在加载外部 SDK 前验证；零、负数和布尔值不再形成 Python 负切片或无意义远端调用。
- 收入、利润、增长率、ROE、ROA 与负债率按各自可用性独立产出；缺少 ROE 或负债率不再丢弃同一报告期全部有效收入/利润数据。
- 缺失 total_assets、total_liabilities、equity 不再被伪造为真实 `0.0`；仅在恒等关系数据充分时推导，并在 fact extra 中记录稳定 `derived_from` 依据。
- 报告期继续写入 `period_end`；实际 `NOTICE_DATE / 公告日期 / 公告日` 单独写入代表发布日期的 `report_date`，来源未提供时保持 `None`，不再用报告期冒充公告日。
- 更新 CPI 同尺度测试夹具为当前正式 AKShare 列名契约，保持生产端必需列失败关闭，不恢复位置列猜测。
- 新增部分财务指标保留、无伪零、公告日期、推导来源和非法 periods 前置短路回归。

## 第三百零八批验证结果

- Data Center 单元、组件、on-demand 财务与 provider adapter 回归 `341 passed`。
- `apps/data_center/infrastructure/_provider_adapter_akshare.py` 增量及整仓上下文 mypy 清零；全仓基线从 `1123 errors / 386 files` 收紧为 `1117 errors / 385 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百零九批

- 按“宏观事实读取真源 × 批量写入原子前置校验 × ORM/Domain 类型边界”收口 Data Center canonical macro fact repository。
- 新增 Infrastructure 内部 typed projection，将 Django ORM 字段值投影到 Domain selection Protocol，并保留原始模型映射；不再让 ORM descriptor 穿透领域选择泛型，也未弱化纯 Domain 协议。
- `get_series` 在发起 ORM 查询前拒绝布尔、零和负数 limit，避免无效切片与无意义数据库读取。
- `bulk_upsert` 改为先校验整批事实的治理元数据，再执行第一笔写入；后项非法时不再留下前项已持久化的部分批次。
- ORM JSONField 到 Domain entity 的 `extra` 显式复制，调用方修改领域对象不再反向污染 ORM 实例。
- 宏观治理快照聚合补齐精确容器类型并拆分重用局部变量，保持现有分组聚合与 iterator 查询形态，不引入 N+1。
- 新增整批前置校验、非法 limit 前置短路及 JSON metadata 去别名回归。

## 第三百零九批验证结果

- Data Center 单元、组件与 on-demand 回归 `346 passed`。
- `apps/data_center/infrastructure/macro_fact_repositories.py` 增量 mypy 清零；全仓基线从 `1117 errors / 385 files` 收紧为 `1111 errors / 384 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十批

- 按“中央数据治理入口 × Django 模型权限 × Provider 凭据防回显”收口 Data Center Admin。
- 六组 Admin 全部迁移到 `TypedModelAdmin[ConcreteModel]`；Provider 配置表单使用 `TypedModelForm[ProviderConfigModel]`，Admin handler 补齐 `HttpRequest`、具体模型可空参数和精确返回类型，移除失效 ignore。
- 两个 singleton Admin 的新增权限恢复 Django 原生模型权限前置判断；无 add 权限的 staff 现在直接失败关闭，并在查询 singleton 是否存在前短路，不再因当前无记录绕过权限。
- Provider API key 与 secret 改用不回显原值的 password widget；编辑表单留空会保留已有凭据，避免浏览器 HTML 暴露存量密钥，也避免常规编辑误清空凭据。
- Provider settings 与 production coverage universe 的全局 singleton 继续禁止 Admin 删除。
- 新增凭据不回显、留空保留、无权限短路及禁止删除回归。

## 第三百一十批验证结果

- Data Center 单元、组件与 on-demand 回归 `352 passed`。
- `apps/data_center/interface/admin.py` 增量 mypy 清零；全仓基线从 `1111 errors / 384 files` 收紧为 `1097 errors / 383 files`，净减少 `14 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十一批

- 按“宏观 canonical fact 跨模块读取 × PIT 后视偏差 × PeriodType 领域契约”收口 Macro 的 Data Center fact repository。
- `use_pit=True` 不再是无效参数：必须提供 `end_date` 作为 as-of 截止日，并同时要求 `published_at` 非空且不晚于截止日；报告期在范围内但事后发布或发布日期未知的事实不再进入历史 Regime/回测链路。
- PIT 开关只接受真实布尔值；整数、字符串和空值等动态伪装在 ORM 查询前失败关闭，缺少 as-of 日期同样拒绝执行。
- 新增 Infrastructure 内部 typed projection，将 Data Center ORM 字段值安全投影到 canonical selection Protocol，再映射回原模型；跨 App 读取不再让 Django field descriptor 穿透领域泛型。
- 单位规则 ORM TypedDict 显式复制为稳定 `dict[str, Any]`，读仓储裸 dict 返回契约补齐键值类型。
- period type 解析改为返回 `PeriodType`；事实 metadata 和 catalog 仅接受真实枚举值，非法扩展周期回退受治理的 catalog 周期，catalog 也非法时稳定回退月度。
- 新增 PIT 晚发布/未知发布时间隔离、非法开关、缺失截止日回归；既有非 PIT 实时查询保持不变。

## 第三百一十一批验证结果

- Macro 单元、组件、Application 用例与 Data Center canonical selection 回归 `233 passed`。
- `apps/macro/infrastructure/data_center_fact_repository.py` 增量 mypy 清零；全仓基线从 `1097 errors / 383 files` 收紧为 `1092 errors / 382 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十二批

- 按“部署缓存预热 × canonical 来源一致性 × ORM 查询放大”收口 Data Center macro cache warmup repository。
- 最新指标预热从“1 次代码列表 + 每个指标 3 次查询”的线性 N+1 改为固定 3 次批量查询：指标代码、各指标最新报告期全部来源事实、对应 catalog；50 个指标的理论查询数由约 151 降为 3。
- 最新报告期使用 correlated subquery 在数据库侧筛选，同时保留该期所有来源与修订供 canonical selection 判断，不因查询优化绕过治理源优先或 1% 跨源一致性阻断。
- 新增 typed ORM projection 并从正式 enums 模块导入 `DataQualityStatus`；Django field descriptor 不再穿透 Domain selection Protocol，质量枚举映射恢复显式契约。
- ORM JSON metadata 显式复制，缓存实体不再与模型 JSONField 共享可变对象。
- limit 拒绝布尔、字符串与浮点等动态伪装；零和负数保持为不访问数据库的显式空预热。
- 新增固定三查询、治理源优先、不一致来源阻断、质量状态与非法 limit 前置短路回归。

## 第三百一十二批验证结果

- Data Center 单元、组件与 on-demand 回归 `358 passed`。
- `apps/data_center/infrastructure/cache_warmup_queries.py` 增量 mypy 清零；全仓基线从 `1092 errors / 382 files` 收紧为 `1090 errors / 381 files`，净减少 `2 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十三批

- 按“统一 provider 路由 × failover 健康语义 × registry 刷新可用性”收口 Data Center provider registry 与 process-wide runtime。
- Provider config repository Protocol 补齐真实存在且 registry 必需的 `list_active` 契约；运行时不再依赖协议外属性。
- failover 将 `None` 视为违反 provider 列表返回契约并累计故障；合法空列表改为一次健康的“无数据”响应，在继续尝试备用源的同时重置连续故障，不再因连续查询无数据错误熔断整个 capability。
- 泛型结果的空列表判定下沉到 object 边界 helper，保持返回 `T | None` 精确契约，不使用 cast 或 ignore。
- repository 刷新先在候选 registry 中构造全部可用 adapter；有活动配置却一个也无法构造时拒绝替换，现有健康 provider 与熔断状态不再被预先清空。
- process-wide refresh 只在候选 registry 成功后替换全局引用；仓储或构造异常保留上一版可用 registry，首次启动失败则安全降级为空 registry。
- provider 构造、调用和全局刷新异常日志仅保留稳定操作、provider/capability 与异常类型，不再写入可能包含 token、URL 或响应正文的 traceback/异常文本。
- 新增空数据不熔断、`None` 契约失败熔断、刷新失败保留旧 provider、全局 refresh 失败保留引用及日志脱敏回归。

## 第三百一十三批验证结果

- Data Center 单元、组件与 on-demand 回归 `363 passed`。
- `apps/data_center/domain/protocols.py`、`apps/data_center/infrastructure/provider_registry.py` 与 `apps/data_center/provider_runtime.py` 增量 mypy 清零；全仓基线从 `1090 errors / 381 files` 收紧为 `1088 errors / 380 files`，净减少 `2 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十四批

- 按“政策录入数据质量 × RSS 连接配置完整性 × 表单敏感字段防回显”收口 Policy management forms。
- 三个表单补齐 typed instance Protocol、构造参数、清洗方法与 `dict[str, Any]` payload 返回契约；移除动态 `SimpleNamespace` 边界，并为 create 模板提供显式未保存实例标记。
- Policy event、RSS source 与 keyword payload 改为逐字段写入白名单；即使 cleaned data 被动态注入额外键，也不会越权传播到 Application 写入入口。
- RSSHub custom access key 与 proxy password 改用不回显原值的 password widget，编辑 initial 不再携带凭据；留空保存会保留既有密钥，非空输入才执行替换。
- RSSHub 模式要求有效路由；路由必须以单个 `/` 开头，拒绝相对路径与 `//` network-path。禁用全局配置时必须提供 custom base URL，避免生成不可用或含混的抓取地址。
- 启用代理时必须同时提供 host 与 port；不完整代理配置在进入 Application 前失败关闭。
- keyword 输入兼容中文与英文逗号，IntegerField 权重的 HTML step 从错误的 `0.1` 修正为 `1`。
- 修正一个陈旧 API 边界断言，使非法日期测试与当前统一 serializer 错误契约 `Invalid query parameters` 一致；生产 API 未改动。
- 新增凭据不回显/留空保留/显式替换、RSSHub 路由与自定义基址、代理完整性、中文关键词及 payload 白名单回归。

## 第三百一十四批验证结果

- Policy 单元、组件、API 与集成回归 `363 passed`；另有 5 条来自未改动 Policy Admin `format_html()` 的 Django 6.0 deprecation warning，留待 Admin 专项收口。
- `apps/policy/interface/forms.py` 增量 mypy 清零；全仓基线从 `1088 errors / 380 files` 收紧为 `1077 errors / 379 files`，净减少 `11 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十五批

- 按“Policy Admin 唯一注册入口 × 凭据展示安全 × Django 6.0 兼容”收口 Policy 管理后台。
- 删除未被 AppConfig 加载、与正式入口重复注册同一批模型的 `apps/policy/infrastructure/admin.py`；Policy 只保留 `apps/policy/interface/admin.py` 一个真实注册入口，消除误导性死实现及潜在 AlreadyRegistered 风险。
- 正式入口的六个 Admin 全部直接继承 `TypedModelAdmin[ConcreteModel]`，移除 TYPE_CHECKING/runtime 双套裸 `ModelAdmin` alias；两个凭据表单使用 `TypedModelForm`。
- RSSHub global access key、source custom access key 与 proxy password 改用不回显原值的 password widget；留空编辑保留既有值，非空输入才替换。
- effective URL 预览在渲染前移除 URL user-info，并遮蔽 `key/token/access_key/api_key/password/secret` query value；访问密钥不再通过只读预览泄露。
- RSSHub singleton 新增入口恢复 Django 模型权限前置判断；无 add 权限用户在查询 singleton 状态前直接失败关闭。
- 5 处无参数 `format_html()` 改为正式 placeholder 调用，并以精确 warning-as-error 门禁验证 Django 6.0 兼容。
- Policy 统计 HTML 对 catalog/status 展示名执行条件转义，再进入受控 markup，避免异常或遗留数据库值形成 Admin XSS。
- 新增 typed 唯一入口、凭据不回显/保留、effective URL 脱敏和 singleton 权限短路回归。

## 第三百一十五批验证结果

- Policy 单元、组件、API 与集成回归 `366 passed`；精确 `format_html()` Django 6.0 warning-as-error 门禁通过。
- `apps/policy/interface/admin.py` 增量 mypy 保持清零；删除旧 Admin 债务文件后，全仓基线从 `1077 errors / 379 files` 收紧为 `1065 errors / 378 files`，净减少 `12 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、重复入口引用零命中与全仓 debt baseline 刷新通过。

## 第三百一十六批

- 按“综合估值满分口径 × 异常倍数语义 × 跨股票事实隔离”收口 Equity comprehensive valuation Domain 服务。
- DCF 方法实际未参与评分时，四个有效方法权重仅合计 `0.85`，原实现却直接按 100 分阈值解释加权和，理论满分被压缩为 85；现按实际参与权重归一化，恢复真实 `0-100` 综合分与信号阈值一致性。
- 文档中的有效方法列表与运行时保持一致，不再把未实现的 DCF 描述成已参与评分；预留 risk-free rate 明确只做有限值边界验证。
- 负 PE 与负 PB 不再因相对行业比率为负而获得 100 分“深度低估”，无法解释的非正倍数按中性比率处理。
- public analyzer 在评分前验证 stock code 非空，且 FinancialData、ValuationMetrics 必须与目标股票一致，杜绝跨股票事实混合成一个估值结论。
- PE/PB、行业基准、risk-free rate、增长率、ROE 与负债率拒绝 `NaN/Inf`；历史 PE/PB 中的非有限、零和负值被隔离，保留其余有效 PIT 观测。
- `ValuationScore` 与 `ComprehensiveValuationResult` 改为 frozen Domain value object，score details 补齐 `dict[str, object]`，结果方法列表使用 tuple 防止事后增删。
- 四处分支 signal 使用精确 Literal，综合信号别名与返回契约补齐；没有方法时置信度稳定为 `0.0`，避免除零。
- 新增满分归一化、跨股票阻断、非有限输入、坏历史行隔离、负倍数中性语义和冻结结果回归。

## 第三百一十六批验证结果

- Equity Domain/Application 单元回归 `282 passed`；Equity ORM、API 与集成回归 `66 passed`，合计 `348 passed`。
- `apps/equity/domain/services_comprehensive_valuation.py` 增量 mypy 清零；全仓基线从 `1065 errors / 378 files` 收紧为 `1060 errors / 377 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十七批

- 按“多维筛选评分口径 × Application 仓储边界 × 空结果稳定契约”收口 Equity Application services。
- 七项 Equity 多维得分权重原本合计 `1.10` 并直接相加，总分可突破 100；现将既有权重固化为不可变 Mapping，并按实际权重总和归一化，恢复 `0-100` 评分语义。
- Application 定义 consumer-owned `EquityAssetRepositoryProtocol`，构造函数不再依赖具体 Django repository 类型；共享资产池入口改由 Application provider factory 组装实现，不再直接构造 Infrastructure 仓储。
- `screen_stocks` 使用 `Mapping[str, object]` 输入和稳定 TypedDict 输出；成功与无结果均固定包含 `success/count/message/stocks`。无结果不再因 API 无条件读取缺失的 `count` 而转成 500。
- `max_count` 只接受非布尔正整数，并在仓储读取前失败关闭，避免负切片、布尔伪装与无意义查询。
- technical、fundamental、valuation 三项个股特有得分必须为有限 `0-100`；`NaN/Inf` 与越界值不再污染排序。
- 同一批次拒绝重复 stock code，避免一个标的占用多个名次；同分时增加 stock code 次级排序，保证跨查询顺序稳定。
- `_to_asset_score`、pool context/filter、screen result 与生产函数返回契约补齐精确类型。
- 新增权重归一化、重复代码、非有限得分、空结果稳定结构与非法 max_count 前置短路回归。

## 第三百一十七批验证结果

- Equity 多维筛选、共享 asset-analysis API、Application 注册与 Domain matcher 回归 `107 passed`。
- `apps/equity/application/services.py` 增量 mypy 清零；全仓基线从 `1060 errors / 377 files` 收紧为 `1053 errors / 376 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十八批

- 按“估值修复配置可用性 × 缓存类型安全 × Application/Infrastructure 异常边界”收口 Equity valuation repair config runtime。
- 数据表尚未迁移或暂不可用时，只在 Infrastructure repository 捕获 `OperationalError` / `ProgrammingError`，Application 通过明确的可用性方法降级到 settings/default；不再用宽泛 `Exception` 吞掉编程错误。
- 数据库降级日志只记录异常类型，不再输出可能携带连接信息或凭据的异常正文。
- 配置缓存命中后验证实际 Domain 类型；陈旧或污染值会先删除再回源，不再让动态对象穿透强类型返回契约。
- `use_cache` 仅接受真实布尔值；整数、字符串和空值不再以 truthy/falsy 语义悄然改变运行路径。
- 配置摘要复用 repository 的安全版本查询；清缓存函数补齐精确返回类型。
- 三组 bootstrap 批量初始化各自只构造一次 repository，避免随配置行数重复执行 provider factory。
- 修正一个曾被宽泛异常隐蔽的单元测试数据库依赖，通过显式注入默认 Domain 配置保持测试隔离，不恢复异常吞噬。
- 新增 schema 不可用降级与日志脱敏、非法缓存淘汰、非法缓存开关和批量 repository 复用回归。

## 第三百一十八批验证结果

- Equity 配置专项回归 `14 passed`；Equity 单元、API edge 与组件回归 `224 passed`。
- `apps/equity/application/config.py`、`apps/equity/application/interface_services.py` 与 `apps/equity/infrastructure/config_repositories.py` 增量 mypy 清零；全仓基线从 `1053 errors / 376 files` 收紧为 `1046 errors / 374 files`，净减少 `7 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百一十九批

- 按“模型制品导入安全 × 激活写操作语义 × 注册表权限边界”收口 Alpha Qlib model Admin。
- pickle 模型导入、验证、注册表新增/变更/删除及模型激活统一限制为超级用户；普通 staff 即使被单独授予 model add/change/delete 权限，也不能上传可执行制品、改写 `model_path` 或删除审计记录。
- 模型验证页的 `GET ?activate=1` 不再改变模型状态；激活改为验证通过后由带 CSRF token 的显式 `POST` 确认，关闭只读请求触发生产状态切换的旁路。
- 批量动作改为每次必须且只能选择一个模型，并在激活前执行完整验证；不再按创建时间静默选择最后一条生效。
- 导入表单移除“导入后立即激活”，将制品落库与生产激活拆成两个明确步骤。
- `model_name` 仅允许稳定标识字符，并拒绝路径穿越、尾随点和 Windows 保留设备名；存储层再次校验模型名与 SHA-256 digest，并验证解析后的制品目录始终位于配置根目录内。
- pickle、Qlib import、运行配置和真实推理失败详情只展示异常类型，不再把可能含 token、路径上下文或第三方响应正文的异常文本写入 Admin 页面。
- 三个 Admin 迁移到 `TypedModelAdmin[ConcreteModel]`；表单 JSON、上传文件、settings、验证结果、QuerySet、URL 与 HTTP handler 补齐精确边界类型。
- 新增超级用户导入限制、注册表变更/删除限制、GET 只读、CSRF POST 激活、路径穿越/保留名称和错误详情脱敏回归。

## 第三百一十九批验证结果

- Alpha 单元、Admin 组件与 API 回归 `68 passed`；另有 1 条来自未改动 Qlib pandas 兼容层 `DataFrame.groupby(axis=...)` 的 FutureWarning。
- `apps/alpha/admin.py` 增量 mypy 清零；全仓基线从 `1046 errors / 374 files` 收紧为 `1024 errors / 373 files`，净减少 `22 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十批

- 按“Regime 阈值发布原子性 × Admin 写操作语义 × 活动配置不可变性”收口 Regime threshold governance Admin。
- Regime Admin 注册统一到 `apps/regime/interface/admin.py`；删除旧 `infrastructure/admin.py`、仅为其 GET 激活入口服务的 `infrastructure/views.py` 以及 Infrastructure package 的隐式 Admin 导入，AppConfig 只加载一个真实入口。
- 删除会改变生产阈值状态的行内 GET 激活链接和自定义 URL；激活改用 Django Admin 标准 action，只接受带 CSRF 的 POST、要求 change 权限且每次必须且只能选择一个候选配置。
- 激活编排通过 Application facade 调用 Infrastructure repository；repository 在同一事务内锁定候选与活动配置、切换唯一活动状态，并仅在提交成功后失效 Regime runtime cache。
- 当前活动配置及其阈值在 Admin 中不可直接变更或删除；新建配置固定先保存为未激活候选，单独阈值表单也拒绝向活动配置追加记录，避免绕过发布流程修改线上判定参数。
- 候选激活前验证指标代码非空且唯一、上下阈值完整/有限/有序；所需指标集合从当前活动配置数据库记录派生，缺项时保持旧配置激活，不新增 PMI/CPI 等指标代码硬编码。
- 阈值摘要改用 `format_html_join` 对数据库内容逐项转义，关闭 `mark_safe` 拼接形成的 Admin XSS；列表查询预取 thresholds，避免数量与摘要列形成逐行重复查询。
- 新增通用双泛型 `TypedTabularInline[ChildModel, ParentModel]`；三个 Regime Admin、inline、Application facade、repository 和 dashboard helper 返回契约补齐精确类型。
- 新增原子切换与回滚、提交后缓存失效、旧 GET 路由移除、单选 POST action、动态指标完整性、活动配置/阈值不可变及摘要 XSS 转义回归。

## 第三百二十批验证结果

- Regime 单元、Domain、组件与 API 回归 `176 passed`。
- Regime Admin/Application/Infrastructure 与共享 typed Admin 基座的 6 个生产文件增量 mypy 清零；全仓基线从 `1024 errors / 373 files` 收紧为 `1004 errors / 369 files`，净减少 `20 errors / 4 files`。
- Django system check、架构 delta、唯一 Admin/旧 GET 路由引用核对、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十一批

- 按“股票评分权重发布原子性 × 活动配置不可变性 × Equity Admin 类型边界”收口 Equity Admin。
- 评分权重不再通过编辑页勾选 `is_active` 时先停用旧配置、后保存新配置；新建配置固定保存为未激活候选，发布改为 Django Admin 标准单选 POST action。
- repository 在同一数据库事务内锁定候选与当前活动权重，再切换唯一活动状态；候选保存失败时整笔回滚，旧活动权重不会被提前停用而形成运行时配置真空。
- 活动权重配置不可直接修改或删除，必须编辑未激活候选并显式发布；Admin action 验证已认证持久化用户、change 权限、单选数量和有效主键。
- 五组 Equity Admin 全部迁移到 `TypedModelAdmin[ConcreteModel]`，handler、QuerySet、ModelForm、HTTP response、Decimal 展示和 display metadata 补齐精确类型，移除动态 `short_description`。
- 日线涨跌幅只以开盘价是否为零作为除法条件，收盘价为零时正确显示 `-100%`；零市值按真实 `0万` 展示，不再与缺失值混为 `-`。
- 新增评分权重原子切换、失败回滚、单选 action、活动配置只读和新建候选强制未激活回归。

## 第三百二十一批验证结果

- Equity 权重发布专项 `15 passed`；Equity 单元、API edge、配置组件与 Admin 回归 `228 passed`。
- `apps/equity/interface/admin.py` 增量 mypy 清零；全仓基线从 `1004 errors / 369 files` 收紧为 `989 errors / 368 files`，净减少 `15 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort 与增量 mypy 通过；全仓 baseline 写入阶段完成后命令进程超时退出，随后只读 debt ceiling 门禁通过并确认最终基线。

## 第三百二十二批

- 按“Qlib 初始化假成功 × 配置中心真源 × 第三方动态边界”收口 Alpha `init_qlib_data` 管理命令。
- Qlib 未安装不再打印错误后以成功状态返回；完整性检查失败、股票池为空、交易日历为空、行情窗口为空、数据准备异常或空结果全部抛出 `CommandError`，命令不再误报“初始化完成”。
- `--universe` 默认值改为 `None`，未显式传参时读取配置中心 `default_universe`；缺失或错误类型直接失败关闭，不再由命令行默认 `csi300` 覆盖运行时配置。
- `region` 与 `provider_uri` 同样要求 CLI 覆盖值或配置中心值为非空字符串；region 贯穿完整性检查、数据准备和下载，不再在 Qlib init 时硬编码为 `cn`。
- `days` 只接受非布尔正整数，download/check 只接受真实布尔值；动态调用者的零、负数、字符串和布尔伪装在加载 Qlib 前被拒绝。
- Qlib、`qlib.data.D` 与 downloader 改由 `importlib` 加载并通过 Protocol 收窄；移除 3 个 untyped import、裸容器/返回类型和无实现的初始化脚本占位函数。
- 第三方 import、下载、完整性和 feature 读取失败只输出异常类型，不再把可能包含路径、token 或底层响应内容的异常正文写入运维输出。
- 新增依赖缺失非零退出、配置中心默认股票池、非法参数前置短路、完整性/准备失败关闭、region 传递和空 feature 拒绝回归。

## 第三百二十二批验证结果

- Alpha 管理命令专项 `4 passed`；Alpha 单元与 API 回归 `65 passed`，另有 1 条来自未改动 Qlib pandas 兼容层 `DataFrame.groupby(axis=...)` 的 FutureWarning。
- `apps/alpha/management/commands/init_qlib_data.py` 增量 mypy 清零；全仓基线从 `989 errors / 368 files` 收紧为 `979 errors / 367 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十三批

- 按“高频指标假审批 × 统计标签真实性 × 数据中心指标真源”收口 Audit 高频指标验证命令。
- 删除把 Recovery/Overheat/Stagflation/Deflation 任意编码为 `1-4` 后做 Pearson 的伪序关系；改为按日期与二元逆风 Regime（Deflation/Stagflation）目标精确对齐，报告明确为同期关联而非预测因果。
- 指标只有在相关性与 p 值均存在且有限、`abs(correlation) >= min_correlation`、`p_value <= max_p_value` 时才通过；缺少 Regime、重叠样本不足、非有限结果或尚未计算相关性时一律待定，不再以 `correlation_significant=True` 默认放行。
- `min_correlation` 正式进入审批判定；`min_data_points` 与 `min_years` 同时约束数据可用性，零、负数、布尔、非有限或越界阈值在数据库访问前失败关闭。
- 删除将 `0.7 * abs(correlation) + 0.3 * coverage` 冒充 F1、将其标准差冒充稳定性分数的逻辑；命令未执行真实分类回测时，`avg_f1_score` 与 `avg_stability_score` 明确保留 `None`。
- 默认指标范围从 Data Center 活动日频/周频 Indicator Catalog 加载，并排除 `governance_sync_supported=false` 条目；`--indicators` 允许显式受控覆盖，不再在 Audit 命令内维护业务指标代码列表。
- 期限利差事件研究仅在显式 `--term-spread-indicator` 且该代码属于本次目录时运行，不再在通用验证器中硬编码某个期限利差代码。
- 可用性、Regime 查询、相关性和事件研究异常写入稳定 `ERROR` 状态及异常类型；报告保存失败抛出 `CommandError` 且不回显底层异常正文，命令不再打印错误后继续显示完成。
- validation run ID 增加随机后缀，重复验证同一日期区间不再因唯一键固定冲突；pandas/numpy 依赖被纯日期对齐与列表运算替代，SciPy 仅通过 importlib/Protocol 动态边界调用。
- 新增缺失相关性不审批、最小相关阈值生效、Data Center 目录治理过滤、伪 F1 清除、保存失败关闭与错误脱敏回归。

## 第三百二十三批验证结果

- Audit 高频验证专项 `4 passed`；Audit 单元、Application、组件、API 与集成回归 `171 passed`。
- `apps/audit/management/commands/validate_high_frequency_indicators.py` 增量 mypy 清零；全仓基线从 `979 errors / 367 files` 收紧为 `969 errors / 366 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十四批

- 按“决策行情调度假成功 × Beat 原子配置 × 动态设置边界”收口 Data Center `setup_decision_quote_refresh` 管理命令。
- readiness 小时/分钟越界不再向 stderr 写一句后成功返回；非法时间直接抛出 `CommandError`，并在进入事务前完成全部校验，四个 Beat 任务不会留下部分写入。
- pre-readiness 刷新必须严格晚于 15:20 post-close 刷新，阻止直接调用命令绕过 readiness Application 用例后配置出先验时序错误。
- `quote_max_age_hours` 不再用 truthy `or` 回退：显式 `0` 不会被悄然替换为 settings 值；布尔、字符串、零、负数、`NaN/Inf` 全部失败关闭。
- `DECISION_READINESS_ASSET_CODES` 必须为字符串 list/tuple；单个字符串不再被误当可迭代字符序列。CLI/设置代码统一 trim、uppercase、按首次出现顺序去重，空资产池禁止发布任务。
- Beat crontab timezone 改为使用项目 `TIME_ZONE`，不再硬编码 `Asia/Shanghai`；缺失或错误类型在写库前拒绝。
- task kwargs 使用 `dict[str, object]` 且 JSON 序列化显式 `allow_nan=False`，所有四个任务始终获得同一份受验证资产池与新鲜度阈值。
- django-celery-beat 通过动态第三方边界加载，CommandParser、动态 options、crontab 返回值和 task upsert handler 补齐精确类型，移除 9 个历史 mypy 错误。
- 新增越界/先于收盘时间、零与非有限行情年龄、字符串设置资产池、时区继承、代码归一去重及写入前零副作用回归。

## 第三百二十四批验证结果

- Scheduler 初始化专项 `23 passed`；scheduler、macro periodic、personal readiness 与 task-monitor 回归 `128 passed`。
- `apps/data_center/management/commands/setup_decision_quote_refresh.py` 增量 mypy 清零；全仓基线从 `969 errors / 366 files` 收紧为 `960 errors / 365 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十五批

- 按“自动投顾账户范围防扩散 × 周报调度失败关闭 × 既有 scope 契约”收口 Dashboard `setup_auto_advisor_weekly_report` 管理命令。
- 更新调度但未显式传 scope 时，既有 kwargs 必须是合法 JSON object，且只允许 `user_id/account_ids`；损坏 JSON、非对象、未知键、非正 ID、布尔伪装或无 user 的 account 列表直接失败，不再静默回退 `{}` 并扩大为全部活跃账户。
- 只有显式 `--clear-scope` 才能清空账户范围；该参数与同时提供的 user/account scope 冲突时拒绝执行，避免操作意图含混导致误清除。
- `user_id` 和 account IDs 只接受非布尔正整数；账户列表稳定去重，负数、零、非整数文本和没有 user 的账户列表在写入 Beat 表前失败关闭。
- hour/minute 越界、空 day-of-week 及动态布尔伪装改为 `CommandError`，不再向 stderr 输出后成功退出；全部参数和现有 scope 在事务写入前验证。
- 既有 PeriodicTask 使用 `select_for_update` 锁定，scope 解析、crontab 创建和任务 upsert 在同一事务；解析失败时原 kwargs 与原调度时间保持不变。
- daily evidence 调度查询异常不再被宽泛吞掉并回退 16:10；数据库错误以异常类型失败关闭。crontab 单值同时校验小时/分钟上界，异常表达式才使用文档默认时间。
- Beat timezone 使用项目 `TIME_ZONE`；kwargs JSON 禁止 NaN，django-celery-beat 经动态第三方边界加载，CommandParser、options、scope 容器和 handler 返回契约补齐。
- 新增非法用户/账户/时间、scope clear 冲突、账户去重、损坏既有 kwargs 保留原任务及显式恢复为空范围回归。

## 第三百二十五批验证结果

- 自动投顾任务与调度专项 `15 passed`；scheduler、auto-advisor、personal readiness 与 task-monitor 回归 `141 passed`。
- `apps/dashboard/management/commands/setup_auto_advisor_weekly_report.py` 增量 mypy 清零；全仓基线从 `960 errors / 365 files` 收紧为 `952 errors / 364 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十六批

- 按“部署缓存预热假成功 × 部分写入污染 × 运维参数失败关闭”收口 Core `warmup_cache` 管理命令。
- `--only` 仅接受 `regime/macro/alpha`，未知目标和错误类型直接抛出 `CommandError`，不再被静默忽略后打印整体完成。
- 所有选中数据源先查询、校验并生成不可变写入计划，再触碰缓存；任一数据源查询失败、返回错误结构或缺少业务键时整批失败，不再留下此前目标的部分预热结果。
- 空数据默认视为部署异常并失败关闭；仅在明确的冷启动场景通过 `--allow-empty` 放行，输出 `SKIP` 且不伪报该目标已写入。
- Regime、Macro、Alpha payload 分别校验非空 `regime`、`indicator_code` 和 `universe_id`；指标代码统一 trim/uppercase，缓存键冲突在写入前拒绝。
- 写入前缓存快照、每个缓存写入和回滚均执行 round-trip 校验；快照异常在零写入状态失败，中途 set/get 异常、后端先变更后抛错或回读不一致时，当前键及此前已写键按逆序恢复旧值，不存在旧值的键删除，命令仅报告脱敏异常类型并显式暴露回滚失败。
- 缓存目标、查询上限和 TTL 提取为显式常量；写入计划与目标结果使用 frozen dataclass，命令参数、动态 options 和内部容器补齐精确类型。
- 新增未知目标、空数据默认失败、准备阶段零写入、重复键前置拒绝、快照异常脱敏、写入失败回滚及后端先变更后抛错回归。

## 第三百二十六批验证结果

- Cache warmup 专项 `7 passed`；Core、personal readiness status/evidence 与 evidence inspection 回归 `168 passed`。
- `core/management/commands/warmup_cache.py` 增量 mypy 清零；全仓基线从 `952 errors / 364 files` 收紧为 `944 errors / 363 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十七批

- 按“管理命令导入副作用 × Task Monitor 接口重复实现 × 正式路由唯一真源”收口 `task_monitor.management` 两个包初始化文件。
- 删除 `apps/task_monitor/management/__init__.py` 与 `apps/task_monitor/management/commands/__init__.py` 中两份完全相同的旧 DRF views 副本；管理包初始化恢复为无副作用的包声明，不再因发现任一 Task Monitor 命令而加载 HTTP、serializer、repository 与 Celery 接口依赖。
- 正式 HTTP 实现继续唯一归属 `apps/task_monitor/interface/views.py`，URL、管理员权限、参数严格校验、Application provider 装配与稳定脱敏错误契约均未改动。
- 唯一仍从 management commands 包调用旧 views 的测试改为验证正式 Interface 路径，并补充管理包不得再次发布 HTTP handler 的回归断言。
- Django 管理命令发现清单验证通过，证明删除错误位置副本未影响 `backup_database`、readiness、scheduler 等真实命令注册。

## 第三百二十七批验证结果

- Task Monitor API、组件、管理命令、personal readiness 与 scheduler 回归 `235 passed`；`python manage.py help --commands` 正常列出完整命令集。
- 两个 Task Monitor management 包初始化文件增量 mypy 清零；全仓基线从 `944 errors / 363 files` 收紧为 `924 errors / 361 files`，净减少 `20 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十八批

- 按“正式 Task Monitor API 类型契约 × OpenAPI 装饰器动态边界 × 运行时零行为变更”收口 `apps/task_monitor/interface/views.py`。
- 为 drf-spectacular `extend_schema` 增加局部泛型 façade，明确装饰器保持被包装 handler 的精确签名；`Any` 仅停留在第三方动态参数边界，不扩散到 Request、Response、Application use case 或业务 payload。
- 五个正式 Task Monitor handler 全部切换到 typed schema 装饰器，清除全仓 `follow-imports=skip` 口径下的 5 个 untyped decorator 错误。
- URL、`IsAdminUser` 权限、严格查询参数校验、provider 装配、序列化与稳定脱敏错误响应均保持不变。

## 第三百二十八批验证结果

- Task Monitor 正式接口、API 与组件回归 `47 passed`；并发运行时一次 Windows 测试库清理文件锁 warning 对应测试单独重跑 `1 passed` 且无 warning。
- `apps/task_monitor/interface/views.py` 在 governed `follow-imports=skip` 与增量 `follow-imports=silent` 两种 mypy 口径均清零；全仓基线从 `924 errors / 361 files` 收紧为 `919 errors / 360 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百二十九批

- 按“Task Monitor 响应 DTO 一致性 × Serializer 泛型边界 × 跨文件类型传播”收口 `apps/task_monitor/interface/serializers.py`。
- Task status、list、health 与 statistics serializers 分别绑定对应 Application DTO；请求 serializer 绑定 `dict[str, str]`，清除五处裸 `Serializer` 泛型，同时避免把动态容器类型扩散到 API 边界。
- dashboard 最近失败任务改为复用完整 `TaskListSerializer`，不再把 `list[TaskStatusResponse]` 作为单实例传给 `TaskStatusSerializer`；dashboard 与列表端点现在共享同一嵌套序列化契约。
- 新增 Application DTO 输出序列化和 task ID 缺失/空白/有效输入校验回归，并更新 dashboard 单元替身以验证正式 list serializer 路径。
- 单文件 mypy 清零后额外执行 DTO + serializer + view 跨文件检查；及时发现并消除只有全模块传播时才暴露的 list/single instance 参数错误，未将其写入债务基线。

## 第三百二十九批验证结果

- Task Monitor serializer 专项、正式 API、组件、管理命令、personal readiness 与 scheduler 最终回归 `237 passed`；跨文件 mypy 与增量 mypy 均清零。
- `apps/task_monitor/interface/serializers.py` 退出债务清单，且 `apps/task_monitor/interface/views.py` 保持零错误；全仓基线从 `919 errors / 360 files` 收紧为 `914 errors / 359 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort 与全仓 debt baseline 刷新通过。

## 第三百三十批

- 按“生产模型回滚原子性 × 活动模型连续可用 × 运维参数失败关闭”收口 Alpha `rollback_model` 管理命令。
- `--to` 与 `--prev` 改为 CLI 互斥且动态调用同样要求恰好选择一个；缺失目标、同时选择、非布尔 `prev`、空白或超长模型名/制品 hash 在数据库访问前抛出 `CommandError`，长度上限直接读取 Registry 模型字段元数据，不复制 schema 数字，也不再打印错误后成功退出。
- 显式目标按模型名与 hash 精确查询并加行锁；previous 模式同时锁定当前活动模型和按创建时间确定的前一版本，无活动模型或无前一版本均失败关闭。
- 删除命令层“先单独停用当前模型、再尝试激活目标”的非原子窗口；完整选择和激活置于外层事务，复用模型自身原子 `activate()`，数据库异常会回滚全部状态，不会留下零活动模型。
- 活动模型按全局唯一约束检查并锁定；成功后才报告被替换模型，显式回滚到已活动目标作为幂等成功处理。
- 数据库失败只报告异常类型，不回显连接信息或底层错误正文；新增模拟后端停用旧模型后抛错的事务回滚与脱敏回归。
- 新增缺失/冲突/空白参数、无活动模型、无前一版本和原子失败恢复测试，并将既有宽松成功契约收紧为非零失败契约。

## 第三百三十批验证结果

- Alpha 模型命令专项 `5 passed`；Alpha 单元、模型训练组件与运维 API 回归 `87 passed`，仅有一条未改动 Qlib pandas 兼容层 `DataFrame.groupby(axis=...)` FutureWarning。
- `apps/alpha/management/commands/rollback_model.py` 在 governed 与增量 mypy 两种口径均清零；全仓基线从 `914 errors / 359 files` 收紧为 `907 errors / 358 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十一批

- 按“宏观一致性审计假干净 × 全表内存放大 × 部署门禁失败关闭”收口 Data Center `audit_macro_fact_consistency` 管理命令。
- tolerance 统一执行 failover 契约的有限 `[0, 1]` 校验；负数、超过 100%、`NaN/Inf`、布尔伪装或不可解析值在查询前失败，不再让 `NaN` 比较把异常来源静默判成一致。
- strict 只接受真实布尔值，max-examples 只接受非布尔非负整数；负数不再被静默钳为 0，动态调用者不能用字符串或浮点绕过 CLI 类型。
- 宏观事实改为按 `indicator_code/reporting_period/id` 排序后分块迭代，每次只保留一个指标的事实；冲突总数完整累加，但每类证据最多保留 max-examples 条，内存占用从“全表事实 + 全部冲突”收敛为“单指标事实 + 有界证据”。
- Catalog 与 Fact JSON metadata 必须是字符串键 object，指标代码、来源和数值必须非空且有限；损坏边界直接非零退出，不再被解释为未治理但无冲突的数据。
- QuerySet 流式迭代器显式关闭，异常路径不会把 SQLite/数据库游标留到连接关闭后再清理；ORM 模型仅在局部边界 cast 到 Domain preference protocol。
- 数据库、解析和 JSON 序列化失败只报告异常类型，JSON 输出禁止 NaN；strict 阻断范围继续保持“未治理跨源冲突或治理来源缺失”，未改变既有 canonical/legacy 报告语义。
- 修复 `compute_rate_of_change` 对 previous `None` 的显式收窄，Domain rules 同步保持增量 mypy 零错误。
- 新增 9 类非法参数前置短路、完整计数/有界证据、损坏 metadata 和数据库异常脱敏回归。

## 第三百三十一批验证结果

- Macro consistency 命令专项 `14 passed`；命令、选择规则与 Phase 2 rules 回归 `51 passed`；Data Center 全量 unit/component 回归 `369 passed`。
- `apps/data_center/management/commands/audit_macro_fact_consistency.py` 与 `apps/data_center/domain/rules.py` 在跨层及增量 mypy 口径均清零；全仓基线从 `907 errors / 358 files` 收紧为 `899 errors / 356 files`，净减少 `8 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十二批

- 按“数据库配置防覆盖 × 跨 App 初始化原子性 × 默认数据唯一代码真源”收口 Equity `init_equity_config` 管理命令。
- 命令默认从 upsert 改为只创建缺失规则：匹配的股票筛选、板块偏好和基金类型偏好保留数据库现值；只有显式 `--force` 才重置为 bootstrap 默认，动态调用的 truthy 字符串等非布尔值在构造 Repository 前拒绝。
- Repository 写入返回 `created/updated/preserved` 精确状态，并以显式 overwrite 参数区分初始化与治理更新；既有 Application interface service 保持 upsert 默认语义，避免无关调用面行为漂移。
- 4 条股票规则、13 条板块偏好和 7 条基金偏好全部置于同一数据库事务；任一后续类别失败会回滚此前写入，命令仅报告数据库异常类型且不打印“初始化完成”。
- 命令输出稳定的 total/created/updated/preserved 汇总，让冷启动补缺失与人工强制重置可审计，不再把“已存在且保留”混同为已重新初始化。
- 删除 `apps/equity/interface/__init__.py` 中错误放置的完整管理命令副本，Interface 包根恢复无业务副作用；`scripts/init_equity_config.py` 改为只委托正式管理命令，不再维护第三份金融默认配置。
- 缺失规则提示统一指向 `python manage.py init_equity_config`；默认 seed 仍只负责首次写入，运行时真源保持数据库/Admin 配置。
- 新增默认保留、显式强制覆盖、三类计数、中途数据库失败整批回滚与脱敏、非布尔 force 前置短路、Interface 导入纯净和兼容脚本委托回归。

## 第三百三十二批验证结果

- Equity 初始化与 Repository 专项 `21 passed`；Equity 全模块、API、组件以及账户冷启动/调度初始化回归 `307 passed`。
- `apps/equity/management/commands/init_equity_config.py` 与 `apps/equity/interface/__init__.py` 退出债务清单，其余改动生产文件保持两种 mypy 口径零错误；全仓基线从 `899 errors / 356 files` 收紧为 `884 errors / 354 files`，净减少 `15 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十三批

- 按“生产初始化假成功 × legacy import 副作用 × 正式冷启动编排唯一入口”收口 Core `init_production` 管理命令。
- 盘点确认原命令列出的 11 个 `scripts/init_*` 模块均只在 `__main__` 分支调用初始化函数；import/reload 不执行任何步骤，但原命令仍逐项累计 succeeded 并输出完成。
- 删除把模块可导入误当成初始化完成的循环，`init_production` 现在只委托已有 `bootstrap_cold_start`；正式编排器按数据库 readiness 检查逐项 apply/skip，并传播必需步骤失败，同时覆盖当前账户、Regime、Audit、Equity、Prompt、Scheduler、RSS、宏观治理、Rotation、Hedge、Factor 与决策参数配置。
- `--dry-run` 改为展示实际将执行的 `python manage.py bootstrap_cold_start` 且不调用任何初始化；动态非布尔值前置拒绝。
- legacy `--skip` 无法安全映射到 readiness 编排，非空值明确失败并引导直接使用正式命令，不再以部分 import 制造虚假成功；错误类型和空值同样在委托前校验。
- 子命令 `CommandError` 原样非零传播，只有真实 bootstrap 返回后才打印 `Production initialization complete`。
- 新增单次委托、dry-run 零副作用、非法动态参数、legacy skip 拒绝和下游失败不得打印成功回归。

## 第三百三十三批验证结果

- Production init、账户 cold-start 与 scheduler 初始化专项 `42 passed`；Core、初始化链路和 Equity bootstrap 扩展回归 `95 passed`。
- 实际执行 `python manage.py init_production --dry-run` 只输出正式 bootstrap 命令且零退出；`core/management/commands/init_production.py` 两种 mypy 口径均清零。
- 全仓基线从 `884 errors / 354 files` 收紧为 `882 errors / 353 files`，净减少 `2 errors / 1 file`；Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十四批

- 按“失败事件重复执行 × 状态迁移竞态 × 决策同步部分提交”收口 Events 失败事件仓储与执行状态同步。
- 待重试事件从普通状态覆盖改为数据库条件领取：只有已到期的 `PENDING` 行能够原子迁移到 `RETRYING`；并发或陈旧 DTO 领取失败时不执行 handler，避免同一失败事件被重复消费。
- 成功迁移只接受当前 `RETRYING` 行；失败计数在事务内通过 `select_for_update` 锁定并递增，耗尽状态从数据库持久化的 `retry_count/max_retries` 推导，不再信任调用方的陈旧计数提示。
- 重试 ID、查询上限、保留天数、处理器 ID、状态、最大重试次数和时间戳增加持久化边界校验；时间戳必须具备时区，零或负保留期在删除前失败关闭，清理仅覆盖过期的 `SUCCESS/EXHAUSTED` 终态记录。
- `EventRetryManager` 验证正整数重试参数，领取失败立即短路；成功或失败结果无法持久化时显式返回失败并记录稳定日志，不再继续报告处理完成。
- 决策请求与 Alpha 候选执行状态同步改为在同一事务内检查两次写入结果；任一 Repository 返回 false 时在事务内部抛出私有回滚哨兵，避免请求已更新而候选未更新的部分提交。
- 跨 App Repository 依赖改用 Domain Protocol 精确标注，显式保留注入的 falsey 替身；失败同步日志不再输出原始执行错误正文，避免敏感券商信息进入日志。
- 新增并发独占领取、条件成功、陈旧 DTO 单次执行、持久化计数耗尽、安全保留期、非法边界输入和同步回滚时机回归。

## 第三百三十四批验证结果

- Events 仓储与同步定向回归 `28 passed`；Events Application、任务、决策执行工作流、组件与 API 扩展回归 `98 passed`。
- `apps/events/application/event_retry.py` 与 `apps/events/infrastructure/repositories.py` 在跨文件及增量 mypy 口径均清零；全仓基线从 `882 errors / 353 files` 收紧为 `875 errors / 352 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十五批

- 按“Prompt 冷启动假成功 × 跨类别部分写入 × 默认模板多份真源”收口 Prompt 初始化链路。
- 正式 `init_prompt_templates` 命令将模板与链配置写入置于同一数据库事务；任一 fixture、查询或 Repository 写入失败时整批回滚并抛出脱敏 `CommandError`，不再逐条打印原始异常后继续报告初始化完成。
- Repository 更新返回 `None` 或持久化对象缺少主键时视为拒绝写入并失败关闭；默认模式继续保留数据库既有记录，`--force` 继续原地更新，不恢复删除重建行为。
- `force/chains_only/templates_only/dry_run` 对动态调用执行严格布尔校验，两个 only 参数同时启用时在数据库访问前拒绝；模板与链配置分别报告 loaded/skipped，链跳过数不再误计入模板汇总。
- 删除 `apps.prompt.interface` 包根对管理命令、fixtures、Repository 与 ORM 的兼容导出，HTTP interface 导入恢复无管理副作用；测试与调用统一指向正式 management command。
- 删除 `apps.prompt.infrastructure.adapters.__init__` 中误复制的 39KB 完整 fixtures；导入任一外部 adapter 不再执行模板构造代码，预置模板唯一真源保持 `infrastructure/fixtures/templates.py`。
- `scripts/init_prompt_templates.py` 删除第三份硬编码默认模板与直接 ORM upsert，只在显式执行时初始化 Django 并以 `force=True` 委托正式管理命令。
- 新增严格参数、互斥 scope、异常脱敏、不得打印成功、模板更新后链失败整批回滚、Interface/Adapters 包纯净和兼容脚本委托回归。

## 第三百三十五批验证结果

- Prompt 初始化与包边界定向回归 `12 passed`，Adapters 依赖边界专项 `9 passed`；Prompt Domain、Application、组件、API、初始化与 AI owner 扩展回归 `125 passed`。
- `apps/prompt/interface/__init__.py`、`apps/prompt/infrastructure/adapters/__init__.py` 与正式初始化命令在 governed 及增量 mypy 口径均清零；全仓基线从 `875 errors / 352 files` 收紧为 `862 errors / 350 files`，净减少 `13 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；实际 dry-run 因当前工作树本地数据库尚未执行 Prompt 两个 migration 而按预期非零失败，测试数据库已验证真实事务回滚。

## 第三百三十六批

- 按“管理命令导入 HTTP 副作用 × MCP 页面重复实现 × 正式 Interface 唯一入口”收口 `apps.ai_capability.management` 包初始化文件。
- 删除 management 包根中误放的旧 MCP tools 页面、同步与开关 handler；Django 导入任一 AI Capability 管理命令时不再加载消息框架、认证 decorators、账户 Interface、Capability ORM 与页面查询逻辑。
- 正式页面继续唯一归属 `apps.ai_capability.interface.views`，Core 路由、Application context/query service、治理同步、管理员权限、稳定提示与开关行为均未改动。
- 新增 management 包不得导出 HTTP handler、正式 Interface handler 归属和四个 AI Capability 管理命令仍可发现的边界回归。

## 第三百三十六批验证结果

- Management 包、MCP tools 页面、权限与命令发现定向回归 `9 passed`；AI Capability Domain、Application、MCP catalog、组件、API 与页面扩展回归 `716 passed`。
- `apps/ai_capability/management/__init__.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `862 errors / 350 files` 收紧为 `856 errors / 349 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十七批

- 按“实时单价伪造历史 × 对冲相关性输入污染 × 缓存跨范围串用”收口 Hedge 历史价格 adapter 与 failover。
- 删除 `CachedHedgeAdapter` 把单个实时价格重复 N 次充当历史序列的逻辑；缺少真实历史或精确 last-known-good 缓存时返回 `None`，由相关性、beta、有效性与绩效用例按既有契约失败关闭。
- 缓存键升级为资产代码、截止日与窗口长度的稳定 hash 精确范围；payload 同时保存并核验 scope metadata，旧裸 list、范围不匹配、损坏结构、布尔、非数值、非有限、零或负价格全部拒绝。
- last-known-good 写入执行 round-trip 校验，回读不一致时删除当前键；缓存异常只记录异常类型且不阻断已经取得的真实持久化价格。
- Tushare/Akshare 兼容 adapter 统一读取 Data Center `PriceBarRepositoryProtocol`，按日期升序返回真实收盘价；Repository 可注入，资产、纯 `date` 截止日和大于 1 的窗口在 I/O 前严格校验。
- Failover 对每个来源返回值再次执行有限正数序列收窄，非法来源结果不能进入计算或缓存；日志不再回显底层异常正文，singleton 与各构造函数补齐精确类型。
- 新增缓存范围隔离、旧/损坏缓存拒绝、非法来源跳过、真实 bars 顺序和动态参数前置拒绝回归。

## 第三百三十七批验证结果

- Hedge adapter、只读相关性和降级日志定向回归 `14 passed`；Hedge Domain、Application、组件、API 与 AI Capability catalog 扩展回归 `117 passed`。
- `apps/hedge/infrastructure/adapters/__init__.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `856 errors / 349 files` 收紧为 `849 errors / 348 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十八批

- 按“Dashboard Admin 未被自动发现 × 注册入口层级错误 × Admin 类型规范”收口 Dashboard 五个模型的后台入口。
- 盘点确认全部 `@admin.register` 只存在于 `apps/dashboard/infrastructure/admin.py`，但 App 无根 `admin.py` 且 `AppConfig.ready()` 不导入该模块；Django Admin autodiscovery 因此不会加载这些注册。
- 将唯一实现迁移到标准 `apps/dashboard/admin.py` 根入口并删除 Infrastructure Admin；Dashboard config、用户 config、card、alert 与 snapshot 五个模型现在均由 Django 正式发现且只注册一次。
- 五个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`，handler 补齐精确模型、`HttpRequest` 与返回类型；严重级别和快照大小改用 `@admin.display`，删除动态 `short_description` 元数据。
- Snapshot Admin 继续禁止手工创建和修改；severity badge、fieldsets、筛选、搜索、只读字段与其余运营行为保持不变。
- 新增五模型根入口注册、typed Admin 继承和 Snapshot 不可变权限回归。

## 第三百三十八批验证结果

- Dashboard Admin 注册专项 `2 passed`；Dashboard Domain、组件与 API 扩展回归 `104 passed`。
- 新根 `apps/dashboard/admin.py` 在 typed Admin 基座联合 governed mypy 与增量 mypy 口径均清零；删除旧债务入口后全仓基线从 `849 errors / 348 files` 收紧为 `838 errors / 347 files`，净减少 `11 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百三十九批

- 按“置信度默认值多份真源 × 多活动配置歧义 × 刷新部分写入”收口 Audit `init_confidence_config` 管理命令。
- 删除命令内复制的 16 项默认配置数值，初始化和显式 refresh 统一从 `ConfidenceConfigModel` 字段默认值派生；模型 schema 成为 bootstrap 默认唯一代码真源，数据库活动行继续作为运行时真源。
- schema 默认在数据库访问前验证：系数/加成/阈值必须有限且处于业务范围，新鲜度系数必须非递增，日/月混合权重必须合计为 1，持续天数必须为非布尔正整数，改进奖励必须位于受控范围。
- 默认调用只创建缺失配置并保留既有活动行；只有显式 `--refresh` 才重置唯一活动配置，动态 truthy 字符串等非布尔参数在 seed 构造与数据库访问前拒绝。
- 活动配置查询加入事务与行锁；发现两个及以上活动行时失败关闭，不再由 `.get()` 暴露不稳定底层异常或随机选择治理真源。
- 创建与 refresh 均执行 `full_clean` 并在同一事务提交；校验或数据库异常整笔回滚，只报告异常类型且不输出成功文案或底层连接/凭据正文。
- Django model metadata 的 Field/Relation 动态联合通过局部 Protocol 收窄，`Any` 不扩散到配置 payload；输出只在事务成功后读取已持久化模型。
- 新增 schema 默认派生、多活动配置拒绝、写后数据库异常回滚与脱敏、动态 refresh 前置拒绝回归。

## 第三百三十九批验证结果

- Confidence 配置与财务配置命令定向回归 `7 passed`；Audit Domain、Application、组件与 API 扩展回归 `337 passed`。
- `apps/audit/management/commands/init_confidence_config.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `838 errors / 347 files` 收紧为 `832 errors / 346 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十批

- 按“Fund Admin 未被自动发现 × 六模型运营入口缺失 × Admin 类型规范”收口 Fund 后台注册。
- 盘点确认六组 `@admin.register` 仅存在于 `apps/fund/interface/admin.py`，但 App 无根 `admin.py` 且 `FundConfig.ready()` 不导入 Interface Admin；Django autodiscovery 不会加载基金基本信息、经理、净值、持仓、行业配置与业绩后台。
- 新增标准 `apps/fund/admin.py` 纯副作用桥接作为唯一自动发现入口，正式实现继续归属 Interface 层；未复制注册类，也未在 Infrastructure 新增第二入口。
- 六个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`；基金规模与持仓市值 handler 补齐精确模型和字符串返回类型，并使用 `@admin.display(description=..., ordering=...)` 删除动态 `short_description`。
- 金额展示继续以模型 canonical 元单位“元”换算为万/亿，仅修复注册可达性与类型契约，不改变列表、筛选、搜索、fieldsets 或数据库字段。
- 新增六模型已注册、唯一 typed Admin owner 与元单位展示回归。

## 第三百四十批验证结果

- Fund Admin 注册与金额显示专项 `2 passed`；Fund Domain、Adapter、Application、组件与 API 扩展回归 `117 passed`，仅保留未改动 Hybrid adapter 对象 repr 缓存键 `CacheKeyWarning` 作为后续独立候选。
- `apps/fund/interface/admin.py` 与根 autodiscovery bridge 在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `832 errors / 346 files` 收紧为 `822 errors / 345 files`，净减少 `10 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十一批

- 按“Fund 缓存键含对象 repr × 跨进程缓存失效 × provider 异常信息泄露”收口 `HybridFundAdapter`。
- 基金列表缓存从 generic decorator 自动拼接 `self` 的对象 repr 改为固定版本化 key `fund:list:em:v1`；key 不再包含内存地址、尖括号或空格，可被 Memcached 接受并由不同 Adapter 实例/进程共享。
- 基金详情与净值缓存使用经严格验证、trim/uppercase 后的六位基金代码构造稳定 exact-code key；空白、路径字符、长度错误、空格和布尔伪装在 provider/cache 前失败关闭。
- pandas 改为 importlib 第三方边界并用局部 DataFrame/Module Protocol 收窄；AKShare/Tushare lazy adapters 使用精确 Protocol，消除动态属性 `Any` 与 untyped import 扩散。
- AKShare/Tushare 返回空 DataFrame 时显式记录 `EmptyData` failure；provider 异常只向健康状态和日志传递异常类型，不再保存或打印可能包含 Token、URL 的原始正文。
- 重试范围从包含冗余裸 `Exception` 收紧为连接、超时与明确的 `DataSourceUnavailable`；健康快照返回 `dict[str, HealthStatus]` 精确契约。
- 新增稳定 key 跨实例命中、Memcached warning 消失和非法基金代码前置拒绝回归。

## 第三百四十一批验证结果

- Hybrid Fund adapter 专项 `11 passed`；Fund Domain、Adapter、Application、组件与 API 扩展回归 `123 passed`，此前对象 repr 缓存键 warning 不再出现。
- `apps/fund/infrastructure/adapters/hybrid_fund_adapter.py` 在 resilience 基座联合 governed mypy 与增量 mypy 口径均清零；全仓基线从 `822 errors / 345 files` 收紧为 `816 errors / 344 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十二批

- 按“Asset Analysis Admin 未被自动发现 × 告警重复解决覆盖审计证据 × 操作者身份失败开放”收口资产分析后台。
- 盘点确认四组 `@admin.register` 仅存在于 `apps/asset_analysis/interface/admin.py`，但 App 无根 `admin.py` 且 `AssetAnalysisConfig.ready()` 未导入；新增标准根 autodiscovery bridge，权重配置、评分缓存、评分日志与分析告警现在由 Interface 唯一实现注册。
- 四个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`；评分日志权限 handler 补齐 `HttpRequest`、精确可空模型与 bool 返回类型，继续禁止人工新增和修改。
- 告警批量动作使用 `@admin.action`、`HttpRequest` 与 `QuerySet[AssetAnalysisAlert]` 精确契约；删除动态 `short_description`。
- 动作必须由已认证且具有非空持久化主键的操作者执行，否则抛出 `PermissionDenied`；`resolved_by` 不再允许匿名/临时身份写入空审计标识。
- 更新范围收紧为 `is_resolved=False`，重复操作不会覆盖终态告警原始 `resolved_at/resolved_by`，提示数量只统计本次真实状态迁移。
- 新增四模型唯一 typed 注册、未解决告警单次迁移、终态审计字段保持以及匿名/无主键操作者拒绝回归。

## 第三百四十二批验证结果

- Asset Analysis Admin 注册、身份与状态迁移专项 `4 passed`；Asset Analysis Domain、Application、组件与 API 扩展回归 `76 passed`。
- `apps/asset_analysis/interface/admin.py` 与根 autodiscovery bridge 在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `816 errors / 344 files` 收紧为 `808 errors / 343 files`，净减少 `8 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十三批

- 按“Terminal Admin 未被自动发现 × Runtime Settings 权限绕过 × 审计日志可删除”收口 Terminal 后台治理入口。
- 盘点确认三组注册仅存在于 `apps/terminal/interface/admin.py`，但 App 无根 `admin.py` 且 `TerminalConfig.ready()` 未导入；新增标准 autodiscovery bridge，命令配置、审计日志与 runtime singleton 现在由 Interface 唯一实现注册。
- 三个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`，权限 handler 补齐 `HttpRequest`、精确可空模型与 bool 返回类型。
- Terminal Audit Log 继续禁止人工新增和修改，并新增 `has_delete_permission=False`；运维人员不能通过 Admin 删除 Terminal 命令执行、确认、结果与错误审计证据。
- Runtime Settings `has_add_permission` 先执行 Django 原生模型 add permission，再检查 singleton 是否缺失；普通 staff 即使当前无配置也不能绕过授权创建系统级聊天范围配置。
- Runtime Settings singleton 继续禁止删除；已有用户仍按 Django change 权限修改，不扩大操作权限。
- 新增三模型唯一 typed 注册、审计记录全不可变、无 add 权限 staff 拒绝、superuser + singleton 状态组合回归。

## 第三百四十三批验证结果

- Terminal Admin 注册与权限专项 `3 passed`；TUI workbench 与 Terminal Agent 固定最小回归包 `208 passed`。
- `apps/terminal/interface/admin.py` 与根 autodiscovery bridge 在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `808 errors / 343 files` 收紧为 `801 errors / 342 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未触碰 MCP、SDK 或部署实现，无额外未验证固定链路。

## 第三百四十四批

- 按“Share Admin 未被自动发现 × 公开访问审计可篡改/删除 × singleton 权限绕过”收口分享后台治理。
- 盘点确认四组注册仅存在于 `apps/share/interface/admin.py`，但 App 无根 `admin.py` 且 `ShareConfig` 不导入；新增标准 autodiscovery bridge，分享链接、快照、访问日志和免责声明配置现在由 Interface 唯一实现注册。
- 删除动态 `django_apps.get_model` 类型边界，改用 App 根模型导出并让四个 Admin 继承 `TypedModelAdmin[ConcreteModel]`，不新增 Interface 对 Infrastructure 的越层 import。
- 分享链接禁止从 Admin 新建，确保 short code、账户范围和密码始终经过 Application 用例；禁止删除以防级联清除快照与访问日志，`password_hash` 改为只读避免直接写入明文或无效 hash。
- 分享快照与访问日志全部字段只读，并禁止新增、修改和删除；管理员只能查看系统生成的公开分享内容及匿名访问审计证据。
- 免责声明 singleton 新建先执行 Django 原生模型 add permission，再检查配置是否已存在；普通 staff 不能利用空表绕过授权，singleton 继续禁止删除。
- 新增四模型唯一 typed 注册、分享链接创建/删除阻断、密码哈希只读、快照/日志全不可变和免责声明权限组合回归。

## 第三百四十四批验证结果

- Share Admin 注册与权限专项 `3 passed`；Share Domain、Application、模型、页面、组件与 API 扩展回归 `191 passed`。
- `apps/share/interface/admin.py` 与根 autodiscovery bridge 在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `801 errors / 342 files` 收紧为 `795 errors / 341 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十五批

- 按“Pulse Admin 未被自动发现 × 行内配置绕过校验 × 计算日志可篡改”收口 Pulse 运行时配置后台。
- 新增标准根 autodiscovery bridge，Pulse snapshot、指标配置与 Navigator 资产配置现在由 Interface 唯一实现注册；根 `models.py` 补显式 `__all__`，严格模式与 Django 模型发现共享同一导出契约。
- 三个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`；指标与 Navigator 使用 `TypedModelForm[ConcreteModel]`，不依赖裸 ModelAdmin/ModelForm。
- 删除指标 `weight/is_active` 和 Navigator `risk_budget/is_active` 的 `list_editable`，禁止 changelist 批量保存绕过专用表单验证与变更审阅。
- 指标权重必须为有限正数，拒绝零、负数、NaN、Inf 与布尔伪装；Navigator 风险预算必须为有限 `[0,1]` 比例，非法值在 Admin 保存前失败。
- PulseLog 全字段只读且禁止新增、修改和删除；计算快照、指标明细、转折原因与来源证据不能由管理员伪造或清除。
- 新增三模型唯一 typed 注册、日志全不可变、非法权重/风险预算拒绝和有效边界接受回归。

## 第三百四十五批验证结果

- Pulse Admin 注册、权限与数值校验专项 `13 passed`；Pulse Domain、Provider、Application、管理命令、组件与 API 扩展回归 `71 passed`。
- `apps/pulse/interface/admin.py`、根 bridge 与显式模型导出在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `795 errors / 341 files` 收紧为 `789 errors / 340 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十六批

- 按“Prompt Admin 未被自动发现 × 活动模板绕过评估门禁 × 对话/执行证据可删除”收口 Prompt 后台治理。
- 删除错误归属 `apps/prompt/infrastructure/admin.py`，实现迁移到 `apps/prompt/interface/admin.py` 并新增标准根 autodiscovery bridge；四个 legacy Prompt 模型现在只有一个正式注册入口。
- 根 `models.py` 补显式 `__all__`，Interface Admin 通过 App 根模型导出取类型，不新增 Interface 对 Infrastructure 的直接依赖。
- 四个 Admin 全部继承 `TypedModelAdmin[ConcreteModel]`；自定义 `PROMPT_EVAL_GATE_ENABLED` 经局部布尔边界读取，兼容严格 Settings stub 与运行时 override。
- evaluation gate 开启时，legacy PromptTemplate Admin 禁止新增和修改，活动模板必须通过 PromptVersion evaluation/promotion 流程；门禁关闭时仍要求 Django 原生模型权限。模板始终禁止删除，避免破坏执行与决策引用。
- PromptExecutionLog 和 ChatSession 全字段只读，并禁止新增、修改和删除；渲染 Prompt、AI 响应、错误、Token/成本、用户消息与上下文证据不能由管理员伪造或清除。
- ChainConfig 继续按 Django 原生权限管理，未改变编排配置业务行为。
- 新增四模型唯一 typed 注册、evaluation gate 开关权限组合和执行/会话证据全不可变回归。

## 第三百四十六批验证结果

- Prompt Admin 注册、门禁与证据权限专项 `3 passed`；Prompt Domain、Application、初始化、组件、API 与 AI owner 扩展回归 `116 passed`。
- 新 Interface Admin、根 bridge 与显式模型导出在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；删除旧 Infrastructure Admin 后全仓基线从 `789 errors / 340 files` 收紧为 `783 errors / 339 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十七批

- 按“Task Monitor 运维证据可篡改/删除 × 动态 Admin 元数据 × 无效查询放大”收口任务监控后台。
- TaskExecution 与 TaskAlert Admin 全部继承 `TypedModelAdmin[ConcreteModel]`，所有 ORM 字段只读，禁止新增、修改和删除；任务参数、结果、异常/traceback、状态、重试、Worker、告警发送结果与 metadata 只能由运行时/Repository 写入。
- TaskExecution 删除自定义 `get_queryset().select_related().annotate(Count(id))`；模型无关联字段且每行 Count 恒为 1，该查询只增加无业务价值的聚合开销。
- 状态、优先级与告警级别展示改用 `@admin.display(description=..., ordering=...)` 和 `SafeString` 精确返回类型，删除动态 `short_description/admin_order_field`。
- badge 继续通过 `format_html` 转义动态 display label，颜色和排序字段保持不变；管理员仍可检索和查看运维证据。
- 删除操作明确引导使用 Repository 分层、有界 retention，不允许通过 Admin 绕过备份前置和分级保留策略。
- 新增两个模型唯一 typed 注册、全不可变权限、HTML 转义和 display ordering metadata 回归。

## 第三百四十七批验证结果

- Task Monitor Admin 专项 `3 passed`；Task Monitor unit/component/API 扩展回归 `54 passed`。并发套件退出时一次 Windows 测试库文件锁 warning 对应备份测试单独重跑 `1 passed` 且无 warning。
- `apps/task_monitor/interface/admin.py` 在 typed Admin 基座联合 governed mypy 及增量 mypy 口径均清零；全仓基线从 `783 errors / 339 files` 收紧为 `774 errors / 338 files`，净减少 `9 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十八批

- 按“非法保留期扩大删除范围 × SQLite VACUUM 备份证据误判 × 无类型调度模型边界”收口 Task Monitor 留存清理仓储。
- `cleanup_old_records` 在任何数据库状态迁移或删除前严格要求非布尔正整数保留天数；零、负数、字符串和布尔伪装全部失败关闭，不能通过未来 cutoff 扩大删除范围，也不会先把运行中任务改为超时。
- SQLite 周期性 VACUUM 的备份前置只接受 26 小时内、非空的 `*.sqlite3` 或 `*.sqlite3.gz` 持久文件；零字节文件、临时文件、PostgreSQL SQL dump、过期文件和无法读取的文件均不能授权 VACUUM。
- `settings.BASE_DIR` 动态边界先收窄为非空路径字符串或 `Path`；无效设置直接视为无备份，保持失败关闭。
- `django-celery-beat` 无类型第三方模型改为 `importlib + Protocol + cast` 局部边界；Repository 的调度展示 helper 使用明确的只读结构契约，不恢复宽泛 `type: ignore`。
- 删除本文件六处已经失效的 Django `import-untyped` 忽略，使真实第三方边界显式可见并让该生产文件退出 mypy 债务清单。
- 新增非法保留期不得修改任何记录、SQLite 备份格式/大小/新鲜度筛选回归。

## 第三百四十八批验证结果

- 留存安全与既有分层清理定向回归 `8 passed`；Task Monitor unit/component/API 扩展回归 `60 passed`。完整套件退出时一次 Windows 测试库文件锁 warning 对应在线备份用例单独重跑 `1 passed` 且无 warning。
- `apps/task_monitor/infrastructure/repositories.py` 在跨文件及增量 mypy 口径均清零；全仓基线从 `774 errors / 338 files` 收紧为 `768 errors / 337 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百四十九批

- 按“陈旧请求释放新锁 × 锁过期后旧任务覆盖新 owner × 投递成功后监控失败导致重复投递”收口 Alpha/Qlib 运维锁生命周期。
- Dashboard Alpha 刷新、批量 scoped inference 与两类 Qlib 数据刷新统一改为不可伪造的 owner token；acquire 返回精确 `LockOwnerToken`，promote/release 必须携带同一 token，陈旧调用只能返回 false，不能修改后继 owner。
- 主锁 claim 与 owner 状态分离：主 claim 及 successor handoff 只通过 cache `add` 原子创建且保持不可变，任务 ID、阶段、绝对 lease 与 metadata 只写 owner 私有状态；无需依赖各缓存后端不一致的 compare-and-delete，也不会因旧 owner 清理窗口删除新锁。
- 释放、任务完成和 lease 过期不再物理覆盖主 claim，而是将当前 generation 转为终态并由下一请求原子领取唯一 successor；跨进程 Redis 与本地 LocMem 共享同一协议，锁链及 registry 物理 TTL 有界为 24 小时。
- Resolver 严格校验 token、owner state、phase、task ID、有限过期时间和 string-key metadata；owner token 不进入页面/API metadata。滚动升级期间继续识别旧 `__pending__`、`__sync__` 和 task-id v1 cache 值；v1 缺少 owner token，终态后不执行可能误删新 claim 的非条件删除，而是等待原 TTL 自然过期。
- 锁 timeout 必须为非布尔正整数，空 lock key、非法 metadata 和空 task ID 在发布/晋升前失败关闭；registry cache 损坏时不再把字符串拆成字符列表。
- Alpha Ops UseCase 与 Dashboard async handler 在任务成功投递后即使 lock promotion 或 Task Monitor pending record 写入失败，也不再释放仍可能运行的任务锁；只有 broker dispatch 尚未成功时才使用自己的 owner token 释放，避免用户重试产生重复任务。
- Dashboard 同步降级路径同样持有 owner token，只有 promotion 成功才执行本地推理，并在 finally 中只释放自己的 generation。
- 新增陈旧 promote/release 隔离、完成/过期 handoff、并发 successor 唯一性、v1 终态不危险删除、token 不外泄、非法 TTL 前置拒绝、监控写入失败保持锁和 broker 投递失败允许安全重试回归。

## 第三百四十九批验证结果

- Alpha Ops owner-token 专项 `11 passed`；Alpha unit、App tests 与 Dashboard Alpha 扩展回归 `167 passed`。
- 扩展回归仅保留既有 Qlib pandas `DataFrame.groupby(axis=...)` FutureWarning，与本批锁逻辑无关。
- `apps/alpha/application/ops_locks.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `768 errors / 337 files` 收紧为 `761 errors / 336 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百五十批

- 按“Prompt 工具注册多份真源 × 趋势结果伪造 × PIT 截止失效 × 工具异常泄密”收口 Prompt/Agent Function Registry 与宏观/Regime 内置工具。
- 将 `FunctionRegistry`、`ToolDefinition`、内置工具 schema 与构造逻辑迁入纯 Domain `function_registry.py` 唯一真源；Domain 包根和 Infrastructure 旧路径仅做显式兼容导出，Application 直接依赖 Domain，不再维护两份行为不同的注册表。
- ToolDefinition 校验 OpenAI 工具名、对象参数 schema、required/properties 勾稽和 callable，并对输入及输出 schema 深复制；调用方或 AI client 修改投影不能污染后续会话的注册定义。
- 指标代码 schema 删除 PMI/CPI 等复制枚举，改由 Data Center 指标目录在实际查询边界治理；工具参数严格校验非空代码、ISO 日期、`1..3650` 天数、受控趋势周期和有界字符串列表，布尔/零/负数/错误 shape 在 provider 前拒绝。
- `get_macro_series` 不再调用 MacroDataAdapter 中不存在的 `_calculate_series_range`；统一从显式 `as_of_date` 与 days 计算窗口。
- `calculate_trend` 不再固定返回 `trend=up`，改为读取真实 PIT 宏观序列，拒绝非有限值并计算 change/change_pct；证据不足时返回 `unknown` 和空数值，不伪造方向。
- 单点宏观查询的 `as_of_date` 改为 `use_pit=True` 的时序截止，同时约束 reporting period 与 published_at；未来才发布的数据不会进入历史 Prompt。
- Regime adapter 查询异常时不再生成固定 `Recovery/复苏/0.65` 模拟状态；内置工具返回稳定 `REGIME_UNAVAILABLE`，避免 AI 基于伪造宏观象限继续判断。
- FunctionRegistry、provider gateway 与 Agent Runtime 的异常结果统一脱敏，只保留稳定 error code、工具/方法名和异常类型；不再返回底层异常正文、原始参数或畸形 JSON，ToolCallRecord 对错误参数只记录稳定 shape 标记。
- Agent structured output 仅接受 string-keyed JSON object，数组和标量不再从声明为 dict 的边界逸出。
- 新增唯一导出身份、schema 隔离、非法参数、异常/Token 脱敏、PIT 发布时间截止、真实趋势和 Regime 失败关闭回归。

## 第三百五十批验证结果

- Prompt 工具注册、宏观 Data Center、Regime/Provider 失败关闭与 Agent Runtime 安全专项 `35 passed`；Prompt/Agent unit、component 与 API 扩展回归 `188 passed`。
- Prompt Domain Registry、两个 Adapter、composition provider、tool execution 与 Agent Runtime 共八个生产文件在联合及增量 mypy 口径均清零；全仓基线从 `761 errors / 336 files` 收紧为 `739 errors / 330 files`，净减少 `22 errors / 6 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百五十一批

- 按“生产覆盖 readiness 配置类型丢失 × truthy/int 强转 × 动态 ORM 日期假阳性”收口 Data Center 诊断查询仓储。
- 活跃股票覆盖质量直接接收已经由 Domain 校验的 `ProductionCoverageUniverseConfig`，不再先降级为 `dict[str, object]` 后对 exchanges 做不可迭代访问或对阈值执行 `int(value or 0)`；零阈值和合法配置语义原样保留。
- 交易所集合与四项最小覆盖阈值从冻结配置实体精确读取；返回的 universe quality 与 fact domain 使用局部 TypedDict，覆盖数量、状态、日期和问题列表不再依赖松散 object。
- 活跃证券代码从 ORM 字符字段显式收窄为字符串；`facts_ready` 固定为 bool，不再在空资产池时产生整数 `0` 的隐式真假值。
- 三类动态 fact model 统一收窄到 Django Model class 并通过 `_default_manager` 查询；latest date 只有真实 `date` 才序列化，无有效日期时即使计数异常也保持 `incomplete`，避免 readiness 把无日期证据标为完成。

## 第三百五十一批验证结果

- Data Center repository 与生产覆盖 universe API 扩展回归 `24 passed`。
- `apps/data_center/infrastructure/diagnostic_queries.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `739 errors / 330 files` 收紧为 `733 errors / 329 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百五十二批

- 按“TUI 编译期合同范围失真 × 动态对象类型误判 × 反向关系误导出 × 非受控 JSON 缩进”收口 Terminal Django contract exporter。
- `app_labels/model_paths/domain_class_paths` 仅在参数为 `None` 时使用默认范围；调用方显式传入空列表时现在得到真正空的模型/聚合合同，不再被 truthy fallback 偷换回 Terminal 默认集合。
- 三类路径统一要求非空字符串、trim 并稳定去重；重复模型或 Domain class 不再生成重复合同节点。
- 动态 model path 必须解析为 Django Model 子类，Domain path 必须解析为 dataclass class；tuple、实例和其他非类型对象在访问 `_meta/__name__` 前以稳定 TypeError 失败关闭。
- Django `_meta.get_fields()` 结果先用真实 `models.Field` 收窄，反向 `ForeignObjectRel` 不再进入普通字段序列化；关系目标仅接受 Django Model class，避免 string/None related model 触发错误合同。
- choices 使用 Django `flatchoices` 输出，分组选项不会被错误序列化为组名和值列表字符串。
- JSON indent 严格限制为非布尔 `0..8` 整数，并在创建目录/文件前校验；负数、布尔和超大缩进不能产生异常或放大的编译产物。
- 新增显式空范围、非模型/非 dataclass 路径、重复路径与非法 indent 不落盘回归。

## 第三百五十二批验证结果

- TUI Django contract 专项 `9 passed`；TUI workbench、Terminal Agent、SDK client、内部 SSL redirect 固定回归包合计 `245 passed`。
- `apps/terminal/infrastructure/tui_contract_export.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `733 errors / 329 files` 收紧为 `728 errors / 328 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 MCP 或部署实现，无未验证固定链路。

## 第三百五十三批

- 按“Tushare 非有限行情污染 × 历史 K 线 OHLC 失真 × 非法 scope 触发外部调用 × 市场后缀丢失”收口 Data Center Tushare 市场网关。
- Decimal 边界拒绝 bool、NaN 与正负 Infinity；整数边界通过共享 `safe_float` 收窄，只接受非负整数，负数、分数成交量和非有限值不再被截断后进入标准行情实体。
- 历史查询在创建 Tushare/Tencent client 前严格校验六位证券代码、可选 `SH/SZ/BJ` 后缀、`YYYYMMDD` 日期及 `start <= end`；非法输入直接返回空结果，不再向任何外部 provider 发送畸形请求或触发无意义 failover。
- Tushare SDK 动态 client 与 DataFrame/row 使用局部 Protocol 收窄，三类 daily endpoint 返回值不再以 Any 穿透网关。
- 每条历史 bar 必须具备合法日期、有限正 OHLC，且 `high >= open/low/close`、`low <= open/high/close`；损坏行被逐条隔离，负 amount 转为空，合法行继续返回。
- 历史结果的 `asset_code` 改为规范 Tushare code，保留市场后缀而不再退化成裸六位代码；无后缀北交所 `4/8/92` 代码补齐 `.BJ`，沪深股票和 ETF 规则保持不变。
- 腾讯 failover 返回值重新验证为完整 `HistoricalPriceBar` 列表；第三方返回混合/错误 shape 时失败关闭。
- 新增非有限/分数数值、北交所映射、非法 scope 无外部调用、损坏 OHLC 隔离和规范代码保持回归。

## 第三百五十三批验证结果

- Tushare/QMT gateway 与资产分类专项 `35 passed`；Data Center 全量单元回归 `298 passed`。
- `apps/data_center/infrastructure/gateways/tushare_gateway.py` 在 governed 与增量 mypy 口径均清零；全仓基线从 `728 errors / 328 files` 收紧为 `724 errors / 327 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过。

## 第三百五十四批

- 按“跨模块资产名称缓存污染 × 来源越界返回 × 代码大小写分裂 × 异常信息泄露”收口 Asset Analysis 公共名称解析链。
- 所有输入代码统一 trim/uppercase、限制长度并拒绝内嵌空白，再按首次出现顺序去重；大小写或首尾空格差异不再形成多个查询、缓存 key 或返回键。
- equity/fund/rotation/fund-holding/index resolver 返回值统一经过边界验证：只接受本次请求 scope 内的规范代码和非空、长度受控字符串名称；额外代码、空名称、非字符串值与同一规范代码的冲突名称全部拒绝。
- 名称缓存升级为 `asset_names:v5`，payload 显式包含 version、排序后的精确 scope 与 names；旧裸 dict、scope 不匹配、额外代码、损坏 shape 均不能命中，避免跨批次或伪造缓存向 TUI/Dashboard/Signal 扩散。
- `resolve_asset_names_read_only` 在损坏 cache miss 后仍只查来源、不执行 cache set；普通解析写入隔离副本，调用方修改返回 mapping 不会改变已保存 payload。
- 单代码解析和 enrichment 统一使用规范键；原有名称字段继续优先保留，缺失名称使用规范资产代码回退。
- cache/provider 异常日志只记录异常类型，不再包含数据库、远端响应或凭据正文。
- Application repository provider 补齐精确返回类型与显式公共导出，asset-name facade 不再依赖 mypy 隐式 re-export。
- 新增来源 scope/shape、代码规范化、损坏缓存、精确缓存 payload、只读不写入和异常脱敏回归。

## 第三百五十四批验证结果

- 资产名称缓存与来源边界专项及既有组件回归 `15 passed`；Asset Analysis、Dashboard guardrail、Signal 与 TUI workbench 扩展回归 `255 passed`。
- 名称 resolver、Application repository provider 与公共 facade 三个生产文件在联合及增量 mypy 口径均清零；全仓基线从 `724 errors / 327 files` 收紧为 `714 errors / 324 files`，净减少 `10 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal Agent、MCP、SDK 或部署实现。

## 第三百五十五批

- 按“伪造价格来源/日期 × 非有限或非正价格进入建仓 × 畸形代码触发数据查询 × 硬编码资产健康探测”收口 Account 市场价格服务。
- 新增 Account 自有 `MarketPriceResult`、`MarketPriceMetadata` 与 provider/service Protocol；Account Application 不再以 `Any` 接收 Simulated Trading provider，也不直接依赖 Data Center 具体结果类，避免 Django autodiscovery 循环导入。
- Simulated Trading adapter 将 Data Center 已验证的 canonical result 映射为 Account DTO，真实保留 `source/as_of/freshness/is_fallback`；Account metadata 不再硬编码 `DataCenterPriceProvider` 或用当天日期冒充行情日期，`timestamp` 只表达本次获取时间。
- provider 返回必须是请求范围内的 Account canonical result；代码不匹配、历史日期不匹配、错误 shape、非正或非有限价格全部失败关闭。来源必须非空、长度受控且无换行，provider 异常日志只保留异常类型，不泄露底层错误正文。
- 缓存 TTL 必须为非布尔正整数；资产代码在任何 provider I/O 前完成严格格式校验和市场规范化，补齐 `92xxxx.BJ`，拒绝未知后缀与任意字符串。
- 批量查询限制为最多 500 项，先验证完整 scope，再按规范代码稳定去重；同一资产的裸代码、大小写和空格变体只查询一次，同时保留请求键映射。
- `is_available` 改为无行情请求的 provider 配置就绪检查，不再依赖硬编码 `000001.SZ` 及实时数据是否恰好存在。
- 新增 TTL、NaN/Inf/零/负数、来源审计、畸形 scope 无 I/O、跨资产结果隔离、批量去重、异常脱敏和 Data Center 元数据无损映射回归。

## 第三百五十五批验证结果

- Account 市场价格与 Simulated Trading adapter 专项 `51 passed`；持仓价格 Data Center 集成链 `19 passed`；Unified Price 与持仓失效检查扩展回归 `25 passed`。
- Account 全量单元回归除既有仓储结构预算外 `108 passed`；唯一失败为未改动的 `apps/account/infrastructure/repositories.py` 已有 `1040` 个非空行，超过既有 `1000` 行预算，与本批价格链改动无关，留待独立仓储拆分批次处理。
- 新 Account 价格合同、gateway、价格服务、Simulated Trading adapter/account gateway 与 Account use case 在联合及增量 mypy 口径均清零；全仓基线从 `714 errors / 324 files` 收紧为 `711 errors / 323 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、MCP、SDK 或部署实现。

## 第三百五十六批

- 按“Account 仓储聚合文件超预算 × 价格重估混用 Decimal/float × 单行异常泄露底层正文”收口资产元数据仓储。
- 将 `AssetMetadataRepository` 从兼容聚合文件迁入独立 `asset_metadata_repository.py` owner module；旧 `repositories.py` 继续保持同一类对象的兼容导出，既有 Application、组件和测试导入路径无需迁移。
- 仓储结构契约新增 owner identity 和 300 行模块预算；聚合文件从 `1040` 降至 `927` 个非空行，新 owner module 为 `127` 行，关闭既有 1000 行预算失败并保留单向依赖。
- 持仓重估将 ORM `FloatField` shares 在边界转换为 Decimal，市值、未实现盈亏和收益率全部使用 Decimal 完成计算后再为 FloatField 收窄；不再执行运行时会失败的 `Decimal * float`。
- 价格、份额和平均成本必须为正有限数；损坏持仓只隔离当前行，不写入部分估值。价格不可用或单行异常日志只记录 position id 与异常类型，不再输出底层异常正文或资产数据。
- 新增精确估值、非有限份额拒绝、逐行异常脱敏、owner 导出身份和模块预算回归。

## 第三百五十六批验证结果

- 仓储结构与资产重估专项 `6 passed`；Account 全量单元回归 `123 passed`；Data Center 建仓、手工成交同步、Dashboard 与宏观配置兼容扩展包 `40 passed`。
- 扩展包中另有一个与本批无关的既有测试夹具失败：`test_macro_sizing_config_repository_returns_active_config` 在迁移已创建 active row 后再次直接创建 active row，触发 SQLite 唯一约束；单独重跑结果相同，本批未修改该模型、迁移或测试。
- 新资产元数据 owner module 与兼容聚合仓储在联合及增量 mypy 口径均清零；全仓基线从 `711 errors / 323 files` 收紧为 `710 errors / 322 files`，净减少 `1 error / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、MCP、SDK 或部署实现。

## 第三百五十七批

- 按“Filter 参数可绕过 API 校验直写 × Kalman 负方差持久化 × float 默认值/状态转换精度漂移 × ORM 模型无类型边界”收口滤波配置与状态模型。
- `FilterConfig` 的 HP lambda、Kalman level/slope variance 必须为非负有限数，observation variance 必须为正有限数；Model `clean()` 复用 Domain 参数实体执行同口径校验，Admin/ModelForm 与 Repository `full_clean()` 路径均失败关闭。
- 新增六项数据库 CheckConstraint；即使调用方跳过 Model validation 直接 `objects.create/update`，负平滑参数、负过程方差和零/负观测方差也不能进入配置或 Kalman 状态表。
- FilterConfig 四项 DecimalField 默认值改用 Decimal 真源，避免二进制 float 默认值进入迁移与 ORM；新增 `0003_filter_parameter_constraints`，`makemigrations filter --check --dry-run` 确认模型与迁移一致。
- Kalman Domain state 转 ORM 时统一通过 `Decimal(str(value))` 收窄，复制 params 后执行完整模型校验；非 JSON 参数、非有限状态和负 variance 在删除/保存状态前拒绝，合法状态可无精度噪声往返。
- 四个模型字符串方法、Domain 转换与 class factory 补齐精确参数/返回类型，裸 `dict` 改为 `dict[str, object]`，模型文件退出 mypy 债务清单。
- 新增 Model/DB 双层非法参数拒绝、有效边界、Decimal 状态往返和直接 ORM 绕过阻断回归。

## 第三百五十七批验证结果

- Filter 模型与数据库约束专项 `10 passed`；Filter API、Domain 算法、Repository 财务真实性、UseCase 与 Dashboard 完整相关回归 `93 passed`。
- `apps/filter/infrastructure/models.py` 在增量 mypy 口径清零；全仓基线从 `710 errors / 322 files` 收紧为 `702 errors / 321 files`，净减少 `8 errors / 1 file`。
- Filter migration drift check、Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、MCP、SDK 或部署实现。

## 第三百五十八批

- 按“Dashboard 告警并发触发丢计数 × 模型公共方法缺少类型合同”收口仪表盘模型。
- `DashboardAlertModel.update_trigger()` 不再读取实例旧值执行 `trigger_count += 1` 后覆盖保存；改由数据库 `F(trigger_count) + 1` 原子更新，同一告警被多个持有陈旧实例的 worker 触发时不会丢事件。
- 原子更新要求模型已持久化且目标行仍存在；无主键实例和更新期间被删除的行明确失败，不制造内存成功假象。更新后实例刷新真实计数，`last_triggered_at` 使用 timezone-aware 时间。
- Dashboard 配置、用户偏好、卡片、告警、快照、自动投顾周报与通知七个模型的字符串方法补齐精确 `str` 返回类型，模型文件退出 mypy 债务清单。
- 新增陈旧双 worker 累计触发与未保存告警拒绝回归。

## 第三百五十八批验证结果

- Dashboard 告警模型、偏好仓储与 API 边界回归 `18 passed`。
- `apps/dashboard/infrastructure/models.py` 在增量 mypy 口径清零；全仓基线从 `702 errors / 321 files` 收紧为 `695 errors / 320 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、MCP、SDK 或部署实现。

## 第三百五十九批

- 按“Dashboard 公共查询结果无类型 × 损坏 Alpha metadata 中断多消费者 × provider 异常泄露到日志/响应”收口 Dashboard Query Services。
- Alpha provider 尝试、fallback 注解和可靠性 metadata 统一使用真实 `AlphaResult`；Dashboard 首页懒加载单例补齐 `AlphaHomepageQuery` 精确类型，页面/API/SDK/MCP 调用链不再从无类型 accessor 取得 Any。
- 动态 provider metadata 只接受 string-keyed mapping；损坏的 `reliability_notice` 列表/字符串降级为空结构，不再触发 `.get()` 异常。用户 fallback 原因只采用有界单行的显式 reliability notice，否则生成稳定“实时 Qlib 未就绪/已触发异步推理”文案。
- 原始 `AlphaResult.error_message` 不再进入 Dashboard fallback metadata；查询层所有降级日志只记录异常类型，Regime warning 与持仓详情错误返回稳定文案，不再暴露数据库、provider、凭据或远端响应正文。
- 删除全仓无调用的动态 `_assign_names_from_rows` helper；证券名称解析保留当前规范化、批量查询和无 N+1 行为。
- 新增损坏嵌套 metadata、provider error 脱敏、持仓详情脱敏与 Regime 降级稳定性回归。

## 第三百五十九批验证结果

- Dashboard Query 安全与 Alpha 查询专项 `41 passed`；Dashboard API、组件 guardrail、SDK Alpha 与 MCP Dashboard 多消费者回归 `43 passed`。
- `apps/dashboard/application/queries.py` 在增量 mypy 口径清零，并同步消除 `query_services.py` 对无类型首页 accessor 的一处调用错误；全仓基线从 `695 errors / 320 files` 收紧为 `688 errors / 319 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI 或部署实现，SDK/MCP 仅执行回归未改代码。

## 第三百六十批

- 按“Auto Advisor 可选账户 scope 松散强转 × 畸形输入触发共享仓储 × 减仓原因动态列表不可索引”收口 Dashboard TUI/runtime Query Services。
- 周报历史与通知查询的可选 `account_id` 在 repository 获取前统一校验：仅接受 `1..2147483647` 的 ASCII 十进制整数；空白等价于未限定账户，负数、零、小数、非数字和越界值稳定失败。
- 非法账户 scope 不再依赖 `int()` 的动态异常或进入共享报告仓储，API、CLI、TUI 与 MCP 复用同一 Application 边界语义。
- 减仓 highlights 明确为 `list[dict[str, Any]]`，首项 reasons 的切片和拼接不再依赖不可索引 union/Any 推断。
- 新增两类查询的非法 scope 无 repository I/O、空白 scope 归一化回归。

## 第三百六十批验证结果

- Dashboard Query Services 安全与 Auto Advisor 输出/控制台组件回归 `26 passed`。
- `apps/dashboard/application/query_services.py` 在增量 mypy 口径清零；全仓基线从 `688 errors / 319 files` 收紧为 `685 errors / 318 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十一批

- 按“请求自定义权重未生效 × 批量评分重复读取配置 × 跨 App 资产类型失真 × 异常详情外泄”收口 Asset Analysis 核心评分链路。
- `ScreenRequest` 内部构造边界与 DRF serializer 对齐：自定义权重必须且只能包含四个标准维度，拒绝 bool、NaN、Inf、越界值和总和失配；`max_count` 严格限制为非布尔 `1..100` 整数。
- 自定义权重现在作为本次请求的实际权重传入批量评分，并原样返回给调用方；未指定权重时每个批次只读取一次 Repository 配置，同一权重对象同时用于全部资产计算与评分日志，不再形成按资产数量增长的重复查询。
- fund/equity/shared 资产对象通过局部 Protocol 动态边界收窄；字符串 style/size 规范化为 `AssetStyle/AssetSize`，自定义分数与数值字段逐项验证，未知 shape、空代码和跨类型对象失败关闭，不再生成后续 `.value` 会崩溃的伪实体。
- 筛选、日志和告警异常只保留稳定用户消息与异常类型，不再把 provider、数据库或凭据正文写入响应和应用日志；错误告警不再持久化原始 traceback。
- 权重配置列表使用 `TypedDict` 仓储/响应合同，并按最高 priority 确定 active 配置；低优先级活动配置不再覆盖先前高优先级结果。
- 多维评分 DTO 补齐既有 API 契约要求的顶层 `total_score`，serializer 保持对旧内部 payload 的兼容。
- 新增自定义权重生效、单批一次配置读取、fund 枚举归一化、未知资产拒绝、异常脱敏、最高优先级选择及内部请求非法边界回归。

## 第三百六十一批验证结果

- Asset Analysis unit/domain/API、fund/equity 集成与评分日志扩展回归 `138 passed`。
- Asset Analysis interfaces、DTO、scoring service 与 use case 四个历史债务文件在联合及增量 mypy 口径清零；全仓基线从 `685 errors / 318 files` 收紧为 `667 errors / 314 files`，净减少 `18 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十二批

- 按“共享评分实体可接受伪数值 × 启动注册异常泄密 × 模块剩余无类型入口”完成 Asset Analysis 模块债务收口。
- `AssetScore` 严格验证资产类型、非空代码/名称、style/size 枚举、sector、score date、risk level 与 string-key context；动态调用不能再把错误 shape 放入冻结 Domain 实体。
- 四项维度分数、综合分数、自定义分数和配置比例全部拒绝 bool、NaN、Inf 与越界值；rank 必须为非布尔非负整数，避免损坏资产进入排序、资产池分类和 API 序列化。
- Asset Analysis AppConfig `ready()` 注册失败日志只记录异常类型，不再输出 registry/provider/凭据正文；保留既有启动降级行为。
- 权重配置 Application facade 返回精确 `WeightConfigsResponse`，Interface 在 DRF 动态构造边界显式投影为普通字典；没有把间接 `arg-type` 回归写入新基线。
- AppConfig、三个 Classic 兼容 redirect handler 补齐精确返回与请求类型，不改变迁移期页面行为。
- 新增资产身份、布尔/非有限分数、自定义分数、负排名和启动日志脱敏回归。

## 第三百六十二批验证结果

- Asset Analysis unit/domain/API、fund/equity 集成、日志与 Classic 路由兼容扩展回归 `172 passed`。
- Domain entity、Application interface service、AppConfig 与 page URL 四个剩余债务文件在增量 mypy 口径清零，Asset Analysis 模块退出全仓债务清单；基线从 `667 errors / 314 files` 收紧为 `658 errors / 310 files`，净减少 `9 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十三批

- 按“Signal 诊断查询不存在字段 × 已失效状态口径 × 不可用证据伪装成零”收口投资信号运维汇总。
- 删除对模型从未定义的 `regime_match_score` 动态字段探测与 ORM filter；诊断查询不再依赖 mypy 无法验证、运行时永远不可达的字段分支。
- 状态统计改用正式 `SignalStatus`：`approved` 计为活跃，`invalidated` 单独统计，`rejected/expired` 计为关闭；不再查询模型 choices 中不存在的 `active/closed` 并长期返回假零。
- 总数和三类状态计数使用单次条件聚合，最近信号使用受控 `only + order_by + slice`，完整汇总固定为两条查询；`recent_limit` 必须为非布尔 `1..100` 整数并在任何查询前拒绝。
- 新增 Domain `SignalDiagnosticSummary`/`RecentSignalDiagnostic` TypedDict，Infrastructure、Application 与运维命令共享精确合同。
- 当前模型没有持久化 Regime 匹配分数时显式发布 `regime_match_available=false`；数据连接命令显示“匹配证据不可用”，不再把不可测量状态描述成“暂无匹配信号”。
- 新增真实状态聚合、固定查询数、非法 limit 零查询和运维文案真实性回归。

## 第三百六十三批验证结果

- Signal 全量单元与数据连接命令扩展回归 `134 passed`。
- `apps/signal/infrastructure/diagnostic_queries.py` 在增量 mypy 口径清零；全仓基线从 `658 errors / 310 files` 收紧为 `657 errors / 309 files`，净减少 `1 error / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十四批

- 按“非法证券代码触发全链数据源 × 非有限价格持久化 fallback × provider 异常泄密”收口 Valuation Application 来源选择链。
- 证券代码在 formal、snapshot、Data Center fact 和行情 provider I/O 前统一 trim/uppercase，并限制为 1..20 位受控资产标识；空白、内嵌空格、超长和非法字符直接返回不可用且零外部调用。
- 同一规范代码贯穿全部来源、fallback 快照与返回合同，避免大小写/空白变体产生跨来源错配或重复持久化。
- fallback 行情必须是正有限 `Decimal`；NaN、Infinity、零、负数和错误类型不能创建或保存估值快照。来源标签必须是非空、长度受控、无控制字符的单行审计标签，污染来源失败关闭。
- 读取或保存后的 fallback 必须属于请求证券、方法为 `FALLBACK`，且六项价格均为正有限 Decimal；损坏持久化结果不能进入推荐链。
- formal/snapshot 有效 payload 返回隔离副本，调用方修改结果不会直接污染来源持有的 mapping。
- 来源异常日志只记录规范证券代码和异常类型，不再输出数据库、provider 响应或凭据正文。
- 拆分 snapshot/fact payload 局部变量，消除 optional dict 赋值债务；新增非法代码零 I/O、非有限价格不落库、来源标签、代码规范化和异常脱敏回归。

## 第三百六十四批验证结果

- Valuation service、Domain 边界、Equity quality gate 与 Unified Recommendation 扩展回归 `67 passed`。
- `apps/valuation/application/use_cases.py` 在增量 mypy 口径清零；全仓基线从 `657 errors / 309 files` 收紧为 `656 errors / 308 files`，净减少 `1 error / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十五批

- 按“Dashboard 动态指标伪趋势 × 非有限图表/告警值 × cooldown 状态不回写”收口仪表盘 Domain 服务。
- 指标路径读取改为 `Mapping -> object` 动态边界，并在展示前收窄为有限 int/float/Decimal、字符串或 None；bool 转为文本状态，NaN/Inf 不再显示为 `nan/infM`。
- 趋势仅在当前值和前值均为非布尔有限数时计算；数字字符串不再被隐式 `float()` 后制造趋势，坏前值稳定返回无趋势。变化率同样拒绝非有限输入。
- 折线图 series 定义只接受非空字符串 name/y_key，非法或重复系列安全忽略；任一系列坏点会隔离整行，X 轴与所有系列保持相同长度。
- 柱状图和饼图只接收具备标签及有限数值的行；缺失值、bool、NaN、Inf 不再被默认成真实零进入用户图表。
- 告警只评估非布尔有限指标和有限阈值；非法 cooldown 配置、损坏或 naive 时间戳失败关闭，不再抛出 aware/naive datetime 比较异常或绕过冷却期。
- 空 cooldown mapping 不再被 truthy fallback 替换；首次触发会回写调用方持有的同一状态对象，后续调用可以真正抑制重复告警。
- `MetricCalculationResult`、DashboardWidget config 和图表 series 局部集合补齐精确类型；新增趋势、非有限展示、图表坏行、告警数值及 cooldown 回写/时区回归。

## 第三百六十五批验证结果

- Dashboard Domain services/rules 与 serializer 扩展回归 `98 passed`。
- `apps/dashboard/domain/services.py` 与 `apps/dashboard/domain/entities.py` 在增量 mypy 口径清零；全仓基线从 `656 errors / 308 files` 收紧为 `653 errors / 306 files`，净减少 `3 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十六批

- 按“Account Position 直接错传 Strategy Protocol × 持仓/总资产不勾稽 × 配置异常泄密”收口 Dashboard 资产配置建议边界。
- Dashboard Application 新增最小 `_AllocationPosition` 与 asset-class value adapter，只向 Strategy 发布规范代码、Decimal 市值和受控资产大类；不再假定完整 Account Domain Position 天然满足跨 App Protocol。
- 总资产必须为非布尔、非负有限数；持仓代码必须为规范受控标识，市值必须为非负有限 Decimal，资产类别只允许 Strategy allocation matrix 正式支持的 equity/fixed_income/commodity/cash。
- fund/currency/derivative/other 等尚未建立显式 allocation 映射的类别失败关闭，不再被 Strategy 汇总遗漏后错误当作现金。
- 持仓市值总和不得超过总资产（保留 0.01 元转换容差）；账实不符时不生成配置比例、调仓金额或收益风险预测，避免 current allocation 合计超过 100%。
- Regime 与风险偏好在 Strategy 调用前校验为正式枚举集合；pending/未知 Policy 继续按既有语义降级为无 Policy 覆盖。
- Strategy 异常日志只记录异常类型，不再输出底层配置、数据库或凭据正文。
- 新增非法总资产不得调用 Strategy、损坏代码/市值/资产类别、持仓超总资产、Domain Position adapter 和异常脱敏回归。

## 第三百六十六批验证结果

- Dashboard allocation safety、Strategy allocation 与 Dashboard guardrail 扩展回归 `24 passed`；首次完整组合运行在 Windows 测试库初始化阶段超过 240 秒上限且无失败输出，按同一范围扩大上限重跑通过。
- `apps/dashboard/application/use_cases.py` 在增量 mypy 口径清零；全仓基线从 `653 errors / 306 files` 收紧为 `652 errors / 305 files`，净减少 `1 error / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十七批

- 按“Decision Workspace 动态参数强转崩页 × 无界导航 token × bool 伪装整数”收口 Dashboard 深链构造器。
- security_code 统一 trim/uppercase 并限制为 1..20 位受控资产标识；空白、内嵌空格、控制字符和超长代码不进入用户链接。
- source 统一为最长 64 位小写 slug，action 统一为最长 32 位大写 token；换行、CRLF、空白和其他非法字符直接省略，不再仅依赖 URL encode 把污染内容带入工作台。
- step 与 account_id 使用共享式本地严格整数边界：只接受非 bool 的正整数或 ASCII 十进制字符串；step 上限 100，账户 ID 上限 `2147483647`，负数、零、小数、Unicode 数字和越界值稳定省略。
- 单个无效参数不会让 `int()` 抛错并中断 Dashboard 页面；其余有效 source/security/action 仍按 canonical 顺序生成链接。
- `build_decision_workspace_url` 的动态入口改为 object 边界并逐项收窄，删除恒假容器比较和两处不安全 int 强转债务。
- 新增 canonical 顺序、非法 account/step 不崩页和污染 token 隔离回归。

## 第三百六十七批验证结果

- Dashboard navigation safety 与既有 Decision Workspace URL/模型注入合同回归 `18 passed`。
- `apps/dashboard/application/navigation.py` 在增量 mypy 口径清零；全仓基线从 `652 errors / 305 files` 收紧为 `649 errors / 304 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十八批

- 按“Exit Watch 仓储属性无类型合同 × 动态仓位/推荐坏数据崩页 × 不安全详情 ID 与异常正文外泄”收口 Dashboard Alpha 退出观察链。
- Exit Watch mixin 显式声明统一推荐与调仓计划 Repository Protocol；`AlphaHomepageQuery` 构造器注入的具体仓储现在具备可验证的 Application 边界，不再依赖宿主类动态属性。
- account/signal ID 只接受非 bool 的正整数或 ASCII 十进制字符串，证券代码统一 trim/uppercase 并限制为受控标识；非法 scope 与代码在推荐、计划和 Signal repository I/O 前隔离。
- 仓位、推荐分数、价格和数量统一拒绝 bool、NaN、Infinity、越界值与宽松数值强转；非有限止损价不能把退出契约错误标记为 ready，损坏 watch item 也不会中断列表排序。
- recommendation/plan ID 通过受控 token 后才进入 API 详情链接；provider 理由、证伪摘要、reason code 与 notes 只发布有界单行字符串，损坏文本失败关闭。
- 调仓计划只接受 timezone-aware datetime `as_of`；最新推荐比较将合法时间统一为 UTC，naive/aware 或错误类型混入时不再抛异常。推荐、计划与 Signal 来源失败日志只保留稳定上下文，不输出底层异常正文。
- 新增非法账户/证券 scope、NaN/Inf、Infinity 止损、危险详情 ID、损坏计划日期、混合时区和异常日志脱敏回归。

## 第三百六十八批验证结果

- Dashboard Alpha Query、Alpha View、Exit Loop、Decision Rhythm Exit Advisor 与结构合同相关回归 `96 passed`。
- `apps/dashboard/application/alpha_homepage_exit_watch.py` 在增量 mypy 口径清零；全仓基线从 `649 errors / 304 files` 收紧为 `647 errors / 303 files`，净减少 `2 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百六十九批

- 按“跨 App API view registry 返回 Any × 兼容委托响应 shape 未验证 × 非法 portfolio/account 映射进入下游”收口账户业绩与估值兼容入口。
- Account Application gateway 新增受控 `AccountViewKey` 与最小 `AccountApiViewClass` Protocol；Simulated Trading 注册端发布精确 view map，14 个 canonical 账户 API URL 与 4 个兼容 API 不再依赖无界 view class Any。
- 框架 view callable 的动态返回值只停留在 gateway/Interface 边界；兼容层必须确认真实 DRF `Response` 后才能回传，错误 shape 与注册表不可用统一返回稳定 503，不把任意对象交给 Django 响应链。
- portfolio ID 与映射后的 unified account ID 必须为 `1..2147483647` 的非 bool 整数；非法路径 scope 或损坏 provider 映射不触发后续 canonical view。
- view registry 解析异常日志只记录 view key 与异常类型，不输出 provider、配置或凭据正文；canonical API 原有账户所有者、管理员与 observer 只读权限检查继续由下游正式视图执行。
- 新增非法 portfolio/mapping、raw request 转发、注册异常脱敏和非 Response 拒绝回归；同步删除因 gateway 合同收紧后已无效的 Django URL import ignore。

## 第三百六十九批验证结果

- Account 兼容委托专项与 canonical/compatibility 业绩 API 集成回归 `64 passed`；API 最小合同 guardrail `23 passed`。
- Application gateway、Account performance compatibility/API URLs 与 Simulated Trading 注册端联合增量 mypy 清零；全仓基线从 `647 errors / 303 files` 收紧为 `639 errors / 301 files`，净减少 `8 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十批

- 按“Admin 文档导入无大小上限 × 异常正文回传 × CSV 公式注入 × 动态请求无类型”收口 Account 文档管理保留流程。
- JSON/CSV 上传限制为最多 5 MB，并在进入 Application service 前执行实际读取长度复核；缺失文件、未知格式、编码/JSON/CSV/字段错误返回稳定 4xx，数据库或服务异常返回稳定 503。
- 导入失败日志只记录异常类型，不再把数据库、文件内容、配置或凭据正文写入响应和日志；删除裸 `Exception` 捕获。
- Admin 排序字段只接受 32 位范围内的精确整数，拒绝 bool、小数、Unicode 数字和越界值；非法输入保留在编辑页并显示稳定校验提示，不再因 `int()` 崩页。
- Markdown 下载使用 RFC 5987 UTF-8 文件名；CSV 导出的公式起始字符统一中和，避免文档标题、摘要或正文被电子表格应用当作公式执行。
- 七个 Django view/helper 补齐 `HttpRequest`、`HttpResponse`、`QueryDict` 和精确 ID 类型；新增上传上限、错误脱敏、严格排序和 CSV 公式隔离回归。

## 第三百七十批验证结果

- Account 文档管理专项、Admin 页面与公共文档 API 集成回归 `46 passed`。
- `apps/account/interface/documentation_views.py` 在增量 mypy 口径清零；全仓基线从 `639 errors / 301 files` 收紧为 `632 errors / 300 files`，净减少 `7 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批只修复既有 retained Admin 流程，未新增 Classic 页面，也未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十一批

- 按“备份下载 token 无界进入校验链 × 动态归档响应未收窄 × 下载 handler 无类型”收口 Account 数据库备份下载入口。
- token 在数据库与 Django signing I/O 前限制为最多 4096 位无空白 ASCII 字符；空值、超长、Unicode 与控制字符统一按无效链接返回 404。
- Application 返回的动态归档必须收窄为非空 bytes、安全单文件名和固定 `application/octet-stream`；路径片段、CRLF、超长文件名、空内容与错误 MIME 不再进入 `FileResponse` header/body。
- 保留既有签名校验、到期、摘要比对、单次原子消费和新链接撤销旧链接语义；下载 handler 补齐 `HttpRequest` 与精确响应类型。
- 新增无界 token 零 service I/O、损坏归档拒绝与合法二进制响应回归。

## 第三百七十一批验证结果

- Account 备份下载专项及加密归档、邮件链接、单次消费、撤销与到期组件回归 `13 passed`。
- `apps/account/interface/backup_views.py` 在增量 mypy 口径清零；全仓基线从 `632 errors / 300 files` 收紧为 `630 errors / 299 files`，净减少 `2 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改备份生成、邮件、数据库配置、Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十二批

- 按“分类循环递归崩溃 × 币种基准/精度可失真 × 非法汇率可绕过 API 直写 × ORM 类型 ignore”收口 Account 分类与汇率模型。
- 资产分类祖先遍历改为带已访问集合的迭代实现；两节点及更深循环失败关闭，不再递归至 `RecursionError`。模型校验同步验证根/子层级、父路径、自引用与循环关系。
- Currency 增加精度 `0..8`、基准货币必须启用及全库最多一个基准货币约束；币种代码在模型边界要求 2 至 10 位大写 ASCII 标识，基准货币查询只返回启用记录。
- Exchange Rate 增加正汇率和源/目标币种不同的数据库约束；仓储 create/update 在保存前执行 `full_clean()`，停用币种、同币种、非正/非有限汇率不能绕过 serializer 进入数据库。
- 金额转换只接受有限 Decimal，币种代码统一 trim/uppercase 并校验；最新汇率与转换查询不再使用停用币种。
- 新增 `0036` migration，在加约束前只读审计既有分类、币种与汇率数据；发现冲突会给出明确违规类别并停止迁移，不静默删除或改写治理数据。
- 数据库约束声明拆入独立 `classification_constraints.py`，原模型 owner 保持 340 行且新模块设置 80 行预算；删除过期 Django import/class ignore 与冗余 cast。

## 第三百七十二批验证结果

- Account 分类/汇率约束专项、完整 API edges、初始化命令、模型与仓储结构回归 `83 passed`。
- `classification_models.py`、约束模块与相关仓储联合增量 mypy 清零；全仓基线从 `630 errors / 299 files` 收紧为 `624 errors / 298 files`，净减少 `6 errors / 1 file`。
- Account migration drift、migration plan、Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十三批

- 按“外部基金事实可写入 NaN/Inf × 非正净值/负持仓 × 越界配置比例 × 模型入口无类型”收口 Fund ORM 真源。
- 新增抽象 `ValidatedFundModel`，所有 Fund model 的 `create/save/update_or_create` 在持久化前执行字段与业务校验；保留数据库 unique 约束原有 `IntegrityError` 契约，不用提前 unique validation 改变调用方行为。
- Decimal 基金规模、净值和持仓市值在校验前按字段声明精度规范化，消除 `Decimal(float)` 尾差；NaN、Infinity、负规模、非正单位/累计净值和非有限日收益失败关闭。
- 基金经理任职结束不得早于开始、任期天数不得为负；持仓数量/市值不得为负，持仓与行业配置比例限制为 `0..100`。
- 业绩窗口要求 `start_date <= end_date`，区间收益、年化收益、波动率、最大回撤、Sharpe、Beta 与 Alpha 全部拒绝非有限数，波动率不得为负；不强行统一现有正/负最大回撤表达口径。
- 新增 11 项数据库 CheckConstraint 保护 QuerySet update/bulk 绕过；`0003` migration 在加约束前只读审计既有 Fund 数据，发现冲突即明确停止且不静默修复投资事实。
- 七个 Fund model 字符串入口补齐 `str` 类型；数据库约束拆入独立 owner 模块，删除模型文件历史 mypy 债务。

## 第三百七十三批验证结果

- Fund 模型专项、Admin、完整 Fund 集成/API、Data Center 同步、资产主数据回填与 Alpha provider 回归 `87 passed`。
- `apps/fund/infrastructure/models.py` 与约束模块联合增量 mypy 清零；全仓基线从 `624 errors / 298 files` 收紧为 `617 errors / 297 files`，净减少 `7 errors / 1 file`。
- Fund migration drift、migration plan、Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十四批

- 按“公开分享计数丢更新 × 访问上限竞态 × 快照/审计坏数据可直写 × 模型入口无类型”收口 Share ORM 与公开访问边界。
- `ShareLinkModel.increment_access_count()` 改为数据库条件更新：仅活动、未过期且未达上限的链接可以原子消费一次访问；陈旧实例连续写入不再丢失计数，未保存实例明确拒绝，失败返回 `False`。
- 运行时可访问性检查对 naive 过期时间失败关闭；最大访问次数统一要求为正数，`0` 不再因分享级别不同而被误当成无限制，并校验账户 ID、短码、访问次数及上限勾稽关系。
- Share Link 增加正账户 ID、非负访问次数、正访问上限与访问次数不超过上限的数据库约束，防止 QuerySet update 等路径绕过模型校验。
- Snapshot 增加正版本号、成对且有序的来源日期约束；模型校验要求五类快照 payload 均为 JSON object、可序列化且不含 NaN/Inf。
- Access Log 状态增加数据库白名单约束；公开 API 在读取后发生访问上限竞态时使用正式 `max_count_exceeded` 审计状态，保留原 `access_limit_reached` 响应文本以兼容调用方。
- Disclaimer 单例键固定为 `default`，lines 限制为有界非空字符串列表；`get_solo()` 会修复已有的 truthy 畸形 JSON，不再只处理空列表。
- 新增 `0005` migration，在加约束前只读审计现有链接计数、快照范围、访问日志状态和免责声明单例键；发现冲突会明确停止迁移，不静默改写历史分享记录。
- 数据库约束拆入独立 `model_constraints.py`，四个字符串入口、模型校验、原子计数和单例读取补齐精确类型，删除 Share 模型文件历史 mypy 债务。

## 第三百七十四批验证结果

- Share Application/Domain/Infrastructure/Interface 全量与安全扩展回归 `180 passed`；其中新增模型完整性专项 `16 passed`，既有模型与视图组合回归 `55 passed`。
- `apps/share/infrastructure/models.py`、约束模块与公开 view 联合增量 mypy 清零；全仓基线从 `617 errors / 297 files` 收紧为 `610 errors / 296 files`，净减少 `7 errors / 1 file`。
- Share migration drift、Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十五批

- 按“Alpha 运维异常正文外泄 × 动态运行配置误入本地 I/O × 任务结果无界发布 × 跨 App provider Any”收口 Alpha/Qlib 运维查询与数据刷新边界。
- Task Monitor 动态 provider 在 Alpha Application 内收窄为正式 `CeleryHealthCheckerProtocol` 与 `TaskRecordRepositoryProtocol`，Celery 健康状态不再通过 Any 传播。
- Celery 健康检查失败只向 staff API/页面发布稳定 `celery_health_check_failed`，结构化日志仅记录异常类型；broker URL、凭据或底层异常正文不再进入响应和普通日志。
- Qlib runtime 仅在 `enabled is True` 时启用；`provider_uri` 必须为非空、长度不超过 4096 且无控制字符的字符串。错误类型、空值、换行和超长路径在 builder/本地日期检查 I/O 前失败关闭。
- 启用 Qlib 但 provider 路径无效时发布 `qlib_provider_uri_invalid`；本地数据检查异常发布 `qlib_data_inspection_failed` 并仅记录异常类型，不再把文件路径、数据库或凭据正文显示在运维页。
- Task Monitor 字符串结果只解析 mapping；非结构化或超长结果统一标记不可用。动态结果限制深度、条目数和文本长度，并递归遮蔽 token/password/secret/credential/DSN/数据库 URL 及 error/exception/traceback 字段。
- 最近任务不再发布持久化的原始 exception，失败只显示稳定 `task_failed`；日期序列化和 runtime config 返回合同同步收窄，清除该文件全部高风险 Any/arg-type 债务。

## 第三百七十五批验证结果

- Alpha 应用、Alpha 单元与运维 API 扩展回归 `136 passed`，仅保留一条既有 pandas `FutureWarning`；新增运维安全专项 `12 passed`，定点权限/任务登记/刷新组合回归 `27 passed`。
- `apps/alpha/application/ops_services.py` 增量 mypy 清零并退出债务清单；全仓基线从 `610 errors / 296 files` 收紧为 `606 errors / 295 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十六批

- 按“Qlib 构建命令动态配置直入文件 I/O × 非法窗口触发无界数据读取 × 日期错误裸异常 × 命令入口无类型”收口 Alpha 基础数据管理命令。
- 新增冻结 `_BuildQlibOptions`，命令先完整校验 provider path、region、target date、freshness window、lookback window、check-only 和 universe 列表，再读取 Tushare 凭据或检查本地 Qlib 数据。
- provider URI 必须为 1..4096 位、无控制字符的字符串；region 必须为 1..16 位受控 slug。配置中心返回错误类型、空值、换行或超长路径时不再进入目录检查或 builder。
- `target_date` 非字符串、非法 ISO 日期统一转为可操作的 `CommandError`；`max_staleness_days` 限制为非 bool 整数 `0..365`，`lookback_days` 限制为非 bool 整数 `1..2000`，避免负数、bool 和超大窗口进入行情构建。
- universe 只接受逗号分隔字符串，每项规范化为最长 64 位 slug，稳定去重并限制最多 32 项；列表/dict、路径片段、空范围和无界范围在 I/O 前失败关闭，不再用 `str(object)` 宽松吞入。
- Tushare token resolver 只接受 trim 后非空字符串，动态配置返回数字、mapping 或空白时按未配置处理；命令输出继续只显示 configured/missing，不输出凭据。
- `add_arguments`、`handle` 与辅助函数补齐精确类型，运行时配置保持 `dict[str, object]` 动态边界并在使用前收窄，清除该命令全部类型债务。

## 第三百七十六批验证结果

- Alpha/Qlib 应用、单元、运维 API 与构建命令扩展回归 `160 passed`，仅保留一条既有 pandas `FutureWarning`；新增命令安全专项 `21 passed`，既有命令边界组合 `28 passed`。
- `apps/alpha/management/commands/build_qlib_data.py` 增量 mypy 清零并退出债务清单；全仓基线从 `606 errors / 295 files` 收紧为 `601 errors / 294 files`，净减少 `5 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百七十七批

- 按“生产 readiness 动态 provider 返回 Any × 损坏 strict cache 可伪造验收状态 × 字符串布尔误判 × 异常正文进入 Task Monitor/TUI”收口 Operational Readiness 公共监视器。
- 四个运行时 provider 入口在动态调用后必须返回 string-keyed mapping；readiness status、AI capability、Terminal surface 与 Data Center coverage 返回 list、scalar 或非字符串键时明确拒绝，不再把错误 shape 交给用户摘要。
- 默认验收目标日期必须为 plain `date`；字符串、datetime 和 None 不再通过 Any 进入状态构建。跨 App 动态装配仍保持 Application 边界，不新增 Infrastructure 依赖。
- strict runtime cache 只接受完整 monitor summary：要求正式顶层 sections、daily state、monitor bool、window bool 与列表字段；部分字典或结构损坏缓存会被忽略并重新获取实时状态，不能伪造“窗口已完成”。
- 嵌套 validation/gate/scheduler/decision sections 使用受控 mapping 读取；字符串不再被 `list()` 拆成字符列表。`"false"` 等 truthy 字符串不再被当作 monitor 通过、窗口验收、scheduler required 或决策禁用标记。
- 每类动态列表限制最多 500 项；attention reason/command 只发布有界单行字符串，损坏对象不会借 `str(object)` 进入 operator 页面。
- cache、AI capability、Terminal 与 Data Center 异常日志只记录异常类型；页面/API 分别发布稳定 `ai_capability_status_unavailable`、`terminal_status_unavailable` 与 `data_coverage_unavailable`，不再暴露数据库 URL、路径或凭据正文。
- 动态 provider 的四个 no-any-return 债务清零；同一安全 summary 继续供 Task Monitor 页面/API 和 TUI runtime governance 队列复用。

## 第三百七十七批验证结果

- Readiness monitor 安全与既有专项 `19 passed`；readiness 证据、每日任务、状态命令、Task Monitor API 与 TUI operator 扩展回归 `216 passed`。
- 按 TUI 高风险链路最小回归要求，Workbench 与 Terminal Agent 组合 `208 passed`。
- `apps/operational_readiness/application/monitor_service.py` 增量 mypy 清零并退出债务清单；全仓基线从 `601 errors / 294 files` 收紧为 `597 errors / 293 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 TUI/Terminal 实现、SDK、MCP 或部署实现。

## 第三百七十八批

- 按“Agent 决策上下文异常正文外泄 × 部分数据源失败仍报告新鲜度 ok × ORM values 原地改型 × portfolio ID 无校验”收口 Agent Runtime 跨 App 上下文快照。
- Repository 的 18 类 ORM 来源统一使用稳定降级合同：失败 payload 固定为 `source_fetch_failed`，结构化日志只记录异常类型；数据库 URL、Redis URL、路径、凭据和底层异常正文不再进入 Agent snapshot 或普通日志。
- Base Context Facade 取消 `exc_info=True`，research/decision/execution/monitoring/ops 公共快照隔离失败时不再记录 traceback；四个 specialized Facade 的 detail enrichment 日志同步只保留异常类型。
- Active Signal 最近记录不再把 ORM values TypedDict 的 datetime 字段原地改成字符串；改为显式构造 JSON-facing mapping，并由受控 date/datetime serializer 输出 ISO 时间。
- Regime 与 Macro freshness 使用独立模型变量和精确日期字段；任一来源查询失败时总状态发布 `degraded`，全部查询成功但无记录时发布 `no_data`，不再用顶层 `ok` 掩盖 `sources.*=unavailable`。
- portfolio position 查询只接受非 bool 正整数 ID；零、负数、字符串、None 和 bool 在 ORM I/O 前返回稳定 `portfolio_id_invalid`，避免动态 Agent 调用扩散无界/错误 scope。
- Policy description 使用正式模型字段合同，不再依赖动态 `getattr`；Context Repository 的 TypedDict mutation、跨模型 assignment 与 attr-defined 债务全部清零。

## 第三百七十八批验证结果

- Agent Runtime 上下文安全与真实 ORM 组件专项 `16 passed`。
- Agent Runtime Facade、Application、Domain、MCP/SDK 合同、Terminal Agent 与 SDK client 扩展回归 `197 passed`。
- `apps/agent_runtime/infrastructure/context_snapshot_repository.py` 与五个相关 Facade 文件联合增量 mypy 清零；上下文仓储退出债务清单，全仓基线从 `597 errors / 293 files` 收紧为 `594 errors / 292 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal/TUI 页面、SDK、MCP 或部署实现。

## 第三百七十九批

- 按“Tushare 动态 SDK 无合同 × NaN/Inf 可污染 canonical facts × 坏字段中断整批 × Provider 异常正文泄露”收口 Data Center 统一事实入口。
- 为 Tushare `trade_cal/daily/margin/etf_share_size` 与 pandas-like frame 建立最小 Infrastructure Protocol；三个 client 创建点显式收窄，ETF calendar/size helper 不再接收无界 Any。
- `MacroFact` 与 `FinancialFact` 的核心数值必须为非 bool 有限数；`ValuationFact` 的七个可选估值字段拒绝 bool、非数值和 NaN/Inf，流通/总市值同时不得为负。
- `FundNavFact` 的累计净值与日收益拒绝非有限值，累计净值必须为正；单位净值原有正有限约束保持不变。
- 通用 Tushare 宏观点统一经 `safe_float`，坏值按观察点跳过；行情快照的坏主价格按记录隔离，负数/非有限成交量和金额降级为 None，不再让单条报价终止整个列表。
- Fund NAV 对非正/非有限主净值按记录跳过，损坏累计净值降级为空；Financial facts 按 metric 逐项收窄，单项 NaN/Inf 不再丢弃同一报告期全部合法指标。
- Valuation facts 使用 `safe_float` 收窄倍率和收益率，负/非有限市值降级为空；所有输出仍由 Domain 不变量二次保护。
- 全市场成交额失败日志只记录异常类型，不再写入 Tushare endpoint、token 或底层异常正文；原有失败关闭语义保持不变。

## 第三百七十九批验证结果

- 新增 canonical fact 与 Tushare 数值/SDK 安全专项 `15 passed`。
- Data Center 全单元、统一价格、on-demand、组件仓储与 API 集成扩展回归 `434 passed`；Macro 与 Equity 财务/估值消费者回归 `160 passed`。
- `apps/data_center/infrastructure/_provider_adapter_tushare.py` 与 Domain entities 联合增量 mypy 清零；Tushare adapter 退出债务清单，全仓基线从 `594 errors / 292 files` 收紧为 `591 errors / 291 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百八十批

- 按“跨用户 Research 证据写入 × 越权触发晋级状态变更 × 动态 payload 污染不可复现证据”收口 Research 注册表。
- Domain 新增精确 Research Registry Gateway、trial/split/metric TypedDict 与只读结果 Protocol；Application 不再通过 `**kwargs: Any` 编排仓储，Composition 的三处宽泛参数债务清零。
- 普通用户创建 trial 或执行 promotion 前必须匹配实验 owner；staff 可维护他人或系统实验。实验/trial 不存在分别稳定映射为 404，越权映射为 403，证据身份冲突和业务校验失败映射为 400。
- trial 创建在事务内锁定实验并先完成归属检查；越权请求不会创建 family、trial、split 或 metric。promotion 同样先完成归属检查，不能替他人触发 decision 或 trial 状态变更。
- 新增严格 DRF 嵌套 serializer，顶层、split 与 metric 未知字段不再静默丢弃；标识、状态、计数、置信区间、p-value、JSON 对象与总体证据大小均有明确边界。
- Application 对非 API 调用执行同一套完整校验：拒绝 bool 伪装整数、NaN/Inf、重复指标名、缺失/未知字段、未配对或倒序置信区间、非法 p-value 与超大 JSON；输入 mapping 深拷贝后持久化，不再由 Repository `pop()` 原地修改。
- Repository 按精确字段创建 trial/split，并批量写入已验证 metric；历史 promotion 读取遇到缺失 split、非法 p-value 或非有限 DSR 输入时记录稳定拒绝原因，不再因坏证据崩溃或错误晋级。

## 第三百八十批验证结果

- Research Unit、Component、权限安全 API 与跨模块完整性 API 合约回归 `36 passed`；覆盖 owner/staff 边界、越权零写入、404/403/400、严格嵌套字段、非有限指标、重复指标、证据大小限制，以及历史缺失 split/非有限指标的安全拒绝。
- `apps/research/domain/contracts.py`、Application use cases、Repository、Composition、serializer 与 API view 联合增量 mypy 清零；全仓基线从 `591 errors / 291 files` 收紧为 `588 errors / 290 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，也未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百八十一批

- 按“Audit 零分数被误报缺失 × 完成态指标数量不勾稽 × 验证异常正文泄露”收口阈值验证摘要链。
- Validation Repository 所有动态字典返回补齐 string/object 精确类型；API view 使用 DRF `Request/Response` 和显式日期 TypedDict，不再把无类型 `validated_data` 通过 `**payload` 传播到 Application。
- 摘要读取改为 `is not None`/有限分数收窄，合法 `0.0` F1 与稳定性分数保持为真实零；历史 NaN、Infinity、负数或越界分数降级为缺失，不再发布非标准 JSON 数值。
- validation run ID、日期范围、状态、布尔标志、查询 limit、四类指标计数、平均分数及文本长度在 ORM 写入前统一校验；completed 状态要求 approved/rejected/pending 合计严格等于 total，分类合计超过总数同样失败关闭。
- 单个指标评估失败时明确计入 pending，修复未分类指标被遗漏但整批仍标记 completed 的审计勾稽缺口。
- 阈值验证异常对 API 与数据库只发布稳定 `threshold_validation_failed`；日志仅记录异常类型，不再输出数据库 URL、凭据或 traceback。失败状态回写自身再次遇到数据库异常时也会隔离，原请求仍稳定失败。
- 新增零分数四类 projection、历史非有限分数、无效 run/date/count/status/score/bool、completed 勾稽、limit 上限、失败指标 pending 和双重数据库异常脱敏回归。

## 第三百八十一批验证结果

- Audit Unit、Application、Domain、Component、Integration 与 API 全链回归 `351 passed`。
- `apps/audit/infrastructure/validation_repositories.py`、`apps/audit/interface/validation_api_views.py` 与阈值验证 Application 联合增量 mypy 清零；全仓基线从 `588 errors / 290 files` 收紧为 `577 errors / 288 files`，净减少 `11 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，也未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百八十二批

- 按“Attribution 非有限事实可直写 × 历史坏报告进入决策复盘 × 外推 Regime 证据在 PostgreSQL 截断失败”收口 Audit 归因持久化链。
- Domain 新增 Attribution Report、Loss Analysis 与 Experience Summary 三类精确 TypedDict 投影；Repository 不再返回裸 dict，下游 Audit summary、Interface service 与 Decision Step 6 直接获得可验证的 int/float/str 合同。
- 报告写入统一验证正整数 backtest ID、有序 plain-date 区间、有限 P&L、`0..1` Regime 准确率、正式 attribution method 与受控 Regime token；bool、NaN、Infinity、路径片段、未知方法在 ORM 前失败关闭。
- Loss Analysis 要求正式损失来源、有限 impact、非负 impact percentage 与有界非空描述；Experience Summary 要求正 report ID、有界非空 lesson/recommendation 与正式优先级。
- 报告、损失和经验查询对非法 ID 返回空结果；report list limit 限制为 `1..500`。历史报告存在非有限 P&L、越界准确率、倒置日期、未知方法或污染 Regime token 时整条隔离；历史损失指标非有限或百分比为负时不再发布。
- 数据库健康探针仍执行真实 `SELECT 1`，但只返回 reachable/vendor，不再返回数据库名、本地 SQLite 路径或连接信息。
- Audit summary 与生成后读回改为构造独立 enriched payload，不再原地向 Repository TypedDict 注入 loss/experience 字段；精确类型同步清除 Attribution use case 与 Decision Step 6 的 11 条隐含不安全转换。
- 发现并修复既有 PostgreSQL 合同缺口：Application 会生成 `EXTRAPOLATED:Recovery:YYYY-MM-DD`，原 `regime_actual max_length=20` 无法容纳。字段扩至 64 位并新增 `0010_alter_attribution_regime_actual` migration，超长或污染 token 仍拒绝。

## 第三百八十二批验证结果

- Audit Unit、Application、Domain、Component、Integration 与 API 全链回归 `378 passed`；精确 enrichment 最终消费端追加回归 `42 passed`。
- `apps/audit/infrastructure/attribution_repositories.py` 与五个生产消费点联合增量 mypy 清零；Attribution Repository 退出债务清单，全仓基线从 `577 errors / 288 files` 收紧为 `571 errors / 287 files`，净减少 `6 errors / 1 file`。
- Migration drift、Audit migration plan、Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Terminal、TUI、SDK、MCP 或部署实现。

## 第三百八十三批

- 按“字符串 staff 标志可提权 × 伪造 roles 进入 MCP 审计/环境 × 动态异常与结果污染执行证据”收口已批准 MCP 提案执行器。
- 执行前必须提供 string-keyed actor mapping、正整数 user ID、真实 bool `is_staff` 和有界单行 username；`"false"`、bool ID、零负 ID、CRLF username 与匿名 actor 在任何环境变量或 MCP I/O 前拒绝。
- trusted MCP role 只由严格 `is_staff` 派生为 `admin/read_only`，不再信任调用方传入的 roles；同一角色同时进入 scoped environment、Django SDK transport 与 Audit context，消除权限与审计身份错配。
- proposal payload 只允许 capability key、arguments 和既有 session ID 字段；capability key 使用受控 slug，arguments 必须为 string-keyed、有限、可 JSON 序列化且不超过 256 KiB 的对象。未知字段、路径片段、NaN/Inf、非 object 或超大参数不进入 MCP。
- stage/resume envelope 必须为有限 JSON object 且总量不超过 1 MiB；confirmation token 限制为 1..4096 位受控字符。非有限结果不能写入 Agent execution evidence。
- MCP 错误只向上游发布受控 error code，error message、数据库/Redis URL 和凭据正文不再进入 execution failure；动态 transport/import/audit sink 异常统一降级为稳定 `mcp_execution_transport_failed`。
- embedded MCP 环境变量继续在全局锁内设置并在成功/异常后恢复；内部认证 secret 类型异常、Audit sink 失败与异常 log ID 均使用稳定错误码。
- SDK/MCP 动态 import 改为 importlib 边界加精确 context-manager callable，两个 import-untyped 与两个无类型函数债务清零。

## 第三百八十三批验证结果

- MCP executor 安全专项 `17 passed`；Terminal/TUI/MCP/SDK/SSL 高风险最小回归包 `274 passed`，覆盖本地无 HTTP stage/resume、audit sink、审批 API、Workbench、Terminal Agent 与 SDK client。
- `apps/agent_runtime/infrastructure/mcp_proposal_executor.py` 增量 mypy 清零并退出债务清单；全仓基线从 `571 errors / 287 files` 收紧为 `567 errors / 286 files`，净减少 `4 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 TUI/Terminal/SDK/MCP 对外契约或部署实现。

## 第三百八十四批

- 按“legacy MCP 环境变量并发串面 × 动态 catalog metadata 无合同 × 非法 MCP 请求回退 builtin 绕过”收口 AI Capability MCP runtime gateway。
- MCP server reload 增加进程内可重入锁；core 与 legacy-inclusive 列表均在锁内显式设置 `AGOMTRADEPRO_MCP_ENABLE_LEGACY_TOOLS`、reload、读取并恢复原环境后再次 reload。core 列表即使宿主环境原为 true 也只返回 core tools，并发 core 请求会等待 legacy scope 完整退出。
- `include_legacy` 只接受真实 bool；字符串 `"false"` 不再打开 legacy surface。动态 server、core names、registry loader 与 legacy disposition 均通过 importlib 边界加载，删除五个 import-untyped 债务。
- MCP tools 限制最多 2000 项，名称必须为受控标识且唯一；description 保持兼容历史空值但限制类型/长度/NUL，input schema 必须为有限 string-keyed JSON object。
- governed manifests 与 legacy dispositions 建立精确 Protocol；registry key 必须等于 capability key，必要字符串、tuple、schema 与确认标志逐项收窄。正式 RiskLevel/ReviewStatus 枚举替代下游宽松字符串。
- MCP tool call 名称、参数与结果执行深度、节点数、有限数、string-keyed object 和编码大小校验；参数上限 256 KiB、结果上限 1 MiB，NaN/Inf、非 JSON、非字符串键和无界 payload 不再进入 routing 或用户响应。
- gateway 验证失败使用专用 `McpRuntimeValidationError`，Capability dispatcher 明确返回 `mcp_request_invalid`，不再回退 builtin registry 绕过 MCP 边界。其他 SDK 故障继续兼容 fallback，但日志只记录异常类型，不输出 traceback/连接串。
- capability source sync 失败只记录异常类型并持久化稳定 `capability_source_sync_failed`，不再把配置、数据库或凭据正文写入 sync summary。

## 第三百八十四批验证结果

- MCP gateway 并发/边界安全专项 `11 passed`，legacy 空描述与真实 catalog 同步专项 `13 passed`；AI Capability catalog/sync/routing API 与 Terminal/TUI/MCP/SDK/SSL 组合回归 `983 passed`。
- MCP runtime gateway、catalog projection、sync use case 与主 routing use case 联合增量 mypy 清零；三个文件退出债务清单，全仓基线从 `567 errors / 286 files` 收紧为 `557 errors / 283 files`，净减少 `10 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 TUI/Terminal/SDK/MCP 对外成功响应结构或部署实现。

## 第三百八十五批

- 按“Terminal 命令失败伪装成功 × 内外部 API 调度边界宽松 × 异常/参数凭据进入用户响应和审计”收口命令执行链。
- Command execution 建立精确 Application Protocol，命令仓储正式发布 `get_all()` 合同，认证用户和 runtime/factory 返回类型收窄；Terminal services、use cases 及两个消费端的隐式动态调用债务同步清零。
- API 命令只允许正式 HTTP method、有限 timeout、合法 status 和受控 endpoint；内部 URL 拒绝 query、fragment、反斜线与编码/明文 traversal，且必须提供存在的正整数认证用户。外部 URL 拒绝内嵌凭据，path 参数按 URL segment 编码并从 request params 移除。
- 外部请求和内部 API 的 4xx/5xx 统一失败关闭；非法 JQ-like filter 不再回退发布原始响应。请求与响应必须为有限、可 JSON 序列化且不超过 1 MiB 的 payload，NaN、Infinity、动态对象和超大数据在输出/metadata 前拒绝。
- Prompt runtime 失败不再把 Agent 原始错误正文当成成功 output；所有命令执行失败向用户与审计只发布稳定 `terminal_command_execution_failed`，日志仅记录异常类型。
- 命令参数审计递归遮蔽 password/token/secret/API key/authorization/cookie/session/credential/private key 等字段，并限制深度、集合数量、文本长度和总摘要大小；审计 ORM 失败通过 Domain 异常跨层传递，连接串和底层异常正文不进入日志。

## 第三百八十五批验证结果

- Terminal 命令执行安全专项 `22 passed`；既有 Terminal 治理、API、边界与查询服务组合 `91 passed`；TUI Workbench、Terminal Agent、SDK client 与内部 SSL redirect 固定高风险回归包 `236 passed`。
- `apps/terminal/application/services.py` 与 `apps/terminal/application/use_cases.py` 增量 mypy 清零并退出债务清单；精确协议同时清除 AI Capability gateway 与 Terminal interface service 的最后债务，全仓基线从 `557 errors / 283 files` 收紧为 `546 errors / 279 files`，净减少 `11 errors / 4 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/SDK/MCP/部署实现或 Terminal 对外成功响应结构。

## 第三百八十六批

- 按“Terminal 审批/审计权限动态 truthy 提权 × DRF 用户边界无合同”收口 Terminal permission classes。
- `IsStaffOrAdmin` 与 `IsStaffOrOperator` 只接受真实布尔 `is_authenticated/is_staff/is_superuser`；字符串 `"false"`、数字和其他 truthy 动态值不再获得 staff、superuser 或 operator 权限。
- operator 访问继续以正式 Django `operator` Group 为真源，但 membership `exists()` 必须返回真实 `True`；异常动态返回不能伪装组成员。匿名和普通用户保持失败关闭。
- DRF request/view、用户标志及 group membership manager/query 建立最小 Protocol，权限判断不再传播 Any 或依赖无类型 handler。

## 第三百八十六批验证结果

- Terminal permission 专项 `7 passed`；审批端点、staff-only 审计端点、TUI Workbench、Terminal Agent、SDK client 与内部 SSL redirect 扩展回归合计 `268 passed`。
- `apps/terminal/interface/permissions.py` 增量 mypy 清零并退出债务清单；全仓基线从 `546 errors / 279 files` 收紧为 `543 errors / 278 files`，净减少 `3 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/SDK/MCP/部署实现或 Terminal 权限角色口径。

## 第三百八十七批

- 按“Macro adapter 动态调用无合同 × 字符串 period type 进入 Domain × 数据源/仓储异常正文进入响应”收口 legacy Macro Application 编排。
- Macro Repository 补齐按日期读取与批量保存协议；同步 adapter 建立 `supports/fetch` 精确 Protocol，动态返回必须为 `list[MacroDataPoint]`，dict、scalar 与混合对象在 canonical 写入前失败关闭。
- 同步实体使用正式 `PeriodType.MONTH`，不再向 Domain 传递裸字符串；同步、最新值读取、手动抓取与删除构造器补齐 Repository/Adapter/UseCase 精确类型。
- 手动抓取、同步 adapter 与删除失败只发布稳定 `macro_data_fetch_failed`、`macro_data_sync_failed`、`macro_indicator_sync_failed`、`macro_data_delete_failed`；日志只记录 indicator 与异常类型，不再包含数据库/Redis URL、路径或凭据正文。
- 上游失败 response 的任意 errors 不再原样透传；Data Center connection probe payload 必须为 string-keyed dict，动态错误 shape 不进入接口展示。

## 第三百八十七批验证结果

- Macro Application 安全、数据管理与既有 use case 专项 `26 passed`；Macro unit、Application component 与 data-sync integration 扩展组合 `185 passed, 1 failed`。唯一失败为既有 PIT 测试要求在 `2024-02-28` 截止查询中纳入 `2024-03-15` 才发布的数据，与 PIT 防后视语义冲突；目标仓储文件本批无改动，单独重跑可稳定复现。
- `apps/macro/application/data_management.py` 与 `apps/macro/application/use_cases.py` 增量 mypy 清零并退出债务清单；全仓基线从 `543 errors / 278 files` 收紧为 `534 errors / 276 files`，净减少 `9 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改 Macro PIT 仓储、数据库 migration、TUI/Terminal/SDK/MCP 或部署实现。

## 第三百八十八批

- 按“Eastmoney 动态 pandas 类型债务 × 非有限行情进入快照 × 新闻 URL/条数无边界 × 资金流日期类型失真”收口 Data Center 外部市场 payload parsers。
- 新增最小 dataframe/row Protocol，行情、新闻和资金流 parser 不再直接 import 无类型 pandas，也不再用宽泛 type ignore 掩盖 Series/DataFrame 边界。
- Quote Decimal/整数转换拒绝 bool、NaN 与 Infinity；价格必须为正，负成交量、成交额和 OHLC 字段降级为空，不再把损坏市场总量发布为合法负值。parser 异常日志只记录股票代码与异常类型。
- Capital flow 先处理 datetime 再处理 date，确保 trade_date 为 plain date；主力净流入和占比必须为有限数，缺失/非有限主字段不再静默伪造为零。
- News limit 只接受正整数并最多处理 500 条；标题、正文和 URL 分别限制长度，aware 时间统一转 UTC。链接只接受无凭据 HTTP(S)，javascript、内嵌用户名/密码、控制字符和超长 URL 降级为空。
- 新闻去重 ID 使用规范化 UTC 发布时间，等价时间表示不再产生重复事实；实体校验失败日志不输出标题、URL 或异常正文。

## 第三百八十八批验证结果

- Eastmoney quote/news/capital-flow parser 专项 `30 passed`；真实 market gateway、Phase 3 provider adapter 与资产分类扩展组合总计 `96 passed`。
- 三份 Eastmoney parser 与共享 dataframe contract 增量 mypy 清零；三个 parser 全部退出债务清单，全仓基线从 `534 errors / 276 files` 收紧为 `526 errors / 273 files`，净减少 `8 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP 或部署实现。

## 第三百八十九批

- 按“跨 App 配置摘要返回 Any × 动态 payload 污染页面/API × staff truthy 越权展示 × 异常正文进入日志”收口 Core Config Center 聚合入口。
- summary builder 建立精确 callable 合同；动态结果必须为包含有界 status 和 string-keyed summary 的 JSON object。非字符串键、scalar/list summary、NaN/Inf、未知对象和非法控制字符统一降级为稳定 attention payload。
- summary payload 限制最多 12 层、10000 节点和 1 MiB；合法结果经 JSON round-trip 脱离 provider 自有可变对象，后续源对象修改不能改变已生成的页面/API 快照。
- 跨 App builder 的数据库、配置、连接和验证异常只记录 capability 与异常类型；数据库/Redis URL、路径、凭据和 traceback 不再进入日志。
- staff-only capability 只接受真实 `is_staff is True`；字符串 `"false"` 和其他 truthy 动态值不能发布系统设置、集中风控、Agent Operator、数据源等管理员配置。
- Core snapshot/capability API handler 补齐 DRF Request/Response 类型和 public docstring，继续由 `IsAdminUser` 保护，不改变成功响应结构。

## 第三百八十九批验证结果

- Core Config Center shape/权限/脱敏专项 `12 passed`；真实 staff API、设置中心页面、Qlib runtime/training 与系统设置跨模块组合 `65 passed`。
- `core/application/config_center.py` 与 `core/api_views.py` 增量 mypy 清零并退出债务清单；全仓基线从 `526 errors / 273 files` 收紧为 `521 errors / 271 files`，净减少 `5 errors / 2 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP 或部署实现。

## 第三百九十批

- 按“Pulse history 查询参数无界 × 执行异常正文反射 × 非有限战术指标发布 × truthy staff 触发手工计算”收口 Pulse 公共 API。
- History query 新增 DRF Serializer：months 限制 `1..120`、limit 限制 `1..500`；零、负数、超限和非整数字符串在 Repository I/O 前返回标准 400，不再由 int 转换异常变成 500。
- API root、Current、History 与 Calculate handler 补齐精确 Request/Response 类型；数据库、配置、连接和运行时异常只记录异常类型，对外分别发布稳定 `pulse_current_unavailable`、`pulse_history_unavailable` 与 `pulse_calculation_failed`。
- Current snapshot、History list 和 Calculate 摘要必须为有限 JSON 且不超过 1 MiB；NaN、Infinity、动态对象和超大 payload 在 DRF Response 前失败关闭，合法 payload 经 JSON round-trip 与源对象隔离。
- 手工计算只接受真实 `is_staff is True` 或 `is_superuser is True`；字符串 `"false"` 和其他 truthy 动态值返回 403，且不会触发 Pulse 计算。
- Pulse snapshot serializer 补齐 DRF 泛型并修正 regime_context 为字符串合同；Domain snapshot serializer 使用精确 `PulseSnapshot` 类型，不再返回裸 dict。

## 第三百九十批验证结果

- Pulse API 输入、权限、非有限 payload 与异常脱敏专项 `15 passed`；API、计算/读取 UseCase、Data Provider freshness、权重配置与路由扩展组合 `62 passed`。
- `apps/pulse/interface/api_views.py`、`apps/pulse/interface/api_urls.py` 与 serializers 增量 mypy 清零并退出债务清单；全仓基线从 `521 errors / 271 files` 收紧为 `513 errors / 268 files`，净减少 `8 errors / 3 files`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP 或部署实现。

## 第三百九十一批

- 按“模型评估样本错位 × 缺失分组成员伪造零值 × 非有限指标进入证据 × coverage/turnover 越界”收口共享 Model Evaluation 基础设施。
- IC/Rank IC 只使用同位置的有限 prediction/target 对；数组必须一维且等长。Rank IC 对并列值使用稳定平均名次，不再由双 argsort 任意打破 ties。
- ICIR 同时过滤 NaN 与 Infinity；rolling IC 要求 window 为大于 1 的真实整数并先校验序列等长，非法窗口和错位序列不再在切片后产生误导结果。
- Group IC 只纳入同时存在有限预测、目标和 group 的股票；缺失股票不再被补成 0 后参与行业相关性。每组不足两个真实样本时安全跳过。
- Sharpe 过滤非有限收益并把年化无风险利率转换为日频；max drawdown 拒绝多维和非有限累计序列。Turnover 使用当前/上期去重仓位总数作为分母，结果稳定限制在 `0..1`。
- ModelEvaluator coverage 改为“有限共同股票 / 有限目标 universe”，额外预测和 NaN 不再令覆盖率超过 1；绩效只使用同时存在有限预测与收益的股票，不再把缺失收益伪造为零。
- ModelMetrics 在构造时拒绝 NaN/Inf、越界 coverage/turnover 和负 max drawdown，损坏评估证据不能进入缓存、训练记录或监控链。

## 第三百九十一批验证结果

- 共享评估器有限性、对齐、tie rank、分组、窗口、覆盖率和指标不变量专项 `9 passed`；Alpha cache、Qlib artifact/runtime、training 与 monitoring 扩展组合总计 `89 passed, 1 warning`，warning 为既有 pandas groupby axis FutureWarning。
- `shared/infrastructure/model_evaluation.py` 增量 mypy 清零并退出债务清单；精确类型同时消除 Alpha cache evaluation 的一条无类型调用债务，全仓基线从 `513 errors / 268 files` 收紧为 `507 errors / 267 files`，净减少 `6 errors / 1 file`。
- Django system check、架构 delta、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP 或部署实现。

## 第三百九十二批

- 按“Sector 动态 AKShare/pandas 边界无合同 × 损坏行情进入持久化链 × 外部异常正文泄漏”收口申万行业行情适配器。
- AKShare 与 pandas 动态模块建立最小 Protocol；分类、指数、成分股及批量接口补齐精确容器类型，移除直接无类型 pandas import、无类型方法和裸 `list` 债务。
- 行业层级、行业代码、日期区间与行业名称在 SDK/ORM I/O 前校验；批量指数抓取隔离单个非法代码，避免一个坏输入中断整批任务。
- 远端行业分类过滤空值、非法代码和重复代码；指数行情拒绝非有限或非正收盘价，负 OHLC、成交量和成交额降级为空，NaN/Infinity 不再进入标准行情事实。
- 成分股代码按受控交易所后缀过滤并去重；外部数据源失败日志只记录层级/代码和异常类型，不再输出连接串、凭据或底层异常正文。

## 第三百九十二批验证结果

- AKShare Sector 适配器输入、清洗、批量隔离与异常脱敏专项 `7 passed`；Sector 单元、Domain、跨模块依赖、API 边界与集成扩展组合总计 `85 passed`。
- `apps/sector/infrastructure/adapters/akshare_sector_adapter.py` 增量 mypy 清零并退出债务清单；全仓基线从 `507 errors / 267 files` 收紧为 `502 errors / 266 files`，净减少 `5 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP、费用执行链或部署实现，手工联网的 capital-market smoke test 未纳入自动回归。

## 第三百九十三批

- 按“市场温度计 provider 动态合同 × 线程返回值未收窄 × 上游异常正文进入审计/API”收口 Data Center 输入同步链。
- 同步 UseCase 接入正式 `ProviderRegistryProtocol`，provider 配置与统一数据源使用精确 tuple 合同；解析单个 provider 与 provider 列表不再返回隐式 Any。
- provider 线程调用改为泛型成功/失败结果对象，只允许真实 `Exception` 跨线程重抛，不再对动态 payload 执行 `raise`；超时统一发布稳定 `market_thermometer_provider_timeout`。
- Macro、ETF 共识和市场新闻同步的可恢复错误只进入稳定 `market_thermometer_provider_failed`，数据库/数据源连接串、凭据和底层异常正文不再写入 RawAudit 或 API 结果。
- legacy runtime facade 建立最小 Protocol；决策日期必须为 plain date，默认/分组件 timeout 必须是有限正数且不超过 300 秒，override 最多 50 项并返回脱离 facade 的精确副本。

## 第三百九十三批验证结果

- 市场温度计 provider fallback、timeout、异常脱敏和 runtime 配置边界专项 `31 passed`；Data Center 全单元、架构/反向依赖、Dashboard、市场温度计 API 与 Pulse API 扩展组合总计 `362 passed`。
- `apps/data_center/application/_market_thermometer_runtime.py` 与 `apps/data_center/application/market_thermometer_sync.py` 增量 mypy 清零并退出债务清单；全仓基线从 `502 errors / 266 files` 收紧为 `497 errors / 264 files`，净减少 `5 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI/Terminal/SDK/MCP、费用执行链或部署实现。

## 第三百九十四批

- 按“Terminal Capability Gateway 合同归属错误 × 流式/工具过滤返回类型缺失 × SDK/ORM 异常正文进入用户与审计”收口 Terminal Agent 核心运行链。
- `match_terminal_mcp_capability()` 从 Approval Gateway 纠正到实际调用方 Capability Gateway，正式 Protocol 与 `CapabilityRoutingFacade` 实现重新一致；高风险工具匹配不再依赖协议外动态属性。
- `stream_chat()` 发布精确 `Iterator[TerminalAgentEventDTO]`，MCP tool filter 发布精确 callable 合同，清除流式服务与 SDK filter 的隐式动态返回。
- Agents SDK、MCP session 和动态事件处理失败统一返回 `terminal_agent_execution_failed`；用户流式事件和 usage 审计不再保存连接串、API key 或底层异常正文。
- 执行失败和 usage ORM 写入失败日志只记录异常类型，不再输出 traceback 或异常正文；即使收到携带敏感内容的错误事件，持久化前也会替换为稳定错误码。

## 第三百九十四批验证结果

- Terminal Agent capability、MCP、审批、流式事件与异常脱敏专项 `13 passed`；TUI Workbench、Terminal Agent、SDK client、内部 SSL、Capability gateway 与 Terminal API 固定高风险组合 `259 passed`。
- `apps/agent_runtime/infrastructure/terminal_agent_service.py` 增量 mypy 清零并退出债务清单；全仓基线从 `497 errors / 264 files` 收紧为 `494 errors / 263 files`，净减少 `3 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未修改数据库 migration、TUI 元数据、SDK/MCP 成功响应、费用执行链或部署实现。

## 第三百九十五批

- 按“Alpha 价格覆盖回填先删后写非原子 × 单源异常中断 failover × 错资产/区间外/损坏 bar 进入事实库 × CLI 日期无边界”收口模型价格覆盖同步链。
- `sync_from_alpha_cache()` 与 `sync_codes()` 在 cache、主数据或 gateway I/O 前验证 plain-date 有序区间；反向区间不再执行资产回填或删除价格数据。
- 单个历史行情 gateway 的连接、超时、数据与运行异常被隔离，后续 gateway 继续 failover；日志只记录资产代码、gateway 类型和异常类型，不输出 URL、凭据或底层异常正文。
- gateway payload 必须为 `list[HistoricalPriceBar]`；只接收目标资产、请求区间内、有效 source、正且有限 OHLC、合法高低价关系及非负有限成交量/成交额，重复日期/source 使用最后一条规范事实。
- 旧受管 bar 删除与新 `PriceBar` 批量写入纳入同一数据库事务；新写入失败时旧价格事实完整回滚，不再留下模型评估价格断层。
- 管理命令补齐 CommandParser/handle/date 合同，严格验证字符串、bool、最多 5000 个额外代码及日期区间；结果改为稳定 JSON，Alpha cache core bridge 同步发布 `date | None` 返回合同。

## 第三百九十五批验证结果

- Alpha 覆盖日期、gateway failover、行情过滤、异常脱敏、真实事务回滚与 CLI JSON 专项 `7 passed`；Alpha cache、Data Center runtime helper、资产主数据回填与价格仓储扩展组合 `42 passed`。
- `apps/data_center/infrastructure/alpha_price_coverage_sync.py`、`apps/data_center/management/commands/sync_alpha_price_coverage.py` 与 `core/integration/alpha_cache.py` 增量 mypy 清零并退出债务清单；全仓基线从 `494 errors / 263 files` 收紧为 `487 errors / 260 files`，净减少 `7 errors / 3 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/SDK/MCP、费用执行链或部署实现。

## 第三百九十六批

- 按“模拟交易 SDK mutation 请求/返回无合同 × 超量平仓生成卖出流水 × 业务/数据库异常正文反射 × 账户 ID 枚举”收口公开平仓与账户重置接口。
- Position close 与 account reset handler 补齐 DRF Request、正整数 account ID 和 Response 合同；账户访问拒绝统一为 authentication/access-denied/not-found 稳定错误，不再把账户 ID 或 Application 文案直接反射给 SDK。
- 统一持仓服务在任何流水或持仓写入前验证现有数量、平仓数量和成交价为正且有限；平仓数量超过当前持仓返回 `close_shares_exceeds_position`，不再生成超额卖出记录或删除完整持仓。
- 找不到持仓、损坏持仓状态、非法数量和非法价格使用专用稳定错误码及 400/404/409 状态；未知 ValueError 不再把账户、资产、连接串或凭据正文返回调用方。
- 平仓与重置的数据库、连接、运行时和类型故障统一返回 503 稳定错误；日志仅记录异常类型，不输出 traceback 或底层异常正文。重置成功与账本原子清理结构保持不变。

## 第三百九十六批验证结果

- 模拟交易平仓、重置、超量拒绝、异常脱敏和账本不变量专项 `19 passed`；模拟交易 Domain/Application、SDK client、账户持仓关闭与统一账本扩展组合 `99 passed`。
- `apps/simulated_trading/interface/sdk_contract_views.py` 增量 mypy 清零并退出债务清单；`unified_position_service.py` 保持清零，全仓基线从 `487 errors / 260 files` 收紧为 `483 errors / 259 files`，净减少 `4 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/MCP、费用执行链或部署实现。

## 第三百九十七批

- 按“AI Provider 可选 SDK 类型漂移 × Responses/Chat/failover 原始异常拼接 × provider 配置无边界 × 动态 adapter 返回 Any”收口 OpenAI-compatible 运行链。
- 可选 OpenAI SDK 改由 importlib 动态边界加载，删除 Optional client 的宽泛 ignore；failover adapter 建立精确 Protocol 与 TypedDict，不再从动态 item 返回 Any。
- base URL 只接受无内嵌凭据的 HTTP(S) 地址并限制长度/控制字符；API key、模型、provider 名称和 provider 数量建立边界，fallback flag 必须为真实 bool。
- temperature 必须为有限 `0..2`，max_tokens 必须为正整数且不超过 1,000,000；非法采样配置在 SDK I/O 前返回 `ai_provider_request_invalid`。
- Responses/Chat 单路失败只发布 `ai_provider_request_failed`、`ai_provider_timeout` 或 `ai_provider_rate_limited`；双路失败发布 `ai_provider_fallback_failed`，不再拼接代理 URL、API key 或 SDK 异常正文。
- provider 初始化、健康检查和多 provider 运行失败分别使用稳定原因/错误码；日志仅记录清洗后的 provider 名称和异常类型，多 provider 全失败不再暴露最后一次异常。

## 第三百九十七批验证结果

- AI Provider Responses、Chat fallback、timeout、配置边界和异常脱敏专项 `11 passed`；用户路由、配置模式、公开 API、Agent Runtime 与 Terminal Agent 扩展组合 `86 passed`。
- `apps/ai_provider/infrastructure/adapters.py` 增量 mypy 清零并退出债务清单；全仓基线从 `483 errors / 259 files` 收紧为 `480 errors / 258 files`，净减少 `3 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/SDK/MCP 成功响应、费用执行链或部署实现。

## 第三百九十八批

- 按“Events 注册/排序无类型合同 × 全局单例并发竞态 × 返回内部可变列表 × 订阅描述无边界”收口跨模块事件订阅注册表。
- `SubscriberInfo` 改为 frozen 值对象并补齐 `__post_init__` 合同；module name、正式 EventType、callable factory、`-10000..10000` priority 和 500 字符无控制符 description 在注册前验证。
- 注册、重复替换、排序、读取、取消和清空全部进入进程内 RLock；同一 module/event 的重复注册在锁内原子替换并按 priority/module name 确定性重排。
- `get_subscribers()` 与 `get_all_subscribers()` 返回防御副本；调用方清空结果或尝试修改订阅信息不再污染全局注册状态。
- process-wide registry 首次构造和 reset 由独立可重入锁保护，并发 Django ready/test reload 不再可能创建多个注册表实例或丢失订阅。

## 第三百九十八批验证结果

- Events 注册校验、防御副本、重复替换、并发注册与 singleton 专项组合 `28 passed`；Domain event bus、初始化失败关闭、故障注入、决策执行和跨 App subscriber 扩展组合 `73 passed, 4 skipped`。
- `apps/events/domain/registry.py` 增量 mypy 清零并退出债务清单；全仓基线从 `480 errors / 258 files` 收紧为 `477 errors / 257 files`，净减少 `3 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/SDK/MCP、费用执行链或部署实现。

## 第三百九十九批

- 按“Audit 失败计数跨进程读改写丢计数 × 原始失败原因/traceback 落 cache 和日志 × 损坏 cache 阻断健康检查 × backend 参数失效”收口审计旁路可观测性。
- 失败总数与 database/validation/repository/timeout/cache/unknown 固定组件计数改用 cache `add/incr` 原子键；两个进程/计数器实例共享 backend 时不再因整份 stats payload 竞争而丢失计数。
- legacy stats JSON 继续兼容读取；动态 payload 逐项校验非负整数、有限组件集合、aware ISO 时间和最多 10 条记录，错误类型、非法日期、非对象列表和损坏计数安全降级。
- component 规范为有限类别，reason 只保留 timeout/database/connection/validation/repository/audit-write 稳定原因；PostgreSQL/Redis URL、凭据和底层异常正文不再进入 cache 或日志。
- `exc_info=True` 不再输出 traceback，只记录已抑制提示；cache get/incr/reset 自身失败仅记录异常类型，计数器故障继续不阻断主业务。
- named cache alias 现在真实通过 Django `caches` 解析；默认 cache 保持兼容。健康阈值只接受 `1..1000000` 正整数，全局计数器首次构造增加进程内锁。

## 第三百九十九批验证结果

- Audit Counter 原子计数、敏感原因脱敏、损坏 cache、backend、阈值与 cache 故障专项组合 `43 passed`；Audit 健康报告、接口服务、权限、公开 API 和用例扩展组合 `166 passed`。
- `apps/audit/infrastructure/failure_counter.py` 增量 mypy 清零并退出债务清单；全仓基线从 `477 errors / 257 files` 收紧为 `474 errors / 256 files`，净减少 `3 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/SDK/MCP、费用执行链或部署实现。

## 第四百批

- 按“Equity 估值修复历史输入无合同 × as-of 后记录进入算法 × 乱序/重复/非有限值污染扩张窗口 × Regime/Pool 端口裸容器”收口估值修复 Domain 链。
- 新增 `ValuationHistoryRecord` TypedDict；trade_date 必须为 plain date 且唯一，PE 可空但必须有限，PB 必须为正且有限。历史记录进入扩张窗口前按日期排序，乱序输入不再改变结果。
- `analyze_repair_status(as_of_date=...)` 在校验估值数值前先排除未来记录；未来 NaN/Infinity 或极值不再污染历史时点结论，Application 单股重算正式向 Domain 传递 as-of date。
- lookback 限制为 `1..100000`，confirm/stall window 必须为正整数，rebound/progress 阈值必须有限且非负；PercentilePoint 日期严格递增且所有分位处于 `0..1`。
- 修复启动确认窗口改为包含第 `confirm_window` 个交易日，消除边界日反弹被漏判的 off-by-one；`detect_stall` 正式接受无修复起点的可空日期合同。
- RegimeDataPort 使用精确 `RegimeSnapshot` list/optional，StockPoolPort 元数据使用 `dict[str, object] | None`，移除无参数 Optional、裸 list/dict 和多余 abstractmethod。

## 第四百批验证结果

- Equity 估值输入治理、PIT、窗口边界、排序、重复日期和有限性专项组合 `99 passed`；估值修复 Domain/Application、质量门禁、公开 API 和配置集成扩展组合 `184 passed`。
- `apps/equity/domain/ports.py` 与 `apps/equity/domain/services_valuation_repair.py` 增量 mypy 清零并退出债务清单；Application use case 与 Infrastructure adapter 联合检查保持零回归，全仓基线从 `474 errors / 256 files` 收紧为 `468 errors / 254 files`，净减少 `6 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 TUI/Terminal/SDK/MCP、费用执行链或部署实现。

## 第四百零一批

- 按“生成型审计证据可由 Django Admin 伪造/改写/删除 × Admin 泛型合同缺失 × 经验总结正文可绕过归因流程修改”收口 Audit Admin 治理入口。
- `AuditReport`、`AttributionReport`、`LossAnalysis`、`IndicatorPerformanceModel` 与 `ValidationSummaryModel` 统一使用不可变证据 Admin；全部模型字段只读，后台新增、修改和删除均失败关闭，证据只能由正式归因、验证和仓储流程生成。
- `ExperienceSummary` 禁止后台新增和删除，归因生成的报告、经验正文、建议与优先级保持只读；仅保留 `is_applied` 与 `applied_at` 两个应用跟踪字段可由有权管理员更新。
- `IndicatorThresholdConfigModel` 继续保留受控 Admin 编辑能力，不把运行时配置误当成审计证据锁死。
- 7 个 Admin 全部迁移到项目统一 `TypedModelAdmin` 合同；新增注册唯一性、生成证据不可变和经验总结字段边界测试。

## 第四百零一批验证结果

- Audit Admin 专项 `3 passed`；Audit Domain/Application、仓储完整性、接口、归因/验证集成和现有审计控制台扩展组合 `168 passed`。
- `apps/audit/interface/admin.py` 增量 mypy 清零并退出债务清单；全仓基线从 `468 errors / 254 files` 收紧为 `461 errors / 253 files`，净减少 `7 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 Audit 生成/读取 API、TUI/Terminal/SDK/MCP 或部署实现。

## 第四百零二批

- 按“Capability 路由/同步日志可由 Admin 删除 × semantic_key 可绕过幂等审计流程直改 × Catalog 可被后台临时删除 × 风险展示元数据动态挂载”收口 AI Capability Admin 治理入口。
- Routing Log、Sync Log、Semantic Override 与 Semantic Audit 统一为完全不可变证据 Admin；全部字段只读，新增、修改和删除均失败关闭，现有 override 移除继续走正式语义治理事务与追加审计。
- Catalog 的 `semantic_key` 与 `collected_semantic_key` 固定只读，语义修正必须经过已有 preview/apply、幂等键、fingerprint 和 audit 流程；风险等级、确认要求、路由开关与 review status 仍保留人工治理能力。
- Catalog 禁止后台直接删除，退役继续由同步器和治理服务负责；风险等级展示改用 `@admin.display`，动态标签由 `format_html` 转义并保留排序合同。
- 5 个 Admin 全部迁移到统一 `TypedModelAdmin` 合同；新增注册唯一性、证据不可变、Catalog 字段边界与风险标签转义测试。

## 第四百零二批验证结果

- AI Capability Admin/语义治理专项 `7 passed`；完整单元、组件、Catalog/MCP 投影、路由、同步与语义治理 API 扩展组合 `704 passed`。
- `apps/ai_capability/interface/admin.py` 增量 mypy 清零并退出债务清单；全仓基线从 `461 errors / 253 files` 收紧为 `455 errors / 252 files`，净减少 `6 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 Catalog 同步/路由/语义治理 API、TUI/Terminal/SDK/MCP 成功响应或部署实现。

## 第四百零三批

- 按“回测结果/成交证据可由 Admin 删除 × 完成态裸 dict 无合同 × NaN/Infinity 与动态对象可进入 JSON/指标事实 × 调用方可变容器回写已发布证据”收口 Backtest 结果持久化链。
- `BacktestResultModel` 与 `BacktestTradeModel` 统一为不可变证据 Admin，所有模型字段只读，后台新增、修改和删除均失败关闭；清理继续走 owner-scoped repository 或受控 retention task。
- 回测结果 Admin 首屏新增 `trust_status/use_pit_data`，详情显式发布 data manifest、PIT coverage、config hash、code commit、engine version、research trial、decision snapshot、signal config 与 used signals，便于核查可复现性证据。
- 新增 Domain `BacktestCompletionPayload` 合同并由正常回测与 Decision Replay 共同使用；Application 不反向依赖 Infrastructure，Repository 在调用完成态模型方法前构造精确 TypedDict。
- `mark_completed()` 在修改模型前一次性验证 final capital、收益、回撤和 Sharpe 为有限数且拒绝 bool；权益曲线、Regime 历史与成交必须为有限、可 JSON 序列化且单字段不超过 8 MiB，warning 数量/长度有界。
- 完成态 JSON 经过序列化 round-trip 与调用方容器隔离，final capital 通过十进制字符串进入 DecimalField；任一字段非法时保持 pending 状态且不产生部分写入。

## 第四百零三批验证结果

- Backtest Admin 与完成态边界专项 `10 passed`；任务、Repository、Decision Replay、owner-scoped API、指标完整性和真实回测执行扩展组合 `83 passed`。
- `apps/backtest/interface/admin.py` 与 `apps/backtest/infrastructure/models.py` 增量 mypy 清零并退出债务清单；Domain payload、Decision Replay 与 Repository 联合检查保持零回归，全仓基线从 `455 errors / 252 files` 收紧为 `446 errors / 250 files`，净减少 `9 errors / 2 files`。
- Django system check、迁移漂移检查、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 Backtest API 成功响应、TUI/Terminal/SDK/MCP 或部署实现。

## 第四百零四批

- 按“Regime V2 动量方向类型失真 × NaN/Infinity 可进入象限概率和置信度 × 非法 period 改变 Python 索引语义 × 失序阈值可发布矛盾判定”收口核心象限 Domain 算法。
- `calculate_momentum_simple()` 正式返回 `tuple[float, int]`，方向只允许 `-1/0/1`；period 必须为非 bool 的正整数，完整历史序列必须为有限数，有限输入相减溢出也失败关闭。
- ThresholdConfig 构造时验证所有阈值有限、PMI contraction 不高于 expansion、CPI 满足 `deflation <= low <= high`，momentum/confidence 权重限制在 `0..1`。
- 水平分类、距离分布、Z-score、动量强度和主 Calculator 统一拒绝 bool、NaN 与 Infinity；分布距离改用 `hypot`，极端但有限观察导致权重下溢时稳定降级为四象限均匀分布。
- RegimeCalculationResult 在发布时验证 Regime、confidence、增长/通胀水平、状态枚举、趋势对象以及四象限键/概率范围/总和；非有限或非归一化证据不能进入 Application、API、任务或审计消费者。
- 主 Calculator 要求 plain `date` as-of，历史任一点损坏即失败关闭；空数据继续返回带“数据为空”warning 的零置信度安全结果。

## 第四百零四批验证结果

- Regime V2 原有与有限性/阈值/period/分布专项 `40 passed`；Regime Domain、UseCase、任务、API、编排、Interface 与重算命令扩展组合 `108 passed`。
- `apps/regime/domain/services_v2.py` 增量 mypy 清零并退出债务清单；全仓基线从 `446 errors / 250 files` 收紧为 `444 errors / 249 files`，净减少 `2 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 Regime API 成功响应、阈值数据库结构、TUI/Terminal/SDK/MCP 或部署实现。

## 第四百零五批

- 按“Backtest 价格点允许 bool/零值/NaN/Infinity × supports 异常中断 failover × 主源动态序列未经资产/日期校验 × 上游异常正文和 traceback 进入日志”收口组合行情边界。
- `AssetPricePoint` 改为 frozen 规范事实；资产、来源和 plain-date 必须有效，价格接受标准数值/Decimal 但必须为有限正数并统一收窄为 float，控制字符和超长标识失败关闭。
- Composite adapter 防御复制 adapter/default price 配置；default price 必须有限正数，只有显式 `use_defaults=True` 时才发布默认资产支持，调用方后续修改原 dict 不再改变运行结果。
- `supports/get_price/get_prices` 统一校验资产、日期与 cache flag；单个 adapter 的 supports/read 异常被隔离，日志仅发布安全 source、operation 和异常类型，不再包含数据库 URL、Token、异常正文或 traceback。
- 单点价格拒绝 bool、非有限值与非正值后继续 failover；序列只接收正式 AssetPricePoint、目标资产和请求区间内记录，按日期排序并以最后一条规范事实去重，动态对象、错资产和越界记录不进入 Attribution。
- Data Center adapter 直接读取同样校验 finite positive price、plain-date 区间和来源；损坏 bar 单条跳过，仓储异常只记录异常类型。默认工厂使用显式 `list[AssetPriceAdapterProtocol]`，修复 Data Center/Tushare 异构列表类型失真。

## 第四百零五批验证结果

- 价格点、默认值、单点/序列 failover、脱敏和 Data Center 读取专项 `16 passed`；Backtest 任务、Audit Attribution/actual-regime 与 Data Center 消费者扩展组合 `103 passed`。
- `apps/backtest/infrastructure/adapters/base.py` 与 `composite_price_adapter.py` 增量 mypy 清零并退出债务清单；全仓基线从 `444 errors / 249 files` 收紧为 `441 errors / 247 files`，净减少 `3 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改 Backtest/Audit API 成功响应、TUI/Terminal/SDK/MCP 或部署实现。

## 第四百零六批

- 按“PIT 最新版本窗口注解无法被 Django 类型系统识别 × 同时点修订选择缺少稳定顺序 × 冻结清单旁路篡改后可被重复构建直接复用 × 重复版本 ID 可进入绑定读取”收口 Data Center PIT 证据读取链。
- 最新可见事实改用按 `business_key` 关联的数据库子查询，依次按知识时钟、修订号和主键倒序取一条，并按业务键稳定输出；保持数据库侧过滤效率，同时移除动态窗口字段带来的 ORM 类型债务。
- Django PIT view、manifest build 与 manifest-bound view 统一要求真正 timezone-aware 的时点；自定义 `tzinfo` 但无 UTC offset 的伪 aware 时间不再进入历史时点比较。
- manifest-bound reader 在查询事实库前校验选中版本 ID 为唯一正整数、dataset 非空，并继续核对 content hash 与 payload hash；重复、缺失或被修改的证据失败关闭。
- 确定性 manifest 重复构建后重新计算并核对持久化证据；即使数据库记录被旁路改写，也不再把同一 manifest ID 下的冲突快照返回给 Research、Decision Rhythm 或 Backtest 消费者。
- Repository 最近清单读取正式限制为 `1..500` 的非 bool 整数，避免绕过 Application 边界时出现负切片或无界读取。

## 第四百零六批验证结果

- PIT 历史修订、同时间戳稳定选择、冻结后版本隔离、payload 篡改、清单冲突与重复 ID 专项 `7 passed`；Data Center API、Research promotion、Decision Rhythm 输入快照和关键数据安全扩展组合 `27 passed`。
- `apps/data_center/infrastructure/pit_repository.py` 增量 mypy 清零并退出债务清单；全仓基线从 `441 errors / 247 files` 收紧为 `439 errors / 246 files`，净减少 `2 errors / 1 file`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改公开 API 成功响应或数据库结构。

## 第四百零七批

- 按“Regime 核心实体序列化裸 dict × 数据库资产配置可发布 NaN/越界/倒置或不可成仓区间 × frozen 配置仍向调用方暴露嵌套可变对象 × Navigator 输出无精确合同”收口象限导航 Domain 链。
- Kalman state 与 confidence breakdown 新增精确 TypedDict 序列化合同；Navigator 权重区间、资产指引和关注指标输出同样发布可被 Application 静态消费的字段合同，不再依赖裸容器和动态值推断。
- `RegimeAssetConfig` 在构造时验证正式 Regime/资产类别、有限 `0..1` 风险预算与置信度策略、区间上下限及组合可行性；倒置区间、NaN/Infinity、bool、越界值和无法形成 100% 配置的区间失败关闭。
- 资产区间、风险预算、板块、风格、类别标签和关注指标规则统一深度复制为只读映射/tuple；调用方修改原始数据库 payload 或返回的 sectors/watch list，不再回写已加载的运行时配置。
- 部分数据库覆盖只替换其明确发布的 Regime 字段，缺失 Regime 的权重、预算、板块与风格回落到 Domain 默认值，不再错误借用同一自定义配置中的 Deflation 或空值。
- Navigator 入口要求正式 RegimeType、有限 `0..1` confidence、合法 movement direction/transition target 和 TrendIndicator 列表；关注指标字段、显著性、长度与控制字符在发布前验证。
- Regime movement 测试同步使用 V2 正式 `neutral` 方向，移除历史 `flat` 测试载荷与当前 Domain 合同的漂移。

## 第四百零七批验证结果

- Navigator 权重/风险策略、配置隔离、关注指标和 movement 专项 `42 passed`；全部文件名含 Regime 的 Domain、Application、任务、仓储、编排、Data Center provider、API、Audit Attribution 与 AI Capability 回归 `286 passed`。
- `apps/regime/domain/entities.py` 与 `navigator_services.py` 增量 mypy 清零并退出债务清单；全仓基线从 `439 errors / 246 files` 收紧为 `433 errors / 244 files`，净减少 `6 errors / 2 files`。
- Django system check、改动文件 Ruff、Black、isort、增量 mypy 与全仓 debt baseline 刷新通过；本批未新增数据库 migration，未修改公开 API 成功响应或数据库结构。
