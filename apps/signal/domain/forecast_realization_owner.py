"""Immutable Signal-owner contracts for R7 forecast realizations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from re import fullmatch

from apps.signal.domain.forecast_scenario_evidence import ScenarioForecastBinding

_MEMBER_SOURCE_VERSION = "signal-r7-realization-member-source.v1"
_OUTCOME_SOURCE_VERSION = "signal-r7-forecast-outcome-source.v1"
_RECEIPT_VERSION = "signal-r7-realization-receipt.v1"
_MANIFEST_SOURCE_VERSION = "signal-r7-realization-manifest-source.v1"
_MANIFEST_VERSION = "signal-r7-realization-manifest.v1"
_OWNER = "signal.forecast_ledger"


def _hash_components(*components: str) -> str:
    """Return an unambiguous digest for ordered UTF-8 components."""

    digest = sha256()
    for component in components:
        encoded = component.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, byteorder="big", signed=False))
        digest.update(encoded)
    return digest.hexdigest()


def _require_token(value: str, field_name: str, *, maximum: int = 300) -> None:
    """Require one bounded identifier without whitespace or controls."""

    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(character.isspace() for character in value)
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError(f"{field_name} must be a bounded token")


def _require_sha256(value: str, field_name: str) -> None:
    """Require one lowercase SHA-256 digest."""

    if not isinstance(value, str) or fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    """Require a timezone-aware datetime."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _utc_text(value: datetime) -> str:
    _require_aware(value, "hash datetime")
    return value.astimezone(UTC).isoformat()


def _binding_components(binding: ScenarioForecastBinding) -> tuple[str, ...]:
    return (
        str(binding.scenario_revision_id),
        str(binding.scenario_set_revision_id or ""),
        str(binding.subjective_probability),
        binding.subjective_probability_source_version,
        str(binding.model_probability if binding.model_probability is not None else ""),
        str(binding.model_probability_source_version or ""),
        str(binding.model_promotion_decision_id or ""),
    )


def _validated_binding(binding: ScenarioForecastBinding) -> ScenarioForecastBinding:
    """Reject nominal substitutions and rebuild one exact scenario binding."""

    if type(binding) is not ScenarioForecastBinding:
        raise TypeError("scenario binding must use the exact Domain type")
    ScenarioForecastBinding.__post_init__(binding)
    return ScenarioForecastBinding(
        scenario_revision_id=binding.scenario_revision_id,
        scenario_set_revision_id=binding.scenario_set_revision_id,
        subjective_probability=binding.subjective_probability,
        subjective_probability_source_version=(binding.subjective_probability_source_version),
        model_probability=binding.model_probability,
        model_probability_source_version=binding.model_probability_source_version,
        model_promotion_decision_id=binding.model_promotion_decision_id,
    )


