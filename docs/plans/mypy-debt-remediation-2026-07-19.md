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
