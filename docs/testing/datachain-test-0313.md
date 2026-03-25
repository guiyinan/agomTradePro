# AgomTradePro 数据链路专项测试复核与修复说明

复核日期: 2026-03-13
原测试日期: 2026-03-12 至 2026-03-13
复核环境: 本地开发环境 `127.0.0.1:8000`

## 结论

原外包测试报告里混合了三类问题:

1. 真实代码问题
2. 冷启动/初始化缺失
3. 测试口径问题或非系统缺陷

本次已完成以下修复:

- 修正 SDK `regime` / `realtime` 模块的 API 前缀到现行 `/api/...`
- 新增后端 `GET /api/realtime/market-summary/` 兼容接口
- 新增冷启动命令 `python manage.py bootstrap_cold_start`
- 新增 Alpha 冷启动命令 `python manage.py bootstrap_alpha_cold_start`
- 将冷启动 bootstrap 融入 Docker 生产入口和 VPS 部署脚本
- 初始化并验证 Regime 阈值默认配置

## 已修复

### 1. SDK/MCP 路由与 Django 现行路由脱节

状态: 已修复

修复内容:

- `sdk/agomtradepro/modules/regime.py`
  - 旧: `/regime/api`
  - 新: `/api/regime`
- `sdk/agomtradepro/modules/realtime.py`
  - 旧: `realtime/api`
  - 新: `/api/realtime`

说明:

这不是测试误报。SDK 代码中的旧前缀与当前 Django 挂载路径不一致，确实会导致 MCP/SDK 调用失败。

### 2. `GET /api/realtime/market-summary/` 缺失

状态: 已修复

修复内容:

- 新增 `apps/realtime/interface/views.py` 中的 `MarketSummaryView`
- 新增 `apps/realtime/interface/urls.py` 中的 `market-summary/` 路由

当前行为:

- 返回上证/深证/创业板主要指数快照
- `up_count/down_count/flat_count` 等广度统计暂返回 `0`
- 显式返回 `stats_available=false`

说明:

这属于兼容修复。SDK/MCP 已公开暴露 `get_market_summary()`，后端必须给出稳定 endpoint。

### 3. Regime 阈值配置空表

状态: 已修复

修复内容:

- 执行 `python manage.py init_regime_thresholds`
- 当前已验证:
  - `regime_threshold_configs = 1`
  - `active = 1`

说明:

这是冷启动初始化缺失，不是 Regime 计算逻辑本身损坏。

### 4. 冷启动初始化链路缺失

状态: 已修复

新增命令:

```bash
python manage.py bootstrap_cold_start --with-alpha
```

命令职责:

- 初始化账户分类、基础规则、系统文档
- 初始化 Regime 阈值
- 初始化 Audit 阈值与置信度配置
- 初始化 Equity 权重与配置
- 初始化 Prompt 模板与 Chain
- 初始化 Rotation / Hedge / Factor 默认配置
- 初始化 Decision Model Params
- 对已有数据采用跳过策略，支持幂等重复执行

验证结果:

- `currencies = 6`
- `asset_categories = 22`
- `docs = 3`
- `rules = 27`
- `regime_thresholds = 1`
- `audit_indicator_thresholds = 48`
- `audit_confidence = 1`
- `scoring_weights = 3`
- `equity_rules = 4`
- `sector_prefs = 13`
- `fund_prefs = 7`
- `prompt_templates = 15`
- `prompt_chains = 3`
- `rotation_assets = 18`
- `rotation_configs = 5`
- `rotation_templates = 3`
- `hedge_pairs = 10`
- `factor_defs = 27`
- `factor_configs = 6`
- `decision_params_dev = 13`

## 已融入 Docker / 部署流程

### Docker 生产入口

文件:

- `docker/entrypoint.prod.sh`

行为:

- `migrate` 后，如果 `AGOMTRADEPRO_BOOTSTRAP_ON_START=1`，自动执行:

```bash
python manage.py bootstrap_cold_start --with-alpha
```

### VPS 部署脚本

已集成到:

- `scripts/deploy-on-vps.sh`
- `scripts/deploy-on-vps.ps1`
- `scripts/remote_build_deploy_vps.py`

行为:

- 部署完成数据库迁移后，显式执行 `bootstrap_cold_start`
- 再继续配置宏观定时任务

### 部署环境示例

文件:

- `deploy/.env.vps.example`

新增变量:

```env
AGOMTRADEPRO_BOOTSTRAP_ON_START=1
AGOMTRADEPRO_BOOTSTRAP_ALPHA_ON_START=1
AGOMTRADEPRO_BOOTSTRAP_ALPHA_UNIVERSES=csi300
AGOMTRADEPRO_BOOTSTRAP_ALPHA_TOP_N=30
```

## 冷启动问题，已明确但未自动解决

### 1. Alpha 高级 Provider 不可用

状态: 未修复

当前原因:

- `AlphaScoreCacheModel` 无缓存
- `QlibModelRegistryModel` 无激活模型

这不是单纯冷启动配置能解决的问题，仍需要:

- Alpha 冷启动命令已补齐，但默认只会生成“真实 Qlib 缓存”，不会伪造 simple/cache 数据
- 准备 Qlib 数据
- 训练或导入模型
- 再执行 `python manage.py bootstrap_alpha_cold_start --universes csi300`

### 2. 股票基础数据/日线数据空表

状态: 未修复

涉及:

- `equity_stock_info`
- `equity_stock_daily`

说明:

这是业务数据同步问题，不应在容器首启时强制联网执行。建议单独通过同步任务或运维脚本完成。

### 3. 估值 PE 缺失

状态: 未修复

说明:

这属于数据源质量和 fallback 策略问题，需要单独排查 AKShare 返回结构，并评估是否增加备用源。

## 外包报告中的非缺陷项

### 1. POST API 的 CSRF 报错

结论: 不应直接按“关闭 CSRF”处理

说明:

- 当前系统默认同时支持 Session 和 Token 认证
- 如果测试时带着浏览器 Session 去调 POST API，会优先走 Session 分支并触发 CSRF 校验
- 对纯 Token API 调用，不应简单粗暴禁用 CSRF 中间件

建议测试口径:

- 纯 API 测试使用 Token，不附带浏览器 Session/Cookie
- 如需浏览器内调试，显式携带 CSRF Token

### 2. curl 中文乱码

结论: Windows 终端编码问题，不是后端缺陷

## 目前建议

第一优先级:

- 补股票基础数据与日线同步任务

第二优先级:

- 针对估值 PE 缺失增加备用数据源或质量标记策略

第三优先级:

- 让外包测试脚本改为使用现行 `/api/...` 路径
- 统一 Token-only API 测试口径

## 复核命令

```bash
python manage.py check
python manage.py bootstrap_cold_start
python manage.py init_regime_thresholds
```

已验证:

- `python manage.py check` 通过
- `python manage.py bootstrap_cold_start` 可幂等重复执行
- `/api/regime/current/` 可解析
- `/api/realtime/market-summary/` 可解析并返回 200
- `/api/alpha/health/` 可解析