@dataclass(frozen=True)
class ForecastRealizationMemberSource:
    """Outcome-free metadata selecting one exact immutable ForecastOutcome."""

    source_version: str
    entry_id: str
    observation_id: str
    observation_version: str
    expected_observation_hash: str
    forecast_group_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    censoring_rule_version: str
    outcome_evidence_valid_until: datetime
    available_at: datetime
    evidence_ref: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        observation_id: str,
        observation_version: str,
        expected_observation_hash: str,
        forecast_group_id: str,
        pit_manifest_version: str,
        pit_manifest_hash: str,
        censoring_rule_version: str,
        outcome_evidence_valid_until: datetime,
        available_at: datetime,
        evidence_ref: str,
    ) -> ForecastRealizationMemberSource:
        """Seal metadata only; no outcome value is accepted at this boundary."""

        values = (
            _MEMBER_SOURCE_VERSION,
            entry_id,
            observation_id,
            observation_version,
            expected_observation_hash.lower(),
            forecast_group_id,
            pit_manifest_version,
            pit_manifest_hash.lower(),
            censoring_rule_version,
            outcome_evidence_valid_until,
            available_at,
            evidence_ref,
        )
        return cls(*values, _member_source_hash(*values))

    def __post_init__(self) -> None:
        if self.source_version != _MEMBER_SOURCE_VERSION:
            raise ValueError("realization member source version is unsupported")
        for name in (
            "entry_id",
            "observation_id",
            "observation_version",
            "forecast_group_id",
            "pit_manifest_version",
            "censoring_rule_version",
            "evidence_ref",
        ):
            _require_token(str(getattr(self, name)), f"member source {name}")
        if self.observation_id != self.entry_id:
            raise ValueError("member source observation identity is aliased")
        _require_sha256(
            self.expected_observation_hash,
            "member source expected_observation_hash",
        )
        _require_sha256(self.pit_manifest_hash, "member source pit_manifest_hash")
        _require_sha256(self.content_hash, "member source content_hash")
        _require_aware(
            self.outcome_evidence_valid_until,
            "member source outcome_evidence_valid_until",
        )
        _require_aware(self.available_at, "member source available_at")
        if self.available_at >= self.outcome_evidence_valid_until:
            raise ValueError("member source evidence is already expired")
        if self.content_hash != _member_source_hash(
            self.source_version,
            self.entry_id,
            self.observation_id,
            self.observation_version,
            self.expected_observation_hash,
            self.forecast_group_id,
            self.pit_manifest_version,
            self.pit_manifest_hash,
            self.censoring_rule_version,
            self.outcome_evidence_valid_until,
            self.available_at,
            self.evidence_ref,
        ):
            raise ValueError("realization member source content hash mismatch")


def _member_source_hash(
    source_version: str,
    entry_id: str,
    observation_id: str,
    observation_version: str,
    expected_observation_hash: str,
    forecast_group_id: str,
    pit_manifest_version: str,
    pit_manifest_hash: str,
    censoring_rule_version: str,
    outcome_evidence_valid_until: datetime,
    available_at: datetime,
    evidence_ref: str,
) -> str:
    return _hash_components(
        source_version,
        entry_id,
        observation_id,
        observation_version,
        expected_observation_hash.lower(),
        forecast_group_id,
        pit_manifest_version,
        pit_manifest_hash.lower(),
        censoring_rule_version,
        _utc_text(outcome_evidence_valid_until),
        _utc_text(available_at),
        evidence_ref,
    )


@dataclass(frozen=True)
class ForecastOutcomeOwnerRecord:
    """Exact projection of an existing immutable Signal forecast outcome row."""

    source_version: str
    entry_id: str
    binding: ScenarioForecastBinding
    pit_manifest_id: str
    published_at: datetime
    horizon_end: datetime
    scenario_realized: bool
    outcome_recorded_at: datetime
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        binding: ScenarioForecastBinding,
        pit_manifest_id: str,
        published_at: datetime,
        horizon_end: datetime,
        scenario_realized: bool,
        outcome_recorded_at: datetime,
    ) -> ForecastOutcomeOwnerRecord:
        """Seal only fields reread from ForecastLedgerEntry and ForecastOutcome."""

        values = (
            _OUTCOME_SOURCE_VERSION,
            entry_id,
            binding,
            pit_manifest_id,
            published_at,
            horizon_end,
            scenario_realized,
            outcome_recorded_at,
        )
        return cls(*values, _outcome_source_hash(*values))

    def __post_init__(self) -> None:
        if self.source_version != _OUTCOME_SOURCE_VERSION:
            raise ValueError("forecast outcome source version is unsupported")
        _require_token(self.entry_id, "forecast outcome entry_id")
        _validated_binding(self.binding)
        _require_token(self.pit_manifest_id, "forecast outcome pit_manifest_id")
        _require_aware(self.published_at, "forecast outcome published_at")
        _require_aware(self.horizon_end, "forecast outcome horizon_end")
        _require_aware(self.outcome_recorded_at, "forecast outcome outcome_recorded_at")
        if type(self.scenario_realized) is not bool:
            raise TypeError("forecast outcome scenario_realized must be an exact bool")
        if not self.published_at < self.horizon_end <= self.outcome_recorded_at:
            raise ValueError("forecast outcome clocks are invalid")
        _require_sha256(self.content_hash, "forecast outcome content_hash")
        if self.content_hash != _outcome_source_hash(
            self.source_version,
            self.entry_id,
            self.binding,
            self.pit_manifest_id,
            self.published_at,
            self.horizon_end,
            self.scenario_realized,
            self.outcome_recorded_at,
        ):
            raise ValueError("forecast outcome source content hash mismatch")


