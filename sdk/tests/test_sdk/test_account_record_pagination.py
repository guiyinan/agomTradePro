"""Failure-first tests for portfolio-scoped Account record pagination."""

from unittest.mock import call, patch

import pytest

from agomtradepro import AgomTradeProAPIError, AgomTradeProClient
from agomtradepro.modules import account as account_module

_READERS = (
    ("list_transaction_records", "/api/account/transactions/"),
    ("list_capital_flow_records", "/api/account/capital-flows/"),
)
_INVALID_CODE = "account_record_pagination_invalid"
_INVALID_MESSAGE = "Account pagination response was malformed or incomplete."
_SCOPE_CODE = "account_record_scope_invalid"
_SCOPE_MESSAGE = "portfolio_id must be a positive integer."
_SCAN_CODE = "account_record_scan_limit"
_SCAN_MESSAGE = (
    "Account record scan limit reached; requested records could not be completely " "validated."
)


def _assert_local_error(
    error: AgomTradeProAPIError,
    *,
    code: str,
    message: str,
) -> None:
    """Assert a client-side pagination error without an HTTP status."""

    assert error.code == code
    assert error.status_code is None
    assert error.response == {
        "code": code,
        "message": message,
        "origin": "client_validation",
    }
    assert str(error) == message


def _envelope(
    *,
    count: object,
    next_url: object,
    rows: list[object],
    previous_url: object = None,
) -> dict[str, object]:
    """Build the real DRF PageNumberPagination response shape."""

    return {
        "count": count,
        "next": next_url,
        "previous": previous_url,
        "results": rows,
    }


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_portfolio_filter_precedes_limit_and_next_url_is_never_requested(
    reader_name: str,
    endpoint: str,
) -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    first = {"id": 20, "portfolio": 7, "sequence": "first"}
    foreign = {"id": 31, "portfolio": 8, "sequence": "skip"}
    second = {"id": 4, "portfolio": 7, "sequence": "second"}
    pages = [
        _envelope(
            count=3,
            next_url="https://untrusted.invalid/api/account/records/?page=99",
            rows=[first, foreign],
        ),
        _envelope(
            count=3,
            next_url=None,
            previous_url="https://untrusted.invalid/api/account/records/?page=1",
            rows=[second],
        ),
    ]

    with patch.object(client, "_request", side_effect=pages) as request:
        result = getattr(client.account, reader_name)(portfolio_id=7, limit=2)

    assert result == [first, second]
    assert request.call_args_list == [
        call("GET", endpoint, params={"limit": 2, "page": 1}),
        call("GET", endpoint, params={"limit": 2, "page": 2}),
    ]


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_legacy_raw_list_is_filtered_before_limit(
    reader_name: str,
    endpoint: str,
) -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    first = {"id": 12, "portfolio": 7}
    foreign = {"id": 13, "portfolio": 8}
    second = {"id": 5, "portfolio": 7}

    with patch.object(
        client,
        "_request",
        return_value=[first, foreign, second],
    ) as request:
        result = getattr(client.account, reader_name)(portfolio_id=7, limit=2)

    assert result == [first, second]
    request.assert_called_once_with(
        "GET",
        endpoint,
        params={"limit": 2, "page": 1},
    )


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_non_dict_row_in_legacy_raw_list_fails_closed(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(
        client,
        "_request",
        return_value=[{"id": 1, "portfolio": 7}, None],
    ):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=2)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
