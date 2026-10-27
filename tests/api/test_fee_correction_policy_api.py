"""Owner policy HTTP contracts using the real evidence repository and auth stack."""

from __future__ import annotations

import time

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.account.infrastructure.models import UserAccessTokenModel
from apps.simulated_trading.infrastructure.fee_correction_evidence_models import (
    FeeCorrectionEvidencePolicyModel,
)
from tests.component.account.test_authentication import _create_profile, _internal_signature
from tests.component.simulated_trading.test_fee_correction_evidence_repository import (
    EvidenceScenario,
    evidence_scenario,
)

__all__ = ["evidence_scenario"]


def _url(account_id: int) -> str:
    return f"/api/simulated-trading/accounts/{account_id}/fee-correction-policy/"


def _payload(**changes: object) -> dict[str, object]:
    data: dict[str, object] = {
        "expected_version": 0,
        "enabled": True,
        "allow_operator_attested_upload": True,
        "ledger_currency": "CNY",
        "valid_from": None,
        "valid_until": None,
        "attestation_acknowledged": True,
    }
    data.update(changes)
    return data


def test_owner_can_read_enable_disable_and_reject_stale_version(
    evidence_scenario: EvidenceScenario,
) -> None:
    scenario = evidence_scenario
    account = scenario.other_account
    client = APIClient()
    client.force_authenticate(user=scenario.owner)
    url = _url(account.pk)
    response = client.get(url, HTTP_ACCEPT="application/json")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/json"
    assert response.json()["policy"]["version"] == 0
    assert response.json()["policy"]["enabled"] is False
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(account=account).exists()

    enabled = client.put(url, _payload(), format="json")
    assert enabled.status_code == 200
    assert enabled["Content-Type"] == "application/json"
    policy = enabled.json()["policy"]
    assert policy["version"] == 1
    assert policy["enabled"] is True
    assert policy["updated_by_id"] == scenario.owner_id
    assert policy["assurance_class"] == "operator_attested_upload"
    assert "发行方认证" in policy["assurance_notice"]
    stale = client.put(url, _payload(), format="json")
    assert stale.status_code == 409
    assert stale.json()["code"] == "FEE_CORRECTION_POLICY_CONFLICT"
    disabled = client.put(
        url,
        _payload(
            expected_version=1,
            enabled=False,
            allow_operator_attested_upload=False,
            attestation_acknowledged=False,
        ),
        format="json",
    )
    assert disabled.status_code == 200
    assert disabled.json()["policy"]["version"] == 2
    assert disabled.json()["policy"]["enabled"] is False
    # Configuring evidence eligibility never posts cash or rewrites a trade.
    account.refresh_from_db()
    scenario.trade.refresh_from_db()
    assert str(account.current_cash) == "3995.90"
    assert str(scenario.trade.commission) == "3.00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_version", True),
        ("expected_version", "0"),
        ("enabled", "true"),
        ("allow_operator_attested_upload", 1),
        ("attestation_acknowledged", False),
        ("ledger_currency", "cny"),
        ("valid_from", "2026-10-27T01:00:00"),
        ("actor_user_id", 123),
        ("account_id", 123),
        ("valid_until", "not-a-date"),
    ],
)
def test_invalid_policy_input_has_no_write(
    evidence_scenario: EvidenceScenario,
    field: str,
    value: object,
) -> None:
    client = APIClient()
    client.force_authenticate(user=evidence_scenario.owner)
    response = client.put(
        _url(evidence_scenario.other_account.pk), _payload(**{field: value}), format="json"
    )
    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(
        account=evidence_scenario.other_account
    ).exists()


@pytest.mark.parametrize("body", [[], "settings", 1])
def test_nonobject_policy_input_returns_json_error_without_write(
    evidence_scenario: EvidenceScenario,
    body: object,
) -> None:
    client = APIClient()
    client.force_authenticate(user=evidence_scenario.owner)
    response = client.put(_url(evidence_scenario.other_account.pk), body, format="json")
    assert response.status_code == 400
    assert response["Content-Type"] == "application/json"
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(
        account=evidence_scenario.other_account
    ).exists()


