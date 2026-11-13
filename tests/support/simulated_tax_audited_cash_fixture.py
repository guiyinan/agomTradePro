"""Controlled cash facts with real owner, posting, Audit and source-successor storage.

This helper does not qualify an official disclosure or custody history. It is
for the existing controlled owner-financial contract, whose tax facts are also
explicitly synthetic. The separate current qualifier E2E exercises real parsers.
"""

from dataclasses import replace
from decimal import Decimal, localcontext

from django.utils import timezone

from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    PersistedSimulatedAccountRowSourceV2,
)
from apps.simulated_trading.audited_corporate_action_posting_composition import (
    DjangoAuditedCorporateActionPostingRepositoryFactory,
)
from apps.simulated_trading.corporate_action_owner_grant_gate import (
    DjangoCorporateActionOwnerGrantGate,
)
from apps.simulated_trading.domain.corporate_action_posting import CorporateActionStage
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.infrastructure.simulated_account_row_source_v2_repository import (
    DjangoSimulatedAccountRowSourceV2Repository,
)


class _ExactCashFacts:
    """Accept only the two explicit synthetic stage payloads built by this fixture."""

    def __init__(self, entitlement, payment):
        self.entitlement, self.payment = entitlement, payment

    def verify_source(self, request):
        return request in (self.entitlement, self.payment)

    def verify_ownership(self, request):
        return request == self.entitlement


def post_controlled_audited_dividend_and_refresh_owner_source(service, assessment):
    """Post actual cash stages, then append a fresh synthetic source for new consent."""
    world = service.world
    action, proof = assessment.action, assessment.history.record_date_ownership_proof
    now = timezone.now()
    with localcontext() as context:
        context.prec = 96
        gross = proof.eligible_quantity * action.dividend_per_share
        cents = gross.quantize(Decimal("0.01"))
        assert cents == gross, "This controlled fixture supports exact cent payouts only"
    entitlement = replace(
        service.stage,
        security_id=action.security_id,
        asset_code=action.asset_code,
        asset_name="Synthetic tax security",
        source_namespace=action.source_namespace,
        source_record_id=action.source_record_id,
        source_event_id=action.source_event_id,
        source_revision_id=action.source_revision_id,
        source_payload_sha256=action.source_payload_sha256,
        source_observed_at=now,
        qualified_at=now,
        posted_at=now,
        record_date=action.record_date,
        effective_date=action.effective_date,
        stage_date=action.effective_date,
        payment_date=None,
        cash_amount=cents,
        ownership_snapshot_id=proof.ownership_snapshot_id,
        ownership_snapshot_sha256=proof.ownership_snapshot_sha256,
        ownership_snapshot_as_of_date=proof.ownership_snapshot_as_of_date,
        ownership_snapshot_observed_at=now,
        eligible_quantity=proof.eligible_quantity,
    )
    payment = replace(
        entitlement,
        stage=CorporateActionStage.CASH_PAYMENT,
        payment_date=action.effective_date,
        ownership_snapshot_id=None,
        ownership_snapshot_sha256=None,
        ownership_snapshot_as_of_date=None,
        ownership_snapshot_observed_at=None,
        eligible_quantity=None,
        entitlement_calculation_sha256=None,
    )
    facts = _ExactCashFacts(entitlement, payment)
    gate = DjangoCorporateActionOwnerGrantGate(
        selector=service.grant.selector,
        scope_locker=world.locker,
        using="default",
        environment="development",
    )
    repository = DjangoAuditedCorporateActionPostingRepositoryFactory(
        environment="development", owner_grant_gate=gate
    ).build_posting_repository(
        source_qualifier=facts,
        ownership_verifier=facts,
        tax_basis_verifier=None,
        using="default",
    )
    first = repository.post_revision_with_audit((entitlement,))[0]
    second = repository.post_revision_with_audit((payment,))[0]
    assert first.entry_id != second.entry_id
    world.row.refresh_from_db()
    service.financial_cash_before = world.row.current_cash
    service.dividend_entitlement_receipt = first
    service.dividend_payment_receipt = second
    old = world.source
    observed = timezone.now()
    raw = SimulatedAccountRawObservation(
        observation_id=old.raw_observation_id,
        observation_version="audited-payment-successor",
        row_pk=world.row.pk,
        row_user_id=world.user.pk,
        raw_account_type="simulated",
        is_active=True,
        row_created_at=world.row.created_at,
        row_updated_at=world.row.updated_at,
        is_present=True,
        is_tombstone=False,
        observed_at=observed,
        valid_until=old.valid_until,
        supersedes_content_hash=old.raw_observation_content_hash,
    )
    source = replace(
        old,
        source_version="audited-payment-successor",
        supersedes_content_hash=old.content_hash,
        row_updated_at=world.row.updated_at,
        observed_at=observed,
        recorded_at=observed,
        raw_observation_version=raw.observation_version,
        raw_observation_identity_hash=raw.identity_hash,
        raw_observation_content_hash=raw.content_hash,
        raw_observation_observed_at=raw.observed_at,
        raw_observation_valid_until=raw.valid_until,
        raw_observation_supersedes_content_hash=raw.supersedes_content_hash,
        identity_hash="",
        content_hash="",
    )
    source_repository = DjangoSimulatedAccountRowSourceV2Repository()
    with source_repository.atomic():
        source_repository.append(
            PersistedSimulatedAccountRowSourceV2(source),
            expected_predecessor_hash=old.content_hash,
            recorded_at=observed,
        )
    world.source = source
    world.command = replace(
        world.command,
        expected_binding=replace(
            world.command.expected_binding,
            account_source_id=source.source_id,
            account_source_version=source.source_version,
            account_source_content_hash=source.content_hash,
        ),
    )
    return first, second
