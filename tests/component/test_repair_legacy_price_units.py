import gzip
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from apps.data_center.infrastructure.models import AssetMasterModel, PriceBarModel

pytestmark = pytest.mark.django_db


def prepare(tmp_path, expected=1):
    AssetMasterModel.objects.create(
        code="000001.SZ", name="Test", asset_type="stock", exchange="SZSE"
    )
    row = PriceBarModel.objects.create(
        asset_code="000001.SZ",
        bar_date=date(2026, 7, 31),
        source="tushare",
        open=10,
        high=11,
        low=9,
        close=10,
        volume=12,
        amount=12,
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "marker": "test-units-v2",
                "fetched_before": (timezone.now() + timedelta(minutes=1)).isoformat(),
                "rules": [
                    {
                        "source": "tushare",
                        "asset_type": "stock",
                        "expected": expected,
                        "volume_factor": "100",
                        "amount_factor": "1000",
                        "adjustment": "none",
                        "evidence": "Tushare daily documents hands and thousand CNY",
                    }
                ],
            }
        )
    )
    return row, plan


def test_dry_run_apply_archive_and_idempotency(tmp_path):
    row, plan = prepare(tmp_path)
    fetched_at = row.fetched_at
    call_command("repair_legacy_price_units", plan=str(plan))
    row.refresh_from_db()
    assert row.volume == 12
    for _ in range(2):
        call_command(
            "repair_legacy_price_units", plan=str(plan), apply=True, audit_dir=str(tmp_path)
        )
    row.refresh_from_db()
    assert (row.volume, row.amount) == (Decimal(1200), Decimal(12000))
    assert row.fetched_at == fetched_at
    assert row.bar_date == date(2026, 7, 31)
    assert row.revision_number == 2
    archives = list(tmp_path.glob("*.gz"))
    assert len(archives) == 1
    with gzip.open(archives[0], "rt") as stream:
        original = json.loads(stream.readline())
    assert Decimal(original["volume"]) == 12
    assert original["id"] == row.id


def test_cohort_mismatch_aborts_before_write(tmp_path):
    row, plan = prepare(tmp_path, expected=2)
    with pytest.raises(CommandError, match="Cohort changed"):
        call_command(
            "repair_legacy_price_units", plan=str(plan), apply=True, audit_dir=str(tmp_path)
        )
    row.refresh_from_db()
    assert row.volume == 12
    assert not list(tmp_path.glob("*.gz"))


def test_adjusted_collision_preserves_both_records(tmp_path):
    row, plan = prepare(tmp_path)
    contents = json.loads(plan.read_text())
    contents["rules"][0]["adjustment"] = "forward"
    plan.write_text(json.dumps(contents))
    PriceBarModel.objects.create(
        asset_code=row.asset_code,
        bar_date=row.bar_date,
        source=row.source,
        adjustment="forward",
        open=10,
        high=11,
        low=9,
        close=10,
    )
    with pytest.raises(CommandError, match="Target adjustment"):
        call_command(
            "repair_legacy_price_units", plan=str(plan), apply=True, audit_dir=str(tmp_path)
        )
    row.refresh_from_db()
    assert row.adjustment == "none"
