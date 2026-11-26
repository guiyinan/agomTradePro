"""Version-aware writes for market price bars and valuation facts."""

from apps.data_center.domain.entities import PriceBar, ValuationFact

from .models import PriceBarModel, ValuationFactModel
from .published_fact_versions import upsert_publication_safe_facts


def upsert_price_bars(bars: list[PriceBar], natural_key: tuple[str, ...]) -> int:
    """Persist daily corrections without rewriting publication-referenced bars."""
    if not bars:
        return 0
    models = [
        PriceBarModel(
            asset_code=bar.asset_code,
            bar_date=bar.bar_date,
            freq=bar.freq,
            adjustment=bar.adjustment.value,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            amount=bar.amount,
            source=bar.source,
            ingested_run_id=bar.ingested_run_id or None,
        )
        for bar in bars
    ]
    return upsert_publication_safe_facts(
        PriceBarModel,
        models,
        natural_key=natural_key,
        update_fields=(
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "ingested_run_id",
        ),
    )


def upsert_valuation_facts(facts: list[ValuationFact], natural_key: tuple[str, ...]) -> int:
    """Upsert facts by natural key while refreshing values and provenance."""

    if not facts:
        return 0
    models = [
        ValuationFactModel(
            asset_code=fact.asset_code,
            val_date=fact.val_date,
            pe_ttm=fact.pe_ttm,
            pe_static=fact.pe_static,
            pb=fact.pb,
            ps_ttm=fact.ps_ttm,
            market_cap=fact.market_cap,
            float_market_cap=fact.float_market_cap,
            dv_ratio=fact.dv_ratio,
            source=fact.source,
            observed_at=fact.observed_at,
            available_at=fact.available_at,
            fetched_at=fact.fetched_at,
            extra=fact.extra,
            source_record_id=fact.source_record_id,
            raw_payload_hash=fact.raw_payload_hash,
            ingested_run_id=fact.ingested_run_id or None,
        )
        for fact in facts
    ]
    return upsert_publication_safe_facts(
        ValuationFactModel,
        models,
        natural_key=natural_key,
        update_fields=(
            "pe_ttm",
            "pe_static",
            "pb",
            "ps_ttm",
            "market_cap",
            "float_market_cap",
            "dv_ratio",
            "observed_at",
            "available_at",
            "fetched_at",
            "extra",
            "source_record_id",
            "raw_payload_hash",
            "ingested_run_id",
        ),
    )
