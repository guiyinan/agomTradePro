# QMT 整体桥：用户、服务器绑定与行情采集

交易与行情共用 `qmt_agent/` 安装包，在独立进程中运行；交易状态库与行情发件箱分开。行情凭证不能下单，交易凭证不能上传行情。现有交易接入与停止规则继续见 [运行手册](qmt-agent-runbook.md)。

## 用户操作

1. 登录目标服务器，在 TUI 的“个人资料与交易设置”选择“绑定我的 QMT 桥”。填写本地桥名称及资产目录中的采集代码，用逗号分隔。系统绑定当前登录用户，不接受另填用户 ID。
2. 复制服务器地址、桥名称、绑定编号和一次性配对码。配对码十分钟有效，只能使用一次；凭证不放入命令行、配置明文或日志。
3. Windows 上启动有行情权限的 QMT，使用现有安装包的行情模式安装：

```powershell
.\Install.ps1 -PythonExe "C:\Python311\python.exe" -ServerUrl "https://your-server.example" -QmtRoot "D:\qmt" -MarketOnly -RegisterTask
```

行情模式不要求系统交易账户或券商账户编号，不改已有交易配置。仍需要与券商兼容的 `xtquant`；若锁定包在目标机器不可导入，应先处理依赖/兼容性，不能忽略安装失败。

4. 在安装目录执行同一 Agent 的配对入口；终端会隐式输入配对码：

```powershell
.\runtime\Scripts\python.exe -m qmt_agent.main --bridge --state-dir .\market-state --pair --server "https://your-server.example" --agent-id "my-qmt"
```

服务器地址必须与创建配对码的地址一致。凭证以 Windows 当前用户 DPAPI 加密保存，任务计划必须使用同一 Windows 用户。配对只绑定服务器和用户，不自动批准公共行情供数。

5. 管理员在“QMT 接入与设置”选择“批准 QMT 行情接入”，填写绑定编号、已启用的 QMT 数据源编号及经目标券商核验的快照/日线成交量转股数倍率。倍率无默认猜测值；已有数据后不允许原地改变单位口径。一个数据源只能绑定一个桥。
6. 启动行情采集，先检查单次回执，再常驻运行：

```powershell
.\runtime\Scripts\python.exe -m qmt_agent.main --bridge --state-dir .\market-state --once
.\runtime\Scripts\python.exe -m qmt_agent.main --bridge --state-dir .\market-state
```

在“我的 QMT 桥”核对配对/采集状态、源观测时间和最近批次写入回执。心跳成功不等于行情新鲜。默认只支持不复权快照及日线，源成交金额契约为 CNY，资产必须是目录中已启用的 CNY 资产。

## 日线补采与独立暂停

补采每次最多 31 个已结束自然日，不接受当日日线；按批次持久化后上传。补采与实时采集不要同时使用同一个行情状态目录运行，使用同一进程按阶段完成。

```powershell
.\runtime\Scripts\python.exe -m qmt_agent.main --bridge --state-dir .\market-state --backfill-start 2026-08-01 --backfill-end 2026-08-31
```

“暂停行情采集”保留配对和缓冲；“恢复行情采集”要求已经完成管理员审批。也可在 `market-state` 创建 `PAUSE_MARKET` 文件暂停，删除后恢复。交易 `STOP` 和行情暂停分别生效；停止整个进程后仍保留本地发件箱。

凭证有效期为 90 日。到期、丢失或配对回包丢失时，在服务器使用“重新配对本地桥”，旧行情凭证立即失效且采集暂停。使用相同服务器、桥名称和状态目录，执行以上配对命令，将 `--pair` 替换为 `--repair`，再在服务器恢复采集。修复不能更换服务器或绑定编号；换服务器需新状态目录，避免把旧缓冲发往新服务器。

“撤销本地桥绑定”永久停止该绑定。卸载时默认保留行情/交易状态；删除状态前应处理未确认批次和交易未决记录。

## 数据边界与验收

- 行情先进入数据中台事实表，保留源时间、原始批次、单位倍率和接收时间；不直接激活全市场 current Publication。
- Provider 读取桥事实，不在 VPS 加载 `xtquant`；过期快照返回空集，继续现有备用源流程。源一致性与决策发布仍受现有门禁约束。
- 相同批次重试返回同一持久化回执；相同源观测发生内容冲突返回冲突，不覆盖旧事实。日线更正需要后续显式审计修复流程。
- 全批次校验和事务提交；失败批次不部分写入。网络错误保留原批次与时间戳重试。本地缓冲有界，在已有缓冲发送完成前不继续增加采集。
- 仓库自动测试不能替代国金权限、客户端会话、实际字段单位、交易日覆盖率和连续运行验收。默认不自动提高 QMT 数据源优先级，也不解除实盘门禁。

部署迁移：`python manage.py migrate`。服务端与 Agent 代码需一起发布；生产启用前按开发计划 QB0/QB5 保存真实只读与连续运行证据。
