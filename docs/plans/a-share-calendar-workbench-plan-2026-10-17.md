# A 股交易日历 TUI 工作台实施计划（2026-10-17）

本文只规划管理员在 TUI 内完成“读取配置 → 获取预览 → 明确发布 → 查看当前参考日历”的窄任务。现有日历发布 Domain、Application、HTTP API 与正式 Audit/Outbox 行为保持为业务真源；本计划不实现、不发布 metadata、不授予权限、不写入种子，也不把参考日历描述成交易或决策许可。

## 现状和必须保持的边界

现有日历 HTTP 工作流有四个入口：capture、preview、confirm、current，位于 `apps/data_center/interface/api_urls.py` 的日历路由（约 115–135 行）。`calendar_publication_api_views.py` 把它们限定为 JSON、`SessionAuthentication` 和 `IsAuthenticated`；严格 serializer 要求捕获范围、完整 snapshot reference 和服务端预览的完整确认回显。发布还要求真实 `publish_exchange_calendar` 权限。current read 不要求发布权限。

TUI 目前没有日历 screen 或 action。现有管理员 Data Center screen `api-library.data-center` 是全局运行健康任务，定义在 `config/tui/ia/tui_information_architecture.v1.json`（约 162–174 行）；日历任务应有单独的 task screen，不应扩写成 API 目录或混入健康列表。screen 定义仍只放 IA registry，owner action 放 Data Center runtime injection；不另造 screen 路由表。

关键接线缺口是确认回显。日历 preview presenter 会返回完整 `confirmation_intent`，其中包括 snapshot reference、expected identity、expected pointer、activation ID、publication hash 和 preview hash。Workbench 的确认层只把同一 action 的 `params` 原样重试并附加 `confirmed=true` 与通用确认记录；它不会从一个 action 结果中自动构造另一个 action 的嵌套业务 body。因此不能让操作员复制粘贴 JSON/hash，也不能把 Workbench 的按钮确认当成 Data Center 权限或预览证明。

另一个边界是请求认证。外层 `TuiWorkbenchActionRunView` 当前只显式声明 `IsAuthenticated`，并继承项目认证列表；浏览器 `fetchJson` 使用 same-origin credentials 且为非 GET 请求附带 CSRF token。其内部 `TuiInternalActionExecutor` 用默认 `APIRequestFactory()` 直接 dispatch owner view，转递 user、session 和命名的 `Idempotency-Key`，没有开启 factory 的 CSRF 检查，也没有转递外层 request。Calendar session proof 则要求内部 DRF Request 的 `successful_authenticator` 精确为 `SessionAuthentication`、真实 authenticated user、数据库 SessionStore、非空 session key 和 user/database alias 一致。故不能仅凭内层 APIRequestFactory 请求看起来是 SessionAuthentication，就宣称外层 TUI 已通过浏览器 Session+CSRF。

## 最小 UI 方案

新增管理员 screen，建议 canonical key `data-center.exchange-calendar`，归 `system/system-governance`，采用 `task_flow`，`user_experience` 写全 `journey/primary_task/primary_outcome/empty_state_hint/next_step_hint`。主任务是按明确交易所和覆盖日期取得预览、人工确认正式发布、再查看当前 reference。屏幕首个 P0 面板显示唯一配置 scope、合同版本、政策版本/codec、显式 TTL、配置状态与稳定阻断原因；不能显示 provider 凭据或 credential-bearing URL。P0 同时要使“当前参考”状态可见：未选择交易所时明确提示需先选择，不能塞入默认交易所。屏幕空态仍提供下一步 capture 表单，不以无数据的通用 dashboard 结束。

`default_action_key` 使用新的无参只读 `data-center.calendar-scope`，从现有 `resolve_calendar_capture_configuration` 读取唯一已配置 scope，并以不含秘密的 DTO 展示 dataset key/version/schema、policy identity/version/member codec、响应 TTL 和 provider 实例编号/能力。该 DTO 必须把“目录配置已唯一选出”与“capture 已配置但 secret/runtime 尚未核验”分开；它不证明凭据有效、SDK 可用或捕获成功。缺少或存在歧义时显示稳定阻断，不能按名称、priority、最新时间或空 TTL 候选猜选。此读取不发网请求、不读 secret、不执行 capture、不补写配置。

配置状态与 current pointer 状态是独立事实。无参 scope action 没有 exchange，因此不回答任何 exchange 是否有 current；显示“未按交易所查询”，由用户明确选择 exchange 后调用精确 current read。配置缺失、歧义或 inactive 不能被解释成现有 current pointer 已退役或不存在；只有明确 dataset/exchange 的 current reader 可以回答该指针在读取时的状态。若未来需要无参列出已发布 current scopes，必须另行设计精确的 pointer-scope list/read 合同，本计划不假设该入口已存在。

