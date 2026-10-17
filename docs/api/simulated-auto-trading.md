# 自动模拟交易触发接口

`POST /api/simulated-trading/auto-trading/run/` 使用现有登录认证；Session 请求同时需要 CSRF。它触发模拟账户引擎，不是券商下单入口。

## 账户范围

请求可包含 ISO 日期 `trade_date` 和正整数数组 `account_ids`。省略日期使用既有默认日期口径。

| account_ids | 含义 |
| --- | --- |
| 省略 | 仅当前用户本人活跃、已启用自动交易的模拟账户 |
| `[]` | 明确无工作，返回零汇总，不构造引擎 |
| 显式列表 | 整个范围先验证管理权限、模拟账户类型、活跃与自动交易状态，全部通过才构造引擎 |

禁止重复、非正整数和超出 Application 技术批量上限的请求。列表上限由 `MAX_AUTO_TRADING_ACCOUNT_SCOPE_SIZE` 定义，并由 Serializer 引用。

普通用户不能触发其他用户的账户。管理员显式管理其他用户账户沿用既有账户管理策略；省略列表时管理员仍只选择本人账户。真实账户、停用账户和未启用自动交易的账户不能通过显式列表触发。范围预检失败时，已验证的前缀账户也不会先执行。

| 情况 | HTTP 状态 | 执行边界 |
| --- | --- | --- |
| 未登录 | 403（沿用项目 Session 优先的 DRF 认证口径） | 不构造引擎；Application 直接调用的身份拒绝为 401 |
| Session 请求缺 CSRF | 403 | 不进入业务用例 |
| 无权管理显式账户 | 403 | 不构造引擎 |
| 显式账户不存在 | 404 | 不构造引擎 |
| 无效列表或不适格账户 | 400 | 不构造引擎 |
| 授权范围或明确空范围 | 200 | 非空范围仅以明确 ID 列表调用引擎 |

响应使用 JSON。范围错误保留 `success=false` 与用户可理解的 `error`；通过范围预检的业务执行返回 200，并保留 `trade_date`、`total_accounts`、`results` 和 `summary.total_buy_count/total_sell_count`。业务是否完成以 `outcome` 为准，不能只看 HTTP 200 或兼容字段 `success`。

## 业务结果

| outcome | 含义 | 兼容 success |
| --- | --- | --- |
| `success` | 有确认成交且所请求账户没有处理问题 | true |
| `partial` | 有确认成交，同时存在失败、阻断或写入不确定 | true |
| `noop` | 合法执行但没有确认成交；包括明确空范围 | true |
| `blocked` | 没有确认成交，处理受到明确业务阻断 | false |
| `failed` | 没有确认成交且处理失败或执行结果不明 | false |

顶层 `requested/succeeded/failed` 的单位是账户；仅完整 success/noop 的账户计入 succeeded，partial 账户计入 failed 并单列 `partial_account_count`。`buy_count/sell_count/confirmed_trade_count` 是确认成交笔数。`stored` 是已知成交写入笔数；任何可能已部分写账但未正常返回的执行都会让 `stored` 为 null、`counts_unavailable` 为 true。确认笔数仍保留，不能把 null 当作零。`count_unit=account`、`stored_count_unit=trade` 和 `count_units` 明确这些单位。

`results` 按所请求账户 ID 返回完整的账户结果，包含稳定原因码和 issue 列表。漏掉请求账户、旧 buy/sell-only 结果、额外账户或畸形映射均不能被解释为普通成功；已有有效的确认笔数仍保留，写入数量转为未知。底层异常原文不进入响应。成交成功后的执行关联或绩效失败返回 partial；关联记录器正常返回空匹配不表示已经建立推荐关联。

激活策略绑定读取失败会阻断该账户，只有确认没有激活的策略绑定才使用既有无策略逻辑。引擎调用开始后的异常不触发服务端整批自动重试；普通消费者仍需后续完成原子结算和幂等接线，手动重复触发不能据此认定安全。

## SDK 与 MCP 账户范围

SDK 的 `run_auto_trading(account_ids=[])` 保留空数组。MCP 的 `trading.start.simulated_auto_trading` 同样保留省略、空数组和非空列表的区别：空数组预览不读取账户、显示零账户，确认后仍以空数组调用现有 SDK/API；非空列表保留顺序。确认流程完成只表示调用已返回，业务结果仍读取 `result.outcome`，不能将 MCP 的 `status=completed` 当作交易成功；`stored=null` 与 `counts_unavailable=true` 原样保留。

MCP 省略列表时沿用默认预览；当前分页、自动交易启用状态筛选及确认时范围绑定仍待后续完善。该默认预览不能视为完整或锁定的最终执行名单，也不提供额外账户权限。

## 验证范围

本接口预检复用 Application 的账户访问 owner 和现有管理策略，没有新增权限授予或默认全账户执行方式。预检不是事务内当前 owner 锁定；普通消费者接入完整结算 UoW 前，该竞争边界仍需后续验收。

本修复不接通候选结算引擎，不修订旧账、不获得可信市场来源或交易用途资格，也不关闭 T+1、零股、费用、历史 PIT 或 QMT/Evidence 的剩余验收项。
