# ASH-03 自动止损止盈旧写账路径隔离（2026-10-23）

本批保留止损、止盈条件观察，将触发与执行确认分开；触发旧自动退出也只返回观察及阻断结果，不再直接新增 SELL 流水、改持仓或记录成交。手工账户兼容行为与 REAL 镜像保持原合同。正向合格自动卖出及 ASH-03 第七组整体验收继续开放。

观察价格须有精确证券身份、正有限非布尔数值、realtime/non-fallback 标记及 aware 源观测时间；未知、未来时钟及历史回退不可用，不另造本地新鲜度阈值。通知保留来源和原时间，明确没有提交自动卖出或确认平仓。Trailing 只允许更新最高值、源时间和 ORM 更新时间；未证明并发 CAS。

未知阶段不自动重试；已有成功观察与另一未知阶段组合为 partial，未知分母及写入数量保持 null，Task Monitor 的 business_success 为 false。盈亏运算移入小型纯 Domain 模块，原 Decimal 算法保持一致，比例为小数比率；没有向超过千行的既有 Domain 服务继续加代码。

| 同一 Python 候选的检查 | 实际结果 |
| --- | --- |
| PostgreSQL / SQLite | 六个完整模块各 83 passed，均 0 failure/error/skip；整批 327.735 / 1200 秒，7,485 项 Python 输入前后相同。 |
| Domain 覆盖 | 复用上述用例模块完整 36 项，9/9 有效行覆盖 100%；零分支，分支比例为不适用。该 36 项不另算新的独立用例集合。 |
| 类型 | 四个生产文件增量检查 0 新错误、0 历史错误；默认全库债务 0 errors / 0 files，未提高基线。 |
| 格式及边界 | 十个 Python 文件 Black/isort/Ruff、完整/增量架构及 audit、App 循环、治理与四个生产文件增长检查通过。 |
| 官方生成 | R9 八项命令全部通过，四份输出由官方工具生成；386.974 / 1200 秒。隔离候选 10,448 文件 / 7,484 Python；额外一项外来测试仅用于 Source 保全，不进入候选。 |
| 还原与采用 | 独立核对 10,403 个原始基线文件全部原样恢复，额外文件及残留锁为零；四份输出已采用，其他工作区改动和 Git 暂存标志保持。 |

测试使用合成行情及隔离数据库，只证明上述开发合同。生产账户 613 尚待主计划 §19.96 的真实九项验收；没有部署、启用生产配置或写生产账本/订单，production acceptance 为 null。开发提交 CI 与同 SHA 完整 RC/S6 另行验证。

旧 writer 的测试先真实写出 SELL Transaction、修改 Position 和 StopLossTrigger，随后完整账本不变断言失败；该 RED 为一个失败、零 error/skip，67.426 秒。最终 GREEN 的账本断言保留。

历史原件同批保留：R4 在 pytest 前因环境探针失败；首个 GREEN 为 81 passed / 2 个测试契约失败；初次类型检查有三个既有 Celery 装饰器 misc 注释缺失。修正后没有放宽业务断言或类型基线。旧 12 路径双库及 R8 通过只归历史候选。暂存检查发现文档尾部空 CRLF，修复只删除这两个字节，Python 输入和已通过的运行资格不变；最初 LF 假设的准备失败也保留。

| 身份与本机原件 | SHA-256 |
| --- | --- |
| 运行候选 candidate-final-domain.json | 64c30e5ae5688965a73393a34d5a55d20e071ad4f1e97fcc1433ce7e3a8d726b |
| 文档空行修正后 candidate-doc-final.json | a0d59f064fbed06c24ba492bf25257aa525a73453fca80d0f33f40211e9bcdca |
| 双库最终审计 | baee14965c06c5dbbe09e8f17fd860c82670ac932eebee0ff1b345da02902261 |
| R9 官方运行 receipt | 56c313f810923f5779810d4d9971a364927d945952ddaa191012e4639db73586 |
| 本机归档 `artifacts/ash03-automated-exit-2026-10-23/INDEX.json` | 8cfb6aa4c644590e9144c58c8546dda06e407851a8cc2fc8d5d2b9789f45bc03 |

原件位置、逐项哈希、实际控制器、输入、JUnit、日志与各历史候选身份见此单一归档索引；仅本机可用，未上传 Git 或远端。代码与生成输出的规范 Git tree 为 `5c438987369738db504c18504748db2b91f49bc0`；最后两个 Markdown 文件只补验收说明与主计划进度。

CI 兼容补记：开发提交 `f62f1c9d137b66d7cb54f983e9383b2924839b1d` 的双版本 Fast 各为 790 passed / 4 failed / 159 skipped；四个失败均为旧测试导入已移除的私有 `_MarketDataAdapter`。其余五项 CI 成功；Fast 原时限 No-DB 为 13,169 passed + 24 subtests，外层 117.33 / 120 秒。原失败保留，不重跑旧候选或拼接成发布资格。

本次仅迁移四个测试到当前默认工厂与 metadata 通道，验证逐证券身份、来源/观测时间、提供者异常，以及配置可用但无元数据时禁止标量回退；原通知测试类与 fixtures 的 AST 不变，生产 Python 未改。完整通知组件 15 项和止损用例 36 项同次通过，共 51 passed、零 failure/error/skip；使用隔离内存 SQLite、邮件关闭及内存邮件后端，HTTP 尝试为零，7,485 个 Python 输入前后一致。

本次审计 SHA-256 `ef76c4dfd7db195b243b1cbdc77965f965a770d0b8b53f2a20b7892c1b510414`，实际运行 40.881 / 300 秒；同一事项归档已追加原 CI 与本次结果，当前 INDEX SHA-256 `5acc889979c337b661b0da0219ea30dc7e1eb48335957d02f99f3cc2d7abdef3`，旧索引 `8cfb6aa4c644590e9144c58c8546dda06e407851a8cc2fc8d5d2b9789f45bc03` 原样留存。没有路径或模块变化，官方测试分类仍为 component，生成投影无需变化；新提交 CI、完整 RC/S6 和生产 613 验收仍须另行完成。
