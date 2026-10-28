"""Real ORM boundary tests for local operator-attested fee evidence.

The uploads and enabled policy rows in this module are synthetic test fixtures.
They exercise local byte integrity and owner attestation only; they are not
broker statements and do not prove issuer or broker authenticity.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeCorrectionAuthorityEventSnapshotJSON,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadReceipt,
    FeeCorrectionPolicySnapshotJSON,
    PersistedFeeCorrectionEventProof,
    fee_correction_policy_sha256,
)
from apps.simulated_trading.domain.fee_correction import CorrectableFeeComponents
from apps.simulated_trading.infrastructure.fee_correction_event_models import (
    SimulatedFeeCorrectionEventModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_codec import (
    parse_operator_fee_evidence_csv,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidenceArtifactModel,
    FeeCorrectionEvidenceBindingModel,
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_persisted_event_proofs import (
    DjangoPersistedFeeCorrectionSourceProof,
    PersistedFeeCorrectionAuthorityProof,
    proof_from_persisted_event,
)
from apps.simulated_trading.infrastructure.simulated_account_trade_models import (
    SimulatedAccountModel,
    SimulatedTradeModel,
)

_CSV_HEADER = (
    "schema_version,currency_code,source_account_ref,source_trade_ref,asset_code,side,quantity,"
    "price,amount,execution_at,source_observed_at,commission,transfer_fee,stamp_duty"
)


@dataclass(frozen=True)
class EvidenceScenario:
    """Synthetic local-owner, account, exact Trade, policy, and upload fixture."""

    owner: AuthenticatedFeeCorrectionPrincipalProtocol
    owner_id: int
    other_user: AuthenticatedFeeCorrectionPrincipalProtocol
    other_user_id: int
    account: SimulatedAccountModel
    other_account: SimulatedAccountModel
    trade: SimulatedTradeModel
    other_trade: SimulatedTradeModel
    policy: FeeCorrectionEvidencePolicyModel
    repository: DjangoFeeCorrectionEvidenceRepository
    content: bytes
    command: FeeCorrectionEvidenceUploadCommand


def _iso(value: datetime) -> str:
    """Return an aware source time in canonical UTC ISO form."""

    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _csv_upload(
    *,
    execution_at: datetime,
    source_observed_at: datetime,
    currency: str = "CNY",
    commission: str = "2.00",
    transfer_fee: str = "0.10",
    stamp_duty: str = "0.00",
) -> bytes:
    """Build the fixed one-row synthetic CSV, preserving each supplied lexeme."""

    values = (
        OPERATOR_FEE_CSV_SCHEMA,
        currency,
        "SYNTHETIC-ACCOUNT-REF",
        "SYNTHETIC-TRADE-REF",
        "600000.SH",
        "buy",
        "100.000000",
        "10.0000",
        "1000.00",
        _iso(execution_at),
        _iso(source_observed_at),
        commission,
        transfer_fee,
        stamp_duty,
    )
    return (_CSV_HEADER + "\n" + ",".join(values) + "\n").encode("utf-8")


def _make_account(
    *,
    owner: AuthenticatedFeeCorrectionPrincipalProtocol,
    name: str,
) -> SimulatedAccountModel:
    """Create a synthetic simulated account with explicit cash values."""

    return SimulatedAccountModel.objects.create(
        user=owner,
        account_name=name,
        account_type="simulated",
        initial_capital=Decimal("5000.00"),
        current_cash=Decimal("3995.90"),
        current_market_value=Decimal("1000.00"),
        total_value=Decimal("4995.90"),
    )


def _make_trade(
    *,
    account: SimulatedAccountModel,
    execution_time: datetime,
) -> SimulatedTradeModel:
    """Create a fully known, synthetic executed BUY matching the CSV row."""

    executed_date = execution_time.date()
    return SimulatedTradeModel.objects.create(
        account=account,
        asset_code="600000.SH",
        asset_name="Synthetic Example",
        asset_type="equity",
        action="buy",
        quantity=Decimal("100.000000"),
        price=Decimal("10.0000"),
        amount=Decimal("1000.00"),
        commission=Decimal("3.00"),
        transfer_fee=Decimal("0.10"),
        stamp_duty=Decimal("0.00"),
        slippage=Decimal("1.00"),
        total_cost=Decimal("1004.10"),
        fee_amounts_known=True,
        cost_basis_known=True,
        order_date=executed_date,
        execution_date=executed_date,
        execution_time=execution_time,
        status="executed",
    )


@pytest.fixture
def evidence_scenario(db: None) -> EvidenceScenario:
    """Create real Django rows using an explicitly enabled synthetic test policy."""

    user_model = get_user_model()
    owner = user_model.objects.create_user(
        username="synthetic-fee-evidence-owner",
        password="unused-test-password",
        email="synthetic-fee-owner@example.invalid",
    )
    other_user = user_model.objects.create_user(
        username="synthetic-fee-evidence-other",
        password="unused-test-password",
        email="synthetic-fee-other@example.invalid",
    )
    owner_id = cast(int, owner.pk)
    other_user_id = cast(int, other_user.pk)
    owner_principal = cast(AuthenticatedFeeCorrectionPrincipalProtocol, owner)
    other_principal = cast(AuthenticatedFeeCorrectionPrincipalProtocol, other_user)
    account = _make_account(owner=owner_principal, name="Synthetic evidence account")
    other_account = _make_account(owner=owner_principal, name="Synthetic second account")
    now = timezone.now()
    execution_time = now - timedelta(hours=2)
    observed_at = now - timedelta(minutes=1)
    trade = _make_trade(account=account, execution_time=execution_time)
    other_trade = _make_trade(account=other_account, execution_time=execution_time)
    policy = FeeCorrectionEvidencePolicyModel.objects.create(
        account=account,
        enabled=True,
        allow_operator_attested_upload=True,
        ledger_currency="CNY",
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=1),
        updated_by=owner,
    )
    content = _csv_upload(
        execution_at=execution_time,
        source_observed_at=observed_at,
    )
    command = FeeCorrectionEvidenceUploadCommand(
        account_id=cast(int, account.pk),
        trade_id=cast(int, trade.pk),
        expected_revision=0,
        expected_predecessor_id=None,
        idempotency_key="synthetic-upload-key-1",
        original_filename="synthetic-owner-attested.csv",
        content=content,
        attestation_acknowledged=True,
    )
    return EvidenceScenario(
        owner=owner_principal,
        owner_id=owner_id,
        other_user=other_principal,
        other_user_id=other_user_id,
        account=account,
        other_account=other_account,
        trade=trade,
        other_trade=other_trade,
        policy=policy,
        repository=DjangoFeeCorrectionEvidenceRepository(),
        content=content,
        command=command,
    )


def _upload_receipt(
    scenario: EvidenceScenario,
    *,
    command: FeeCorrectionEvidenceUploadCommand | None = None,
    principal: AuthenticatedFeeCorrectionPrincipalProtocol | object | None = None,
) -> FeeCorrectionEvidenceUploadReceipt:
    """Capture one synthetic upload through the real Django repository."""

    selected_principal = scenario.owner if principal is None else principal
    return scenario.repository.capture(
        scenario.command if command is None else command,
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, selected_principal),
    )


def _request(
    receipt: FeeCorrectionEvidenceUploadReceipt,
    scenario: EvidenceScenario,
    *,
    idempotency_key: str | None = None,
) -> FeeCorrectionRequest:
    """Use the original upload key when qualifying its stored source binding."""

    return FeeCorrectionRequest(
        account_id=cast(int, scenario.account.pk),
        trade_id=cast(int, scenario.trade.pk),
        idempotency_key=(
            scenario.command.idempotency_key if idempotency_key is None else idempotency_key
        ),
        expected_revision=0,
        source_locator=receipt.source_locator,
    )


def _persisted_proof(
    receipt: FeeCorrectionEvidenceUploadReceipt,
    scenario: EvidenceScenario,
) -> PersistedFeeCorrectionEventProof:
    """Build one complete synthetic event proof bound to the stored artifact."""

    binding = FeeCorrectionEvidenceBindingModel.objects.get(public_id=receipt.source_locator)
    artifact = FeeCorrectionEvidenceArtifactModel.objects.get(pk=binding.artifact_id)
    parsed = parse_operator_fee_evidence_csv(bytes(artifact.raw_bytes))
    policy_snapshot = cast(
        FeeCorrectionPolicySnapshotJSON,
        binding.policy_snapshot_json,
    )
    evidence_verified_at = timezone.now()
    posted_at = evidence_verified_at + timedelta(seconds=1)
    request_payload_hash = "9" * 64
    authority_record_id = f"fee-correction-policy:{binding.policy_id}:v{binding.policy_version}"
    authority_payload: FeeCorrectionAuthorityEventSnapshotJSON = {
        "schema": "simulated-fee-correction-authority-event.v1",
        "account_id": binding.account_id,
        "account_owner_user_id": binding.attested_by_id,
        "account_type": "simulated",
        "account_active": True,
        "actor_user_id": binding.attested_by_id,
        "actor_authenticated": True,
        "principal_enabled": True,
        "authority_identity": "local.owner_policy.v1",
        "authority_record_id": authority_record_id,
        "authority_sha256": binding.policy_sha256,
        "authorization_scope": "simulated_fee_correction:operator_attested_upload",
        "policy_version": policy_snapshot["version"],
        "policy_sha256": binding.policy_sha256,
        "policy_ledger_currency": policy_snapshot["ledger_currency"],
        "policy_enabled": policy_snapshot["enabled"],
        "policy_allows_operator_attested_upload": policy_snapshot[
            "allows_operator_attested_upload"
        ],
        "policy_valid_from": policy_snapshot["valid_from"],
        "policy_valid_until": policy_snapshot["valid_until"],
        "policy_updated_by_id": policy_snapshot["updated_by_id"],
        "trade_id": binding.trade_id,
        "trade_snapshot_hash": binding.trade_snapshot_sha256,
        "original_v4_receipt_hash": None,
        "receipt_snapshot_hash": None,
        "source_namespace": ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        "source_record_id": str(binding.public_id),
        "verifier_identity": "local.operator_attested_csv.v1",
        "source_evidence_hash": artifact.content_sha256,
        "source_payload_hash": artifact.payload_sha256,
        "source_observed_at": _iso(parsed.source_observed_at),
        "evidence_verified_at": _iso(evidence_verified_at),
        "idempotency_key": "synthetic-correction-event-key-1",
        "request_payload_hash": request_payload_hash,
        "revision": 1,
        "previous_event_id": None,
        "account_revision": 1,
        "account_predecessor_hash": "0" * 64,
        "previous_fees": {
            "commission": "3.00",
            "transfer_fee": "0.10",
            "stamp_duty": "0.00",
        },
        "revised_fees": {
            "commission": format(cast(Decimal, parsed.fee_amounts[0]), ".2f"),
            "transfer_fee": format(cast(Decimal, parsed.fee_amounts[1]), ".2f"),
            "stamp_duty": format(cast(Decimal, parsed.fee_amounts[2]), ".2f"),
        },
        "original_slippage": "1.00",
        "posting_time": _iso(posted_at),
        "posting_date": posted_at.date().isoformat(),
    }
    authority_sha256 = hashlib.sha256(
        json.dumps(
            authority_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return PersistedFeeCorrectionEventProof(
        account_id=binding.account_id,
        trade_id=binding.trade_id,
        actor_user_id=binding.attested_by_id,
        revision=1,
        previous_event_id=None,
        account_revision=1,
        account_predecessor_hash="0" * 64,
        idempotency_key="synthetic-correction-event-key-1",
        request_payload_hash=request_payload_hash,
        trade_snapshot_hash=binding.trade_snapshot_sha256,
        original_v4_receipt_hash=None,
        receipt_snapshot_hash=None,
        source_namespace=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        source_record_id=str(binding.public_id),
        verifier_identity="local.operator_attested_csv.v1",
        source_evidence_hash=artifact.content_sha256,
        source_payload_hash=artifact.payload_sha256,
        source_observed_at=parsed.source_observed_at,
        evidence_verified_at=evidence_verified_at,
        authority_identity="local.owner_policy.v1",
        authority_record_id=authority_record_id,
        authority_hash=binding.policy_sha256,
        authority_snapshot_sha256=authority_sha256,
        authority_snapshot_json=authority_payload,
        previous_fee_components=CorrectableFeeComponents(
            commission=Decimal("3.00"),
            transfer_fee=Decimal("0.10"),
            stamp_duty=Decimal("0.00"),
        ),
        revised_fee_components=CorrectableFeeComponents(
            commission=cast(Decimal, parsed.fee_amounts[0]),
            transfer_fee=cast(Decimal, parsed.fee_amounts[1]),
            stamp_duty=cast(Decimal, parsed.fee_amounts[2]),
        ),
        original_slippage=scenario.trade.slippage,
        posted_at=posted_at,
        posting_date=posted_at.date(),
    )


def _persisted_event(
    proof: PersistedFeeCorrectionEventProof,
    scenario: EvidenceScenario,
) -> SimulatedFeeCorrectionEventModel:
    """Persist a synthetic event row for event-to-proof/source-reader tests."""

    commission_delta = (
        proof.revised_fee_components.commission - proof.previous_fee_components.commission
    )
    transfer_fee_delta = (
        proof.revised_fee_components.transfer_fee - proof.previous_fee_components.transfer_fee
    )
    stamp_duty_delta = (
        proof.revised_fee_components.stamp_duty - proof.previous_fee_components.stamp_duty
    )
    total_fee_delta = commission_delta + transfer_fee_delta + stamp_duty_delta
    return SimulatedFeeCorrectionEventModel.objects.create(
        account=scenario.account,
        trade=scenario.trade,
        actor_user_id=proof.actor_user_id,
        revision=proof.revision,
        account_revision=proof.account_revision,
        account_predecessor_hash=proof.account_predecessor_hash,
        # This fixture exercises the event/proof adapter, not prefix-chain verification.
        account_prefix_hash="a" * 64,
        previous_event_id=proof.previous_event_id,
        idempotency_key=proof.idempotency_key,
        request_payload_hash=proof.request_payload_hash,
        trade_snapshot_hash=proof.trade_snapshot_hash,
        receipt_snapshot_hash=proof.receipt_snapshot_hash,
        source_namespace=proof.source_namespace,
        source_record_id=proof.source_record_id,
        verifier_identity=proof.verifier_identity,
        source_evidence_hash=proof.source_evidence_hash,
        source_payload_hash=proof.source_payload_hash,
        source_observed_at=proof.source_observed_at,
        evidence_verified_at=proof.evidence_verified_at,
        authority_identity=proof.authority_identity,
        authority_record_id=proof.authority_record_id,
        authority_hash=proof.authority_hash,
        authority_snapshot_json=proof.authority_snapshot_json,
        authority_snapshot_sha256=proof.authority_snapshot_sha256,
        previous_commission=proof.previous_fee_components.commission,
        previous_transfer_fee=proof.previous_fee_components.transfer_fee,
        previous_stamp_duty=proof.previous_fee_components.stamp_duty,
        revised_commission=proof.revised_fee_components.commission,
        revised_transfer_fee=proof.revised_fee_components.transfer_fee,
        revised_stamp_duty=proof.revised_fee_components.stamp_duty,
        original_slippage=proof.original_slippage,
        commission_delta=commission_delta,
        transfer_fee_delta=transfer_fee_delta,
        stamp_duty_delta=stamp_duty_delta,
        total_fee_delta=total_fee_delta,
        cash_delta=-total_fee_delta,
        posted_at=proof.posted_at,
        posting_date=proof.posting_date,
    )


@pytest.mark.django_db
def test_capture_persists_exact_bytes_row_hash_and_operator_assurance(
    evidence_scenario: EvidenceScenario,
) -> None:
    """The artifact and binding preserve local input facts without broker claims."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    artifact = FeeCorrectionEvidenceArtifactModel.objects.get(
        account=scenario.account,
        content_sha256=hashlib.sha256(scenario.content).hexdigest(),
    )
    binding = FeeCorrectionEvidenceBindingModel.objects.get(public_id=receipt.source_locator)
    parsed = parse_operator_fee_evidence_csv(scenario.content)

    assert bytes(artifact.raw_bytes) == scenario.content
    assert artifact.content_sha256 == hashlib.sha256(scenario.content).hexdigest()
    assert artifact.payload_sha256 == parsed.payload_sha256
    assert artifact.raw_row_json == parsed.raw_row
    assert artifact.parsed_metadata_json == parsed.parsed_metadata
    assert parsed.raw_row["transfer_fee"] == "0.10"
    assert parsed.fee_precisions == (2, 2, 2)
    assert parsed.fee_known == (True, True, True)
    assert artifact.schema_version == OPERATOR_FEE_CSV_SCHEMA
    assert artifact.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert artifact.uploaded_by_id == scenario.owner_id
    assert binding.account_id == scenario.account.pk
    assert binding.trade_id == scenario.trade.pk
    assert binding.artifact_id == artifact.pk
    assert binding.attested_by_id == scenario.owner_id
    assert binding.attestation_version == OPERATOR_ATTESTATION_VERSION
    assert binding.attestation_acknowledged is True
    assert binding.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert binding.content_sha256 == artifact.content_sha256
    assert binding.payload_sha256 == artifact.payload_sha256
    assert binding.trade_snapshot_sha256 == scenario.repository.hash_trade(
        trade=scenario.trade,
        original_v4_receipt_hash=None,
    )
    assert receipt.assurance_class == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert (
        scenario.repository.authorize(
            account_id=cast(int, scenario.account.pk),
            principal=scenario.owner,
        )
        is not None
    )
    verified = scenario.repository.verify(_request(receipt, scenario))
    assert verified is not None
    assert verified.source_namespace == ASSURANCE_OPERATOR_ATTESTED_UPLOAD
    assert verified.source_record_id == receipt.source_locator
    assert verified.evidence_sha256 == artifact.content_sha256
    assert verified.source_payload_sha256 == artifact.payload_sha256
    assert verified.verifier_identity == "local.operator_attested_csv.v1"
    assert "broker" not in verified.verifier_identity.lower()


