# AGENTS.md - AgomTradePro 代理开发规则

> 本文件只保留所有代码代理必须常驻上下文的硬约束和文档路由。
> 详细设计、操作步骤与动态状态以链接文档和机器治理文件为准，禁止在此复制形成第二真源。

## 1. 使用方式与真源

- 本文件适用于整个仓库；子目录如有代理说明，只能补充局部规则，不得放宽本文件约束。
- 开始工作前先阅读与本次改动相关的专项文档；不要为无关任务加载全部文档。
- 系统版本见 `docs/VERSION.md`；文档导航见 `docs/INDEX.md`。
- 动态治理规模的唯一真源是 `governance/governance_baseline.json`。
- 运行与开发依赖的唯一真源是 `pyproject.toml`。禁止手工编辑 `requirements-prod.txt`、`requirements-dev.txt`；使用 `python scripts/sync_dependency_projections.py` 生成投影。

项目基线：Python 3.11+、Django 5.x、Celery + Redis；本地可用 SQLite，正式生产使用 PostgreSQL。

## 2. 四层架构红线

所有业务 App 遵循 `Domain → Application → Infrastructure / Interface` 的依赖方向。

### Domain (`apps/*/domain/`)

- 只允许 Python 标准库、`dataclasses`、`typing`、`enum`、`abc`。
- 禁止 `django`、Pandas、NumPy、Requests 和其他外部库。
- 金融实体、值对象、纯业务规则和算法放在此层；值对象优先使用 `@dataclass(frozen=True)`。

### Application (`apps/*/application/`)

- 只编排用例，通过 Protocol、Facade、Query Service、Provider Factory 或构造函数注入访问外部能力。
- 禁止导入 `*.infrastructure.models`、`*.infrastructure.repositories`，禁止任何 `.objects` ORM 访问，也不得用函数内延迟 import 绕过。
- 数据库查询应下沉到 Infrastructure Repository，由 Interface 或 composition root 组装实现后注入。
- 跨 App 优先调用对方公开的 Application UseCase / Service，不得直连其 Infrastructure。

### Infrastructure (`apps/*/infrastructure/`)

- 负责 ORM、Pandas、外部 API、缓存、文件和网络 I/O，并实现 Domain/Application 定义的 Protocol。
- 外部输入必须在进入 Domain/Application 前完成校验、标准化和类型收窄。

### Interface (`apps/*/interface/`)

- 只负责 HTTP/DRF 输入验证、用例调用和输出格式化，禁止业务逻辑。
- 禁止导入任何 `apps.*.infrastructure`；不得直接查 ORM。

CI 会扫描新增行并拒绝以下结构回退：

```text
apps/*/domain/      import django / pandas / numpy / requests
apps/*/application/ import infrastructure models/repositories 或访问 .objects
apps/*/interface/   import apps.*.infrastructure
```

## 3. 模块边界

- `apps/` 承载有业务语义的完整模块；`shared/` 只承载 Protocol、通用算法、配置和无业务语义工具。
- `shared/` 禁止依赖 `apps/`，禁止放 Django Model、业务实体、业务规则和业务默认配置。
- 新增代码不得引入 App 级循环依赖。跨 App 协作优先使用 Protocol、Facade、Registry 或 Domain Event，不得互相 import implementation。
- `data_center` 只负责 provider 协议、注册、统一查询与标准化存储，不得反向依赖业务模块 Infrastructure。
- 全局运行配置归 `config_center`；账户身份归 `account`；组合、持仓和交易流水归 `portfolio`；风险规则与状态归 `risk_center`。

## 4. 通用编码硬约束

