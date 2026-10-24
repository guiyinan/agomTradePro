"""Compatibility of optional vendor metrics with existing quote rows."""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from apps.data_center.domain.quote_change_pct import QuoteChangePctCandidate
from apps.data_center.infrastructure.market_gateway_entities import QuoteSnapshot
from apps.data_center.infrastructure.provider_quote_snapshot_mapping import (
    optional_quote_change_pct_candidate,
    quote_source,
)


def test_legacy_price_and_percentage_do_not_invent_a_metric_candidate() -> None:
    quote = SimpleNamespace(price=Decimal("10"), change_pct=0.0)
    assert optional_quote_change_pct_candidate(quote, provider_source="fixture") is None
    assert quote.price == Decimal("10") and quote.change_pct == 0.0


@pytest.mark.parametrize("raw", ["0", "1.234567891234"])
def test_real_gateway_candidate_keeps_exact_reported_text_and_zero(raw: str) -> None:
    observed = datetime(2026, 10, 23, 7, tzinfo=UTC)
    quote = QuoteSnapshot(
        stock_code="000001.SZ",
        price=Decimal("10"),
        source="fixture",
        observed_at=observed,
        fetched_at=observed,
        change_pct_source_value=raw,
        change_pct_source_field="reported_pct",
        change_pct_source_origin="vendor_reported",
    )
    expected = quote.to_change_pct_candidate(provider_source="fixture")
    result = optional_quote_change_pct_candidate(quote, provider_source="fixture")
    assert isinstance(result, QuoteChangePctCandidate) and result == expected
    assert result.raw_value == raw and result.provider_source == "fixture"


@pytest.mark.parametrize("error", [ValueError, TypeError])
def test_bad_optional_metric_does_not_discard_a_valid_price(error: type[Exception]) -> None:
    def invalid_builder(*, provider_source: str) -> None:
        assert provider_source == "fixture"
        raise error("invalid optional source scalar")

    quote = SimpleNamespace(price=Decimal("10"), to_change_pct_candidate=invalid_builder)
    assert optional_quote_change_pct_candidate(quote, provider_source="fixture") is None
    assert quote.price == Decimal("10")


def test_untyped_candidate_output_is_not_admitted_to_the_domain() -> None:
    quote = SimpleNamespace(
        price=Decimal("10"),
        to_change_pct_candidate=lambda **_kwargs: {"raw_value": "0"},
    )
    assert optional_quote_change_pct_candidate(quote, provider_source="fixture") is None


@pytest.mark.parametrize("source", [None, "", " ", 7, {"vendor": "fixture"}])
def test_optional_source_is_narrowed_before_adaptation(source: object) -> None:
    assert quote_source(SimpleNamespace(source=source), "tushare") == "tushare"
    assert quote_source(SimpleNamespace(), "tushare") == "tushare"


def test_real_vendor_source_precedes_configured_fallback() -> None:
    assert quote_source(SimpleNamespace(source=" actual_vendor "), "configured") == "actual_vendor"


@pytest.mark.parametrize("reported_source", [None, "actual_vendor"])
def test_adapter_source_identity_does_not_use_provider_display_name(
    monkeypatch: pytest.MonkeyPatch, reported_source: str | None
) -> None:
    from datetime import date

    from apps.data_center.domain.entities import ProviderConfig
    from apps.data_center.infrastructure._provider_adapter_tushare import (
        TushareUnifiedProviderAdapter,
    )

    config = ProviderConfig(
        id=1,
        name="Tushare Display Name",
        source_type="tushare",
        is_active=True,
        priority=1,
        api_key="test-key",
        api_secret="",
        http_url="",
        api_endpoint="",
        extra_config={},
        description="",
    )
    observed = datetime(2026, 10, 23, 7, tzinfo=UTC)

    def build_candidate(*, provider_source: str) -> QuoteChangePctCandidate:
        return QuoteChangePctCandidate(
            raw_value="0",
            source_field="pct_chg",
            origin="vendor_reported",
            provider_source=provider_source,
        )

    quote = SimpleNamespace(
        stock_code="000001.SZ",
        price=10.0,
        open=None,
        high=None,
        low=None,
        pre_close=None,
        volume=None,
        amount=None,
        observed_at=observed,
        fetched_at=observed,
        to_change_pct_candidate=build_candidate,
        extra={"actual_source": "untrusted_extra_vendor"},
    )
    if reported_source is not None:
        quote.source = reported_source

    class Gateway:
        def __init__(self, **kwargs: object) -> None:
            pass

        def get_quote_snapshots(self, codes: list[str], *, target_trade_date: date) -> list[object]:
            assert codes == ["000001.SZ"] and target_trade_date == date(2026, 10, 23)
            return [quote]

    monkeypatch.setattr(
        "apps.data_center.infrastructure.gateways.tushare_gateway.TushareGateway", Gateway
    )
    facts = TushareUnifiedProviderAdapter(config).fetch_quote_snapshots_for_session(
        ["000001.SZ"], date(2026, 10, 23)
    )
    assert len(facts) == 1 and facts[0].source == "tushare"
    candidate = facts[0].change_pct_candidate
    assert candidate is not None and candidate.provider_source == (reported_source or "tushare")
    assert candidate.raw_value == "0"
    assert facts[0].extra == {
        "provider_name": "Tushare Display Name",
        "source_type": "tushare",
        **({"actual_source": reported_source} if reported_source else {}),
    }


@pytest.mark.parametrize("row_id", [None, "", " ", 7, {"id": "bad"}, "x" * 201])
def test_valid_response_provenance_survives_an_invalid_optional_row_id(row_id: object) -> None:
    from apps.data_center.infrastructure._provider_adapter_tushare import (
        _optional_quote_transport_extra,
    )

    response = {
        "raw_payload_hash": "a" * 64,
        "raw_payload_scope": "batch_response_body",
        "response_completed_at": "2026-10-23T07:00:00+00:00",
    }
    result = _optional_quote_transport_extra(
        SimpleNamespace(extra={**response, "source_record_id": row_id})
    )
    assert result == response
