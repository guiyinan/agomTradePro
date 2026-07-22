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