在 scope 行上提供两项显式行操作：

1. `data-center.calendar-prepare-preview`：用户必须填写 `exchange`、`coverage_start`、`coverage_end`。字段来自现有 capture serializer；日期无默认值，exchange 不由代码前缀推断。该 Data Center owner 操作在真实 SessionAuthentication 通过后调用现有 capture 与 preview 用例，返回一条可读预览行并创建该次操作专属 opaque `preview_token`。捕获与预览不等于发布授权；confirm 时必须重新验证真实发布权限。预览行说明 scope、覆盖区间、source first-seen/recorded、configured TTL、response expiry、目标/当前 pointer 摘要和冲突状态；未知 source observed/available time 继续显示未知。它不输出 `confirmation_intent`、RawPayload、完整 JSON/hash，也不发布 pointer。
2. `data-center.calendar-current`：用户明确填写 `exchange`，`dataset_key` 从 scope 行映射，调用现有 current read。若无当前发布，只把精确的 `CALENDAR_CURRENT_PUBLICATION_NOT_FOUND` 呈现为该 scope 的无 current 空态；不得把任意 404/配置故障吞成无数据。

预览行显示可识别的临时引用和业务摘要，但 `preview_token` 不提供复制控件，也不标作 access token、授权码或签名。Dashboard `row_actions.param_map` 已可把 datagrid 行值映射到 action 字段，因此可把该行的 token 映射到隐藏 `preview_token` 字段；这是自动结构传递，不是让用户复制粘贴。Workbench 在渲染 row action 时会把整行和映射参数放入 DOM data attribute，故 token 必须短期、opaque，且即使被读到也不能授予任何权力。可评估复用 TUI 审计脱敏规则；token 不得进入通用 raw-response drawer，calendar action 使用 `raw_debug: false`。

预览行的 row action 指向单独 `data-center.calendar-confirm-preview`，只提交 `preview_token`。Action 元数据采用 admin/write 类别、明确 mutation effect、`confirmation_required=true` 和 `audit_required=true`。Workbench 自带确认弹窗要求用户再点击确认；对话框不接触原始业务 echo。确认 action 返回一条发布回执行，至少标明 dataset/exchange/range、publication ID/hash 的可读摘要、transition、checked time 和结果。该回执行提供“查看当前日历”安全 row action，把 dataset/exchange 映射到已有 current-read action，并将实际日历行展示在同屏 current panel。这样发布回执说明该事务已提交；之后的 current read 才说明读取时 pointer 当前指向什么。

结果字段按 `presentation_semantic=metadata` 展示；只有真正需要的用户材料才声明 `copyable`。完整 hash 可作为短摘要或不展示，不建立复制整段 hash 的路径。所有用户文案只说“正式参考日历/当前参考”，始终展示 `must_not_use_for_decision=true`、`must_not_execute=true`、`blocked_reason=exchange_calendar_reference_only`，以及未知 source clocks。不得使用“交易日历已就绪”“可下单”等结论。

## Opaque preview token 与状态所有权

现有数据库 SessionStore 方案不可接受：已验证的 Middleware 整行保存窗口会使锁内更新与并发请求互相覆盖。后续候选已选择短期 opaque `preview_token`，复用现有 FieldEncryptionService 的认证加密，并将既有环境加密密钥接入中央 `get_secrets`；缺密钥必须明确阻断，不依赖加密器的配置回退。中央 accessor 的默认旧行为保留，显式 env-only 读取不得为获取加密密钥触发数据库或要求行情令牌。候选尚未作为工作台接线验收或发出真实 token，不新增秘密存储或业务表。独立审查已复现候选 codec 未独立核对原 TTL 的合同缺口；必须携带原 first-seen、按原 identity TTL 精确核对 expiry，并从完整服务器 preview 构造，才能接线。该候选尚无生产调用者，正式确认用例仍重新读取并校验源 TTL，不将此描述为已发生发布绕过。密钥轮换后清缓存或重启才生效，滚动期间不同 worker 可能持有不同 key；没有 key ring 或瞬时集群撤销保证。

如果后续采用 `preview_token`，它只承载或定位原 preview 的精确输入，绝不授予发布权。token 必须绑定原始 `response_expires_at`、actor user ID、真实 session key 的不可逆摘要、DB alias、预览 scope/activation/CAS 和 token 版本；不得按当前时间延长 TTL。prepare 与 confirm 都标记 `session_auth_required`，并在真实 SessionAuthentication 外层保护下运行。confirm 时仍须重新获取当前 publisher principal，并复验 token、session/actor/alias、snapshot binding、preview 原 TTL、exact pointer CAS、catalog/policy/fact 身份和正式 Audit/Outbox。不能凭 token 绕过权限检查、重捕获或刷新 CAS；网络重试只能走已有同 activation 精确 replay。过期、session rotation、authority 撤销或 token 篡改都以 typed blocked/conflict 呈现。

