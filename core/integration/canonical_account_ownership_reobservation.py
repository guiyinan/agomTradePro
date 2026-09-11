"""Compose a current ownership re-observation from permanent creation evidence.

The composition re-reads a server-owned Binding-v2 selector, serializes the
authenticated user's existing Account row, and appends only the raw/source/
Physical-v2 successors needed to represent that read.  It never allocates an
identity, creates a Physical-v3 root, binds a new winner, or grants authority.
Authentication must already have happened before this boundary.  The public
``account_creation_transaction`` helper supplies the same-alias user lock and
transaction only; the requester supplied here must be a trusted server-side
snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from apps.account.application.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2Conflict,
    CanonicalAccountCreationBindingV2Corruption,
    CanonicalAccountCreationBindingV2Unavailable,
    GetExactCanonicalAccountCreationBindingV2Command,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Conflict as DurableReobservationConflict,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1Corruption as DurableReobservationCorruption,
)
from apps.account.application.canonical_account_ownership_reobservation_v1 import (
    RecordCanonicalAccountOwnershipReobservationV1,
    RecordCanonicalAccountOwnershipReobservationV1Command,
)
from apps.account.application.creation_evidence_settings import (
    CanonicalAccountCreationEvidenceSettings,
)
from apps.account.application.physical_account_row_observation_v2 import (
    CapturePhysicalAccountRowObservationV2Command,
    PhysicalAccountRowObservationV2,
    PhysicalAccountRowObservationV2Conflict,
    PhysicalAccountRowObservationV2Corruption,
    PhysicalAccountRowObservationV2Unavailable,
)
from apps.account.canonical_account_ownership_reobservation_composition import (
    build_canonical_account_ownership_reobservation_repository,
)
from apps.account.canonical_creation_composition import (
    build_canonical_account_creation_stages,
)
from apps.account.domain.canonical_account_creation import (
    CanonicalAccountCreationRequester,
)
from apps.account.domain.canonical_account_creation_binding_v2 import (
    CanonicalAccountCreationBindingV2,
)
from apps.account.domain.canonical_account_ownership_reobservation_v1 import (
    CanonicalAccountOwnershipReobservationV1,
)
from apps.simulated_trading.account_physical_row_v2_composition import (
    build_account_physical_row_v2_provider,
)
from apps.simulated_trading.account_reobservation_composition import (
    build_existing_account_reobserver,
)
from apps.simulated_trading.application.account_row_reobservation import (
    ReobserveExistingAccountRowCommand,
)
from apps.simulated_trading.application.current_account_ownership import (
    CurrentAccountOwnershipUnavailable,
)
from apps.simulated_trading.application.simulated_account_raw_observation import (
    SimulatedAccountRawObservationConflict,
    SimulatedAccountRawObservationCorruption,
    SimulatedAccountRawObservationUnavailable,
)
from apps.simulated_trading.application.simulated_account_row_source_v2 import (
    CaptureSimulatedAccountRowSourceV2Command,
    SimulatedAccountRowSourceV2Conflict,
    SimulatedAccountRowSourceV2Corruption,
    SimulatedAccountRowSourceV2Unavailable,
)
from apps.simulated_trading.creation_composition import (
    build_simulated_account_creation_stages,
)
from apps.simulated_trading.creation_transaction_composition import (
    account_creation_transaction,
)
from apps.simulated_trading.domain.entities import AccountType
from apps.simulated_trading.domain.simulated_account_raw_observation import (
    SimulatedAccountRawObservation,
)
from apps.simulated_trading.domain.simulated_account_row_source_v2 import (
    SimulatedAccountRowSourceV2,
)
from core.exceptions import DataValidationError, DuplicateResourceError, ExternalServiceError


class CanonicalAccountOwnershipReobservationUnavailable(ExternalServiceError):
    """Required permanent or current ownership evidence is unavailable."""

    default_message = "canonical Account ownership re-observation is unavailable"
    default_code = "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_UNAVAILABLE"


class CanonicalAccountOwnershipReobservationConflict(DuplicateResourceError):
    """The requested owner or immutable re-observation identity conflicts."""

    default_message = "canonical Account ownership re-observation conflicts"
    default_code = "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_CONFLICT"


class CanonicalAccountOwnershipReobservationCorruption(DataValidationError):
    """A trusted stage returned substituted or malformed evidence."""

    default_message = "canonical Account ownership re-observation evidence is invalid"
    default_code = "CANONICAL_ACCOUNT_OWNERSHIP_REOBSERVATION_CORRUPTION"


def _require_token(value: object, field_name: str) -> str:
    """Validate one exact bounded identity token."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if (
        not value
        or value.strip() != value
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded canonical token")
    return value


