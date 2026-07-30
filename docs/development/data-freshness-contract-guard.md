# 当前数据新鲜度契约与 CI 门禁

## 目标

所有带有 `current`、`latest`、`realtime`、`summary` 语义的数据面，都必须证明“源数据仍在允许的新鲜度窗口内”，不能仅因为数据库查询返回了最新一行就宣称数据当前可用。

机器真源为 `governance/current_data_contracts.json`，自动检查入口为：

```bash
python scripts/check_current_data_contracts.py
pytest tests/unit/ci/test_check_current_data_contracts.py -q
```

该检查已接入 `.github/workflows/consistency-check.yml`。

## 五条不可破坏的语义

1. **排序最新不等于当前可用**：`get_latest()` 之后必须执行 freshness/reliability 判断。
2. **源观测时间不可变**：`snapshot_at`、`observed_at`、`bar_date`、`as_of` 必须来自源数据；不得用请求时间或计算时间覆盖。
3. **过期结果不能截断 failover**：provider 返回非空但已过期时，组合数据源必须继续尝试后续来源。
4. **降级必须显式**：历史收盘、代理值和不完整数据必须发布明确的 freshness/source/fallback 状态。
5. **决策输出必须失败关闭**：数据不可靠时发布 `must_not_use_for_decision=true` 和稳定的 `blocked_reason`，不得继续生成确定性建议。

## 版本化登记内容

每个当前数据面必须在 manifest 中登记：

- `id`：稳定、唯一的契约标识；
- `surface`：API、SDK、MCP 或内部服务入口；
- `source_files`：实现该语义的生产文件；
- `required_markers`：必须保留的观测时间、阻断与 failover 代码标记；
- `required_tests`：精确到测试函数的证据，并区分 stale/fresh/fallback/observation 等场景。

仅写测试文件名不算证据；检查器会解析 Python AST，确认函数真实存在。

## AST 时间戳洗白门禁

检查器会扫描 `apps/**/*.py`、`sdk/agomtradepro/**/*.py` 和 `sdk/agomtradepro_mcp/**/*.py`（排除 migrations/tests），当前拒绝三类高风险模式：

- 从 `bar/latest_bar/historical/close/nav/fact` 等历史变量构造 `RealtimePrice`，却使用 `timezone.now()` 或 `datetime.now()` 作为行情时间；
- 已包含 `trade_date/as_of/freshness/is_fallback/observed_at` 等来源元数据的 payload，又把 `timestamp` 设置成请求时刻。
- 当 `observed_at/snapshot_at/market_data_as_of` 缺失时，用 `timezone.now()`、`datetime.now()` 或 `date.today()` 补造源观测时间。

真实现货抓取在收到响应时以 `timezone.now()` 记录“抓取观测时间”是允许的，前提是值并非来自历史 bar 或旧 fact。

## 新数据面接入清单

新增任何当前数据读取时，按顺序完成：

1. 在 Domain/DTO 中定义 observation 与 freshness 约束；
2. 在 provider/failover 层区分 missing、stale、fresh；
3. 在 API/SDK/MCP 输出 observation 和决策阻断字段；
4. 写 fresh、stale、fallback、未来时间/naive 时间边界测试；
5. 更新 `governance/current_data_contracts.json`；
6. 运行本门禁、相关回归、mypy 和架构检查。

## 现有受管数据面

当前 manifest 登记 18 个数据面，覆盖：

- Realtime 市场概况、轮询副作用、板块表现与缓存榜单；
- Data Center 最新报价、统一价格、日线收盘/基金净值 failover 与市场温度计；
- Regime 当前状态、缓存行动建议、Core 决策上下文与 Terminal/SDK/MCP 传播；
- Sentiment 当前状态及 Fund/Asset Analysis 消费者；
- Valuation 当前价格 fallback；
- Account 最新汇率、隐式换算与组合币种配置；
- Hedge 最新快照、Rotation 最新信号；
- Equity 分时备用源校验；
- Decision Rhythm 特征快照与统一推荐；
- Pulse 当前快照。

受管范围应随新的决策数据面增加，只能扩展，不能静默删除。
