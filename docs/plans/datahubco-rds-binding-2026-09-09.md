# DataHubCo RDS 数据中台绑定

用户提供的服务根地址为 `http://datahubco.com/app-api/openapi/v1/tushare`。
独立 provider 使用 `source_type=tushare`、`extra_config.tushare_request_mode=rest_path`；
凭据通过既有 ProviderCredentialStore 加密保存，不写入代码、文档或 extra_config。

该协议使用 GET、X-API-Key 请求头、下划线接口名到连字符资源名的转换。
不能作为标准 Tushare SDK POST 地址，也不能作为统一中继 POST 地址直接绑定。
传输由数据中台 tushare_client 负责，Alpha/Qlib 继续使用中台公开端口。
Admin、配置 API 与 TUI 创建/编辑均支持“RDS 数据服务”连接方式。

安全与完整性：凭据不进入查询参数；禁止自动重定向；独立 Session 不继承进程代理，
不设置全局 NO_PROXY=*。验证 fields/items 的表格结构，明确 has_more 的结果拒绝作为
完整历史返回（MODEL_MARKET_INCOMPLETE_RESULT），目前不自动分页。

2026-09-09 VPS 实测股票基础资料、600519.SH 的 9 月 7—8 日日线/复权因子、
交易日历和 000300.SH 指数日线均为 HTTP 200、业务 code=0。
这些探针不代表全市场数据覆盖、最新交易日完整性或 Alpha 评分恢复已经验收。
新增绑定不覆盖原 Tushare 或 AKShare 配置，保留中台一致性与新鲜度检查。

回滚：停用新增 provider；如需回滚传输补丁，恢复 hot-update 备份并重启 web/worker。
无数据库迁移、依赖变更或历史数据删除。

## 绑定验收

VPS provider id=4，名称 DataHubCo RDS，已启用，priority=0。
连接测试经正式用例执行并保存成功回执；列表显示“RDS 数据服务”、has_api_key=true，
不返回密钥。保持全局 AKShare 优先策略，Tushare 同类路由优先最近成功的 RDS。
直接经中台适配器取到 600519.SH 的 63 个交易日日线与复权因子（截至 9 月 8 日），
指数日线正常。Web/worker/beat 已同步传输补丁。

生产中台路由完整性验收仍被 MODEL_MARKET_SOURCE_CONFLICT 阻断：35 条重叠参考记录
来自 tencent，例如 2026-06-11 open=1244.096，而 RDS open=1272.12，差异约 2.25%。
尚未确定参考数据的复权口径；没有放宽 1% 阈值、改写旧参考记录或发布新 Alpha 评分。

代码热更新备份：`/opt/agomtradepro/manual-file-backups/20260909181759`。
增量 mypy（6 个生产文件）与全库 mypy 债务门禁均为 0；Ruff、Black、diff-check 通过。
传输回归 12 项通过；Admin/TUI/新传输组合回归 17 项通过；配置 API 回归 4 项通过，
覆盖 rest_path 创建、JSON 状态码/Content-Type 与凭据脱敏。部分传输用例在组合包中重复。
生产 HTTPS（验证证书）200；web/worker 文件哈希与发布目录一致；pyqlib=0.9.7。