def _outcome_source_hash(
    source_version: str,
    entry_id: str,
    binding: ScenarioForecastBinding,
    pit_manifest_id: str,
    published_at: datetime,
    horizon_end: datetime,
    scenario_realized: bool,
    outcome_recorded_at: datetime,
) -> str:
    return _hash_components(
        source_version,
        entry_id,
        *_binding_components(binding),
        pit_manifest_id,
        _utc_text(published_at),
        _utc_text(horizon_end),
        "true" if scenario_realized else "false",
        _utc_text(outcome_recorded_at),
    )


@dataclass(frozen=True)
class ForecastRealizationManifestSource:
    """Canonical outcome-free period membership supplied to the Signal owner."""

    source_version: str
    owner_record_id: str
    owner_record_version: str
    result_id: str
    result_version: str
    result_hash: str
    calendar_id: str
    calendar_version: str
    period_id: str
    period_version: str
    period_hash: str
    period_start: datetime
    period_end: datetime
    available_at: datetime
    valid_until: datetime
    evidence_ref: str
    members: tuple[ForecastRealizationMemberSource, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        owner_record_id: str,
        owner_record_version: str,
        result_id: str,
        result_version: str,
        result_hash: str,
        calendar_id: str,
        calendar_version: str,
        period_id: str,
        period_version: str,
        period_hash: str,
        period_start: datetime,
        period_end: datetime,
        available_at: datetime,
        valid_until: datetime,
        evidence_ref: str,
        members: tuple[ForecastRealizationMemberSource, ...],
    ) -> ForecastRealizationManifestSource:
        """Seal exact membership metadata without accepting raw outcome values."""

        canonical = tuple(sorted(members, key=lambda item: item.entry_id))
        values = (
            _MANIFEST_SOURCE_VERSION,
            owner_record_id,
            owner_record_version,
            result_id,
            result_version,
            result_hash.lower(),
            calendar_id,
            calendar_version,
            period_id,
            period_version,
            period_hash.lower(),
            period_start,
            period_end,
            available_at,
            valid_until,
            evidence_ref,
            canonical,
        )
        return cls(*values, _manifest_source_hash(*values))

    def __post_init__(self) -> None:
        if self.source_version != _MANIFEST_SOURCE_VERSION:
            raise ValueError("realization manifest source version is unsupported")
        for name in (
            "owner_record_id",
            "owner_record_version",
            "result_id",
            "result_version",
            "calendar_id",
            "calendar_version",
            "period_id",
            "period_version",
            "evidence_ref",
        ):
            _require_token(str(getattr(self, name)), f"manifest source {name}")
        for name in ("result_hash", "period_hash", "content_hash"):
            _require_sha256(str(getattr(self, name)), f"manifest source {name}")
        for name in (
            "period_start",
            "period_end",
            "available_at",
            "valid_until",
        ):
            _require_aware(getattr(self, name), f"manifest source {name}")
        if not self.period_start < self.period_end <= self.available_at < self.valid_until:
            raise ValueError("realization manifest source clocks are invalid")
        if type(self.members) is not tuple or not self.members:
            raise ValueError("realization manifest source requires complete membership")
        identities = tuple(item.entry_id for item in self.members)
        if identities != tuple(sorted(identities)) or len(identities) != len(set(identities)):
            raise ValueError("realization manifest membership is not canonical and unique")
        for member in self.members:
            if type(member) is not ForecastRealizationMemberSource:
                raise TypeError("realization manifest member source is invalid")
            ForecastRealizationMemberSource.__post_init__(member)
            if not (
                self.period_end <= member.available_at <= self.available_at
                and self.valid_until <= member.outcome_evidence_valid_until
            ):
                raise ValueError("realization member does not cover the manifest window")
        if self.content_hash != _manifest_source_hash(
            self.source_version,
            self.owner_record_id,
            self.owner_record_version,
            self.result_id,
            self.result_version,
            self.result_hash,
            self.calendar_id,
            self.calendar_version,
            self.period_id,
            self.period_version,
            self.period_hash,
            self.period_start,
            self.period_end,
            self.available_at,
            self.valid_until,
            self.evidence_ref,
            self.members,
        ):
            raise ValueError("realization manifest source content hash mismatch")


