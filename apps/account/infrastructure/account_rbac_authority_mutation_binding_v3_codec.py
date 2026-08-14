"""Strict canonical codec for Account RBAC mutation binding evidence v3."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from apps.account.domain.account_actor_authority_raw_source_primitives_v3 import (
    AccountAuthorityRawSourceChainV3,
    canonical_utc_z,
)
from apps.account.domain.account_rbac_authority_mutation_binding_v3 import (
    AccountRbacAuthorityHumanOperatorRefV3,
    AccountRbacAuthorityMutationBindingV3,
    AccountRbacAuthorityMutationIssuerV3,
    AccountRbacAuthorityProfileStateRefV3,
    AccountRbacAuthoritySourceEpochV3,
)


class AccountRbacAuthorityMutationBindingV3CodecError(ValueError):
    """An RBAC mutation binding payload is malformed or non-canonical."""


def encode_account_rbac_authority_mutation_binding_v3(
    value: AccountRbacAuthorityMutationBindingV3,
) -> dict[str, object]:
    """Encode one complete Domain binding without dropping nested evidence."""

    if type(value) is not AccountRbacAuthorityMutationBindingV3:
        raise TypeError("value must be an exact AccountRbacAuthorityMutationBindingV3")
    value.__post_init__()
    return value.to_payload()


def decode_account_rbac_authority_mutation_binding_v3(
    payload: object,
) -> AccountRbacAuthorityMutationBindingV3:
    """Decode exact nested shapes, revalidate Domain seals, and require canonical equality."""

    data = _mapping(payload, "RBAC mutation binding")
    _keys(data, _BINDING_KEYS, "RBAC mutation binding")
    epoch_data = _mapping(data["epoch"], "epoch")
    old_subject_data = data["old_subject"]
    subject_data = _mapping(data["subject"], "subject")
    operator_data = _mapping(data["operator"], "operator")
    issuer_data = _mapping(data["issuer"], "issuer")
    binding_chain_data = _mapping(data["binding_chain"], "binding_chain")
    source_chain_data = _mapping(data["authority_source_chain"], "authority_source_chain")
    _keys(epoch_data, _EPOCH_KEYS, "epoch")
    _keys(subject_data, _PROFILE_KEYS, "subject")
    _keys(operator_data, _OPERATOR_KEYS, "operator")
    _keys(issuer_data, _ISSUER_KEYS, "issuer")
    _keys(binding_chain_data, _CHAIN_KEYS, "binding_chain")
    _keys(source_chain_data, _CHAIN_KEYS, "authority_source_chain")
    try:
        epoch = AccountRbacAuthoritySourceEpochV3(
            epoch_id=_string(epoch_data["epoch_id"]),
            target_user_id=_integer(epoch_data["target_user_id"]),
            subject_actor_id=_string(epoch_data["subject_actor_id"]),
            source_id=_string(epoch_data["source_id"]),
            epoch_sequence=_integer(epoch_data["epoch_sequence"]),
            opened_at=_datetime(epoch_data["opened_at"]),
            previous_epoch_content_hash=_optional_string(epoch_data["previous_epoch_content_hash"]),
            terminal_authority_source_content_hash=_optional_string(
                epoch_data["terminal_authority_source_content_hash"]
            ),
            terminal_mutation_binding_content_hash=_optional_string(
                epoch_data["terminal_mutation_binding_content_hash"]
            ),
            root_claim_hash=_string(epoch_data["root_claim_hash"]),
            identity_hash=_string(epoch_data["identity_hash"]),
            content_hash=_string(epoch_data["content_hash"]),
        )
        if _string(epoch_data["epoch_kind"]) != epoch.epoch_kind:
            raise ValueError("epoch_kind does not match epoch sequence")
        source_id = _string(data["source_id"])
        if source_id != epoch.source_id:
            raise ValueError("binding source_id differs from epoch source_id")
        old_subject = _profile(old_subject_data, "old_subject")
        subject = _profile(subject_data, "subject")
        if subject is None:
            raise ValueError("subject cannot be null")
        operator = AccountRbacAuthorityHumanOperatorRefV3(
            principal_id=_string(operator_data["principal_id"]),
            user_id=_integer(operator_data["user_id"]),
            actor_id=_string(operator_data["actor_id"]),
            is_authenticated=_boolean(operator_data["is_authenticated"]),
            is_active=_boolean(operator_data["is_active"]),
            is_staff=_boolean(operator_data["is_staff"]),
            is_superuser=_boolean(operator_data["is_superuser"]),
            rbac_role=_string(operator_data["rbac_role"]),
            authentication_source_id=_string(operator_data["authentication_source_id"]),
            authentication_source_version=_string(operator_data["authentication_source_version"]),
            authentication_source_content_hash=_string(
                operator_data["authentication_source_content_hash"]
            ),
            user_source_id=_string(operator_data["user_source_id"]),
            user_source_version=_string(operator_data["user_source_version"]),
            user_source_content_hash=_string(operator_data["user_source_content_hash"]),
            rbac_source_id=_string(operator_data["rbac_source_id"]),
            rbac_source_version=_string(operator_data["rbac_source_version"]),
            rbac_source_content_hash=_string(operator_data["rbac_source_content_hash"]),
            observed_at=_datetime(operator_data["observed_at"]),
            valid_until=_datetime(operator_data["valid_until"]),
            identity_hash=_string(operator_data["identity_hash"]),
            authority_hash=_string(operator_data["authority_hash"]),
        )
        issuer = AccountRbacAuthorityMutationIssuerV3(
            service_id=_string(issuer_data["service_id"]),
            role=_string(issuer_data["role"]),
            kind=_string(issuer_data["kind"]),
            is_automated=_boolean(issuer_data["is_automated"]),
            identity_hash=_string(issuer_data["identity_hash"]),
        )
        value = AccountRbacAuthorityMutationBindingV3(
            mutation_id=_string(data["mutation_id"]),
            mutation_kind=_string(data["mutation_kind"]),
            epoch=epoch,
            old_subject=old_subject,
            subject=subject,
            operator=operator,
            issuer=issuer,
            source_version=_string(data["source_version"]),
            old_authority_state=_optional_string(data["old_authority_state"]),
            new_authority_state=_string(data["new_authority_state"]),
            old_rbac_role=_optional_string(data["old_rbac_role"]),
            new_rbac_role=_string(data["new_rbac_role"]),
            authority_source_identity_hash=_string(data["authority_source_identity_hash"]),
            authority_source_content_hash=_string(data["authority_source_content_hash"]),
            authority_source_record_seal=_string(data["authority_source_record_seal"]),
            observed_at=_datetime(data["observed_at"]),
            issued_at=_datetime(data["issued_at"]),
            recorded_at=_datetime(data["recorded_at"]),
            valid_until=_datetime(data["valid_until"]),
            binding_chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=_optional_string(binding_chain_data["root_claim_hash"]),
                supersedes_content_hash=_optional_string(
                    binding_chain_data["supersedes_content_hash"]
                ),
            ),
            authority_source_chain=AccountAuthorityRawSourceChainV3(
                root_claim_hash=_optional_string(source_chain_data["root_claim_hash"]),
                supersedes_content_hash=_optional_string(
                    source_chain_data["supersedes_content_hash"]
                ),
            ),
            identity_hash=_string(data["identity_hash"]),
            transition_seal=_string(data["transition_seal"]),
            old_subject_seal=_string(data["old_subject_seal"]),
            subject_seal=_string(data["subject_seal"]),
            operator_seal=_string(data["operator_seal"]),
            issuer_seal=_string(data["issuer_seal"]),
            source_binding_seal=_string(data["source_binding_seal"]),
            clock_seal=_string(data["clock_seal"]),
            binding_chain_seal=_string(data["binding_chain_seal"]),
            authority_source_chain_seal=_string(data["authority_source_chain_seal"]),
            fixed_authority_seal=_string(data["fixed_authority_seal"]),
            record_seal=_string(data["record_seal"]),
            content_hash=_string(data["content_hash"]),
            owner=_string(data["owner"]),
            artifact_type=_string(data["artifact_type"]),
            schema=_string(data["schema"]),
            permission=_string(data["permission"]),
            status=_string(data["status"]),
            must_not_execute=_boolean(data["must_not_execute"]),
            execution_allowed=_boolean(data["execution_allowed"]),
        )
    except (
        AccountRbacAuthorityMutationBindingV3CodecError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, AccountRbacAuthorityMutationBindingV3CodecError):
            raise
        raise AccountRbacAuthorityMutationBindingV3CodecError(
            "RBAC mutation binding payload is invalid"
        ) from error
    if encode_account_rbac_authority_mutation_binding_v3(value) != payload:
        raise AccountRbacAuthorityMutationBindingV3CodecError(
            "RBAC mutation binding payload is non-canonical"
        )
    return value


def _profile(value: object, name: str) -> AccountRbacAuthorityProfileStateRefV3 | None:
    if value is None:
        return None
    data = _mapping(value, name)
    _keys(data, _PROFILE_KEYS, name)
    return AccountRbacAuthorityProfileStateRefV3(
        profile_id=_string(data["profile_id"]),
        profile_version=_string(data["profile_version"]),
        profile_content_hash=_string(data["profile_content_hash"]),
        rbac_role=_string(data["rbac_role"]),
        user_id=_integer(data["user_id"]),
        subject_actor_id=_string(data["subject_actor_id"]),
        observed_at=_datetime(data["observed_at"]),
        identity_hash=_string(data["identity_hash"]),
        content_hash=_string(data["content_hash"]),
    )


def _mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise AccountRbacAuthorityMutationBindingV3CodecError(f"{name} must be an exact mapping")
    raw = cast(dict[object, object], value)
    if any(type(key) is not str for key in raw):
        raise AccountRbacAuthorityMutationBindingV3CodecError(f"{name} keys are invalid")
    return cast(dict[str, object], raw)


def _keys(data: dict[str, object], expected: set[str], name: str) -> None:
    if set(data) != expected:
        raise AccountRbacAuthorityMutationBindingV3CodecError(f"{name} has an invalid shape")


def _string(value: object) -> str:
    if type(value) is not str:
        raise AccountRbacAuthorityMutationBindingV3CodecError("expected an exact string")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise AccountRbacAuthorityMutationBindingV3CodecError("expected an exact integer")
    return value


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise AccountRbacAuthorityMutationBindingV3CodecError("expected an exact boolean")
    return value


def _datetime(value: object) -> datetime:
    text = _string(value)
    if not text.endswith("Z"):
        raise AccountRbacAuthorityMutationBindingV3CodecError(
            "datetime must use canonical UTC-Z microseconds"
        )
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00")
    except ValueError as error:
        raise AccountRbacAuthorityMutationBindingV3CodecError("datetime is invalid") from error
    if parsed.tzinfo != UTC or canonical_utc_z(parsed) != text:
        raise AccountRbacAuthorityMutationBindingV3CodecError("datetime is not canonical UTC-Z")
    return parsed


_PROFILE_KEYS = {
    "profile_id",
    "profile_version",
    "profile_content_hash",
    "rbac_role",
    "user_id",
    "subject_actor_id",
    "observed_at",
    "identity_hash",
    "content_hash",
}
_OPERATOR_KEYS = {
    "principal_id",
    "user_id",
    "actor_id",
    "is_authenticated",
    "is_active",
    "is_staff",
    "is_superuser",
    "rbac_role",
    "authentication_source_id",
    "authentication_source_version",
    "authentication_source_content_hash",
    "user_source_id",
    "user_source_version",
    "user_source_content_hash",
    "rbac_source_id",
    "rbac_source_version",
    "rbac_source_content_hash",
    "observed_at",
    "valid_until",
    "identity_hash",
    "authority_hash",
}
_ISSUER_KEYS = {"service_id", "role", "kind", "is_automated", "identity_hash"}
_EPOCH_KEYS = {
    "epoch_id",
    "target_user_id",
    "subject_actor_id",
    "source_id",
    "epoch_sequence",
    "opened_at",
    "previous_epoch_content_hash",
    "root_claim_hash",
    "terminal_authority_source_content_hash",
    "terminal_mutation_binding_content_hash",
    "epoch_kind",
    "identity_hash",
    "content_hash",
}
_CHAIN_KEYS = {"root_claim_hash", "supersedes_content_hash"}
_BINDING_KEYS = {
    "mutation_id",
    "mutation_kind",
    "epoch",
    "old_subject",
    "subject",
    "operator",
    "issuer",
    "source_version",
    "old_authority_state",
    "new_authority_state",
    "old_rbac_role",
    "new_rbac_role",
    "authority_source_identity_hash",
    "authority_source_content_hash",
    "authority_source_record_seal",
    "observed_at",
    "issued_at",
    "recorded_at",
    "valid_until",
    "binding_chain",
    "authority_source_chain",
    "source_id",
    "identity_hash",
    "transition_seal",
    "old_subject_seal",
    "subject_seal",
    "operator_seal",
    "issuer_seal",
    "source_binding_seal",
    "clock_seal",
    "binding_chain_seal",
    "authority_source_chain_seal",
    "fixed_authority_seal",
    "record_seal",
    "content_hash",
    "owner",
    "artifact_type",
    "schema",
    "permission",
    "status",
    "must_not_execute",
    "execution_allowed",
}


__all__ = [
    "AccountRbacAuthorityMutationBindingV3CodecError",
    "decode_account_rbac_authority_mutation_binding_v3",
    "encode_account_rbac_authority_mutation_binding_v3",
]