- 所有新增或修改的生产函数必须完整标注参数与返回类型；public 函数必须有 docstring。
- 禁止裸 `dict/list/tuple/set/Callable`；可空值显式使用 `T | None`。
- `Any` 只能停留在 JSON、ORM、动态导入和第三方 API 边界，进入 Domain/Application 前必须用 `TypedDict`、dataclass、Protocol、类型守卫或局部 `cast` 收窄。
- 禁止模块级/文件级 `ignore_errors` 和宽泛 `type: ignore`。生产 Python 改动必须通过增量 mypy 门禁，不能抬高债务基线来接受新错误。
- 密钥不得硬编码，统一通过 `shared.config.secrets.get_secrets()` 获取。
- 资产类型、指标代码、量纲规则等业务配置不得新增硬编码，应进入数据库并提供初始化或管理入口。
- Django 启用 `USE_TZ=True`：Domain 使用 `datetime.now(timezone.utc)`；Application/Infrastructure 可使用 `django.utils.timezone.now()`；禁止 naive datetime。
- 调用或测试跨模块实体前先阅读完整定义，核对必填字段、类型及 `date/datetime` 差异。
- 未知事件类型必须映射到专用 `UNKNOWN` 并记录日志，禁止伪装成已有业务事件。
- 外部数值使用 `shared.numeric.safe_float`；缺失值默认 `None`，业务默认值、字符清理和缩放必须显式声明。
- 使用 `core/exceptions.py` 的异常体系；禁止以裸 `Exception` 代替可识别的业务/应用异常。

## 5. 金融与数据正确性

- HP 滤波必须使用扩张窗口，只能在时点 `t` 使用 `series[:t+1]`，禁止全量滤波造成后视偏差。
- Kalman 参数定义在 Domain；技术实现位于 `shared/infrastructure/kalman_filter.py`。
- 投资信号必须包含明确的证伪逻辑和阈值，不能只描述看多/看空理由。
- 数据源必须支持 failover；切换前校验一致性（默认容差 1%），超限应告警，不能静默切换。
- 宏观数据必须包含单位。货币值转换为 catalog/rule 定义的 canonical unit 后存储，原始单位写入审计字段；禁止在业务代码新增单位映射。
- 宏观指标及量纲运行时真源：`IndicatorCatalog`、`IndicatorUnitRule`、`data_center_macro_fact`。
- `latest` 仅表示排序最新，不等于 `fresh/current`；决策数据必须保留源观测时间并发布 freshness、reliability、`must_not_use_for_decision` 和稳定阻断原因。
- 历史数据不得用请求/计算时间伪装为实时数据；failover 遇到 stale 结果必须继续尝试后续数据源。

## 6. 按改动类型加载专项规范

只有触发对应改动时才加载以下文档，并同步更新其治理清单或测试证据。

| 改动类型 | 必读真源 | 必做检查 |
| --- | --- | --- |
| Celery 批量写入/新鲜度任务 | `docs/development/celery-task-contract-guard.md` | 更新 `governance/celery_task_contracts.json`；运行 `python scripts/check_celery_task_contracts.py` |
| `current/latest/realtime/summary` 决策数据 | `docs/development/data-freshness-contract-guard.md` | 更新 `governance/current_data_contracts.json`；运行 `python scripts/check_current_data_contracts.py` |
| TUI metadata/runtime/promotion | `docs/development/tui-user-facing-design-standard.md` | 同步 schema、metadata、compiler/runtime 与测试 |
| Classic Web 模板或 Web→TUI 迁移 | `docs/plans/web-to-tui-migration-plan-2026-07-25.md` | 同步迁移矩阵/配置；运行 `python scripts/web_template_migration_inventory.py --check` |
| Git 分支、提交和合并 | `docs/GIT_WORKFLOW.md` | 遵循下节的最小 Git 规则 |
| API/路由/外包交付质量 | `docs/development/outsourcing-work-guidelines.md` | 添加契约测试并检查所有引用方 |
| 业务含义不确定 | `docs/business/AgomTradePro_V3.4.md` | 先确认规则再实现 |
| 常用命令/API 入口 | `docs/development/quick-reference.md` | 仅作操作参考，不复制到本文件 |

### Celery 任务最低契约

- 在任务/Application 入口校验参数，不能依赖 HTTP Serializer。
- 发布规范化 `outcome`: `success/partial/noop/blocked/failed`；兼容字段 `success` 不能作为唯一依据。
- 统一统计 `requested/succeeded/failed/stored`；部分失败不得返回全成功，零写入必须说明原因。
- Task Monitor、指标和告警读取业务 `outcome`，不得只看 Celery 自身状态。

