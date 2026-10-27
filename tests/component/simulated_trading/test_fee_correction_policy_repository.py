"""Django policy boundary tests using the existing fee-evidence scenario."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.simulated_trading.application.fee_correction import (
    AuthenticatedFeeCorrectionPrincipalProtocol,
    FeeCorrectionBlockedError,
)
from apps.simulated_trading.application.fee_correction_policy import (
    FeeCorrectionPolicyCommand,
    FeeCorrectionPolicyUseCase,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from apps.simulated_trading.infrastructure.fee_correction_evidence_repository import (
    DjangoFeeCorrectionEvidenceRepository,
)
from apps.simulated_trading.infrastructure.fee_correction_policy_repository import (
    DjangoFeeCorrectionPolicyRepository,
)
from tests.component.simulated_trading.test_fee_correction_evidence_repository import (
    EvidenceScenario,
    evidence_scenario,
)

__all__ = ["evidence_scenario"]


def _command(
    *,
    account_id: int,
    expected_version: int,
    enabled: bool = True,
    allow_operator_attested_upload: bool = True,
    ledger_currency: str = "HKD",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    attestation_acknowledged: bool = True,
) -> FeeCorrectionPolicyCommand:
    """Build one explicit test policy without application-side defaults."""

    now = timezone.now()
    return FeeCorrectionPolicyCommand(
        account_id=account_id,
        expected_version=expected_version,
        enabled=enabled,
        allow_operator_attested_upload=allow_operator_attested_upload,
        ledger_currency=ledger_currency,
        valid_from=valid_from if valid_from is not None else now - timedelta(days=1),
        valid_until=valid_until if valid_until is not None else now + timedelta(days=1),
        attestation_acknowledged=attestation_acknowledged,
    )


@pytest.mark.django_db
def test_missing_policy_read_returns_disabled_version_zero_without_writing(
    evidence_scenario: EvidenceScenario,
) -> None:
    """GET is read-only when an active owner's second simulated account has no policy."""

    scenario = evidence_scenario
    account_id = cast(int, scenario.other_account.pk)
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())

    state = use_case.get(account_id, principal=scenario.owner)

    assert state.account_id == account_id
    assert state.version == 0
    assert state.enabled is False
    assert state.allow_operator_attested_upload is False
    assert state.ledger_currency == ""
    assert state.valid_from is None
    assert state.valid_until is None
    assert state.updated_by_id is None
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(account_id=account_id).exists()


@pytest.mark.django_db
def test_owner_can_create_disable_and_compare_and_swap_policy(
    evidence_scenario: EvidenceScenario,
) -> None:
    """The owner creates at version zero and model save owns subsequent version increments."""

    scenario = evidence_scenario
    account_id = cast(int, scenario.other_account.pk)
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())

    initial_command = _command(account_id=account_id, expected_version=0)
    created = use_case.save(initial_command, principal=scenario.owner)
    assert created.version == 1
    assert created.enabled is True
    assert created.allow_operator_attested_upload is True
    assert created.ledger_currency == "HKD"
    assert created.updated_by_id == scenario.owner_id

    read_back = use_case.get(account_id, principal=scenario.owner)
    assert read_back == created

    repeated = use_case.save(
        replace(initial_command, expected_version=1),
        principal=scenario.owner,
    )
    assert repeated.version == 1

    disabled = use_case.save(
        _command(
            account_id=account_id,
            expected_version=1,
            enabled=False,
            allow_operator_attested_upload=False,
            attestation_acknowledged=False,
        ),
        principal=scenario.owner,
    )
    assert disabled.version == 2
    assert disabled.enabled is False
    assert disabled.allow_operator_attested_upload is False
    assert disabled.updated_by_id == scenario.owner_id

    with pytest.raises(FeeCorrectionBlockedError) as stale:
        use_case.save(
            _command(account_id=account_id, expected_version=1),
            principal=scenario.owner,
        )
    assert stale.value.code == "FEE_CORRECTION_POLICY_CONFLICT"
    assert FeeCorrectionEvidencePolicyModel.objects.get(account_id=account_id).version == 2


@pytest.mark.django_db
def test_superuser_does_not_bypass_simulated_account_owner_scope(
    evidence_scenario: EvidenceScenario,
) -> None:
    """An active superuser who is not the account owner cannot read or alter its policy."""

    scenario = evidence_scenario
    user_model = get_user_model()
    actor = user_model._base_manager.get(pk=scenario.other_user_id)
    actor.is_superuser = True
    actor.save(update_fields=("is_superuser",))
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
    account_id = cast(int, scenario.account.pk)

    with pytest.raises(FeeCorrectionBlockedError) as denied_read:
        use_case.get(account_id, principal=scenario.other_user)
    assert denied_read.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    with pytest.raises(FeeCorrectionBlockedError) as denied_write:
        use_case.save(
            _command(account_id=account_id, expected_version=1),
            principal=scenario.other_user,
        )
    assert denied_write.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
    assert scenario.policy.version == 1