普通 Workbench 取消只是关闭确认框，不会调用 owner confirm，也不承诺永久 discard token；UI 应说明取消没有发布。另一个 tab 完成发布后，旧预览 confirm 必须因 CAS 不符而冲突；不静默 refresh 其 expected pointer。成功发布后允许用户对确认结果再点一次“查看当前日历”，以既有 read endpoint 检查实际 current pointer。

## 必要的 TUI session/CSRF extension

为 calendar prepare 和 confirm 增加严格的 action-level `session_auth_required` metadata contract（schema、Application metadata validator 和 action-run gate 一起定义），不要依赖 `audience=admin` 或 `risk=admin` 代替会话认证。外层 action-run 在解析该 action 后，必须要求实际外部 DRF request 的 `successful_authenticator` 精确为 `SessionAuthentication`，身份已认证且对应非空 DB session；否则在任何 owner API 调用前稳定拒绝。`session_auth_required` 不应用于只读全站 action，避免更改其它 TUI token 行为。

浏览器现有路径会用 `credentials: same-origin` 和 `X-CSRFToken` 调用 TUI action-run；DRF `SessionAuthentication` 在外层应完成真正 CSRF 校验。随后 TUI 可以把已验证的同一个用户/session 转交给 owner APIRequestFactory。当前 factory 没启 CSRF 检查，因此方案只允许在外层 session-auth gate 通过后依赖该授权事实；不得声称 inner APIRequestFactory 自己重新做了 CSRF 校验。也不得让 terminal/token/internal-auth 请求以传入 user/session 的方式伪装成 calendar browser publisher。

`TuiInternalActionExecutor` 当前会将外层 TUI idempotency key 转成内部 `HTTP_IDEMPOTENCY_KEY`，但 Calendar API 目前不把它作为发布授权。它只属于 Workbench 每次提交的运输身份；publish 唯一业务重试身份仍来自服务器生成并保存在 preview token 中的 activation ID 和原 echo。不要把 idempotency key 混入业务字段或用它扩权。

## 最小生产文件范围

具体文件可按依赖继续细分，但第一切片限制在以下范围：

- TUI：`config/tui/ia/tui_information_architecture.v1.json`、`config/tui/schema/tui_metadata.schema.v3.json`、`apps/terminal/application/tui_metadata.py`、`apps/terminal/application/tui_workbench_execution.py`、`apps/terminal/interface/api_views.py`、`apps/terminal/infrastructure/tui_adapters.py`、`apps/terminal/infrastructure/tui_metadata_runtime_injection_data_center.py`。仅为 `session_auth_required` 与动作 metadata/请求转递所必需的 JS 调整才改 `frontend/tui-workbench/src/20-dashboard.js`；先用现有 `row_actions` 机制，不预设需要新的通用 result-binding 框架。
- Data Center：可新增 `apps/data_center/application/calendar_workbench.py`（scope/token/use-case ports）、`apps/data_center/interface/calendar_workbench_api_views.py` 与严格 serializer/presenter、token codec adapter，并在 `apps/data_center/calendar_publication_operations_composition.py`/`apps/data_center/interface/api_urls.py` 最小接线。复用 `calendar_capture_configuration.py` 的精确配置选择、现有 capture/preview/confirm/current 用例和正式 Audit bridge；不要另建 provider/client 或 publication repository。
- 当前不预设数据库 migration、secret store 或 token key 的具体实现。scope-context DTO 只能从既有配置选择结果投影必要字段，禁止暴露 secret payload、provider token、原始 body 或无法证实的 source clock；token 实现必须先经中心密钥能力、生命周期和 typed codec 决策。

## 测试与验收顺序

先写失败优先契约用例，再实现 metadata/owner adapter。

