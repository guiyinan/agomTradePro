# ASH-02 独立开发验收清单

本记录依据 Owner 2026-10-18 的有限收口要求：只验 C3c 与有界结算、当前来源用途，不把 ASH-03 或生产验收作为关闭前置。当前状态：七项均已满足 Owner 限定的仓库/本地开发退出标准；ASH-02 关闭，研发焦点转 ASH-03。正式生产、M2/M3 与 B1 不在此次完成声明内。

| 验收项 | 已有提交与证据 | 还缺什么、动作与通过标准 |
| --- | --- | --- |
| C3c 不确定写入、真实 unknown 与计数 | `d4897d3630ad11e5b97969a78856bc83fc12737d`；`docs/testing/a-share-usability-import-outcomes-2026-10-18.json`，801 项本地回归 | 已满足；不重做、不扩职责提取。 |
| 成交时间与获知时间分开 | `1e8a2a77958ca99844ea80ad2bc5191f802f1723`；`docs/testing/a-share-usability-manual-fill-time-2026-10-18.json`，native PostgreSQL 140 项 | 已满足今后写入合同；不回填旧事实，不冒称 M2。 |
| 当前模拟数量与锁内结算 | `91e37c8a8a6744a93682bf67a93760388a176ff3`；`docs/testing/a-share-usability-quantity-rule-math-2026-10-18.json`，177 项 | 已满足有界模拟规则；真实券商持仓及 T+1 导入属于 ASH-03。 |
| 版本化配置的 aware cutoff | `162df3622464faa8190ff79195a191161ac12866`；`docs/testing/a-share-usability-calendar-cutoff-2026-10-18.json`，177 项 | 组件已满足；不把夹具配置当作 Owner 环境已配置。 |
| 正式日历发布到结算引用 | `90841a7e1e91d71ca88a50c1df83f47d9e3f8b00`；`docs/testing/a-share-usability-published-calendar-adapter-2026-10-18.json`，81 项 | 真实仓储、Audit、RawPayload、半开 TTL 的组件组合已满足；与真实来源的联接归最后一项。 |
| 原手工模拟入口 BUY/SELL、稳定幂等键与旧回执兼容 | `d376380c90048bdd5ccfab0978c0e76e99b50a26`；`docs/testing/a-share-usability-current-reference-manual-2026-10-18.json`，755 个唯一节点；182 项 Domain 另计 | 已满足隔离 caller 与账本回归；identity/Risk/calendar 的合成端口不冒充真实来源端到端。 |
| 一份真实现有来源到上述 caller 的有限本地联接 | 已从现有配置来源捕获 SSE/L `stock_basic` 2320 行与 SSE `trade_cal` 2026-10-18..26 九日；使用正式 retainer 留存原件 | 已在隔离 native PostgreSQL 联接真实 RawPayload/Audit、snapshot/mapping、显式本地版本配置、正式日历与 Audit、RuleV3/FeeV2 和原 HTTP caller；实际闭市拒绝，以及明确周一场景的 BUY/SELL、余额拒绝和幂等均通过。 |

这些数字属于各自提交的验收范围，存在范围交叠，不相加成一个新的唯一测试总数。前六份 JSON 的 Git 祖先关系、提交对象和当前 JSON 一致性已单独核对；本次未重跑这些历史测试。

## 具体来源事实与本轮动作

本地原有 `db.sqlite3` 没有 stock_basic retained raw、instrument snapshot/mapping、正式 calendar fact/pointer 或目标配置，且 schema 早于当前代码。此事实来自 sqlite3 `mode=ro` 与 `query_only` 核查；旧库未迁移、写入或恢复。先前静态盘点只说明代码具备留存能力，不能当作原件已经存在。

本轮没有购买新库。使用现有 `.env` endpoint 与 credential，在固定 `94130f88a5282050911d38a0435a8cddd6b401fa` 代码导出中明确选择隔离验证用 `unified_relay` 请求协议，两次物理传输均为 `direct`；这两个维度不同。没有现有数据库 ProviderConfig/egress 规则可被绕过，也没有激活 Owner 或生产 profile。凭据与 endpoint 不进入公开记录。

