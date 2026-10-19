# F6 失败结果状态断言修复

实际远端 Fast Feedback `39230236531` 的 Node 回归为 175 passed / 1 failed：失败分支仍在等待“读取完成”，与已采用的失败反馈“读取失败，请检查结果后重试”不一致。本批只按已有 mock outcome 修正这一处等待，成功分支、原超时、F6 关闭时不请求、F9 展开/聚焦、第二次提交和 300ms 防重复断言均保留；生产代码未变。

修复后 targeted 2 项及三个正式 Node 测试目录的全部 176 项均通过，0 failure/error/skip。driver JSON 错按 testsuite 属性计数为 0，实际数量已由独立审查直接解析 testcase，原错误汇总保留。输入是 f30 加六个 Alpha overlay 的私有副本，Node 测试输入与基准 `3b11ed5703e4a9fce55e66ad0de92e92f02e9a05` 匹配；不宣称最终干净候选通过。

命令、源码/补丁身份、独立审查、原始 CI 失败及 XML 见[证据索引](tui-rc-node-f6-status-evidence-2026-10-19.json)。原件逐项读回验证后存于仓库外本机持久归档，未上传到远端。最终同 SHA RC/S6 仍待完成；本轮不部署。