@pytest.mark.parametrize("superuser", [False, True])
def test_foreign_owner_and_superuser_cannot_read_or_write(
    evidence_scenario: EvidenceScenario,
    superuser: bool,
) -> None:
    other = evidence_scenario.other_user
    other.is_superuser = superuser
    other.is_staff = superuser
    other.save()
    client = APIClient()
    client.force_authenticate(user=other)
    url = _url(evidence_scenario.account.pk)
    for response in (client.get(url), client.put(url, _payload(expected_version=1), format="json")):
        assert response.status_code == 403
        assert response["Content-Type"] == "application/json"
        assert response.json()["code"] == "FEE_CORRECTION_AUTHORITY_UNAVAILABLE"
        assert "policy" not in response.json()
    evidence_scenario.policy.refresh_from_db()
    assert evidence_scenario.policy.version == 1


def test_anonymous_and_session_without_csrf_cannot_write(
    evidence_scenario: EvidenceScenario,
) -> None:
    url = _url(evidence_scenario.other_account.pk)
    anonymous = APIClient()
    response = anonymous.put(url, _payload(), format="json")
    assert response.status_code == 403
    assert response["Content-Type"] == "application/json"
    client = APIClient(enforce_csrf_checks=True)
    client.force_login(evidence_scenario.owner)
    assert client.get(url).status_code == 200
    assert client.put(url, _payload(), format="json").status_code == 403
    assert not FeeCorrectionEvidencePolicyModel.objects.filter(
        account=evidence_scenario.other_account
    ).exists()


@pytest.mark.parametrize("writable", [False, True])
def test_token_access_level_controls_policy_writes(
    evidence_scenario: EvidenceScenario,
    writable: bool,
) -> None:
    owner = evidence_scenario.owner
    _create_profile(owner)
    _, token = UserAccessTokenModel.create_token(
        user=owner,
        name="policy-readonly",
        access_level=(
            UserAccessTokenModel.ACCESS_LEVEL_READ_WRITE
            if writable
            else UserAccessTokenModel.ACCESS_LEVEL_READ_ONLY
        ),
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
    url = _url(evidence_scenario.other_account.pk)
    assert client.get(url).status_code == 200
    response = client.put(url, _payload(), format="json")
    assert response.status_code == (200 if writable else 403)
    if not writable:
        assert "read-only" in response.json()["error"]
    assert (
        FeeCorrectionEvidencePolicyModel.objects.filter(
            account=evidence_scenario.other_account
        ).exists()
        is writable
    )


@pytest.mark.parametrize("signature_valid", [True, False])
@override_settings(AGOMTRADEPRO_INTERNAL_AUTH_SECRET="fee-policy-test-secret")
def test_terminal_signature_preserves_owner_write_contract(
    evidence_scenario: EvidenceScenario,
    signature_valid: bool,
) -> None:
    owner = evidence_scenario.owner
    _create_profile(owner)
    url = _url(evidence_scenario.other_account.pk)
    timestamp = str(int(time.time()))
    signature = _internal_signature(
        secret="fee-policy-test-secret",
        timestamp=timestamp,
        method="PUT",
        path=url,
        user_id=owner.pk,
        username=owner.username,
    )
    client = APIClient(enforce_csrf_checks=True)
    response = client.put(
        url,
        _payload(),
        format="json",
        HTTP_X_AGOM_INTERNAL_TIMESTAMP=timestamp,
        HTTP_X_AGOM_INTERNAL_USER_ID=str(owner.pk),
        HTTP_X_AGOM_INTERNAL_USERNAME=owner.username,
        HTTP_X_AGOM_INTERNAL_SIGNATURE=signature if signature_valid else "invalid-signature",
    )
    assert response.status_code == (200 if signature_valid else 403)
    assert response["Content-Type"] == "application/json"
    assert (
        FeeCorrectionEvidencePolicyModel.objects.filter(
            account=evidence_scenario.other_account
        ).exists()
        is signature_valid
    )
