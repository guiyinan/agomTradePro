"""Ordinary-owner workflow blocks a share amount without registry allocation."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.db import connection
from django.db.models import Model
from django.test import override_settings

from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability as Capability,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.models import PositionModel, SimulatedAccountModel
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from shared.config.secrets import get_secrets
from tests.component.simulated_trading.test_corporate_action_owner_workflow_http_postgres import (
    _API_ROOT,
    _WORKFLOW_URLCONF,
    _assert_direct_retained_source_successor,
    _business_effect_counts,
    _business_original_fingerprints,
    _event_id,
    _headers,
    _issue_v3_share_consent,
    _post,
    _refresh,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_sources import (
    install_synthetic_szse_capture_transport,
    owner_workflow_statutory_bodies,
    share_distribution_capture,
)
from tests.support.ash05_owner_workflow_native_world import (
    build_owner_workflow_native_world,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = [
    pytest.mark.django_db(
        transaction=True,
        available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
    ),
    pytest.mark.skipif(
        connection.vendor != "postgresql",
        reason="ordinary-owner fractional allocation block requires migrated PostgreSQL",
    ),
]


@pytest.fixture(autouse=True)
def _isolated_owner_workflow_channels() -> Iterator[None]:
    """Isolate cache and process-local task channels for this owner journey."""
    get_secrets.cache_clear()
    try:
        with isolated_task_channels():
            yield
    finally:
        get_secrets.cache_clear()


def _account_rows(
    model: type[Model], *, account_id: int, account_field: str
) -> tuple[tuple[object, ...], ...]:
    """Read every persisted field for one account-scoped table without exposing values."""
    fields = tuple(field.attname for field in model._meta.concrete_fields)
    return tuple(
        tuple(row)
        for row in model._base_manager.filter(**{account_field: account_id})
        .order_by("pk")
        .values_list(*fields)
    )


def _owner_financial_snapshot(account_id: int) -> tuple[object, ...]:
    """Capture cash, holdings, reservations, financial ledger and original audit evidence."""
    return (
        _account_rows(SimulatedAccountModel, account_id=account_id, account_field="pk"),
        _account_rows(PositionModel, account_id=account_id, account_field="account_id"),
        _account_rows(
            SimulatedOrderReservationModel,
            account_id=account_id,
            account_field="account_id",
        ),
        _account_rows(
            CorporateActionPostingModel,
            account_id=account_id,
            account_field="account_id",
        ),
        _account_rows(
            CorporateActionTaxAssessmentHeaderModel,
            account_id=account_id,
            account_field="account_id",
        ),
        _account_rows(
            CorporateActionTaxLiabilityOperationModel,
            account_id=account_id,
            account_field="account_id",
        ),
        _business_effect_counts(account_id),
        _business_original_fingerprints(account_id),
    )


def test_nonstaff_owner_blocks_fractional_share_without_registry_allocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A retained 100 x 1.05/10 entitlement blocks without changing owner finances."""
    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            capture_kind="share",
        )
        assert world.owner.owner.is_staff is False
        assert world.owner.owner.is_superuser is False
        if world.eligible_quantity != Decimal("100.000000"):
            raise AssertionError("the retained ownership proof must provide its actual 100 shares")
        if world.eligible_quantity * Decimal("1.05") / Decimal("10") != Decimal("10.500000"):
            raise AssertionError("the declared synthetic ratio must produce exactly 10.5 shares")

        original = _refresh(world)
        if original.get("outcome") != "success":
            raise AssertionError("the owner could not read the synthetic source event")
        original_event_id = _event_id(world, payload=original)

        successor = share_distribution_capture(
            asset_code=world.asset_code,
            published_on=world.decision_date,
            record_date=world.record_date,
            ex_date=world.settlement_date,
            delivery_date=world.share_delivery_date,
            sellable_date=world.share_sellable_date,
            shares_per_ten="1.05",
            title_suffix="（更正后）",
        )
        successor.announcement_id = world.capture.announcement_id + 1
        if b"%ASH05 synthetic fixture" not in successor.pdf_body:
            raise AssertionError("the retained successor must declare its synthetic source body")
        install_synthetic_szse_capture_transport(
            monkeypatch,
            world.capture,
            statutory_documents=owner_workflow_statutory_bodies(),
            additional_captures=(successor,),
        )
        current = _refresh(world)
        if current.get("outcome") != "success":
            raise AssertionError("the owner could not refresh the synthetic corrected event")
        event_id = _event_id(world, payload=current)
        if event_id == original_event_id:
            raise AssertionError("the corrected source successor did not become current")
        _assert_direct_retained_source_successor(
            world=world,
            previous_event_id=original_event_id,
            current_event_id=event_id,
        )
        if successor.pdf_reads < 1 or world.capture.pdf_reads < 2:
            raise AssertionError("both original and corrected retained PDF bodies must be read")

        consent = _issue_v3_share_consent(world)
        if consent.get("selected_capabilities") != [Capability.SHARE_STAGE_WRITE.value]:
            raise AssertionError("the ordinary owner must select only share-stage authority")

        before = _owner_financial_snapshot(world.account_id)
        prepared = _post(
            world.owner.client,
            _API_ROOT.format(account_id=world.account_id) + "prepare/",
            {
                "event_id": event_id,
                "action": "share_entitlement",
                "correction_mode": "ordinary",
            },
            _headers(world),
        )
        if (
            prepared.get("outcome") != "blocked"
            or prepared.get("blocking_reason") != "CORPORATE_ACTION_OWNER_ODD_LOT_UNSUPPORTED"
            or "continuation" in prepared
        ):
            raise AssertionError(
                "fractional gross shares must block pending exact registry quantity"
            )
        if _owner_financial_snapshot(world.account_id) != before:
            raise AssertionError(
                "fractional allocation block changed cash, shares, ledger, holds, Audit or Outbox"
            )
        if CorporateActionPostingModel.objects.filter(account_id=world.account_id).exists():
            raise AssertionError("a blocked fractional entitlement must create no posting rows")
