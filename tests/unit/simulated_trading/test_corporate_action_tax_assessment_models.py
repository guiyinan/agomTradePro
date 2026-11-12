from __future__ import annotations

import hashlib
from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.simulated_trading.infrastructure import corporate_action_tax_assessment_models as module
from apps.simulated_trading.infrastructure.corporate_action_tax_assessment_models import (
    CorporateActionTaxAssessmentAllocationModel,
    CorporateActionTaxAssessmentHeaderModel,
)


def _payload_digest(payload: str = "{}") -> tuple[str, str]:
    """Return one exact canonical JSON text and digest for no-DB model tests."""

    return payload, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _header() -> CorporateActionTaxAssessmentHeaderModel:
    """Build an unsaved model with canonical payloads for guard tests."""

    payload, digest = _payload_digest()
    return CorporateActionTaxAssessmentHeaderModel(
        account_id=1,
        owner_user_id=2,
        assessment_revision_id="synthetic-assessment-revision",
        supersedes_id=None,
        supersedes_assessment_revision_id=None,
        semantic_payload_json=payload,
        semantic_sha256=digest,
        observation_manifest_json=payload,
        observation_manifest_sha256=digest,
        calculation_payload_json=payload,
        calculation_sha256=digest,
        gross_dividend_amount_text="0.00",
        taxable_dividend_amount_text="0.00",
        withholding_amount_text="0.00",
    )


def _allocation() -> CorporateActionTaxAssessmentAllocationModel:
    """Build an unsaved allocation with a valid canonical payload and digest."""

    payload, digest = _payload_digest()
    return CorporateActionTaxAssessmentAllocationModel(
        assessment_id=1,
        ordinal=1,
        lot_id="synthetic-lot",
        allocation_payload_json=payload,
        allocation_sha256=digest,
    )


def test_header_protects_physical_account_and_owner_foreign_keys() -> None:
    account = CorporateActionTaxAssessmentHeaderModel._meta.get_field("account")
    owner = CorporateActionTaxAssessmentHeaderModel._meta.get_field("owner_user")

    assert isinstance(account, models.ForeignKey)
    assert account.remote_field.model is not None
    assert account.remote_field.model.__name__ == "SimulatedAccountModel"
    assert account.remote_field.on_delete is models.PROTECT
    assert isinstance(owner, models.ForeignKey)
    assert owner.remote_field.model._meta.label == settings.AUTH_USER_MODEL
    assert owner.remote_field.on_delete is models.PROTECT


def test_two_table_identity_and_lossless_decimal_text_contract() -> None:
    header_fields = {
        field.name: field for field in CorporateActionTaxAssessmentHeaderModel._meta.fields
    }
    allocation_fields = {
        field.name: field for field in CorporateActionTaxAssessmentAllocationModel._meta.fields
    }
    assert "assessment_revision_id" in header_fields
    assert "supersedes" in header_fields
    assert "semantic_payload_json" in header_fields
    assert "observation_manifest_json" in header_fields
    assert "calculation_payload_json" in header_fields
    assert isinstance(header_fields["gross_dividend_amount_text"], models.CharField)
    assert isinstance(header_fields["taxable_dividend_amount_text"], models.CharField)
    assert isinstance(header_fields["withholding_amount_text"], models.CharField)
    assert {"assessment", "ordinal", "allocation_payload_json", "allocation_sha256"}.issubset(
        allocation_fields
    )
    assert not any(isinstance(field, models.DecimalField) for field in header_fields.values())
    assert not any(isinstance(field, models.DecimalField) for field in allocation_fields.values())
    assert CorporateActionTaxAssessmentHeaderModel._meta.db_table == "sim_ca_tax_assessment"
    assert (
        CorporateActionTaxAssessmentAllocationModel._meta.db_table == "sim_ca_tax_assess_allocation"
    )


@pytest.mark.parametrize("row", (_header(), _allocation()))
def test_instance_save_and_delete_cannot_mutate_or_insert_without_private_claim(
    row: CorporateActionTaxAssessmentHeaderModel | CorporateActionTaxAssessmentAllocationModel,
) -> None:
    with pytest.raises(ValidationError, match="append claim"):
        row.save()
    with pytest.raises(ValidationError, match="retained permanently"):
        row.delete()
    with pytest.raises(ValidationError, match="raw save"):
        row.save_base(raw=True)


