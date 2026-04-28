# AgomTradePro 版本号管理规范

> **当前版本**: `0.7.0`
> **Build 日期**: `2026-03-23`
> **完整版本号**: `0.7.0-build.20260323`
> **开发文档快照**: `2026-04-28`

---

## 版本号格式

采用**语义化版本**（Semantic Versioning）+ **Build 日期**组合：

```
主版本号.次版本号.修订号-build.日期

示例：0.7.0-build.20260323
```

### 版本号组成

| 组成部分 | 说明 | 变更时机 |
|---------|------|---------|
| **主版本号** | 架构级变更 | 不兼容的 API 变更、重大架构重构 |
| **次版本号** | 功能级变更 | 新增功能模块、重要功能改进 |
| **修订号** | 修复级变更 | Bug 修复、小优化 |
| **Build 日期** | 构建日期 | 每次发布时更新，格式 `YYYYMMDD` |

---

## 当前版本信息

```
版本: 0.7.0
代号: AgomTradePro
状态: 开发中
Build: 2026-03-23
文档快照: 2026-04-28
```

> 当前公开版本号仍为 `0.7.0`。2026-03-23 之后的功能收口、界面整合与架构修复仍记入 `Unreleased` / 开发快照，尚未单独切出新发布版本号。

## 0.7.0 之后的开发快照（截至 2026-04-28）

- Alpha / Qlib 运维台 V1 已落地：新增 staff 可读、superuser 可执行的推理管理与基础数据管理页面，方便统一查看激活模型、缓存、任务、告警与本地 Qlib 数据状态
- 这轮运维台与 Nightly 修复没有变更 MCP 外部契约：SDK/MCP 的 tool 名称、参数 schema、canonical API 路径与 RBAC 语义保持不变
- `tests/integration/test_alpha_stress.py` 已切到默认离线 ETF fallback mock，避免 GitHub Actions 上偶发落到 `akshare` 远端请求；最新 push CI 与 Nightly 已重新全绿
- Dashboard / SDK / MCP 的 Alpha 候选读取链已统一支持 `pool_mode` 和共享 `contract` 元数据，明确区分研究排序、异步刷新与真实可行动推荐
- Alpha 账户驱动股票池补齐价格覆盖同步与资产主数据回填，账户池稳定性、可解释性和跨入口一致性进一步提升
- Pulse 重算前会先刷新上游宏观输入；当当前 Regime 只能解析到 `Unknown` 时，系统会保留最近有效的 Pulse 快照而不是覆盖成未知状态
- Alpha cache 读取已回收至 repository 边界，Architecture Layer Guard 与整条 Nightly 主回归重新恢复绿色
- Domain / Application 层一批静默 `except Exception:` 已改成显式日志分支，架构治理时可以保留降级行为，同时不再无痕吞错
- Strategy 外部 provider 已移除对 macro / asset_analysis / signal / equity / fund ORM model 的跨 App 直连，统一改走 Application Service / Repository Provider / Facade 边界
- Asset name resolution 桥接已回收到 equity / fund / rotation / asset_analysis 各自应用层公开入口，`asset_analysis` 与 `core/integration` 不再跨过去直接访问这些模块的 ORM
- Asset pool screening 桥接已改为调用 equity / fund 各自 application facade，`core/integration` 不再自行组装 scorer + repository
- asset_analysis 跨 App 市场协作已升级为 shared technical registry；equity / fund / rotation 在启动时注册 repository / screener / name-resolver，旧 `core/integration/asset_analysis_market_sources.py` 已移除且未引入新循环依赖
- `tests/unit` 缺失的测试包入口已补齐，Nightly 全量 pytest 收集不再因重复测试文件名触发 `import file mismatch`
- 多个 Application provider 入口已改回按调用时解析 concrete implementation，并补回 Alpha / StopLoss 旧测试契约兼容层，Nightly 可继续暴露真实单测失败而不是被 patch 断点卡住
- Nightly integration 步骤已从 `pytest-xdist` 并行改为串行执行，并补充 `faulthandler` / per-test timeout，优先保证 GitHub hosted runner 上的稳定性与可诊断性
- Strategy 执行在 investable asset pool 尚未预热时会回退读取 asset_analysis 最新评分缓存；Decision Workspace AI 证伪草稿接口已切到新的 `generate_chat_completion` 参数签名
- 统一账户 API、SDK 与 MCP 契约进一步收口，统一到账户绩效、估值与 canonical 路径
- Equity Detail 补齐技术图表、分时数据 fallback 与更完整的市场上下文展示
- Equity Detail 在本地股票主数据或估值缓存缺失时，支持基础信息回退与部分加载，避免详情页整体阻塞
- Equity Detail 日线/Regime 相关性在本地缓存缺失时接入 Tushare Gateway 历史行情回退，降低单一 AKShare/EastMoney 失败影响
- Equity Detail 历史行情回退新增 read-through cache，远端成功返回后会幂等写回本地 `equity_stock_daily`
- 系统设置中心、管理员界面、MCP Tools、服务日志与文档管理页统一到共享管理界面
- 财经数据源配置页收口为统一数据源中心，支持 Provider Inventory 与运行时连接测试
- RSS 管理页支持 RSSHub / timeout / retry / proxy 等更完整的源配置
- GitHub Actions 架构与逻辑门禁已跟上这轮界面和数据源收口后的最新代码边界