def _require_digest(value: object, field_name: str) -> str:
    """Validate one exact lowercase SHA-256 selector hash."""

    if type(value) is not str:
        raise TypeError(f"{field_name} must be an exact string")
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _require_aware(value: object, field_name: str) -> datetime:
    """Validate one exact timezone-aware server clock."""

    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise CanonicalAccountOwnershipReobservationCorruption(
            f"{field_name} must be timezone-aware"
        )
    return value


def _server_now() -> datetime:
    """Return the server clock used for the permanent Binding PIT selector."""

    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CanonicalAccountOwnershipReobservationCommand:
    """Select a permanent Binding and one server-generated observation revision.

    The command carries only immutable IDs, content hashes, and the new
    server-side observation identity.  It deliberately has no user, actor,
    account-row, mode, or renewal fields; those facts are read from the exact
    Binding and the locked physical row.
    """

    binding_id: str
    binding_version: str
    expected_binding_content_hash: str
    observation_id: str
    observation_version: str

    def __post_init__(self) -> None:
        """Reject malformed Binding and new-observation selectors."""

        _require_token(self.binding_id, "binding_id")
        _require_token(self.binding_version, "binding_version")
        _require_digest(self.expected_binding_content_hash, "expected_binding_content_hash")
        _require_token(self.observation_id, "observation_id")
        _require_token(self.observation_version, "observation_version")


def _require_binding(
    value: object,
    command: CanonicalAccountOwnershipReobservationCommand,
    cutoff: datetime,
) -> CanonicalAccountCreationBindingV2:
    """Validate the exact Binding returned by the server-owned reader."""

    if value is None:
        raise CanonicalAccountOwnershipReobservationUnavailable(
            "canonical creation Binding is unavailable"
        )
    if type(value) is not CanonicalAccountCreationBindingV2:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Binding reader returned a substituted type"
        )
    binding = value
    try:
        binding.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Binding reader returned invalid evidence"
        ) from error
    if (
        binding.binding_id != command.binding_id
        or binding.binding_version != command.binding_version
        or binding.content_hash != command.expected_binding_content_hash
    ):
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Binding exact selector was substituted"
        )
    if not binding.is_knowable_at(cutoff):
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Binding exact selector returned future evidence"
        )
    return binding


def _account_type(raw_account_type: str) -> AccountType:
    """Map the sealed raw type to the existing exact AccountType enum."""

    try:
        return AccountType(raw_account_type)
    except ValueError:
        try:
            return AccountType[raw_account_type]
        except KeyError as error:
            raise CanonicalAccountOwnershipReobservationCorruption(
                "Binding contains an unsupported raw account type"
            ) from error


def _require_raw(
    value: object,
    *,
    command: CanonicalAccountOwnershipReobservationCommand,
    binding: CanonicalAccountCreationBindingV2,
    expected_account_type: AccountType,
) -> SimulatedAccountRawObservation:
    """Validate a raw successor before allowing source projection."""

    if type(value) is not SimulatedAccountRawObservation:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "raw re-observer returned a substituted type"
        )
    raw = value
    try:
        raw.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "raw re-observer returned invalid evidence"
        ) from error
    old_physical = binding.creation_root.physical_observation
    if (
        raw.observation_id != command.observation_id
        or raw.observation_version != command.observation_version
        or raw.row_pk != old_physical.underlying_unified_account_id
        or raw.row_user_id != binding.allocation.requested_row_user_id
        or raw.raw_account_type != binding.allocation.requested_raw_account_type
        or raw.raw_account_type != expected_account_type.name
        and raw.raw_account_type != expected_account_type.value
        or raw.is_active is not True
        or raw.is_present is not True
        or raw.is_tombstone is not False
        or raw.row_created_at != old_physical.row_created_at
        or raw.row_updated_at < old_physical.row_updated_at
        or raw.supersedes_content_hash is None
    ):
        raise CanonicalAccountOwnershipReobservationCorruption(
            "raw re-observer changed the Binding physical identity"
        )
    return raw


