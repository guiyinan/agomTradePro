"""Verify exact retained M1 prices stay historical after pointer replacement.

The provider responses and market calendar are explicitly synthetic. M1
capture, staging, activation, current reads, and historical Audit/Outbox
verification all use their real production compositions.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Protocol, cast

import pytest
from django.db import connection, models
from django.test import override_settings
from django.utils import timezone

from apps.audit.infrastructure.system_audit_models import SystemAuditEventModel
from apps.audit.infrastructure.system_audit_outbox_models import SystemAuditOutboxModel
from apps.data_center.application.public_published_queries import (
    get_published_price_bar_source,
    get_retained_historical_price_source,
)
from apps.data_center.domain.control_plane import PublicationState
from apps.data_center.domain.market_time import latest_closed_cn_market_session
from apps.data_center.domain.publication_lanes import M1_REBALANCE_REFERENCE_PUBLICATION_KEY
from apps.data_center.domain.raw_landing import RawPayload
from apps.data_center.infrastructure.published_price_source_repository import (
    DjangoPublishedPriceSourceRepository,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.corporate_action_nav_mark_composition import (
    build_corporate_action_nav_raw_mark_reader,
)
from apps.simulated_trading.infrastructure.corporate_action_posting_models import (
    CorporateActionPostingModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentAllocationModel,
    CorporateActionTaxAssessmentHeaderModel,
)
from apps.simulated_trading.infrastructure.corporate_action_tax_liability_models import (
    CorporateActionTaxLiabilityOperationModel,
)
from apps.simulated_trading.infrastructure.models import PositionModel
from apps.simulated_trading.infrastructure.order_fill_receipt_models import (
    SimulatedOrderFillReceiptModel,
)
from apps.simulated_trading.infrastructure.order_reservation_models import (
    SimulatedOrderReservationModel,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)
from tests.component.simulated_trading import test_corporate_action_owner_nav_postgres as owner_nav
from tests.support.account_authority_generation_flush import (  # noqa: F401
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash03_auto_calendar_fixture import (
    FormalCalendarFixture,
    persist_auto_uow_formal_calendar,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_context import _TIMEZONE
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS,
)

_WORKFLOW_URLCONF = "tests.support.ash05_owner_workflow_test_urls"


class _RawClosePublication(Protocol):
    """Expose only the identity fields used by this historical source test."""

    trade_date: date
    publication_id: str
    close: Decimal


class _NavFixtureHelpers(Protocol):
    """Type the narrow fixture helpers from the delivered companion fixture."""

    def _publish_synthetic_raw_close_capture(
        self,
        *,
        world: OwnerWorkflowNativeWorld,
        calendar: FormalCalendarFixture,
        target_trade_date: date | None = None,
        close: Decimal,
    ) -> _RawClosePublication: ...

    def _activate_raw_mark_policy(
        self, *, world: OwnerWorkflowNativeWorld, publication_key: str
    ) -> None: ...

    def _query(
        self, world: OwnerWorkflowNativeWorld
    ) -> SimulatedCorporateActionNavRawMarkQuery: ...


def _load_nav_fixture_helpers() -> _NavFixtureHelpers:
    """Use the formally delivered companion NAV fixture's exact typed helpers."""
    return cast(_NavFixtureHelpers, owner_nav)


def _model_rows(model: type[models.Model], **filters: object) -> tuple[tuple[object, ...], ...]:
    """Return a stable full-row snapshot for one bounded test-owned table scope."""
    columns = tuple(field.attname for field in model._meta.concrete_fields)
    rows = (
        model._default_manager.using("default")
        .filter(**filters)
        .order_by("pk")
        .values_list(*columns)
    )
    return tuple(tuple(row) for row in rows)


