"""Seed the former code matrix as an explicitly unverified policy version."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

from django.db import migrations

POLICY_KEY = "strategic_asset_allocation"


def _legacy_entries():
    return (
        (
            "Recovery",
            "aggressive",
            "0.70",
            "0.15",
            "0.05",
            "0.10",
            "复苏期权益资产表现优异，激进型可高配股票，充分享受经济增长红利",
            "0.12",
            "0.18",
            "0.67",
        ),
        (
            "Recovery",
            "moderate",
            "0.55",
            "0.25",
            "0.05",
            "0.15",
            "复苏期股市走强，稳健型适度增加权益仓位，债券提供稳定收益",
            "0.09",
            "0.14",
            "0.64",
        ),
        (
            "Recovery",
            "conservative",
            "0.40",
            "0.35",
            "0.05",
            "0.20",
            "复苏期可适度参与股市，保守型以债券为主，权益仓位适中",
            "0.06",
            "0.10",
            "0.60",
        ),
        (
            "Recovery",
            "defensive",
            "0.25",
            "0.45",
            "0.05",
            "0.25",
            "防御型优先保值，复苏期少量参与股市，主要持有债券和现金",
            "0.04",
            "0.07",
            "0.57",
        ),
        (
            "Overheat",
            "aggressive",
            "0.50",
            "0.20",
            "0.15",
            "0.15",
            "过热期通胀上升，商品表现好，激进型可加配商品对冲通胀",
            "0.08",
            "0.20",
            "0.40",
        ),
        (
            "Overheat",
            "moderate",
            "0.40",
            "0.30",
            "0.10",
            "0.20",
            "过热期政策收紧风险加大，适度降低权益，增加商品和债券",
            "0.06",
            "0.15",
            "0.40",
        ),
        (
            "Overheat",
            "conservative",
            "0.25",
            "0.40",
            "0.10",
            "0.25",
            "过热期风险加大，保守型降低权益，增加债券和现金仓位",
            "0.04",
            "0.10",
            "0.40",
        ),
        (
            "Overheat",
            "defensive",
            "0.15",
            "0.45",
            "0.10",
            "0.30",
            "防御型大幅降低风险，过热期以债券和现金为主",
            "0.03",
            "0.06",
            "0.50",
        ),
        (
            "Stagflation",
            "aggressive",
            "0.30",
            "0.25",
            "0.20",
            "0.25",
            "滞胀期股债双杀，激进型大幅降低权益，增加商品和现金避险",
            "0.03",
            "0.15",
            "0.20",
        ),
        (
            "Stagflation",
            "moderate",
            "0.20",
            "0.35",
            "0.15",
            "0.30",
            "滞胀期风险极高，稳健型以债券和现金为主，少量商品对冲通胀",
            "0.02",
            "0.12",
            "0.17",
        ),
        (
            "Stagflation",
            "conservative",
            "0.10",
            "0.45",
            "0.15",
            "0.30",
            "滞胀期极度不利，保守型以债券和现金为主，避免权益风险",
            "0.01",
            "0.08",
            "0.13",
        ),
        (
            "Stagflation",
            "defensive",
            "0.05",
            "0.40",
            "0.15",
            "0.40",
            "滞胀期防御型最大限度降低风险，以现金为主，商品对冲通胀",
            "0.00",
            "0.05",
            "0.00",
        ),
        (
            "Deflation",
            "aggressive",
            "0.40",
            "0.35",
            "0.05",
            "0.20",
            "衰退期债券表现优异，激进型适度配置债券，等待股市反弹机会",
            "0.05",
            "0.15",
            "0.33",
        ),
        (
            "Deflation",
            "moderate",
            "0.25",
            "0.45",
            "0.05",
            "0.25",
            "衰退期央行宽松利好债券，稳健型以债券为主，降低权益仓位",
            "0.04",
            "0.10",
            "0.40",
        ),
        (
            "Deflation",
            "conservative",
            "0.15",
            "0.55",
            "0.05",
            "0.25",
            "衰退期债券表现最佳，保守型以债券为主，现金防守",
            "0.03",
            "0.07",
            "0.43",
        ),
        (
            "Deflation",
            "defensive",
            "0.10",
            "0.50",
            "0.05",
            "0.35",
            "防御型以债券和现金为主，衰退期最大限度降低波动",
            "0.02",
            "0.05",
            "0.40",
        ),
    )


def _legacy_adjustments():
    return (
        ("P0", "1.0", "1.0", "1.0", "1.0"),
        ("P1", "0.8", "0.9", "0.8", "0.9"),
        ("P2", "0.6", "0.8", "0.8", "0.9"),
        ("P3", "0.3", "0.65", "0.8", "0.9"),
    )


def _canonical_number(value):
    return format(Decimal(str(value)).normalize(), "f")


def _content_hash(entries, adjustments):
    entry_payload = []
    for (
        regime,
        risk_profile,
        equity,
        fixed_income,
        commodity,
        cash,
        reasoning,
        expected_return,
        expected_volatility,
        sharpe_ratio,
    ) in sorted(entries, key=lambda item: (item[0], item[1])):
        entry_payload.append(
            {
                "regime": regime,
                "risk_profile": risk_profile,
                "allocation": {
                    "equity": _canonical_number(equity),
                    "fixed_income": _canonical_number(fixed_income),
                    "commodity": _canonical_number(commodity),
                    "cash": _canonical_number(cash),
                },
                "reasoning": reasoning,
                "expected_return": _canonical_number(expected_return),
                "expected_volatility": _canonical_number(expected_volatility),
                "sharpe_ratio": _canonical_number(sharpe_ratio),
                "statistics_status": "legacy_unverified",
                "research_evidence_id": None,
            }
        )
    adjustment_payload = [
        {
            "policy_level": level,
            "equity_multiplier": _canonical_number(equity_multiplier),
            "expected_return_multiplier": _canonical_number(return_multiplier),
            "expected_volatility_multiplier": _canonical_number(volatility_multiplier),
            "sharpe_multiplier": _canonical_number(sharpe_multiplier),
        }
        for (
            level,
            equity_multiplier,
            return_multiplier,
            volatility_multiplier,
            sharpe_multiplier,
        ) in sorted(adjustments, key=lambda item: item[0])
    ]
    canonical_json = json.dumps(
        {"entries": entry_payload, "adjustments": adjustment_payload},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical_json.encode("utf-8")).hexdigest()


def seed_legacy_allocation_policy(apps, schema_editor):
    version_model = apps.get_model("strategy", "AllocationPolicyVersionModel")
    entry_model = apps.get_model("strategy", "AllocationPolicyEntryModel")
    adjustment_model = apps.get_model("strategy", "AllocationPolicyAdjustmentModel")
    entries = _legacy_entries()
    adjustments = _legacy_adjustments()
    seeded_at = datetime(2026, 8, 4, tzinfo=UTC)
    active_exists = version_model.objects.filter(
        policy_key=POLICY_KEY,
        status="active",
    ).exists()
    version, _ = version_model.objects.get_or_create(
        policy_key=POLICY_KEY,
        version=1,
        defaults={
            "status": "superseded" if active_exists else "active",
            "content_hash": _content_hash(entries, adjustments),
            "source_type": "legacy_code_migration",
            "source_metadata": {
                "original_file": "apps/strategy/domain/allocation_matrix.py",
                "migration": "strategy.0013_seed_legacy_allocation_policy",
                "statistics_classification": "legacy_unverified",
            },
            "change_reason": "Migrate the legacy 4x4 allocation matrix and Policy multipliers",
            "effective_at": seeded_at,
            "activated_at": seeded_at,
        },
    )
    for (
        regime,
        risk_profile,
        equity,
        fixed_income,
        commodity,
        cash,
        reasoning,
        expected_return,
        expected_volatility,
        sharpe_ratio,
    ) in entries:
        entry_model.objects.get_or_create(
            policy_version=version,
            regime=regime,
            risk_profile=risk_profile,
            defaults={
                "equity": Decimal(equity),
                "fixed_income": Decimal(fixed_income),
                "commodity": Decimal(commodity),
                "cash": Decimal(cash),
                "reasoning": reasoning,
                "expected_return": Decimal(expected_return),
                "expected_volatility": Decimal(expected_volatility),
                "sharpe_ratio": Decimal(sharpe_ratio),
                "statistics_status": "legacy_unverified",
                "research_evidence_id": None,
            },
        )
    for (
        level,
        equity_multiplier,
        return_multiplier,
        volatility_multiplier,
        sharpe_multiplier,
    ) in adjustments:
        adjustment_model.objects.get_or_create(
            policy_version=version,
            policy_level=level,
            defaults={
                "equity_multiplier": Decimal(equity_multiplier),
                "expected_return_multiplier": Decimal(return_multiplier),
                "expected_volatility_multiplier": Decimal(volatility_multiplier),
                "sharpe_multiplier": Decimal(sharpe_multiplier),
            },
        )


def remove_legacy_allocation_policy(apps, schema_editor):
    version_model = apps.get_model("strategy", "AllocationPolicyVersionModel")
    version_model.objects.filter(
        policy_key=POLICY_KEY,
        version=1,
        source_type="legacy_code_migration",
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("strategy", "0012_allocation_policy_models"),
    ]

    operations = [
        migrations.RunPython(
            seed_legacy_allocation_policy,
            remove_legacy_allocation_policy,
        ),
    ]
