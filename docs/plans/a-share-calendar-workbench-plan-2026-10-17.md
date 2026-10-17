# A 股交易日历 TUI 工作台实施计划（2026-10-17）

> 当前方案及剩余验收门。已接受的 HTTP/TUI 基础与未完成的消费者阶段分开记录；整体 Goal 保持 active。该计划不创建业务默认值、生产权限或数据种子，也不扩大支持市场范围。

## 已接受基线与未完成状态

- scope 选择切片已由 commit 961c3800d 接受；opaque preview token/key 边界已由 commit b8a30b74e 接受。
- 严格 session_auth_required metadata/gate 与 confirmed 必须为 JSON boolean 的入口已接受。缺省 confirmed 为 false；其他类型在任何 executor 副作用前拒绝。
- Calendar HTTP/API 切片由 commit 02540d22c 接受：166 项相关单元测试；8 个生产文件增量检查及全库 mypy 结果为 0；真实 URL 路由 Native Session/CSRF 测试 14 passed（12 项业务流程及 2 项目标资格，34.86 秒）；freshness 85 项和入口目录 1362 项检查通过。首轮 13 passed、1 failed 是旧数据库绑定未关闭的测试夹具错误，修复后的 14 项结果取代首轮作为验收证据。官方生成与最终修正夹具后的入口 stale-check 均已通过；完整证据见[接口检查点](../testing/a-share-usability-calendar-workbench-api-2026-10-17.json)。
- 通用 result_continuation 已独立验收：schema/service/private-tab controller 与配对 bundle/manifest；最终 build 后5项浏览器场景及完整Node 92项通过。Python/type/static/architecture结果来自明确独立源码窗口，相关源LF相等；不累加用例、不冒充同一CI/S6身份。详见[通用交接检查点](../testing/a-share-usability-tui-result-continuation-2026-10-17.json)。
- 确认提交的网络/5xx精确重试、确认前重试返回确认、密码复核、同屏切换清理已关闭。旧令牌和原提交身份不变，密码不保存在重试上下文。Calendar实际owner外层Native和真实浏览器主任务现已独立通过，见本计划C节检查点。
- 已登记的 74 项 closure 单元是既有治理清单；本计划不把它们统称为全部已关闭，也不新增整体规模承诺。DATA-18、ASH-11 仍 incomplete/planned，完整 Goal 未关闭。

## 唯一用户旅程与公开契约

Calendar 采用单独 TUI 管理工作台，screen key 为 data-center.calendar-workbench。runtime action keys 按 owner 命名为：

- data-center.calendar-workbench-scope
- data-center.calendar-workbench-current
- data-center.calendar-workbench-prepare
- data-center.calendar-workbench-confirm

确认目标 action 的精确 key 为 data-center.calendar-workbench-confirm。屏幕和 action 必须由 IA/runtime 正式注册，不能把管理任务塞进 API 目录或通用健康 dashboard。外层 action-run 路径为 /api/tui/actions/{action_key}/run/。

四个公开 Workbench owner 端点为：

- GET /api/data-center/exchange-calendars/workbench/scope/：无参数，展示唯一选中的非秘密合同/政策/TTL 配置和阻断状态。metadata_selected 不证明 secret、SDK 或 provider runtime 可用；它也不代表任何具体交易所已有 current。
- GET /api/data-center/exchange-calendars/workbench/current/?exchange={exchange}：必须显式传一个 exchange。服务端按已选配置和该 exchange 精确读取；普通认证读取不要求发布权限。
- POST /api/data-center/exchange-calendars/workbench/prepare/：JSON 只接受 exchange、coverage_start、coverage_end。服务端捕获并准备预览，回传安全可见摘要和隐藏 continuation。
- POST /api/data-center/exchange-calendars/workbench/confirm/：JSON 只接收 continuation 中的 confirmation_token，由 owner 在锁内重新验证 Session、当前发布权限、原来源/目录身份、原 TTL、完整 CAS 和 Audit/Outbox。

