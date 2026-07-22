# QMT Agent 安装与运行手册

## 1. 本地需要额外安装什么

需要。VPS 不安装 QMT；执行端 Windows 主机至少需要：

1. 券商提供且已开通程序化交易权限的 QMT/MiniQMT；
2. Python 3.10+，并且该解释器必须与目标 QMT/`xtquant` 版本兼容；
3. 券商随 QMT 提供或指定版本的 `xtquant`；如使用迅投官方发布包，必须锁定版本、校验 wheel SHA-256 并在目标客户端通过只读探针；
4. AgomTradePro 的 `qmt_agent/` 目录；
5. 使用 YAML 配置时安装 `PyYAML`；使用 JSON 配置则不需要它；
6. Windows 任务计划或服务托管、自动时间同步、滚动日志目录和本地状态目录。

`PyYAML` 可由仓库自带安装脚本安装；Agent 的 HTTPS 通信使用 Python 标准库，不需要额外安装 `requests`。`xtquant` 必须来自券商/QMT 交付环境或迅投官方发布渠道，不能从 VPS 或来源不明的同名包替代。建议直接执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\qmt_agent\scripts\install-agent.ps1 `
  -PythonExe "C:\path\to\broker-python.exe" -InstallRoot "C:\AgomQmtAgent" -RegisterTask
```

不要把 `xtquant` 加入 VPS 的 `pyproject.toml` 或生产镜像。当前 Agent 的最低语法基线是 Python 3.10；不同券商和 QMT 版本的 Python/`xtquant` 兼容范围可能不同，必须以券商交付包为准。如果券商仅提供不兼容 Python 3.10+ 的 `xtquant`，WP0 不通过，必须先制作并单独验收兼容 Agent 制品，不能直接启用实盘。

### 1.1 QMT 必须具有可供外部 API 连接的权限

- 普通 QMT 窗口已经登录，不代表 `xtquant` 可以连接。
- MiniQMT/极简模式通常使用安装目录下的 `userdata_mini`；投研端可按券商版本使用 `userdata`。
- 国金 QMT `2.1.19.0` 登录页没有“极简模式”，当前安装使用普通端 `D:\qmt\userdata`；不得要求用户勾选一个不存在的选项。
- 登录页“独立交易”不等同于外部 XtQuant API 授权，是否勾选应以券商说明为准。
- 普通端或 MiniQMT 的只读探针返回 `QMT_CONNECTION_FAILED` / `QMT_ACCOUNT_SUBSCRIPTION_FAILED` 时，联系券商确认 xtquant、函数查询和函数下单权限，并确认是否需要专用客户端。
- 在只读探针通过以前，保持 `dry_run: true`、自动执行关闭，并禁止真实报单验收。

目标机 2026-07-22 首次实测为国金证券 QMT `2.1.19.0` 普通会话：Python 3.11 与 `xtquant 250807.1.2` 隔离导入成功，普通端 `userdata` 存在，真实只读探针返回 `QMT_CONNECTION_FAILED`。下一步是向国金确认该账号的外部 XtQuant 权限和所需客户端版本，而不是修改 VPS 或降低项目 Python 版本。

仓库提供可重复构建的 Windows ZIP 安装包，详见 [国金 QMT 本地 Agent 安装包说明](qmt-agent-local-install-package.md)。

## 2. 服务端初始化

部署代码后执行数据库迁移，并确保 Celery Worker/Beat 正常：

```powershell
python manage.py migrate
python manage.py check
```

管理员打开“实盘执行中心 → 本地连接”：

1. 绑定系统账户、Agent ID 和券商账户；
2. 在“执行设置”配置单笔上限、单日上限和标的白名单；
3. 保持自动执行关闭，直到 dry-run 和仿真验收完成；
4. 创建 Agent 凭证时显式选择允许访问的系统账户 ID；凭证不能访问同一 Agent 下未列入范围的其他账户；
5. 立即复制完整 Token，它只显示一次。账户绑定范围变化后应轮换凭证，不能依赖旧凭证自动扩大权限。

## 3. Windows 配置

