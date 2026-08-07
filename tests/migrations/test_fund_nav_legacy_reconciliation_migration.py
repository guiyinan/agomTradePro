"""Migration evidence for the bounded Fund NAV legacy reconciliation."""

from __future__ import annotations

import importlib
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.apps import apps as django_apps
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

MIGRATION = "0004_reconcile_legacy_nav_to_data_center"
SOURCE = "fund_legacy_repo"


@pytest.mark.django_db(transaction=True)
def test_aligned_fund_nav_snapshot_persists_clean_evidence_without_rewriting_fact() -> None:
    """A zero-repair upgrade must still leave deterministic clean evidence."""

    migration = importlib.import_module(
        "apps.fund.migrations.0004_reconcile_legacy_nav_to_data_center"
    )
    legacy = _seed_legacy_row(
        django_apps,
        fund_code="000003",
        nav_date=date(2025, 2, 3),
        unit_nav="1.2340",
        accum_nav="2.3450",
    )
    canonical = _seed_canonical_row(
        django_apps,
        fund_code="000003",
        nav_date=date(2025, 2, 3),
        nav="1.234000",
        acc_nav="2.345000",
    )

    migration.forward_reconcile_fund_nav(django_apps, None)

    from apps.data_center.infrastructure.models import FundNavFactModel
    from apps.data_center.infrastructure.reconciliation_models import (
        ReconciliationEvidenceModel,
    )

    matching = [
        evidence
        for evidence in ReconciliationEvidenceModel._default_manager.filter(dataset_key="fund.nav")
        if evidence.classification_counts.get("same") == 1
        and evidence.classification_counts.get("expected_difference") == 0
    ]
    assert len(matching) == 1
    assert matching[0].is_clean is True
    assert matching[0].rows == []
    canonical.refresh_from_db()
    assert canonical.extra.get("migration") is None
    assert FundNavFactModel._default_manager.filter(pk=canonical.pk).count() == 1
    assert legacy.pk is not None


def _seed_legacy_row(
    apps: object,
    *,
    fund_code: str,
    nav_date: date,
    unit_nav: str,
    accum_nav: str,
) -> object:
    legacy_model = apps.get_model("fund", "FundNetValueModel")
    row = legacy_model._default_manager.create(
        fund_code=fund_code,
        nav_date=nav_date,
        unit_nav=Decimal(unit_nav),
        accum_nav=Decimal(accum_nav),
        daily_return=None,
    )
    legacy_model._default_manager.filter(pk=row.pk).update(
        created_at=datetime(2026, 6, 25, 8, 0, tzinfo=UTC)
    )
    row.refresh_from_db()
    return row


def _seed_canonical_row(
    apps: object,
    *,
    fund_code: str,
    nav_date: date,
    nav: str,
    acc_nav: str,
) -> object:
    canonical_model = apps.get_model("data_center", "FundNavFactModel")
    return canonical_model._default_manager.create(
        fund_code=fund_code,
        nav_date=nav_date,
        nav=Decimal(nav),
        acc_nav=Decimal(acc_nav),
        daily_return=None,
        source=SOURCE,
    )


