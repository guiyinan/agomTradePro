from django.db import migrations

_SEED_MARKER = "system-seeded asset pool thresholds"
_SEEDED_CONFIGS = {
    "equity": {
        "name": "system_equity_pool_thresholds",
        "min_total_score": 60.0,
        "min_regime_score": 50.0,
        "min_policy_score": 50.0,
        "max_total_score": 30.0,
        "max_regime_score": 40.0,
        "max_policy_score": 40.0,
        "max_pe_ratio": 50.0,
        "max_pb_ratio": 10.0,
    },
    "fund": {
        "name": "system_fund_pool_thresholds",
        "min_total_score": 65.0,
        "min_regime_score": 55.0,
        "min_policy_score": 50.0,
        "max_total_score": 35.0,
        "max_regime_score": 40.0,
        "max_policy_score": 40.0,
    },
    "bond": {
        "name": "system_bond_pool_thresholds",
        "min_total_score": 60.0,
        "min_regime_score": 50.0,
        "min_policy_score": 60.0,
        "max_total_score": 30.0,
        "max_regime_score": 40.0,
        "max_policy_score": 40.0,
    },
}


def seed_asset_pool_configs(apps, schema_editor) -> None:
    config_model = apps.get_model("asset_analysis", "AssetPoolConfig")
    for asset_category, values in _SEEDED_CONFIGS.items():
        has_active_config = config_model.objects.filter(
            asset_category=asset_category,
            pool_type="investable",
            is_active=True,
        ).exists()
        if has_active_config:
            continue
        config_model.objects.create(
            asset_category=asset_category,
            pool_type="investable",
            description=_SEED_MARKER,
            is_active=True,
            **values,
        )


def remove_seeded_asset_pool_configs(apps, schema_editor) -> None:
    config_model = apps.get_model("asset_analysis", "AssetPoolConfig")
    config_model.objects.filter(
        name__in=[values["name"] for values in _SEEDED_CONFIGS.values()],
        description=_SEED_MARKER,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("asset_analysis", "0004_assetconfigmodel"),
    ]

    operations = [
        migrations.RunPython(
            seed_asset_pool_configs,
            remove_seeded_asset_pool_configs,
        ),
    ]