复制 [`qmt_agent/config.example.yaml`](../../qmt_agent/config.example.yaml)，填写本机配置，并按券商交付物填写 `qmt_client_version` 与 `xtquant_version`。普通配置文件不得保存 Token、密码或私钥。

在受限用户的环境变量中设置一次性凭证：

```powershell
[Environment]::SetEnvironmentVariable(
  "AGOM_QMT_AGENT_TOKEN",
  "<credential-id>.<secret>",
  "User"
)
$env:AGOM_QMT_AGENT_TOKEN = [Environment]::GetEnvironmentVariable(
  "AGOM_QMT_AGENT_TOKEN",
  "User"
)
```

第一行供该低权限 Windows 用户的后续任务计划进程读取，第二行只让当前 PowerShell 会话立即可用。轮换或撤销后必须同步覆盖/清除用户级变量；不要把 Token 写入 YAML、启动参数或任务计划描述。

首次运行兼容性探针：

```powershell
python -m qmt_agent.main --config C:\AgomQmtAgent\config.yaml --preflight
```

探针应确认 Windows、Python 3.10+、`xtquant`、`userdata_mini`、日志和状态目录。随后先使用 Fake QMT 和 `dry_run: true`：

启动并登录 QMT 后，执行只读券商 API 探针并保存证据。该命令只查询连接、资金接口可用性、持仓、当日委托和当日成交，不报单、不撤单，也不输出券商账户号或资金数值：

```powershell
python -m qmt_agent.main --config C:\AgomQmtAgent\config.yaml `
  --qmt-read-probe --evidence-file C:\AgomQmtAgent\logs\qmt-read-probe.json
```

只有报告中 `read_only=true`、`submitted_order=false`、`canceled_order=false` 且 `ready=true` 时，才算完成 WP0 的只读部分。限价报单、撤单、部分成交与 callback 仍必须在券商仿真环境按 WP0/WP7 人工授权执行。

```powershell
python -m qmt_agent.main --config C:\AgomQmtAgent\config.yaml --fake success --once
```

连接真实 QMT 前，先启动并登录 QMT/MiniQMT，再运行：

```powershell
python -m qmt_agent.main --config C:\AgomQmtAgent\config.yaml --once
```

移除 `--once` 后进入持续轮询。建议用专用低权限 Windows 账户和任务计划托管，并设置登录后启动、失败重启和交易时段运行。

Agent 每次启动会先连接/重连 QMT、上传资金/持仓/当日委托/当日成交基线并恢复未决订单，然后才允许领取新单。运行中断线会在下一轮保守重连；没有新鲜快照、当前不在配置交易时段、行情价缺失、限价越界/偏离过大、现金或可用持仓不足、持仓数超限时都拒绝本地提交。

连接页的“测试连接 / 立即同步”不会从 VPS 反向连接家庭电脑，而是通过 Agent 已有的出站轮询下发 `full_sync` 命令。Dry-run 校验结果会以幂等事件回传，但订单不会进入 QMT 提交流程。批准、拒绝和撤单的确认请求必须使用刚才 preview 返回的订单版本；版本已变化时重新预览。

## 4. 分级启用

按以下顺序启用，不跨级：

1. Shadow：只生成服务端订单，不让 Agent 领取；
2. Dry-run：Agent 领取和校验，不调用 QMT 报单；
3. QMT 仿真：验证报单、部分/全部成交、撤单、断线和重启恢复；
4. 小额实盘：人工逐单批准；
5. 受限自动实盘：只允许白名单、严格额度和批准的时段。

建议至少连续 5 个交易日仿真无重复单和未处置差异，小额实盘至少连续 3 个交易日逐单确认后，再评估自动执行。

## 5. 紧急停止

任一入口触发 VPS 紧急停止后，Agent 不再领取或提交新订单。Windows 本地还可以创建配置中的 `STOP` 文件单方面阻止下单：

```powershell
New-Item -ItemType File -Path C:\AgomQmtAgent\STOP
```

删除本地 STOP 文件不会恢复 VPS。恢复必须由管理员在实盘执行中心预览确认，且 Agent 在线、QMT 已连接、未知订单和对账差异均已处理。最终确认时必须重新输入当前登录密码；Web、TUI 和 SDK/MCP 都执行同一服务端二次认证，密码不写入审计或响应。

## 6. 故障处理

- `OFFLINE`：检查 Windows 任务、网络、系统时间、凭证有效期和 Agent 日志；
- `REVIEW`：先查看执行异常与对账，不要重新报单；
- `RECONCILIATION_REQUIRED`：查询 QMT 当日委托/成交并接受券商事实或升级人工处理；
- `CANCEL_PENDING`：仅表示 QMT 已受理撤单请求，必须等待券商委托状态变为 `CANCELED`，不能据此假定未成交部分已经撤销；
- 凭证泄露：管理员立即撤销，创建新凭证后更新受限环境变量；
- 本地状态损坏：停止 Agent，保留 SQLite 和日志副本，先通过 QMT 查询所有未决委托，再恢复；
- 重复单疑似发生：立即触发 VPS 与本地 STOP，保留日志、订单事件和审计证据。

## 7. 当前外部验收项

仓库提供了 Fake Adapter、签名 Agent 契约和自动测试，但无法替代目标券商环境。上线前仍需记录券商、QMT/MiniQMT 版本、Python、`xtquant` 版本、普通股票账户类型，以及查询、报单、撤单、回调、重连和部分成交的实测证据。首版拒绝信用账户，不能用 `CREDIT` 绕过该门禁。

## 8. 升级与卸载

升级前先在 VPS 触发停止并确认没有 `SUBMITTING`、`CANCEL_PENDING` 或未处置对账批次，随后备份 `C:\AgomQmtAgent\state`、配置和日志。使用新版仓库重新运行 `install-agent.ps1` 会更新 Agent 代码并保留配置/状态；升级后依次运行 `--preflight`、Fake `--once`、真实 QMT `--once`，确认新基线已入库后再恢复。

默认卸载只移除计划任务和 Agent 代码，保留审计所需的配置、日志和 SQLite 状态：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\qmt_agent\scripts\uninstall-agent.ps1
```