def test_preassigned_primary_key_insert_is_rejected_without_database_access() -> None:
    row = _header()
    row.pk = 99

    with pytest.raises(ValidationError, match="cannot be replaced"):
        row.save()


def test_save_base_cannot_insert_a_preassigned_primary_key_under_an_exact_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _header()
    row.pk = 99
    monkeypatch.setattr(
        module,
        "connections",
        {"test-alias": SimpleNamespace(in_atomic_block=True)},
    )
    called = False

    def observe_base_save(self: models.Model, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        nonlocal called
        called = True

    monkeypatch.setattr(models.Model, "save_base", observe_base_save)
    expected = {
        field.attname: getattr(row, field.attname)
        for field in row._meta.concrete_fields
        if field is not row._meta.auto_field
    }
    with module._activate_tax_assessment_uow() as token:
        with module._claim_tax_assessment_insert(
            token=token,
            using="test-alias",
            model_type=type(row),
            expected_values=expected,
        ):
            with pytest.raises(ValidationError, match="primary key"):
                row.save_base(force_insert=True)

    assert not called


def test_canonical_payload_rejects_unencodable_json_as_validation_error() -> None:
    row = _header()
    row.semantic_payload_json = '{"value":"\ud800"}'
    row.semantic_sha256 = "0" * 64

    with pytest.raises(ValidationError, match="UTF-8"):
        row.save()


def test_header_rejects_mismatched_revision_link_payload_hash_and_decimal_text() -> None:
    row = _header()
    row.supersedes_assessment_revision_id = "synthetic-prior-revision"
    with pytest.raises(ValidationError, match="must be paired"):
        row.save()

    row = _header()
    row.semantic_sha256 = "0" * 64
    with pytest.raises(ValidationError, match="digest does not match"):
        row.save()

    row = _header()
    row.gross_dividend_amount_text = "1e2"
    with pytest.raises(ValidationError, match="canonical lossless decimal text"):
        row.save()


def test_allocation_rejects_non_object_or_noncanonical_json() -> None:
    row = _allocation()
    row.allocation_payload_json = "[]"
    row.allocation_sha256 = hashlib.sha256(b"[]").hexdigest()
    with pytest.raises(ValidationError, match="not canonical JSON"):
        row.save()

    row = _allocation()
    row.allocation_payload_json = '{ "lot": "synthetic" }'
    row.allocation_sha256 = hashlib.sha256(row.allocation_payload_json.encode("utf-8")).hexdigest()
    with pytest.raises(ValidationError, match="JSON digest does not match"):
        row.save()


@pytest.mark.parametrize(
    "operation",
    (
        lambda: CorporateActionTaxAssessmentHeaderModel.objects.update(semantic_sha256="0" * 64),
        lambda: CorporateActionTaxAssessmentHeaderModel.objects.bulk_create([]),
        lambda: CorporateActionTaxAssessmentHeaderModel.objects.filter(pk=1).delete(),
        lambda: CorporateActionTaxAssessmentAllocationModel.objects.bulk_create([]),
        lambda: CorporateActionTaxAssessmentAllocationModel.objects.filter(pk=1).delete(),
    ),
)
def test_queryset_and_manager_mutation_shortcuts_are_rejected(
    operation: Callable[[], object],
) -> None:
    with pytest.raises(ValidationError):
        cast(Callable[[], object], operation)()


def test_exact_insert_claim_binds_all_fields_without_opening_a_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = _header()
    monkeypatch.setattr(
        module,
        "connections",
        {"test-alias": SimpleNamespace(in_atomic_block=True)},
    )
    expected = {
        field.attname: getattr(row, field.attname)
        for field in row._meta.concrete_fields
        if field is not row._meta.auto_field
    }
    with module._activate_tax_assessment_uow() as token:
        with module._claim_tax_assessment_insert(
            token=token,
            using="test-alias",
            model_type=type(row),
            expected_values=expected,
        ):
            module._require_insert_claim(row, using="test-alias")
            row.semantic_sha256 = "1" * 64
            with pytest.raises(ValidationError, match="exact append claim"):
                module._require_insert_claim(row, using="test-alias")


def test_claim_cannot_be_opened_without_active_uow_or_atomic_database() -> None:
    row = _header()
    with pytest.raises(ValidationError, match="private UOW"):
        with module._claim_tax_assessment_insert(
            token=object(),
            using="default",
            model_type=type(row),
            expected_values={},
        ):
            pytest.fail("claim unexpectedly opened")
