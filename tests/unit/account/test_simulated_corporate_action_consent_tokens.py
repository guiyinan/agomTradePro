"""Preparation tokens never authenticate owners or survive terms/scope substitution."""

import base64
import hashlib
import json
from dataclasses import replace
from datetime import timedelta

import pytest

from apps.account import simulated_corporate_action_consent_composition as tokens
from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.application.simulated_corporate_action_write_issuance import (
    SimulatedCorporateActionGrantConsent,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA,
    SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
)
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _AT,
    _grant,
    _grant_v2,
)
from tests.unit.account.test_simulated_corporate_action_write_grant_seal import _key


def _command():
    grant = _grant()
    return SimulatedCorporateActionGrantConsent(
        grant_id=grant.grant_id,
        grant_version=grant.grant_version,
        physical_account_id=41,
        expected_binding=grant.binding,
        valid_until=_AT + timedelta(minutes=5),
        consent=True,
    )


def _v2_command():
    """Build one explicit V2 preparation with no inferred capabilities or terms."""
    return replace(
        _command(),
        grant_schema=SIMULATED_CORPORATE_ACTION_WRITE_GRANT_V2_SCHEMA,
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        ),
        terms_version="owner-terms-v2",
        terms_sha256="c" * 64,
    )


def _v2_payload(command: SimulatedCorporateActionGrantConsent) -> dict[str, object]:
    """Construct exact token fields for malformed-but-validly-signed contract tests."""
    assert command.capabilities is not None
    return {
        "grant_id": command.grant_id,
        "grant_version": command.grant_version,
        "physical_account_id": command.physical_account_id,
        "binding": command.expected_binding.to_payload(),
        "prepared_at": _AT.isoformat(),
        "valid_until": command.valid_until.isoformat(),
        "predecessor": command.expected_predecessor_content_hash,
        "grant_schema": command.grant_schema,
        "capabilities": [capability.value for capability in command.capabilities],
        "terms_version": command.terms_version,
        "terms_sha256": command.terms_sha256,
    }


def _signed_v2(payload: dict[str, object]) -> str:
    """MAC one V2 token fixture using only the test server key."""
    return "v2." + tokens._pack(payload, purpose="account.simulated-action-consent-preparation.v2")


def test_oversized_v2_envelope_is_rejected_before_mac_decoder(monkeypatch):
    def unexpected_decode(*args, **kwargs):
        pytest.fail("Oversized full envelope reached the MAC decoder")

    monkeypatch.setattr(tokens, "_unpack", unexpected_decode)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            "v2." + "x" * 16382,
            owner_user_id=81,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )


def _tamper_v2_without_mac(token: str, *, field: str, value: object) -> str:
    """Change one authenticated field while retaining the old MAC."""
    packed = token[3:]
    _, digest = packed.rsplit(".", 1)
    payload = tokens._unpack(packed, purpose="account.simulated-action-consent-preparation.v2")
    payload[field] = value
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    changed_body = base64.urlsafe_b64encode(body).decode()
    return "v2." + changed_body + "." + digest


def test_displayed_consent_terms_roundtrip_only_with_explicit_owner_confirmation(monkeypatch):
    _key(monkeypatch)
    command = _command()
    token = tokens.prepare_simulated_action_consent_token(command, as_of=_AT)
    assert not token.startswith("v1.")
    assert hashlib.sha256(token.encode("utf-8")).hexdigest() == (
        "cb0149d2dbc7744a2509d337995cc3a532e202524e5b341d9381debcb3c49bd3"
    )
    restored = tokens.restore_simulated_action_consent_token(
        token,
        owner_user_id=command.expected_binding.owner_user_id,
        physical_account_id=41,
        confirmed=True,
        as_of=_AT + timedelta(seconds=1),
    )
    assert restored == command


def test_v2_displayed_consent_roundtrips_full_explicit_rights_and_terms(monkeypatch):
    _key(monkeypatch)
    command = _v2_command()
    token = tokens.prepare_simulated_action_consent_token(command, as_of=_AT)
    assert token.startswith("v2.")
    restored = tokens.restore_simulated_action_consent_token(
        token,
        owner_user_id=command.expected_binding.owner_user_id,
        physical_account_id=command.physical_account_id,
        confirmed=True,
        as_of=_AT + timedelta(seconds=1),
    )
    assert restored == command


@pytest.mark.parametrize(
    "defect",
    [
        "missing_capabilities",
        "extra_field",
        "unknown_capability",
        "duplicate_capability",
        "reordered_capabilities",
        "nonstring_capability",
        "missing_terms",
        "wrong_schema",
        "missing_schema",
        "bad_terms_version",
        "bad_terms_digest",
    ],
)
def test_v2_consent_rejects_signed_noncanonical_rights_or_terms(monkeypatch, defect):
    _key(monkeypatch)
    command = _v2_command()
    payload = _v2_payload(command)
    capabilities = payload["capabilities"]
    assert isinstance(capabilities, list)
    if defect == "missing_capabilities":
        del payload["capabilities"]
    elif defect == "extra_field":
        payload["unexpected"] = "extra"
    elif defect == "unknown_capability":
        payload["capabilities"] = ["simulated.corporate_action_tax.unknown"]
    elif defect == "duplicate_capability":
        payload["capabilities"] = [capabilities[0], capabilities[0]]
    elif defect == "reordered_capabilities":
        payload["capabilities"] = list(reversed(capabilities))
    elif defect == "nonstring_capability":
        payload["capabilities"] = [True]
    elif defect == "missing_terms":
        del payload["terms_version"]
    elif defect == "wrong_schema":
        payload["grant_schema"] = SIMULATED_CORPORATE_ACTION_WRITE_GRANT_SCHEMA
    elif defect == "missing_schema":
        del payload["grant_schema"]
    elif defect == "bad_terms_version":
        payload["terms_version"] = "contains whitespace"
    else:
        payload["terms_sha256"] = "D" * 64
    token = _signed_v2(payload)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=command.expected_binding.owner_user_id,
            physical_account_id=command.physical_account_id,
            confirmed=True,
            as_of=_AT,
        )