@pytest.mark.django_db
@pytest.mark.parametrize("account_state", ("real", "inactive"))
def test_nonactive_or_real_accounts_cannot_manage_fee_policy(
    evidence_scenario: EvidenceScenario,
    account_state: str,
) -> None:
    """The boundary admits only active simulated accounts, including on GET."""

    scenario = evidence_scenario
    if account_state == "real":
        scenario.account.account_type = "real"
        scenario.account.save()
    else:
        scenario.account.is_active = False
        scenario.account.save(update_fields=("is_active",))

    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
    account_id = cast(int, scenario.account.pk)
    with pytest.raises(FeeCorrectionBlockedError) as denied_read:
        use_case.get(account_id, principal=scenario.owner)
    assert denied_read.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    with pytest.raises(FeeCorrectionBlockedError) as denied_write:
        use_case.save(
            _command(account_id=account_id, expected_version=1),
            principal=scenario.owner,
        )
    assert denied_write.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"


@pytest.mark.django_db
def test_inactive_owner_cannot_manage_fee_policy(evidence_scenario: EvidenceScenario) -> None:
    """A persisted but inactive owner is denied before policy state is returned or saved."""

    scenario = evidence_scenario
    user_model = get_user_model()
    owner = user_model._base_manager.get(pk=scenario.owner_id)
    owner.is_active = False
    owner.save(update_fields=("is_active",))
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
    account_id = cast(int, scenario.account.pk)

    with pytest.raises(FeeCorrectionBlockedError) as denied_read:
        use_case.get(account_id, principal=scenario.owner)
    assert denied_read.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"

    with pytest.raises(FeeCorrectionBlockedError) as denied_write:
        use_case.save(
            _command(account_id=account_id, expected_version=1),
            principal=scenario.owner,
        )
    assert denied_write.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"


@pytest.mark.django_db
def test_disabling_policy_revokes_an_existing_upload_qualification(
    evidence_scenario: EvidenceScenario,
) -> None:
    """A policy update invalidates later evidence upload attempts under the old state."""

    scenario = evidence_scenario
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
    disabled = use_case.save(
        _command(
            account_id=cast(int, scenario.account.pk),
            expected_version=1,
            enabled=False,
            allow_operator_attested_upload=False,
            ledger_currency="CNY",
            attestation_acknowledged=False,
        ),
        principal=scenario.owner,
    )
    assert disabled.version == 2

    with pytest.raises(FeeCorrectionBlockedError) as denied_upload:
        DjangoFeeCorrectionEvidenceRepository().capture(
            scenario.command,
            principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, scenario.owner),
        )
    assert denied_upload.value.code == "FEE_CORRECTION_POLICY_DENIED"


@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    (
        ({"account_id": True}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        ({"expected_version": -1}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        ({"enabled": 1}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        ({"ledger_currency": "cny"}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        ({"ledger_currency": "CN"}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        ({"attestation_acknowledged": False}, "FEE_CORRECTION_POLICY_INPUT_INVALID"),
        (
            {"valid_from": datetime(2026, 1, 1, 0, 0, 0)},
            "FEE_CORRECTION_POLICY_INPUT_INVALID",
        ),
        (
            {
                "valid_from": datetime(2026, 1, 2, tzinfo=UTC),
                "valid_until": datetime(2026, 1, 1, tzinfo=UTC),
            },
            "FEE_CORRECTION_POLICY_INPUT_INVALID",
        ),
    ),
)
def test_policy_command_rejects_invalid_values(
    overrides: dict[str, object],
    expected_code: str,
) -> None:
    """Currency, acknowledgment, and validity must be explicit and well formed."""

    values: dict[str, object] = {
        "account_id": 1,
        "expected_version": 0,
        "enabled": True,
        "allow_operator_attested_upload": True,
        "ledger_currency": "HKD",
        "valid_from": datetime(2026, 1, 1, tzinfo=UTC),
        "valid_until": datetime(2026, 1, 2, tzinfo=UTC),
        "attestation_acknowledged": True,
    }
    values.update(overrides)
    with pytest.raises(FeeCorrectionBlockedError) as invalid:
        FeeCorrectionPolicyCommand(**values)  # type: ignore[arg-type]
    assert invalid.value.code == expected_code


@pytest.mark.django_db
def test_policy_use_case_rejects_invalid_principal_before_repository_call(
    evidence_scenario: EvidenceScenario,
) -> None:
    """The Application boundary does not accept an unauthenticated or forged ID object."""

    scenario = evidence_scenario
    use_case = FeeCorrectionPolicyUseCase(DjangoFeeCorrectionPolicyRepository())
    forged_principal = type(
        "ForgedPrincipal",
        (),
        {"is_authenticated": True, "pk": True},
    )()

    with pytest.raises(FeeCorrectionBlockedError) as denied:
        use_case.get(
            cast(int, scenario.account.pk),
            principal=cast(AuthenticatedFeeCorrectionPrincipalProtocol, forged_principal),
        )
    assert denied.value.code == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
