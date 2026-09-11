"""Structure and append-only guards for ownership Receipt and Subject V5 ledgers."""

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from apps.account.infrastructure.account_owner_assignment_v5_models import (
    AccountOwnerAssignmentProvenanceReceiptV5Model,
    AccountOwnerAssignmentSubjectV5Model,
)


def test_receipt_v5_has_exact_protected_parent_cardinalities() -> None:
    """Keep durable policy/Binding/re-observation parents separate from its chain link."""

    for name in ("policy", "binding", "reobservation"):
        field = AccountOwnerAssignmentProvenanceReceiptV5Model._meta.get_field(name)
        assert field.many_to_one is True
        assert field.one_to_one is False
        assert field.remote_field.on_delete is models.PROTECT
    predecessor = AccountOwnerAssignmentProvenanceReceiptV5Model._meta.get_field("predecessor")
    assert predecessor.one_to_one is True
    assert predecessor.remote_field.on_delete is models.PROTECT


def test_subject_v5_binds_one_receipt_and_repeatable_canonical_parents() -> None:
    """One receipt registers at most one subject while canonical roots may be reused."""

    receipt = AccountOwnerAssignmentSubjectV5Model._meta.get_field("receipt")
    assert receipt.one_to_one is True
    assert receipt.remote_field.on_delete is models.PROTECT
    for name in ("binding", "reobservation"):
        field = AccountOwnerAssignmentSubjectV5Model._meta.get_field(name)
        assert field.many_to_one is True
        assert field.one_to_one is False
        assert field.remote_field.on_delete is models.PROTECT


@pytest.mark.parametrize(
    "model_type",
    [AccountOwnerAssignmentProvenanceReceiptV5Model, AccountOwnerAssignmentSubjectV5Model],
)
def test_v5_models_reject_direct_and_bulk_inserts(
    model_type: type[models.Model],
) -> None:
    """Every durable V5 row must pass the repository's exact insertion claim."""

    with pytest.raises(ValidationError, match="exact insert claim"):
        model_type().save(using="default")
    with pytest.raises(ValidationError, match="exact appends"):
        model_type._default_manager.bulk_create([model_type()])


@pytest.mark.parametrize(
    "model_type",
    [AccountOwnerAssignmentProvenanceReceiptV5Model, AccountOwnerAssignmentSubjectV5Model],
)
def test_v5_models_expose_hash_and_clock_constraints(
    model_type: type[models.Model],
) -> None:
    """Require unique envelope seals and database clock/fixed-state checks."""

    unique = {field.name for field in model_type._meta.fields if getattr(field, "unique", False)}
    assert {"identity_hash", "content_hash", "record_seal", "ledger_seal"} <= unique
    constraint_names = {constraint.name for constraint in model_type._meta.constraints}
    assert any(name.endswith("fixed_ck") for name in constraint_names)
    assert any(name.endswith("clock_ck") for name in constraint_names)
