# QMT 内置 Python 接入指南与联调记录

> 适用版本：Agom QMT Agent `0.3.0`，国金 QMT `2.1.19.0`，普通股票账户。
>
> 当前结论：2026-11-05 已在目标 Windows 主机通过真实只读探针。资金、持仓、当日委托、当日成交查询成功；未报单、未撤单。真实报撤单、成交回报、重启恢复和连续运行仍须单独验收，不得据此直接启用自动实盘。

## 1. 最终接入方式

券商停止外部 `xt`/MiniQMT 的函数查询、函数委托和撤单后，交易链路调整为：

```text
VPS AgomTradePro
  -> 订单审批、风控、租约和审计
本地 Agom QMT Agent
  -> Windows 命名管道 \\.\pipe\agom_qmt_builtin_bridge
QMT 内置 Python 实盘策略
  -> get_trade_detail_data / passorder / cancel
券商账户
```

命名管道不是 TCP/UDP 网络服务，不开放端口，也不依赖 QMT 策略的文件读写权限。Agent 原有风控、订单幂等、SQLite 未决状态、STOP 和 `RECONCILIATION_REQUIRED` 规则不变。行情仍使用 `xtdata`，账户查询成功不等于行情新鲜或可下单。

## 2. TUI 下载与一键引导脚本

管理员登录 TUI 后，在“系统治理”打开 **QMT 接入引导**。首屏可直接下载与当前 Agent 版本一致的 Windows 桥 ZIP，并查看版本、大小、SHA-256 和接入步骤。既有“QMT 接入与设置”也提供该引导页入口；只读验收后再返回设置页完成账户绑定、凭证和门禁。普通用户不能调用桥下载接口。

先按 [安装包说明](qmt-agent-local-install-package.md) 安装新版 Agent 并保存 Token。然后在 Windows PowerShell 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "C:\AgomQmtAgent\qmt_agent\scripts\setup-builtin-python.ps1" `
  -ConfigPath "C:\AgomQmtAgent\config.json"
```

默认安装位置是 `%LOCALAPPDATA%\AgomQmtAgent` 时，可省略 `-ConfigPath`。脚本会：

1. 检查 Agent 配置、QMT 程序和内置策略文件；
2. 备份现有 `config.json`；
3. 设置 `qmt_trade_api=builtin_python` 和默认管道名；
4. 强制保持 `dry_run=true`，不改变服务端审批或自动执行设置；
5. 显示接下来在 QMT 中需要完成的步骤。

脚本不读取或保存 QMT 密码，不修改 Agent Token，不调用报单或撤单接口。

完成第 3 节的 QMT 操作后，运行同一脚本并增加 `-RunReadProbe`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File "C:\AgomQmtAgent\qmt_agent\scripts\setup-builtin-python.ps1" `
  -ConfigPath "C:\AgomQmtAgent\config.json" `
  -RunReadProbe