def _manifest_source_hash(
    source_version: str,
    owner_record_id: str,
    owner_record_version: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    calendar_id: str,
    calendar_version: str,
    period_id: str,
    period_version: str,
    period_hash: str,
    period_start: datetime,
    period_end: datetime,
    available_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
    members: tuple[ForecastRealizationMemberSource, ...],
) -> str:
    return _hash_components(
        source_version,
        owner_record_id,
        owner_record_version,
        result_id,
        result_version,
        result_hash.lower(),
        calendar_id,
        calendar_version,
        period_id,
        period_version,
        period_hash.lower(),
        _utc_text(period_start),
        _utc_text(period_end),
        _utc_text(available_at),
        _utc_text(valid_until),
        evidence_ref,
        *(member.content_hash for member in members),
    )


@dataclass(frozen=True)
class ForecastRealizationReceipt:
    """One owner receipt rebuilt from metadata plus an exact ForecastOutcome row."""

    receipt_id: str
    receipt_version: str
    observation_id: str
    observation_version: str
    observation_hash: str
    entry_id: str
    forecast_group_id: str
    binding: ScenarioForecastBinding
    pit_manifest_id: str
    pit_manifest_version: str
    pit_manifest_hash: str
    censoring_rule_version: str
    published_at: datetime
    horizon_end: datetime
    scenario_realized: bool
    outcome_recorded_at: datetime
    outcome_evidence_valid_until: datetime
    available_at: datetime
    recorded_at: datetime
    evidence_ref: str
    source_outcome_hash: str
    content_hash: str

    @classmethod
    def from_sources(
        cls,
        *,
        metadata: ForecastRealizationMemberSource,
        outcome: ForecastOutcomeOwnerRecord,
        recorded_at: datetime,
    ) -> ForecastRealizationReceipt:
        """Build a receipt without accepting a caller-supplied realization value."""

        if type(metadata) is not ForecastRealizationMemberSource:
            raise TypeError("realization metadata must use the exact Domain type")
        if type(outcome) is not ForecastOutcomeOwnerRecord:
            raise TypeError("forecast outcome must use the exact Domain type")
        ForecastRealizationMemberSource.__post_init__(metadata)
        ForecastOutcomeOwnerRecord.__post_init__(outcome)
        if metadata.entry_id != outcome.entry_id:
            raise ValueError("realization receipt source entry identity differs")
        observation_hash = forecast_observation_hash(metadata=metadata, outcome=outcome)
        if observation_hash != metadata.expected_observation_hash:
            raise ValueError("realization receipt differs from the expected observation hash")
        receipt_id = f"signal-r7-realization-receipt:{observation_hash[:24]}"
        values = (
            receipt_id,
            _RECEIPT_VERSION,
            metadata.observation_id,
            metadata.observation_version,
            observation_hash,
            outcome.entry_id,
            metadata.forecast_group_id,
            outcome.binding,
            outcome.pit_manifest_id,
            metadata.pit_manifest_version,
            metadata.pit_manifest_hash,
            metadata.censoring_rule_version,
            outcome.published_at,
            outcome.horizon_end,
            outcome.scenario_realized,
            outcome.outcome_recorded_at,
            metadata.outcome_evidence_valid_until,
            metadata.available_at,
            recorded_at,
            metadata.evidence_ref,
            outcome.content_hash,
        )
        return cls(*values, _receipt_hash(*values))

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "observation_id",
            "observation_version",
            "entry_id",
            "forecast_group_id",
            "pit_manifest_id",
            "pit_manifest_version",
            "censoring_rule_version",
            "evidence_ref",
        ):
            _require_token(str(getattr(self, name)), f"realization receipt {name}")
        if self.receipt_version != _RECEIPT_VERSION:
            raise ValueError("realization receipt version is unsupported")
        if self.observation_id != self.entry_id:
            raise ValueError("realization observation identity is aliased")
        _validated_binding(self.binding)
        for name in (
            "observation_hash",
            "pit_manifest_hash",
            "source_outcome_hash",
            "content_hash",
        ):
            _require_sha256(str(getattr(self, name)), f"realization receipt {name}")
        for name in (
            "published_at",
            "horizon_end",
            "outcome_recorded_at",
            "outcome_evidence_valid_until",
            "available_at",
            "recorded_at",
        ):
            _require_aware(getattr(self, name), f"realization receipt {name}")
        if type(self.scenario_realized) is not bool:
            raise TypeError("realization receipt outcome must be an exact bool")
        if not (
            self.published_at
            < self.horizon_end
            <= self.outcome_recorded_at
            <= self.available_at
            <= self.recorded_at
            < self.outcome_evidence_valid_until
        ):
            raise ValueError("realization receipt clocks are invalid")
        if self.content_hash != realization_receipt_hash(self):
            raise ValueError("realization receipt content hash mismatch")


