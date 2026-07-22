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
