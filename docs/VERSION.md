# AgomTradePro 版本号管理规范

> **当前版本**: `0.7.0`
> **Build 日期**: `2026-03-23`
> **完整版本号**: `0.7.0-build.20260323`

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
```

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
  "modules": 34
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
**最后更新**: 2026-03-23
