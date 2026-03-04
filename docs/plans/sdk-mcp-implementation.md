# AgomSAAF 接口层实现计划（MCP + SDK 组合方案）

> 创建 MCP Server 和 Python SDK，让 Claude Code 等 AI agent 能够通过多种方式操作 AgomSAAF 系统

## 项目概述

- **目标**: 创建 `agomsaaf-sdk` 项目，包含 Python SDK 和 MCP Server
- **位置**: `D:\githv\agomSAAF\sdk\`（AgomSAAF 项目内部）
- **原则**: 不修改 AgomSAAF 系统代码，只通过 HTTP API 调用
- **功能**: 支持完整操作（查询 + 写入）
- **架构**: MCP Server（快速操作）+ Python SDK（完整功能）

### MCP vs SDK 分工

| | MCP Server | Python SDK |
|---|---|---|
| **用途** | 常用操作、快速查询 | 完整功能、复杂逻辑 |
| **调用方式** | AI 原生工具调用 | Python 代码 |
| **覆盖范围** | ~20% 核心 API | 100% API |
| **数据处理** | 简单 JSON 返回 | 可用 pandas 处理 |
| **典型场景** | "获取当前 Regime" | "批量回测+数据分析" |

---

## 目录结构

```
sdk/
├── agomsaaf/                      # Python SDK 主包
│   ├── __init__.py
│   ├── client.py                  # 核心客户端类
│   ├── config.py                  # 配置管理
│   ├── exceptions.py              # 统一异常定义
│   ├── types.py                   # 类型定义
│   └── modules/                   # 业务模块封装
│       ├── __init__.py
│       ├── base.py                # 模块基类
│       ├── regime.py              # Regime 判定
│       ├── signal.py              # 投资信号
│       ├── macro.py               # 宏观数据
│       ├── policy.py              # 政策事件
│       ├── backtest.py            # 回测引擎
│       └── account.py             # 账户管理
│
├── agomsaaf_mcp/                  # MCP Server
│   ├── __init__.py
│   ├── server.py                  # MCP 服务器主文件
│   └── tools/                     # MCP 工具定义
│       ├── __init__.py
│       ├── regime_tools.py        # Regime 相关工具
│       ├── signal_tools.py        # Signal 相关工具
│       ├── macro_tools.py         # Macro 相关工具
│       └── backtest_tools.py      # Backtest 相关工具
│
├── tests/
│   ├── conftest.py
│   ├── test_sdk/                  # SDK 测试
│   └── test_mcp/                  # MCP 测试
│
├── pyproject.toml
├── README.md
└── LICENSE
```

---

## 实现状态

### Phase 1: 项目骨架（已完成）✅

1. ✅ 创建项目目录结构
2. ✅ 编写 `pyproject.toml`
3. ✅ 实现 SDK 基础：
   - ✅ `client.py` - 核心客户端类
   - ✅ `exceptions.py` - 异常定义
   - ✅ `config.py` - 配置管理
   - ✅ `types.py` - 类型定义
4. ✅ 实现 MCP 基础：
   - ✅ `server.py` - MCP 服务器

### Phase 2: Python SDK 核心模块（已完成）✅

1. ✅ `modules/base.py` - 模块基类
2. ✅ `modules/regime.py` - Regime 判定
3. ✅ `modules/signal.py` - 投资信号
4. ✅ `modules/macro.py` - 宏观数据
5. ✅ `modules/policy.py` - 政策事件
6. ✅ `modules/backtest.py` - 回测引擎
7. ✅ `modules/account.py` - 账户管理

### Phase 3: MCP Server 工具（已完成）✅

1. ✅ `tools/regime_tools.py` - Regime 相关 MCP 工具
2. ✅ `tools/signal_tools.py` - Signal 相关 MCP 工具
3. ✅ `tools/macro_tools.py` - Macro 相关 MCP 工具
4. ✅ `tools/backtest_tools.py` - Backtest 相关 MCP 工具

### Phase 4: SDK 扩展模块（已完成）✅

1. ✅ `modules/simulated_trading.py` - 模拟盘交易
2. ✅ `modules/equity.py` - 个股分析
3. ✅ `modules/fund.py` - 基金分析
4. ✅ `modules/sector.py` - 板块分析
5. ✅ `modules/strategy.py` - 策略管理
6. ✅ `modules/realtime.py` - 实时价格监控

### Phase 5: MCP 扩展工具（已完成）✅

1. ✅ `tools/simulated_trading_tools.py` - 模拟盘交易工具
2. ✅ `tools/equity_tools.py` - 个股分析工具
3. ✅ `tools/fund_tools.py` - 基金分析工具
4. ✅ `tools/sector_tools.py` - 板块分析工具
5. ✅ `tools/strategy_tools.py` - 策略管理工具
6. ✅ `tools/realtime_tools.py` - 实时价格工具
7. ✅ `tools/policy_tools.py` - 政策事件工具
8. ✅ `tools/account_tools.py` - 账户管理工具

### Phase 6: 文档和测试（已完成）✅

1. ✅ `README.md` - 项目说明（更新，包含所有模块和工具）
2. ✅ `docs/sdk/quickstart.md` - 快速开始指南
3. ✅ `docs/mcp/mcp_guide.md` - MCP 使用指南
4. ✅ `docs/sdk/api_reference.md` - API 参考文档
5. ✅ `docs/examples/` - 使用示例：
   - ✅ `basic_usage.py` - 基础使用示例
   - ✅ `backtesting.py` - 回测示例
   - ✅ `data_analysis.py` - 数据分析示例（pandas）
   - ✅ `simulated_trading.py` - 模拟盘交易示例
   - ✅ `equity_fund_analysis.py` - 股票基金分析示例
   - ✅ `realtime_strategy.py` - 实时监控和策略示例
6. ✅ `tests/conftest.py` - 测试配置
7. ✅ `tests/test_sdk/test_client.py` - 客户端测试
8. ✅ `tests/test_sdk/test_regime_module.py` - Regime 模块测试
9. ✅ `tests/test_sdk/test_signal_module.py` - Signal 模块测试
10. ✅ `tests/test_sdk/test_macro_module.py` - Macro 模块测试
11. ✅ `tests/test_sdk/test_backtest_module.py` - Backtest 模块测试

---

## 实现总结

### 完成状态

| Phase | 描述 | 状态 |
|-------|------|------|
| Phase 1 | 项目骨架 | ✅ 完成 |
| Phase 2 | Python SDK 核心模块 | ✅ 完成 |
| Phase 3 | MCP Server 工具（核心） | ✅ 完成 |
| Phase 4 | SDK 扩展模块 | ✅ 完成 |
| Phase 5 | MCP 扩展工具 | ✅ 完成 |
| Phase 6 | 文档和测试 | ✅ 完成 |

### 项目统计

- **Python SDK 模块**: 13 个
- **MCP 工具**: 50+ 个
- **测试文件**: 6 个（核心模块覆盖）
- **文档文件**: 7 个
- **示例文件**: 6 个

### 文件清单（60+ 文件）

#### SDK 核心文件 (20)
- `agomsaaf/__init__.py`
- `agomsaaf/client.py`
- `agomsaaf/config.py`
- `agomsaaf/exceptions.py`
- `agomsaaf/types.py`
- `agomsaaf/modules/__init__.py`
- `agomsaaf/modules/base.py`
- `agomsaaf/modules/regime.py`
- `agomsaaf/modules/signal.py`
- `agomsaaf/modules/macro.py`
- `agomsaaf/modules/policy.py`
- `agomsaaf/modules/backtest.py`
- `agomsaaf/modules/account.py`
- `agomsaaf/modules/simulated_trading.py`
- `agomsaaf/modules/equity.py`
- `agomsaaf/modules/fund.py`
- `agomsaaf/modules/sector.py`
- `agomsaaf/modules/strategy.py`
- `agomsaaf/modules/realtime.py`

#### MCP Server 文件 (15)
- `agomsaaf_mcp/__init__.py`
- `agomsaaf_mcp/server.py`
- `agomsaaf_mcp/tools/__init__.py`
- `agomsaaf_mcp/tools/regime_tools.py`
- `agomsaaf_mcp/tools/signal_tools.py`
- `agomsaaf_mcp/tools/macro_tools.py`
- `agomsaaf_mcp/tools/policy_tools.py`
- `agomsaaf_mcp/tools/backtest_tools.py`
- `agomsaaf_mcp/tools/account_tools.py`
- `agomsaaf_mcp/tools/simulated_trading_tools.py`
- `agomsaaf_mcp/tools/equity_tools.py`
- `agomsaaf_mcp/tools/fund_tools.py`
- `agomsaaf_mcp/tools/sector_tools.py`
- `agomsaaf_mcp/tools/strategy_tools.py`
- `agomsaaf_mcp/tools/realtime_tools.py`

#### 测试文件 (7)
- `tests/conftest.py`
- `tests/test_sdk/__init__.py`
- `tests/test_sdk/test_client.py`
- `tests/test_sdk/test_regime_module.py`
- `tests/test_sdk/test_signal_module.py`
- `tests/test_sdk/test_macro_module.py`
- `tests/test_sdk/test_backtest_module.py`
- `tests/test_mcp/__init__.py`

#### 文档文件 (7)
- `README.md`
- `docs/sdk/quickstart.md`
- `docs/mcp/mcp_guide.md`
- `docs/sdk/api_reference.md`
- `docs/examples/basic_usage.py`
- `docs/examples/backtesting.py`
- `docs/examples/data_analysis.py`
- `docs/examples/simulated_trading.py`
- `docs/examples/equity_fund_analysis.py`
- `docs/examples/realtime_strategy.py`

#### 配置文件 (3)
- `pyproject.toml`
- `LICENSE`
- `docs/plans/sdk-mcp-implementation.md`

---

## 使用示例

### 方式 1: MCP 工具（快速操作）

Claude Code 直接调用 MCP 工具，无需写代码：

```
# Claude 对话
用户: 当前处于什么宏观象限？
Claude: [调用 get_current_regime 工具]
       当前处于 Recovery（复苏）象限，增长向上，通胀向下。

