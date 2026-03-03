# 工程护栏与评审规矩

> 生效日期：2026-02-22  
> 适用范围：Policy / Regime / Audit / Sentiment / Backtest 及所有新模块

## 目标

避免以下问题重复出现：

1. 阈值和关键参数硬编码，导致配置失效。
2. 外部数据处理链路失败时数据丢失。
3. 宽泛异常吞错，掩盖真实故障。
4. 测试依赖环境初始数据，导致不稳定或误报。

## 强制规则

### 0) 四层架构红线（必须满足）

1. 唯一允许依赖方向：`Interface -> Application -> Domain`，`Infrastructure -> Domain`。
2. 禁止反向依赖：`Domain -> Application/Infrastructure/Interface`、`Application -> Interface`。
3. Domain 层禁止导入任何 `django.*`、ORM Model、`pandas/numpy/requests` 等外部库。
4. Application 层禁止直接导入 ORM Model；必须通过 Domain Protocol + Repository 访问数据。
5. Interface 层禁止写业务规则；只允许参数校验、调用 UseCase、返回 DTO/Response。
6. Infrastructure 层禁止承载业务决策；仅实现 Repository/Adapter/网关细节。

### 0.1) 四层架构门禁命令（PR 必跑）

1. Domain 禁用依赖扫描：  
   `rg -n "from django|import django|import pandas|import numpy|import requests" apps/*/domain -S`
2. Application 直连 ORM 扫描：  
   `rg -n "from .*infrastructure\\.models|\\.objects\\." apps/*/application -S`
3. Interface 越层调用扫描：  
   `rg -n "from .*infrastructure\\.|from .*domain\\.(services|rules)" apps/*/interface -S`

### 1) 配置唯一来源（Single Source of Truth）

1. 所有业务阈值必须通过 `ConfigHelper + ConfigKeys` 读取。
2. 默认值只允许作为“配置缺失兜底”，不得在业务分支中重复写字面量阈值。
3. 同一阈值在代码中出现第二处时，必须解释为何不是复用配置键。

### 2) 外部数据处理采用两阶段入库

1. 阶段1：先持久化原始记录（`pending/raw` 状态）。
2. 阶段2：再进行解析、分类、提取、打标，并回写同一条记录。
3. 阶段2失败时，必须保留阶段1记录并写入失败元数据（错误、阶段、时间）。

### 2.1) 事件唯一键与更新策略

1. 仓储层禁止默认“按日期覆盖”更新事件。
2. 事件更新必须基于明确标识：
   - RSS 场景：`rss_item_guid`；
   - 通用场景：`event_date + title + evidence_url`；
   - 人工更新场景：显式 `id`。
3. 只有在明确的迁移/补录脚本中，才允许按日期批量修订。

### 3) 异常处理分层

1. 业务层禁止无说明 `except Exception` 直接吞错并返回成功。
2. 可恢复异常必须记录结构化上下文（模块、输入摘要、错误类型、trace id）。
3. 不可恢复异常必须上抛到统一错误边界并触发告警。

### 4) 测试必须环境无关

1. 集成测试不得假设数据库天然为空。
2. 用例应通过 fixture 主动清理或构建自己的测试数据基线。
3. 对“配置生效”与“失败兜底”必须有回归测试。
4. 诊断类测试（guardrails）默认纳入 CI，不允许长期 `xfail` 漂移。
5. 当前 CI 工作流：
   - `.github/workflows/logic-guardrails.yml`
   - `.github/workflows/architecture-layer-guard.yml`
6. Guardrail 必跑命令：
   `pytest -q tests/guardrails/test_logic_guardrails.py tests/integration/policy/test_policy_integration.py tests/unit/policy/test_fetch_rss_use_case.py tests/unit/regime/test_config_threshold_regression.py`

## 代码评审清单（PR Checklist）

1. 是否存在新增硬编码阈值/魔法数字？
2. 是否复用已有 `ConfigKeys`？
3. 外部数据链路是否先入库后处理？
4. 失败时是否保留原始数据并可追溯？
5. 是否新增了覆盖关键分支的测试（成功、失败、边界）？
6. 测试是否依赖环境预置数据？

## 发布门禁（Release Gate）

合入前至少满足：

1. 关键回归集通过：Policy/Regime/Audit/Backtest 相关单测与集成测试。
2. 本文 PR Checklist 全项勾选。
3. 关键参数变更已在配置中心登记，并附默认值与回滚策略。
