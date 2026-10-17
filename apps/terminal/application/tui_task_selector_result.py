"""Portable, bounded projections for the TUX09 selection panels.

The functions in this module accept one decoded owner response and keep only
the fields declared by the task metadata.  They never fetch a URL, infer a
currency, or turn an owner error into a generic raw detail view.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, TypedDict, cast

SelectorStatus = Literal["已读取"]


class TuiColumn(TypedDict):
    """One portable datagrid column."""

    key: str
    label: str


class TuiPager(TypedDict):
    """The pagination facts consumed by the existing datagrid renderer."""

    client_side: bool
    pagination_mode: Literal["page"]
    page: int
    page_size: int
    total_rows: int
    total_pages: int
    has_previous: bool
    has_next: bool


class TuiNextStep(TypedDict):
    """A bounded follow-up hint; selector results currently publish none."""

    label: str
    hint: str


class TuiAccountSelectorRow(TypedDict):
    """Safe account fields from the authenticated user's active account list."""

    account_name: str
    account_type: str
    account_id: int


class TuiPortfolioSelectorRow(TypedDict):
    """Safe portfolio fields in the metadata column order."""

    name: str
    is_active: bool
    base_currency_code: str | None
    base_currency_name: str | None
    id: int


class TuiAccountDatagridView(TypedDict):
    """Portable account datagrid view."""

    kind: Literal["datagrid"]
    title: str
    status: SelectorStatus
    columns: list[TuiColumn]
    rows: list[TuiAccountSelectorRow]
    pager: TuiPager
    empty_message: str
    empty_guidance: list[str]
    next_steps: list[TuiNextStep]
    business_summary: str


class TuiPortfolioDatagridView(TypedDict):
    """Portable portfolio datagrid view."""

    kind: Literal["datagrid"]
    title: str
    status: SelectorStatus
    columns: list[TuiColumn]
    rows: list[TuiPortfolioSelectorRow]
    pager: TuiPager
    empty_message: str
    empty_guidance: list[str]
    next_steps: list[TuiNextStep]
    business_summary: str


class TuiSelectorMessageView(TypedDict):
    """Portable blocked message for transport or owner-shape failures."""

    kind: Literal["message"]
    title: str
    status: Literal["已阻断"]
    message: str
    outcome: Literal["blocked"]
    blocking_reason: str
    business_summary: str
    next_steps: list[TuiNextStep]


TuiSelectorResult = TuiAccountDatagridView | TuiPortfolioDatagridView | TuiSelectorMessageView

_ACCOUNT_COLUMNS: tuple[TuiColumn, ...] = (
    {"key": "account_name", "label": "账户名称"},
    {"key": "account_type", "label": "账户类型"},
    {"key": "account_id", "label": "账户编号"},
)
_PORTFOLIO_COLUMNS: tuple[TuiColumn, ...] = (
    {"key": "name", "label": "组合名称"},
    {"key": "is_active", "label": "是否启用"},
    {"key": "base_currency_code", "label": "基础币种代码"},
    {"key": "base_currency_name", "label": "基础币种名称"},
    {"key": "id", "label": "组合编号"},
)
_PORTFOLIO_PAGE_SIZE = 20


def _as_mapping(value: object) -> Mapping[str, object] | None:
    """Narrow one decoded JSON object to a string-key mapping."""

    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _transport_message(kind: str, http_status: int) -> str | None:
    """Return a bounded message for a non-success or invalid HTTP status."""

    if type(http_status) is not int:
        return f"{kind}响应状态无法识别。"
    if 200 <= http_status < 300:
        return None
    if http_status in {401, 403}:
        return f"当前用户没有访问{kind}的权限。"
    if http_status == 404:
        return f"{kind}不存在或已不可用。"
    if http_status >= 500:
        return f"{kind}服务暂时不可用。"
    return f"{kind}请求未完成。"


def _blocked(message: str, reason: str) -> TuiSelectorMessageView:
    """Build a bounded message without copying owner detail or URLs."""

    return {
        "kind": "message",
        "title": "读取结果",
        "status": "已阻断",
        "message": message,
        "outcome": "blocked",
        "blocking_reason": reason,
        "business_summary": "本次选择结果未形成可展示记录。",
        "next_steps": [],
    }


def _positive_int(value: object) -> int | None:
    """Read an exact positive integer from a projector input or JSON value."""

    if type(value) is not int or value < 1:
        return None
    return value


def _nonnegative_int(value: object) -> int | None:
    """Read an exact non-negative JSON count."""

    if type(value) is not int or value < 0:
        return None
    return value


