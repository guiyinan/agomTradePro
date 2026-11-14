"""Application contracts for a simulation-only corporate-action raw NAV mark."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol
from zoneinfo import ZoneInfo

from apps.data_center.application.published_price_source import PublishedPriceSourceEvidence
from apps.data_center.domain.market_time import (
    cn_market_session_close_utc,
    latest_closed_cn_market_session,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
)
from apps.simulated_trading.domain.execution_instrument_classification import (
    SimulatedInstrumentClassificationEvidenceV1,
)
from apps.simulated_trading.domain.execution_settlement_calendar import ExecutionCalendarEvidence

_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


class SimulatedCorporateActionNavRawMarkContractError(ValueError):
    """Raised when a current raw mark contract is malformed, stale, or unbound."""


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionNavRawMarkQuery:
    """Bind one raw mark request to the physical and canonical owner identities."""

    physical_account_id: int
    canonical_account_id: str
    owner_user_id: int
    security_id: str
    asset_code: str
    asset_type: str

    def __post_init__(self) -> None:
        """Validate exact account, owner, security, and server-selected asset scope."""

        self.validate()

    def validate(self) -> None:
        """Require positive exact database identities and canonical scope tokens."""

        if type(self.physical_account_id) is not int or self.physical_account_id <= 0:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "physical account identity is invalid"
            )
        if type(self.owner_user_id) is not int or self.owner_user_id <= 0:
            raise SimulatedCorporateActionNavRawMarkContractError("owner identity is invalid")
        for name in ("canonical_account_id", "security_id", "asset_code", "asset_type"):
            _require_token(getattr(self, name), name)


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionNavRawMarkPolicyBinding:
    """Retain one explicit policy with its selected runtime profile and snapshot."""

    policy: SimulatedCorporateActionNavRawMarkPolicy
    runtime_environment: str
    profile_id: str
    profile_key: str
    profile_version: int
    profile_content_sha256: str
    profile_activated_at: datetime
    snapshot_id: str
    snapshot_content_sha256: str
    snapshot_generated_at: datetime
    snapshot_effective_from: datetime
    known_at: datetime
    valid_from: datetime
    valid_until: datetime
    checked_at: datetime

    def __post_init__(self) -> None:
        """Validate typed policy provenance and its explicit finite interval."""

        if type(self.policy) is not SimulatedCorporateActionNavRawMarkPolicy:
            raise SimulatedCorporateActionNavRawMarkContractError("raw mark policy is invalid")
        self.policy.__post_init__()
        for name in (
            "runtime_environment",
            "profile_id",
            "profile_key",
            "snapshot_id",
        ):
            _require_token(getattr(self, name), name)
        for name in ("profile_content_sha256", "snapshot_content_sha256"):
            _require_hash(getattr(self, name), name)
        if type(self.profile_version) is not int or self.profile_version <= 0:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark profile version is invalid"
            )
        for name in (
            "profile_activated_at",
            "snapshot_generated_at",
            "snapshot_effective_from",
            "known_at",
            "valid_from",
            "valid_until",
            "checked_at",
        ):
            _require_clock(getattr(self, name), name)
        if self.profile_activated_at != self.snapshot_effective_from:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark profile and snapshot activation differ"
            )
        if not self.profile_activated_at <= self.snapshot_generated_at:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark snapshot predates profile activation"
            )
        if self.valid_from >= self.valid_until:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark policy validity interval is invalid"
            )

    def validate_for(self, *, as_of: datetime) -> None:
        """Require all original runtime clocks known by the checked cutoff."""

        self.__post_init__()
        _require_clock(as_of, "requested_as_of")
        if self.checked_at > as_of:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark policy check is later than its verification cutoff"
            )
        if self.valid_from > self.checked_at:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark policy is not effective at its checked time"
            )
        known_clocks = (
            self.profile_activated_at,
            self.snapshot_generated_at,
            self.snapshot_effective_from,
            self.known_at,
            self.valid_from,
        )
        if any(value > self.checked_at for value in known_clocks):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark policy contains a future provenance clock"
            )
        if not self.valid_from <= self.checked_at < self.valid_until:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark policy was outside its finite window when checked"
            )
        if as_of >= self.valid_until:
            raise SimulatedCorporateActionNavRawMarkContractError("raw mark policy has expired")

    def to_payload(self, *, include_checked_at: bool = True) -> dict[str, object]:
        """Return a canonical policy binding, optionally excluding its read clock."""

        self.__post_init__()
        payload: dict[str, object] = {
            "schema": "simulated-corporate-action-nav-raw-mark-policy-binding.v1",
            "policy": self.policy.to_payload(),
            "runtime_environment": self.runtime_environment,
            "profile_id": self.profile_id,
            "profile_key": self.profile_key,
            "profile_version": self.profile_version,
            "profile_content_sha256": self.profile_content_sha256,
            "profile_activated_at": _clock_text(self.profile_activated_at),
            "snapshot_id": self.snapshot_id,
            "snapshot_content_sha256": self.snapshot_content_sha256,
            "snapshot_generated_at": _clock_text(self.snapshot_generated_at),
            "snapshot_effective_from": _clock_text(self.snapshot_effective_from),
            "known_at": _clock_text(self.known_at),
            "valid_from": _clock_text(self.valid_from),
            "valid_until": _clock_text(self.valid_until),
        }
        if include_checked_at:
            payload["checked_at"] = _clock_text(self.checked_at)
        return payload

    @property
    def content_sha256(self) -> str:
        """Return a digest over policy provenance and the exact check clock."""

        return _canonical_sha256(self.to_payload())

    @property
    def selection_sha256(self) -> str:
        """Return a stable selection digest that can be compared across re-reads."""

        return _canonical_sha256(self.to_payload(include_checked_at=False))


@dataclass(frozen=True, slots=True)
class SimulatedCorporateActionNavRawMarkProof:
    """Seal one exact daily close while limiting its meaning to a raw price mark."""

    query: SimulatedCorporateActionNavRawMarkQuery
    policy_binding: SimulatedCorporateActionNavRawMarkPolicyBinding
    classification: SimulatedInstrumentClassificationEvidenceV1
    calendar: ExecutionCalendarEvidence
    source_evidence: PublishedPriceSourceEvidence
    trade_date: date
    interval_end_at: datetime
    reading_started_at: datetime
    checked_at: datetime
    valid_until: datetime
    freshness_status: Literal["current"] = "current"
    reliability_status: Literal["source_verified"] = "source_verified"
    scope_reason: Literal["raw_price_only"] = "raw_price_only"
    must_not_use_for_decision: Literal[True] = True

    def __post_init__(self) -> None:
        """Revalidate source, profile, owner, and raw-price scope evidence."""

        self.verify_for(self.query, as_of=self.checked_at)

    @property
    def price(self) -> Decimal:
        """Return the exact unadjusted close from the retained source evidence."""

        return self.source_evidence.values.close

    @property
    def source_observed_at(self) -> datetime | None:
        """Preserve the original unknown provider observation time without a fallback."""

        return self.source_evidence.source_observed_at

    @property
    def content_sha256(self) -> str:
        """Return a stable digest over owner scope and retained source references."""

        return _canonical_sha256(self.to_payload())

    def verify_for(
        self, query: SimulatedCorporateActionNavRawMarkQuery, *, as_of: datetime
    ) -> None:
        """Verify exact request binding and require every original clock before cutoff."""

        if type(query) is not SimulatedCorporateActionNavRawMarkQuery or query != self.query:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark owner or instrument request differs from its proof"
            )
        self.query.validate()
        for name in ("reading_started_at", "checked_at", "valid_until", "interval_end_at"):
            _require_clock(getattr(self, name), name)
        _require_clock(as_of, "requested_as_of")
        if not self.reading_started_at <= self.checked_at <= as_of:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark check clocks are reversed or later than the requested cutoff"
            )
        if type(self.freshness_status) is not str or self.freshness_status != "current":
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark freshness state is unsupported"
            )
        if type(self.reliability_status) is not str or self.reliability_status != "source_verified":
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source reliability state is unsupported"
            )
        if type(self.scope_reason) is not str or self.scope_reason != "raw_price_only":
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark scope must remain limited to a raw price"
            )
        if type(self.must_not_use_for_decision) is not bool or not self.must_not_use_for_decision:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark cannot be represented as decision evidence"
            )

        self.policy_binding.validate_for(as_of=as_of)
        self._verify_classification(as_of)
        self._verify_source_and_calendar(as_of)

    def _verify_classification(self, as_of: datetime) -> None:
        """Bind the policy profile and exact security to current classification."""

        if type(self.classification) is not SimulatedInstrumentClassificationEvidenceV1:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark classification evidence is invalid"
            )
        if self.classification.read_at > self.checked_at:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark classification was read after the mark check"
            )
        self.classification.validate_at(as_of=self.checked_at)
        identity = self.classification.identity_evidence.source_evidence
        selection = self.classification.identity_evidence.selection
        binding = self.policy_binding
        if (
            identity.security_id != self.query.security_id
            or identity.asset_code != self.query.asset_code
            or self.classification.simulated_asset_type != self.query.asset_type
            or self.query.asset_type not in binding.policy.supported_asset_types
            or selection.profile_id != binding.profile_id
            or selection.profile_key != binding.profile_key
            or selection.environment != binding.runtime_environment
            or selection.profile_version != binding.profile_version
            or selection.profile_content_hash != binding.profile_content_sha256
            or selection.runtime_snapshot_id != binding.snapshot_id
            or selection.runtime_snapshot_hash != binding.snapshot_content_sha256
            or selection.profile_activated_at != binding.profile_activated_at
            or selection.runtime_snapshot_generated_at != binding.snapshot_generated_at
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark classification differs from current policy or request scope"
            )

    def _verify_source_and_calendar(self, as_of: datetime) -> None:
        """Validate one exact unadjusted bar and its formal exchange calendar."""

        if type(self.calendar) is not ExecutionCalendarEvidence:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark execution calendar is invalid"
            )
        if type(self.source_evidence) is not PublishedPriceSourceEvidence:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark published source evidence is invalid"
            )
        self.calendar.validate_for(self.checked_at)
        publication = self.calendar.publication
        identity = self.classification.identity_evidence.source_evidence
        policy = self.policy_binding.policy
        evidence = self.source_evidence
        if (
            publication is None
            or publication.timezone_name != "Asia/Shanghai"
            or self.calendar.snapshot.exchange != identity.source_exchange
            or evidence.asset_code != self.query.asset_code
            or evidence.trade_date != self.trade_date
            or evidence.publication_key != policy.publication_key
            or evidence.source != policy.source
            or evidence.adjustment.value != "none"
            or evidence.observation_basis != "daily_interval_end"
            or policy.frequency != "1d"
            or policy.adjustment != "none"
            or policy.observation_basis != "daily_interval_end"
            or policy.currency != "CNY"
            or evidence.interval_end_at != self.interval_end_at
            or evidence.source_observed_at is not None
            or evidence.volume_unit != "shares"
            or evidence.amount_unit != "CNY"
            or evidence.availability_basis != "local_response_body_completion"
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark price source semantics differ from explicit policy"
            )
        evidence.values.__post_init__()
        payload_reference = evidence.raw_payload_reference
        audit_reference = evidence.raw_audit_reference
        capture_completed_at = payload_reference.response_completed_at
        _require_clock(capture_completed_at, "raw_payload_completed_at")
        if (
            capture_completed_at != evidence.local_known_at
            or payload_reference.provider_name != evidence.source
            or payload_reference.provider_name != audit_reference.provider_name
            or payload_reference.dataset_key != "equity.price.bar"
            or payload_reference.run_id != audit_reference.run_id
            or not payload_reference.original_body_retained
            or payload_reference.retained_content_encoding != "exact_original_utf8_json"
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark retained price capture does not match its verified source reference"
            )
        _require_clock(self.interval_end_at, "source_interval_end_at")
        source_known_clocks: tuple[datetime, ...] = (
            evidence.interval_end_at,
            evidence.local_known_at,
            evidence.fact_recorded_at,
            evidence.publication_as_of,
            evidence.publication_published_at,
            evidence.knowledge_cutoff,
            capture_completed_at,
        )
        if evidence.source_published_at is not None:
            _require_clock(evidence.source_published_at, "source_published_at")
            source_known_clocks = (*source_known_clocks, evidence.source_published_at)
        if any(value > self.checked_at or value > as_of for value in source_known_clocks):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark contains a source or capture clock later than its checked time"
            )
        if not (
            self.interval_end_at
            <= evidence.publication_as_of
            <= evidence.publication_published_at
            <= self.checked_at
            and self.interval_end_at <= evidence.local_known_at <= self.checked_at
            and evidence.fact_recorded_at <= self.checked_at
            and evidence.knowledge_cutoff <= self.checked_at
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source clock ordering is invalid"
            )
        if evidence.source_published_at is not None and not (
            self.interval_end_at <= evidence.source_published_at <= evidence.local_known_at
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark source publication clock is inconsistent"
            )
        day_rows = {row.calendar_date: row for row in self.calendar.snapshot.days}
        local_checked_date = self.checked_at.astimezone(ZoneInfo(publication.timezone_name)).date()
        if (
            self.trade_date not in day_rows
            or not day_rows[self.trade_date].is_open
            or local_checked_date not in day_rows
            or self.interval_end_at > self.reading_started_at
            or self.interval_end_at != cn_market_session_close_utc(self.trade_date)
            or latest_closed_cn_market_session(
                self.checked_at,
                open_sessions=frozenset(day for day, row in day_rows.items() if row.is_open),
            )
            != self.trade_date
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark trade date is not supported by the complete published calendar"
            )
        try:
            expected_deadline = self.interval_end_at + timedelta(
                seconds=policy.freshness_window_seconds
            )
        except (OverflowError, TypeError, ValueError) as error:
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark freshness deadline is not representable"
            ) from error
        if (
            self.valid_until != expected_deadline
            or self.checked_at >= self.valid_until
            or as_of >= self.valid_until
        ):
            raise SimulatedCorporateActionNavRawMarkContractError(
                "raw mark expired or its deadline differs from policy"
            )

    def to_payload(self) -> dict[str, object]:
        """Return a complete safe reference payload without the retained response body."""

        self.verify_for(self.query, as_of=self.checked_at)
        evidence = self.source_evidence
        return {
            "schema": "simulated-corporate-action-nav-raw-mark.v1",
            "purpose": "simulated_corporate_action_nav_raw_mark",
            "query": {
                "physical_account_id": self.query.physical_account_id,
                "canonical_account_id": self.query.canonical_account_id,
                "owner_user_id": self.query.owner_user_id,
                "security_id": self.query.security_id,
                "asset_code": self.query.asset_code,
                "asset_type": self.query.asset_type,
            },
            "policy_binding_sha256": self.policy_binding.content_sha256,
            "classification_sha256": self.classification.content_hash,
            "calendar_sha256": self.calendar.evidence_hash,
            "trade_date": self.trade_date.isoformat(),
            "interval_end_at": _clock_text(self.interval_end_at),
            "price": str(self.price),
            "values": {
                "open": str(evidence.values.open),
                "high": str(evidence.values.high),
                "low": str(evidence.values.low),
                "close": str(evidence.values.close),
                "volume": str(evidence.values.volume),
                "amount": str(evidence.values.amount),
            },
            "currency": "CNY",
            "source_observed_at": None,
            "observed_at": _clock_text(evidence.observed_at),
            "available_at": _clock_text(evidence.available_at),
            "local_known_at": _clock_text(evidence.local_known_at),
            "source_published_at": (
                _clock_text(evidence.source_published_at)
                if evidence.source_published_at is not None
                else None
            ),
            "publication_id": evidence.publication_id,
            "publication_hash": evidence.publication_hash,
            "publication_key": evidence.publication_key,
            "manifest_id": evidence.manifest_id,
            "manifest_hash": evidence.manifest_hash,
            "member_id": evidence.member_id,
            "fact_pk": evidence.fact_pk,
            "fact_content_hash": evidence.fact_content_hash,
            "source": evidence.source,
            "adjustment": evidence.adjustment.value,
            "frequency": "1d",
            "observation_basis": evidence.observation_basis,
            "volume_unit": evidence.volume_unit,
            "amount_unit": evidence.amount_unit,
            "provider_configuration_id": evidence.provider_configuration_id,
            "fact_recorded_at": _clock_text(evidence.fact_recorded_at),
            "publication_as_of": _clock_text(evidence.publication_as_of),
            "publication_published_at": _clock_text(evidence.publication_published_at),
            "knowledge_cutoff": _clock_text(evidence.knowledge_cutoff),
            "raw_audit_reference": evidence.raw_audit_reference.canonical_fields(),
            "raw_payload_reference": evidence.raw_payload_reference.to_payload(),
            "reading_started_at": _clock_text(self.reading_started_at),
            "checked_at": _clock_text(self.checked_at),
            "valid_until": _clock_text(self.valid_until),
            "freshness_status": self.freshness_status,
            "reliability_status": self.reliability_status,
            "scope_reason": self.scope_reason,
            "must_not_use_for_decision": self.must_not_use_for_decision,
        }


class SimulatedCorporateActionNavRawMarkPolicyReader(Protocol):
    """Read the explicit current NAV raw-mark policy and runtime proof."""

    def read_policy(
        self, *, query: SimulatedCorporateActionNavRawMarkQuery, as_of: datetime
    ) -> SimulatedCorporateActionNavRawMarkPolicyBinding | None:
        """Return the current fully bound policy at this cutoff, if configured."""


class SimulatedCorporateActionNavRawMarkReader(Protocol):
    """Read one owner- and instrument-bound current raw mark."""

    def read_current_mark(
        self, query: SimulatedCorporateActionNavRawMarkQuery
    ) -> SimulatedCorporateActionNavRawMarkProof | None:
        """Return current raw-price evidence or ``None`` without fallback values."""


def _require_token(value: object, field_name: str) -> None:
    """Require a nonempty canonical identity token before external reads."""

    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > 192
        or any(character.isspace() for character in value)
    ):
        raise SimulatedCorporateActionNavRawMarkContractError(f"{field_name} is invalid")


def _require_hash(value: object, field_name: str) -> None:
    """Require a lowercase SHA-256 identity digest."""

    if type(value) is not str or _HASH_PATTERN.fullmatch(value) is None:
        raise SimulatedCorporateActionNavRawMarkContractError(f"{field_name} is invalid")


def _require_clock(value: object, field_name: str) -> None:
    """Require one exact aware datetime and reject unusable timezone values."""

    if type(value) is not datetime or value.tzinfo is None:
        raise SimulatedCorporateActionNavRawMarkContractError(f"{field_name} is invalid")
    try:
        if value.utcoffset() is None:
            raise SimulatedCorporateActionNavRawMarkContractError(f"{field_name} is invalid")
        value.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as error:
        raise SimulatedCorporateActionNavRawMarkContractError(f"{field_name} is invalid") from error


def _clock_text(value: datetime) -> str:
    """Render one validated clock in canonical UTC form."""

    _require_clock(value, "datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_sha256(payload: dict[str, object]) -> str:
    """Hash one finite JSON-compatible application contract."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = (
    "SimulatedCorporateActionNavRawMarkPolicyBinding",
    "SimulatedCorporateActionNavRawMarkPolicyReader",
    "SimulatedCorporateActionNavRawMarkProof",
    "SimulatedCorporateActionNavRawMarkQuery",
    "SimulatedCorporateActionNavRawMarkReader",
    "SimulatedCorporateActionNavRawMarkContractError",
)
