# 快速反馈浏览器测试选择修复

候选 cddd 的 Fast Feedback 在 Python 3.11 和 3.13 均为 74 passed / 43 setup errors。直接变更的 Signal 浏览器用例被加入普通 pytest，测试所需的 localhost:8000 应用服务器没有启动，登录夹具连接被拒绝；这 43 项没有进入测试主体，不能当作业务功能失败或通过。

根因是 ci-only 和 shared-only 的 logic_guardrails 提前返回分支漏用了现有目标过滤器。此次仅在这两处复用该过滤器，保留普通 profile、其他模块选择及既有核心护栏。完整 RC 继续由 live-server wrapper 执行全部 UAT，要求无跳过及至少 20 项，不降低发布门槛。

新增四项契约先产生四个失败 subtest，修复后全部 67 项选择器单测通过；实际 f30..cddd CLI 不再选入未托管浏览器路径。格式、增量类型和债务检查的真实结果及独立复核见[证据索引](tui-rc-ci-selector-evidence-2026-10-19.json)。原始失败、日志和源码保存在本机仓库外归档，未上传到远端；这些私有验证不替代最终同 SHA RC/S6。本轮不部署。