@pytest.mark.django_db
def test_multirow_upload_is_rejected_before_any_artifact_or_binding_write(
    evidence_scenario: EvidenceScenario,
) -> None:
    """The finite CSV contract accepts exactly one data row."""

    scenario = evidence_scenario
    invalid_command = replace(
        scenario.command,
        idempotency_key="synthetic-multirow-upload",
        content=scenario.content + scenario.content.splitlines(keepends=True)[1],
    )
    with pytest.raises(FeeCorrectionBlockedError) as captured:
        _upload_receipt(scenario, command=invalid_command)

    assert captured.value.code == "FEE_CORRECTION_EVIDENCE_INVALID"
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == 0
    assert FeeCorrectionEvidenceBindingModel.objects.count() == 0


@pytest.mark.django_db
def test_real_owner_and_simple_lazy_request_user_are_accepted(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Actual user rows and Django's lazy request-user proxy remain supported."""

    scenario = evidence_scenario
    first = _upload_receipt(scenario)
    lazy_principal = SimpleLazyObject(lambda: scenario.owner)
    proxy_trade = _make_trade(
        account=scenario.account,
        execution_time=scenario.trade.execution_time,
    )
    proxy_command = replace(
        scenario.command,
        trade_id=cast(int, proxy_trade.pk),
        idempotency_key="synthetic-upload-key-proxy",
    )
    second = _upload_receipt(
        scenario,
        command=proxy_command,
        principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, lazy_principal),
    )

    assert first.source_locator != second.source_locator
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account=scenario.account).count() == 2
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account=scenario.account).count() == 2
    assert (
        FeeCorrectionEvidenceBindingModel.objects.get(public_id=second.source_locator).trade_id
        == proxy_trade.pk
    )


