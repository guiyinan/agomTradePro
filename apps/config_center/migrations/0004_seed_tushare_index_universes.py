from django.db import migrations, models

_SEEDED_UNIVERSES = {
    "csi300": ("沪深 300", "000300.SH"),
    "csi500": ("中证 500", "000905.SH"),
    "sse50": ("上证 50", "000016.SH"),
    "csi1000": ("中证 1000", "000852.SH"),
}
_SEED_MARKER = "system-seeded Tushare index universe"


def seed_tushare_index_universes(apps, schema_editor) -> None:
    universe_model = apps.get_model("config_center", "AlphaUniverseConfigModel")
    for universe_id, (name, index_code) in _SEEDED_UNIVERSES.items():
        universe_model.objects.get_or_create(
            universe_id=universe_id,
            defaults={
                "name": name,
                "source_type": "tushare_index",
                "stock_codes": [],
                "filters": {"index_code": index_code},
                "is_active": True,
                "description": _SEED_MARKER,
            },
        )


def remove_seeded_tushare_index_universes(apps, schema_editor) -> None:
    universe_model = apps.get_model("config_center", "AlphaUniverseConfigModel")
    universe_model.objects.filter(
        universe_id__in=list(_SEEDED_UNIVERSES),
        source_type="tushare_index",
        description=_SEED_MARKER,
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("config_center", "0003_systemsettingsmodel_backup_download_token_state"),
    ]

    operations = [
        migrations.AlterField(
            model_name="alphauniverseconfigmodel",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("manual", "手工代码清单"),
                    ("csv", "CSV 导入代码清单"),
                    ("data_center_filter", "Data Center 条件生成"),
                    ("tushare_index", "Tushare 指数成分"),
                ],
                default="manual",
                max_length=32,
                verbose_name="来源类型",
            ),
        ),
        migrations.RunPython(
            seed_tushare_index_universes,
            remove_seeded_tushare_index_universes,
        ),
    ]
