# TUI 股票筛选阻断与操作反馈修复

股票筛选在 HTTP 200 返回业务阻断时，普通界面此前可能把空列表显示为完成。此次仅将明确的 `success=false`、`status=blocked`、`must_not_use_for_decision=true` 且 HTTP 2xx 的响应投影为阻断；没有完整证据的失败、HTTP 错误及真实成功空结果各自保留原语义。普通投影不暴露 owner 的原始错误或发布门禁明细。

主结果和 dashboard 面板共用失败/阻断反馈；确认后仍受阻时不显示完成，也移除此前保存的任务完成标记。正常成功、二次确认和列表刷新均有回归覆盖。此批不改变股票池 partial 契约或 A 股研究快照格式化器。

私有输入的四文件最小 Python 回归 417 项通过，增量 mypy 和债务门禁通过；5 项实际 Node 浏览器反馈/进度用例通过。另以 A 股 `8f6c3afc2a69133e161393017642fdbd9cf3d3b6` 的精确格式化器覆盖私有基线，正常初始化 memory SQLite 的 Django registry，真实 Service dispatch 和既有格式化器共 26 项通过，保留零值、partial 覆盖和不可决策状态。它们是有精确源码绑定的局部验证，不是最终候选 RC/S6。

R3 中错误的 dashboard DOM 断言、缺 Django registry 的导入失败、首轮不完整 dispatch 测试夹具的错误及恢复记录均保留。未通过增加超时、跳过、改权限、返回虚假数据或改写失败原件取得通过。

原件保存在本机仓库外的持久归档；完整路径、逐文件哈希、实际输入及命令见[证据索引](tui-rc-blocked-feedback-evidence-2026-10-19.json)。归档未上传，不表示远端持有。最终固定候选仍需完整回归、同 SHA RC 与全新 S6。本轮未部署、未启动观察 T0，TUI-02 未关闭。
