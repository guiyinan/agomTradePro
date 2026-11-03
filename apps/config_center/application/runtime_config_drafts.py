"""Create immutable Config Center drafts without publishing runtime snapshots."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from apps.config_center.domain.runtime_config import (
    RuntimeConfigDefinition,
    RuntimeConfigProfile,
    RuntimeConfigRevision,
    RuntimeConfigValue,
    RuntimeProfileStatus,
    hash_runtime_profile_values,
    project_public_runtime_values,
)


class RuntimeConfigDraftValidationError(ValueError):
    """One draft request failed generic Config Center validation."""

    def __init__(self, reason_code: str, message: str) -> None:
        """Keep a stable error code alongside the operator-facing detail."""

        self.reason_code = reason_code
        super().__init__(message)


class RuntimeConfigDraftConflictError(RuntimeError):
    """A create-only profile key/version already contains different content."""


@dataclass(frozen=True, slots=True)
class RuntimeConfigDraftValueInput:
    """One typed configuration value supplied for a draft profile."""

    definition_key: str
    value_json: object
    source: str
    secret_ref: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeConfigDraftRequest:
    """Immutable create-only request for one inactive profile version."""

    profile_key: str
    environment: str
    version: int
    actor: str
    reason: str
    values: tuple[RuntimeConfigDraftValueInput, ...]
    release_ref: str = ""


@dataclass(frozen=True, slots=True)
class RuntimeConfigDraftPlan:
    """Prepared draft entities after generic definition-type validation."""

    profile: RuntimeConfigProfile
    values: tuple[RuntimeConfigValue, ...]
    revision: RuntimeConfigRevision


@dataclass(frozen=True, slots=True)
class RuntimeConfigDraftCreateResult:
    """Persisted draft entities and whether this call inserted them."""

    profile: RuntimeConfigProfile
    values: tuple[RuntimeConfigValue, ...]
    revision: RuntimeConfigRevision
    created: bool


class RuntimeConfigDraftDefinitionPort(Protocol):
    """Read the registered definitions used for generic draft validation."""

    def list_all(self) -> list[RuntimeConfigDefinition]:
        """Return the current definition catalog without reconciling it."""


class RuntimeConfigDraftPersistencePort(Protocol):
    """Atomically create one draft profile, its values, and revision evidence."""

    def create_draft(
        self,
        *,
        profile: RuntimeConfigProfile,
        values: tuple[RuntimeConfigValue, ...],
        revision: RuntimeConfigRevision,
    ) -> RuntimeConfigDraftCreateResult:
        """Insert or return the exact prior draft; never activate or snapshot it."""


class RuntimeConfigDraftService:
    """Prepare or persist draft profiles through existing Config Center records."""

    def __init__(
        self,
        definitions: RuntimeConfigDraftDefinitionPort,
        persistence: RuntimeConfigDraftPersistencePort,
    ) -> None:
        """Inject read-only definitions and the atomic draft persistence port."""

        self._definitions = definitions
        self._persistence = persistence

    def preview(self, request: RuntimeConfigDraftRequest) -> RuntimeConfigDraftPlan:
        """Validate and prepare a draft without writing profile or audit rows."""

        return self._prepare(request)

    def create(self, request: RuntimeConfigDraftRequest) -> RuntimeConfigDraftCreateResult:
        """Create one DRAFT profile; identical retries are idempotent."""

        plan = self._prepare(request)
        return self._persistence.create_draft(
            profile=plan.profile,
            values=plan.values,
            revision=plan.revision,
        )

    def _prepare(self, request: RuntimeConfigDraftRequest) -> RuntimeConfigDraftPlan:
        """Build deterministic identities and validate only registered value types."""

        if type(request) is not RuntimeConfigDraftRequest:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "draft request must be RuntimeConfigDraftRequest"
            )
        _require_token(request.profile_key, "profile_key")
        _require_token(request.environment, "environment")
        _require_text(request.actor, "actor")
        _require_text(request.reason, "reason")
        if len(request.profile_key) > 120 or len(request.environment) > 40:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "profile_key or environment exceeds storage limits"
            )
        if len(request.actor) > 150:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "actor exceeds the Config Center storage limit"
            )
        if type(request.release_ref) is not str or (
            request.release_ref and request.release_ref.strip() != request.release_ref
        ):
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "release_ref must already be trimmed"
            )
        if len(request.release_ref) > 100:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "release_ref exceeds the Config Center storage limit"
            )
        if type(request.version) is not int or request.version < 1:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_REQUEST_INVALID", "version must be a positive exact integer"
            )
        if type(request.values) is not tuple or not request.values:
            raise RuntimeConfigDraftValidationError(
                "DRAFT_VALUES_REQUIRED", "at least one typed draft value is required"
            )
        if any(type(item) is not RuntimeConfigDraftValueInput for item in request.values):
            raise RuntimeConfigDraftValidationError(
                "DRAFT_VALUE_INVALID", "values must contain RuntimeConfigDraftValueInput"
            )

        for item in request.values:
            _require_token(item.definition_key, "definition_key")
            _require_token(item.source, "source")
            if len(item.definition_key) > 180 or len(item.source) > 40:
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_VALUE_INVALID", "definition_key or source exceeds storage limits"
                )
            if type(item.secret_ref) is not str or (
                item.secret_ref and item.secret_ref.strip() != item.secret_ref
            ):
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_VALUE_INVALID", "secret_ref must already be trimmed"
                )
            if len(item.secret_ref) > 300:
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_VALUE_INVALID", "secret_ref exceeds the Config Center storage limit"
                )
        ordered_inputs = tuple(sorted(request.values, key=lambda item: item.definition_key))
        definitions = {item.key: item for item in self._definitions.list_all()}
        seen: set[str] = set()
        for item in ordered_inputs:
            if item.definition_key in seen:
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_DUPLICATE_DEFINITION", "draft values contain duplicate definition keys"
                )
            seen.add(item.definition_key)
            definition = definitions.get(item.definition_key)
            if definition is None:
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_DEFINITION_UNKNOWN",
                    f"registered definition is unavailable: {item.definition_key}",
                )
            _validate_json_value(item.value_json)
            try:
                definition.validate(item.value_json, secret_ref=item.secret_ref)
            except (TypeError, ValueError) as exc:
                raise RuntimeConfigDraftValidationError(
                    "DRAFT_VALUE_INVALID",
                    f"draft value failed generic Config Center validation: {item.definition_key}",
                ) from exc

        now = datetime.now(UTC)
        identity = (
            f"config-center-runtime-draft:{request.environment}:"
            f"{request.profile_key}:{request.version}"
        )
        profile_id = str(uuid5(NAMESPACE_URL, identity))
        resolved: dict[str, object] = {
            item.definition_key: item.secret_ref if item.secret_ref else item.value_json
            for item in ordered_inputs
        }
        content_hash = hash_runtime_profile_values(resolved)
        profile = RuntimeConfigProfile(
            profile_id=profile_id,
            profile_key=request.profile_key,
            environment=request.environment,
            version=request.version,
            status=RuntimeProfileStatus.DRAFT,
            based_on_profile="",
            content_hash=content_hash,
            created_by=request.actor,
            activated_by="",
            created_at=now,
            activated_at=None,
            change_reason=request.reason,
            release_ref=request.release_ref,
        )
        values = tuple(
            RuntimeConfigValue(
                profile_id=profile_id,
                definition_key=item.definition_key,
                value_json=item.value_json,
                secret_ref=item.secret_ref,
                source=item.source,
                validation_status="valid",
                validation_error="",
            )
            for item in ordered_inputs
        )
        public_projection = project_public_runtime_values(resolved, definitions)
        revision = RuntimeConfigRevision(
            revision_id=str(uuid5(UUID(profile_id), f"draft-revision:{content_hash}")),
            profile_id=profile_id,
            before_hash="",
            after_hash=content_hash,
            changed_keys=tuple(sorted(resolved)),
            before_projection={},
            after_projection=public_projection,
            actor=request.actor,
            reason=request.reason,
            changed_at=now,
            release_ref=request.release_ref,
            validation_evidence={
                "draft_only": True,
                "generic_definition_validation": "passed",
                "consumer_schema_validation": "not_performed",
                "snapshot_created": False,
                "active_pointer_changed": False,
            },
        )
        return RuntimeConfigDraftPlan(profile=profile, values=values, revision=revision)


def _require_token(value: str, name: str) -> None:
    """Require an exact, non-empty token without silently normalizing input."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or any(character.isspace() for character in value)
    ):
        raise RuntimeConfigDraftValidationError(
            "DRAFT_REQUEST_INVALID", f"{name} must be a canonical non-empty token"
        )


