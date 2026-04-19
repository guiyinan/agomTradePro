# AgomTradePro 开发日记 | 从零到 50,000+ 行代码的血泪史

> 本文档为虚构的开发日志，基于实际 git 提交记录改编，以小红书风格连载直播开发进度。
> 日记中的"日期"为虚拟时间线，不完全对应实际自然日。

---

## Day 1 | 我决定自己造一个投资决策系统

### 为什么开始？

事情是这样的。

作为一个在金融市场摸爬滚打多年的"老韭菜"，我发现一个痛点：

**每次投资决策，都像在迷雾中开车。**

宏观环境怎么样？政策有没有风险？这只股票到底值不值得买？

信息太分散，决策太随意。

于是，一个疯狂的想法诞生了：

**我要自己造一个系统，帮我做投资决策。**

### 目标很简单

1. 告诉我当前处于什么经济周期（复苏/过热/滞胀/衰退）
2. 提醒我政策有没有重大风险
3. 帮我筛选值得投资的标的
4. 全程留痕，方便复盘

听起来不难？我当时也是这么想的……

**spoiler：我错了，大错特错。**

---

## Day 2 | MVP 来了，能跑了就行

### 技术选型

作为一个 Python 爱好者，毫不犹豫选择了 Django。

第一行代码敲下的那一刻，心情：

> "这把稳了！"

### MVP 功能

- 用户登录
- 简单的数据展示页面
- 维基百科风格的配色（对，就是那个蓝白配色）

当时还觉得自己审美在线，现在回头看……

**代码丑，界面更丑。**

但至少，能跑了！

---

## Day 3 | 引入 AI，噩梦开始

### 为什么用 AI？

我想让系统自动分析政策新闻、判断市场情绪。

于是接入了 AI 模型。

**这是我犯的第一个大错。**

### AI 生成的问题

AI 帮我生成了第一版代码，看起来很完美：

```python
# AI 生成的代码
def classify_policy(text):
    return ai_model.predict(text)
```

简洁、优雅、看起来没问题。

**但是……**

- 没有错误处理
- 没有降级方案
- 没有数据验证
- 硬编码的阈值（0.75、0.3 都是哪来的？）

这些坑，我后来填了一个月。

---

## Day 4-7 | Policy 模块与 RSS 订阅

### Policy 模块

投资最怕什么？**黑天鹅。**

政策突然变化，市场剧烈波动，手里的票直接腰斩……

所以我决定做一个 Policy 模块：

- 监控政策事件
- 设置风险档位（P0 正常 → P3 危机）
- 自动约束交易行为

### RSS 订阅集成

为了自动获取政策新闻，接入了 RSS 订阅。

本以为很简单，结果遇到了：

- RSS 源不稳定，三天两头挂
- 编码问题，中文全是乱码
- 解析格式不统一，有的用 CDATA，有的直接裸文本

**折腾了两天才搞定。**

---

## Day 8-10 | 资产分析框架搭建

### Equity 模块（个股分析）

既然要投资，总得知道股票值多少钱吧。

估值方法一个都不能少：

- DCF 现金流折现
- PE Band 市盈率区间
- PB Band 市净率区间
- PEG 成长性评估

**理论上完美，实际上……数据质量一言难尽。**

### Fund 模块（基金分析）

股票太难选？那就选基金。

### Backtest 模块（回测引擎）

没有回测的策略都是耍流氓。

---

## Day 11-15 | Docker 化与部署

### 容器化改造

本地跑得好好的，部署就翻车。

于是开始 Docker 化：

- Dockerfile 编写
- docker-compose 配置
- PostgreSQL 容器

**踩坑无数：**

- 镜像太大（1.5GB+）
- 数据库连接配置
- 静态文件处理

### 第一次部署翻车

部署到 VPS 的第一天：

- 数据库连不上
- 静态文件 404
- CORS 报错
- 内存溢出

**那天晚上，我修到了凌晨 3 点。**

---

## Day 16-30 | 中期挣扎与架构债务

### 这段时间干了啥？

老实说，有点混乱。

- 补充各种边界条件
- 修复莫名其妙出现的 bug
- 文档整理

### 架构债务

早期追求速度，代码质量堪忧。

技术债务开始显现：

- 循环依赖（A import B，B import A，死循环）
- 硬编码配置（到处都是魔法数字）
- 测试覆盖不足（甚至有的模块完全没有测试）

**是时候重构了。**

---

## Day 31 | Regime 模块大改造

### 四象限模型