@pytest.mark.parametrize("limit", [0, -1])
def test_nonpositive_limit_performs_no_read(
    reader_name: str,
    endpoint: str,
    limit: int,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(client, "_request") as request:
        assert getattr(client.account, reader_name)(portfolio_id=7, limit=limit) == []

    request.assert_not_called()


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
@pytest.mark.parametrize("portfolio_id", [True, 0, -1, 1.0, "7"])
@pytest.mark.parametrize("limit", [0, -1, 2])
def test_invalid_portfolio_scope_is_rejected_before_read(
    reader_name: str,
    endpoint: str,
    portfolio_id: object,
    limit: int,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(client, "_request") as request:
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=portfolio_id, limit=limit)

    request.assert_not_called()
    _assert_local_error(error.value, code=_SCOPE_CODE, message=_SCOPE_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
@pytest.mark.parametrize(
    "row",
    [
        {"id": 1},
        {"id": 1, "portfolio": True},
        {"id": 1, "portfolio": "7"},
    ],
)
def test_unscoped_ledger_read_still_requires_exact_portfolio_id(
    reader_name: str,
    endpoint: str,
    row: dict[str, object],
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    response = _envelope(count=1, next_url=None, rows=[row])

    with patch.object(client, "_request", return_value=response) as request:
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(limit=2)

    request.assert_called_once()
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_countless_terminal_envelope_remains_legacy_compatible(
    reader_name: str,
    endpoint: str,
) -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    expected = [{"id": 2, "portfolio": 7}]

    with patch.object(
        client,
        "_request",
        return_value={"results": expected, "next": None},
    ) as request:
        result = getattr(client.account, reader_name)(portfolio_id=7, limit=10)

    assert result == expected
    request.assert_called_once_with(
        "GET",
        endpoint,
        params={"limit": 10, "page": 1},
    )


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_existing_5000_row_read_limit_survives_twenty_row_pages(
    reader_name: str,
    endpoint: str,
) -> None:
    """The default 5000-row MCP export remains below the transport page ceiling."""
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    page_count = 250
    rows_per_page = 20
    pages = [
        _envelope(
            count=page_count * rows_per_page,
            next_url=(f"https://untrusted.invalid/?page={page + 1}" if page < page_count else None),
            rows=[
                {"id": (page - 1) * rows_per_page + row + 1, "portfolio": 7}
                for row in range(rows_per_page)
            ],
        )
        for page in range(1, page_count + 1)
    ]

    with patch.object(client, "_request", side_effect=pages) as request:
        result = getattr(client.account, reader_name)(limit=5000)

    assert len(result) == 5000
    assert request.call_count == 250
    assert request.call_args_list[0] == call(
        "GET",
        endpoint,
        params={"limit": 200, "page": 1},
    )
    assert request.call_args_list[-1] == call(
        "GET",
        endpoint,
        params={"limit": 200, "page": 250},
    )


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
@pytest.mark.parametrize(
    "response",
    [
        {"count": 1, "next": None, "results": "not-a-list"},
        {"count": True, "next": None, "results": [{"id": 1, "portfolio": 7}]},
        {"count": 1.5, "next": None, "results": [{"id": 1, "portfolio": 7}]},
        {"count": "1", "next": None, "results": [{"id": 1, "portfolio": 7}]},
        {"count": -1, "next": None, "results": []},
        {"count": 0, "next": None},
        {"count": 1, "next": [], "results": [{"id": 1, "portfolio": 7}]},
        {"count": 1, "next": "", "results": [{"id": 1, "portfolio": 7}]},
        {"count": 1, "results": [{"id": 1, "portfolio": 7}]},
        {"count": 1, "next": None, "results": [{"portfolio": 7}]},
        {"count": 1, "next": None, "results": [{"id": True, "portfolio": 7}]},
        {"count": 1, "next": None, "results": [{"id": 1}]},
        {"count": 1, "next": None, "results": [{"id": 1, "portfolio": True}]},
        {"count": 1, "next": None, "results": [{"id": 1, "portfolio": "7"}]},
        {
            "count": 1,
            "next": None,
            "results": [{"id": 1, "portfolio": 7}, None],
        },
        {"next": "https://untrusted.invalid/?page=2", "results": []},
    ],
)
def test_malformed_envelope_metadata_or_rows_fails_closed(
    reader_name: str,
    endpoint: str,
    response: object,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(client, "_request", return_value=response):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=2)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_page_metadata_is_checked_before_limit_early_return(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    response = _envelope(
        count=1,
        next_url={"url": "https://untrusted.invalid/?page=2"},
        rows=[{"id": 1, "portfolio": 7}],
    )

    with patch.object(client, "_request", return_value=response):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=1)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_page_count_change_is_rejected_before_early_return(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    pages = [
        _envelope(
            count=2,
            next_url="https://untrusted.invalid/?page=2",
            rows=[{"id": 1, "portfolio": 8}],
        ),
        _envelope(
            count=3,
            next_url=None,
            rows=[{"id": 2, "portfolio": 7}],
        ),
    ]

    with patch.object(client, "_request", side_effect=pages):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=1)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
@pytest.mark.parametrize(
    "pages",
    [
        [
            _envelope(
                count=2,
                next_url="https://untrusted.invalid/?page=2",
                rows=[{"id": 1, "portfolio": 8}],
            ),
            _envelope(
                count=3,
                next_url=None,
                rows=[{"id": 2, "portfolio": 7}],
            ),
        ],
        [
            _envelope(
                count=2,
                next_url=None,
                rows=[{"id": 1, "portfolio": 7}],
            ),
        ],
        [
            _envelope(
                count=2,
                next_url="https://untrusted.invalid/?page=2",
                rows=[{"id": 1, "portfolio": 7}],
            ),
            _envelope(count=2, next_url=None, rows=[]),
        ],
    ],
    ids=["count-changes", "terminal-count-incomplete", "empty-continuation"],
)
def test_changed_or_incomplete_counted_pagination_fails_closed(
    reader_name: str,
    endpoint: str,
    pages: list[dict[str, object]],
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")

    with patch.object(client, "_request", side_effect=pages):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=5)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_second_page_cannot_drop_count(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    pages = [
        _envelope(
            count=2,
            next_url="https://untrusted.invalid/?page=2",
            rows=[{"id": 1, "portfolio": 8}],
        ),
        {"next": None, "results": [{"id": 2, "portfolio": 7}]},
    ]

    with patch.object(client, "_request", side_effect=pages):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=1)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_count_exhausted_while_next_still_advertises_more_rows_fails(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    only_page = _envelope(
        count=1,
        next_url="https://untrusted.invalid/?page=2",
        rows=[{"id": 1, "portfolio": 7}],
    )

    with patch.object(client, "_request", return_value=only_page) as request:
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=5)
    request.assert_called_once()
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_raw_list_cannot_replace_a_continuing_envelope_page(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    pages = [
        _envelope(
            count=2,
            next_url="https://untrusted.invalid/?page=2",
            rows=[{"id": 1, "portfolio": 8}],
        ),
        [{"id": 2, "portfolio": 7}],
    ]

    with patch.object(client, "_request", side_effect=pages):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=1)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(
    ("reader_name", "endpoint", "call_kwargs", "first_params"),
    [
        (
            "list_portfolio_records",
            "/api/account/portfolios/",
            {},
            {"limit": 2, "page": 1},
        ),
        (
            "list_position_records",
            "/api/account/positions/read-only/",
            {"portfolio_id": 7},
            {"portfolio_id": 7, "include_closed": False, "limit": 2, "page": 1},
        ),
    ],
)
def test_other_shared_page_readers_keep_counted_pagination_contract(
    reader_name: str,
    endpoint: str,
    call_kwargs: dict[str, object],
    first_params: dict[str, object],
) -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    if reader_name == "list_portfolio_records":
        first = {"id": 11, "name": "Core"}
        second = {"id": 12, "name": "Reserve"}
    else:
        first = {"id": 11, "portfolio": 7, "asset_code": "510300.SH"}
        second = {"id": 12, "portfolio": 7, "asset_code": "510500.SH"}
    pages = [
        _envelope(
            count=2,
            next_url="https://untrusted.invalid/?page=2",
            rows=[first],
        ),
        _envelope(count=2, next_url=None, rows=[second]),
    ]
    second_params = {**first_params, "page": 2}

    with patch.object(client, "_request", side_effect=pages) as request:
        result = getattr(client.account, reader_name)(**call_kwargs, limit=2)

    assert result == [first, second]
    assert request.call_args_list == [
        call("GET", endpoint, params=first_params),
        call("GET", endpoint, params=second_params),
    ]


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_duplicate_record_id_across_pages_fails_closed(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    pages = [
        _envelope(
            count=3,
            next_url="https://untrusted.invalid/?page=2",
            rows=[{"id": 1, "portfolio": 7}, {"id": 2, "portfolio": 8}],
        ),
        _envelope(
            count=3,
            next_url=None,
            rows=[{"id": 2, "portfolio": 7}],
        ),
    ]

    with patch.object(client, "_request", side_effect=pages):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=5)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_duplicate_record_id_within_page_fails_closed(
    reader_name: str,
    endpoint: str,
) -> None:
    del endpoint
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    duplicate = {"id": 1, "portfolio": 7}
    response = _envelope(
        count=2,
        next_url=None,
        rows=[duplicate, duplicate.copy()],
    )

    with patch.object(client, "_request", return_value=response):
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=2)
    _assert_local_error(error.value, code=_INVALID_CODE, message=_INVALID_MESSAGE)


@pytest.mark.parametrize(("reader_name", "endpoint"), _READERS)
def test_page_scan_ceiling_raises_instead_of_returning_partial_records(
    reader_name: str,
    endpoint: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = AgomTradeProClient(base_url="http://test.com", api_token="token")
    monkeypatch.setattr(account_module, "_MAX_RECORD_SCAN_PAGES", 2, raising=False)

    def page_response(
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        del kwargs
        assert method == "GET"
        assert path == endpoint
        assert params is not None
        page = params["page"]
        assert isinstance(page, int)
        assert page <= 2
        row_id = page
        return _envelope(
            count=10,
            next_url="https://untrusted.invalid/?page=next",
            rows=[{"id": row_id, "portfolio": 7}],
        )

    with patch.object(client, "_request", side_effect=page_response) as request:
        with pytest.raises(AgomTradeProAPIError) as error:
            getattr(client.account, reader_name)(portfolio_id=7, limit=10)

    assert request.call_count == 2
    _assert_local_error(error.value, code=_SCAN_CODE, message=_SCAN_MESSAGE)
