"""Seed definitions for macro indicator semantics and chart policies."""

from __future__ import annotations

from typing import Any

ALIAS_SCOPE = "macro_compat_alias"
FALLBACK_CHART_POLICY = "continuous_line"
DEFAULT_RESET_FREQUENCY = ""
DEFAULT_SEGMENT_BASIS = ""
DIRECT_INPUT_ALLOWED = "direct_allowed"
DERIVE_REQUIRED = "derive_required"
SEMANTICS_TO_CHART_POLICY = {
    "cumulative_level": "yearly_reset_bar",
    "monthly_level": "period_bar",
    "flow_level": "period_bar",
    "yoy_rate": "continuous_line",
    "mom_rate": "continuous_line",
    "rate": "continuous_line",
    "index_level": "continuous_line",
    "balance_level": "continuous_line",
    "level": "continuous_line",
}


def resolve_direct_input_policies(series_semantics: str) -> dict[str, str]:
    """Resolve whether a semantic class can feed regime/pulse directly."""

    normalized = str(series_semantics or "").strip()
    if normalized == "cumulative_level":
        return {
            "regime_input_policy": DERIVE_REQUIRED,
            "pulse_input_policy": DERIVE_REQUIRED,
        }
    return {
        "regime_input_policy": DIRECT_INPUT_ALLOWED,
        "pulse_input_policy": DIRECT_INPUT_ALLOWED,
    }


def resolve_chart_runtime_metadata(series_semantics: str) -> dict[str, str]:
    """Resolve the generic chart runtime metadata for one semantic class."""

    normalized = str(series_semantics or "").strip()
    if normalized == "cumulative_level":
        return {
            "chart_policy": "yearly_reset_bar",
            "chart_reset_frequency": "year",
            "chart_segment_basis": "period_delta",
        }
    return {
        "chart_policy": resolve_chart_policy(normalized),
        "chart_reset_frequency": DEFAULT_RESET_FREQUENCY,
        "chart_segment_basis": DEFAULT_SEGMENT_BASIS,
    }


def resolve_chart_policy(series_semantics: str) -> str:
    """Resolve the canonical chart policy for one semantic class."""

    normalized = str(series_semantics or "").strip()
    return SEMANTICS_TO_CHART_POLICY.get(normalized, FALLBACK_CHART_POLICY)