宏观经济周期，我采用了经典的四象限模型：

```
         通胀动量 ↑
              │
    ┌─────────┼─────────┐
    │  过热   │  滞胀   │
    │ (G↑ I↑) │ (G↓ I↑) │
    │         │         │
增长├─────────┼─────────┤通胀
动量│  复苏   │  衰退   │动量
    │ (G↑ I↓) │ (G↓ I↓) │
    │         │         │
    └─────────┼─────────┘
              │
         增长动量 ↓
```

### HP 滤波的后视偏差问题

这是我在回测中发现的一个大坑。

**AI 生成的代码：**

```python
# AI 生成的代码 - 有严重问题！
trend, cycle = hpfilter(full_series, lamb=129600)
```

看起来没问题对吧？

**问题在于：这是用全量数据做的滤波！**

在真实环境中，你只能用截至当前时刻的数据，不能"穿越到未来"。

**正确做法：**

```python
# 扩张窗口滤波 - 避免后视偏差
def get_trend_at(series, t):
    truncated = series[:t+1]  # 只用到时刻 t 的数据
    trend, _ = hpfilter(truncated, lamb=129600)
    return trend[-1]
```

这个坑，AI 完全不知道。**因为它不懂金融。**

---

## Day 32-35 | Realtime 实时监控

### 价格监控

实时价格获取，用于：

- 持仓盯盘
- 止损提醒
- 异常波动告警

数据源选择了 AKShare：

- 免费可用
- 接口丰富
- **但稳定性一般……**

### 数据源降级

AKShare 挂了怎么办？

我设计了一个多级降级方案：

```
AKShare → 东方财富 → 新浪财经 → 缓存数据 → 报错
```

**这个设计救了我很多次。**

---

## Day 36-40 | MCP 集成与 SDK 开发

### 什么是 MCP？

Model Context Protocol，让 AI 助手能够直接调用系统功能。

**简单说：我可以用 AI 帮我操作系统了。**

### 第一版 MCP 的灾难

AI 帮我生成了 MCP 工具代码，看起来很完美：

```python
# AI 生成的 MCP 工具
@tool
def get_regime():
    return regime_repository.get_latest()
```

**问题是：**

1. 没有错误处理，API 挂了直接崩
2. 返回格式不统一，前端解析不了
3. 路由和后端 API 不一致
4. SDK 和 MCP 调用的路径不同

**这四端（后端、前端、SDK、MCP）对齐的问题，我修了整整两周。**

---

## Day 41-45 | SQLite 迁移与 VPS 部署

### 数据库选型

PostgreSQL 很好，但：

- 需要额外维护
- 资源占用高
- 个人项目没必要

**决定：迁移到 SQLite。**

### 迁移过程

- 数据导出
- Schema 转换
- 数据导入
- 功能验证

**最大的坑：并发写入限制。**

最终方案：读多写少的架构设计，写入操作排队执行。

---

## Day 46-55 | UI/UX 大改造

### 为什么要改？

原来的界面：

- 风格不统一
- 移动端适配差
- 交互体验一般

### 改造过程

找了设计师（其实就是我自己审美觉醒），改造内容：

- 全局样式统一
- 暗色模式支持
- 响应式布局
- 微交互动画

### CSS 陷阱

改完后，噩梦开始了。

**提交记录里的问题：**

```
fix(templates): resolve modal close bug caused by CSS specificity conflict
fix(ui): isolate page modals from global helpers
```

**CSS 选择器优先级地狱：**

- 全局样式和局部样式冲突
- 模态框关不掉
- 按钮样式乱飞

**修复方法：**

1. 使用 CSS Modules 隔离
2. 用 BEM 命名规范
3. 提高选择器优先级（最后手段）

---

## Day 56-60 | UAT 测试与 Bug 修复（外包噩梦）

### 外包团队交付

为了加快进度，找了外包团队帮忙。

**结果：交付质量一言难尽。**

### Week 1 缺陷清单

**P0（阻断性问题）：**

- Policy events 路由冲突，同一个 URL 被定义了两次

**P1（重要问题）：**

- Backtest 月度调仓 12 月边界计算错误
- Audit 使用错误的 Regime 名称（GROWTH → Recovery，应该是 Recovery）

### Week 2 缺陷清单

- Policy 删除功能返回 404
- Policy 查询列表为空时崩溃
- Regime 空表时报错

### 我的心态

```
我看代码，代码看我，相看两厌。
```

**最离谱的一个：**