def _read_only_effects(world: OwnerWorkflowNativeWorld) -> tuple[object, ...]:
    """Fingerprint account finance plus retained Audit/Outbox rows around reads."""
    account_id = world.account_id
    scoped_rows = (
        _model_rows(SimulatedAccountModel, pk=account_id),
        _model_rows(PositionModel, account_id=account_id),
        _model_rows(SimulatedTradeModel, account_id=account_id),
        _model_rows(SimulatedOrderReservationModel, account_id=account_id),
        _model_rows(SimulatedOrderFillReceiptModel, reservation__account_id=account_id),
        _model_rows(CorporateActionPostingModel, account_id=account_id),
        _model_rows(CorporateActionTaxAssessmentHeaderModel, account_id=account_id),
        _model_rows(CorporateActionTaxAssessmentAllocationModel, account_id=account_id),
        _model_rows(CorporateActionTaxLiabilityOperationModel, account_id=account_id),
    )
    return (
        scoped_rows,
        _model_rows(SystemAuditEventModel),
        _model_rows(SystemAuditOutboxModel),
    )


def _assert_aware_at_or_before(value: datetime, cutoff: datetime) -> None:
    """Check an original clock without rewriting it to the current read time."""
    assert value.tzinfo is not None and value.utcoffset() is not None
    assert value <= cutoff