prepare 返回的 continuation action key 必须是 data-center.calendar-workbench-confirm。浏览器只在当前标签页运行时内存中把隐藏 confirmation_token 交给 confirm action；不得显示、复制、写入 URL 或持久化浏览器存储。用户只显式输入交易所和覆盖日期；不输入 dataset、catalog/policy identity、seal、hash、activation ID、token、alias、actor、TTL 或客户端时间。交易所/日期无默认值，不从证券代码推断交易所，不因为 capture/preview 失败而谎称源响应没有保留。

正式发布的四个 HTTP 路径为 POST /api/data-center/exchange-calendars/snapshots/capture/、POST /api/data-center/exchange-calendars/publication-preview/、POST /api/data-center/exchange-calendars/publications/ 和 GET /api/data-center/exchange-calendars/current/。已完成的 Native 14 项是路由真实 Session/CSRF 证据，但不能替代完整 TUI 外层 action-run 到业务 owner 的旅程或新 bundle 浏览器验收。

所有 TUI 写 action 使用 session_auth_required=true、confirmation_required=true 和现有审计合同。浏览器外层必须实际通过 SessionAuthentication 与 CSRF gate；owner 继续独立在锁内校验发布授权。内部 APIRequestFactory 不开启 CSRF，不能描述成再次验证了 CSRF。API token/internal auth 不能伪装 browser publisher。confirmed 缺省为 false，只有精确 JSON boolean 才有效；字符串 false/true、数字、null、数组和对象均稳定 400 拒绝。

预览、发布和实际 current 参考数据继续保留 must_not_use_for_decision=true、must_not_execute=true、source observed/available 未提供及稳定阻断原因；纯 scope 元数据与没有 current 的空态不冒充日历事实。不得描述为“可交易”“日历已满足结算”等状态。

## 有界后续批次

### A. 已完成的 HTTP/API 依赖

依赖基线为 commit 02540d22c。官方生成检查及最终 test-body 修正后的入口投影检查已通过，首次失败与修复后通过的原始证据分别保留。后续接线不放宽该 owner/API 与配置选择合同；如再修改其生产源，重新运行受影响的严格输入、Session/CSRF、TTL/CAS、撤权及 Audit/Outbox 回归。Native 测试在写入与清理前核对真实显式 TEST.NAME；SQLite 不能替代 PostgreSQL 验收。

### B. 已验收的通用 continuation 基础

真实工作台浏览器另发现公开action缺method导致前端将目标识别为GET。该公开投影缺陷已独立修复并通过完整Python/Node和类型/静态门禁，见[机器请求方法检查点](../testing/a-share-usability-tui-public-action-method-2026-10-17.json)。技术endpoint/source仍隐藏；Calendar用户旅程继续单独验收。

本通用阶段已完成取消、失败、过期、新 prepare、同屏动作对和screen变化的清理；源generation避免旧响应覆盖。网络/5xx重放原token/confirmation/key/expiry，首次未确认提交重试后仍需用户确认，密码复核不会保留旧密码。保留真实red和修复后新built-bundle结果。旧81项Node早于新build，未作为本阶段验收。Calendar外层Session/CSRF、owner及真实浏览器主任务独立验收。

### C. Calendar screen 与完整外层 TUI Native / browser journey

本阶段已按最终冻结源码独立验收：125项unit/Service回归、4项外层Native、真实浏览器1项旅程和2项数据库前后核验分别通过，不累计唯一用例。覆盖实际登录/F9/确认/取消/发布/current/撤权只读/普通用户拒绝及移动视口；Provider transport和秘密为合成夹具，数据库业务配置由测试预置，metadata数据库版本选择由真实文件规范化替代。没有实际Provider、生产或消费者资格。精确源、业务/夹具失败原件、类型/架构和生成投影见[工作台TUI检查点](../testing/a-share-usability-calendar-workbench-tui-2026-10-17.json)。

