"""Real-reader synthetic inputs for disposable TUX08 acceptance only.

This seeds typed facts and evidence, not owner responses. Calendar transport,
stored health and a one-stock universe are explicitly synthetic. It grants no
production authority and changes no freshness threshold or business rule.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.conf import settings

from apps.data_center import composition
from apps.data_center.application import market_calendar
from apps.data_center.domain.entities import (
    MarketThermometerComponentScore,
    MarketThermometerConfig,
    MarketThermometerSnapshot,
)
from apps.data_center.domain.market_time import cn_market_session_close_utc
from core.health_checks import is_decision_ready, run_decision_readiness_checks
from tests.support.tui_research import calendar_transport as calendar
from tests.support.tui_research import financial_consumer_state as financial
from tests.support.tui_research import market_consumer_state as market
from tests.support.tui_research import optional_consumer_state as optional
from tests.support.tui_research import readiness_support as support


@dataclass(frozen=True)
class ResearchScenario:
    """Source-bearing test objects and their original observation clocks."""

    financial: financial.FinancialConsumerState
    observed_at: datetime
    closed_session: date
    artifact_root: Path
    calendar_sha256: str
    strict_checks: dict[str, object]


@contextmanager
def research_scenario(
    *, with_optionals: bool = True, financial_age_days: int = 1, require_ready: bool = True
) -> Iterator[ResearchScenario]:
    """Seed an empty disposable database and preserve the actual owner pipeline.

    Two explicit synthetic sessions are supplied as controlled calendar input;
    they are not an exchange calendar claim or inferred weekday schedule.
    pytest owns the fresh database lifetime. This context restores only its
    temporary calendar composition seam; teardown must flush its test database.
    """

    support.require_tux08_sqlite_database()
    if financial_age_days < 1:
        raise ValueError("Synthetic financial age must be positive")
    observed = datetime.now(UTC)
    end = observed.astimezone(ZoneInfo("Asia/Shanghai")).date()
    sessions = (end - timedelta(days=2), end - timedelta(days=1))
    start = end - timedelta(days=45)
    root = (
        Path(
            getattr(
                settings,
                "TUX08_ARTIFACT_ROOT",
                Path(settings.BASE_DIR) / ".tmp" / "tux08-fixture-artifacts",
            )
        )
        / "source-artifacts"
        / uuid4().hex
    )
    root.mkdir(parents=True)
    body = json.dumps(
        {
            "coverage_start": start.isoformat(),
            "coverage_end": end.isoformat(),
            "open_sessions": [day.isoformat() for day in sessions],
            "observed_at": observed.isoformat(),
            "source": "synthetic fixture",
        },
        sort_keys=True,
    ).encode()
    service, artifacts = calendar.build_synthetic_calendar_service(
        open_sessions=sessions,
        coverage_start=start,
        coverage_end=end,
        observed_at=observed,
        raw_json=body,
        tmp_path=root,
    )
    original = composition.build_model_market_data_service
    composition.build_model_market_data_service = lambda: service
    market_calendar.load_cn_market_calendar_evidence.cache_clear()
    try:
        closed = market_calendar.latest_closed_cn_market_session(datetime.now(UTC))
        if closed not in sessions:
            raise AssertionError("Actual resolver did not select an explicit fixture session")
        assert closed is not None
        config = MarketThermometerConfig()
        components = [
            MarketThermometerComponentScore(
                component_key=key,
                label=key,
                indicator_code=f"tux08:{key}",
                score=50.0,
                weight=weight,
                current_value=1.0,
                unit="synthetic",
                age_days=(end - closed).days,
                reason="Controlled consumer input; not calculated production evidence",
            )
            for key, weight in config.component_weights.items()
        ]
        snapshot = MarketThermometerSnapshot(
            observed_at=closed,
            score=50.0,
            band="warm",
            change_5d=None,
            change_20d=None,
            components=components,
            valid_component_count=len(components),
            data_source="tux08-fixture",
        )
        support.seed_readiness_support(
            source_observed_at=observed, closed_session=closed, snapshot=snapshot
        )
        financial_date = end - timedelta(days=financial_age_days)
        financial_state = financial.prepare_financial_consumer_state(
            root,
            period_type="quarterly",
            period_end=date(financial_date.year, ((financial_date.month - 1) // 3) * 3 + 1, 1)
            - timedelta(days=1),
            report_date=financial_date,
            announced_at=datetime.combine(financial_date, time(6), UTC),
            available_at=datetime.combine(financial_date, time(6, 30), UTC),
        )
        market.prepare_market_consumer_state(
            tmp_path=root,
            governance_root=Path(settings.BASE_DIR) / "governance",
            clocks=market.MarketConsumerClocks(
                closed_session=closed,
                price_observed_at=cn_market_session_close_utc(closed),
                valuation_observed_at=observed,
                quote_snapshot_at=observed,
                available_at=observed,
                fetched_at=observed,
            ),
            publication_clock=lambda: datetime.now(UTC),
            price=market.PriceSeed("600000.SH", closed, 12.1, 12.5, 12.0, 12.34, 1000.0, 12340.0),
            quotes=(
                market.QuoteSeed("510300.SH", 4.0),
                market.QuoteSeed("000300.SH", 4000.0),
                market.QuoteSeed("600000.SH", 12.34),
            ),
            valuation=market.ValuationSeed("600000.SH", closed, pe_ttm=8.0, pb=0.8),
            run_id=str(uuid4()),
        )
        if with_optionals:
            optional.prepare_optional_consumer_state(
                tmp_path=root,
                governance_root=Path(settings.BASE_DIR) / "governance",
                clocks=optional.OptionalConsumerClocks(
                    closed_session=closed,
                    news_published_at=observed,
                    available_at=observed,
                    fetched_at=observed,
                ),
                publication_clock=lambda: datetime.now(UTC),
                run_id=str(uuid4()),
            )
        checks = run_decision_readiness_checks()
        if require_ready and not is_decision_ready(checks):
            raise AssertionError(f"Actual readiness checks did not pass: {checks}")
        yield ResearchScenario(
            financial_state, observed, closed, root, artifacts.sha256_hex, checks
        )
    finally:
        composition.build_model_market_data_service = original
        market_calendar.load_cn_market_calendar_evidence.cache_clear()
