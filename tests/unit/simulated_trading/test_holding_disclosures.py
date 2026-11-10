"""Contract tests for the account-scoped published financial disclosure read."""

from __future__ import annotations

import pytest

from apps.data_center.domain.financial_source_evidence import FinancialFactSourceEvidence
from apps.simulated_trading.application.holding_disclosures import (
    GetHoldingDisclosuresUseCase,
)

_ASSET_CODE = "600000.SH"
_ACCOUNT_ID = 17
_ACTOR_ID = 23
_RAW_HASH = "a" * 64


def _fact_row(
    *,
    asset_code: str = _ASSET_CODE,
    available_at: str | None = "2026-10-30T12:00:00+08:00",
    announced_at: str | None = "2026-10-30T11:30:00+08:00",
) -> dict[str, object]:
    """Return one normalized Data Center financial fact row."""

    return {
        "asset_code": asset_code,
        "period_end": "2026-09-30",
        "period_type": "quarterly",
        "metric_code": "net_profit",
        "value": 1250000.0,
        "unit": "CNY",
        "source": "akshare",
        "report_date": "2026-10-30",
        "available_at": available_at,
        "fetched_at": "2026-10-30T12:05:00+08:00",
        "source_evidence": {
            "announced_at": announced_at,
            "source_record_id": "vendor-row-17",
            "raw_payload_hash": _RAW_HASH,
        },
    }


def _published_payload(rows: list[dict[str, object]]) -> dict[str, object]:
    """Return one usable current publication response."""

    return {
        "rows": rows,
        "publication_id": "financial-publication-17",
        "publication_key": "current",
        "dataset_key": "equity.financial.fact",
        "must_not_use_for_decision": False,
        "blocked_reason": "",
        "freshness_status": "fresh",
        "reliability": "source_bound",
    }


class _HoldingReader:
    """In-memory account and exact-held-security scope port."""

    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[int, int, str]] = []

    def has_readable_active_holding(
        self, *, actor_user_id: int, account_id: int, asset_code: str
    ) -> bool:
        self.calls.append((actor_user_id, account_id, asset_code))
        return self.allowed


class _FinancialFactsReader:
    """In-memory published-financial-facts public port."""

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, int, str]] = []

    def read_published_financial_facts(
        self, asset_code: str, *, limit: int, publication_key: str
    ) -> dict[str, object]:
        self.calls.append((asset_code, limit, publication_key))
        return self.payload


def _use_case(
    *, allowed: bool = True, payload: dict[str, object] | None = None
) -> tuple[GetHoldingDisclosuresUseCase, _HoldingReader, _FinancialFactsReader]:
    holding_reader = _HoldingReader(allowed=allowed)
    facts_reader = _FinancialFactsReader(payload or _published_payload([_fact_row()]))
    return (
        GetHoldingDisclosuresUseCase(
            holding_reader=holding_reader,
            financial_facts_reader=facts_reader,
        ),
        holding_reader,
        facts_reader,
    )


def _execute(use_case: GetHoldingDisclosuresUseCase) -> dict[str, object]:
    """Run the exact account and asset request used by the API."""

    return use_case.execute(
        actor_user_id=_ACTOR_ID,
        account_id=_ACCOUNT_ID,
        asset_code=_ASSET_CODE,
    ).to_payload()


def test_usable_rows_remain_partial_and_carry_original_clocks() -> None:
    """A published financial metric is never promoted to complete event coverage."""

    use_case, holding_reader, facts_reader = _use_case()

    result = _execute(use_case)

    assert result["outcome"] == "partial"
    assert result["scope"] == "simulation_only"
    assert result["read_only"] is True
    assert result["must_not_use_for_decision"] is True
    assert result["must_not_execute"] is True
    assert result["freshness"] == "fresh"
    assert result["reliability"] == "source_bound"
    assert result["as_of"]
    rows = result["rows"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert isinstance(row, dict)
    assert row["asset_code"] == _ASSET_CODE
    assert row["report_date"] == "2026-10-30"
    assert row["announced_at"] == "2026-10-30T11:30:00+08:00"
    assert row["available_at"] == "2026-10-30T12:00:00+08:00"
    assert row["fetched_at"] == "2026-10-30T12:05:00+08:00"
    assert row["source_record_id"] == "vendor-row-17"
    assert row["raw_payload_hash"] == _RAW_HASH
    assert holding_reader.calls == [(_ACTOR_ID, _ACCOUNT_ID, _ASSET_CODE)]
    assert facts_reader.calls == [(_ASSET_CODE, 20, "current")]


def test_unreadable_account_or_unheld_asset_is_uniformly_blocked_before_source_read() -> None:
    """Account scope and exact-holding failures disclose neither account nor source data."""

    use_case, _, facts_reader = _use_case(allowed=False)

    result = _execute(use_case)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "account_scope_or_holding_unavailable"
    assert result["rows"] == []
    assert facts_reader.calls == []


def test_explicit_data_center_block_is_returned_as_blocked_business_payload() -> None:
    """A normal missing or stale publication remains a user-readable blocked result."""

    payload = {
        "rows": [],
        "publication_id": None,
        "must_not_use_for_decision": True,
        "blocked_reason": "canonical_publication_missing",
        "freshness_status": "missing",
    }
    use_case, _, _ = _use_case(payload=payload)

    result = _execute(use_case)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "canonical_publication_missing"
    assert result["freshness"] == "missing"
    assert result["reliability"] == "unknown"
    assert result["rows"] == []


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"rows": []}, "published_financial_gate_invalid"),
        (
            {
                **_published_payload([_fact_row()]),
                "publication_id": None,
            },
            "published_financial_publication_identity_missing",
        ),
        (
            {
                **_published_payload([_fact_row()]),
                "rows": "not-a-list",
            },
            "published_financial_rows_invalid",
        ),
    ],
)
def test_malformed_publication_gate_or_rows_fail_closed(
    payload: dict[str, object], reason: str
) -> None:
    """Missing gates, identities, and row containers cannot become usable evidence."""

    use_case, _, _ = _use_case(payload=payload)

    result = _execute(use_case)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == reason
    assert result["rows"] == []


