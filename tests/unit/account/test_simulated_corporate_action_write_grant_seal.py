"""Server provenance must distinguish authenticated issuance from plain stored facts."""

import base64
from dataclasses import replace
from types import SimpleNamespace

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.infrastructure import simulated_corporate_action_write_grant_seal as seals
from tests.unit.account.test_simulated_corporate_action_write_grant import _binding, _grant


def _key(monkeypatch: pytest.MonkeyPatch, raw: bytes = b"a" * 32) -> None:
    monkeypatch.setattr(
        seals,
        "get_secrets",
        lambda **kwargs: SimpleNamespace(
            field_encryption_key=base64.urlsafe_b64encode(raw).decode("ascii")
        ),
    )


def test_plain_canonical_storage_record_is_not_issuer_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    assert not seal.verify(_grant())
    issued = seal.seal(_grant())
    assert seal.verify(issued)
    assert issued.content_hash != _grant().content_hash
    assert seal.seal(issued) == issued


@pytest.mark.parametrize(
    "change",
    [
        {"grant_version": "different"},
        {"consent_evidence_hash": "f" * 64},
        {"binding": _binding(owner_user_id=82)},
        {"binding": _binding(account_id="another-account")},
        {"binding": _binding(tenant_id="another-tenant")},
        {"binding": _binding(policy_content_hash="f" * 64)},
        {"binding": _binding(account_source_content_hash="f" * 64)},
    ],
)
def test_recomputing_public_hashes_does_not_reseal_changed_authority(
    monkeypatch: pytest.MonkeyPatch, change: dict[str, object]
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    issued = seal.seal(_grant())
    forged = replace(issued, **change, content_hash="", identity_hash="")
    assert not seal.verify(forged)


def test_rotated_or_missing_server_key_never_accepts_old_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    issued = seal.seal(_grant())
    _key(monkeypatch, b"b" * 32)
    assert not seal.verify(issued)
    _key(monkeypatch, b"a" * 32)
    assert seal.verify(issued)  # Restored key never removes separate revocation/scope checks.
    monkeypatch.setattr(
        seals, "get_secrets", lambda **kwargs: SimpleNamespace(field_encryption_key=None)
    )
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        seal.verify(issued)


@pytest.mark.parametrize("raw", [b"", b"x" * 31, b"x" * 33])
def test_invalid_secret_configuration_fails_closed(
    monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    _key(monkeypatch, raw)
    with pytest.raises(SimulatedCorporateActionWriteGrantUnavailable):
        seals.SimulatedCorporateActionWriteGrantSeal().seal(_grant())