@pytest.mark.django_db
def test_namespace_with_claimed_owner_id_is_not_an_authenticated_principal(
    evidence_scenario: EvidenceScenario,
) -> None:
    """A caller-created namespace cannot substitute for Django request.user."""

    scenario = evidence_scenario
    forged_namespace = SimpleNamespace(
        pk=scenario.owner_id,
        is_authenticated=True,
    )
    with pytest.raises(FeeCorrectionBlockedError) as captured:
        _upload_receipt(
            scenario,
            principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, forged_namespace),
        )

    assert captured.value.code == "FEE_CORRECTION_PRINCIPAL_INVALID"
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == 0
    assert FeeCorrectionEvidenceBindingModel.objects.count() == 0


@pytest.mark.django_db
def test_cross_owner_and_cross_account_trade_bindings_are_rejected(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Both the request principal and selected Trade must match the locked account."""

    scenario = evidence_scenario
    with pytest.raises(FeeCorrectionBlockedError) as wrong_owner:
        _upload_receipt(scenario, principal=scenario.other_user)
    assert wrong_owner.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    wrong_trade_command = replace(
        scenario.command,
        trade_id=cast(int, scenario.other_trade.pk),
        idempotency_key="synthetic-cross-account-trade",
    )
    with pytest.raises(FeeCorrectionBlockedError) as cross_account:
        _upload_receipt(scenario, command=wrong_trade_command)
    assert cross_account.value.code == "FEE_CORRECTION_TRADE_SCOPE_INVALID"
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == 0
    assert FeeCorrectionEvidenceBindingModel.objects.count() == 0


@pytest.mark.django_db
def test_inactive_user_and_disabled_policy_fail_closed(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Only an active owner and explicit enabled qualification policy can upload."""

    scenario = evidence_scenario
    scenario.policy.enabled = False
    scenario.policy.allow_operator_attested_upload = False
    scenario.policy.save(update_fields=("enabled", "allow_operator_attested_upload"))
    assert scenario.policy.version == 2
    assert (
        scenario.repository.authorize(
            account_id=cast(int, scenario.account.pk),
            principal=scenario.owner,
        )
        is None
    )
    with pytest.raises(FeeCorrectionBlockedError) as denied_policy:
        _upload_receipt(scenario)
    assert denied_policy.value.code == "FEE_CORRECTION_POLICY_DENIED"

    scenario.policy.enabled = True
    scenario.policy.allow_operator_attested_upload = True
    scenario.policy.ledger_currency = "CNY"
    scenario.policy.updated_by_id = scenario.owner_id
    scenario.policy.save()
    owner_model = get_user_model()
    owner_row = owner_model.objects.get(pk=scenario.owner_id)
    owner_row.is_active = False
    owner_row.save(update_fields=("is_active",))
    with pytest.raises(FeeCorrectionBlockedError) as denied_user:
        _upload_receipt(
            scenario, command=replace(scenario.command, idempotency_key="inactive-owner")
        )
    assert denied_user.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
    assert FeeCorrectionEvidenceArtifactModel.objects.count() == 0


@pytest.mark.django_db
def test_currency_mismatch_unknown_fee_and_revoked_policy_never_verify(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Currency is explicit, unknown is not zero, and revocation invalidates live proof."""

    scenario = evidence_scenario
    parsed_times = parse_operator_fee_evidence_csv(scenario.content)
    wrong_currency = _csv_upload(
        execution_at=parsed_times.execution_at,
        source_observed_at=parsed_times.source_observed_at,
        currency="USD",
    )
    wrong_currency_command = replace(
        scenario.command,
        idempotency_key="synthetic-wrong-currency",
        content=wrong_currency,
    )
    with pytest.raises(FeeCorrectionBlockedError) as mismatch:
        _upload_receipt(scenario, command=wrong_currency_command)
    assert mismatch.value.code == "FEE_CORRECTION_CURRENCY_MISMATCH"

    unknown_fee = _csv_upload(
        execution_at=parsed_times.execution_at,
        source_observed_at=parsed_times.source_observed_at,
        commission=r"\N",
    )
    unknown_command = replace(
        scenario.command,
        idempotency_key="synthetic-unknown-fee",
        content=unknown_fee,
    )
    unknown_receipt = _upload_receipt(scenario, command=unknown_command)
    artifact = FeeCorrectionEvidenceArtifactModel.objects.get(
        content_sha256=hashlib.sha256(unknown_fee).hexdigest()
    )
    assert artifact.raw_row_json["commission"] == r"\N"
    assert artifact.parsed_metadata_json["fees"][0]["known"] is False
    assert artifact.parsed_metadata_json["fees"][0]["value"] is None
    assert (
        scenario.repository.verify(
            _request(unknown_receipt, scenario, idempotency_key=unknown_command.idempotency_key)
        )
        is None
    )

    valid_trade = _make_trade(
        account=scenario.account,
        execution_time=scenario.trade.execution_time,
    )
    valid_command = replace(
        scenario.command,
        trade_id=cast(int, valid_trade.pk),
        idempotency_key="synthetic-valid-after-unknown-fee",
    )
    valid_receipt = _upload_receipt(scenario, command=valid_command)
    valid_request = FeeCorrectionRequest(
        account_id=cast(int, scenario.account.pk),
        trade_id=cast(int, valid_trade.pk),
        idempotency_key=valid_command.idempotency_key,
        expected_revision=0,
        source_locator=valid_receipt.source_locator,
    )
    assert scenario.repository.verify(valid_request) is not None
    scenario.policy.enabled = False
    scenario.policy.allow_operator_attested_upload = False
    scenario.policy.save(update_fields=("enabled", "allow_operator_attested_upload"))
    assert scenario.repository.verify(valid_request) is None


@pytest.mark.django_db
def test_same_upload_idempotency_replays_and_conflicting_bytes_are_rejected(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Identical retry returns the same immutable binding; changed bytes conflict."""

    scenario = evidence_scenario
    first = _upload_receipt(scenario)
    replay = _upload_receipt(scenario)
    assert replay.source_locator == first.source_locator
    assert replay.content_sha256 == first.content_sha256
    assert replay.payload_sha256 == first.payload_sha256
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account=scenario.account).count() == 1
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account=scenario.account).count() == 1

    second_trade = _make_trade(
        account=scenario.account,
        execution_time=scenario.trade.execution_time,
    )
    target_conflict = replace(
        scenario.command,
        trade_id=cast(int, second_trade.pk),
    )
    with pytest.raises(FeeCorrectionBlockedError) as target_conflict_error:
        _upload_receipt(scenario, command=target_conflict)
    assert target_conflict_error.value.code == "FEE_CORRECTION_EVIDENCE_IDEMPOTENCY_CONFLICT"
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account=scenario.account).count() == 1
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account=scenario.account).count() == 1

    parsed = parse_operator_fee_evidence_csv(scenario.content)
    changed_bytes = _csv_upload(
        execution_at=parsed.execution_at,
        source_observed_at=parsed.source_observed_at,
        commission="2.50",
    )
    conflict_command = replace(scenario.command, content=changed_bytes)
    with pytest.raises(FeeCorrectionBlockedError) as conflict:
        _upload_receipt(scenario, command=conflict_command)
    assert conflict.value.code == "FEE_CORRECTION_EVIDENCE_IDEMPOTENCY_CONFLICT"
    assert FeeCorrectionEvidenceBindingModel.objects.filter(account=scenario.account).count() == 1
    assert FeeCorrectionEvidenceArtifactModel.objects.filter(account=scenario.account).count() == 1