外包写的代码里，Audit 模块直接用随机数生成绩效数据！

```python
# 外包的代码 - 我看到的时候差点晕过去
return random.uniform(0.1, 0.3)  # 假的收益率
```

**这就是为什么我后来写了一大堆 Guardrail 测试。**

---

## Day 61 | 24 个系统逻辑问题修复

### 问题来源

全面审查后发现，系统里有 **24 个逻辑问题**。

### 高优先级（4 个）

1. **Audit 模块用假数据**：随机数生成绩效数据 → 改用真实价格数据
2. **Policy 处理失败时数据丢失**：添加原始数据保存
3. **Sentiment 无法区分"无数据"和"中性"**：添加 data_sufficient 标志
4. **归因报告没说明方法**：添加方法论标签

### 中优先级（12 个）

1. AI 分类直接返回 policy_level
2. Signal 证伪只检查已批准的，漏掉待处理的
3. Regime 重试无限循环 → 限制 3 次
4. Qlib 推理失败没告警 → 添加 AlphaAlertModel
5. 回测结果没审计状态
6. Regime 准确率硬编码 → 动态计算
7. ……还有 6 个

### 低优先级 - 消除硬编码（8 个）

把所有魔法数字移到配置中心：

```python
# 之前 - 硬编码
if score > 0.75:  # 这是啥？

# 之后 - 配置化
if score > config.ai_threshold:  # 可配置的阈值
```

**这个提交改了 42 个文件，新增 3000+ 行，删除 150+ 行。**

**这就是给 AI 收拾烂摊子的代价。**

---

## Day 62-65 | API 路由统一（四端对齐）

### 问题由来

早期开发没有规划好 API 路由，导致：

- 后端路由：`/api/regime/current/`
- SDK 调用：`/api/regime/current`（没有尾部斜杠）
- MCP 工具：`/api/regime/current/`
- 前端调用：`/api/v1/regime/`

**四端不一致，乱成一锅粥。**

### 统一方案

定义了规范的路由格式：

```
/api/{module}/{resource}/
```

### 修复过程

**这个星期我做了这些事：**

```
Normalize audit API routes across backend SDK and frontend
Normalize canonical API roots for account regime macro filter backtest ai and prompt
Normalize strategy simulated trading realtime and system API roots
Fix frontend API routes after canonical migration
Align events and dashboard SDK routes
```

**每天醒来就是修路由，修到我怀疑人生。**

---

## Day 66-70 | MCP 工具对齐（继续收拾烂摊子）

### MCP 写工具失败

当我以为路由修好了，发现 MCP 的写操作还是失败。

**问题：**

1. 序列化格式不对
2. 错误处理缺失
3. 返回字段不一致

### 修复清单

```
Fix MCP write tool serialization and error handling
Fix additional MCP write tool alignment
Fix remaining MCP write tool failures
Fix long-tail MCP tool alignment and smoke regressions
```

**每一行提交记录背后，都是无数次的调试。**

### 最坑的一个

MCP 工具调用后端 API，但返回的 JSON 格式和 MCP 协议期望的不一致。

```python
# 后端返回
{"success": true, "data": {...}}

# MCP 期望
{"content": [{"type": "text", "text": "..."}]}
```

**中间要做一层转换，AI 生成的代码完全没考虑这个。**

---

## Day 71-75 | 架构治理与护栏测试

### 架构依赖泄露

审查代码发现，Domain 层直接 import 了 Django 和 Pandas：

```python
# domain/services.py - 这是错误的！
import pandas as pd  # Domain 层不应该依赖外部库
from django.db import models  # Domain 层不应该知道 Django
```

**这是违反 DDD 四层架构的。**

### 修复

```
refactor: close remaining architecture dependency leaks
Add architecture governance guardrails
```

### 护栏测试

为了防止以后再犯同样的错误，我写了架构护栏测试：

```python
# tests/guardrails/test_architecture_guardrails.py

def test_domain_layer_no_django_import():
    """Domain 层不应该 import Django"""
    domain_files = glob.glob("apps/*/domain/**/*.py")
    for f in domain_files:
        content = open(f).read()
        assert "from django" not in content
        assert "import django" not in content

def test_domain_layer_no_pandas_import():
    """Domain 层不应该 import Pandas"""
    domain_files = glob.glob("apps/*/domain/**/*.py")
    for f in domain_files:
        content = open(f).read()
        assert "import pandas" not in content
```

**这些测试现在每次 CI 都会跑，谁再犯就自动报错。**

---