def _require_text(value: str, name: str) -> None:
    """Require non-empty, trimmed audit text."""

    if type(value) is not str or not value or value.strip() != value:
        raise RuntimeConfigDraftValidationError(
            "DRAFT_REQUEST_INVALID", f"{name} must be non-empty and already trimmed"
        )


def _validate_json_value(value: object) -> None:
    """Reject non-JSON values before hashing or passing values to JSONField."""

    if value is None or type(value) in {str, bool, int}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise RuntimeConfigDraftValidationError(
                "DRAFT_VALUE_NOT_JSON", "draft JSON cannot contain NaN or Infinity"
            )
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise RuntimeConfigDraftValidationError(
                "DRAFT_VALUE_NOT_JSON", "draft JSON object keys must be strings"
            )
        for item in value.values():
            _validate_json_value(item)
        return
    raise RuntimeConfigDraftValidationError(
        "DRAFT_VALUE_NOT_JSON", "draft value contains a non-JSON object"
    )


__all__ = [
    "RuntimeConfigDraftConflictError",
    "RuntimeConfigDraftCreateResult",
    "RuntimeConfigDraftDefinitionPort",
    "RuntimeConfigDraftPersistencePort",
    "RuntimeConfigDraftPlan",
    "RuntimeConfigDraftRequest",
    "RuntimeConfigDraftService",
    "RuntimeConfigDraftValidationError",
    "RuntimeConfigDraftValueInput",
]
