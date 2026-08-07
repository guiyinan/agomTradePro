"""Reconcile the frozen Fund NAV projection into the canonical Data Center."""

from __future__ import annotations

import hashlib
import json
import uuid
from decimal import Decimal, InvalidOperation

from django.db import migrations
from django.utils import timezone

DATASET_KEY = "fund.nav"
SOURCE = "fund_legacy_repo"
MIGRATION_MARKER = "fund.0004_reconcile_legacy_nav_to_data_center"
CLASSIFICATIONS = (
    "same",
    "expected_difference",
    "data_missing",
    "semantic_conflict",
    "code_defect",
)


def _decimal_text(value, *, field_name, positive):
    if value is None:
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"invalid_{field_name}") from exc
    if not decimal_value.is_finite() or (positive and decimal_value <= 0):
        raise RuntimeError(f"invalid_{field_name}")
    return format(decimal_value.normalize(), "f")


def _natural_key(fund_code, nav_date):
    normalized_code = str(fund_code or "").strip()
    if not normalized_code or normalized_code != str(fund_code):
        raise RuntimeError("invalid_fund_code")
    if nav_date is None:
        raise RuntimeError("invalid_nav_date")
    return f"{normalized_code}:{nav_date.isoformat()}:{SOURCE}"


def _snapshot_value(*, nav, acc_nav, daily_return):
    return {
        "nav": _decimal_text(nav, field_name="nav", positive=True),
        "acc_nav": _decimal_text(acc_nav, field_name="acc_nav", positive=True),
        "daily_return": _decimal_text(
            daily_return,
            field_name="daily_return",
            positive=False,
        ),
    }


def _snapshot_hash(snapshot):
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _add_unique(snapshot, natural_key, value, *, side):
    if natural_key in snapshot:
        raise RuntimeError(f"duplicate_{side}_natural_key:{natural_key}")
    snapshot[natural_key] = value


def _legacy_snapshot(Legacy):
    snapshot = {}
    rows = {}
    queryset = Legacy._default_manager.order_by("fund_code", "nav_date", "id").values(
        "id",
        "fund_code",
        "nav_date",
        "unit_nav",
        "accum_nav",
        "daily_return",
        "created_at",
    )
    for row in queryset.iterator(chunk_size=2000):
        natural_key = _natural_key(row["fund_code"], row["nav_date"])
        value = _snapshot_value(
            nav=row["unit_nav"],
            acc_nav=row["accum_nav"],
            daily_return=row["daily_return"],
        )
        _add_unique(snapshot, natural_key, value, side="legacy")
        rows[natural_key] = row
    return snapshot, rows


def _canonical_snapshot(Canonical):
    snapshot = {}
    rows = {}
    queryset = (
        Canonical._default_manager.filter(source=SOURCE)
        .order_by("fund_code", "nav_date", "id")
        .values("id", "fund_code", "nav_date", "nav", "acc_nav", "daily_return", "extra")
    )
    for row in queryset.iterator(chunk_size=2000):
        natural_key = _natural_key(row["fund_code"], row["nav_date"])
        value = _snapshot_value(
            nav=row["nav"],
            acc_nav=row["acc_nav"],
            daily_return=row["daily_return"],
        )
        _add_unique(snapshot, natural_key, value, side="canonical")
        rows[natural_key] = row
    return snapshot, rows


def _assert_repairable(legacy, canonical):
    canonical_only = sorted(set(canonical) - set(legacy))
    if canonical_only:
        raise RuntimeError(f"canonical_only:{canonical_only[:10]}")
    conflicts = sorted(
        natural_key
        for natural_key in set(legacy) & set(canonical)
        if legacy[natural_key] != canonical[natural_key]
    )
    if conflicts:
        raise RuntimeError(f"semantic_conflict:{conflicts[:10]}")
    return sorted(set(legacy) - set(canonical))


def _raw_payload_hash(row):
    payload = {
        "legacy_pk": row["id"],
        "fund_code": row["fund_code"],
        "nav_date": row["nav_date"].isoformat(),
        "unit_nav": str(row["unit_nav"]),
        "accum_nav": str(row["accum_nav"]),
        "daily_return": row["daily_return"],
        "created_at": row["created_at"].isoformat(),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _evidence_id(legacy_hash, canonical_hash):
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"agomtradepro:{DATASET_KEY}:{MIGRATION_MARKER}:{legacy_hash}:{canonical_hash}",
    )