def _require_source(
    value: object,
    *,
    raw: SimulatedAccountRawObservation,
    binding: CanonicalAccountCreationBindingV2,
) -> SimulatedAccountRowSourceV2:
    """Validate the Source-v2 successor and its exact raw seal."""

    if type(value) is not SimulatedAccountRowSourceV2:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "source capture returned a substituted type"
        )
    source = value
    try:
        source.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "source capture returned invalid evidence"
        ) from error
    if (
        source.source_id != raw.observation_id
        or source.source_version != raw.observation_version
        or source.raw_observation_content_hash != raw.content_hash
        or source.account_namespace != binding.account_namespace_claim
        or source.account_id != binding.account_id_claim
        or source.underlying_unified_account_namespace
        != binding.underlying_unified_account_namespace_claim
        or source.underlying_unified_account_id != binding.underlying_unified_account_id_claim
        or source.row_user_id != binding.allocation.requested_row_user_id
        or source.raw_account_type != binding.allocation.requested_raw_account_type
        or source.is_active is not True
        or source.is_present is not True
        or source.is_tombstone is not False
        or source.supersedes_content_hash is None
        or source.raw_observation_supersedes_content_hash != raw.supersedes_content_hash
    ):
        raise CanonicalAccountOwnershipReobservationCorruption(
            "source capture changed the Binding physical identity"
        )
    return source


def _require_physical(
    value: object,
    *,
    command: CanonicalAccountOwnershipReobservationCommand,
    source: SimulatedAccountRowSourceV2,
    binding: CanonicalAccountCreationBindingV2,
) -> PhysicalAccountRowObservationV2:
    """Validate the Physical-v2 successor before constructing the proof."""

    if type(value) is not PhysicalAccountRowObservationV2:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Physical capture returned a substituted type"
        )
    physical = value
    try:
        physical.__post_init__()
    except (TypeError, ValueError) as error:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Physical capture returned invalid evidence"
        ) from error
    if (
        physical.observation_id != command.observation_id
        or physical.observation_version != command.observation_version
        or physical.source_id != source.source_id
        or physical.source_version != source.source_version
        or physical.source_content_hash != source.content_hash
        or physical.account_namespace != binding.account_namespace_claim
        or physical.account_id != binding.account_id_claim
        or physical.underlying_unified_account_namespace
        != binding.underlying_unified_account_namespace_claim
        or physical.underlying_unified_account_id != binding.underlying_unified_account_id_claim
        or physical.row_user_id != binding.allocation.requested_row_user_id
        or physical.raw_account_type != binding.allocation.requested_raw_account_type
        or physical.is_active is not True
        or physical.is_present is not True
        or physical.is_tombstone is not False
        or physical.supersedes_content_hash is None
    ):
        raise CanonicalAccountOwnershipReobservationCorruption(
            "Physical capture changed the Binding physical identity"
        )
    return physical


def _binding_command(
    command: CanonicalAccountOwnershipReobservationCommand,
    *,
    as_of: datetime,
) -> GetExactCanonicalAccountCreationBindingV2Command:
    """Build the permanent exact Binding selector without accepting nested input."""

    return GetExactCanonicalAccountCreationBindingV2Command(
        binding_id=command.binding_id,
        binding_version=command.binding_version,
        expected_content_hash=command.expected_binding_content_hash,
        as_of=as_of,
    )


