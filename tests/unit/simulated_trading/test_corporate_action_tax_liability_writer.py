"""Financial writer refuses rounding, retained instances and unproven snapshots."""

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from apps.simulated_trading.infrastructure import corporate_action_tax_liability_writer as writer
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_liability_evidence import _material


@pytest.mark.parametrize("amount", ["0", "0.01", "1234567890123.45", "9999999999999.99"])
def test_cash_ledger_supported_values_remain_exact(amount):
    writer.require_ledger_cash_capacity(Decimal(amount), currency_quantum=Decimal("0.01"))


@pytest.mark.parametrize(
    "amount,quantum",
    [
        ("0.001", "0.01"),
        ("10000000000000", "0.01"),
        ("-0.01", "0.01"),
        ("NaN", "0.01"),
        ("Infinity", "0.01"),
        ("0.01", "0.001"),
        ("0.01", "1"),
    ],
)
def test_cash_ledger_never_implicitly_rounds_or_accepts_unsupported_quantum(amount, quantum):
    with pytest.raises(BusinessLogicError):
        writer.require_ledger_cash_capacity(Decimal(amount), currency_quantum=Decimal(quantum))


def _writer(monkeypatch):
    origin = _material().origin
    verifier = Mock(database_alias="default")
    verifier.get_locked_audit_origin.return_value = origin
    audit = Mock(database_alias="default")
    clock = Mock()
    clock.now.return_value = _material().recorded_at
    monkeypatch.setattr(writer, "connections", {"default": SimpleNamespace(in_atomic_block=True)})
    instance = writer.DjangoTaxLiabilityAtomicWriter(
        using="default",
        token=object(),
        verifier=verifier,
        audit=audit,
        clock=clock,
        assessment_audit=Mock(),
    )
    return instance, verifier, audit


def test_retained_writer_is_revoked_after_uow_exit(monkeypatch):
    instance, verifier, _ = _writer(monkeypatch)
    instance._require_active()
    verifier.get_locked_audit_origin.reset_mock()
    instance.close()
    with pytest.raises(BusinessLogicError, match="outside"):
        instance._require_active()
    verifier.get_locked_audit_origin.assert_not_called()


def test_hashes_and_typed_origins_cannot_substitute_an_active_owner_context(monkeypatch):
    instance, verifier, _ = _writer(monkeypatch)
    verifier.get_locked_audit_origin.side_effect = BusinessLogicError("no active owner scope")
    with pytest.raises(BusinessLogicError, match="no active owner scope"):
        instance._require_active()


def test_snapshot_full_provenance_must_match_its_original_reference():
    material = _material()
    with pytest.raises(BusinessLogicError, match="provenance"):
        replace(material, cash_snapshot_provenance_json=None)
    with pytest.raises(BusinessLogicError):
        replace(
            material,
            cash_snapshot_provenance_json=material.cash_snapshot_provenance_json.replace(
                '"reserved_cash":"0"', '"reserved_cash":"0.01"'
            ),
        )


def test_stored_assessment_lookup_is_exact_when_revision_labels_repeat(monkeypatch):
    """A label reused by another partial disposition cannot select its header."""
    instance, verifier, _ = _writer(monkeypatch)
    from tests.unit.simulated_trading.test_corporate_action_tax_liability import _taxable_assessment

    assessment = _taxable_assessment()
    wrong = SimpleNamespace(
        pk=1,
        account_id=assessment.account_id,
        assessment_revision_id=assessment.assessment_revision_id,
        idempotency_key="other-disposition",
        semantic_sha256="0" * 64,
    )
    exact = SimpleNamespace(
        pk=2,
        account_id=assessment.account_id,
        assessment_revision_id=assessment.assessment_revision_id,
        idempotency_key=assessment.calculation.idempotency_key,
        semantic_sha256=assessment.semantic_sha256,
        observation_manifest_sha256=assessment.observation_manifest_sha256,
    )

    class Query:
        def __init__(self, rows):
            self.rows = rows

        def using(self, _alias):
            return self

        def select_for_update(self):
            return self

        def filter(self, **fields):
            return Query(
                [
                    row
                    for row in self.rows
                    if all(getattr(row, key) == value for key, value in fields.items())
                ]
            )

        def first(self):
            return self.rows[0] if self.rows else None

        def get(self, **fields):
            rows = self.filter(**fields).rows
            assert len(rows) == 1, "header selector must identify exactly one partial disposition"
            return rows[0]

    monkeypatch.setattr(writer, "Header", SimpleNamespace(_default_manager=Query([wrong, exact])))

    def verify(header, candidate):
        assert (
            candidate is assessment and header.pk == 2
        ), "another disposition header must never be selected"

    instance._assessments.verify_stored = verify
    instance._readback.verify_assessment = Mock()
    receipt = instance.require_stored_assessment(assessment, actor_user_id=assessment.owner_user_id)
    assert receipt.semantic_sha256 == assessment.semantic_sha256
    assert instance._assessment_id(assessment) == 2