def forward_reconcile_fund_nav(apps, schema_editor):
    Legacy = apps.get_model("fund", "FundNetValueModel")
    Canonical = apps.get_model("data_center", "FundNavFactModel")
    Evidence = apps.get_model("data_center", "ReconciliationEvidenceModel")

    legacy, legacy_rows = _legacy_snapshot(Legacy)
    canonical, _ = _canonical_snapshot(Canonical)
    missing_keys = _assert_repairable(legacy, canonical)
    predicted = dict(canonical)
    for natural_key in missing_keys:
        predicted[natural_key] = legacy[natural_key]
    legacy_hash = _snapshot_hash(legacy)
    predicted_hash = _snapshot_hash(predicted)
    if legacy_hash != predicted_hash:
        raise RuntimeError("predicted_snapshot_mismatch")
    evidence_id = _evidence_id(legacy_hash, predicted_hash)

    repairs = []
    for natural_key in missing_keys:
        row = legacy_rows[natural_key]
        repairs.append(
            Canonical(
                fund_code=row["fund_code"],
                nav_date=row["nav_date"],
                nav=row["unit_nav"],
                acc_nav=row["accum_nav"],
                daily_return=row["daily_return"],
                source=SOURCE,
                extra={
                    "migration": MIGRATION_MARKER,
                    "legacy_pk": row["id"],
                    "reconciliation_evidence_id": str(evidence_id),
                },
                contract_version="1.0",
                schema_version="1.0",
                source_record_id=f"fund_net_value:{row['id']}",
                raw_payload_hash=_raw_payload_hash(row),
                quality_status="accepted",
                revision_number=1,
                available_at=row["created_at"],
            )
        )
    if repairs:
        Canonical._default_manager.bulk_create(repairs, batch_size=1000)

    final, final_rows = _canonical_snapshot(Canonical)
    if final != legacy:
        raise RuntimeError("post_repair_snapshot_mismatch")
    final_hash = _snapshot_hash(final)
    repaired_keys = sorted(
        natural_key
        for natural_key, row in final_rows.items()
        if isinstance(row.get("extra"), dict) and row["extra"].get("migration") == MIGRATION_MARKER
    )
    evidence_rows = [
        {
            "natural_key": natural_key,
            "classification": "expected_difference",
            "legacy_value": legacy[natural_key],
            "canonical_value": final[natural_key],
            "action": "backfilled_missing_canonical_fact",
        }
        for natural_key in repaired_keys
    ]
    counts = dict.fromkeys(CLASSIFICATIONS, 0)
    counts["same"] = len(final) - len(repaired_keys)
    counts["expected_difference"] = len(repaired_keys)
    defaults = {
        "dataset_key": DATASET_KEY,
        "legacy_snapshot_hash": legacy_hash,
        "canonical_snapshot_hash": final_hash,
        "classification_counts": counts,
        "is_clean": True,
        "observed_at": timezone.now(),
        "rows": evidence_rows,
    }
    evidence, created = Evidence._default_manager.get_or_create(
        evidence_id=evidence_id,
        defaults=defaults,
    )
    if not created:
        for field_name in (
            "dataset_key",
            "legacy_snapshot_hash",
            "canonical_snapshot_hash",
            "classification_counts",
            "is_clean",
            "rows",
        ):
            if getattr(evidence, field_name) != defaults[field_name]:
                raise RuntimeError(f"reconciliation_evidence_conflict:{field_name}")


def reverse_reconcile_fund_nav(apps, schema_editor):
    Legacy = apps.get_model("fund", "FundNetValueModel")
    Canonical = apps.get_model("data_center", "FundNavFactModel")
    Evidence = apps.get_model("data_center", "ReconciliationEvidenceModel")
    legacy, _ = _legacy_snapshot(Legacy)
    canonical, _ = _canonical_snapshot(Canonical)
    evidence_ids = {str(_evidence_id(_snapshot_hash(legacy), _snapshot_hash(canonical)))}
    repaired_ids = []
    queryset = Canonical._default_manager.filter(source=SOURCE).values("id", "extra")
    for row in queryset.iterator(chunk_size=2000):
        extra = row.get("extra")
        if not isinstance(extra, dict) or extra.get("migration") != MIGRATION_MARKER:
            continue
        repaired_ids.append(row["id"])
        raw_evidence_id = str(extra.get("reconciliation_evidence_id") or "").strip()
        if raw_evidence_id:
            evidence_ids.add(raw_evidence_id)
    if repaired_ids:
        Canonical._default_manager.filter(id__in=repaired_ids).delete()
    if evidence_ids:
        Evidence._default_manager.filter(evidence_id__in=sorted(evidence_ids)).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("fund", "0003_fundholdingmodel_fund_holding_amount_nonnegative_and_more"),
        ("data_center", "0055_reconciliationevidencemodel"),
    ]

    operations = [
        migrations.RunPython(
            forward_reconcile_fund_nav,
            reverse_reconcile_fund_nav,
        )
    ]