def merge_governance_extra(
    existing_extra: dict[str, Any] | None,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Merge runtime metadata and keep chart policy consistent with semantics."""

    merged = dict(existing_extra or {})
    merged.update(updates)
    series_semantics = str(merged.get("series_semantics") or "")
    merged.update(resolve_chart_runtime_metadata(series_semantics))
    merged.update(resolve_direct_input_policies(series_semantics))
    return merged


def is_direct_consumer_input_allowed(
    extra: dict[str, Any] | None,
    *,
    consumer: str,
) -> bool:
    """Return True when one macro series may feed the consumer directly."""

    metadata = dict(extra or {})
    series_semantics = str(metadata.get("series_semantics") or "")
    policies = resolve_direct_input_policies(series_semantics)
    key = f"{consumer}_input_policy"
    policy = str(metadata.get(key) or policies.get(key) or DIRECT_INPUT_ALLOWED).strip()
    return policy == DIRECT_INPUT_ALLOWED


def _row(
    *,
    name_cn: str,
    description: str,
    semantics: str,
    paired_indicator_code: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload_extra = {
        "series_semantics": semantics,
        "paired_indicator_code": paired_indicator_code,
    }
    if extra:
        payload_extra.update(extra)
    payload_extra.update(resolve_chart_runtime_metadata(semantics))
    return {
        "name_cn": name_cn,
        "description": description,
        "extra": payload_extra,
    }


def _alias_row(
    *,
    name_cn: str,
    description: str,
    semantics: str,
    alias_of_indicator_code: str,
    paired_indicator_code: str = "",
) -> dict[str, Any]:
    return _row(
        name_cn=name_cn,
        description=description,
        semantics=semantics,
        paired_indicator_code=paired_indicator_code,
        extra={
            "alias_of_indicator_code": alias_of_indicator_code,
            "governance_status": "alias_only",
            "governance_scope": ALIAS_SCOPE,
            "governance_sync_supported": False,
        },
    )


INDICATOR_METADATA_UPDATES: dict[str, dict[str, Any]] = {
    "CN_BLAST_FURNACE": _row(
        name_cn="高炉开工率",
        description=(
            "当前公开源使用钢铁行业指数周频代理高炉开工率，运行时应按指数水平序列理解，"
            "不可按累计值或同比序列解释。"
        ),
        semantics="index_level",
    ),
    "CN_BOND_10Y": _row(
        name_cn="10年期国债收益率",
        description="日度收益率水平值口径，用于连续观察长端利率变化。",
        semantics="rate",
    ),
    "CN_BOND_1Y": _row(
        name_cn="1年期国债收益率",
        description="日度收益率水平值口径，用于连续观察短端利率变化。",
        semantics="rate",
    ),
    "CN_BOND_2Y": _row(
        name_cn="2年期国债收益率",
        description="日度收益率水平值口径，用于连续观察中短端利率变化。",
        semantics="rate",
    ),
    "CN_BOND_5Y": _row(
        name_cn="5年期国债收益率",
        description="日度收益率水平值口径，用于连续观察中长端利率变化。",
        semantics="rate",
    ),
    "CN_BOND_ISSUANCE": _row(
        name_cn="债券发行额",
        description="月度债券发行额口径，属于当期流量值，不应与跨月累计趋势线混用。",
        semantics="flow_level",
    ),
    "CN_CCFI": _row(
        name_cn="中国出口集装箱运价指数",
        description="周频运价指数水平值口径，用于连续观察外贸航运景气度。",
        semantics="index_level",
    ),
    "CN_CORP_YIELD_AA": _row(
        name_cn="AA级企业债收益率",
        description="日度企业债收益率水平值口径，用于连续观察信用融资成本。",
        semantics="rate",
    ),
    "CN_CORP_YIELD_AAA": _row(
        name_cn="AAA级企业债收益率",
        description="日度企业债收益率水平值口径，用于连续观察高等级信用融资成本。",
        semantics="rate",
    ),
    "CN_CPI_CORE": _row(
        name_cn="核心CPI同比增速",
        description="月度同比增速口径，用于观察剔除食品和能源后的核心通胀方向。",
        semantics="yoy_rate",
    ),
    "CN_CPI_FOOD": _row(
        name_cn="食品CPI同比增速",
        description="月度同比增速口径，用于观察食品价格通胀方向。",
        semantics="yoy_rate",
    ),
    "CN_CPI_MOY": _alias_row(
        name_cn="CPI环比",
        description="兼容别名代码，canonical 指标为 CN_CPI_NATIONAL_MOM；不再单独维护独立时序。",
        semantics="mom_rate",
        alias_of_indicator_code="CN_CPI_NATIONAL_MOM",
        paired_indicator_code="CN_CPI",
    ),
    "CN_CPI_NATIONAL_MOM": _row(
        name_cn="全国CPI环比增速",
        description="月度环比增速口径，用于观察居民消费价格的短期边际变化。",
        semantics="mom_rate",
        paired_indicator_code="CN_CPI",
    ),
    "CN_CPI_RURAL_MOM": _row(
        name_cn="农村CPI环比增速",
        description="月度环比增速口径，用于观察农村居民消费价格的短期边际变化。",
        semantics="mom_rate",
    ),
    "CN_CPI_RURAL_YOY": _row(
        name_cn="农村CPI同比增速",
        description="月度同比增速口径，用于观察农村居民消费价格涨幅方向。",
        semantics="yoy_rate",
    ),
    "CN_CPI_URBAN_MOM": _row(
        name_cn="城市CPI环比增速",
        description="月度环比增速口径，用于观察城市居民消费价格的短期边际变化。",
        semantics="mom_rate",
    ),
    "CN_CPI_URBAN_YOY": _row(
        name_cn="城市CPI同比增速",
        description="月度同比增速口径，用于观察城市居民消费价格涨幅方向。",
        semantics="yoy_rate",
    ),
    "CN_CREDIT_SPREAD": _row(
        name_cn="信用利差(AA-AAA)",
        description="日度信用利差口径，用于连续观察信用环境松紧变化。",
        semantics="rate",
    ),
    "CN_DR007": _row(
        name_cn="DR007 7天回购利率",
        description="日度回购利率水平值口径，用于连续观察银行间流动性价格。",
        semantics="rate",
    ),
    "CN_EXPORT": _alias_row(
        name_cn="出口额",
        description="兼容别名代码，canonical 指标为 CN_EXPORTS；不再单独维护独立时序。",
        semantics="monthly_level",
        alias_of_indicator_code="CN_EXPORTS",
        paired_indicator_code="CN_EXPORT_YOY",
    ),
    "CN_FX_CENTER": _row(
        name_cn="人民币中间价",
        description="日度人民币汇率中间价水平值口径，应按汇率水平序列理解，不属于涨跌幅。",
        semantics="level",
    ),
    "CN_IMPORT": _alias_row(
        name_cn="进口额",
        description="兼容别名代码，canonical 指标为 CN_IMPORTS；不再单独维护独立时序。",
        semantics="monthly_level",
        alias_of_indicator_code="CN_IMPORTS",
        paired_indicator_code="CN_IMPORT_YOY",
    ),
    "CN_INDUSTRIAL_PROFIT": _row(
        name_cn="工业企业利润累计值",
        description="月度年初累计利润总额口径，跨年会自然重置，不适合直接跨年连成连续趋势线。",
        semantics="cumulative_level",
    ),
    "CN_LOAN_RATE": _row(
        name_cn="金融机构贷款利率",
        description="月度贷款利率水平值口径，用于连续观察实体融资成本。",
        semantics="rate",
    ),
    "CN_LPR": _row(
        name_cn="LPR 贷款市场报价利率",
        description="月度LPR利率水平值口径，用于连续观察贷款定价基准变化。",
        semantics="rate",
    ),
    "CN_M0": _row(
        name_cn="M0 流通中现金余额",
        description="月度余额口径，反映流通中现金存量，不是同比增速。",
        semantics="balance_level",
    ),
    "CN_M1": _row(
        name_cn="M1 狭义货币供应量余额",
        description="月度余额口径，反映狭义货币存量，不是同比增速。",
        semantics="balance_level",
    ),
    "CN_NEW_CREDIT": _row(
        name_cn="新增信贷",
        description="月度新增信贷口径，属于当期流量值，不应与存量余额序列混用。",
        semantics="flow_level",
    ),
    "CN_NEW_HOUSE_PRICE": _row(
        name_cn="新房价格同比变动",
        description="当前按新房价格指数减 100 后入库，代表同比变动幅度，应按同比增速序列理解。",
        semantics="yoy_rate",
    ),
    "CN_NHCI": _row(
        name_cn="南华商品指数",
        description="日度商品指数水平值口径，用于连续观察工业品与大宗商品价格环境。",
        semantics="index_level",
    ),
    "CN_NON_MAN_PMI": _row(
        name_cn="非制造业PMI",
        description="月度PMI指数水平值口径，用于连续观察服务业与建筑业景气度。",
        semantics="index_level",
    ),
    "CN_OIL_PRICE": _row(
        name_cn="成品油价格",
        description="调价时点价格水平值口径，用于连续观察成品油价格水平。",
        semantics="level",
    ),
    "CN_PBOC_NET_INJECTION": _row(
        name_cn="央行公开市场净投放额",
        description="日度公开市场净投放额口径，正值为净投放，负值为净回笼，属于流量值。",
        semantics="flow_level",
    ),
    "CN_PMI": _row(
        name_cn="PMI 制造业采购经理指数",
        description="月度PMI指数水平值口径，用于连续观察制造业景气度。",
        semantics="index_level",
    ),
    "CN_PMI_EMPLOYMENT": _row(
        name_cn="PMI从业人员指数",
        description="月度PMI分项指数水平值口径，用于连续观察制造业用工景气度。",
        semantics="index_level",
    ),
    "CN_PMI_INVENTORY": _row(
        name_cn="PMI产成品库存指数",
        description="月度PMI分项指数水平值口径，用于连续观察制造业库存变化。",
        semantics="index_level",
    ),
    "CN_PMI_MANUFACTURING": _alias_row(
        name_cn="制造业PMI",
        description="兼容别名代码，canonical 指标为 CN_PMI；不再单独维护独立时序。",
        semantics="index_level",
        alias_of_indicator_code="CN_PMI",
    ),
    "CN_PMI_NEW_ORDER": _row(
        name_cn="PMI新订单指数",
        description="月度PMI分项指数水平值口径，用于连续观察制造业需求强弱。",
        semantics="index_level",
    ),
    "CN_PMI_NON_MANUFACTURING": _alias_row(
        name_cn="非制造业PMI",
        description="兼容别名代码，canonical 指标为 CN_NON_MAN_PMI；不再单独维护独立时序。",
        semantics="index_level",
        alias_of_indicator_code="CN_NON_MAN_PMI",
    ),
    "CN_PMI_PRODUCTION": _row(
        name_cn="PMI生产指数",
        description="月度PMI分项指数水平值口径，用于连续观察制造业生产强弱。",
        semantics="index_level",
    ),
    "CN_PMI_PURCHASE": _row(
        name_cn="PMI采购量指数",
        description="月度PMI分项指数水平值口径，用于连续观察制造业采购强弱。",
        semantics="index_level",
    ),
    "CN_PMI_RAW_MAT": _row(
        name_cn="PMI原材料库存指数",
        description="月度PMI分项指数水平值口径，用于连续观察原材料库存变化。",
        semantics="index_level",
    ),
    "CN_POWER_GEN": _row(
        name_cn="发电量",
        description="当前公开源使用全社会用电量月度值作为发电量代理序列，属于当期量级口径。",
        semantics="monthly_level",
    ),
    "CN_PPIRM": _row(
        name_cn="PPIRM同比增速",
        description="月度同比增速口径，用于观察工业生产资料购进价格变化方向。",
        semantics="yoy_rate",
    ),
    "CN_REALESTATE_INVESTMENT_YOY": _row(
        name_cn="房地产开发投资同比增速",
        description="月度同比增速口径，用于观察房地产开发投资变化方向。",
        semantics="yoy_rate",
    ),
    "CN_RESERVE_RATIO": _row(
        name_cn="金融机构存款准备金率",
        description="调整时点的准备金率水平值口径，用于连续观察货币政策约束强弱。",
        semantics="rate",
    ),
    "CN_REVERSE_REPO": _row(
        name_cn="逆回购利率",
        description="日度逆回购利率水平值口径，用于连续观察公开市场操作价格。",
        semantics="rate",
    ),
    "CN_RMB_DEPOSIT": _row(
        name_cn="人民币存款余额",
        description="月度人民币存款余额口径，属于存量序列，不应按当期流量值理解。",
        semantics="balance_level",
    ),
    "CN_RMB_LOAN": _row(
        name_cn="人民币贷款新增额",
        description="月度新增人民币贷款口径，属于当期流量值，不应与贷款余额混用。",
        semantics="flow_level",
    ),
    "CN_RRR": _row(
        name_cn="存款准备金率",
        description="调整时点的准备金率水平值口径，用于连续观察货币政策约束强弱。",
        semantics="rate",
    ),
    "CN_SCFI": _row(
        name_cn="上海出口集装箱运价指数",
        description="周频运价指数水平值口径，用于连续观察出口航运价格变化。",
        semantics="index_level",
    ),
    "CN_SHIBOR": _row(
        name_cn="SHIBOR 上海银行间同业拆放利率",
        description="日度同业拆放利率水平值口径，用于连续观察银行间资金价格。",
        semantics="rate",
    ),
    "CN_STOCK_MARKET_CAP": _row(
        name_cn="股票总市值",
        description="月度股票总市值口径，属于存量规模序列，不是涨跌幅。",
        semantics="balance_level",
    ),
    "CN_TERM_SPREAD_10Y1Y": _row(
        name_cn="期限利差(10Y-1Y)",
        description="日度期限利差口径，用于连续观察收益率曲线陡峭程度。",
        semantics="rate",
    ),
    "CN_TERM_SPREAD_10Y2Y": _row(
        name_cn="期限利差(10Y-2Y)",
        description="日度期限利差口径，用于连续观察收益率曲线陡峭程度。",
        semantics="rate",
    ),
    "CN_TRADE_BALANCE": _row(
        name_cn="贸易差额",
        description="月度贸易差额口径，属于当期流量值，不应与累计值或同比序列混用。",
        semantics="flow_level",
    ),
    "CN_UNEMPLOYMENT": _row(
        name_cn="城镇调查失业率",
        description="月度失业率水平值口径，用于连续观察就业压力变化。",
        semantics="rate",
    ),
    "USD_INDEX": _row(
        name_cn="美元指数",
        description="日度美元指数水平值口径，用于连续观察美元强弱。",
        semantics="index_level",
    ),
    "US_BOND_10Y": _row(
        name_cn="美国10年期国债收益率",
        description="日度收益率水平值口径，用于连续观察美债长端利率变化。",
        semantics="rate",
    ),
    "VIX_INDEX": _row(
        name_cn="VIX波动率指数",
        description="日度波动率指数水平值口径，用于连续观察风险偏好与市场波动。",
        semantics="index_level",
    ),
}