用户: 这个象限适合投资什么？
Claude: [调用 get_recommended_assets 工具]
       Recovery 象限推荐: 股票、商品、房地产
```

### 方式 2: Python SDK（完整功能）

```python
from agomsaaf import AgomSAAFClient
from datetime import date

# 初始化客户端
client = AgomSAAFClient(
    base_url="http://localhost:8000",
    api_token="your_token_here"
)

# 1. 获取当前 Regime
regime = client.regime.get_current()
print(f"当前处于 {regime.dominant_regime} 象限")

# 2. 检查信号准入
eligibility = client.signal.check_eligibility(
    asset_code="000001.SH",
    logic_desc="PMI 回升，经济复苏"
)

# 3. 创建投资信号
if eligibility["is_eligible"]:
    signal = client.signal.create(
        asset_code="000001.SH",
        logic_desc="PMI 回升，经济复苏",
        invalidation_logic="PMI 跌破 50",
        invalidation_threshold=49.5
    )
    print(f"信号已创建: {signal.id}")

# 4. 运行回测
result = client.backtest.run(
    strategy_name="momentum",
    start_date=date(2023, 1, 1),
    end_date=date(2024, 12, 31),
    initial_capital=1000000.0
)
print(f"年化收益: {result.annual_return:.2%}")
```

---

## MCP 配置

### Claude Code 配置

在 Claude Code 配置文件中添加 MCP 服务器：

```json
// ~/.config/claude-code/mcp_servers.json
{
  "mcpServers": {
    "agomsaaf": {
      "command": "python",
      "args": ["-m", "agomsaaf_mcp.server"],
      "cwd": "D:/githv/agomSAAF/sdk",
      "env": {
        "AGOMSAAF_BASE_URL": "http://localhost:8000",
        "AGOMSAAF_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

### MCP 工具列表

#### Regime（宏观象限）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `get_current_regime` | 获取当前宏观象限 | `client.regime.get_current()` |
| `calculate_regime` | 计算 Regime 判定 | `client.regime.calculate()` |
| `get_regime_history` | 获取 Regime 历史 | `client.regime.history()` |
| `get_regime_distribution` | 获取 Regime 分布统计 | `client.regime.get_regime_distribution()` |
| `explain_regime` | 解释象限含义 | - |
| `get_recommended_assets` | 获取推荐资产 | - |

#### Signal（投资信号）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_signals` | 获取信号列表 | `client.signal.list()` |
| `get_signal` | 获取信号详情 | `client.signal.get()` |
| `check_signal_eligibility` | 检查信号准入 | `client.signal.check_eligibility()` |
| `create_signal` | 创建投资信号 | `client.signal.create()` |
| `approve_signal` | 审批信号 | `client.signal.approve()` |
| `reject_signal` | 拒绝信号 | `client.signal.reject()` |
| `invalidate_signal` | 使信号失效 | `client.signal.invalidate()` |

#### Macro（宏观数据）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_macro_indicators` | 获取宏观指标列表 | `client.macro.list_indicators()` |
| `get_macro_indicator` | 获取指标详情 | `client.macro.get_indicator()` |
| `get_macro_data` | 获取指标数据 | `client.macro.get_indicator_data()` |
| `get_latest_macro_data` | 获取最新数据 | `client.macro.get_latest_data()` |
| `sync_macro_indicator` | 同步指标 | `client.macro.sync_indicator()` |
| `explain_macro_indicator` | 解释指标含义 | - |

#### Policy（政策事件）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `get_policy_status` | 获取政策状态 | `client.policy.get_status()` |
| `get_policy_events` | 获取政策事件 | `client.policy.get_events()` |
| `create_policy_event` | 创建政策事件 | `client.policy.create_event()` |

#### Backtest（回测）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `run_backtest` | 运行回测 | `client.backtest.run()` |
| `get_backtest_result` | 获取回测结果 | `client.backtest.get_result()` |
| `list_backtests` | 获取回测列表 | `client.backtest.list_backtests()` |
| `get_backtest_equity_curve` | 获取净值曲线 | `client.backtest.get_equity_curve()` |

#### Account（账户管理）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_portfolios` | 获取投资组合 | `client.account.get_portfolios()` |
| `get_portfolio` | 获取组合详情 | `client.account.get_portfolio()` |
| `get_positions` | 获取持仓 | `client.account.get_positions()` |
| `create_position` | 创建持仓 | `client.account.create_position()` |

#### Simulated Trading（模拟交易）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_simulated_accounts` | 获取模拟账户 | `client.simulated_trading.list_accounts()` |
| `create_simulated_account` | 创建模拟账户 | `client.simulated_trading.create_account()` |
| `execute_simulated_trade` | 执行模拟交易 | `client.simulated_trading.execute_trade()` |
| `get_simulated_positions` | 获取模拟持仓 | `client.simulated_trading.get_positions()` |
| `get_simulated_performance` | 获取模拟绩效 | `client.simulated_trading.get_performance()` |
| `reset_simulated_account` | 重置模拟账户 | `client.simulated_trading.reset_account()` |

#### Equity（个股分析）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `get_stock_score` | 获取股票评分 | `client.equity.get_stock_score()` |
| `list_stocks` | 获取股票列表 | `client.equity.list_stocks()` |
| `get_stock_detail` | 获取股票详情 | `client.equity.get_stock_detail()` |
| `get_stock_recommendations` | 获取股票推荐 | `client.equity.get_recommendations()` |
| `analyze_stock` | 分析股票 | `client.equity.analyze_stock()` |
| `get_stock_financials` | 获取财务数据 | `client.equity.get_financials()` |
| `get_stock_valuation` | 获取估值数据 | `client.equity.get_valuation()` |

#### Fund（基金分析）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `get_fund_score` | 获取基金评分 | `client.fund.get_fund_score()` |
| `list_funds` | 获取基金列表 | `client.fund.list_funds()` |
| `get_fund_detail` | 获取基金详情 | `client.fund.get_fund_detail()` |
| `get_fund_recommendations` | 获取基金推荐 | `client.fund.get_recommendations()` |
| `analyze_fund` | 分析基金 | `client.fund.analyze_fund()` |
| `get_fund_performance` | 获取基金业绩 | `client.fund.get_performance()` |
| `get_fund_holdings` | 获取基金持仓 | `client.fund.get_holdings()` |

#### Sector（板块分析）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_sectors` | 获取板块列表 | `client.sector.list_sectors()` |
| `get_sector_score` | 获取板块评分 | `client.sector.get_sector_score()` |
| `get_sector_recommendations` | 获取板块推荐 | `client.sector.get_recommendations()` |
| `analyze_sector` | 分析板块 | `client.sector.analyze_sector()` |
| `get_sector_stocks` | 获取板块股票 | `client.sector.get_sector_stocks()` |
| `get_hot_sectors` | 获取热门板块 | `client.sector.get_hot_sectors()` |
| `compare_sectors` | 比较板块 | `client.sector.compare_sectors()` |

#### Strategy（策略管理）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `list_strategies` | 获取策略列表 | `client.strategy.list_strategies()` |
| `get_strategy` | 获取策略详情 | `client.strategy.get_strategy()` |
| `create_strategy` | 创建策略 | `client.strategy.create_strategy()` |
| `execute_strategy` | 执行策略 | `client.strategy.execute_strategy()` |
| `get_strategy_performance` | 获取策略绩效 | `client.strategy.get_performance()` |
| `get_strategy_signals` | 获取策略信号 | `client.strategy.get_strategy_signals()` |
| `get_strategy_positions` | 获取策略持仓 | `client.strategy.get_strategy_positions()` |

#### Realtime（实时价格）
| 工具名 | 功能 | 对应 SDK 方法 |
|--------|------|--------------|
| `get_realtime_price` | 获取实时价格 | `client.realtime.get_price()` |
| `get_multiple_realtime_prices` | 批量获取价格 | `client.realtime.get_multiple_prices()` |
| `get_price_history` | 获取价格历史 | `client.realtime.get_price_history()` |
| `get_market_summary` | 获取市场概况 | `client.realtime.get_market_summary()` |
| `get_sector_realtime_performance` | 获取板块表现 | `client.realtime.get_sector_performance()` |
| `get_top_movers` | 获取涨跌幅榜 | `client.realtime.get_top_movers()` |
| `list_price_alerts` | 获取价格预警 | `client.realtime.list_alerts()` |
| `create_price_alert` | 创建价格预警 | `client.realtime.create_alert()` |
| `delete_price_alert` | 删除价格预警 | `client.realtime.delete_alert()` |

---

## 安装和使用

### 安装 SDK

```bash
cd D:/githv/agomSAAF/sdk
pip install -e .
```

### 运行 MCP 服务器

```bash
cd D:/githv/agomSAAF/sdk
python -m agomsaaf_mcp.server
```

### 运行测试

```bash
cd D:/githv/agomSAAF/sdk
pytest tests/ -v
```

---

## 注意事项

1. **不修改 AgomSAAF 代码**：SDK 是独立项目，只通过 HTTP API 调用
2. **版本同步**：AgomSAAF API 变更时，需要同步更新 SDK
3. **错误处理**：所有 API 调用都应有明确的异常处理
4. **类型安全**：使用 Python 类型注解，方便 AI agent 理解
5. **文档友好**：docstring 必须清晰，便于 AI 理解每个方法的用途

---

## 后续扩展

1. CLI 工具：`agomsaaf regime get-current`
2. 更多模块：simulated_trading, equity, fund, sector, strategy, realtime
3. OpenAPI 代码生成工具
4. 版本同步验证工具