def test_missing_source_clocks_stay_null_without_fallback_or_precision_change() -> None:
    """Missing announcement and availability clocks remain explicit null values."""

    use_case, _, _ = _use_case(
        payload=_published_payload(
            [
                {
                    **_fact_row(available_at=None, announced_at=None),
                    "report_date": "2026-10-30",
                }
            ]
        )
    )

    result = _execute(use_case)

    rows = result["rows"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["announced_at"] is None
    assert rows[0]["available_at"] is None
    assert rows[0]["report_date"] == "2026-10-30"


def test_empty_optional_source_evidence_matches_financial_fact_serialization() -> None:
    """The domain's empty optional evidence identifiers remain explicit nulls."""

    row = {
        **_fact_row(available_at=None, announced_at=None),
        "source_evidence": FinancialFactSourceEvidence(
            announced_at=None,
            source_record_id="",
            raw_payload_hash="",
        ).to_dict(),
    }
    use_case, _, _ = _use_case(payload=_published_payload([row]))

    result = _execute(use_case)

    assert result["outcome"] == "partial"
    rows = result["rows"]
    assert isinstance(rows, list) and isinstance(rows[0], dict)
    assert rows[0]["announced_at"] is None
    assert rows[0]["source_record_id"] is None
    assert rows[0]["raw_payload_hash"] is None


@pytest.mark.parametrize(
    "row",
    [
        _fact_row(available_at="2099-01-01T00:00:00+00:00"),
        _fact_row(asset_code="000001.SZ"),
        {**_fact_row(), "report_date": "2026-10-30T00:00:00+08:00"},
        {**_fact_row(), "period_end": "2026-09-30T00:00:00+08:00"},
        {**_fact_row(), "fetched_at": "2026-10-30T12:05:00"},
        {**_fact_row(), "value": True},
    ],
)
def test_future_cross_asset_and_malformed_evidence_fail_closed(row: dict[str, object]) -> None:
    """Future clocks, cross-asset rows, and invalid date/time precision block all rows."""

    use_case, _, _ = _use_case(payload=_published_payload([row]))

    result = _execute(use_case)

    assert result["outcome"] == "blocked"
    assert result["rows"] == []
    assert result["blocked_reason"] in {
        "published_financial_row_asset_mismatch",
        "published_financial_row_time_invalid",
        "published_financial_row_future_time",
        "published_financial_row_date_invalid",
        "published_financial_row_value_invalid",
    }


def test_public_port_overreturn_fails_closed() -> None:
    """A public port that exceeds its requested page cannot hide bad extra rows."""

    rows = [_fact_row() for _ in range(25)]
    use_case, _, facts_reader = _use_case(payload=_published_payload(rows))

    result = _execute(use_case)

    assert result["outcome"] == "blocked"
    assert result["blocked_reason"] == "published_financial_rows_limit_exceeded"
    assert result["rows"] == []
    assert facts_reader.calls == [(_ASSET_CODE, 20, "current")]


def test_repeated_reads_only_repeat_the_two_read_ports() -> None:
    """Repeat requests remain reads and never invoke a write-capable dependency."""

    use_case, holding_reader, facts_reader = _use_case()

    _execute(use_case)
    _execute(use_case)

    assert len(holding_reader.calls) == 2
    assert len(facts_reader.calls) == 2