### TUI 与迁移最低契约

- `/tui/` 是面向用户的任务界面，不是 API 目录；一个 screen 只服务一个主任务并发布 `primary_task`、`primary_outcome`。
- P0 信息必须首屏可见；Token/Endpoint/Prompt 使用专门的可复制呈现语义；用户文案不得泄露 HTTP/API 实现细节。
- 非 dashboard 必须有 `default_action_key`；dashboard 必须有可执行 P0 panel。
- Web→TUI 迁移计划归档前，新业务主任务默认只进入 `/tui/`；Classic 页面只允许缺陷修复、兼容提示和迁移导流。

### Django Admin 最低契约

- Admin 继承 `TypedModelAdmin[ConcreteModel]`；表单继承 `TypedModelForm[ConcreteModel]`。
- 展示列使用 `@admin.display`，批量动作使用 `@admin.action`；禁止动态挂载 `short_description/admin_order_field`。
- Handler 精确标注 `HttpRequest`、`QuerySet[ConcreteModel]` 和返回类型；写入前验证用户已认证且主键非空。
- 每个 App 只保留一个真实 Admin 注册入口。

## 7. 测试、格式化与文档

- 采用 TDD 友好顺序：先确认实体/契约并补测试，再实现；Domain 层覆盖率目标不低于 90%。
- API 路由放 `api_urls.py`，页面路由放 `urls.py`。每个 API 端点应有 Content-Type 和状态码契约测试。
- CRUD 成对操作保持参数签名一致；路由重命名必须同步模板、JS、Python 引用，并添加渲染/契约测试。
- 修复问题时检查同类场景，不能只覆盖眼前样例。
- 代码改动后更新受影响的专项文档；不要修改与本次变更无关的状态性文档。
- 格式化与静态检查使用 Black、isort、Ruff；测试范围应与风险成比例。

生产 Python 文件改动至少运行：

```bash
python scripts/check_mypy_regression.py <changed-production-python-files>
python scripts/check_mypy_debt_ceiling.py
```

仅当历史债务实际下降时才运行：

```bash
python scripts/check_mypy_debt_ceiling.py --write-baseline
```

涉及高风险链路时，按范围运行最小回归包：

```bash
pytest tests/unit/test_tui_workbench.py -q
pytest tests/unit/test_terminal_agent_service.py -q
pytest sdk/tests/test_sdk/test_client.py -q
pytest tests/unit/test_internal_ssl_redirect.py -q
```

## 8. Git 与工作拆分

- `main` 保持稳定；日常开发分支使用 `dev/<type>-<scope>-<description>`，不要使用 `codex/` 前缀。
- Commit 格式为 `<type>: <summary>`，主题使用简短英文；一个 commit 尽量只解决一件事。
- 不得无边界混合功能实现、架构重构、部署修复和治理文档。`terminal/tui`、`agent_runtime/sdk/mcp`、`deploy/vps`、`governance/docs` 应优先拆成独立主线或 commit 组。
- 一条主线连续两个以上提交仍在扩展边界时，补阶段 plan/remediation 文档，记录目标、已完成、剩余、回归范围、风险和回滚点。
- 工作树可能包含用户改动：不要覆盖、回退或顺手格式化无关文件；禁止未经明确授权执行破坏性 Git 操作。

## 9. 完成与交接

- 用户面改动不仅要证明代码能跑，还要验证用户能完成主任务。
- 涉及 `terminal/tui/mcp/sdk/deploy` 时，最终交接必须列出：已完成项、未完成项、已验证测试、未验证风险。
- 不能运行的检查必须明确说明原因和影响，不能以“未报错”代替验证。
- 大型整改必须有清晰完成标准，不得长期停留在“还差一点”的状态。

## 10. 环境约定

- Python 虚拟环境名为 `agomtradepro`。
- PowerShell 脚本内容使用英文。

