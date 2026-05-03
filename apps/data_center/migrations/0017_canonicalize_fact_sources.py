"""Canonicalize stored fact sources to provider source_type."""

from django.db import migrations


def _build_provider_source_map(ProviderConfig):
    return {
        str(row["name"]): str(row["source_type"])
        for row in ProviderConfig.objects.exclude(name="").exclude(source_type="").values(
            "name",
            "source_type",
        )
        if str(row["name"]) and str(row["source_type"])
    }


def _merge_extra_payload(instance, *, target_source: str, provider_name: str) -> bool:
    if not hasattr(instance, "extra"):
        return False

    next_extra = dict(instance.extra or {})
    changed = False
    if next_extra.get("source_type") != target_source:
        next_extra["source_type"] = target_source
        changed = True
    if next_extra.get("provider_name") != provider_name:
        next_extra["provider_name"] = provider_name
        changed = True
    if changed:
        instance.extra = next_extra
    return changed


def _same_payload(left, right, compare_fields):
    for field in compare_fields:
        if getattr(left, field) != getattr(right, field):
            return False
    return True


def _canonicalize_model(
    model,
    provider_source_map,
    *,
    key_fields,
    compare_fields,
):
    queryset = model.objects.filter(source__in=list(provider_source_map.keys())).order_by("id")
    for instance in queryset.iterator():
        provider_name = str(instance.source or "")
        target_source = str(provider_source_map.get(provider_name) or "").strip()
        if not target_source or target_source == provider_name:
            continue

        lookup = {
            field: getattr(instance, field)
            for field in key_fields
            if field != "source"
        }
        lookup["source"] = target_source
        conflict = model.objects.filter(**lookup).exclude(id=instance.id).first()

        if conflict is not None:
            if _same_payload(instance, conflict, compare_fields):
                if _merge_extra_payload(
                    conflict,
                    target_source=target_source,
                    provider_name=provider_name,
                ):
                    conflict.save(update_fields=["extra"])
                instance.delete()
            continue

        update_fields = ["source"]
        instance.source = target_source
        if _merge_extra_payload(
            instance,
            target_source=target_source,
            provider_name=provider_name,
        ):
            update_fields.append("extra")
        instance.save(update_fields=update_fields)


def apply_canonical_fact_sources(apps, schema_editor):
    ProviderConfig = apps.get_model("data_center", "ProviderConfigModel")
    MacroFact = apps.get_model("data_center", "MacroFactModel")
    PriceBar = apps.get_model("data_center", "PriceBarModel")
    QuoteSnapshot = apps.get_model("data_center", "QuoteSnapshotModel")
    FundNavFact = apps.get_model("data_center", "FundNavFactModel")
    FinancialFact = apps.get_model("data_center", "FinancialFactModel")
    ValuationFact = apps.get_model("data_center", "ValuationFactModel")
    SectorMembershipFact = apps.get_model("data_center", "SectorMembershipFactModel")
    NewsFact = apps.get_model("data_center", "NewsFactModel")
    CapitalFlowFact = apps.get_model("data_center", "CapitalFlowFactModel")

    provider_source_map = _build_provider_source_map(ProviderConfig)
    if not provider_source_map:
        return

    _canonicalize_model(
        MacroFact,
        provider_source_map,
        key_fields=("indicator_code", "reporting_period", "source", "revision_number"),
        compare_fields=("value", "unit", "published_at", "quality"),
    )
    _canonicalize_model(
        PriceBar,
        provider_source_map,
        key_fields=("asset_code", "bar_date", "freq", "adjustment", "source"),
        compare_fields=("open", "high", "low", "close", "volume", "amount"),
    )
    _canonicalize_model(
        QuoteSnapshot,
        provider_source_map,
        key_fields=("asset_code", "snapshot_at", "source"),
        compare_fields=(
            "current_price",
            "open",
            "high",
            "low",
            "prev_close",
            "volume",
            "amount",
            "bid",
            "ask",
        ),
    )
    _canonicalize_model(
        FundNavFact,
        provider_source_map,
        key_fields=("fund_code", "nav_date", "source"),
        compare_fields=("nav", "acc_nav", "daily_return"),
    )
    _canonicalize_model(
        FinancialFact,
        provider_source_map,
        key_fields=("asset_code", "period_end", "period_type", "metric_code", "source"),
        compare_fields=("value", "unit", "report_date"),
    )
    _canonicalize_model(
        ValuationFact,
        provider_source_map,
        key_fields=("asset_code", "val_date", "source"),
        compare_fields=(
            "pe_ttm",
            "pe_static",
            "pb",
            "ps_ttm",
            "market_cap",
            "float_market_cap",
            "dv_ratio",
        ),
    )
    _canonicalize_model(
        SectorMembershipFact,
        provider_source_map,
        key_fields=("asset_code", "sector_code", "effective_date", "source"),
        compare_fields=("sector_name", "expiry_date", "weight"),
    )
    _canonicalize_model(
        NewsFact,
        provider_source_map,
        key_fields=("source", "external_id"),
        compare_fields=("asset_code", "title", "summary", "url", "published_at", "sentiment_score"),
    )
    _canonicalize_model(
        CapitalFlowFact,
        provider_source_map,
        key_fields=("asset_code", "flow_date", "source"),
        compare_fields=(
            "main_net",
            "retail_net",
            "super_large_net",
            "large_net",
            "medium_net",
            "small_net",
        ),
    )


def revert_canonical_fact_sources(apps, schema_editor):
    # Canonical source_type is the new long-term storage contract.
    return


class Migration(migrations.Migration):

    dependencies = [
        ("data_center", "0016_seed_macro_governance_scope_metadata"),
    ]

    operations = [
        migrations.RunPython(
            apply_canonical_fact_sources,
            revert_canonical_fact_sources,
        ),
    ]
