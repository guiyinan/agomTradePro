# Share 模块 Application 架构整改（2026-05-01）

> 日期: 2026-05-01  
> 范围: `apps/share/application/*`, `apps/share/infrastructure/*`, `apps/share/tests/*`

## 背景

`share` 模块此前存在一条明显的架构绕行路径：

1. `apps/share/infrastructure/orm_handles.py` 暴露裸 ORM manager。
2. `apps/share/application/use_cases.py` 直接调用 `.get()/.filter()/.create()/.save()/.delete()`。
3. `apps/share/application/interface_services.py` 直接遍历 `account.positions` / `account.trades` 反向关系。

这违反了项目四层架构中 “Application 不直接碰 ORM” 的硬约束，也使 CI 护栏很难对真实依赖方向建立可信基线。

## 本次改动

### 1. 建立显式 repository protocol

- 新增 `apps/share/domain/interfaces.py`
- 定义：
  - `ShareApplicationRepositoryProtocol`
  - `ShareInterfaceRepositoryProtocol`
  - `ShareOwnedAccountSnapshot`
  - `ShareOwnedPositionSnapshot`
  - `ShareOwnedTradeSnapshot`

Application 层从“直接拿 manager 干活”改为“依赖 protocol + provider factory”。

### 2. Application 用例去 ORM

- `apps/share/application/use_cases.py` 不再导入：
  - `apps.share.infrastructure.models`
  - `apps.share.infrastructure.repositories`
  - `apps.share.infrastructure.orm_handles`
- `ShareLinkUseCases / ShareSnapshotUseCases / ShareAccessUseCases` 改为通过可注入 repository 执行持久化。
- 分享链接更新、撤销、删除、快照创建、访问日志聚合全部下沉到 Infrastructure repository。

### 3. Interface 辅助服务去反向关系遍历

- `apps/share/application/interface_services.py`
- 账户快照构造改为通过 repository 获取：
  - 账户摘要 DTO
  - 持仓 DTO 列表
  - 交易 DTO 列表

这样 Application 不再直接写 `account.positions.all()` / `account.trades.all()`。

### 4. 删除 manager alias 绕行文件

- 删除 `apps/share/infrastructure/orm_handles.py`

这一步的目的不是“文件整理”，而是消除一条能长期规避架构扫描的逃逸路径。

## 行为约束变化

- `ShareLinkUseCases.create_share_link()` 现在会同时校验：
  - owner 用户存在
  - account 存在且属于 owner

此前该用例只校验账户存在，不校验归属，属于权限边界缺口。

## 验收点

- `apps/share/application/use_cases.py` 不再直接出现 ORM manager 调用。
- `apps/share/application/use_cases.py` 不再依赖 `orm_handles.py`。
- `apps/share/application/interface_services.py` 不再直接遍历反向关系 manager。
- `apps/share/tests/test_use_cases.py` 新增 owner/account 归属校验覆盖。
