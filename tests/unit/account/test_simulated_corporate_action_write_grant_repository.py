"""Strict grant row codecs and version-specific Account model declarations."""

from __future__ import annotations

import importlib

import pytest
from django.core.exceptions import ValidationError
from django.db.migrations.operations.models import AddConstraint, RemoveConstraint
from django.db.models import Q

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantCorruption,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA,
    SimulatedCorporateActionWriteGrant,
    SimulatedCorporateActionWriteGrantRecord,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    DjangoSimulatedCorporateActionWriteGrantRepository,
    _grant_values,
    _restore_grant,
    _restore_revocation,
    _revocation_values,
)
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _grant,
    _grant_v2,
    _grant_v3,
    _revocation,
)


def _v2_grant() -> SimulatedCorporateActionWriteGrant:
    """Build one explicit V2 root with independent tax capabilities."""

    return _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        ),
        supersedes_content_hash=None,
    )


def _grant_row(
    grant: SimulatedCorporateActionWriteGrant,
    *,
    predecessor_id: int | None = None,
) -> SimulatedCorporateActionWriteGrantModel:
    """Build an unsaved model from the repository's production append codec."""

    return SimulatedCorporateActionWriteGrantModel(**_grant_values(grant, predecessor_id))


def test_grant_model_declares_nullable_v2_fields_and_keeps_v1_columns_empty() -> None:
    capabilities = SimulatedCorporateActionWriteGrantModel._meta.get_field("capabilities")
    terms_version = SimulatedCorporateActionWriteGrantModel._meta.get_field("terms_version")
    terms_sha256 = SimulatedCorporateActionWriteGrantModel._meta.get_field("terms_sha256")
    assert capabilities.null and capabilities.blank
    assert terms_version.null and terms_sha256.null

    row = _grant_row(_grant())
    assert row.schema.endswith(".v1")
    assert row.permission == SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    assert row.capabilities is None
    assert row.terms_version is None
    assert row.terms_sha256 is None
    row.clean()


def test_v2_model_requires_a_nonempty_canonical_capability_array_and_terms() -> None:
    grant = _v2_grant()
    values = _grant_values(grant, None)
    assert values["schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA
    assert values["permission"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION
    assert values["capabilities"] == [
        SimulatedCorporateActionWriteCapability.TAX_ASSESS.value,
        SimulatedCorporateActionWriteCapability.TAX_WITHHOLD.value,
    ]
    assert values["terms_version"] == grant.terms_version
    assert values["terms_sha256"] == grant.terms_sha256

    row = _grant_row(grant)
    row.clean()
    assert _restore_grant(row) == grant

    for invalid in ([], ["unknown.permission"], list(reversed(values["capabilities"]))):
        changed = _grant_row(grant)
        changed.capabilities = invalid
        with pytest.raises(ValidationError):
            changed.clean()

    missing_terms = _grant_row(grant)
    missing_terms.terms_version = None
    with pytest.raises(ValidationError):
        missing_terms.clean()

    v1_with_capability_data = _grant_row(_grant())
    v1_with_capability_data.capabilities = [
        SimulatedCorporateActionWriteCapability.TAX_ASSESS.value
    ]
    with pytest.raises(ValidationError):
        v1_with_capability_data.clean()


def test_v3_storage_round_trips_explicit_share_capabilities_and_terms() -> None:
    grant = _grant_v3(
        capabilities=(
            SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        ),
        supersedes_content_hash="e" * 64,
    )
    values = _grant_values(grant, 41)

    assert values["schema"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA
    assert values["permission"] == SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION
    assert values["capabilities"] == [
        SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED.value,
        SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE.value,
    ]
    assert values["terms_version"] == grant.terms_version
    assert values["terms_sha256"] == grant.terms_sha256

    row = _grant_row(grant, predecessor_id=41)
    row.clean()
    assert _restore_grant(row) == grant


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("capabilities", []),
        (
            "capabilities",
            [
                SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE.value,
                SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED.value,
            ],
        ),
        ("terms_version", None),
        ("terms_sha256", "g" * 64),
        ("permission", SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_PERMISSION),
    ),
)
def test_v3_model_requires_exact_capabilities_and_terms(field: str, value: object) -> None:
    grant = _grant_v3(
        capabilities=(
            SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        ),
        supersedes_content_hash="e" * 64,
    )
    row = _grant_row(grant, predecessor_id=41)
    setattr(row, field, value)

    with pytest.raises(ValidationError):
        row.clean()


def test_v3_restore_rejects_payload_that_differs_from_typed_columns() -> None:
    grant = _grant_v3(
        capabilities=(
            SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        ),
        supersedes_content_hash="e" * 64,
    )
    row = _grant_row(grant, predecessor_id=41)
    row.canonical_payload = dict(row.canonical_payload, terms_sha256="f" * 64)

    with pytest.raises(SimulatedCorporateActionWriteGrantCorruption):
        _restore_grant(row)


def test_v3_migration_only_replaces_the_fixed_grant_constraint() -> None:
    migration_module = importlib.import_module(
        "apps.account.migrations.0072_simulated_corporate_action_write_grant_v3"
    )
    migration = migration_module.Migration

    assert migration.dependencies == [
        ("account", "0071_simulated_corporate_action_grant_capabilities")
    ]
    assert len(migration.operations) == 2
    assert isinstance(migration.operations[0], RemoveConstraint)
    assert isinstance(migration.operations[1], AddConstraint)
    assert migration.operations[0].name == "acct_scawg_fixed_ck"
    assert migration.operations[1].constraint.name == "acct_scawg_fixed_ck"
    model_constraint = next(
        item
        for item in SimulatedCorporateActionWriteGrantModel._meta.constraints
        if item.name == "acct_scawg_fixed_ck"
    )
    assert migration.operations[1].constraint.condition == model_constraint.condition


def test_repository_history_restores_a_v1_v2_v3_account_chain_without_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    v1 = _grant()
    v2 = _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        ),
        supersedes_content_hash=v1.content_hash,
    )
    v3 = _grant_v3(
        capabilities=(
            SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        ),
        supersedes_content_hash=v2.content_hash,
    )
    rows = [
        _grant_row(v1),
        _grant_row(v2, predecessor_id=41),
        _grant_row(v3, predecessor_id=42),
    ]
    for row, primary_key in zip(rows, (41, 42, 43), strict=True):
        row.pk = primary_key

    class _Query:
        def using(self, alias: str) -> _Query:
            del alias
            return self

        def filter(self, **kwargs: object) -> _Query:
            del kwargs
            return self

        def order_by(self, *fields: str) -> _Query:
            del fields
            return self

        def __iter__(self) -> object:
            return iter(rows)

    records = {
        grant.content_hash: SimulatedCorporateActionWriteGrantRecord(grant=grant)
        for grant in (v1, v2, v3)
    }
    manager = SimulatedCorporateActionWriteGrantModel._default_manager
    monkeypatch.setattr(manager, "using", lambda alias: _Query())
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteGrantRepository,
        "get_current_for_scope",
        lambda self, account_namespace, account_id, *, as_of: (v3,),
    )
    monkeypatch.setattr(
        DjangoSimulatedCorporateActionWriteGrantRepository,
        "get_exact_record",
        lambda self, *, selector, as_of: records[selector.content_hash],
    )

    history = DjangoSimulatedCorporateActionWriteGrantRepository().get_scope_records(
        "simulated",
        v1.binding.account_id,
        as_of=v3.recorded_at,
    )

    assert tuple(record.grant for record in history) == (v1, v2, v3)


