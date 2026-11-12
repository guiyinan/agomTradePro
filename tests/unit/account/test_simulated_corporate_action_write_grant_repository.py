"""Strict grant row codecs and version-specific Account model declarations."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
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
    SimulatedCorporateActionWriteGrant,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_models import (
    SimulatedCorporateActionWriteGrantModel,
    SimulatedCorporateActionWriteGrantRevocationModel,
)
from apps.account.infrastructure.simulated_corporate_action_write_grant_repository import (
    _grant_values,
    _restore_grant,
    _restore_revocation,
    _revocation_values,
)
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _grant,
    _grant_v2,
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
) -> SimulatedCorporateActionWriteGrantModel:
    """Build an unsaved model from the repository's production append codec."""

    return SimulatedCorporateActionWriteGrantModel(**_grant_values(grant, None))


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