def forecast_observation_hash(
    *,
    metadata: ForecastRealizationMemberSource,
    outcome: ForecastOutcomeOwnerRecord,
) -> str:
    """Compute the exact Research observation seal without importing Research."""

    return forecast_observation_hash_from_values(
        observation_version=metadata.observation_version,
        observation_id=metadata.observation_id,
        entry_id=outcome.entry_id,
        forecast_group_id=metadata.forecast_group_id,
        binding=outcome.binding,
        pit_manifest_id=outcome.pit_manifest_id,
        pit_manifest_version=metadata.pit_manifest_version,
        pit_manifest_hash=metadata.pit_manifest_hash,
        censoring_rule_version=metadata.censoring_rule_version,
        published_at=outcome.published_at,
        horizon_end=outcome.horizon_end,
        scenario_realized=outcome.scenario_realized,
        outcome_recorded_at=outcome.outcome_recorded_at,
        outcome_evidence_valid_until=metadata.outcome_evidence_valid_until,
    )


def forecast_observation_hash_from_values(
    *,
    observation_version: str,
    observation_id: str,
    entry_id: str,
    forecast_group_id: str,
    binding: ScenarioForecastBinding,
    pit_manifest_id: str,
    pit_manifest_version: str,
    pit_manifest_hash: str,
    censoring_rule_version: str,
    published_at: datetime,
    horizon_end: datetime,
    scenario_realized: bool,
    outcome_recorded_at: datetime,
    outcome_evidence_valid_until: datetime,
) -> str:
    """Compute the canonical Research observation hash from complete exact values."""

    if observation_id != entry_id:
        raise ValueError("forecast observation identity is aliased")
    return _hash_components(
        observation_version,
        observation_id,
        forecast_group_id,
        *_binding_components(binding),
        pit_manifest_id,
        pit_manifest_version,
        pit_manifest_hash,
        censoring_rule_version,
        published_at.isoformat(),
        horizon_end.isoformat(),
        str(scenario_realized),
        outcome_recorded_at.isoformat(),
        outcome_evidence_valid_until.isoformat(),
        "",
    )


