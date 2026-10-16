# 交易日历采集、预览、确认与当前读取合同

本文描述内部 Application 操作合同与精确准备仓储。HTTP/TUI、真实采集配置和普通模拟/回测消费者另行验收；这四个用例本身不是已上线的用户功能。

## 操作输入与结果

`CaptureExchangeCalendarSnapshotUseCase` 只接受明确的交易所、起止日期，通过注入的来源端口返回已保存快照的完整引用。调用者不能传入凭据、数据库 alias、源时钟或发布状态。结果保留原响应完成与首次入库时刻；未知的上游发布时间保持空。捕获不会发布或移动指针。

`PreviewCalendarPublicationUseCase` 只接受完整快照引用和上游已验证的发布主体。准备仓储从持久化原文、事实、唯一活动合同/策略和当前指针重建证据，Application 在服务器知识截止点重新生成 seal。预览返回合同/schema/策略完整身份、显式响应 TTL、完整 CAS、activation、内容摘要、原知识时钟和过期时刻；不向调用者接受或信任自编 seal。

`ConfirmCalendarPublicationUseCase` 接受预览引用、身份、原 CAS、activation 和摘要的机器回传。每次确认重新读取持久证据、目录与当前指针；配置变化、来源过期、范围错配或其他赢家使确认阻断。`preview_hash` 是无密钥内容校验和，只用于检测输入变化，不是签名、权限凭据或“曾预览过”的证明。授权始终由实时 Session 和精确发布权提供。

确认端口必须接既有 `PublishExchangeCalendarSnapshotUseCase`，不能直接绕到仓储。它继续执行正式 CAS、原 actor 当前权限、Audit/outbox 配对及提交前 lease/TTL 检查。调用方必须让拥有唯一外层事务的 authority context 成功退出，再向外部返回确认结果。

`ReadCurrentCalendarUseCase` 只接受明确 dataset 与 exchange，由注入的服务器 clock 产生截止点；结果须属于请求范围并保留该截止点。没有 current 时返回空，不从 latest、历史发布或其他范围补齐。上游入口负责读取访问授权，普通参考读取不要求原发布者继续持有发布权。

## 重试与存储身份

首次或 forward 确认成功后，原请求可重试精确当前赢家：原预览校验和仍使用原 CAS，正式发布用例接收锁内实际 current CAS。只有 publication hash 和 activation 都匹配的当前赢家可走此分支；不同 actor、历史赢家、不同 activation、跨 dataset/publication-key 的原 CAS 继续阻断。新预览遇到同一 current 内容时复用其 activation。

仓储可以重新分配成员行 ID 和其所属 publication ID。确认回执通过 Domain 的完整证据等价函数比较，只有这两个编码明确排除的存储 ID 可不同；其他 seal 证据、activation、Audit actor 与数据库 alias 必须相符。不能只比较摘要字符串，也不能用 dataclass 全等误拒合法存储分配。

## 精确准备与事务

`DjangoFormalExchangeCalendarPublicationRepository.load_exact(reference, known_at=...)` 加入调用方唯一外层事务，不自己开启 nested atomic。PostgreSQL 要求 READ COMMITTED，并依次取得排序后的目录 SHARE fence、范围锁、RawPayload/事实锁和完整 current 锁。目录在 SHARE 之后使用普通 SELECT，避免和既有先锁行后写入的目录管理操作形成锁升级环。

准备阶段重解析精确保留响应、验证完整快照引用和两类知识时刻、重算实际事实行摘要、校验唯一活动目录和旧 current 的完整 Audit 配对。它不会创建 publication/member/coverage/pointer/event/outbox，也不修补损坏的历史。旧 current 的完整性核验不要求其源 TTL 仍有效；即将发布的新来源仍须有效。

正式存储、来源时钟、配置版本、撤权与失败回滚的更底层约束见[正式发布合同](a-share-formal-calendar-publication.md)。本合同所有输出保持 `must_not_execute=True`；不证明盘中停牌、交易阶段、证券状态、涨跌幅边界、股份结算或订单许可。

## 验证边界

本切片的测试包括纯 Application 端口组合、精确准备 SQLite 组件，以及主代理独占的本地原生 PostgreSQL。原生组合使用真实 Session 授权、准备仓储、正式 Application publisher 和 Core/Audit bridge，验证原确认重试、撤权后普通读取、配置漂移及两种目录锁顺序。

实际结果、源 SHA 与失败原件记录在实施计划对应阶段和独立检查点中。纯用例、SQLite 与 PostgreSQL 测试可能重叠，不能累计成唯一用例数；本地夹具不代表生产、真实 Provider、CI/S6 或券商验收。
