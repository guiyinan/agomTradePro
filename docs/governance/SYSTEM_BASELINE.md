# AgomTradePro 系统基线

> **版本**: 0.7.0
> **基线日期**: 2026-03-28
> **文档性质**: 单一叙事来源（Single Source of Truth）
> **更新频率**: 每次发布后更新
> **版本管理**: [VERSION.md](../VERSION.md)

---

## 1. 系统身份

**名称**: AgomTradePro (Agom Strategic Asset Allocation Framework)

**定位**: 个人投研平台

**核心理念**: 通过 **Regime（增长/通胀象限）** 和 **Policy（政策档位）** 双重过滤，确保投资者 **"不在错误的宏观环境中下注"**

---

## 2. 当前版本

| 指标 | 数值 | 来源 |
|------|------|------|
| **系统版本** | 0.7.0 | `core/version.py` |
| **发布状态** | 生产就绪 | `docs/development/system-review-report.md` |
| **最后更新** | 2026-04-21 | Git log |
| **业务模块** | 35个 | `apps/` 目录扫描 |
| **MCP 工具** | 326个 | `sdk/agomtradepro_mcp.server` 本地注册 |
| **测试规模** | 5,212项 | `pytest --collect-only -q` |
| **代码行数** | 50,000+ | 代码统计 |
| **API 路径** | 515个 | `docs/testing/api/openapi.json` |
| **数据库表** | 80+ | Migration 文件 |

---

## 3. 模块清单

### 3.1 按层级分类

**基础设施层 (4个)**: `regime`, `ai_provider`, `events`, `macro`（宏观采集编排/兼容层）

**核心业务层 (14个)**: `signal`, `policy`, `sentiment`, `filter`, `alpha_trigger`, `beta_gate`, `alpha`, `factor`, `hedge`, `rotation`, `sector`, `agent_runtime`, `task_monitor`, `ai_capability`

**资产分析层 (3个)**: `asset_analysis`, `equity`, `fund`

**应用集成层 (10个)**: `backtest`, `audit`, `dashboard`, `prompt`, `realtime`, `data_center`, `terminal`, `strategy`, `decision_rhythm`, `share`

**战术指标层 (1个)**: `pulse`

**顶层聚合层 (3个)**: `simulated_trading`, `account`, `setup_wizard`

### 3.2 完整清单（按字母序）

```
account, ai_capability, ai_provider, agent_runtime, alpha, alpha_trigger,
asset_analysis, audit, backtest, beta_gate, dashboard,
decision_rhythm, equity, events, factor, filter,
fund, hedge, macro, data_center, policy,
prompt, pulse, realtime, regime, rotation, sector,
sentiment, setup_wizard, share, signal, simulated_trading, strategy,
task_monitor, terminal
```

---

## 4. 部署口径

### 4.1 部署模式

| 模式 | 说明 | 文档 |
|------|------|------|
| **Docker Compose** | 本地开发 + 生产部署 | `docs/deployment/DOCKER_DEPLOYMENT.md` |
| **VPS Bundle** | 打包上传到 Linux VPS | `docs/deployment/VPS_BUNDLE_DEPLOYMENT.md` |
| **三机架构** | VPS FRP + 本地运行 + AI Agent | `docs/architecture/frp-vps-local-runtime-architecture.md` |

### 4.2 部署流程

```
本地打包 → 上传 Bundle → VPS 部署 → 健康检查
    ↓            ↓            ↓           ↓
package-for-vps.ps1  scp    deploy-on-vps.sh  /api/health/
```

### 4.3 数据库

- **开发环境**: SQLite (`db.sqlite3`)
- **生产环境**: SQLite (Docker Volume) / PostgreSQL (可选)

### 4.4 缓存

- **开发环境**: 内存缓存 (`LocMemCache`)
- **生产环境**: Redis

---

## 5. 测试口径

### 5.1 测试分层

| 层级 | 内容 | 文件数 | 覆盖率 |
|------|------|--------|--------|
| **L0 静态质量** | ruff/black/mypy | - | 100% |
| **L1 单元层** | Domain 规则/算法 | ~100 | 90%+ |
| **L2 组件层** | use_case + repository | ~50 | 85%+ |
| **L3 集成层** | 模块间流程 | ~30 | 80%+ |
| **L4 API 合同** | OpenAPI/鉴权/契约 | ~20 | 100% |
| **L5 E2E 层** | 浏览器关键路径 | ~10 | 关键路径 |
| **L6 UAT 层** | 用户旅程验收 | ~5 | A-E旅程 |
| **L7 生产守护** | 冒烟/监控/回滚 | - | 100% |

