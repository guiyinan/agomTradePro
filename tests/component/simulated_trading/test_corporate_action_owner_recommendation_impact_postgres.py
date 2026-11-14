"""Ordinary-owner rebalance plans revalidate retained event changes before action."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from importlib import import_module
from typing import cast
from uuid import uuid4

import pytest
from django.db import connection
from django.db.models import Model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.portfolio.application.transition_plan_lifecycle import (
    TransitionPlanEventReviewRequired,
)
from apps.portfolio.domain.transition_plan_revision import (
    TransitionPlanRevision,
    TransitionPlanRevisionPreparation,
)
from apps.portfolio.domain.transition_plan_revision_basis import TransitionPlanSourceBinding
from apps.portfolio.domain.transition_plan_revision_support import _canonical_hash
from apps.portfolio.infrastructure.models import PortfolioTransitionPlanModel
from apps.portfolio.infrastructure.transition_plan_revision_repository import (
    DjangoTransitionPlanRevisionRepository,
)
from apps.risk_center.application.portfolio_risk_assets import PortfolioRiskAssetIdentity
from apps.simulated_trading.application.rebalance_journey_event_request_scope import (
    RebalanceJourneyEventRequestScope,
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
from apps.simulated_trading.transition_plan_event_coverage_composition import (
    build_configured_rebalance_journey_event_coverage_pinner,
)
from apps.simulated_trading.transition_plan_event_review_composition import (
    build_configured_transition_plan_event_review_validator,
)
from apps.simulated_trading.transition_plan_journey_composition import (
    build_transition_plan_locked_guard,
)
from apps.simulated_trading.transition_plan_official_disclosure_source import (
    build_official_szse_distribution_refresher,
)
from shared.config.secrets import get_secrets
from tests.component.simulated_trading.test_corporate_action_owner_workflow_http_postgres import (
    _WORKFLOW_URLCONF,
    _assert_direct_retained_source_successor,
    _business_original_fingerprints,
    _event_id,
    _refresh,
)
from tests.integration.simulated_trading.test_readonly_rebalance_plan_owner_api import (
    _install_preview_ports,
    _publish_m1_policy_for_preview,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)
from tests.support.ash05_owner_workflow_native_sources import (
    cash_distribution_capture,
    install_synthetic_szse_capture_transport,
    owner_workflow_statutory_bodies,
)
from tests.support.ash05_owner_workflow_native_world import (
    OwnerWorkflowNativeWorld,
    build_owner_workflow_native_world,
)
from tests.support.ash07_owner_account_authority import ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS
from tests.support.simulated_tax_model_native_sources import isolated_task_channels

pytestmark = pytest.mark.django_db(
    transaction=True,
    available_apps=(*ASH07_OWNER_ACCEPTANCE_AVAILABLE_APPS, "apps.portfolio"),
)

_PLAN_ROOT = "/api/simulated-trading/accounts/{account_id}/rebalance-plans/"


@pytest.fixture(autouse=True)
def _isolated_task_channels() -> Iterator[None]:
    """Isolate this migrated owner journey's local cache and task channels."""

    get_secrets.cache_clear()
    try:
        with isolated_task_channels():
            yield
    finally:
        get_secrets.cache_clear()


def _account_rows(model: type[Model], *, account_id: int) -> tuple[tuple[object, ...], ...]:
    """Snapshot all persisted fields for one account-owned model without exposing them."""

    columns = tuple(field.attname for field in model._meta.concrete_fields)
    return tuple(
        tuple(row)
        for row in model._base_manager.filter(account_id=account_id)
        .order_by("pk")
        .values_list(*columns)
    )


def _owner_financial_snapshot(account_id: int) -> tuple[object, ...]:
    """Fingerprint financial, plan, reservation, and original corporate-action evidence."""

    account = SimulatedAccountModel.objects.values_list(
        "current_cash", "current_market_value", "total_value", "updated_at"
    ).get(pk=account_id)
    positions = tuple(
        PositionModel.objects.filter(account_id=account_id)
        .order_by("asset_code")
        .values_list(
            "asset_code",
            "quantity",
            "available_quantity",
            "current_price",
            "market_value",
            "updated_at",
        )
    )
    return (
        account,
        positions,
        _account_rows(CorporateActionPostingModel, account_id=account_id),
        _account_rows(CorporateActionTaxAssessmentHeaderModel, account_id=account_id),
        _account_rows(CorporateActionTaxLiabilityOperationModel, account_id=account_id),
        _account_rows(SimulatedOrderReservationModel, account_id=account_id),
        _account_rows(PortfolioTransitionPlanModel, account_id=account_id),
        _business_original_fingerprints(account_id),
    )