def reobserve_canonical_account_ownership(
    *,
    command: CanonicalAccountOwnershipReobservationCommand,
    requester: CanonicalAccountCreationRequester,
    using: str,
    settings: CanonicalAccountCreationEvidenceSettings,
) -> CanonicalAccountOwnershipReobservationV1:
    """Record one current physical re-observation under a trusted user lock.

    Authentication must happen before this Core boundary.  ``requester`` is a
    trusted server-side identity snapshot, not an HTTP identity claim.  The
    transaction helper holds the same-alias user lock while the exact Binding
    read, raw successor, Source-v2 successor, and Physical-v2 successor are
    materialized.  Only the final inactive evidence value is returned.
    """

    if type(command) is not CanonicalAccountOwnershipReobservationCommand:
        raise TypeError("command must be an exact ownership re-observation command")
    command.__post_init__()
    if type(requester) is not CanonicalAccountCreationRequester:
        raise TypeError("requester must be an exact CanonicalAccountCreationRequester")
    requester.__post_init__()
    if type(settings) is not CanonicalAccountCreationEvidenceSettings:
        raise TypeError("settings must be an exact creation evidence settings snapshot")
    settings.__post_init__()

    account_stages = build_canonical_account_creation_stages(
        using=using,
        settings=settings,
        requester=requester,
        physical_row_provider=build_account_physical_row_v2_provider(using=using),
    )
    owner_stages = build_simulated_account_creation_stages(using=using, settings=settings)
    reobserver = build_existing_account_reobserver(using=using, settings=settings)
    if account_stages.database_alias != using or owner_stages.database_alias != using:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "ownership re-observation stages do not share the requested alias"
        )

    try:
        with account_creation_transaction(using=using, user_id=requester.user_id):
            cutoff = _require_aware(_server_now(), "re-observation cutoff")
            binding_value = account_stages.get_exact_binding.execute(
                _binding_command(command, as_of=cutoff)
            )
            binding = _require_binding(binding_value, command, cutoff)
            if binding.allocation.requested_by != requester:
                raise CanonicalAccountOwnershipReobservationConflict(
                    "requester does not match the permanent Binding owner"
                )

            old_physical = binding.creation_root.physical_observation
            expected_account_type = _account_type(binding.allocation.requested_raw_account_type)
            raw_value = reobserver.execute(
                ReobserveExistingAccountRowCommand(
                    observation_id=command.observation_id,
                    observation_version=command.observation_version,
                    row_pk=old_physical.underlying_unified_account_id,
                    expected_user_id=binding.allocation.requested_row_user_id,
                    expected_account_type=expected_account_type,
                    expected_created_at=old_physical.row_created_at,
                    minimum_updated_at=old_physical.row_updated_at,
                )
            )
            raw = _require_raw(
                raw_value,
                command=command,
                binding=binding,
                expected_account_type=expected_account_type,
            )
            source = _require_source(
                owner_stages.source_capture.execute(
                    CaptureSimulatedAccountRowSourceV2Command(
                        source_id=raw.observation_id,
                        source_version=raw.observation_version,
                        expected_raw_observation_content_hash=raw.content_hash,
                        account_namespace=binding.account_namespace_claim,
                        account_id=binding.account_id_claim,
                        underlying_unified_account_namespace=(
                            binding.underlying_unified_account_namespace_claim
                        ),
                        underlying_unified_account_id=(binding.underlying_unified_account_id_claim),
                    )
                ),
                raw=raw,
                binding=binding,
            )
            physical = _require_physical(
                account_stages.physical_capture.execute(
                    CapturePhysicalAccountRowObservationV2Command(
                        observation_id=command.observation_id,
                        observation_version=command.observation_version,
                        source_id=source.source_id,
                        source_version=source.source_version,
                        expected_source_content_hash=source.content_hash,
                        account_namespace=binding.account_namespace_claim,
                        account_id=binding.account_id_claim,
                        underlying_unified_account_namespace=(
                            binding.underlying_unified_account_namespace_claim
                        ),
                        underlying_unified_account_id=(binding.underlying_unified_account_id_claim),
                    )
                ),
                command=command,
                source=source,
                binding=binding,
            )
            try:
                recorded_at = _require_aware(_server_now(), "re-observation recorded_at")
                evidence = CanonicalAccountOwnershipReobservationV1(
                    observation_id=command.observation_id,
                    observation_version=command.observation_version,
                    binding=binding,
                    current_physical=physical,
                    recorded_at=recorded_at,
                    valid_until=physical.valid_until,
                )
                return RecordCanonicalAccountOwnershipReobservationV1(
                    build_canonical_account_ownership_reobservation_repository(using=using)
                ).execute(RecordCanonicalAccountOwnershipReobservationV1Command(evidence))
            except (TypeError, ValueError) as error:
                raise CanonicalAccountOwnershipReobservationCorruption(
                    "ownership re-observation evidence could not be sealed"
                ) from error
    except (
        CanonicalAccountCreationBindingV2Unavailable,
        CurrentAccountOwnershipUnavailable,
        SimulatedAccountRawObservationUnavailable,
        SimulatedAccountRowSourceV2Unavailable,
        PhysicalAccountRowObservationV2Unavailable,
    ) as error:
        raise CanonicalAccountOwnershipReobservationUnavailable(
            "ownership re-observation source is unavailable"
        ) from error
    except (
        CanonicalAccountCreationBindingV2Conflict,
        SimulatedAccountRawObservationConflict,
        SimulatedAccountRowSourceV2Conflict,
        PhysicalAccountRowObservationV2Conflict,
        DurableReobservationConflict,
    ) as error:
        raise CanonicalAccountOwnershipReobservationConflict(
            "ownership re-observation source conflicts with an immutable chain"
        ) from error
    except (
        CanonicalAccountCreationBindingV2Corruption,
        SimulatedAccountRawObservationCorruption,
        SimulatedAccountRowSourceV2Corruption,
        PhysicalAccountRowObservationV2Corruption,
        DurableReobservationCorruption,
    ) as error:
        raise CanonicalAccountOwnershipReobservationCorruption(
            "ownership re-observation source returned invalid evidence"
        ) from error


__all__ = [
    "CanonicalAccountOwnershipReobservationCommand",
    "CanonicalAccountOwnershipReobservationConflict",
    "CanonicalAccountOwnershipReobservationCorruption",
    "CanonicalAccountOwnershipReobservationUnavailable",
    "reobserve_canonical_account_ownership",
]