- stock_basic 原响应 SHA-256：`77304dc532a3b0f15561b9b3757aa6a9287c13fb5998eebdc6822235030d8cfb`；实际本地接收 `2026-10-18T14:44:22.717022+00:00`。
- trade_cal 原响应 SHA-256：`bcbe5a27d81db695abd6094f0171a387496bcb7306e4d7d0efbab3d7b0907615`；实际本地接收 `2026-10-18T14:44:23.653410+00:00`。
- 只选原件明确列出的 `600000.SH / SSE / 主板 / L`，不按前缀猜身份。上游 observed/available 保持 None，source 禁止标记保持原值。
- 10 月 18 日是原件明确的闭市日，真实当前时钟下入口应具体拒绝且账本零变。正常 BUY/SELL 使用明确标注的 10 月 19 日周一确定性测试时钟；保留所有来源接收、数据库物理记录与发布时间，不换交易所时区、不伪造源时钟。测试配置的参考年龄和日历 TTL 明确限定为 86400 秒，不刷新原件年龄。
- SELL 的既有可卖余额由隔离模拟账户的显式测试基线提供；新 BUY 的 pending 仍不能即时卖出。这不证明任何券商的实际可卖余额，后者属于 ASH-03/M2。

最终 actual-caller-05 已执行并通过；未把先前脚本草稿或仅捕获成功当作通过证据。第一次捕获脚本的 AppRegistryNotReady 是 bootstrap 失败，不计作金融行为 RED；第二版在无数据库访问的最小配置下完成两次真实读取。

## 收口后仍分别开放的事项

ASH-03 的真实成交事实保全、余额 inclusion、旧持仓、导入后的 T+1/可卖量与对账；M1 可读调仓计划；M2 实际成交后的持仓正确性；M3 同候选实际环境闭环；来源/配置在 Owner 环境的激活；历史未留存区间、盘中停牌/ST/涨跌停/行情资格；独立 B1 与正式生产签字均保持各自真实状态。

Owner 已说明当前 VPS 尚未实际投入生产、测试环境可随时更新；一次测试升级不等于正式生产或 M3 资格。ASH-02 关闭也不自动部署、回填、开启真实账户或发出订单。


## 本轮实际验证与修复

实际来源 trade_cal 日期降序触发了旧解析器的排序不变量拒绝。Infrastructure 仅在原件身份、哈希、请求和行类型校验后按日期排序；Domain 仍拒绝重复日期、缺日和不合法前交易日。生产变更为一行排序及 docstring。原件、源时钟、各行 previous_open_date 均未修改。永久回归先 2 failed / 13 passed，修复后连同真实原件解析为 16 passed。

四组最终 JUnit 合计 **445 个唯一通过节点**：来源顺序 16、实际 caller 1、日历兼容与最低回归 405、SDK client 23；最低四文件为其中 404 项。无失败、错误或跳过；SDK 有一条既有 Django 弃用警告。环境预检不计入业务数，前六批历史测试不叠加。单文件增量 mypy 与全量债务均为零；架构边界/审计增量违规为零，88 个 freshness 合同通过，模块地图一致。

实际 caller 的墙钟为 2026-10-18T15:20:04.551810Z 至 15:20:13.686803Z。真实周日入口 HTTP400 且账本不变；周一 2026-10-19T02:00:00Z 场景只控制入口/锁内 UOW 的 _ServerUTCClock 与防未来审计的 DjangoSystemAuditClock，不修改 timezone.now、原始接收、落库或发布时间。采用原 ManualTradeAPIView 的原 URLPattern，以私有窄 URLConf 隔离无关根路由；不是全站浏览器验收。RuleV3、FeeV2 和既有可卖 1000 股均为显式本地测试配置，不代表 Owner/券商资格。

BUY100 进入 pending，释放日为 10 月 20 日；重放不新增交易。SELL1100 返回 SELLABLE_BALANCE_INSUFFICIENT；SELL1000 既有基线成功，最终总量100、可卖0。version3 输入绑定 hash 为 ea3af6d59513ca7c2eb5c099e4e765b04d4ee44b0a8e8eca2f1129b174b6641b；场景前后 Audit/Outbox 各1，未追加。上游 observed/available 仍为空，限制标记仍保持原值；使用已实现的显式 current-purpose 合同。

最终业务验证基于固定 94130f88 导出及本修复，静态验证基于 1c11f8e85 导出及相同修复，排除未提交 ASH03/TUX2。此分层开发证据不构成同 SHA 的发布候选、S6、生产 B1 或正式 M3。S5 settings 未列入最初硬编码 manifest；另有执行时补充身份记录，最终哈希一致。保留所有前序失败和 S4 隔离记录，不修复复用失败库。最后 caller、原件重放 helper 与窄 URLConf 以 LF 换行导出另存 artifacts 的 .py.txt（原字节哈希仍见执行 manifest）；原始供应商响应及凭据不进入 Git。

完整结构化结果见同名 JSON 及其绑定 artifacts。登记完成后的治理检查终态和精确提交清单另保存在本次提交的私有 final manifest；没有部署、推送、业务回填或启用真实自动下单。