## Day 76-78 | AI-native 架构升级

### 为什么要升级？

系统跑起来了，但总觉得缺点什么。

直到有一天，我发现：

> **这个系统，天生就是为 AI 准备的。**

### L4 级别 AI 原生架构

从 L0 到 L4，AI 融合程度逐渐加深：

| 级别 | 描述 | 示例 |
|------|------|------|
| L0 | 无 AI 能力 | 传统系统 |
| L1 | AI 辅助查询 | "当前 Regime 是什么？" |
| L2 | AI 辅助决策 | "建议调整仓位" |
| L3 | AI 自主执行（需确认） | "确认卖出 XXX？" |
| L4 | AI 全自主运营 | 自动监控、决策、执行 |

### 本次升级内容

**M1 里程碑**：上下文快照
- AI 可以获取系统完整状态
- 知道当前 Regime、Policy、持仓等

**M2 里程碑**：外观模式
- 为 AI 提供简化的调用接口
- 不需要了解内部复杂性

**M3 里程碑**：提案生命周期
- AI 可以发起操作提案
- 支持审批工作流

**M4 里程碑**：运营仪表盘
- AI 操作可视化
- 失败分类与处理
- 人工交接机制

### AI 还是会犯错

升级后，AI 的操作更频繁了。

**新增了失败分类器：**

- 数据缺失
- 权限不足
- 参数错误
- 系统繁忙

**当 AI 处理不了时，会自动创建人工交接工单。**

---

## 写在最后 | 给后来者的建议

### 这 78 天，我学到了什么？

#### 1. AI 是好帮手，但不是好司机

AI 可以帮你写代码，但：

- **它不懂业务**：HP 滤波的后视偏差，AI 完全不知道
- **它不会处理边界**：空数据、异常输入、并发问题
- **它会产生幻觉**：硬编码的魔法数字，问它是哪来的，它会编一个理由

**正确用法：AI 写初稿，人做审查。**

#### 2. 测试不是负担，是保险

如果没有 Guardrail 测试：

- 外包的烂代码会一直在系统里腐烂
- 架构违规会越来越多
- 回归 bug 会无穷无尽

**我现在有 1600+ 测试用例，每次提交都跑，心里踏实。**

#### 3. 架构设计要趁早

早期省下的时间，后期加倍偿还。

四层架构（Domain/Application/Infrastructure/Interface）：

- Domain 层：纯业务逻辑，不依赖任何框架
- Application 层：用例编排
- Infrastructure 层：数据库、外部服务
- Interface 层：API、序列化

**一开始就要定好规矩，否则技术债利滚利。**

#### 4. 个人项目也要有工程化

- CI/CD 自动化
- 代码审查流程
- 测试覆盖要求
- 文档规范

**这不是大公司的专利，个人项目更需要。**

---

## 彩蛋 | 那些让我崩溃的提交记录

### 最长的提交信息

```
fix: Resolve 24 system logic issues and eliminate hardcoding

## High Priority (4)
- Audit module: Replace fake random data with real price data
- Policy module: Save raw data (PX level) on processing failure
...

42 files changed, 3019 insertions(+), 154 deletions(-)
```

### 最绝望的几天

```
Day 66: Fix MCP write tool serialization and error handling
Day 67: Fix additional MCP write tool alignment
Day 68: Fix remaining MCP write tool failures
Day 69: Fix long-tail MCP tool alignment and smoke regressions
```

**连续四天修同一个问题。**

### 最解气的提交

```
Remove fake data generation from Alpha providers
```

**删掉外包写的假数据生成代码，心情舒畅。**

---

## 2026-04-18 补充记录 | Nightly CI 可靠性修复

- 现象：`Nightly Tests` 的 unit 步骤在 GitHub Actions 上卡到 98% 后出现 `node down: Not properly terminated`
- 根因：`pytest-xdist` worker 在 hosted runner 上异常退出，主进程继续等待，最终被 step timeout 杀掉
- 处理：nightly 的 unit 步骤改为串行执行，保留 `pytest-timeout`，并补充 `faulthandler_timeout`
- 结果：本地用同等 coverage 参数串行复跑，`3592 passed, 4 skipped`，耗时约 4 分 32 秒，明显低于 25 分钟上限

这类问题不是业务逻辑失败，而是测试运行器稳定性问题。Nightly 更重视可重复和可诊断，先保证稳定跑完，再考虑并行提速。

---

## 2026-04-18 补充记录 | Dashboard Alpha E2E/UAT 对齐

