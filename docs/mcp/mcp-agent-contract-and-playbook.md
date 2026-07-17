# MCP Agent 运行契约与工作流 Playbook

> 最后更新：2026-07-17  
> 适用范围：AgomTradePro Python SDK 内置 MCP Server  
> 默认配置：`sdk/agomtradepro_mcp/prompts/agent_contracts.json`

## 1. 目标与边界

Agent 运行契约用于告诉外部 Agent 如何发现、校验和调用 AgomTradePro 能力，降低其绕开 Regime、Policy、确认流程或输出契约的概率。

Prompt 不是安全边界。以下规则仍由服务端强制执行，Prompt 或外部 Agent 均不能覆盖：

- RBAC、可见性和真实用户权限；
- 输入 Schema 白名单和未知参数拒绝；
- 风险等级、确认 token 绑定与有效期；
- 幂等性和允许的状态流转；
- 模拟交易边界和审计日志。

系统不要求、保存或返回隐藏思维链。Agent 只能返回简短的 `decision_summary`，说明意图、所选能力、显式假设、缺失参数、风险、证据和下一步。

## 2. MCP 入口

### 2.1 核心工具

| 工具 | 用途 |
| --- | --- |
| `agom_get_agent_contract` | 返回当前契约版本、校验值、强制规则、结构化决策摘要 Schema 和任务覆盖规则 |
| `agom_get_workflow_playbook` | 返回 Playbook 目录或指定 Playbook |
| `agom_capability_search` | 使用中英文业务意图检索候选能力 |
| `agom_capability_schema` | 获取单项能力的参数、风险和确认契约 |
| `agom_capability_call` | 通过统一 dispatcher 执行能力 |
| `agom_confirmation_resume` | 恢复服务端锁定的待确认操作 |

### 2.2 Resources

| URI | 内容 |
| --- | --- |
| `agomtradepro://agent/contract` | 当前完整 Agent 运行契约，JSON |
| `agomtradepro://agent/playbooks` | Playbook 索引、版本和内容校验值，JSON |

### 2.3 Prompts

- `agom_agent_contract(task_type)`：把当前契约作为 Agent 工作上下文加载；
- 原有 `analyze_macro_environment`、`check_signal_eligibility` 和 `run_*_workflow` Prompt 保持名称兼容，但正文改由版本化配置渲染。

## 3. 标准调用顺序

```text
agom_get_agent_contract
        ↓
agom_get_workflow_playbook（适用时）
        ↓
agom_capability_search
        ↓
agom_capability_schema
        ↓
agom_capability_call
        ↓
agom_confirmation_resume（仅服务端要求确认时）
```

如果没有可靠匹配，Agent 必须返回 no-match 或提出一个简短澄清问题，不得默认执行 `builtin.system_status`。

## 4. 结构化决策摘要

Agent 不输出原始思维链，使用以下可审计摘要：

```json
{
  "intent": "fund_recommendation",
  "capability_key": "fund.read.ranking",
  "assumptions": [],
  "missing_params": [],
  "risk_level": "low",
  "requires_confirmation": true,
  "evidence": [
    "用户明确要求适合当前市场的基金",
    "已读取当前 Regime 和 Policy"
  ],
  "next_action": "request_confirmation"
}
```

`decision_summary` 只解释可观察的选择依据，不包含隐藏推理过程。

## 5. 内置 Playbook

配置中提供以下稳定任务族：

- `market_research`
- `fund_recommendation`
- `account_aware_fund_recommendation`
- `signal_review`
- `monitoring`
- `decision`
- `execution`
- `ops`

Playbook 只编排能力调用顺序，不复制金融算法，也不替代 Domain 规则和服务端权限。

## 6. 配置、版本与校验

默认配置文件为：

```text
sdk/agomtradepro_mcp/prompts/agent_contracts.json
```

配置包含：

- `schema_version`
- `contract.contract_id`
- `contract.version`
- `contract.status`
- `contract.effective_at`
- 强制规则、路由协议、失败策略和任务覆盖规则
- Playbook 定义
- Prompt 模板及其声明参数

MCP 返回运行时计算的 `content_sha256`，用于审计和定位 Agent 使用的具体内容版本。生产环境可使用独立配置：

```powershell
$env:AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH="D:\agom-config\agent_contracts.json"
```

Linux：

```bash
export AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH=/etc/agomtradepro/agent_contracts.json
```

修改配置时必须同时提升 `contract.version`，完成 JSON 校验和 MCP 契约回归后再切换环境变量。配置不可读取、JSON 损坏或 Schema 版本不支持时，MCP 初始化欢迎词降级为代码内最小安全基线；权限、确认和 Schema 等服务端护栏不受影响。

## 7. 发布与回滚

推荐发布流程：

1. 复制当前配置为新版本；
2. 修改 Prompt 或 Playbook，提升 `contract.version`；
3. 运行 `sdk/tests/test_mcp/test_agent_contracts.py` 和 MCP 固定回归；
4. 让灰度 MCP 实例指向新文件；
5. 检查 `contract.version` 与 `content_sha256`；
6. 再切换正式实例。

回滚只需把 `AGOMTRADEPRO_MCP_AGENT_CONTRACT_PATH` 指回上一份已验证配置并重启 MCP Server。不得通过降低服务端权限、关闭确认或放开参数 Schema 来解决 Prompt 兼容问题。
