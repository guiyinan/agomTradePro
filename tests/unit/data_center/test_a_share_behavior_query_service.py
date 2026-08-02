"""Freshness contracts for current A-share trading-behavior reads."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from apps.data_center.application.query_services import (
    A_SHARE_BEHAVIOR_INDICATORS,
    get_latest_a_share_behavior_payload,
    query_published_a_share_behavior_payload,
)
from apps.data_center.domain.entities import MacroFact
from apps.data_center.domain.enums import DataQualityStatus


class _Repository:
    def __init__(self, facts: dict[str, MacroFact]) -> None:
        self._facts = facts

    def get_latest(self, indicator_code: str) -> MacroFact | None:
        return self._facts.get(indicator_code)


class _Publication:
    def __init__(self, publication_id: str) -> None:
        self.publication_id = publication_id
        self.published_at = datetime(2026, 7, 30, 8, 0, tzinfo=UTC)
        self.as_of = self.published_at
        self.must_not_use_for_decision = False
        self.blocked_reason = ""


class _PublicationRepository:
    def __init__(self, missing: set[str] | None = None) -> None:
        self.missing = missing or set()

    def get_current(self, dataset_key: str, publication_key: str) -> _Publication | None:
        assert dataset_key == "macro.fact"
        if publication_key in self.missing:
            return None
        return _Publication(f"publication-{publication_key}")


class _StalePublicationRepository(_PublicationRepository):
    def get_oldest_member_observed_at(self, _publication_id: str) -> datetime:
        return datetime(2025, 7, 1, tzinfo=UTC)


def _fact(indicator_code: str, observed_at: date, value: float) -> MacroFact:
    return MacroFact(
        indicator_code=indicator_code,
        reporting_period=observed_at,
        value=value,
        unit="家",
        source="test",
        published_at=observed_at,
        quality=DataQualityStatus.VALID,
    )


def test_current_behavior_payload_accepts_latest_completed_session(monkeypatch) -> None:
    observed_at = date(2026, 7, 30)
    values = {
        "up_count": 3100,
        "down_count": 1800,
        "limit_up_count": 90,
        "limit_down_count": 8,
    }
    repository = _Repository(
        {
            indicator_code: _fact(indicator_code, observed_at, values[field_name])
            for field_name, indicator_code in A_SHARE_BEHAVIOR_INDICATORS.items()
        }
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_macro_fact_repository",
        lambda: repository,
    )

    payload = get_latest_a_share_behavior_payload(now=datetime(2026, 7, 30, 8, 30, tzinfo=UTC))

    assert payload["stats_available"] is True
    assert {field: payload[field] for field in values} == values
    assert payload["contract"]["market_data_as_of"] == "2026-07-30"
    assert payload["contract"]["must_not_use_for_decision"] is False


def test_behavior_payload_blocks_missing_and_stale_values(monkeypatch) -> None:
    observed_at = date(2026, 7, 29)
    repository = _Repository(
        {
            "CN_A_ADVANCE_COUNT": _fact("CN_A_ADVANCE_COUNT", observed_at, 3000),
            "CN_A_DECLINE_COUNT": _fact("CN_A_DECLINE_COUNT", observed_at, 1900),
        }
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_macro_fact_repository",
        lambda: repository,
    )

    payload = get_latest_a_share_behavior_payload(now=datetime(2026, 7, 30, 8, 30, tzinfo=UTC))

    assert payload["limit_up_count"] is None
    assert payload["limit_down_count"] is None
    assert payload["stats_available"] is False
    assert payload["contract"]["must_not_use_for_decision"] is True
    assert payload["contract"]["blocked_reason"] == "market_breadth_incomplete"
    assert payload["contract"]["missing_fields"] == ["limit_up_count", "limit_down_count"]
    assert payload["contract"]["stale_fields"] == ["up_count", "down_count"]


def test_published_behavior_fails_closed_before_reading_facts(monkeypatch) -> None:
    """Missing one component publication must block the composite read."""

    repository = _PublicationRepository(missing={"CN_A_LIMIT_UP_COUNT"})
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_canonical_publication_repository",
        lambda: repository,
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_macro_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("facts must not be read before publication")),
    )

    payload = query_published_a_share_behavior_payload()

    assert payload["stats_available"] is False
    assert payload["contract"]["blocked_reason"] == "canonical_publication_missing"
    assert payload["contract"]["missing_fields"] == ["limit_up_count"]


def test_published_behavior_carries_each_component_publication_id(monkeypatch) -> None:
    """A complete composite keeps the publication evidence for every component."""

    observed_at = date(2026, 7, 30)
    repository = _Repository(
        {
            indicator_code: _fact(indicator_code, observed_at, 1)
            for indicator_code in A_SHARE_BEHAVIOR_INDICATORS.values()
        }
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_canonical_publication_repository",
        lambda: _PublicationRepository(),
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_macro_fact_repository",
        lambda: repository,
    )

    payload = query_published_a_share_behavior_payload(now=datetime(2026, 7, 30, 8, 30, tzinfo=UTC))

    assert payload["stats_available"] is True
    assert set(payload["publication_ids"]) == set(A_SHARE_BEHAVIOR_INDICATORS.values())
    assert payload["contract"]["must_not_use_for_decision"] is False


def test_published_behavior_blocks_stale_component_publications(monkeypatch) -> None:
    """A composite behavior read blocks before facts when any component is stale."""

    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_canonical_publication_repository",
        lambda: _StalePublicationRepository(),
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_dataset_contract_repository",
        lambda: SimpleNamespace(
            get_active=lambda _dataset_key: SimpleNamespace(freshness_seconds=86_400)
        ),
    )
    monkeypatch.setattr(
        "apps.data_center.application.query_services.get_macro_fact_repository",
        lambda: (_ for _ in ()).throw(AssertionError("stale breadth facts must not be read")),
    )

    payload = query_published_a_share_behavior_payload(now=datetime(2026, 7, 30, 8, 30, tzinfo=UTC))

    assert payload["stats_available"] is False
    assert payload["contract"]["blocked_reason"] == "canonical_publication_stale"
    assert payload["contract"]["is_stale"] is True
    assert payload["contract"]["stale_fields"] == list(A_SHARE_BEHAVIOR_INDICATORS.keys())
    assert payload["contract"]["blocked_fields"] == list(A_SHARE_BEHAVIOR_INDICATORS.keys())