def realization_receipt_hash(value: ForecastRealizationReceipt) -> str:
    """Recompute the complete realization receipt seal."""

    return _receipt_hash(
        value.receipt_id,
        value.receipt_version,
        value.observation_id,
        value.observation_version,
        value.observation_hash,
        value.entry_id,
        value.forecast_group_id,
        value.binding,
        value.pit_manifest_id,
        value.pit_manifest_version,
        value.pit_manifest_hash,
        value.censoring_rule_version,
        value.published_at,
        value.horizon_end,
        value.scenario_realized,
        value.outcome_recorded_at,
        value.outcome_evidence_valid_until,
        value.available_at,
        value.recorded_at,
        value.evidence_ref,
        value.source_outcome_hash,
    )


def _receipt_hash(
    receipt_id: str,
    receipt_version: str,
    observation_id: str,
    observation_version: str,
    observation_hash: str,
    entry_id: str,
    forecast_group_id: str,
    binding: ScenarioForecastBinding,
    pit_manifest_id: str,
    pit_manifest_version: str,
    pit_manifest_hash: str,
    censoring_rule_version: str,
    published_at: datetime,
    horizon_end: datetime,
    scenario_realized: bool,
    outcome_recorded_at: datetime,
    outcome_evidence_valid_until: datetime,
    available_at: datetime,
    recorded_at: datetime,
    evidence_ref: str,
    source_outcome_hash: str,
) -> str:
    return _hash_components(
        receipt_version,
        receipt_id,
        observation_id,
        observation_version,
        observation_hash,
        entry_id,
        forecast_group_id,
        *_binding_components(binding),
        pit_manifest_id,
        pit_manifest_version,
        pit_manifest_hash.lower(),
        censoring_rule_version,
        _utc_text(published_at),
        _utc_text(horizon_end),
        "true" if scenario_realized else "false",
        _utc_text(outcome_recorded_at),
        _utc_text(outcome_evidence_valid_until),
        _utc_text(available_at),
        _utc_text(recorded_at),
        evidence_ref,
        source_outcome_hash.lower(),
    )