def _post_plan_json(
    *,
    client: APIClient,
    path: str,
    body: dict[str, object],
    csrf_token: str,
    idempotency_key: str,
) -> tuple[int, dict[str, object]]:
    """Use the real session/CSRF plan API and return its bounded JSON payload."""

    response = client.post(
        path,
        body,
        format="json",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=csrf_token,
        HTTP_IDEMPOTENCY_KEY=idempotency_key,
    )
    if not response.headers.get("Content-Type", "").startswith("application/json"):
        raise AssertionError("owner plan route did not return JSON")
    payload: object = response.json()
    if type(payload) is not dict:
        raise AssertionError("owner plan route returned an invalid JSON envelope")
    return response.status_code, cast(dict[str, object], payload)


def _read_plan(
    *, client: APIClient, world: OwnerWorkflowNativeWorld, plan: Mapping[str, object]
) -> dict[str, object]:
    """Read the same exact saved plan through the public owner endpoint."""

    identity_value = plan.get("identity")
    if not isinstance(identity_value, Mapping):
        raise AssertionError("saved plan has no typed identity")
    identity = cast(Mapping[str, object], identity_value)
    plan_id = identity.get("plan_id")
    version = identity.get("version")
    revision_hash = identity.get("revision_hash")
    if type(plan_id) is not str or type(version) is not int or type(revision_hash) is not str:
        raise AssertionError("saved plan read pins are incomplete")
    response = client.get(
        f"{_PLAN_ROOT.format(account_id=world.account_id)}{plan_id}/"
        f"?plan_version={version}&revision_hash={revision_hash}",
        secure=True,
        HTTP_ORIGIN="https://testserver",
        HTTP_X_CSRFTOKEN=world.owner.csrf_token,
    )
    if response.status_code != 200 or not response.headers.get("Content-Type", "").startswith(
        "application/json"
    ):
        raise AssertionError("owner plan exact-read did not succeed")
    payload: object = response.json()
    if type(payload) is not dict:
        raise AssertionError("owner plan exact-read returned an invalid envelope")
    return cast(dict[str, object], payload)


@dataclass(frozen=True, slots=True)
class _PlanOwnerContext:
    """Actual persisted owner/account fields consumed by the synthetic plan factory."""

    account: SimulatedAccountModel
    owner_id: int


def _mapping(value: object, *, field_name: str) -> dict[str, object]:
    """Require a decoded canonical JSON object before updating trusted fixture evidence."""

    if type(value) is not dict or any(type(key) is not str for key in value):
        raise AssertionError(f"synthetic plan evidence field {field_name} is not an object")
    return cast(dict[str, object], value)


