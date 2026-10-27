"""Pure contract tests for the operator-attested fee evidence boundary.

All rows below are synthetic mechanism fixtures. They are not broker records
and do not assert issuer authenticity.
"""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

from apps.simulated_trading.application.fee_correction import (
    FeeCorrectionBlockedError,
    FeeCorrectionRequest,
)
from apps.simulated_trading.application.fee_correction_evidence import (
    ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
    OPERATOR_ATTESTATION_VERSION,
    OPERATOR_FEE_CSV_SCHEMA,
    CorrectableFeeComponents,
    FeeCorrectionEvidencePersistedEventSnapshot,
    FeeCorrectionEvidencePredecessorSnapshot,
    FeeCorrectionEvidenceUploadCommand,
    FeeCorrectionEvidenceUploadReceipt,
    FeeCorrectionEvidenceUploadUseCase,
    FeeCorrectionEvidenceVerificationSnapshot,
    PersistedFeeCorrectionEventProof,
    TradeEconomicFingerprintInput,
    fee_correction_policy_sha256,
    fee_correction_policy_snapshot_json,
    trade_economic_fingerprint_sha256,
    verify_fee_correction_evidence_snapshot,
    verify_persisted_fee_correction_authority_snapshot,
    verify_persisted_fee_correction_event_snapshot,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_codec import (
    FeeEvidenceCsvParseError,
    parse_operator_fee_evidence_csv,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_receipt_codec import (
    receipt_snapshot_sha256,
)

_HEADERS = (
    "schema_version,currency_code,source_account_ref,source_trade_ref,asset_code,side,quantity,"
    "price,amount,execution_at,source_observed_at,commission,transfer_fee,stamp_duty"
)
_LOCATOR = "12345678-1234-5678-1234-567812345678"
_NOW = datetime(2026, 10, 25, 5, 0, tzinfo=UTC)


def _upload(
    *,
    currency: str = "CNY",
    commission: str = "2.00",
    transfer_fee: str = "0.10",
    stamp_duty: str = "0.00",
) -> bytes:
    """Return one synthetic fixed-schema row for parser and verifier tests."""

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
        "2026-10-25T09:30:00+08:00",
        "2026-10-25T10:00:00+08:00",
        commission,
        transfer_fee,
        stamp_duty,
    )
    return (_HEADERS + "\n" + ",".join(values) + "\n").encode("utf-8")


def _trade() -> TradeEconomicFingerprintInput:
    """Return one synthetic exact Trade fingerprint input."""

    return TradeEconomicFingerprintInput(
        account_id=10,
        account_owner_id=5,
        trade_id=42,
        asset_code="600000.SH",
        asset_name="浦发银行",
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
        realized_pnl=None,
        realized_pnl_pct=None,
        order_date=date(2026, 10, 25),
        execution_date=date(2026, 10, 25),
        execution_time=datetime(2026, 10, 25, 9, 30, tzinfo=timezone(timedelta(hours=8))),
        status="executed",
        idempotency_key="synthetic-trade-key",
        request_payload_hash="a" * 64,
        fee_config_id=3,
        fee_schedule_hash="b" * 64,
        fee_precision_basis="yuan-cent",
        fee_calculation_purpose="NORMAL_SIM_ESTIMATED",
        fee_rounding_policy="half-even",
        settlement_security_id="SYNTHETIC-SECURITY-ID",
        settlement_market="SYNTHETIC-MARKET",
        settlement_exchange="SYNTHETIC-EXCHANGE",
        settlement_board="SYNTHETIC-BOARD",
        settlement_market_session=date(2026, 10, 26),
        settlement_lag_sessions=1,
        settlement_plan_binding_version=1,
        settlement_plan_binding_hash="c" * 64,
        settlement_bundle_id="SYNTHETIC-BUNDLE",
        settlement_bundle_version="v1",
        settlement_bundle_hash="d" * 64,
        settlement_policy_id="SYNTHETIC-POLICY",
        settlement_policy_version="v1",
        settlement_policy_hash="e" * 64,
        execution_rule_v2_hash="f" * 64,
        original_v4_receipt_hash="1" * 64,
    )


def _snapshot(
    content: bytes | None = None,
) -> tuple[FeeCorrectionEvidenceVerificationSnapshot, FeeCorrectionRequest]:
    """Build an internally consistent synthetic local verification snapshot."""

    upload = _upload() if content is None else content
    parsed = parse_operator_fee_evidence_csv(upload)
    trade = _trade()
    policy_values = {
        "account_id": 10,
        "version": 2,
        "enabled": True,
        "allows_operator_attested_upload": True,
        "ledger_currency": "CNY",
        "valid_from": _NOW - timedelta(days=1),
        "valid_until": _NOW + timedelta(days=1),
        "updated_by_id": 5,
    }
    policy_snapshot = fee_correction_policy_snapshot_json(**policy_values)
    policy_hash = fee_correction_policy_sha256(**policy_values)
    trade_hash = trade_economic_fingerprint_sha256(trade)
    snapshot = FeeCorrectionEvidenceVerificationSnapshot(
        binding_locator=_LOCATOR,
        artifact_account_id=10,
        artifact_uploaded_by_id=5,
        artifact_bytes=upload,
        artifact_sha256=hashlib.sha256(upload).hexdigest(),
        artifact_payload_sha256=parsed.payload_sha256,
        artifact_raw_row=parsed.raw_row,
        artifact_parsed_metadata=parsed.parsed_metadata,
        artifact_uploaded_at=_NOW - timedelta(minutes=5),
        artifact_schema_version=OPERATOR_FEE_CSV_SCHEMA,
        artifact_assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        binding_account_id=10,
        binding_trade_id=42,
        binding_attested_by_id=5,
        binding_attestation_version=OPERATOR_ATTESTATION_VERSION,
        binding_attestation_acknowledged=True,
        binding_assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
        binding_content_sha256=hashlib.sha256(upload).hexdigest(),
        binding_payload_sha256=parsed.payload_sha256,
        binding_created_at=_NOW - timedelta(minutes=3),
        binding_idempotency_key="synthetic-correction-key",
        binding_expected_revision=0,
        binding_expected_predecessor_id=None,
        binding_trade_snapshot_sha256=trade_hash,
        binding_policy_version=2,
        binding_policy_sha256=policy_hash,
        policy_ledger_currency="CNY",
        binding_policy_snapshot=policy_snapshot,
        current_account_id=10,
        current_account_owner_id=5,
        policy_account_id=10,
        policy_version=2,
        policy_enabled=True,
        policy_allows_operator_attested_upload=True,
        policy_valid_from=policy_values["valid_from"],
        policy_valid_until=policy_values["valid_until"],
        policy_updated_by_id=5,
        trade=trade,
        predecessor=None,
        parsed_upload=parsed,
    )
    request = FeeCorrectionRequest(
        account_id=10,
        trade_id=42,
        idempotency_key="synthetic-correction-key",
        expected_revision=0,
        source_locator=_LOCATOR,
    )
    return snapshot, request


@dataclass(frozen=True, slots=True)
class _Principal:
    """Synthetic request principal; never a broker identity or source proof."""

    is_authenticated: bool
    pk: int | None


@dataclass(frozen=True, slots=True)
class _SyntheticReceipt:
    """Mechanism-only V4 receipt row; it is not production evidence."""

    pk: int
    reservation_id: int
    trade_id: int
    fill_sequence: int
    source_namespace: str
    source_version: str
    source_event_id: str
    event_kind: str
    source_event_payload_hash: str
    source_event_snapshot_hash: str
    economic_request_hash: str
    economics_snapshot_hash: str
    plan_snapshot_hash: str
    receipt_hash: str
    receipt_version: int


class _CaptureRepository:
    """In-memory application port used only by the pure use-case test."""

    def __init__(self) -> None:
        self.calls = 0

    def capture(
        self,
        command: FeeCorrectionEvidenceUploadCommand,
        *,
        principal: _Principal,
    ) -> FeeCorrectionEvidenceUploadReceipt:
        """Return a synthetic storage receipt and record the authenticated call."""

        self.calls += 1
        return FeeCorrectionEvidenceUploadReceipt(
            source_locator=_LOCATOR,
            content_sha256=hashlib.sha256(command.content).hexdigest(),
            payload_sha256="2" * 64,
            assurance_class=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
            stored_at=_NOW,
        )


class FeeCorrectionEvidenceContractTests(unittest.TestCase):
    """Exercise strict parsing, fail-closed qualification, and owner binding."""

    def test_parser_keeps_exact_raw_fee_precision_and_observation_time(self) -> None:
        """Persisted hashes retain fee lexemes and source time, not upload time."""

        parsed = parse_operator_fee_evidence_csv(_upload(commission="2.0"))
        self.assertEqual(parsed.fee_lexemes[0], "2.0")
        self.assertEqual(parsed.fee_precisions[0], 1)
        self.assertEqual(parsed.fee_known, (True, True, True))
        self.assertEqual(parsed.currency_code, "CNY")
        self.assertEqual(parsed.source_observed_at.utcoffset(), timedelta(hours=8))
        changed = parse_operator_fee_evidence_csv(_upload(commission="2.00"))
        self.assertNotEqual(parsed.payload_sha256, changed.payload_sha256)

    def test_parser_preserves_missing_fee_as_unknown_not_zero(self) -> None:
        """The explicit null token remains unknown and cannot be qualified."""

        content = _upload(transfer_fee=r"\N")
        parsed = parse_operator_fee_evidence_csv(content)
        self.assertIsNone(parsed.fee_amounts[1])
        self.assertIsNone(parsed.fee_precisions[1])
        self.assertEqual(parsed.fee_known, (True, False, True))
        self.assertEqual(parsed.fee_lexemes[1], r"\N")
        snapshot, request = _snapshot(content)
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(snapshot, request, verified_at=_NOW)
        )

    def test_parser_rejects_multiple_rows_and_noncanonical_schema(self) -> None:
        """Ambiguous CSV layouts never become evidence rows."""

        content = _upload()
        with self.assertRaises(FeeEvidenceCsvParseError):
            parse_operator_fee_evidence_csv(content + content.splitlines(keepends=True)[1])
        with self.assertRaises(FeeEvidenceCsvParseError):
            parse_operator_fee_evidence_csv(
                content.replace(b"commission", b"commission,commission", 1)
            )
        with self.assertRaises(FeeEvidenceCsvParseError):
            parse_operator_fee_evidence_csv(_upload(currency="Cny"))

    def test_receipt_snapshot_hash_binds_row_identity_separately_from_receipt_hash(self) -> None:
        """The secondary digest matches R4's exact immutable receipt envelope."""

        receipt = _SyntheticReceipt(
            pk=8,
            reservation_id=3,
            trade_id=42,
            fill_sequence=1,
            source_namespace="synthetic.source",
            source_version="v1",
            source_event_id="synthetic-event-1",
            event_kind="fill",
            source_event_payload_hash="a" * 64,
            source_event_snapshot_hash="b" * 64,
            economic_request_hash="c" * 64,
            economics_snapshot_hash="d" * 64,
            plan_snapshot_hash="e" * 64,
            receipt_hash="f" * 64,
            receipt_version=1,
        )
        payload = {
            "receipt_id": receipt.pk,
            "reservation_id": receipt.reservation_id,
            "trade_id": receipt.trade_id,
            "fill_sequence": receipt.fill_sequence,
            "source_namespace": receipt.source_namespace,
            "source_version": receipt.source_version,
            "source_event_id": receipt.source_event_id,
            "event_kind": receipt.event_kind,
            "source_event_payload_hash": receipt.source_event_payload_hash,
            "source_event_snapshot_hash": receipt.source_event_snapshot_hash,
            "economic_request_hash": receipt.economic_request_hash,
            "economics_snapshot_hash": receipt.economics_snapshot_hash,
            "plan_snapshot_hash": receipt.plan_snapshot_hash,
            "receipt_hash": receipt.receipt_hash,
            "receipt_version": receipt.receipt_version,
        }
        expected = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(receipt_snapshot_sha256(receipt), expected)
        self.assertNotEqual(receipt_snapshot_sha256(receipt), receipt.receipt_hash)
        with self.assertRaises(ValueError):
            receipt_snapshot_sha256(replace(receipt, receipt_hash="Z" * 64))

    def test_valid_explicit_operator_attestation_produces_labeled_local_proof(self) -> None:
        """A fully evidenced row returns only the explicitly operator-attested class."""

        snapshot, request = _snapshot()
        evidence = verify_fee_correction_evidence_snapshot(snapshot, request, verified_at=_NOW)
        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence.source_namespace, ASSURANCE_OPERATOR_ATTESTED_UPLOAD)
        self.assertEqual(evidence.source_record_id, _LOCATOR)
        self.assertEqual(evidence.previous_fee_components.commission, Decimal("3.00"))
        self.assertEqual(evidence.revised_fee_components.commission, Decimal("2.00"))
        self.assertEqual(evidence.source_observed_at, snapshot.parsed_upload.source_observed_at)
        self.assertEqual(
            evidence.evidence_sha256, hashlib.sha256(snapshot.artifact_bytes).hexdigest()
        )

    def test_revision_two_proof_uses_the_bound_predecessor_fees(self) -> None:
        """A later revision compares its CSV only with its exact persisted predecessor."""

        snapshot, request = _snapshot()
        predecessor = FeeCorrectionEvidencePredecessorSnapshot(
            account_id=10,
            trade_id=42,
            revision=1,
            event_id=81,
            revised_fee_components=CorrectableFeeComponents(
                commission=Decimal("9.00"),
                transfer_fee=Decimal("0.00"),
                stamp_duty=Decimal("0.00"),
            ),
        )
        snapshot = replace(
            snapshot,
            binding_expected_revision=1,
            binding_expected_predecessor_id=81,
            predecessor=predecessor,
        )
        request = replace(request, expected_revision=1)

        evidence = verify_fee_correction_evidence_snapshot(snapshot, request, verified_at=_NOW)

        self.assertIsNotNone(evidence)
        assert evidence is not None
        self.assertEqual(evidence.previous_fee_components.commission, Decimal("9.00"))
        self.assertEqual(evidence.previous_fee_components.transfer_fee, Decimal("0.00"))
        self.assertEqual(evidence.expected_predecessor_id, 81)

    def test_evidence_key_and_predecessor_identity_must_match_the_binding(self) -> None:
        """A locator cannot be replayed under another key or predecessor identity."""

        snapshot, request = _snapshot()
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, binding_idempotency_key="other-key"),
                request,
                verified_at=_NOW,
            )
        )
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                snapshot,
                replace(request, idempotency_key="other-key"),
                verified_at=_NOW,
            )
        )
        predecessor = FeeCorrectionEvidencePredecessorSnapshot(
            account_id=10,
            trade_id=42,
            revision=1,
            event_id=82,
            revised_fee_components=CorrectableFeeComponents(
                commission=Decimal("9.00"),
                transfer_fee=Decimal("0.00"),
                stamp_duty=Decimal("0.00"),
            ),
        )
        revision_two = replace(
            snapshot,
            binding_expected_revision=1,
            binding_expected_predecessor_id=81,
            predecessor=predecessor,
        )
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                revision_two,
                replace(request, expected_revision=1),
                verified_at=_NOW,
            )
        )

    def test_tampered_upload_bytes_do_not_verify(self) -> None:
        """A changed local byte stream cannot reuse the stored content digest."""

        snapshot, request = _snapshot()
        tampered = replace(snapshot, artifact_bytes=snapshot.artifact_bytes + b" ")
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(tampered, request, verified_at=_NOW)
        )

    def test_cross_account_owner_and_target_fingerprint_mismatches_fail_closed(self) -> None:
        """The binding is exact to one current owner/account/Trade fingerprint."""

        snapshot, request = _snapshot()
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, binding_account_id=11), request, verified_at=_NOW
            )
        )
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, binding_attested_by_id=8), request, verified_at=_NOW
            )
        )
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, binding_trade_snapshot_sha256="0" * 64),
                request,
                verified_at=_NOW,
            )
        )

    def test_denied_or_changed_policy_does_not_verify(self) -> None:
        """Default-deny and policy-version changes cannot qualify an upload."""

        snapshot, request = _snapshot()
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, policy_allows_operator_attested_upload=False),
                request,
                verified_at=_NOW,
            )
        )
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                replace(snapshot, policy_version=3), request, verified_at=_NOW
            )
        )
        mismatched_currency, currency_request = _snapshot(_upload(currency="USD"))
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(
                mismatched_currency, currency_request, verified_at=_NOW
            )
        )
        with self.assertRaises(ValueError):
            fee_correction_policy_snapshot_json(
                account_id=10,
                version=2,
                enabled=True,
                allows_operator_attested_upload=True,
                ledger_currency="",
                valid_from=_NOW - timedelta(days=1),
                valid_until=_NOW + timedelta(days=1),
                updated_by_id=5,
            )

    def test_fee_amount_cannot_exceed_event_storage_contract(self) -> None:
        """Fee evidence cannot qualify values the financial event cannot store."""

        at_limit, at_limit_request = _snapshot(_upload(commission="99999999.99"))
        self.assertIsNotNone(
            verify_fee_correction_evidence_snapshot(at_limit, at_limit_request, verified_at=_NOW)
        )
        snapshot, request = _snapshot(_upload(commission="100000000.00"))
        self.assertIsNone(
            verify_fee_correction_evidence_snapshot(snapshot, request, verified_at=_NOW)
        )

    def test_unauthenticated_principal_cannot_capture(self) -> None:
        """The use case obtains actor identity only from an authenticated principal."""

        repository = _CaptureRepository()
        use_case = FeeCorrectionEvidenceUploadUseCase(repository)
        command = FeeCorrectionEvidenceUploadCommand(
            account_id=10,
            trade_id=42,
            expected_revision=0,
            expected_predecessor_id=None,
            idempotency_key="synthetic-upload-key",
            original_filename="synthetic.csv",
            content=_upload(),
            attestation_acknowledged=True,
        )
        with self.assertRaises(FeeCorrectionBlockedError):
            use_case.execute(command, principal=_Principal(is_authenticated=False, pk=5))
        self.assertEqual(repository.calls, 0)

    def test_persisted_event_rechecks_immutable_source_and_policy_snapshot(self) -> None:
        """Historical proof binds event IDs, bytes, row, policy, Trade, and fees."""

        live, _ = _snapshot()
        verified_at = _NOW
        posted_at = _NOW + timedelta(minutes=1)
        historical = FeeCorrectionEvidencePersistedEventSnapshot(
            binding_locator=live.binding_locator,
            binding_account_id=live.binding_account_id,
            binding_trade_id=live.binding_trade_id,
            binding_attested_by_id=live.binding_attested_by_id,
            binding_attestation_version=live.binding_attestation_version,
            binding_attestation_acknowledged=live.binding_attestation_acknowledged,
            binding_assurance_class=live.binding_assurance_class,
            binding_expected_revision=live.binding_expected_revision,
            binding_expected_predecessor_id=live.binding_expected_predecessor_id,
            binding_content_sha256=live.binding_content_sha256,
            binding_payload_sha256=live.binding_payload_sha256,
            binding_created_at=live.binding_created_at,
            binding_trade_snapshot_sha256=live.binding_trade_snapshot_sha256,
            binding_policy_version=live.binding_policy_version,
            binding_policy_sha256=live.binding_policy_sha256,
            binding_policy_snapshot=live.binding_policy_snapshot,
            artifact_account_id=live.artifact_account_id,
            artifact_uploaded_by_id=live.artifact_uploaded_by_id,
            artifact_bytes=live.artifact_bytes,
            artifact_sha256=live.artifact_sha256,
            artifact_payload_sha256=live.artifact_payload_sha256,
            artifact_raw_row=live.artifact_raw_row,
            artifact_parsed_metadata=live.artifact_parsed_metadata,
            artifact_uploaded_at=live.artifact_uploaded_at,
            artifact_schema_version=live.artifact_schema_version,
            artifact_assurance_class=live.artifact_assurance_class,
            trade=live.trade,
            receipt_snapshot_hash="2" * 64,
            parsed_upload=live.parsed_upload,
        )
        previous_fees = {
            "commission": "3.00",
            "transfer_fee": "0.10",
            "stamp_duty": "0.00",
        }
        revised_fees = {
            "commission": "2.00",
            "transfer_fee": "0.10",
            "stamp_duty": "0.00",
        }
        authority_snapshot = {
            "schema": "simulated-fee-correction-authority-event.v1",
            "account_id": 10,
            "account_owner_user_id": 5,
            "account_type": "simulated",
            "account_active": True,
            "actor_user_id": 5,
            "actor_authenticated": True,
            "principal_enabled": True,
            "authority_identity": "local.owner_policy.v1",
            "authority_record_id": "fee-correction-policy:1:v2",
            "authority_sha256": live.binding_policy_sha256,
            "authorization_scope": "simulated_fee_correction:operator_attested_upload",
            "policy_version": 2,
            "policy_sha256": live.binding_policy_sha256,
            "policy_ledger_currency": "CNY",
            "policy_enabled": True,
            "policy_allows_operator_attested_upload": True,
            "policy_valid_from": live.binding_policy_snapshot["valid_from"],
            "policy_valid_until": live.binding_policy_snapshot["valid_until"],
            "policy_updated_by_id": 5,
            "trade_id": 42,
            "trade_snapshot_hash": live.binding_trade_snapshot_sha256,
            "original_v4_receipt_hash": live.trade.original_v4_receipt_hash,
            "receipt_snapshot_hash": "2" * 64,
            "source_namespace": ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
            "source_record_id": _LOCATOR,
            "verifier_identity": "local.operator_attested_csv.v1",
            "source_evidence_hash": live.artifact_sha256,
            "source_payload_hash": live.artifact_payload_sha256,
            "source_observed_at": "2026-10-25T02:00:00.000000Z",
            "evidence_verified_at": "2026-10-25T05:00:00.000000Z",
            "request_payload_hash": "9" * 64,
            "idempotency_key": "synthetic-correction-key",
            "revision": 1,
            "previous_event_id": None,
            "account_revision": 7,
            "account_predecessor_hash": "6" * 64,
            "previous_fees": previous_fees,
            "revised_fees": revised_fees,
            "original_slippage": "1.00",
            "posting_time": "2026-10-25T05:01:00.000000Z",
            "posting_date": "2026-10-25",
        }
        authority_snapshot_sha256 = hashlib.sha256(
            json.dumps(
                authority_snapshot,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        proof = PersistedFeeCorrectionEventProof(
            account_id=10,
            trade_id=42,
            actor_user_id=5,
            revision=1,
            previous_event_id=None,
            account_revision=7,
            account_predecessor_hash="6" * 64,
            idempotency_key="synthetic-correction-key",
            request_payload_hash="9" * 64,
            trade_snapshot_hash=live.binding_trade_snapshot_sha256,
            original_v4_receipt_hash=live.trade.original_v4_receipt_hash,
            receipt_snapshot_hash="2" * 64,
            source_namespace=ASSURANCE_OPERATOR_ATTESTED_UPLOAD,
            source_record_id=_LOCATOR,
            verifier_identity="local.operator_attested_csv.v1",
            source_evidence_hash=live.artifact_sha256,
            source_payload_hash=live.artifact_payload_sha256,
            source_observed_at=live.parsed_upload.source_observed_at,
            evidence_verified_at=verified_at,
            authority_identity="local.owner_policy.v1",
            authority_record_id="fee-correction-policy:1:v2",
            authority_hash=live.binding_policy_sha256,
            authority_snapshot_sha256=authority_snapshot_sha256,
            authority_snapshot_json=authority_snapshot,
            previous_fee_components=CorrectableFeeComponents(
                commission=Decimal("3.00"),
                transfer_fee=Decimal("0.10"),
                stamp_duty=Decimal("0.00"),
            ),
            revised_fee_components=CorrectableFeeComponents(
                commission=Decimal("2.00"),
                transfer_fee=Decimal("0.10"),
                stamp_duty=Decimal("0.00"),
            ),
            original_slippage=Decimal("1.00"),
            posted_at=posted_at,
            posting_date=posted_at.date(),
        )
        self.assertTrue(verify_persisted_fee_correction_authority_snapshot(proof))
        self.assertTrue(verify_persisted_fee_correction_event_snapshot(historical, proof))
        tampered_authority = dict(authority_snapshot)
        tampered_authority["authorization_scope"] = "simulated_fee_correction:other"
        self.assertFalse(
            verify_persisted_fee_correction_authority_snapshot(
                replace(proof, authority_snapshot_json=tampered_authority)
            )
        )
        self.assertFalse(
            verify_persisted_fee_correction_authority_snapshot(
                replace(proof, authority_snapshot_sha256="0" * 64)
            )
        )
        self.assertFalse(
            verify_persisted_fee_correction_authority_snapshot(replace(proof, account_revision=8))
        )
        changed_currency = dict(authority_snapshot)
        changed_currency["policy_ledger_currency"] = "USD"
        changed_currency_digest = hashlib.sha256(
            json.dumps(
                changed_currency,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertFalse(
            verify_persisted_fee_correction_authority_snapshot(
                replace(
                    proof,
                    authority_snapshot_json=changed_currency,
                    authority_snapshot_sha256=changed_currency_digest,
                )
            )
        )
        self.assertFalse(
            verify_persisted_fee_correction_event_snapshot(
                historical,
                replace(proof, source_evidence_hash="0" * 64),
            )
        )
        self.assertFalse(
            verify_persisted_fee_correction_event_snapshot(
                replace(historical, binding_attested_by_id=8),
                proof,
            )
        )

        def self_consistent_authority_variant(
            *, actor_user_id: int, policy_version: int
        ) -> PersistedFeeCorrectionEventProof:
            """Build a self-consistent local authority record for mismatch tests."""

            policy_digest = fee_correction_policy_sha256(
                account_id=10,
                version=policy_version,
                enabled=True,
                allows_operator_attested_upload=True,
                ledger_currency="CNY",
                valid_from=_NOW - timedelta(days=1),
                valid_until=_NOW + timedelta(days=1),
                updated_by_id=actor_user_id,
            )
            authority_record_id = f"fee-correction-policy:1:v{policy_version}:actor-{actor_user_id}"
            authority_variant: dict[str, object] = dict(authority_snapshot)
            authority_variant.update(
                {
                    "account_owner_user_id": actor_user_id,
                    "actor_user_id": actor_user_id,
                    "policy_updated_by_id": actor_user_id,
                    "authority_record_id": authority_record_id,
                    "authority_sha256": policy_digest,
                    "policy_version": policy_version,
                    "policy_sha256": policy_digest,
                }
            )
            snapshot_digest = hashlib.sha256(
                json.dumps(
                    authority_variant,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            return replace(
                proof,
                actor_user_id=actor_user_id,
                authority_record_id=authority_record_id,
                authority_hash=policy_digest,
                authority_snapshot_sha256=snapshot_digest,
                authority_snapshot_json=authority_variant,
            )

        actor_mismatch = self_consistent_authority_variant(actor_user_id=8, policy_version=2)
        self.assertTrue(verify_persisted_fee_correction_authority_snapshot(actor_mismatch))
        policy_version_mismatch = self_consistent_authority_variant(
            actor_user_id=5, policy_version=99
        )
        self.assertTrue(verify_persisted_fee_correction_authority_snapshot(policy_version_mismatch))
        with self.subTest(mismatch="actor"):
            self.assertFalse(
                verify_persisted_fee_correction_event_snapshot(historical, actor_mismatch)
            )
        with self.subTest(mismatch="policy_version"):
            self.assertFalse(
                verify_persisted_fee_correction_event_snapshot(historical, policy_version_mismatch)
            )

        oversized_authority = dict(authority_snapshot)
        oversized_authority["revised_fees"] = {
            "commission": "100000000.00",
            "transfer_fee": "0.10",
            "stamp_duty": "0.00",
        }
        oversized_digest = hashlib.sha256(
            json.dumps(
                oversized_authority,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        oversized_event = replace(
            proof,
            authority_snapshot_sha256=oversized_digest,
            authority_snapshot_json=oversized_authority,
            revised_fee_components=CorrectableFeeComponents(
                commission=Decimal("100000000.00"),
                transfer_fee=Decimal("0.10"),
                stamp_duty=Decimal("0.00"),
            ),
        )
        self.assertTrue(verify_persisted_fee_correction_authority_snapshot(oversized_event))
        self.assertFalse(
            verify_persisted_fee_correction_event_snapshot(historical, oversized_event)
        )


if __name__ == "__main__":
    unittest.main()