在 IA registry 注册 data-center.calendar-workbench screen 并由 Data Center runtime 提供上述四个 actions。scope 作为默认无参入口；current 要显式 exchange；prepare 只呈现 exchange 与覆盖日期字段；confirm 目标 schema 使用自动隐藏 continuation。metadata 不授予权限、不写默认配置、不展示凭据。用户文案说明无 current、配置阻断、来源 TTL 和 reference-only 边界。

Native 端用真实生产 root URLConf 和 test-only provider transport 完整走通浏览器 Session/CSRF → /api/tui/actions/{action_key}/run/ → owner Composition → capture/preview/formal publish/current。确认：缺 CSRF、匿名和非 Session/internal authenticator 在 owner dispatch 前拒绝；prepare 只生成预览、不发布；用户权限撤回后 confirm 拒绝；普通 current 按普通登录读权限执行；相同原提交的重试仅返回相同当前赢家；第二个 preview forward 后旧 continuation 冲突；篡改、换 session/actor、来源过期、catalog/version/TTL 改变均阻断。测试必须区分外层真实 CSRF 与内部 factory 属性，不伪造 owner proof/grant。

浏览器 UAT 在新 bundle 构建后进行，验证管理员从 scope/阻断状态完成 preview、独立确认与 current read；普通用户不能看到管理员操作；取消清空 continuation；请求异常时只提供契约定义的精确重试；过期或 CAS 冲突重新预览；检查键盘/焦点、移动视口、DOM/URL/持久化存储及 console。测试账号和合成 Provider 仅限隔离环境，不连接真实 Provider 或生产账号。

### D. Simulated-trading / backtest 消费者（独立后续阶段）

消费者接线另开阶段，不能与管理员工作台一起验收。consumer 必须使用正式发布绑定、精确 exchange、来源 TTL 和 PIT knowledge cutoff；不能拿“今天 current pointer”重建历史交易日的日历事实。缺失 publication binding、覆盖不足、过期、exchange 不匹配或历史 knowledge 不充分时 fail closed。参考日历目前的 must_not_use_for_decision 与 must_not_execute 标志不能由当前指针读取自动提升；消费端资格、历史结算语义和来源范围需由各业务 owner 独立审查和验收。

## 验收、回滚与范围限制

复用已登记的 74 项 closure 单元清单并按本次改动路径选取既有回归，不把清单数量当全部关闭证明，也不扩大交易所/板块或业务支持矩阵。Python 改动执行增量 mypy、Black、isort、Ruff；metadata/runtime 改动执行对应 schema/compiler、Node/build 和生成一致性检查。每个阶段以冻结源、准确测试目标和真实日志验收；首次失败不能与后续通过拼接。

回滚可以撤下新增 screen、runtime metadata 和 owner 接线，但不能删除已提交的 snapshot/publication/Audit 记录。它也不能恢复正式 pointer 或历史 PIT；未过期 continuation 是否仍可解析须按 codec/key 版本合同处理，不能声称部署回滚立刻撤销。Calendar pointer 回滚/reinstatement 与消费者历史重建均不在本计划范围。

**撤回说明：**早期的 row_actions.param_map、用户复制或填写 token、逐行确认、数据库 SessionStore 交接及“取消即永久撤销”假设全部撤回。当前方案只使用同屏、当前标签页内存的 result_continuation 与严格 Session/confirmation gate。

没有真实 Provider 采集、生产发布、券商动作或 live-gate 放行。该工作台只处理交易日历参考事实的 capture/preview/formal publication/current read；不表示 A 股交易规则完整、结算已接线或 broker 已接受。DATA-18、ASH-11 与完整 Goal 保持 open。

通用 TUI 回退时须按同一版本配对 schema、metadata reader/validator、runtime source、bundle 与 manifest；先撤下或禁用依赖 continuation 的新 screen/actions，再退回不理解该语义的旧客户端。不能遗留要求隐藏令牌的 action 让旧 UI 进入不可见必填循环。当前未进行生产 promotion 或部署，本节仅定义回滚边界。
