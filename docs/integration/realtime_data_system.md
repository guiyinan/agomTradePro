# 实时价格监控系统

> 实施日期: 2026-01-14
> 状态: ✅ 已完成

## 概述

实时价格监控系统为 AgomSAAF 提供了市场数据实时接入能力，解决了"实时的市场数据还没接进来"的问题。

### 核心特性

- **高频轮询**: 每30秒自动轮询持仓资产价格
- **Redis缓存**: 价格数据缓存5分钟，减少API调用
- **自动更新**: 收盘后自动批量更新所有持仓价格（16:30）
- **前端实时展示**: 价格变化自动高亮显示
- **故障转移**: 支持多数据源自动切换

---

## 架构设计

### 四层架构

```
apps/realtime/
├── domain/                  # Domain 层（纯Python标准库）
│   ├── entities.py          # 实体定义
│   └── protocols.py         # Protocol 接口
├── application/             # Application 层（业务编排）
│   └── price_polling_service.py  # 价格轮询服务
├── infrastructure/          # Infrastructure 层（外部依赖）
│   └── repositories.py      # 仓储实现
└── interface/               # Interface 层（API接口）
    ├── views.py             # 视图
    └── urls.py              # 路由
```

### Domain 层实体

| 实体 | 说明 |
|------|------|
| `RealtimePrice` | 实时价格值对象 |
| `PriceUpdate` | 价格更新事件值对象 |
| `PricePollingConfig` | 轮询配置值对象 |
| `PriceSnapshot` | 价格快照值对象 |

### Protocol 接口

| 接口 | 说明 |
|------|------|
| `RealtimePriceRepositoryProtocol` | 价格仓储接口 |
| `PriceDataProviderProtocol` | 数据提供者接口 |
| `PriceUpdateNotifierProtocol` | 更新通知接口 |
| `WatchlistProviderProtocol` | 关注池提供者接口 |

---

## 数据源

### Tushare Pro

- **适配器**: `TusharePriceDataProvider`
- **数据类型**: 日线数据（"实时"实际为最新交易日数据）
- **支持资产**: A股（上交所/深交所/北交所）
- **更新频率**: 每日收盘后

### 后续可扩展数据源

- FRED（美联储经济数据）
- Bloomberg API
- Wind（万得）
- Choice（集思录）

---

## API 端点

### 价格查询

#### GET /api/realtime/prices/

查询价格数据。

**参数**:
- `assets` (可选): 资产代码列表，逗号分隔

**响应**:
```json
{
    "timestamp": "2026-01-14T10:30:00",
    "prices": [
        {
            "asset_code": "000001.SZ",
            "asset_type": "equity",
            "price": 10.50,
            "change": 0.10,
            "change_pct": 0.96,
            "volume": 1000000,
            "timestamp": "2026-01-14T10:30:00",
            "source": "tushare"
        }
    ],
    "total": 10,
    "success": 10,
    "failed": 0
}
```

#### GET /api/realtime/prices/{asset_code}/

查询单个资产价格。

**响应**: 单个 `RealtimePrice` 对象

### 轮询控制

#### POST /api/realtime/poll/

手动触发价格轮询。

**响应**: `PriceSnapshot` 对象

#### POST /api/realtime/prices/

手动触发价格轮询（别名端点）。

**响应**: `PriceSnapshot` 对象

### 健康检查

#### GET /api/realtime/health/

检查数据源健康状态。

**响应**:
```json
{
    "status": "healthy",
    "data_provider_available": true,
    "timestamp": {...}
}
```

---

## 定时任务

### 收盘后价格更新

- **任务名**: `realtime-update-prices-after-close`
- **执行时间**: 每个交易日 16:30
- **功能**: 批量更新所有持仓资产价格
- **配置位置**: `core/settings/base.py` -> `CELERY_BEAT_SCHEDULE`

```python
'realtime-update-prices-after-close': {
    'task': 'apps.simulated_trading.application.tasks.update_all_prices_after_close',
    'schedule': crontab(hour=16, minute=30, day_of_week='mon-fri'),
    'options': {'expires': 3600}
}
```

---

## 前端集成

### 轮询脚本位置

`core/templates/simulated_trading/my_accounts.html`

### 配置选项

```javascript
const PRICE_POLLING_CONFIG = {
    enabled: true,           // 是否启用轮询
    interval: 30000,         // 轮询间隔（毫秒），默认30秒
    apiEndpoint: '/api/realtime/prices/',
};
```