def test_v2_model_and_restore_reject_new_v3_capabilities() -> None:
    grant = _v2_grant()
    row = _grant_row(grant)
    row.capabilities = [SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE.value]

    with pytest.raises(ValidationError, match="V2 grant cannot include V3 capabilities"):
        row.clean()
    with pytest.raises(SimulatedCorporateActionWriteGrantCorruption):
        _restore_grant(row)


def test_fixed_constraint_requires_nonnull_v2_terms() -> None:
    constraint = next(
        item
        for item in SimulatedCorporateActionWriteGrantModel._meta.constraints
        if item.name == "acct_scawg_fixed_ck"
    )

    def leaves(condition: Q) -> list[object]:
        result: list[object] = []
        for child in condition.children:
            if isinstance(child, Q):
                result.extend(leaves(child))
            else:
                result.append(child)
        return result

    predicates = leaves(constraint.condition)
    assert ("terms_version__isnull", False) in predicates
    assert ("terms_sha256__isnull", False) in predicates
    assert ("schema", SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_SCHEMA) in predicates
    assert ("permission", SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V3_PERMISSION) in predicates


def test_grant_restore_rejects_column_payload_and_v2_schema_disagreement() -> None:
    grant = _v2_grant()
    row = _grant_row(grant)

    row.capabilities = [SimulatedCorporateActionWriteCapability.TAX_ASSESS.value]
    with pytest.raises(SimulatedCorporateActionWriteGrantCorruption):
        _restore_grant(row)

    row = _grant_row(grant)
    row.canonical_payload = dict(row.canonical_payload, unexpected="field")
    with pytest.raises(SimulatedCorporateActionWriteGrantCorruption):
        _restore_grant(row)

    row = _grant_row(grant)
    row.permission = SIMULATED_CORPORATE_ACTION_STAGE_WRITE_PERMISSION
    with pytest.raises(SimulatedCorporateActionWriteGrantCorruption):
        _restore_grant(row)


def test_v2_revocation_codec_retains_the_exact_whole_grant_target() -> None:
    grant = _v2_grant()
    grant_row = _grant_row(grant)
    grant_row.pk = 41
    revocation = _revocation(grant, recorded_at=grant.recorded_at.replace(minute=5))
    values = _revocation_values(revocation, 41)
    row = SimulatedCorporateActionWriteGrantRevocationModel(**values)

    assert values["grant_content_hash"] == grant.content_hash
    assert row.canonical_payload == revocation.to_payload()
    assert _restore_revocation(row, grant, 41) == revocation