---

## 版本演进历史

### 0.7.0 (2026-03-23)

**新增模块**:
- `setup_wizard` - 系统初始化向导（首次安装引导）
- `ai_capability` - AI 能力目录与统一路由
- `terminal` - 终端 CLI（AI 交互界面）
- `agent_runtime` - Agent 运行时
- `pulse` - Pulse 脉搏层（战术指标聚合与转折预警）

**功能改进**:
- 网页版安装向导，引导配置管理员密码、AI API、数据源
- 密码强度实时检查
- 已初始化系统需密码验证才能修改配置

**模块数量**: 35 个业务模块

---

### 0.6.0 (2026-03-19)

**新增模块**:
- `ai_capability` - 系统级 AI 能力目录与统一路由

**功能改进**:
- 支持四种能力来源：builtin/terminal_command/mcp_tool/api
- 统一路由 API
- 自动采集全站 API 并进行安全分层

---

### 0.5.0 (2026-03-17)

**新增模块**:
- `terminal` - 终端 CLI（终端风格 AI 交互界面）
- `agent_runtime` - Agent 运行时（Terminal AI 后端）

**功能改进**:
- 支持可配置命令系统（Prompt/API 两种执行类型）
- 任务编排和 Facade 模式

---

## 版本号使用场景

### 1. 文档中引用版本

```markdown
> **版本**: 0.7.0
> **Build**: 2026-03-23
```

### 2. API 响应中返回版本

```json
{
  "version": "0.7.0",
  "build": "20260323",
  "modules": 35
}
```

### 3. 代码中获取版本

```python
# core/version.py
__version__ = "0.7.0"
__build__ = "20260323"

def get_version():
    return __version__

def get_full_version():
    return f"{__version__}-build.{__build__}"
```

### 4. Git 标签

```bash
git tag -a v0.7.0 -m "Release 0.7.0: Setup Wizard + AI Capability"
git push origin v0.7.0
```

---

## 版本发布流程

### 1. 开发阶段
- 在 `develop` 分支开发
- 版本号保持 `-dev` 后缀，如 `0.8.0-dev`

### 2. 测试阶段
- 合并到 `release` 分支
- 版本号改为 `-rc.N`，如 `0.8.0-rc.1`

### 3. 发布阶段
- 合并到 `main` 分支
- 更新 Build 日期
- 创建 Git 标签 `v0.8.0`
- 更新本文档的版本历史

---

## 版本号变更规则

### 主版本号 (0 → 1)
- [ ] 生产环境首次正式部署
- [ ] API 发生不兼容变更
- [ ] 数据库架构重大调整
- [ ] 核心架构重构

### 次版本号 (7 → 8)
- [x] 新增业务模块
- [ ] 重大功能改进
- [ ] 性能大幅优化

### 修订号 (0 → 1)
- [ ] Bug 修复
- [ ] 小功能优化
- [ ] 文档更新

---

## 相关文件

| 文件 | 用途 |
|-----|------|
| `docs/VERSION.md` | 版本号管理规范（本文档）|
| `core/version.py` | 版本号常量定义 |
| `AGENTS.md` | AI Agent 指引（引用版本号）|
| `README.md` | 项目说明（引用版本号）|
| `docs/INDEX.md` | 文档索引（引用版本号）|

---

## 版本号同步检查清单

发布新版本时，需更新以下文件：

- [ ] `core/version.py` - 版本号常量
- [ ] `AGENTS.md` - 项目概述中的版本号
- [ ] `README.md` - 项目说明中的版本号
- [ ] `docs/INDEX.md` - 文档索引中的版本号
- [ ] `docs/VERSION.md` - 版本历史记录
- [ ] `docs/governance/SYSTEM_BASELINE.md` - 系统基线中的版本号
- [ ] `docs/SYSTEM_SPECIFICATION.md` - 系统规格书中的版本号

---

**维护者**: AgomTradePro Team  
**最后更新**: 2026-04-21
