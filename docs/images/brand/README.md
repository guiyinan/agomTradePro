# AgomTradePro 图标

当前采用阿狗像素版：`agomtradepro-icon-v2-pixel-ashare.png`。用户于 2026-10-28 确认将它用于系统 favicon 与宣传视频；原始角色参考现保存为本目录的 [agom.png](agom.png)。

- 形象：金色垂耳、圆框眼镜、奶油色口鼻；保留像素风。
- 交易标识：右下角 K 线徽标，采用 A 股红涨、绿跌配色。
- 原始品牌图：本目录的透明 PNG，1254 × 1254。
- 系统用图：`static/img/brand/agomtradepro.png`，512 × 512 透明 PNG。
- 浏览器图标：`static/img/brand/agomtradepro.ico`，包含 16、32、48、64、128、256 像素六种尺寸。
- 导出方式：从确认的 PNG 使用 nearest-neighbor 缩放，保留像素轮廓；ICO 各层使用对应尺寸的独立导出帧。

Classic 共用基座与 `/tui/` shell 显式引用 ICO 静态资源；兼容入口 `/favicon.ico` 重定向到 Django 静态存储生成的地址，生产环境通过正常的 `collectstatic` 流程发布。此次变更不执行 VPS 部署。

已确认像素图标及其生成提示词保留在本目录供追溯。当前视频口播、分镜及全片风险提示见 [150 秒工作流版文案](../../video/agomtradepro-workflows-150s-vertical-v2.md)；[60 秒首版文案](../../video/agomtradepro-60s-vertical-intro.md) 保留供对照。

## 本地验证（2026-10-28）

- `pytest tests/component/test_core_favicon.py`：5 项通过，覆盖匿名访问、静态资源 MIME、两套页面引用及 ICO 尺寸。
- `check_mypy_regression.py core/urls.py`：0 新增类型错误。
- Black、isort、Ruff 定向检查及 `web_template_migration_inventory.py --check` 通过；迁移矩阵只同步两份宿主模板的内容哈希和静态资源列表。
- 首次全生产范围 `check_mypy_debt_ceiling.py` 未通过：当时工作区 `apps/data_center/application/price_response_capture.py:90` 存在一处 `no-any-return`，不属于本次 favicon 改动。
- 提交前重新检查：favicon 5 项测试、`core/urls.py` 增量 mypy 与模板清单检查通过。全量类型债务检查仍未通过，当前阻断来自其他未提交事项：`apps/simulated_trading/domain/initial_position_mark_policy.py:181` 的 `redundant-cast`，以及 `apps/simulated_trading/infrastructure/published_price_initial_position_mark_reader.py:28,167` 的两处 `attr-defined`。本次不提交这些业务文件，也未改动类型债务基线。

上述结果是本地开发验证，不代表 VPS 已部署或发布资格通过。
