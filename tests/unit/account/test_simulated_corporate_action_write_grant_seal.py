"""Server provenance must distinguish authenticated issuance from plain stored facts."""

import base64
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from apps.account.application.simulated_corporate_action_write_grant import (
    SimulatedCorporateActionWriteGrantUnavailable,
)
from apps.account.domain.simulated_corporate_action_write_capabilities import (
    SimulatedCorporateActionWriteCapability,
)
from apps.account.domain.simulated_corporate_action_write_grant import (
    validate_simulated_corporate_action_write_grant_revocation,
)
from apps.account.infrastructure import simulated_corporate_action_write_grant_seal as seals
from tests.unit.account.test_simulated_corporate_action_write_grant import (
    _binding,
    _grant,
    _grant_v2,
    _grant_v3,
    _revocation,
)


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
    assert issued.issuer_evidence_hash == (
        "c613635ae033121e8dba03ed66eceaa46dde8e693c08126c9c3afa29823767bf"
    )
    assert issued.content_hash != _grant().content_hash
    assert seal.seal(issued) == issued


def test_v2_capabilities_use_a_versioned_mac_and_reject_public_hash_resealing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    grant = _grant_v2(
        capabilities=(
            SimulatedCorporateActionWriteCapability.TAX_ASSESS,
            SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
        ),
        supersedes_content_hash=None,
    )

    issued = seal.seal(grant)

    assert issued.issuer_evidence_version == "2"
    assert seal.verify(issued)
    assert issued.issuer_evidence_hash == (
        "d310d7fed5324945048196c448fbbf35753b240ede45d1899e668bce51d78c23"
    )
    forged = replace(
        issued,
        capabilities=(SimulatedCorporateActionWriteCapability.TAX_ASSESS,),
        identity_hash="",
        content_hash="",
    )
    assert not seal.verify(forged)


def test_v3_share_permissions_use_a_distinct_issuer_mac_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    grant = _grant_v3(
        capabilities=(
            SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,
            SimulatedCorporateActionWriteCapability.SHARE_STAGE_WRITE,
        ),
        supersedes_content_hash="e" * 64,
    )

    issued = seal.seal(grant)

    assert issued.issuer_evidence_version == "3"
    assert seal.verify(issued)
    assert issued.issuer_evidence_hash == (
        "bf91e813d8ac2d9a1769e93c5d477896e5e80447b853265c52ceb1d0facdeba0"
    )
    assert seal.seal(issued) == issued
    forged = replace(
        issued,
        capabilities=(SimulatedCorporateActionWriteCapability.RIGHTS_NOT_EXERCISED,),
        identity_hash="",
        content_hash="",
    )
    assert not seal.verify(forged)


def test_v2_revocation_mac_binds_the_complete_grant_content_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _key(monkeypatch)
    seal = seals.SimulatedCorporateActionWriteGrantSeal()
    grant = seal.seal(
        _grant_v2(
            capabilities=(
                SimulatedCorporateActionWriteCapability.TAX_ASSESS,
                SimulatedCorporateActionWriteCapability.TAX_WITHHOLD,
            ),
            supersedes_content_hash=None,
        )
    )
    revocation = seal.seal_revocation(
        _revocation(grant, recorded_at=grant.recorded_at + timedelta(minutes=5))
    )

    assert seal.verify_revocation(revocation)
    assert revocation.grant_content_hash == grant.content_hash
    validate_simulated_corporate_action_write_grant_revocation(grant, revocation)

    forged = replace(
        revocation,
        grant_content_hash="f" * 64,
        identity_hash="",
        content_hash="",
    )
    assert not seal.verify_revocation(forged)
    with pytest.raises(ValueError, match="target"):
        validate_simulated_corporate_action_write_grant_revocation(grant, forged)


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