@pytest.mark.django_db
def test_trade_economic_change_makes_existing_upload_stale(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Changing exact Trade economics invalidates an old binding, without an age rule."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    request = _request(receipt, scenario)
    assert scenario.repository.verify(request) is not None

    scenario.trade.price = Decimal("10.0100")
    scenario.trade.amount = Decimal("1001.00")
    scenario.trade.total_cost = Decimal("1005.10")
    scenario.trade.save(update_fields=("price", "amount", "total_cost"))

    assert scenario.repository.verify(request) is None


@pytest.mark.django_db
def test_model_save_and_default_or_base_queryset_guards_are_real_orm_boundaries(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Normal ORM writes are blocked; policy changes use the versioned save path."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    artifact = FeeCorrectionEvidenceArtifactModel.objects.get(content_sha256=receipt.content_sha256)
    binding = FeeCorrectionEvidenceBindingModel.objects.get(public_id=receipt.source_locator)
    original_bytes = bytes(artifact.raw_bytes)
    original_row = dict(binding.policy_snapshot_json)

    artifact.raw_bytes = b"synthetic mutation rejected"
    with pytest.raises(ValidationError):
        artifact.save()
    with pytest.raises(ValidationError):
        artifact.delete()
    for manager in (
        FeeCorrectionEvidenceArtifactModel.objects,
        FeeCorrectionEvidenceArtifactModel._base_manager,
    ):
        with pytest.raises(ValidationError):
            manager.filter(pk=artifact.pk).update(raw_bytes=b"synthetic mutation rejected")
        with pytest.raises(ValidationError):
            manager.filter(pk=artifact.pk).delete()

    binding.created_at += timedelta(seconds=1)
    with pytest.raises(ValidationError):
        binding.save()
    with pytest.raises(ValidationError):
        FeeCorrectionEvidenceBindingModel._base_manager.filter(pk=binding.pk).update(
            policy_snapshot_json={"schema": "synthetic-tamper"}
        )

    for manager in (
        FeeCorrectionEvidencePolicyModel.objects,
        FeeCorrectionEvidencePolicyModel._base_manager,
    ):
        with pytest.raises(ValidationError):
            manager.filter(pk=scenario.policy.pk).update(enabled=False)
    scenario.policy.enabled = False
    scenario.policy.save(update_fields=("enabled",))
    assert scenario.policy.version == 2
    artifact.refresh_from_db()
    binding.refresh_from_db()
    assert bytes(artifact.raw_bytes) == original_bytes
    assert binding.policy_snapshot_json == original_row


@pytest.mark.django_db
def test_historical_source_proof_survives_current_owner_and_policy_changes(
    evidence_scenario: EvidenceScenario,
) -> None:
    """Historical qualification uses captured policy and attester, not current rows."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    event = _persisted_event(_persisted_proof(receipt, scenario), scenario)
    translated_proof = proof_from_persisted_event(
        event,
        original_v4_receipt_hash=None,
    )
    assert scenario.repository.verify_persisted_event(translated_proof) is True
    source_proof = DjangoPersistedFeeCorrectionSourceProof(scenario.repository)
    assert source_proof.validate_event(event, original_v4_receipt_hash=None) is True

    scenario.account.user_id = scenario.other_user_id
    scenario.account.save(update_fields=("user",))
    scenario.policy.enabled = False
    scenario.policy.allow_operator_attested_upload = False
    scenario.policy.ledger_currency = "USD"
    scenario.policy.updated_by_id = scenario.other_user_id
    scenario.policy.save()

    event.refresh_from_db()
    assert source_proof.validate_event(event, original_v4_receipt_hash=None) is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tamper",
    ("artifact_bytes", "artifact_row_snapshot", "artifact_content_hash", "binding_policy_snapshot"),
)
def test_historical_source_proof_fails_after_persisted_record_tampering(
    evidence_scenario: EvidenceScenario,
    tamper: str,
) -> None:
    """The verifier notices low-level tampering despite ordinary ORM guards."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    event = _persisted_event(_persisted_proof(receipt, scenario), scenario)
    source_proof = DjangoPersistedFeeCorrectionSourceProof(scenario.repository)
    assert source_proof.validate_event(event, original_v4_receipt_hash=None) is True
    binding = FeeCorrectionEvidenceBindingModel.objects.get(public_id=receipt.source_locator)
    artifact = FeeCorrectionEvidenceArtifactModel.objects.get(pk=binding.artifact_id)

    # Call the base QuerySet implementation only to simulate privileged raw-row
    # corruption. This test does not claim ORM hooks protect against DB authority.
    if tamper == "artifact_bytes":
        altered = scenario.content.replace(b"2.00", b"9.99", 1)
        models.QuerySet.update(
            FeeCorrectionEvidenceArtifactModel.objects.filter(pk=artifact.pk),
            raw_bytes=altered,
        )
    elif tamper == "artifact_row_snapshot":
        altered_row = dict(artifact.raw_row_json)
        altered_row["commission"] = "9.99"
        models.QuerySet.update(
            FeeCorrectionEvidenceArtifactModel.objects.filter(pk=artifact.pk),
            raw_row_json=altered_row,
        )
    elif tamper == "artifact_content_hash":
        models.QuerySet.update(
            FeeCorrectionEvidenceArtifactModel.objects.filter(pk=artifact.pk),
            content_sha256="f" * 64,
        )
    elif tamper == "binding_policy_snapshot":
        altered_policy = dict(binding.policy_snapshot_json)
        altered_policy["version"] = altered_policy["version"] + 1
        models.QuerySet.update(
            FeeCorrectionEvidenceBindingModel.objects.filter(pk=binding.pk),
            policy_snapshot_json=altered_policy,
        )
    else:
        raise AssertionError(f"unhandled tamper case: {tamper}")

    event.refresh_from_db()
    assert source_proof.validate_event(event, original_v4_receipt_hash=None) is False


@pytest.mark.django_db
def test_historical_event_authority_snapshot_hash_tampering_is_rejected(
    evidence_scenario: EvidenceScenario,
) -> None:
    """A valid source binding cannot repair a changed event authorization seal."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    event = _persisted_event(_persisted_proof(receipt, scenario), scenario)
    assert (
        PersistedFeeCorrectionAuthorityProof().validate_event(
            event,
            original_v4_receipt_hash=None,
        )
        is True
    )
    # This bypass simulates privileged stored-row tampering; it is not an ORM guarantee.
    models.QuerySet.update(
        SimulatedFeeCorrectionEventModel.objects.filter(pk=event.pk),
        authority_snapshot_sha256="0" * 64,
    )
    event.refresh_from_db()

    assert (
        PersistedFeeCorrectionAuthorityProof().validate_event(
            event,
            original_v4_receipt_hash=None,
        )
        is False
    )
    assert (
        DjangoPersistedFeeCorrectionSourceProof(scenario.repository).validate_event(
            event,
            original_v4_receipt_hash=None,
        )
        is False
    )


@pytest.mark.django_db
def test_self_consistent_event_actor_change_still_fails_source_binding(
    evidence_scenario: EvidenceScenario,
) -> None:
    """A recomputed event seal cannot rebind old evidence to another actor."""

    scenario = evidence_scenario
    receipt = _upload_receipt(scenario)
    event = _persisted_event(_persisted_proof(receipt, scenario), scenario)
    authority_payload = dict(event.authority_snapshot_json)
    authority_payload["account_owner_user_id"] = scenario.other_user_id
    authority_payload["actor_user_id"] = scenario.other_user_id
    authority_payload["policy_updated_by_id"] = scenario.other_user_id
    valid_from_value = authority_payload["policy_valid_from"]
    valid_until_value = authority_payload["policy_valid_until"]
    policy_sha256 = fee_correction_policy_sha256(
        account_id=cast(int, authority_payload["account_id"]),
        version=cast(int, authority_payload["policy_version"]),
        enabled=cast(bool, authority_payload["policy_enabled"]),
        allows_operator_attested_upload=cast(
            bool,
            authority_payload["policy_allows_operator_attested_upload"],
        ),
        ledger_currency=cast(str, authority_payload["policy_ledger_currency"]),
        valid_from=(
            datetime.fromisoformat(cast(str, valid_from_value).replace("Z", "+00:00"))
            if valid_from_value is not None
            else None
        ),
        valid_until=(
            datetime.fromisoformat(cast(str, valid_until_value).replace("Z", "+00:00"))
            if valid_until_value is not None
            else None
        ),
        updated_by_id=scenario.other_user_id,
    )
    authority_payload["authority_sha256"] = policy_sha256
    authority_payload["policy_sha256"] = policy_sha256
    authority_sha256 = hashlib.sha256(
        json.dumps(
            authority_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    # Use Django's base QuerySet only to simulate a privileged stored-row rewrite.
    models.QuerySet.update(
        SimulatedFeeCorrectionEventModel.objects.filter(pk=event.pk),
        actor_user_id=scenario.other_user_id,
        authority_hash=policy_sha256,
        authority_snapshot_json=authority_payload,
        authority_snapshot_sha256=authority_sha256,
    )
    event.refresh_from_db()

    # The payload is internally self-consistent, but does not match the immutable binding.
    assert (
        PersistedFeeCorrectionAuthorityProof().validate_event(
            event,
            original_v4_receipt_hash=None,
        )
        is True
    )
    assert (
        DjangoPersistedFeeCorrectionSourceProof(scenario.repository).validate_event(
            event,
            original_v4_receipt_hash=None,
        )
        is False
    )
