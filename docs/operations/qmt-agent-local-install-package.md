# 国金 QMT 本地 Agent 安装包说明

## 1. 当前客户端结论

目标电脑安装的是国金证券 QMT 智能策略交易终端 `2.1.19.0`。登录页提供“行情+交易 / 交易 / 行情”和“独立交易”，**没有“极简模式”选项**。因此本项目不再把“极简模式”作为安装前提：

- 当前国金普通 QMT 使用 `D:\qmt\userdata`；
- 若券商以后另行提供 MiniQMT，安装程序会优先识别 `userdata_mini`；
- “独立交易”不等同于已开通外部 XtQuant Python API，是否勾选应以国金证券说明为准；
- 普通 QMT 已登录但 `XtQuantTrader.connect()` 返回失败时，应确认券商接口权限或专用客户端版本，而不是反复修改 VPS。

联系国金证券时可直接使用下面的描述：

> 请确认该普通股票资金账号是否已开通 QMT 外部 XtQuant Python API、函数查询、函数委托和撤单权限。当前使用国金 QMT 2.1.19.0，外部 Python XtQuantTrader 连接 D:\qmt\userdata 返回失败。若该版本不支持外部 API，请提供支持 XtQuant 的 QMT/MiniQMT 安装包及匹配 SDK。

## 2. 安装包包含什么

仓库构建产物：`artifacts/qmt-agent/agom-qmt-agent-windows-0.1.0.zip`。

安装包包含：

- Agom QMT Agent 代码；
- Windows 安装、Token 保存、只读测试和卸载脚本；
- 普通 `userdata` / MiniQMT `userdata_mini` 自动识别；
- 独立 Python venv；
- 锁定的迅投官方 `xtquant` 下载地址、版本和 SHA-256；
- 默认 `dry_run: true` 的 JSON 配置；
- 当前 Windows 用户与 SYSTEM 专属目录 ACL；
- 可选的登录后自动启动任务。

安装包不包含：

- QMT 客户端及交易密码；
- 券商账户密码、VPS 密码或 Agent Token；
- `xtquant` 二进制 wheel（安装时从锁定的官方地址下载并校验，或使用券商提供的 wheel）；
- 自动实盘启用配置。

## 3. 构建安装包

在仓库根目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_qmt_agent_package.ps1
```

构建脚本生成 ZIP 和同名 `.sha256` 文件。ZIP 内的 `manifest.json` 记录所有文件的大小和 SHA-256，且明确标记不包含秘密、QMT 和 xtquant wheel。

### 3.1 在 TUI 完成服务端接入

管理员可在 TUI 的“系统治理 → QMT 接入与设置”完成服务端准备，不再需要从“账户与持仓”的通用动作列表里寻找 QMT 配置：

1. 先读取“QMT 接入指引”，复制安装包构建、Windows 安装、Token 保存和只读验收命令；
2. 预览并确认 Agent 与系统账户绑定；
3. 核对当前执行门禁，完成额度、白名单、交易时段和快照时效设置；
4. 创建一次性 Agent 凭证，立即复制 Token 并在 Windows 使用 DPAPI 保存；
5. 安装后查看 Agent/QMT 连接与最后心跳，必要时下发一次全量同步；
6. 只读探针与仿真验收完成前保持自动执行关闭。

该工作区只对管理员开放；普通用户仍在“账户与持仓”查看实盘就绪结论、订单和已授权连接，不会看到凭证、绑定或门禁变更动作。

## 4. 安装

先安装一个 64 位 Python 3.11。不要使用 QMT 自带的 Python 3.6 运行 Agom Agent。

解压安装包，在解压目录执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 `
  -PythonExe "C:\path\to\python.exe" `
  -QmtRoot "D:\qmt" `
  -ServerUrl "https://your-vps.example.com" `
  -SystemAccountId 1 `
  -AgentId "qmt-home-01" `
  -RegisterTask `
  -RunReadProbe
```

说明：

- `SystemAccountId` 是 AgomTradePro 服务端账户 ID，不是券商资金账号；
- 安装程序会在普通 QMT 仅有一个本地用户目录时自动识别券商账号，否则要求显式传入 `-BrokerAccountId`；
- 默认安装到 `%LOCALAPPDATA%\AgomQmtAgent`，避免向 QMT 目录写入 Agent 文件；
- 安装程序创建私有运行时并安装锁定的 `xtquant`；
- 若使用券商 wheel，必须同时传 `-XtQuantWheelPath` 和 `-XtQuantWheelSha256`；
- 安装后配置仍是 `dry_run: true`，不会自动打开实盘。

## 5. 保存 Agent Token

在 AgomTradePro“实盘执行中心 → 本地连接”创建一次性 Agent Token 后，在与计划任务相同的 Windows 用户下执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Set-AgentToken.ps1 -StartTask
```

脚本使用 `Read-Host -AsSecureString` 输入 Token，并用 Windows DPAPI 加密到安装目录。Token 不进入 `config.json`、日志或安装包，也不能被其他 Windows 用户直接解密。`-StartTask` 会在 Token 保存成功后启动已经注册的 `AgomQmtAgent` 计划任务。

## 6. 只读验收

保持 QMT 已登录，然后执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Test-Connection.ps1 -ReadProbe
```

测试只执行：

- Windows/Python/xtquant/目录预检；
- QMT 连接；
- 资产接口存在性、持仓、当日委托和当日成交查询；
- 生成不含券商账号和资金数值的证据 JSON。

测试不会调用报单或撤单。常见结果：

| 结果码 | 含义 | 处理 |
| --- | --- | --- |
| `QMT_CONNECTION_FAILED` | 外部 SDK 未连接到 QMT | 确认 QMT 已登录；仍失败则联系国金开通外部 XtQuant 或更换支持版本 |
| `QMT_SERVER_NOT_ALLOWED` | QMT 日志明确拒绝启动 XtQuantServer | 当前账号或客户端没有外部 XtQuant 服务权限；联系国金开通或提供支持客户端 |
| `QMT_ACCOUNT_SUBSCRIPTION_FAILED` | QMT 已连接但账户订阅失败 | 核对普通股票账户类型、账号绑定及函数查询权限 |
| `XTQUANT_IMPORT_FAILED` | SDK 未正确安装 | 重新安装并核对 wheel SHA-256、Python 位数和版本 |
| `ready: true` | 只读接口门禁通过 | 继续仿真报撤单验收，仍不得直接启用实盘 |

## 7. 权限与安全

- 服务端 RBAC 决定谁能审批订单、撤单、停止或恢复交易；账户授权限制用户和 Agent 可访问的账户。
- 本地安装目录只授权当前 Windows 用户和 SYSTEM。
- Agent Token 使用 DPAPI 加密；QMT 密码始终由 QMT 客户端管理。
- Agent 只向 VPS 发起 HTTPS 出站连接，不在本机开放入站端口。
- `dry_run`、服务端自动执行开关、本地 STOP 文件和账户停止开关共同构成多重门禁。

## 8. 卸载与回滚

默认卸载会移除计划任务、代码、私有 Python、下载缓存和加密 Token，但保留配置、日志和 SQLite 状态：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall.ps1
```

确认不再需要取证和恢复信息时，才使用：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall.ps1 -RemoveState
```

完整运行、停止、故障和仿真验收流程参见 [QMT Agent 运维手册](qmt-agent-runbook.md)。
