from __future__ import annotations

from copy import deepcopy

import pytest

from apps.account.infrastructure.account_rbac_authority_mutation_binding_v3_codec import (
    AccountRbacAuthorityMutationBindingV3CodecError,
    decode_account_rbac_authority_mutation_binding_v3,
    encode_account_rbac_authority_mutation_binding_v3,
)
from tests.unit.account.test_account_rbac_authority_mutation_binding_v3 import _binding


def test_complete_nested_binding_roundtrips_canonically() -> None:
    root = _binding()
    binding = _binding("role_change", previous=root, new_role="admin")
    payload = encode_account_rbac_authority_mutation_binding_v3(binding)

    restored = decode_account_rbac_authority_mutation_binding_v3(payload)

    assert restored == binding
    assert restored.old_subject == binding.old_subject
    assert restored.operator == binding.operator
    assert restored.issuer == binding.issuer
    assert restored.epoch == binding.epoch
    assert restored.binding_chain == binding.binding_chain
    assert restored.authority_source_chain == binding.authority_source_chain
    assert encode_account_rbac_authority_mutation_binding_v3(restored) == payload


def test_bootstrap_nullable_old_subject_and_dual_roots_roundtrip() -> None:
    binding = _binding()
    payload = encode_account_rbac_authority_mutation_binding_v3(binding)

    restored = decode_account_rbac_authority_mutation_binding_v3(payload)

    assert restored.old_subject is None
    assert restored.binding_chain.root_claim_hash is not None
    assert restored.authority_source_chain.root_claim_hash == restored.epoch.root_claim_hash


@pytest.mark.parametrize(
    "path",
    [
        ("epoch", "content_hash"),
        ("old_subject", "content_hash"),
        ("subject", "content_hash"),
        ("operator", "authority_hash"),
        ("issuer", "identity_hash"),
        ("binding_chain", "supersedes_content_hash"),
        ("authority_source_chain", "supersedes_content_hash"),
        ("content_hash",),
    ],
)
def test_nested_seals_and_hashes_are_domain_revalidated(path: tuple[str, ...]) -> None:
    root = _binding()
    binding = _binding("role_change", previous=root, new_role="admin")
    payload = deepcopy(encode_account_rbac_authority_mutation_binding_v3(binding))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = "0" * 64

    with pytest.raises(AccountRbacAuthorityMutationBindingV3CodecError):
        decode_account_rbac_authority_mutation_binding_v3(payload)


def test_cross_chain_predecessor_replacement_fails_closed() -> None:
    root = _binding()
    binding = _binding("role_change", previous=root, new_role="admin")
    payload = deepcopy(encode_account_rbac_authority_mutation_binding_v3(binding))
    source_chain = payload["authority_source_chain"]
    assert type(source_chain) is dict
    source_chain["supersedes_content_hash"] = root.content_hash

    with pytest.raises(AccountRbacAuthorityMutationBindingV3CodecError):
        decode_account_rbac_authority_mutation_binding_v3(payload)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("epoch", "epoch_sequence"), True),
        (("subject", "user_id"), True),
        (("operator", "is_active"), 1),
        (("must_not_execute",), 1),
        (("observed_at",), "2026-08-14T10:06:00+00:00"),
    ],
)
def test_exact_types_and_canonical_utc_z_are_required(path: tuple[str, ...], value: object) -> None:
    root = _binding()
    binding = _binding("role_change", previous=root, new_role="admin")
    payload = deepcopy(encode_account_rbac_authority_mutation_binding_v3(binding))
    target: object = payload
    for key in path[:-1]:
        assert type(target) is dict
        target = target[key]
    assert type(target) is dict
    target[path[-1]] = value

    with pytest.raises(AccountRbacAuthorityMutationBindingV3CodecError):
        decode_account_rbac_authority_mutation_binding_v3(payload)


def test_unknown_and_missing_nested_keys_are_rejected() -> None:
    binding = _binding()
    payload = encode_account_rbac_authority_mutation_binding_v3(binding)

    extra = deepcopy(payload)
    extra["subject"]["unexpected"] = None  # type: ignore[index]
    with pytest.raises(AccountRbacAuthorityMutationBindingV3CodecError, match="shape"):
        decode_account_rbac_authority_mutation_binding_v3(extra)

    missing = deepcopy(payload)
    del missing["operator"]["authority_hash"]  # type: ignore[index]
    with pytest.raises(AccountRbacAuthorityMutationBindingV3CodecError, match="shape"):
        decode_account_rbac_authority_mutation_binding_v3(missing)


def test_encoder_rejects_non_exact_binding() -> None:
    with pytest.raises(TypeError):
        encode_account_rbac_authority_mutation_binding_v3(object())  # type: ignore[arg-type]