@pytest.mark.django_db(transaction=True)
def test_fund_nav_reconciliation_fails_closed_then_repairs_reverses_and_reapplies() -> None:
    """A conflict prevents all writes; an exact retry repairs only missing rows."""

    executor = MigrationExecutor(connection)
    leaf_nodes = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(
            [("fund", "0003_fundholdingmodel_fund_holding_amount_nonnegative_and_more")]
        )
        executor = MigrationExecutor(connection)
        old_apps = executor.loader.project_state(
            [
                ("fund", "0003_fundholdingmodel_fund_holding_amount_nonnegative_and_more"),
                ("data_center", "0065_widen_retention_member_digests"),
            ]
        ).apps
        matching_legacy = _seed_legacy_row(
            old_apps,
            fund_code="000004",
            nav_date=date(2025, 1, 13),
            unit_nav="0.8100",
            accum_nav="1.0200",
        )
        missing_legacy = _seed_legacy_row(
            old_apps,
            fund_code="000004",
            nav_date=date(2025, 1, 14),
            unit_nav="0.8210",
            accum_nav="1.0310",
        )
        conflicting = _seed_canonical_row(
            old_apps,
            fund_code="000004",
            nav_date=date(2025, 1, 13),
            nav="9.999000",
            acc_nav="1.020000",
        )
        evidence_model = old_apps.get_model("data_center", "ReconciliationEvidenceModel")
        initial_evidence_ids = set(
            evidence_model._default_manager.filter(dataset_key="fund.nav").values_list(
                "evidence_id", flat=True
            )
        )

        with pytest.raises(RuntimeError, match="semantic_conflict"):
            MigrationExecutor(connection).migrate([("fund", MIGRATION)])

        canonical_model = old_apps.get_model("data_center", "FundNavFactModel")
        assert (
            canonical_model._default_manager.filter(
                fund_code="000004",
                nav_date=date(2025, 1, 14),
                source=SOURCE,
            ).exists()
            is False
        )
        assert (
            set(
                evidence_model._default_manager.filter(dataset_key="fund.nav").values_list(
                    "evidence_id", flat=True
                )
            )
            == initial_evidence_ids
        )

        canonical_model._default_manager.filter(pk=conflicting.pk).update(nav=Decimal("0.810000"))
        MigrationExecutor(connection).migrate([("fund", MIGRATION)])

        executor = MigrationExecutor(connection)
        new_apps = executor.loader.project_state(
            [
                ("fund", MIGRATION),
                ("data_center", "0065_widen_retention_member_digests"),
            ]
        ).apps
        canonical_model = new_apps.get_model("data_center", "FundNavFactModel")
        evidence_model = new_apps.get_model("data_center", "ReconciliationEvidenceModel")
        repaired = canonical_model._default_manager.get(
            fund_code="000004",
            nav_date=date(2025, 1, 14),
            source=SOURCE,
        )
        assert repaired.nav == Decimal("0.821000")
        assert repaired.acc_nav == Decimal("1.031000")
        assert repaired.source_record_id == f"fund_net_value:{missing_legacy.pk}"
        assert len(repaired.raw_payload_hash) == 64
        assert repaired.available_at == missing_legacy.created_at
        assert repaired.extra["legacy_pk"] == missing_legacy.pk
        assert repaired.extra["migration"] == f"fund.{MIGRATION}"

        matching_evidence = [
            row
            for row in evidence_model._default_manager.filter(dataset_key="fund.nav")
            if any(
                item.get("action") == "backfilled_missing_canonical_fact"
                for item in row.rows
                if isinstance(item, dict)
            )
        ]
        assert len(matching_evidence) == 1
        evidence = matching_evidence[0]
        assert evidence.is_clean is True
        assert evidence.classification_counts == {
            "same": 1,
            "expected_difference": 1,
            "data_missing": 0,
            "semantic_conflict": 0,
            "code_defect": 0,
        }
        assert evidence.rows == [
            {
                "natural_key": "000004:2025-01-14:fund_legacy_repo",
                "classification": "expected_difference",
                "legacy_value": {
                    "nav": "0.821",
                    "acc_nav": "1.031",
                    "daily_return": None,
                },
                "canonical_value": {
                    "nav": "0.821",
                    "acc_nav": "1.031",
                    "daily_return": None,
                },
                "action": "backfilled_missing_canonical_fact",
            }
        ]

        MigrationExecutor(connection).migrate(
            [("fund", "0003_fundholdingmodel_fund_holding_amount_nonnegative_and_more")]
        )
        canonical_model = old_apps.get_model("data_center", "FundNavFactModel")
        assert (
            canonical_model._default_manager.filter(
                fund_code="000004",
                nav_date=date(2025, 1, 14),
                source=SOURCE,
            ).exists()
            is False
        )
        assert (
            canonical_model._default_manager.filter(
                fund_code="000004",
                nav_date=date(2025, 1, 13),
                source=SOURCE,
            ).exists()
            is True
        )
        assert (
            old_apps.get_model("data_center", "ReconciliationEvidenceModel")
            ._default_manager.filter(evidence_id=evidence.evidence_id)
            .exists()
            is False
        )

        MigrationExecutor(connection).migrate([("fund", MIGRATION)])
        canonical_model = (
            MigrationExecutor(connection)
            .loader.project_state(
                [
                    ("fund", MIGRATION),
                    ("data_center", "0065_widen_retention_member_digests"),
                ]
            )
            .apps.get_model("data_center", "FundNavFactModel")
        )
        assert (
            canonical_model._default_manager.filter(
                fund_code="000004",
                nav_date=date(2025, 1, 14),
                source=SOURCE,
            ).count()
            == 1
        )
        assert matching_legacy.pk is not None
    finally:
        try:
            old_apps.get_model("data_center", "FundNavFactModel")._default_manager.filter(
                fund_code="000004",
                nav_date=date(2025, 1, 13),
                source=SOURCE,
            ).update(nav=Decimal("0.810000"))
        except UnboundLocalError:
            pass
        MigrationExecutor(connection).migrate(leaf_nodes)
