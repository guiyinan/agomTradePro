  # AgomSAAF 全业务 SDK/MCP 覆盖 + 最新 OpenAI API 兼容三期开发计划（6-10 周）

  ## Summary

  - 目标：让 SDK + MCP 覆盖系统整体业务（含管理后台可操作能力映射），并完成 OpenAI 最新
    API 的双栈兼容迁移。
  - 迁移策略：Responses API 主路径 + chat.completions 兼容回退，兼容窗口保留 2 个版本。
  - 交付节奏：三期稳妥推进；一期先完成 OpenAI 内核与高频业务链路。
  - 验收口径：每个业务模块至少具备“CRUD + 关键业务动作”，并在 MCP 按 RBAC 分级开放。

  ## 当前基线（已确认）

  - 已有 SDK/MCP 重点覆盖：account, alpha, backtest, equity, factor, fund, hedge,
    macro, policy, realtime, regime, rotation, sector, signal, simulated_trading,
    strategy。
  - 系统存在但覆盖不足/缺失模块：ai_provider, prompt, audit, events, decision_rhythm,
    beta_gate, alpha_trigger, dashboard, asset_analysis, sentiment, task_monitor,
    filter（以及管理后台操作链路）。
  - OpenAI 现状：代码主用 chat.completions；需引入 Responses API 主路径。
  - 外部时间点（用于计划约束）：Assistants API 已弃用并计划于 2026-08-26 下线；本计划不
    新增 Assistants 依赖。

  ## 成功标准（DoD）

  - SDK 覆盖全部业务模块，提供统一错误模型、分页、幂等、重试与类型定义。
  - MCP 覆盖全部业务模块的读写关键动作，治理动作按角色分级（默认只读+受控写）。
  - OpenAI provider 对 OpenAI 走 Responses 主路径，失败回退 chat 路径，具备可观测性与灰
    度开关。
  - 回归测试通过：单元、契约、集成、MCP 验收、关键页面 E2E。
  - 文档齐全：迁移指南、兼容策略、弃用计划、模块能力矩阵。

  ## 公共接口/类型变更（对实现者决策已锁定）

  - 新增 LLMAdapterProtocol 抽象接口，统一方法：
      - generate(request) -> LLMResponse
      - stream(request) -> Iterator[LLMChunk]（可选实现）
      - supports(capability) -> bool
  - 新增 OpenAIResponsesAdapter（主路径）与 OpenAIChatAdapter（回退路径）。
  - 在 AI Provider 中新增配置字段（DB + DTO + 管理页）：
      - api_mode: dual|responses_only|chat_only（默认 dual）
      - fallback_enabled: bool（默认 true）
      - fallback_timeout_ms: int（默认 6000）
      - model_mapping_json: JSON（按任务映射模型）
  - SDK 统一响应结构（内部标准，不破坏现有方法签名）：
      - items/list + pagination(meta)、error(code,message,details)、request_id
  - SDK 新模块（文件级）：
      - ai_provider.py, prompt.py, audit.py, events.py, decision_rhythm.py,
        beta_gate.py, alpha_trigger.py, dashboard.py, asset_analysis.py, sentiment.py,
        task_monitor.py, filter.py
  - MCP 新工具域（对应上面缺失模块）并标注权限级别：
      - read, write, admin 三层；默认仅 read 自动暴露。
  - MCP 新资源与提示词：
      - 资源：系统健康、任务队列、审计摘要、事件总线状态、AI provider 健康。
      - 提示词：运营巡检、策略执行复盘、审计异常解释、事件回放分析。

  ## 全量覆盖矩阵（实现范围）

  - 业务交易投研域：account/signal/strategy/backtest/simulated_trading/regime/macro/
    policy/realtime/equity/fund/sector/factor/rotation/hedge/alpha/filter/
    asset_analysis
  - 平台治理域：ai_provider/prompt/audit/events/decision_rhythm/beta_gate/
    alpha_trigger/sentiment/task_monitor/dashboard
  - 管理后台操作映射：用户审批、token 管理、provider 配置、prompt/chain 管理、审计流
    程、事件回放、系统巡检。

  ## 三期实施计划（6-10 周）

  ## 第 1 期（第 1-3 周）：OpenAI 内核 + 高频业务闭环

  - 实现 LLMAdapterProtocol 与 OpenAI 双栈适配器。
  - 将现有 OpenAI 调用点迁移到抽象层（保留旧入口，打弃用告警）。
  - 完成高频模块 SDK/MCP 补强：
      - account, signal, strategy, simulated_trading, regime, macro, policy, realtime,
        backtest
  - 增加 feature flag：
      - AGOMSAAF_OPENAI_API_MODE=dual|responses_only|chat_only
      - AGOMSAAF_OPENAI_FALLBACK_ENABLED=true|false
  - 输出一期文档：
      - 《OpenAI 双栈迁移指南》
      - 《一期模块能力清单》

  ## 第 2 期（第 4-7 周）：平台治理 + 管理后台映射

  - 新增 SDK 模块：
      - ai_provider, prompt, audit, events, decision_rhythm, beta_gate, alpha_trigger,
        task_monitor, dashboard
  - 新增 MCP 工具与资源（RBAC 分级）：
      - 治理动作默认只对 admin 或指定角色开放。
  - 打通管理后台关键动作的 API 化映射：
      - 用户/角色审批、token 轮换、provider 配置、审计审核、事件回放、系统状态查询。
  - 完成跨模块错误码与审计日志统一。
  - 输出二期文档：
      - 《治理能力 MCP 权限矩阵》
      - 《管理后台能力 API 映射表》

  ## 第 3 期（第 8-10 周）：剩余模块收口 + 质量硬化 + 兼容发布

  - 新增/补齐 SDK/MCP：
      - asset_analysis, sentiment, filter 及边缘接口补齐。
  - 完成端点覆盖核查：
      - 逐模块“端点清单 vs SDK 方法 vs MCP 工具”三方对账。
  - 压测与稳定性优化：
      - 重试策略、超时、并发、速率限制、熔断。
  - 发布兼容版本并给出弃用路线：
      - 保留旧行为 2 个版本，后续进入强制 Responses 模式准备。
  - 输出三期文档：
      - 《全量覆盖验收报告》
      - 《旧接口弃用计划（2 版本窗口）》

  ## 测试计划与场景

  - 单元测试：
      - OpenAI 双栈适配器的请求构造、解析、回退逻辑、异常分类。
      - SDK 各模块参数校验、分页、错误映射。
  - 契约测试：
      - 以 OpenAPI 为基线，校验 SDK 方法与 API 字段一致性。
  - 集成测试：
      - 核心链路 E2E：信号生成→策略执行→模拟交易→审计。
      - 治理链路 E2E：provider 切换→prompt 执行→事件发布/回放→监控。
  - MCP 验收：
      - 工具注册、资源读取、提示词调用、RBAC 拒绝/放行。
  - 回归测试：
      - 管理后台关键页面动作可通过 API+MCP 完成同等操作。
  - 性能测试：
      - 高并发工具调用、分页大列表、重试退避、超时边界。

  ## 发布与回滚

  - 灰度策略：
      - 先按 provider / 环境灰度启用 responses_only，保留一键回退 dual。
  - 监控指标：
      - OpenAI 成功率、回退率、延迟分位、错误码分布、MCP 工具失败率。
  - 版本策略：
      - vNext 引入双栈；vNext+1 强化告警；vNext+2 评估去除旧路径。
  ## 风险与缓解

  - 风险：不同 provider 对 OpenAI 兼容度不一。
  - 缓解：仅 OpenAI provider 默认走 Responses；其他 provider 保持 chat 路径并能力探测。
  - 风险：治理动作经 MCP 暴露带来误操作风险。
  - 缓解：默认只读、写操作二次确认、RBAC 白名单、审计全量记录。
  - 风险：全量覆盖范围大导致周期漂移。
  - 缓解：每期固定 DoD + 模块冻结清单 + 周度对账表。

  - OpenAI 迁移策略：双栈平滑迁移。
  - 交付节奏：三期 6-10 周。
  - 兼容窗口：旧行为保留 2 个版本。
  - 覆盖深度：每模块 CRUD + 关键业务动作。
  - MCP 定位：治理动作分级开放（默认只读，受控写）。
  - 一期优先级：OpenAI 内核 + 高频业务链路优先。