### 功能特性

1. **自动启动**: 页面加载3秒后自动开始轮询
2. **自动停止**: 页面卸载时自动停止轮询
3. **价格高亮**:
   - 上涨: 红色高亮（2秒）
   - 下跌: 绿色高亮（2秒）
4. **无持仓检测**: 自动跳过无持仓的账户

---

## 使用示例

### 手动触发价格更新

```bash
# 使用 curl
curl -X POST http://localhost:8000/api/realtime/poll/

# 使用 Python
import requests
response = requests.post('http://localhost:8000/api/realtime/poll/')
data = response.json()
print(f"更新完成: {data['success_count']}/{data['total_assets']}")
```

### 查询指定资产价格

```bash
# 查询单个资产
curl http://localhost:8000/api/realtime/prices/000001.SZ/

# 查询多个资产
curl "http://localhost:8000/api/realtime/prices/?assets=000001.SZ,600000.SH"
```

### 健康检查

```bash
curl http://localhost:8000/api/realtime/health/
```

---

## 缓存策略

### Redis 缓存

- **缓存键**: `realtime:price:{asset_code}`
- **过期时间**: 300秒（5分钟）
- **实现**: `RedisRealtimePriceRepository`

### 缓存更新流程

1. 价格轮询服务从数据源获取最新价格
2. 数据立即写入 Redis 缓存
3. 前端查询时优先从缓存读取
4. 5分钟后缓存过期，下次轮询时更新

---

## 监控范围

### 当前实现

- ✅ 持仓资产（从 `PositionModel` 查询）
- ⏳ 关注池资产（待实现 `WatchlistProvider`）

### 监控逻辑

```python
def get_all_monitored_assets(self) -> List[str]:
    held = set(self.get_held_assets())       # 持仓
    watchlist = set(self.get_watchlist_assets())  # 关注池
    return list(held | watchlist)             # 去重合并
```

---

## 故障处理

### 数据源故障转移

`CompositePriceDataProvider` 支持多个数据源自动切换：

```python
providers = [
    TusharePriceDataProvider(),  # 主数据源
    # FREDAdapter(),            # 备用数据源（待实现）
    # ...
]
composite_provider = CompositePriceDataProvider(providers)
```

### 错误处理策略

1. **单资产失败**: 记录日志，跳过该资产
2. **数据源全部失败**: 返回空列表，记录错误日志
3. **Celery任务失败**: 自动重试（最多3次），指数退避

---

## 性能优化

### 批量查询

- 默认批量大小: 100个资产/次
- 减少 API 调用次数
- 降低网络延迟影响

### 请求缓存

- Redis 缓存5分钟
- 避免频繁调用外部 API
- 减轻数据源压力

### 前端优化

- 轮询间隔可配置（默认30秒）
- 无持仓时自动跳过
- 页面卸载时自动停止

---

## 后续优化方向

### 短期（1-2周）

1. **WebSocket 升级**: 从轮询升级为实时推送
2. **关注池实现**: 完善 `WatchlistProvider`
3. **价格变化计算**: 实现 change 和 change_pct 字段

### 中期（1个月）

1. **FRED 数据源**: 接入美联储经济数据
2. **期货数据**: 大连、上海、郑州商品交易所
3. **数据质量监控**: 异常数据检测和告警

### 长期（3个月）

1. **Bloomberg API**: 全球市场数据
2. **Wind 接口**: 国内专业数据
3. **AI 预测**: 使用 AI 进行价格预测

---

## 故障排查

### 价格不更新

1. 检查 Celery worker 是否运行
2. 检查 Tushare token 是否配置
3. 查看 Django 日志
4. 检查 Redis 连接

### 前端不刷新

1. 打开浏览器控制台查看错误
2. 检查 `PRICE_POLLING_CONFIG.enabled` 是否为 `true`
3. 查看网络请求是否成功

### 数据源不可用

```bash
# 健康检查
curl http://localhost:8000/api/realtime/health/

# 手动触发轮询
curl -X POST http://localhost:8000/api/realtime/poll/
```

---

## 相关文档

- [系统概述](SYSTEM_OVERVIEW.md)
- [项目结构](project_structure.md)
- [API 参考](api/API_REFERENCE.md)
- [策略系统实施计划](strategy_system_implementation_plan.md)