只有完成归档并明确需要时才增加 `-RemoveState`。该选项会删除本地配置、日志、STOP 和 SQLite 状态，无法依赖 Agent 自身恢复。

## 9. 正式启用检查表

- [ ] 已记录券商、QMT、Python、`xtquant` 和账户类型兼容矩阵；
- [ ] Windows 专用低权限账户、时间同步、TLS 校验和 Token 文件/环境权限已验证；
- [ ] 服务端绑定的是统一账户中的 active real account，券商账户号只显示脱敏值；
- [ ] Agent 凭证已显式限制允许账户 ID，越范围心跳、拉单、回报、快照和命令均被拒绝；
- [ ] 单笔/单日额度、标的白名单、最大持仓数、快照时效、交易时段和价格偏离均非空且经第二人复核；
- [ ] Fake 的成功、拒单、未知结果、部分成交、全部成交、撤单、断线和重启恢复全部通过；
- [ ] 连续 5 个交易日 QMT 仿真无重复单、无未处置 P0/P1 差异；
- [ ] 连续 3 个交易日小额实盘逐单批准通过；
- [ ] Classic Web、TUI、SDK/MCP 的读取、预览、确认、越权拒绝和审计证据均通过；
- [ ] 紧急停止、P0 自动停止、告警转发、四维对账、日报与 operational readiness 证据均通过；
- [ ] 回滚负责人、窗口、版本和数据保全位置已填写。

## 10. 回滚记录模板

```text
变更编号：
Agent 旧版本 / 新版本：
服务端旧版本 / 新版本：
开始时间 / 停止时间（Asia/Shanghai）：
账户范围（仅系统账户 ID 与脱敏券商号）：
触发原因：
停止开关证据：
QMT 当日委托/成交导出位置：
Agent SQLite/日志备份位置与 SHA-256：
VPS 对账批次与审计 ID：
回滚动作：
回滚后基线快照时间：
未决差异与责任人：
复核人：
```