@dataclass(frozen=True)
class ForecastRealizationManifest:
    """Signal-owned, append-only, period-complete realization manifest."""

    manifest_version: str
    owner: str
    owner_record_id: str
    owner_record_version: str
    result_id: str
    result_version: str
    result_hash: str
    calendar_id: str
    calendar_version: str
    period_id: str
    period_version: str
    period_hash: str
    period_start: datetime
    period_end: datetime
    pit_as_of: datetime
    available_at: datetime
    recorded_at: datetime
    valid_until: datetime
    evidence_ref: str
    source_manifest_hash: str
    members: tuple[ForecastRealizationReceipt, ...]
    payload_hash: str
    content_hash: str
    research_only: bool
    must_not_use_for_decision: bool
    must_not_execute: bool

    @classmethod
    def from_sources(
        cls,
        *,
        source: ForecastRealizationManifestSource,
        outcomes: tuple[ForecastOutcomeOwnerRecord, ...],
        recorded_at: datetime,
    ) -> ForecastRealizationManifest:
        """Reread exact outcomes and seal them under one owner manifest."""

        if type(source) is not ForecastRealizationManifestSource:
            raise TypeError("realization manifest source must use the exact Domain type")
        ForecastRealizationManifestSource.__post_init__(source)
        if type(outcomes) is not tuple:
            raise TypeError("realization outcomes must be an exact tuple")
        for outcome in outcomes:
            if type(outcome) is not ForecastOutcomeOwnerRecord:
                raise TypeError("realization outcome must use the exact Domain type")
            ForecastOutcomeOwnerRecord.__post_init__(outcome)
        by_entry = {item.entry_id: item for item in outcomes}
        if len(by_entry) != len(outcomes) or tuple(sorted(by_entry)) != tuple(
            item.entry_id for item in source.members
        ):
            raise ValueError("realization outcome membership differs from the source manifest")
        members = tuple(
            ForecastRealizationReceipt.from_sources(
                metadata=metadata,
                outcome=by_entry[metadata.entry_id],
                recorded_at=recorded_at,
            )
            for metadata in source.members
        )
        payload_hash = _hash_components(
            "signal-r7-realization-manifest-payload.v1",
            source.period_hash,
            *(member.content_hash for member in members),
        )
        values = (
            _MANIFEST_VERSION,
            _OWNER,
            source.owner_record_id,
            source.owner_record_version,
            source.result_id,
            source.result_version,
            source.result_hash,
            source.calendar_id,
            source.calendar_version,
            source.period_id,
            source.period_version,
            source.period_hash,
            source.period_start,
            source.period_end,
            recorded_at,
            source.available_at,
            recorded_at,
            source.valid_until,
            source.evidence_ref,
            source.content_hash,
            members,
            payload_hash,
            True,
            True,
            True,
        )
        return cls(*values[:-3], _manifest_hash(*values), *values[-3:])

    def __post_init__(self) -> None:
        if self.manifest_version != _MANIFEST_VERSION or self.owner != _OWNER:
            raise ValueError("realization manifest owner or version is invalid")
        for name in (
            "owner_record_id",
            "owner_record_version",
            "result_id",
            "result_version",
            "calendar_id",
            "calendar_version",
            "period_id",
            "period_version",
            "evidence_ref",
        ):
            _require_token(str(getattr(self, name)), f"realization manifest {name}")
        for name in (
            "result_hash",
            "period_hash",
            "source_manifest_hash",
            "payload_hash",
            "content_hash",
        ):
            _require_sha256(str(getattr(self, name)), f"realization manifest {name}")
        for name in (
            "period_start",
            "period_end",
            "pit_as_of",
            "available_at",
            "recorded_at",
            "valid_until",
        ):
            _require_aware(getattr(self, name), f"realization manifest {name}")
        if not (
            self.period_start
            < self.period_end
            <= self.available_at
            <= self.recorded_at
            <= self.pit_as_of
            < self.valid_until
        ):
            raise ValueError("realization manifest clocks are invalid")
        if not (self.research_only and self.must_not_use_for_decision and self.must_not_execute):
            raise ValueError("realization manifest must remain research-only")
        identities = tuple(member.entry_id for member in self.members)
        if (
            not identities
            or identities != tuple(sorted(identities))
            or len(identities) != len(set(identities))
        ):
            raise ValueError("realization manifest receipts are not canonical and unique")
        for member in self.members:
            if type(member) is not ForecastRealizationReceipt:
                raise TypeError("realization manifest receipt type is invalid")
            ForecastRealizationReceipt.__post_init__(member)
            if member.horizon_end != self.period_end:
                raise ValueError("realization receipt horizon differs from manifest period")
            if member.recorded_at != self.recorded_at or member.available_at > self.available_at:
                raise ValueError("realization receipt clocks differ from its manifest")
            if self.valid_until > member.outcome_evidence_valid_until:
                raise ValueError("realization manifest outlives one outcome receipt")
        expected_payload = _hash_components(
            "signal-r7-realization-manifest-payload.v1",
            self.period_hash,
            *(member.content_hash for member in self.members),
        )
        if self.payload_hash != expected_payload:
            raise ValueError("realization manifest payload hash mismatch")
        if self.content_hash != realization_manifest_hash(self):
            raise ValueError("realization manifest content hash mismatch")

    def validated_copy(self) -> ForecastRealizationManifest:
        """Return a fully revalidated immutable copy."""

        if type(self) is not ForecastRealizationManifest:
            raise TypeError("realization manifest must use the exact Domain type")
        ForecastRealizationManifest.__post_init__(self)
        copied_members = tuple(
            ForecastRealizationReceipt(
                receipt_id=member.receipt_id,
                receipt_version=member.receipt_version,
                observation_id=member.observation_id,
                observation_version=member.observation_version,
                observation_hash=member.observation_hash,
                entry_id=member.entry_id,
                forecast_group_id=member.forecast_group_id,
                binding=_validated_binding(member.binding),
                pit_manifest_id=member.pit_manifest_id,
                pit_manifest_version=member.pit_manifest_version,
                pit_manifest_hash=member.pit_manifest_hash,
                censoring_rule_version=member.censoring_rule_version,
                published_at=member.published_at,
                horizon_end=member.horizon_end,
                scenario_realized=member.scenario_realized,
                outcome_recorded_at=member.outcome_recorded_at,
                outcome_evidence_valid_until=member.outcome_evidence_valid_until,
                available_at=member.available_at,
                recorded_at=member.recorded_at,
                evidence_ref=member.evidence_ref,
                source_outcome_hash=member.source_outcome_hash,
                content_hash=member.content_hash,
            )
            for member in self.members
        )
        return ForecastRealizationManifest(
            manifest_version=self.manifest_version,
            owner=self.owner,
            owner_record_id=self.owner_record_id,
            owner_record_version=self.owner_record_version,
            result_id=self.result_id,
            result_version=self.result_version,
            result_hash=self.result_hash,
            calendar_id=self.calendar_id,
            calendar_version=self.calendar_version,
            period_id=self.period_id,
            period_version=self.period_version,
            period_hash=self.period_hash,
            period_start=self.period_start,
            period_end=self.period_end,
            pit_as_of=self.pit_as_of,
            available_at=self.available_at,
            recorded_at=self.recorded_at,
            valid_until=self.valid_until,
            evidence_ref=self.evidence_ref,
            source_manifest_hash=self.source_manifest_hash,
            members=copied_members,
            payload_hash=self.payload_hash,
            content_hash=self.content_hash,
            research_only=self.research_only,
            must_not_use_for_decision=self.must_not_use_for_decision,
            must_not_execute=self.must_not_execute,
        )