1. TUI metadata：screen/action/fields/row action 全部同 screen；default action 是无参 scope read；scope 行 `param_map` 能把 dataset key 和 preview token 准确映射；hidden token 不成为用户必填字段；新 session-auth 属性默认 false 且只在显式配置的 prepare/confirm action 上生效；write action 必须 confirmed/audited 且不可 dashboard 自动执行。缺未知 action、错 screen、缺字段、额外 body、错误 row key 都拒绝。
2. Domain/Application/interface：输入不规范、过期 handle、actor/session/alias mismatch、权限撤回、CAS 漂移、TTL 到期、Audit/Outbox 缺半边都不得发布或修复；没有配置/多配置返回稳定阻断；scope/context 不发 provider 请求；未知源时间保持 null。
3. Token：短期 token 对篡改、错误版本、错误 actor/session/alias、过期 echo 一律拒绝；token key 不可用时 fail closed；token 不包含可读的确认 echo；同 token 确认后的网络重试只返回同一 winner/receipt；不同 preview 同 scope 的第二次确认因 CAS 冲突；对话框取消无 owner request，也不声称已永久撤销 token；失效后只要求用户重新获取新 preview，不延长旧 echo。
4. TUI 内部 auth 必须有 Native PostgreSQL HTTP 旅程：启用真实 SessionMiddleware/DRF SessionAuthentication/CSRF checks，以有效浏览器 CSRF 登录 staff 并授予真实 `publish_exchange_calendar`；从 TUI action-run 外层逐步执行 scope、capture-preview、拒绝/取消、confirm、current read，证明 owner `CalendarSessionRequestClaim` 看见同 user、同真实 DB session key/alias 和 SessionAuthentication。缺 CSRF 在 TUI outer 被拒绝且零 provider/snapshot/token 副作用。另用非 Session token 或 internal auth 身份测试在任何 inner APIRequestFactory dispatch 前被 `session_auth_required` gate 拒绝。需验证 inner factory 的 CSRF-disabled 属性与外层保护边界，不能将其测试结果写成 inner-CSRF 已开启。
5. 浏览器 UAT：普通用户不可见 admin screen/action；授权 staff 首屏立即看到 scope/阻断；输入 exchange/date 后只生成 preview、不发布；显示明确范围/TTL/到期/P0限制；确认 modal 的取消无写；确认后可读当前日历，refresh 与回执在同屏；旧 tab CAS 冲突、过期 handle 需重新预览、无 current 显示可恢复空态。检查键盘/焦点、移动布局、P0 首屏和浏览器控制台无意外错误。

候选实现至少运行 TUI 单测 `agomtradepro\Scripts\python.exe -m pytest tests/unit/test_tui_workbench.py tests/unit/test_tui_metadata_compiler.py tests/unit/test_tui_actionability_contract.py -q -p no:cacheprovider`，owner 日历相关 unit/component 和新增 Native HTTP integration；对全部改动 Python 执行增量 mypy、Black、isort、Ruff。Metadata/前端运行 promotion guide 中的 Django contract export/OpenAPI、metadata validate/generate、source-consistency、copy-density、presentation-details、`npm run test:tui-js`、`npm run check:tui`、`npm run build:tui`。用可丢弃、迁移完整的数据库运行 TUI smoke，禁止广泛允许 4xx/5xx。任何实际 metadata 发布均遵循项目既有 promotion review 与验证流程；这不是本计划另设的用户授权门，本计划和当前任务不执行该操作。

若实现变成新增 Classic route/page 或迁移旧 Web 页面，才更新 route migration matrix 并运行 `scripts/web_template_migration_inventory.py --check`；本切片是新增 TUI admin task，不创建 Classic 页面。只读/当前数据 surface 的治理登记与 `docs/development/data-freshness-contract-guard.md` 应按最终 endpoint contract 评估，reference-only 与禁止决策/执行标记不得被 metadata projection 丢弃。

## 回滚范围

仅回滚新增 TUI screen/actions/schema support、owner TUI adapter/composition 和 token codec 处理；不改变已存在的日历 HTTP 合约、Formal Publication/Pointer/Audit 代码，也不撤回已正式发布的日历。已生成但未过期的 token 是否仍可解析取决于后续获批的版本化 codec/key 退役契约，不能假设部署回滚会即时撤销 token。UI 回滚不能冒充正式 publication rollback。Calendar pointer rollback/reinstatement 当前尚未实现或验收；若将来需要恢复 pointer，必须另行设计、审查并验证正式 rollback/reinstatement 流程，不能声称已有受审流程。

基础认证门禁已有独立冻结验收：六项 Native PostgreSQL APIClient 组件执行真实外层 Session/CSRF、生产内部 executor 和 owner session/grant 校验，证明外层缺 CSRF、匿名、真实 token/internal 认证及撤权的拒绝边界。内部 request factory 仍关闭 CSRF；保护来自真实外层。该测试用只读 owner probe，没有采集/预览/确认/current 的完整工作台业务旅程。

此计划不代表已接入 Calendar 浏览器任务、已发布当前 reference、已验证真实生产源或已获得 failover。scope、中央密钥及 token 的未暂存候选需各自经主代理验收；真实业务接线、浏览器主任务和普通消费者仍待完成，不能将基础门禁标作工作台交付。