def _nonempty_text(value: object) -> str | None:
    """Read display text without inventing a fallback value."""

    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _optional_text(value: object) -> str | None:
    """Preserve a nullable owner text field without inferring its meaning."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _link_present(value: object) -> bool | None:
    """Convert an owner pagination link to a boolean without retaining its URL."""

    if value is None:
        return False
    if isinstance(value, str) and value:
        return True
    return None


def _account_pager(total: int) -> TuiPager:
    """Keep every loaded row accessible through bounded client-side pages."""

    return {
        "client_side": True,
        "pagination_mode": "page",
        "page": 1,
        "page_size": 20,
        "total_rows": total,
        "total_pages": max(1, (total + 19) // 20),
        "has_previous": False,
        "has_next": total > 20,
    }


def _portfolio_pager(
    *,
    page: int,
    total: int,
    total_pages: int,
    has_previous: bool,
    has_next: bool,
) -> TuiPager:
    """Build the fixed-size server-page facts for the portable view."""

    return {
        "client_side": False,
        "pagination_mode": "page",
        "page": page,
        "page_size": _PORTFOLIO_PAGE_SIZE,
        "total_rows": total,
        "total_pages": max(1, total_pages),
        "has_previous": has_previous,
        "has_next": has_next,
    }


def project_account_selector_payload(
    payload: object, *, http_status: int
) -> TuiAccountDatagridView | TuiSelectorMessageView:
    """Project the authenticated user's unpaginated active account response.

    The owner contract is ``success/count/accounts``.  A malformed response,
    a failed owner response, or a non-2xx transport result becomes a bounded
    ``kind=message`` view.  Successful rows retain only ``account_id``,
    ``account_name`` and ``account_type`` and are marked client-side because
    this endpoint does not advertise server pagination.
    """

    transport_message = _transport_message("账户目录", http_status)
    if transport_message is not None:
        return _blocked(transport_message, "账户目录读取未完成。")

    data = _as_mapping(payload)
    if data is None:
        return _blocked("账户目录返回格式无法识别。", "账户目录响应格式不受支持。")

    success = data.get("success")
    if type(success) is not bool:
        return _blocked("账户目录返回格式无法识别。", "账户目录响应格式不受支持。")
    if not success:
        return _blocked("账户目录当前不可用。", "暂时无法读取账户目录，请稍后重试。")

    count = _nonnegative_int(data.get("count"))
    raw_accounts = data.get("accounts")
    if count is None or not isinstance(raw_accounts, list) or count != len(raw_accounts):
        return _blocked("账户目录返回格式无法识别。", "账户目录响应格式不受支持。")

    rows: list[TuiAccountSelectorRow] = []
    seen_ids: set[int] = set()
    for raw_account in raw_accounts:
        account = _as_mapping(raw_account)
        if account is None:
            return _blocked("账户目录返回格式无法识别。", "账户目录响应格式不受支持。")
        account_id = _positive_int(account.get("account_id"))
        account_name = _nonempty_text(account.get("account_name"))
        account_type = _nonempty_text(account.get("account_type"))
        if (
            account_id is None
            or account_name is None
            or account_type is None
            or account_id in seen_ids
        ):
            return _blocked("账户目录返回格式无法识别。", "账户目录响应格式不受支持。")
        seen_ids.add(account_id)
        rows.append(
            {
                "account_name": account_name,
                "account_type": {
                    "real": "实仓",
                    "simulated": "模拟仓",
                }.get(account_type, "未识别类型"),
                "account_id": account_id,
            }
        )

    if rows:
        empty_message = "当前没有可显示的账户。"
        empty_guidance: list[str] = []
        summary = f"已读取当前用户本人活跃账户，共{count}个。"
    else:
        empty_message = "当前没有本人活跃账户。"
        empty_guidance = ["可先查看市场环境，再重新选择账户。"]
        summary = "当前用户没有可供本任务读取的本人活跃账户。"
    return {
        "kind": "datagrid",
        "title": "本人活跃账户",
        "status": "已读取",
        "columns": list(_ACCOUNT_COLUMNS),
        "rows": rows,
        "pager": _account_pager(count),
        "empty_message": empty_message,
        "empty_guidance": empty_guidance,
        "next_steps": [],
        "business_summary": summary,
    }


def project_portfolio_selector_payload(
    payload: object,
    *,
    requested_page: object,
    http_status: int,
) -> TuiPortfolioDatagridView | TuiSelectorMessageView:
    """Project one fixed-size owner portfolio page.

    The owner contract is ``count/next/previous/results`` with a page size of
    twenty.  Only page booleans are retained; ``next`` and ``previous`` URLs
    are intentionally discarded.  Nullable currency values remain nullable
    and are never inferred from another field.
    """

    page = _positive_int(requested_page)
    if page is None:
        return _blocked("组合目录页码无效。", "组合目录请求页码不符合合同。")

    transport_message = _transport_message("组合目录", http_status)
    if transport_message is not None:
        return _blocked(transport_message, "组合目录读取未完成。")

    data = _as_mapping(payload)
    if data is None:
        return _blocked("组合目录返回格式无法识别。", "组合目录响应格式不受支持。")

    count = _nonnegative_int(data.get("count"))
    raw_results = data.get("results")
    has_next = _link_present(data.get("next")) if "next" in data else None
    has_previous = _link_present(data.get("previous")) if "previous" in data else None
    if (
        count is None
        or not isinstance(raw_results, list)
        or has_next is None
        or has_previous is None
        or len(raw_results) > _PORTFOLIO_PAGE_SIZE
    ):
        return _blocked("组合目录返回格式无法识别。", "组合目录响应格式不受支持。")

    total_pages = max(1, (count + _PORTFOLIO_PAGE_SIZE - 1) // _PORTFOLIO_PAGE_SIZE)
    if page > total_pages:
        return _blocked("组合目录分页信息不一致。", "组合目录分页事实相互矛盾。")
    expected_rows = (
        0 if count == 0 else min(_PORTFOLIO_PAGE_SIZE, count - (page - 1) * _PORTFOLIO_PAGE_SIZE)
    )
    if len(raw_results) != expected_rows:
        return _blocked("组合目录分页信息不一致。", "组合目录分页事实相互矛盾。")
    if has_previous != (page > 1) or has_next != (page < total_pages):
        return _blocked("组合目录分页信息不一致。", "组合目录分页事实相互矛盾。")

    rows: list[TuiPortfolioSelectorRow] = []
    seen_ids: set[int] = set()
    for raw_portfolio in raw_results:
        portfolio = _as_mapping(raw_portfolio)
        if portfolio is None:
            return _blocked("组合目录返回格式无法识别。", "组合目录响应格式不受支持。")
        portfolio_id = _positive_int(portfolio.get("id"))
        name = _nonempty_text(portfolio.get("name"))
        is_active = portfolio.get("is_active")
        currency_code = _optional_text(portfolio.get("base_currency_code"))
        currency_name = _optional_text(portfolio.get("base_currency_name"))
        if (
            portfolio_id is None
            or name is None
            or type(is_active) is not bool
            or portfolio_id in seen_ids
            or "base_currency_code" not in portfolio
            or "base_currency_name" not in portfolio
            or (portfolio.get("base_currency_code") is not None and currency_code is None)
            or (portfolio.get("base_currency_name") is not None and currency_name is None)
        ):
            return _blocked("组合目录返回格式无法识别。", "组合目录响应格式不受支持。")
        seen_ids.add(portfolio_id)
        rows.append(
            {
                "name": name,
                "is_active": is_active,
                "base_currency_code": currency_code,
                "base_currency_name": currency_name,
                "id": portfolio_id,
            }
        )

    if rows:
        empty_message = "当前没有可显示的组合记录。"
        empty_guidance: list[str] = []
        summary = f"已读取第{page}页组合目录，本页{len(rows)}条，目录共{count}条。"
    elif count == 0:
        empty_message = "当前没有可查看的授权组合。"
        empty_guidance = ["请确认当前用户的组合访问范围。"]
        summary = "当前没有可供本任务读取的授权组合。"
    else:
        empty_message = "当前页没有组合记录。"
        empty_guidance = ["请返回组合目录首页重新选择。"]
        summary = f"目录共{count}条，但第{page}页没有记录。"
    return {
        "kind": "datagrid",
        "title": "可查看组合",
        "status": "已读取",
        "columns": list(_PORTFOLIO_COLUMNS),
        "rows": rows,
        "pager": _portfolio_pager(
            page=page,
            total=count,
            total_pages=total_pages,
            has_previous=has_previous,
            has_next=has_next,
        ),
        "empty_message": empty_message,
        "empty_guidance": empty_guidance,
        "next_steps": [],
        "business_summary": summary,
    }


__all__ = [
    "TuiAccountDatagridView",
    "TuiAccountSelectorRow",
    "TuiColumn",
    "TuiNextStep",
    "TuiPager",
    "TuiPortfolioDatagridView",
    "TuiPortfolioSelectorRow",
    "TuiSelectorMessageView",
    "TuiSelectorResult",
    "project_account_selector_payload",
    "project_portfolio_selector_payload",
]
