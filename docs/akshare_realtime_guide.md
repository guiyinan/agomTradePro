# AKShare 实时价格接入指南

> 更新日期: 2026-01-14
> 状态: ✅ 已集成

## 概述

系统现已支持使用 **AKShare** 作为实时价格数据源。

### AKShare vs Tushare 对比

| 特性 | AKShare | Tushare Pro |
|------|---------|--------------|
| **费用** | 完全免费 ❗️ | 免费/付费 |
| **Token** | 不需要 ❗️ | 需要 |
| **实时性** | 盘中实时行情 | 最新交易日数据（免费版） |
| **请求限制** | 无限制 | 2000次/天（免费版） |
| **数据质量** | 高（直接抓取交易所） | 高（官方API） |
| **维护成本** | 低（开源社区维护） | 中（官方维护） |

### 数据源优先级

系统默认使用 **AKShare** 作为主数据源：

```python
# 数据源故障转移顺序
1. AKShare（主数据源，免费）
   ↓ 如果失败
2. Tushare Pro（备用数据源）
```

---

## 无需配置，开箱即用

### 已完成的集成工作

1. ✅ 新增 `AKSharePriceDataProvider` 类
2. ✅ 支持个股实时行情：`ak.stock_zh_a_spot_em()`
3. ✅ 支持指数实时行情：`ak.index_zh_a_spot_em()`
4. ✅ 批量查询优化（一次性获取所有股票）
5. ✅ 自动故障转移（AKShare → Tushare）

---

## 使用方法

### 1. 确保 AKShare 已安装

AKShare 已包含在项目依赖中，无需额外安装。

如需手动安装：
```bash
agomsaaf/Scripts/pip install akshare
```

### 2. 启动服务

```bash
# 激活虚拟环境
agomsaaf\Scripts\activate

# 启动 Django 服务
python manage.py runserver

# （另开终端）启动 Celery worker
celery -A core worker -l info
```

### 3. 验证数据源

访问健康检查 API：
```bash
curl http://127.0.0.1:8000/api/realtime/health/
```

预期响应：
```json
{
    "status": "healthy",
    "data_provider_available": true,
    "timestamp": {...}
}
```

### 4. 测试价格查询

```bash
# 查询单个资产（平安银行 000001.SZ）
curl http://127.0.0.1:8000/api/realtime/prices/000001.SZ/

# 查询多个资产
curl "http://127.0.0.1:8000/api/realtime/prices/?assets=000001.SZ,600000.SH"

# 手动触发价格轮询
curl -X POST http://127.0.0.1:8000/api/realtime/poll/
```

---

## 数据源配置

### 方式1：使用默认配置（推荐）

无需任何配置，系统自动使用 AKShare 作为主数据源。

### 方式2：仅使用 Tushare

如果您想禁用 AKShare，只使用 Tushare：

编辑 `apps/realtime/application/price_polling_service.py`：

```python
# 原代码（使用 AKShare 优先）
self.price_provider = CompositePriceDataProvider([
    akshare_provider,  # 主数据源
    tushare_provider    # 备用数据源
])

# 修改为（仅使用 Tushare）
self.price_provider = CompositePriceDataProvider([
    tushare_provider
])
```

### 方式3：调整数据源顺序

如果您想 Tushare 优先，AKShare 作为备用：

```python
self.price_provider = CompositePriceDataProvider([
    tushare_provider,   # 主数据源
    akshare_provider    # 备用数据源
])
```

---

## 支持的资产类型

### A股个股

- 上交所：600000.SH、600001.SH、...
- 深交所：000001.SZ、000002.SZ、...
- 北交所：832XXX.BJ、...

### A股指数

- 上证指数：000001.SH
- 深证成指：399001.SZ
- 沪深300：000300.SH
- 中证500：000905.SH

---

## API 数据字段说明

### AKShare 返回的字段

| 字段 | 说明 | 示例值 |
|------|------|--------|
| `代码` | 股票代码 | 000001 |
| `名称` | 股票名称 | 平安银行 |
| `最新价` | 最新成交价 | 10.50 |
| `涨跌额` | 价格变动额 | 0.10 |
| `涨跌幅` | 价格变动百分比 | 0.96 |
| `成交量` | 成交量（手） | 100000 |
| `成交额` | 成交额（元） | 10500000 |
| `振幅` | 振幅 | 1.50 |
| `最高` | 最高价 | 10.60 |
| `最低` | 最低价 | 10.40 |
| `今开` | 开盘价 | 10.45 |
| `昨收` | 昨收价 | 10.40 |
| `涨跌数` | 涨跌数 | 10 |
| `涨跌` | 涨跌 | 10 |

---

## 常见问题

### Q1: 为什么选择 AKShare 而不是 Tushare？

**A:**
- **成本**：AKShare 完全免费，Tushare 免费版有请求限制
- **实时性**：AKShare 提供盘中实时行情，Tushare 免费版只有历史数据
- **无限制**：AKShare 无请求次数限制，Tushare 免费版每天 2000 次

### Q2: AKShare 数据准确吗？

**A:**
- AKShare 直接从交易所网站抓取数据，数据准确度高
- 与 Tushare 数据源一致（都是交易所官方数据）
- 缺点：依赖网站结构变化，可能偶尔需要适配更新

### Q3: 可以同时使用两个数据源吗？

**A:** 可以！系统默认配置就是：
- **主数据源**：AKShare（优先使用）
- **备用数据源**：Tushare Pro（AKShare 失败时自动切换）

### Q4: 如何查看当前使用的是哪个数据源？

**A:** 查看日志输出：
```bash
# AKShare 成功
"Retrieved 10/10 prices from AKShare"

# AKShare 失败，切换到 Tushare
"Provider AKSharePriceDataProvider failed: ..."
"Retrieved 8/10 prices from Tushare"
```

### Q5: AKShare 是否支持港股/美股？

**A:**
- AKShare 支持港股和美股数据
- 目前 `AKSharePriceDataProvider` 只实现了 A 股功能
- 如需港股/美股，可以扩展该类添加：
  - `ak.stock_hk_spot_em()` - 港股实时
  - `ak.stock_us_spot_em()` - 美股实时

---

## 扩展 AKShare 支持更多市场

### 添加港股支持

编辑 `apps/realtime/infrastructure/repositories.py`：

```python
class AKSharePriceDataProvider(PriceDataProviderProtocol):
    # ... 现有代码 ...

    def get_realtime_price(self, asset_code: str) -> Optional[RealtimePrice]:
        try:
            import akshare as ak
            symbol = self._convert_to_akshare_code(asset_code)

            # 添加港股支持
            if asset_code.endswith(".HK"):
                df = ak.stock_hk_spot_em()
                df_filtered = df[df['代码'] == symbol]
                # ... 其余代码
```

---

## 更新日志

### 2026-01-14

- ✅ 新增 `AKSharePriceDataProvider` 类
- ✅ 集成到 `PricePollingUseCase`（主数据源）
- ✅ 支持个股和指数实时行情
- ✅ 支持涨跌额、涨跌幅字段
- ✅ 批量查询优化

---

## 相关文档

- [实时价格监控系统文档](realtime_data_system.md)
- [Tushare 接入指南](#)
- [项目结构说明](project_structure.md)