- 本地 `tests/playwright/tests/uat` 在 `http://localhost:8000` 跑通，`74 passed`
- 本地 `tests/e2e` 初始失败 2 项，根因都不是线上逻辑回退，而是测试桩仍按旧版 Dashboard Alpha 接口断言
- 修复点：
  - E2E 改为 mock `_get_alpha_stock_scores_payload(top_n, user, portfolio_id)`，与账户池作用域接口保持一致
  - JSON 端点断言从旧字段 `items` 改为当前返回字段 `top_candidates`
  - 页面动作文案断言从旧文案 `加入观察` 更新为当前文案 `在 Workflow 中查看`
- 结果：本地复跑 `tests/e2e`，`96 passed`

这次收口的是测试契约漂移，不是产品偷偷回退。Dashboard Alpha 现在线上行为与测试已经重新对齐。

---

## 2026-04-18 补充记录 | 本地全量回归入口与 CI 假绿收口

- 问题 1：RC Gate 的 Journey Tests 之前没有显式启动 Django server，Playwright 在 live server 不可达时可能整组 `skip`，workflow 仍然通过。
- 问题 2：nightly 的 Playwright smoke 带 `|| true`，失败不会阻断 nightly。
- 问题 3：consistency check 还保留 route baseline=35 的历史容忍逻辑，而当前实际已经是 `0` 违规。
- 问题 4：本地完整回归没有统一入口，开发者需要手工拼命令，容易漏跑。

这次一起收口：

1. 新增 `scripts/run_live_server_pytest.py`，统一负责：
   - 起 Django live server
   - 等待 `/account/login/` 可达
   - 显式注入 `--base-url`
   - 生成 JUnit XML
   - 校验最小执行数
   - 拒绝“整组 skip 但门禁仍绿”
2. 新增 `scripts/run_full_regression.py`，把一致性、架构、安全、本地后端矩阵、浏览器矩阵、RC 等价子集统一成一个命令。
3. `tests/playwright/conftest.py` 增加严格模式：CI 或 `AGOM_PLAYWRIGHT_REQUIRE_SERVER=1` 时，live server 不可达直接 fail。
4. `tests/uat/run_uat.py` 改为复用统一 helper，不再各自维护一套 Playwright 启动路径。
5. `rc-gate.yml` / `nightly-tests.yml` / `consistency-check.yml` 统一切到真实失败语义。

这类改动不改变产品功能，但会明显提高“本地绿”和“CI 绿”的可信度。后面再出红灯，就更大概率是真问题，不是门禁自己在骗我们。

---

## 2026-04-19 补充记录 | Nightly Smoke 空库契约修正

- 现象：`Nightly Tests` 的 Playwright smoke 在 GitHub Actions 上失败 6 项，但本地带业务数据的开发库无法稳定复现。
- 根因：nightly 使用的是“迁移后但未灌业务数据”的全新 SQLite 数据库；`macro / regime / signal / audit / filter / rotation` 六个页面会合法进入空态，但 smoke 断言仍硬要求 `.ind-item / .regime-card / .signal-card / .report-card / .summary-value / .asset-card` 必须存在。
- 处理：
  1. `tests/playwright/tests/smoke/test_critical_paths.py` 新增可见空态识别辅助函数；
  2. 上述六个页面改为校验“数据态 or 合法空态”二选一；
  3. 仍然保留页面骨架、标题、核心控件等断言，避免把 smoke 放宽成“HTTP 200 即通过”。
- 本地验证：
  - 新建空库 `tmp/nightly-smoke.sqlite3`
  - 执行 `migrate` 并创建 `admin`
  - 先复跑 6 个失败点：`6 passed`
  - 再按 nightly 等价命令复跑整套 `tests/playwright/tests/smoke`：`28 passed`

这次修的是 smoke 契约，不是给产品加 mock 数据，也不是吞掉真实失败。以后如果页面在空库下渲染坏掉，nightly 仍会报红；只是不会再因为“合法空态”被误判成失败。

---

## 下一步计划

- 更多 AI Agent 集成
- 实盘对接
- 多用户支持

**敬请期待后续连载！**

---

#AgomSAAF #投资系统 #Django #AI原生 #个人项目 #技术分享 #踩坑记录 #外包血泪史

---

> 如果这篇日记对你有帮助，欢迎点赞收藏！
> 有问题欢迎评论区交流～
> 
> P.S. 如果你也在做类似项目，记住一句话：
> **AI 生成的代码，审查两遍再提交。**