def _attach_current_event_bindings(
    preparation: TransitionPlanRevisionPreparation,
    *,
    event_bindings: tuple[TransitionPlanSourceBinding, ...],
) -> TransitionPlanRevisionPreparation:
    """Retain real current event pins beside this explicitly synthetic plan basis."""

    if type(preparation) is not TransitionPlanRevisionPreparation or not event_bindings:
        raise AssertionError("the synthetic plan preparation or real event pins are unavailable")
    basis = preparation.basis
    source_bindings = (*basis.source_bindings, *event_bindings)
    source_payloads = [item.to_payload() for item in source_bindings]
    source_evidence_hash = _canonical_hash({"source_bindings": source_payloads})
    positions = tuple(
        replace(
            row,
            source_binding_hashes=tuple(
                _canonical_hash(item.to_payload())
                for item in source_bindings
                if item.asset_code == row.asset_code and item.security_id == row.security_id
            ),
        )
        for row in basis.current_positions
    )

    document = _mapping(json.loads(basis.preparation_evidence_json), field_name="root")
    portfolio = _mapping(document.get("portfolio_snapshot"), field_name="portfolio_snapshot")
    resources = _mapping(portfolio.get("resources"), field_name="portfolio.resources")
    resources["positions"] = [row.to_payload() for row in positions]
    portfolio_hash = _canonical_hash(resources)
    portfolio["content_hash"] = portfolio_hash
    portfolio["source_evidence_hash"] = source_evidence_hash

    decision = _mapping(document.get("decision_snapshot"), field_name="decision_snapshot")
    decision_payload = _mapping(decision.get("payload"), field_name="decision.payload")
    decision_payload["portfolio_snapshot_hash"] = portfolio_hash
    decision_hash = _canonical_hash(decision_payload)
    decision["content_hash"] = decision_hash

    positions_evidence = _mapping(document.get("positions"), field_name="positions")
    positions_evidence["current"] = [row.to_payload() for row in positions]
    document["source_bindings"] = source_payloads
    encoded = json.dumps(
        document,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    updated_basis = replace(
        basis,
        portfolio_snapshot_hash=portfolio_hash,
        portfolio_source_evidence_hash=source_evidence_hash,
        decision_snapshot_hash=decision_hash,
        source_bindings=source_bindings,
        current_positions=positions,
        preparation_evidence_json=encoded,
    )
    return replace(preparation, basis=updated_basis)


def test_owner_rebalance_preview_is_reviewed_after_retained_event_correction(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """A real saved plan loses previewability after the current source adds its successor."""

    if connection.vendor != "postgresql":
        pytest.skip("ordinary-owner current-event impact requires migrated PostgreSQL")

    with override_settings(ROOT_URLCONF=_WORKFLOW_URLCONF):
        world = build_owner_workflow_native_world(monkeypatch=monkeypatch, tmp_path=tmp_path)
        assert world.owner.owner.is_staff is False
        assert world.owner.owner.is_superuser is False

        # Only the unrelated valuation/risk plan facts are synthetic. The
        # owner, retained event coverage, Portfolio write and review guard stay real.
        account = SimulatedAccountModel.objects.get(pk=world.account_id)
        position = PositionModel.objects.get(
            account_id=world.account_id, asset_code=world.asset_code
        )
        price_reader, _, _, _ = _install_preview_ports(
            monkeypatch,
            account=account,
            user_id=world.owner.owner.pk,
            identity_security_ids={world.asset_code: world.security_id},
            classification_asset_types={world.asset_code: "equity"},
        )

        # Publish the normal current M1 policy with its existing public setup
        # API. Its temporary setup clock is restored before source or plan reads.
        with monkeypatch.context() as m1_setup:
            _publish_m1_policy_for_preview(
                m1_setup,
                client=APIClient(),
                owner=world.owner.owner,
                account=account,
                strategy=None,
            )

        initial = _refresh(world)
        if initial.get("outcome") != "success":
            raise AssertionError("the ordinary owner did not read the current synthetic event")
        original_event_id = _event_id(world, payload=initial)
        request_scope = RebalanceJourneyEventRequestScope(
            actor_user_id=world.owner.owner.pk,
            account_id=world.account_id,
            owner_user_id=world.owner.owner.pk,
        )
        prepared_at = timezone.now()
        asset_identities = ((world.asset_code, world.security_id),)
        refresher = build_official_szse_distribution_refresher(
            runtime_environment=world.owner.environment, using="default"
        )
        refresh_receipt = refresher.refresh(
            asset_identities=(PortfolioRiskAssetIdentity(world.asset_code, world.security_id),),
            request_scope=request_scope,
            as_of=prepared_at,
        )
        # Capture and durable proof recording must precede the pin cutoff.
        prepared_at = timezone.now()
        event_bindings = build_configured_rebalance_journey_event_coverage_pinner(
            runtime_environment=world.owner.environment, using="default"
        ).pin(
            asset_identities=asset_identities,
            request_scope=request_scope,
            as_of=prepared_at,
            parent=None,
            refresh_receipt=refresh_receipt,
        )

        plan_fixture = import_module(
            "tests.component.simulated_trading.test_transition_plan_execution_native"
        )
        monkeypatch.setattr(plan_fixture, "ASSET_CODE", world.asset_code)
        monkeypatch.setattr(plan_fixture, "SECURITY_ID", world.security_id)
        actual_revision_builder = plan_fixture.build_transition_plan_revision

        def build_current_event_pinned_revision(
            preparation: TransitionPlanRevisionPreparation,
        ) -> TransitionPlanRevision:
            """Keep fixture economics synthetic while sealing genuine current event pins."""

            updated = _attach_current_event_bindings(preparation, event_bindings=event_bindings)
            lease_deadline = min(item.admission_until for item in event_bindings)
            updated_basis = replace(
                updated.basis,
                valid_until=min(updated.basis.valid_until, lease_deadline),
            )
            updated_plan = replace(updated.plan, expires_at=lease_deadline)
            return actual_revision_builder(replace(updated, basis=updated_basis, plan=updated_plan))

        monkeypatch.setattr(
            plan_fixture, "build_transition_plan_revision", build_current_event_pinned_revision
        )
        synthetic_revision = plan_fixture._build_revision(
            context=_PlanOwnerContext(account=account, owner_id=world.owner.owner.pk),
            position_quantity=Decimal(position.quantity),
            order_quantity=int(position.quantity),
            prepared_at=prepared_at,
        )
        event_validator = build_configured_transition_plan_event_review_validator(
            runtime_environment=world.owner.environment, using="default"
        )
        saved = DjangoTransitionPlanRevisionRepository(
            using="default", event_review_validator=event_validator
        ).append_initial(
            synthetic_revision,
            idempotency_key=synthetic_revision.plan.idempotency_key,
        )
        saved_payload = saved.to_payload()
        plan = saved_payload
        baseline = _read_plan(client=world.owner.client, world=world, plan=plan)
        baseline_capabilities = baseline.get("capabilities")
        if (
            not isinstance(baseline_capabilities, Mapping)
            or baseline_capabilities.get("can_preview_order") is not True
        ):
            raise AssertionError("the original current-event plan was not previewable")
        policy_depths: list[int] = []
        locked_guard = build_transition_plan_locked_guard(
            using="default",
            current_policy_pins_validator=plan_fixture._AtomicDepthPolicyReader(
                delegate=plan_fixture._PinnedPolicyReader(
                    plan_fixture._current_synthetic_policy_hashes()
                ),
                observed_depths=policy_depths,
            ),
            event_review_validator=event_validator,
        )
        locked_binding = saved.orders[0].to_execution_binding(
            saved.identity,
            owner_user_id=world.owner.owner.pk,
            action_attempt_key=f"ash05-impact-locked-{uuid4().hex}",
        )
        if (
            locked_guard.validate_locked_action(
                binding=locked_binding,
                account_id=world.account_id,
                owner_user_id=world.owner.owner.pk,
                as_of=timezone.now(),
            )
            != saved
            or not policy_depths
            or any(depth < 1 for depth in policy_depths)
        ):
            raise AssertionError(
                "the original current-event plan did not pass its real SQL lock guard"
            )
        raw_identity = plan.get("identity")
        raw_basis = plan.get("basis")
        raw_orders = plan.get("orders")
        raw_sources = raw_basis.get("source_bindings") if isinstance(raw_basis, Mapping) else None
        if (
            not isinstance(raw_identity, Mapping)
            or not isinstance(raw_orders, list)
            or not isinstance(raw_sources, list)
        ):
            raise AssertionError("the saved plan omitted its exact order or event-source bindings")
        identity = cast(Mapping[str, object], raw_identity)
        marker_rows = [
            item
            for item in raw_sources
            if isinstance(item, Mapping)
            and item.get("kind") == "security_disclosure_event"
            and item.get("source_record_id") == "__coverage__"
            and item.get("asset_code") == world.asset_code
            and item.get("security_id") == world.security_id
        ]
        event_rows = [
            item
            for item in raw_sources
            if isinstance(item, Mapping)
            and item.get("kind") == "security_disclosure_event"
            and item.get("source_record_id") == original_event_id
            and item.get("asset_code") == world.asset_code
            and item.get("security_id") == world.security_id
        ]
        if (
            len(marker_rows) != 1
            or marker_rows[0].get("coverage_status") != "complete"
            or len(event_rows) != 1
        ):
            raise AssertionError("the saved plan did not pin the retained complete current event")
        orders = [
            cast(Mapping[str, object], item) for item in raw_orders if isinstance(item, Mapping)
        ]
        order = next(
            (
                row
                for row in orders
                if row.get("asset_code") == world.asset_code
                and row.get("side") == "sell"
                and type(row.get("approved_quantity")) is int
                and cast(int, row.get("approved_quantity")) > 0
            ),
            None,
        )
        if order is None:
            raise AssertionError("the plan did not contain a previewable synthetic sell row")
        quantity = Decimal(str(order["approved_quantity"]))
        price_text = order.get("approved_limit_price") or order.get("reference_price")
        if type(price_text) is not str or not price_text:
            raise AssertionError("the exact plan order has no usable selected limit-price text")

        # Append a direct synthetic correction using the real two-pass capture,
        # retained PDF, parser, Data Center revision, and Audit/Outbox composition.
        successor = cash_distribution_capture(
            asset_code=world.asset_code,
            published_on=world.decision_date,
            record_date=world.record_date,
            ex_date=world.settlement_date,
            payment_date=world.decision_date,
            cash_per_ten="3.00",
            title_suffix="（更正后）",
        )
        successor.announcement_id = world.capture.announcement_id + 1
        install_synthetic_szse_capture_transport(
            monkeypatch,
            world.capture,
            statutory_documents=owner_workflow_statutory_bodies(),
            additional_captures=(successor,),
        )
        refresher = build_official_szse_distribution_refresher(
            runtime_environment=world.owner.environment, using="default"
        )
        refresher.refresh(
            asset_identities=(PortfolioRiskAssetIdentity(world.asset_code, world.security_id),),
            request_scope=RebalanceJourneyEventRequestScope(
                actor_user_id=world.owner.owner.pk,
                account_id=world.account_id,
                owner_user_id=world.owner.owner.pk,
            ),
            as_of=timezone.now(),
        )
        from apps.data_center.domain.security_disclosure_event import (
            SecurityDisclosureEventReadScope,
            SecurityDisclosureExchange,
        )
        from apps.data_center.security_disclosure_capture_composition import (
            make_security_disclosure_event_reader,
        )

        retained = make_security_disclosure_event_reader(using="default").execute(
            SecurityDisclosureEventReadScope(
                as_of=timezone.now(),
                exchange=SecurityDisclosureExchange.SZSE,
                asset_code=world.asset_code,
            )
        )
        successor_rows = tuple(
            item.event for item in retained if item.event.source_event_id != original_event_id
        )
        if len(successor_rows) != 1:
            raise AssertionError(
                "the current retained source did not select one correction successor"
            )
        corrected_event_id = successor_rows[0].source_event_id
        _assert_direct_retained_source_successor(
            world=world,
            previous_event_id=original_event_id,
            current_event_id=corrected_event_id,
        )

        saved_after_source_change = _read_plan(client=world.owner.client, world=world, plan=plan)
        if not isinstance(saved_after_source_change.get("plan"), Mapping):
            raise AssertionError("the original immutable plan stopped being readable")
        if cast(Mapping[str, object], saved_after_source_change["plan"]) != plan:
            raise AssertionError("source refresh rewrote the original plan revision")
        capabilities = saved_after_source_change.get("capabilities")
        stale_preview_disabled = (
            isinstance(capabilities, Mapping) and capabilities.get("can_preview_order") is False
        )

        before_block = _owner_financial_snapshot(world.account_id)
        plan_id = identity.get("plan_id")
        plan_version = identity.get("version")
        revision_hash = identity.get("revision_hash")
        ordinal = order.get("ordinal")
        content_hash = order.get("order_content_hash")
        binding_id = order.get("plan_order_binding_id")
        if (
            type(plan_id) is not str
            or type(plan_version) is not int
            or type(revision_hash) is not str
            or type(ordinal) is not int
            or type(content_hash) is not str
            or type(binding_id) is not str
        ):
            raise AssertionError("the exact stale-plan order pins are incomplete")
        preview_status, preview_result = _post_plan_json(
            client=world.owner.client,
            path=(
                f"{_PLAN_ROOT.format(account_id=world.account_id)}{plan_id}/orders/"
                f"{ordinal}/preview/"
            ),
            body={
                "plan_version": plan_version,
                "revision_hash": revision_hash,
                "order_content_hash": content_hash,
                "plan_order_binding_id": binding_id,
                "quantity": format(quantity, "f"),
                "limit_price": price_text,
            },
            csrf_token=world.owner.csrf_token,
            idempotency_key=f"ash05-impact-preview-{uuid4().hex}",
        )
        if (
            preview_status != 409
            or preview_result.get("success") is not False
            or preview_result.get("code") != "TRANSITION_PLAN_EVENT_REVIEW_REQUIRED"
            or "preview" in preview_result
            or "continuation" in preview_result
        ):
            raise AssertionError(
                "the public owner preview preflight did not block stale event facts"
            )
        if price_reader.calls:
            raise AssertionError(
                "stale-plan preview read market prices before current event review blocked it"
            )
        if not stale_preview_disabled:
            raise AssertionError("the stale plan still advertises an actionable order preview")
        try:
            locked_guard.validate_locked_action(
                binding=locked_binding,
                account_id=world.account_id,
                owner_user_id=world.owner.owner.pk,
                as_of=timezone.now(),
            )
        except TransitionPlanEventReviewRequired:
            pass
        else:
            raise AssertionError(
                "the SQL-locked current-event guard accepted the old synthetic plan"
            )
        if len(policy_depths) != 2 or any(depth < 1 for depth in policy_depths):
            raise AssertionError("both actual event validations must retain SQL transaction locks")
        if _owner_financial_snapshot(world.account_id) != before_block:
            raise AssertionError(
                "a stale order preview changed plan, cash, shares, holds, or Audit"
            )