def test_retained_m1_price_is_exactly_historical_after_newer_pointer_activation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Read two exact M1 dates and prove the old one never masquerades as current."""
    if connection.vendor != "postgresql":
        pytest.skip("retained M1 activation requires the assigned migrated PostgreSQL DB")

    from apps.config_center.application.runtime_public import activate_runtime_profile_patch

    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF), isolated_task_channels():
        nav_helpers = _load_nav_fixture_helpers()
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        calendar = persist_auto_uow_formal_calendar(
            as_of=timezone.now().astimezone(UTC),
            exchange="SZSE",
            timezone_name=_TIMEZONE,
            live_clock=True,
            require_current_open_session=False,
            bootstrap_runtime=False,
        )
        assert calendar.dataset_key == world.calendar_dataset_key
        activate_runtime_profile_patch(
            environment="development",
            patch={
                "config_center.market.exchange_timezone_map": {
                    "SZ": _TIMEZONE,
                    "SZSE": _TIMEZONE,
                }
            },
            actor="ash05-retained-price-calendar-scope",
            reason="retain explicit source-exchange and rule-market calendar timezones",
        )
        open_sessions = frozenset(
            item.calendar_date for item in calendar.snapshot.days if item.is_open
        )
        latest_closed = latest_closed_cn_market_session(
            timezone.now().astimezone(UTC), open_sessions=open_sessions
        )
        assert latest_closed is not None
        recent_sessions = tuple(sorted(day for day in open_sessions if day <= latest_closed))
        assert len(recent_sessions) >= 2
        older_date, current_date = recent_sessions[-2:]
        assert current_date == latest_closed

        older = nav_helpers._publish_synthetic_raw_close_capture(
            world=world,
            calendar=calendar,
            target_trade_date=older_date,
            close=Decimal("11.47"),
        )
        current = nav_helpers._publish_synthetic_raw_close_capture(
            world=world,
            calendar=calendar,
            target_trade_date=current_date,
            close=Decimal("12.83"),
        )
        assert older.publication_id != current.publication_id
        nav_helpers._activate_raw_mark_policy(
            world=world,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )

        before_reads = _read_only_effects(world)
        cutoff = timezone.now().astimezone(UTC)
        current_source = get_published_price_bar_source(
            world.asset_code,
            trade_date=current_date,
            knowledge_cutoff=cutoff,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        assert current_source.evidence is not None, current_source.blocked_reason
        assert current_source.evidence.publication_id == current.publication_id
        assert current_source.evidence.values.close == Decimal("12.83")
        assert current_source.evidence.source_observed_at is None
        old_current_source = get_published_price_bar_source(
            world.asset_code,
            trade_date=older_date,
            knowledge_cutoff=cutoff,
            publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
        )
        assert old_current_source.evidence is None
        assert old_current_source.blocked_reason

        current_mark = build_corporate_action_nav_raw_mark_reader(
            runtime_environment="development",
            calendar_dataset_key=world.calendar_dataset_key,
        ).read_current_mark(nav_helpers._query(world))
        assert current_mark is not None
        assert current_mark.trade_date == current_date
        assert current_mark.price == Decimal("12.83")
        assert current_mark.source_evidence.publication_id == current.publication_id
        assert current_mark.source_observed_at is None
        assert current_mark.must_not_use_for_decision is True

        historical = get_retained_historical_price_source(
            world.asset_code,
            trade_date=older_date,
            publication_id=older.publication_id,
            expected_publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=cutoff,
            environment="development",
        )
        assert historical.evidence is not None, historical.blocked_reason
        evidence = historical.evidence
        price = evidence.price
        pair = evidence.activation.pair
        assert evidence.knowledge_semantics == "currently_known_historical"
        assert evidence.must_not_use_for_decision is True
        assert price.publication_state is PublicationState.SUPERSEDED
        assert price.publication_id == older.publication_id
        assert price.publication_key == M1_REBALANCE_REFERENCE_PUBLICATION_KEY
        assert price.trade_date == older_date
        assert price.values.close == Decimal("11.47")
        assert price.adjustment.value == "none"
        assert price.source_observed_at is None
        assert price.interval_end_at < price.source_available_at
        assert price.source_available_at == price.raw_payload_reference.response_completed_at
        assert price.publication_published_at <= cutoff
        assert pair.event.event_type == "data.publication.published"
        assert pair.event.publication_id == older.publication_id
        assert pair.outbox_id
        assert len(pair.outbox_payload_sha256) == 64
        pair.verify_at_cutoff(as_of=cutoff)
        for clock in (
            pair.event.recorded_at,
            pair.audit_persisted_at,
            pair.outbox_created_at,
            price.fact_recorded_at,
            price.publication_as_of,
            price.publication_published_at,
            price.source_available_at,
        ):
            _assert_aware_at_or_before(clock, cutoff)

        wrong_selector = get_retained_historical_price_source(
            world.asset_code,
            trade_date=older_date,
            publication_id=current.publication_id,
            expected_publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=cutoff,
            environment="development",
        )
        assert wrong_selector.evidence is None
        assert wrong_selector.blocked_reason

        unknown_outbox_cutoff = pair.outbox_created_at - timedelta(microseconds=1)
        outbox_not_yet_known = get_retained_historical_price_source(
            world.asset_code,
            trade_date=older_date,
            publication_id=older.publication_id,
            expected_publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=unknown_outbox_cutoff,
            environment="development",
        )
        assert outbox_not_yet_known.evidence is None
        assert outbox_not_yet_known.blocked_reason

        original_read_payload = DjangoPublishedPriceSourceRepository.read_payload

        def changed_retained_body(
            repository: DjangoPublishedPriceSourceRepository,
            payload_hash: str,
        ) -> RawPayload | None:
            """Corrupt only the in-memory repository result, never the stored row."""
            raw_payload = original_read_payload(repository, payload_hash)
            if raw_payload is None:
                return None
            retained_json = raw_payload.payload.get("retained_response_json")
            if not isinstance(retained_json, str):
                return raw_payload
            payload = dict(raw_payload.payload)
            payload["retained_response_json"] = retained_json + " "
            return replace(raw_payload, payload=payload)

        monkeypatch.setattr(
            DjangoPublishedPriceSourceRepository,
            "read_payload",
            changed_retained_body,
        )
        changed_body = get_retained_historical_price_source(
            world.asset_code,
            trade_date=older_date,
            publication_id=older.publication_id,
            expected_publication_key=M1_REBALANCE_REFERENCE_PUBLICATION_KEY,
            knowledge_cutoff=cutoff,
            environment="development",
        )
        assert changed_body.evidence is None
        assert changed_body.blocked_reason

        assert _read_only_effects(world) == before_reads