### 5.2 测试统计

| 指标 | 数值 | 来源 |
|------|------|------|
| **测试文件数** | 238 | `find tests/ -name "test_*.py" | wc -l` |
| **测试用例数** | 1,500+ | pytest 执行统计 |
| **Domain 层覆盖率** | ≥ 90% | coverage 报告 |
| **模块覆盖率** | 100% (35/35) | 扫描结果 |

### 5.3 质量门禁

- **PR Gate**: 10-15 分钟，Guardrail 回归 + 变更影响测试
- **Nightly Gate**: 30-60 分钟，全量单元/集成测试
- **RC Gate**: 发布前，关键旅程 ≥ 90%, P0 缺陷 = 0
- **Post-Deploy Gate**: 上线后 30 分钟，健康检查 + 核心流程

---

## 6. 核心链路

### 6.1 主业务链路

```
宏观采集/同步 → Data Center 宏观事实 → Regime 判定 → Policy 档位 → Alpha 选股 → 信号生成 → 模拟盘交易 → 事后审计
      ↓                 ↓                 ↓             ↓            ↓            ↓            ↓            ↓
   macro            data_center       regime        policy       alpha       signal   simulated_trading  audit
```

### 6.2 关键约束链路

```
Regime 象限 → Policy 闸门 → Beta 闸门 → 决策频率 → 执行审批
    ↓            ↓            ↓            ↓            ↓
  regime      policy     beta_gate   decision_rhythm  account
```

### 6.3 数据流链路

```
外部数据源 → Market Data 统一接口 → 各模块消费 → 数据库存储 → 审计日志
     ↓               ↓                  ↓             ↓            ↓
Tushare/AKShare  data_center      regime/policy   SQLite      audit
东方财富/Redis
```

### 6.4 宏观数据治理真源

- 指标目录真源：`IndicatorCatalog`
- 量纲/单位规则真源：`IndicatorUnitRule`
- 宏观事实真源：`data_center_macro_fact`
- 对外宏观 HTTP 入口：`/api/data-center/indicators/*`、`/api/data-center/macro/series/`、`/api/data-center/sync/macro/`
- 对外宏观 MCP 入口：`data_center_list_indicators`、`data_center_get_macro_series`、`data_center_sync_macro`

---

## 7. 技术栈

| 类别 | 技术选型 | 版本 |
|------|----------|------|
| **语言** | Python | 3.11+ |
| **Web框架** | Django | 5.x |
| **API框架** | Django REST Framework | 3.x |
| **异步任务** | Celery + Redis | - |
| **数据处理** | Pandas + NumPy | - |
| **AI 集成** | Qlib | - |
| **测试框架** | Pytest | - |
| **代码质量** | ruff + black + mypy | - |
| **容器化** | Docker + Docker Compose | - |

---

## 8. 文档索引

### 8.1 核心文档

| 文档 | 用途 | 位置 |
|------|------|------|
| **系统说明书** | 完整技术+功能说明 | `docs/SYSTEM_SPECIFICATION.md` |
| **快速启动** | 新用户上手 | `docs/QUICK_START.md` |
| **模块账本** | 边界规则/依赖统计 | `docs/development/module-ledger.md` |
| **模块依赖** | 依赖拓扑图 | `docs/architecture/MODULE_DEPENDENCIES.md` |

### 8.2 治理文档

| 文档 | 用途 | 位置 |
|------|------|------|
| **系统基线** | 单一叙事来源 | `docs/governance/SYSTEM_BASELINE.md` (本文档) |
| **模块分级** | 核心/成熟/试验 | `docs/governance/MODULE_CLASSIFICATION.md` |
| **开发禁令** | 禁止事项清单 | `docs/governance/DEVELOPMENT_BANLIST.md` |

---

## 9. 变更记录

| 日期 | 版本 | 变更内容 |
|------|------|----------|
| 2026-03-28 | V1.2 | 更新模块数量(34→35)，新增 pulse、setup_wizard 模块，新增战术指标层 |
| 2026-03-22 | V1.1 | 更新模块数量(32→33)，新增 ai_capability 模块 |
| 2026-03-18 | V1.0 | 初始版本，建立系统基线 |

---

**维护者**: AgomTradePro Team
**最后更新**: 2026-03-28
**下次更新**: 下次发布后