```

脚本会等待用户确认策略已启动，然后执行只读探针。证据默认写入安装目录 `logs\builtin-read-probe.json`。只有 `ready=true` 且 `submitted_order=false`、`canceled_order=false` 才算只读接入成功。

## 3. QMT 中一步一步操作

### 3.1 新建策略文件

1. 登录 QMT 时使用 **行情+交易**，不要使用极简模式。
2. 在首页点击 **新建策略**，选择 **Python 策略**。
3. 名称设置为 `AgomBuiltinBridge`。
4. 删除编辑器中的全部模板代码。
5. 完整复制安装目录中的以下文件：

   ```text
   qmt_agent\builtin_strategy.py
   ```

6. 不需要修改 `PIPE_ADDRESS`、账号或其他代码。账号由下一步的模型交易条目绑定。
7. 点击 **编译/保存**。编译按钮主要用于保存，不代表策略已进入实盘运行。

### 3.2 在模型交易中启动

1. 返回主界面，进入 **模型交易**；部分版本显示为“策略交易”。
2. 点击 **新建策略交易**。
3. 选择刚保存的 `AgomBuiltinBridge`。
4. 绑定与 Agent `broker_account_id` 相同的普通股票账号。
5. 选择实盘运行并启动。此处只是启用内置接口；在只读探针阶段不会发送委托或撤单。
6. 保持策略运行，不要删除或停止模型交易条目，也不要同时启动多个使用同一管道名的实例。
7. 返回执行带 `-RunReadProbe` 的引导脚本。

策略日志应出现账号订阅和 `agom_poll` 定时器初始化。QMT 客户端和策略都必须在需要执行交易的时间段持续运行。

## 4. 券商客户端网络要求

若 QMT 提示 `198.18.x.x` 非法 IP，而本机运行 Clash Verge/Mihomo，应先处理代理，否则策略交易权限可能被拦截。本机有效配置为：

- `PROCESS-NAME,XtItClient.exe,DIRECT`；
- `DOMAIN-SUFFIX,gjzq.com.cn,DIRECT`；
- 在 `dns.fake-ip-filter` 中加入 `+.gjzq.com.cn`；
- `enable-process=true`、`find-process-mode=always`。

本次通过 Clash Verge `2.5.8` 的全局扩展脚本 `profiles\Script.js` 配置，保留原有 AgomTradePro VPS 直连规则。重启 Clash Verge 后，`qmt.gjzq.com.cn` 应解析为真实公网地址，而不是 `198.18.x.x`。随后完全退出并重新登录 QMT。

不要仅把命名管道名称加入代理例外；命名管道不经过 Clash，需要直连的是 QMT 到券商服务器的连接。修改 Clash 前备份脚本，恢复时还原备份并重启 Clash/QMT。

## 5. 本次联调记录与故障对照

| 现象/错误 | 已确认原因 | 正确处理 |
| --- | --- | --- |
| 外部探针 `QMT_SERVER_NOT_ALLOWED` | 券商不允许启动外部 XtQuant 服务 | 使用内置 Python 模式，不反复修改 VPS |
| `TypeError: ABCMeta object is not subscriptable` | Python 3.6 不支持 `collections.abc.Mapping[str, Any]` | 使用兼容的 `typing.Mapping`；当前代码已修复 |
| `IndentationError` 或 `SyntaxError` | 手工修改多行 `BRIDGE_DIR` 时留下残余代码 | 完整覆盖策略；命名管道版无需手工改代码 |
| `future feature annotations is not defined` | 把外部 `builtin_adapter.py` 错贴进 QMT | QMT 只复制 `builtin_strategy.py` |
| `PermissionError: Foribdden FileIO` | 券商客户端禁止内置策略文件 I/O | 使用当前命名管道版，不使用文件队列或外部文件加载入口 |
| 探针提示管道不存在或 `QMT built-in pipe is unavailable` | QMT/策略未运行，策略启动失败，或管道名不一致 | 先确认 `XtItClient` 进程和模型交易条目均在运行，再检查策略日志及双方 `agom_qmt_builtin_bridge` 配置；不要反复重试报单 |
| 管道存在但探针超时 | QMT 回调延迟或策略未处理队列 | 确认 `agom_poll` 已初始化并保持策略运行；可将超时调至 10 秒 |
| 探针提示账号不匹配 | 模型交易绑定账号与 Agent 配置不同 | 核对两边普通股票账号，不要切换成信用账号 |
| QMT 提示非法 `198.18.x.x` | Clash/Mihomo Fake IP/TUN 接管券商连接 | 按第 4 节配置直连和真实 DNS，重启 Clash/QMT |

2026-11-05 最终真实只读结果：`ready=true`，资产、持仓、委托、成交查询全部成功，返回 24 条持仓、0 条当日委托、0 条当日成交；`submitted_order=false`、`canceled_order=false`。客户端重启后，又以 5 个独立 Agent 进程连续重连并执行相同探针，5 次均为 `ready=true`、24 条持仓且未报撤单。原始脱敏报告保存在目标机联调目录 `.tmp/qmt-live-probe/builtin-read-probe.json` 和 `builtin-stability-probe-1.json` 至 `builtin-stability-probe-5.json`，该目录不作为正式交付制品。

同一事项的命名管道安全回归新增响应丢失后的同请求缓存重放、策略重启后 SQLite/券商备注恢复、成交事件幂等与撤单参数检查；相关 Agent/安装包完整文件最终 93 项通过。响应丢失重放只调用一次原生 `passorder`，重启恢复只查询券商事实。这些只读和仿真对端证据不替代券商仿真账户的真实报撤单与回调验收。

## 6. 后续分级验收与回滚

只读通过后仍按以下顺序，不跨级：

1. 保持 `dry_run=true`，完成 Fake Agent 和服务端合同验证；
2. 在券商仿真环境验收限价报单、拒单、部分/全部成交、撤单、断线和重启恢复；
3. 小额实盘逐单人工批准；
4. 连续运行和对账通过后，才评估受限自动执行。

内置 `passorder` 没有同步委托号返回值。Agent 使用 `userOrderId`/`m_strRemark` 查询 `m_strOrderSysID`；未查到时保留已提交但委托号为空的状态，由后续查询补齐。结果不明确时进入 `RECONCILIATION_REQUIRED`，禁止直接重报。

需要回滚时：停止 Agent 新单领取，停止 QMT 桥策略，将配置备份恢复或把 `qmt_trade_api` 改回 `xtquant`。已有未决订单必须先按券商委托和成交事实完成对账，不能用回滚操作撤销或改变券商已有订单。

接口定义以 [迅投 QMT 知识库](https://dict.thinktrader.net/?id=NF25nX) 为准；日常故障处理同时参考 [QMT Agent 运行手册](qmt-agent-runbook.md)。
