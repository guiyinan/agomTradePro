# 基金研究数据链整改记录

> 日期：2026-05-04
> 范围：`apps/fund/infrastructure/repositories.py`、`apps/fund/management/commands/prepare_fund_research_data.py`

## 问题根因

基金研究页面的 `screen` / `rank` 虽然前端链路已恢复，但后端依赖的研究数据链为空：

- `fund_info` 无基金主数据
- `fund_performance` 无预计算业绩
- `data_center` 的 `FundNavFactModel` 为空

导致 `ScreenFundsUseCase` / `RankFundsUseCase` 在查询过去一年基金数据时直接得到空结果。

## 本次整改

### 1. 研究数据解析改为“优先复用、必要时现算”

在 `DjangoFundRepository` 中新增：

- `ensure_fund_universe_seeded()`
- `get_nearest_fund_performance()`
- `get_or_build_fund_performance()`
- `build_and_store_fund_performance()`

效果：

- 如果精确日期的业绩快照不存在，会优先复用相邻日期窗口内的已存快照
- 如果本地已有净值但没有业绩快照，会直接从净值现算并落库
- `get_funds_with_performance()` 不再只依赖“完全命中的预计算业绩”
- `screen` / `rank` 会自动锚到本地最新可用基金数据日，而不是盲目使用系统当前日期

### 2. 修正 Tushare 基金净值字段映射

原 `fund_nav` 适配代码错误地按 `trade_date` 解析 Tushare 返回，实际返回字段为 `nav_date`。

本次修正后：

- `TushareFundAdapter.fetch_fund_daily()` 正确读取 `nav_date`
- provider 同步返回 `0` 时不再错误短路，允许回退到直接 Tushare 拉取
- 基金净值可正确镜像到 `fund_net_value` 和 `data_center` 的基金净值事实表

### 3. 补充基金研究数据准备命令

新增命令：

```bash
python manage.py prepare_fund_research_data --allow-remote-nav-sync --max-funds 30
```

能力：

- 在本地基金主数据为空时，先同步基金主数据
- 按基金代码或基金类型批量准备基金研究数据
- 需要时从 Tushare 拉取缺失净值，再计算并写入业绩快照

常见用法：

```bash
python manage.py prepare_fund_research_data --allow-remote-nav-sync --max-funds 30
python manage.py prepare_fund_research_data --fund-types 股票型,混合型 --allow-remote-nav-sync --max-funds 50
python manage.py prepare_fund_research_data --fund-codes 110011,161725 --allow-remote-nav-sync
```

## 影响

- 新环境不再必须先手工构造“精确日期命中的业绩快照”才能让基金页出数
- 仍建议通过管理命令或后续定时任务批量准备基金研究数据，避免在请求链路中做大规模外部同步