def test_v1_restore_rejects_v2_extras_even_with_a_valid_v1_mac(monkeypatch):
    _key(monkeypatch)
    command = _v2_command()
    token = tokens._pack(
        _v2_payload(command), purpose="account.simulated-action-consent-preparation.v1"
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=command.expected_binding.owner_user_id,
            physical_account_id=command.physical_account_id,
            confirmed=True,
            as_of=_AT,
        )


def test_consent_version_prefixes_never_fall_back_between_mac_purposes(monkeypatch):
    _key(monkeypatch)
    v1_command = _command()
    v1_token = tokens.prepare_simulated_action_consent_token(v1_command, as_of=_AT)
    v2_command = _v2_command()
    v2_token = _signed_v2(_v2_payload(v2_command))
    attempts = (
        ("v2." + v1_token, v1_command),
        (v2_token[3:], v2_command),
        ("v3." + v2_token[3:], v2_command),
        ("v1." + v1_token, v1_command),
    )
    for token, command in attempts:
        with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
            tokens.restore_simulated_action_consent_token(
                token,
                owner_user_id=command.expected_binding.owner_user_id,
                physical_account_id=command.physical_account_id,
                confirmed=True,
                as_of=_AT,
            )


@pytest.mark.parametrize(
    "mutation",
    ["owner", "account", "unconfirmed", "expired", "future", "tampered"],
)
def test_v2_consent_token_binds_owner_account_confirmation_and_clock(monkeypatch, mutation):
    _key(monkeypatch)
    command = _v2_command()
    token = _signed_v2(_v2_payload(command))
    kwargs = {
        "owner_user_id": command.expected_binding.owner_user_id,
        "physical_account_id": command.physical_account_id,
        "confirmed": True,
        "as_of": _AT,
    }
    if mutation == "owner":
        kwargs["owner_user_id"] += 1
    elif mutation == "account":
        kwargs["physical_account_id"] += 1
    elif mutation == "unconfirmed":
        kwargs["confirmed"] = False
    elif mutation == "expired":
        kwargs["as_of"] = command.valid_until
    elif mutation == "future":
        kwargs["as_of"] = _AT - timedelta(seconds=1)
    else:
        token = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(token, **kwargs)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("predecessor", "f" * 64),
        ("terms_version", "owner-terms-v3"),
        ("terms_sha256", "d" * 64),
    ],
)
def test_v2_predecessor_and_terms_tampering_fails_the_mac(monkeypatch, field, value):
    _key(monkeypatch)
    command = _v2_command()
    token = _signed_v2(_v2_payload(command))
    token = _tamper_v2_without_mac(token, field=field, value=value)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=command.expected_binding.owner_user_id,
            physical_account_id=command.physical_account_id,
            confirmed=True,
            as_of=_AT,
        )


@pytest.mark.parametrize(
    "mutation", ["owner", "account", "unconfirmed", "expired", "future", "seal"]
)
def test_consent_preparation_cannot_be_promoted_across_owner_scope_or_clock(monkeypatch, mutation):
    _key(monkeypatch)
    command = _command()
    token = tokens.prepare_simulated_action_consent_token(command, as_of=_AT)
    kwargs = {
        "owner_user_id": command.expected_binding.owner_user_id,
        "physical_account_id": 41,
        "confirmed": True,
        "as_of": _AT,
    }
    if mutation == "owner":
        kwargs["owner_user_id"] += 1
    elif mutation == "account":
        kwargs["physical_account_id"] += 1
    elif mutation == "unconfirmed":
        kwargs["confirmed"] = False
    elif mutation == "expired":
        kwargs["as_of"] = command.valid_until
    elif mutation == "future":
        kwargs["as_of"] = _AT - timedelta(seconds=1)
    else:
        token = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(token, **kwargs)


def test_withdrawal_locator_is_distinct_and_keeps_exact_historical_target(monkeypatch):
    _key(monkeypatch)
    grant = _grant()
    token = tokens.prepare_simulated_action_withdrawal_token(grant, physical_account_id=41)
    assert (
        tokens.restore_simulated_action_withdrawal_token(
            token, owner_user_id=grant.binding.owner_user_id, physical_account_id=41
        )
        == grant.selector
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=grant.binding.owner_user_id,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )


def test_v2_grant_withdrawal_locator_preserves_the_full_content_selector(monkeypatch):
    _key(monkeypatch)
    grant = _grant_v2(
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        supersedes_content_hash=None,
    )
    token = tokens.prepare_simulated_action_withdrawal_token(grant, physical_account_id=41)
    selector = tokens.restore_simulated_action_withdrawal_token(
        token,
        owner_user_id=grant.binding.owner_user_id,
        physical_account_id=41,
    )
    assert selector == grant.selector
    assert selector.content_hash == grant.content_hash
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=grant.binding.owner_user_id,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )


def test_rotating_the_server_key_invalidates_a_preparation_token(monkeypatch):
    _key(monkeypatch)
    token = tokens.prepare_simulated_action_consent_token(_command(), as_of=_AT)
    _key(monkeypatch, b"b" * 32)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        tokens.restore_simulated_action_consent_token(
            token,
            owner_user_id=_command().expected_binding.owner_user_id,
            physical_account_id=41,
            confirmed=True,
            as_of=_AT,
        )
