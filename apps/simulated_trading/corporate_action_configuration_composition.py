"""Freeze actual Config Center provenance for explicit company-action model readers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime

from django.utils import timezone

from apps.simulated_trading.application.corporate_action_official_window_evidence import (
    _is_aware,
    _is_sha256,
    _is_token,
)
from core.exceptions import AgomTradeProException, BusinessLogicError
from core.integration.config_center_runtime import (
    ActiveRuntimeValueEvidence,
    RuntimeConfigProfileRead,
    RuntimeConfigSnapshotRead,
    get_active_runtime_profile,
    get_active_runtime_value_evidence,
    get_latest_runtime_snapshot,
)


@dataclass(frozen=True, slots=True)
class CorporateActionConfigurationEvidence:
    """Immutable resolved JSON and original provenance; no source or financial qualification."""

    definition_key: str
    environment: str
    value_json: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_sha256: str
    profile_created_at: datetime
    profile_activated_at: datetime
    snapshot_id: str
    snapshot_sha256: str
    snapshot_generated_at: datetime
    effective_at: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Require explicit finite clock ordering and authentic immutable snapshot identities."""
        for value in (
            self.definition_key,
            self.environment,
            self.profile_id,
            self.profile_key,
            self.snapshot_id,
        ):
            if not _is_token(value):
                raise ValueError("configuration identity is invalid")
        if (
            type(self.profile_version) is not int
            or self.profile_version <= 0
            or not _is_sha256(self.profile_content_sha256)
            or not _is_sha256(self.snapshot_sha256)
            or type(self.value_json) is not str
            or not self.value_json
            or len(self.value_json.encode()) > 1_048_576
        ):
            raise ValueError("configuration payload or hashes are invalid")
        clocks = (
            self.profile_created_at,
            self.profile_activated_at,
            self.snapshot_generated_at,
            self.effective_at,
            self.checked_at,
        )
        if (
            not all(_is_aware(value) for value in clocks)
            or self.profile_activated_at != self.effective_at
            or not self.profile_created_at
            <= self.profile_activated_at
            <= self.snapshot_generated_at
            <= self.checked_at
        ):
            raise ValueError("configuration clocks are invalid")

    @property
    def known_at(self) -> datetime:
        """Return original resolved-snapshot availability, preserving its creation clock separately."""
        return self.snapshot_generated_at

    @property
    def identity_sha256(self) -> str:
        """Bind every immutable field while excluding only this read's current check time."""
        self.__post_init__()
        fields = asdict(self)
        del fields["checked_at"]
        return hashlib.sha256(
            json.dumps(
                fields, sort_keys=True, separators=(",", ":"), default=_original_clock_json
            ).encode()
        ).hexdigest()


def _original_clock_json(value: object) -> str:
    if type(value) is not datetime:
        raise TypeError("unsupported configuration field")
    return value.isoformat()


def _blocked() -> BusinessLogicError:
    return BusinessLogicError(
        "当前显式模型配置无法核对，请联系管理员检查已启用的配置版本。",
        code="CORPORATE_ACTION_MODEL_CONFIGURATION_UNAVAILABLE",
    )


def read_corporate_action_configuration(
    *,
    definition_key: str,
    environment: str,
    as_of: datetime,
) -> CorporateActionConfigurationEvidence:
    """Reuse the owner's repeated current read and verify the actual full snapshot hash."""
    try:
        started = timezone.now()
        if not _is_aware(as_of) or not _is_aware(started) or as_of > started:
            raise _blocked()
        evidence = get_active_runtime_value_evidence(
            environment=environment, definition_key=definition_key, as_of=as_of
        )
        if type(evidence) is not ActiveRuntimeValueEvidence:
            raise _blocked()
        snapshot = get_latest_runtime_snapshot(evidence.profile_key)
        if not isinstance(snapshot, RuntimeConfigSnapshotRead):
            raise _blocked()
        snapshot.__post_init__()
        if (
            (
                snapshot.profile_id,
                snapshot.profile_key,
                snapshot.profile_version,
                snapshot.snapshot_id,
                snapshot.snapshot_hash,
                snapshot.effective_from,
                snapshot.generated_at,
            )
            != (
                evidence.profile_id,
                evidence.profile_key,
                evidence.profile_version,
                evidence.snapshot_id,
                evidence.snapshot_hash,
                evidence.effective_at,
                evidence.snapshot_generated_at,
            )
            or evidence.environment != environment
            or evidence.definition_key != definition_key
            or evidence.as_of != as_of
            or snapshot.resolved_values.get(definition_key) != evidence.value
        ):
            raise _blocked()
        canonical = json.dumps(
            dict(snapshot.resolved_values),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if hashlib.sha256(canonical.encode()).hexdigest() != evidence.snapshot_hash:
            raise _blocked()
        final_profile = get_active_runtime_profile(environment)
        if not isinstance(final_profile, RuntimeConfigProfileRead):
            raise _blocked()
        final_profile.__post_init__()
        if (
            (
                final_profile.profile_id,
                final_profile.profile_key,
                final_profile.version,
                final_profile.content_hash,
                final_profile.activated_at,
            )
            != (
                evidence.profile_id,
                evidence.profile_key,
                evidence.profile_version,
                evidence.profile_content_hash,
                evidence.activated_at,
            )
            or final_profile.environment != environment
            or final_profile.status != "active"
            or not evidence.created_at
            <= evidence.activated_at
            <= evidence.snapshot_generated_at
            <= as_of
        ):
            raise _blocked()
        checked = timezone.now()
        if checked < started:
            raise _blocked()
        return CorporateActionConfigurationEvidence(
            definition_key,
            environment,
            json.dumps(
                evidence.value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            evidence.profile_id,
            evidence.profile_key,
            evidence.profile_version,
            evidence.profile_content_hash,
            evidence.created_at,
            evidence.activated_at,
            evidence.snapshot_id,
            evidence.snapshot_hash,
            evidence.snapshot_generated_at,
            evidence.effective_at,
            checked,
        )
    except BusinessLogicError:
        raise
    except (
        AgomTradeProException,
        ArithmeticError,
        AttributeError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as error:
        raise _blocked() from error
