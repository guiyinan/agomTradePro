"""HTTP contracts for the governed equity research snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import Mock, patch

import pytest

from apps.equity.application.research_snapshot import EquityResearchSnapshotRequest

ENDPOINT = "/api/equity/research-snapshot/000001.sz/"


@dataclass(frozen=True)
class _FakeSnapshotResult:
    payload: dict[str, object]

    def to_payload(self) -> dict[str, object]:
        return dict(self.payload)


def _snapshot_payload() -> dict[str, object]:
    return {
        "status": "fresh",
        "stock_code": "000001.SZ",
        "identity": {"status": "fresh", "required": True, "data": {"code": "000001.SZ"}},
        "sections": {},
        "decision_readiness": {"status": "ok", "must_not_use_for_decision": False},
        "missing_optional_sections": [],
        "reliability": {
            "status": "fresh",
            "source": "agomtradepro_api",
            "must_not_use_for_decision": False,
            "block_reason_code": "",
            "block_reason": "",
        },
        "must_not_use_for_decision": False,
    }


@pytest.mark.django_db
def test_research_snapshot_requires_authentication(api_client) -> None:
    response = api_client.get(ENDPOINT)

    assert response.status_code in {401, 403}


@pytest.mark.django_db
def test_research_snapshot_delegates_normalized_defaults_to_application(
    authenticated_client,
) -> None:
    use_case = Mock()
    use_case.execute.return_value = _FakeSnapshotResult(_snapshot_payload())

    with patch(
        "apps.equity.interface.research_snapshot_views." "make_equity_research_snapshot_use_case",
        return_value=use_case,
    ) as factory:
        response = authenticated_client.get(ENDPOINT)

    assert response.status_code == 200
    assert response.json() == _snapshot_payload()
    factory.assert_called_once_with()
    use_case.execute.assert_called_once_with(
        EquityResearchSnapshotRequest(
            stock_code="000001.SZ",
            history_limit=252,
            financial_limit=20,
            valuation_limit=252,
            news_limit=20,
            capital_flow_limit=60,
        )
    )


@pytest.mark.django_db
def test_research_snapshot_forwards_bounded_custom_limits(authenticated_client) -> None:
    use_case = Mock()
    use_case.execute.return_value = _FakeSnapshotResult(_snapshot_payload())

    with patch(
        "apps.equity.interface.research_snapshot_views." "make_equity_research_snapshot_use_case",
        return_value=use_case,
    ):
        response = authenticated_client.get(
            ENDPOINT,
            {
                "history_limit": 1000,
                "financial_limit": 100,
                "valuation_limit": 999,
                "news_limit": 1,
                "capital_flow_limit": 500,
            },
        )

    assert response.status_code == 200
    use_case.execute.assert_called_once_with(
        EquityResearchSnapshotRequest(
            stock_code="000001.SZ",
            history_limit=1000,
            financial_limit=100,
            valuation_limit=999,
            news_limit=1,
            capital_flow_limit=500,
        )
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "query",
    [
        {"unexpected": "true"},
        {"stock_code": "600000.SH"},
        {"history_limit": 0},
        {"financial_limit": 101},
        {"valuation_limit": 1001},
        {"news_limit": "not-an-integer"},
        {"capital_flow_limit": -1},
    ],
)
def test_research_snapshot_rejects_invalid_query_without_calling_application(
    authenticated_client,
    query: dict[str, object],
) -> None:
    with patch(
        "apps.equity.interface.research_snapshot_views." "make_equity_research_snapshot_use_case"
    ) as factory:
        response = authenticated_client.get(ENDPOINT, query)

    assert response.status_code == 400
    factory.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stock_code",
    [
        "invalid%20code",
        "%2E%2E",
        "bad%3Fquery",
        "a" * 33,
    ],
)
def test_research_snapshot_rejects_unsafe_path_identifier(
    authenticated_client,
    stock_code: str,
) -> None:
    with patch(
        "apps.equity.interface.research_snapshot_views." "make_equity_research_snapshot_use_case"
    ) as factory:
        response = authenticated_client.get(f"/api/equity/research-snapshot/{stock_code}/")

    assert response.status_code == 400
    factory.assert_not_called()


@pytest.mark.django_db
def test_research_snapshot_is_get_only(authenticated_client) -> None:
    response = authenticated_client.post(ENDPOINT, {}, format="json")

    assert response.status_code == 405