def realization_manifest_hash(value: ForecastRealizationManifest) -> str:
    """Recompute the complete Signal owner manifest seal."""

    return _manifest_hash(
        value.manifest_version,
        value.owner,
        value.owner_record_id,
        value.owner_record_version,
        value.result_id,
        value.result_version,
        value.result_hash,
        value.calendar_id,
        value.calendar_version,
        value.period_id,
        value.period_version,
        value.period_hash,
        value.period_start,
        value.period_end,
        value.pit_as_of,
        value.available_at,
        value.recorded_at,
        value.valid_until,
        value.evidence_ref,
        value.source_manifest_hash,
        value.members,
        value.payload_hash,
        value.research_only,
        value.must_not_use_for_decision,
        value.must_not_execute,
    )


def _manifest_hash(
    manifest_version: str,
    owner: str,
    owner_record_id: str,
    owner_record_version: str,
    result_id: str,
    result_version: str,
    result_hash: str,
    calendar_id: str,
    calendar_version: str,
    period_id: str,
    period_version: str,
    period_hash: str,
    period_start: datetime,
    period_end: datetime,
    pit_as_of: datetime,
    available_at: datetime,
    recorded_at: datetime,
    valid_until: datetime,
    evidence_ref: str,
    source_manifest_hash: str,
    members: tuple[ForecastRealizationReceipt, ...],
    payload_hash: str,
    research_only: bool,
    must_not_use_for_decision: bool,
    must_not_execute: bool,
) -> str:
    return _hash_components(
        manifest_version,
        owner,
        owner_record_id,
        owner_record_version,
        result_id,
        result_version,
        result_hash.lower(),
        calendar_id,
        calendar_version,
        period_id,
        period_version,
        period_hash.lower(),
        _utc_text(period_start),
        _utc_text(period_end),
        _utc_text(pit_as_of),
        _utc_text(available_at),
        _utc_text(recorded_at),
        _utc_text(valid_until),
        evidence_ref,
        source_manifest_hash.lower(),
        *(member.content_hash for member in members),
        payload_hash.lower(),
        "true" if research_only else "false",
        "true" if must_not_use_for_decision else "false",
        "true" if must_not_execute else "false",
    )


__all__ = [
    "ForecastOutcomeOwnerRecord",
    "ForecastRealizationManifest",
    "ForecastRealizationManifestSource",
    "ForecastRealizationMemberSource",
    "ForecastRealizationReceipt",
    "forecast_observation_hash",
    "forecast_observation_hash_from_values",
    "realization_manifest_hash",
    "realization_receipt_hash",
]
