"""Manifest-bound in-memory inputs for reproducible R3 research runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.macro_factor.domain.entities import PITSelectedFactVersion

from ._runner_support import (
    decimal_text,
    hash_payload,
    require_aware,
    require_finite,
    require_sha256,
    require_token,
    utc_text,
)

ABSOLUTE_MAXIMUM_INPUT_KNOWLEDGE_AGE_SECONDS = 366 * 24 * 60 * 60


@dataclass(frozen=True)
class VersionedResearchContract:
    """Exact version/hash identity for one externally governed contract."""

    version: str
    content_hash: str

    def __post_init__(self) -> None:
        require_token(self.version, "VersionedResearchContract.version")
        require_sha256(self.content_hash, "VersionedResearchContract.content_hash")


@dataclass(frozen=True)
class ResearchOutputValidityPolicy:
    """Content-addressed policy used to derive research-output validity exactly."""

    policy_version: str
    valid_for_seconds: int
    maximum_valid_for_seconds: int
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        valid_for_seconds: int,
        maximum_valid_for_seconds: int,
    ) -> ResearchOutputValidityPolicy:
        """Create an exact version/hash binding for a fixed validity duration."""

        payload = {
            "policy_version": policy_version,
            "valid_for_seconds": valid_for_seconds,
            "maximum_valid_for_seconds": maximum_valid_for_seconds,
        }
        return cls(
            policy_version=policy_version,
            valid_for_seconds=valid_for_seconds,
            maximum_valid_for_seconds=maximum_valid_for_seconds,
            content_hash=hash_payload(payload),
        )

    def __post_init__(self) -> None:
        require_token(self.policy_version, "ResearchOutputValidityPolicy.policy_version")
        if isinstance(self.valid_for_seconds, bool) or self.valid_for_seconds <= 0:
            raise ValueError("valid_for_seconds must be a positive integer")
        if isinstance(self.maximum_valid_for_seconds, bool) or self.maximum_valid_for_seconds <= 0:
            raise ValueError("maximum_valid_for_seconds must be a positive integer")
        if self.valid_for_seconds > self.maximum_valid_for_seconds:
            raise ValueError("validity duration exceeds its preregistered governance maximum")
        require_sha256(self.content_hash, "ResearchOutputValidityPolicy.content_hash")
        if self.content_hash.lower() != hash_payload(self.canonical_payload()):
            raise ValueError("output validity policy hash does not match content")

    def canonical_payload(self) -> dict[str, object]:
        """Return the exact governed validity content."""

        return {
            "policy_version": self.policy_version,
            "valid_for_seconds": self.valid_for_seconds,
            "maximum_valid_for_seconds": self.maximum_valid_for_seconds,
        }

    def validated_copy(self) -> ResearchOutputValidityPolicy:
        """Reconstruct the policy so post-construction mutation cannot bypass its seal."""

        return ResearchOutputValidityPolicy(
            policy_version=self.policy_version,
            valid_for_seconds=self.valid_for_seconds,
            maximum_valid_for_seconds=self.maximum_valid_for_seconds,
            content_hash=self.content_hash,
        )

    def valid_until(self, produced_at: datetime) -> datetime:
        """Derive validity from the governed duration and aware production time."""

        require_aware(produced_at, "ResearchOutputValidityPolicy.produced_at")
        return produced_at + timedelta(seconds=self.valid_for_seconds)


@dataclass(frozen=True)
class InputKnowledgeFreshnessPolicy:
    """Versioned maximum ages for manifest and inference knowledge."""

    policy_version: str
    max_manifest_age_seconds: int
    max_inference_age_seconds: int
    maximum_allowed_age_seconds: int
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        policy_version: str,
        max_manifest_age_seconds: int,
        max_inference_age_seconds: int,
        maximum_allowed_age_seconds: int,
    ) -> InputKnowledgeFreshnessPolicy:
        """Create an exact content-addressed knowledge-age policy."""

        payload = {
            "policy_version": policy_version,
            "max_manifest_age_seconds": max_manifest_age_seconds,
            "max_inference_age_seconds": max_inference_age_seconds,
            "maximum_allowed_age_seconds": maximum_allowed_age_seconds,
        }
        return cls(
            policy_version=policy_version,
            max_manifest_age_seconds=max_manifest_age_seconds,
            max_inference_age_seconds=max_inference_age_seconds,
            maximum_allowed_age_seconds=maximum_allowed_age_seconds,
            content_hash=hash_payload(payload),
        )

    def __post_init__(self) -> None:
        require_token(self.policy_version, "InputKnowledgeFreshnessPolicy.policy_version")
        for value, name in (
            (self.max_manifest_age_seconds, "max_manifest_age_seconds"),
            (self.max_inference_age_seconds, "max_inference_age_seconds"),
            (self.maximum_allowed_age_seconds, "maximum_allowed_age_seconds"),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.maximum_allowed_age_seconds > ABSOLUTE_MAXIMUM_INPUT_KNOWLEDGE_AGE_SECONDS:
            raise ValueError("input knowledge governance maximum exceeds the implementation cap")
        if (
            self.max_manifest_age_seconds > self.maximum_allowed_age_seconds
            or self.max_inference_age_seconds > self.maximum_allowed_age_seconds
        ):
            raise ValueError("input knowledge age exceeds its preregistered governance maximum")
        require_sha256(self.content_hash, "InputKnowledgeFreshnessPolicy.content_hash")
        if self.content_hash.lower() != hash_payload(self.canonical_payload()):
            raise ValueError("input knowledge freshness policy hash does not match content")

    def canonical_payload(self) -> dict[str, object]:
        """Return the exact governed knowledge-age limits."""

        return {
            "policy_version": self.policy_version,
            "max_manifest_age_seconds": self.max_manifest_age_seconds,
            "max_inference_age_seconds": self.max_inference_age_seconds,
            "maximum_allowed_age_seconds": self.maximum_allowed_age_seconds,
        }

    def validated_copy(self) -> InputKnowledgeFreshnessPolicy:
        """Reconstruct the policy and verify its seal live."""

        return InputKnowledgeFreshnessPolicy(
            policy_version=self.policy_version,
            max_manifest_age_seconds=self.max_manifest_age_seconds,
            max_inference_age_seconds=self.max_inference_age_seconds,
            maximum_allowed_age_seconds=self.maximum_allowed_age_seconds,
            content_hash=self.content_hash,
        )

    def manifest_expires_at(self, manifest_as_of: datetime) -> datetime:
        """Return the last instant at which manifest knowledge may be used."""

        require_aware(manifest_as_of, "InputKnowledgeFreshnessPolicy.manifest_as_of")
        return manifest_as_of + timedelta(seconds=self.max_manifest_age_seconds)

    def inference_expires_at(self, inference_available_at: datetime) -> datetime:
        """Return the last instant at which inference knowledge may be used."""

        require_aware(
            inference_available_at,
            "InputKnowledgeFreshnessPolicy.inference_available_at",
        )
        return inference_available_at + timedelta(seconds=self.max_inference_age_seconds)


@dataclass(frozen=True)
class ProxyObservation:
    """One proxy value on an immutable PIT research row."""

    asset_code: str
    value: Decimal
    fact_version: PITSelectedFactVersion

    def __post_init__(self) -> None:
        require_token(self.asset_code, "ProxyObservation.asset_code")
        require_finite(self.value, "ProxyObservation.value")

    def validated_copy(self) -> ProxyObservation:
        """Reconstruct this value and its owner fact version live."""

        return ProxyObservation(
            asset_code=self.asset_code,
            value=self.value,
            fact_version=self.fact_version.validated_copy(),
        )


@dataclass(frozen=True)
class InferenceTargetCalendarPeriod:
    """One content-addressed target period for a label-free inference row."""

    calendar_id: str
    period_id: str
    calendar_version: str
    calendar_hash: str
    period_start: date
    period_end: date
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        calendar_id: str,
        period_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_start: date,
        period_end: date,
    ) -> InferenceTargetCalendarPeriod:
        """Create one exact versioned target-calendar period."""

        payload = cls._payload(
            calendar_id=calendar_id,
            period_id=period_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_start=period_start,
            period_end=period_end,
        )
        return cls(
            calendar_id=calendar_id,
            period_id=period_id,
            calendar_version=calendar_version,
            calendar_hash=calendar_hash,
            period_start=period_start,
            period_end=period_end,
            content_hash=hash_payload(payload),
        )

    @staticmethod
    def _payload(
        *,
        calendar_id: str,
        period_id: str,
        calendar_version: str,
        calendar_hash: str,
        period_start: date,
        period_end: date,
    ) -> dict[str, object]:
        return {
            "calendar_id": calendar_id,
            "period_id": period_id,
            "calendar_version": calendar_version,
            "calendar_hash": calendar_hash,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
        }

    def __post_init__(self) -> None:
        require_token(self.calendar_id, "InferenceTargetCalendarPeriod.calendar_id")
        require_token(self.period_id, "InferenceTargetCalendarPeriod.period_id")
        require_token(
            self.calendar_version,
            "InferenceTargetCalendarPeriod.calendar_version",
        )
        require_sha256(self.calendar_hash, "InferenceTargetCalendarPeriod.calendar_hash")
        if self.period_start > self.period_end:
            raise ValueError("inference target calendar period is invalid")
        require_sha256(
            self.content_hash,
            "InferenceTargetCalendarPeriod.content_hash",
        )
        expected = hash_payload(
            self._payload(
                calendar_id=self.calendar_id,
                period_id=self.period_id,
                calendar_version=self.calendar_version,
                calendar_hash=self.calendar_hash,
                period_start=self.period_start,
                period_end=self.period_end,
            )
        )
        if self.content_hash.lower() != expected:
            raise ValueError("inference target calendar period hash does not match content")

    def canonical_payload(self) -> dict[str, object]:
        """Return the exact calendar identity and closed target window."""

        return {
            **self._payload(
                calendar_id=self.calendar_id,
                period_id=self.period_id,
                calendar_version=self.calendar_version,
                calendar_hash=self.calendar_hash,
                period_start=self.period_start,
                period_end=self.period_end,
            ),
            "content_hash": self.content_hash,
        }

    def validated_copy(self) -> InferenceTargetCalendarPeriod:
        """Reconstruct the period and verify its content seal live."""

        return InferenceTargetCalendarPeriod(
            calendar_id=self.calendar_id,
            period_id=self.period_id,
            calendar_version=self.calendar_version,
            calendar_hash=self.calendar_hash,
            period_start=self.period_start,
            period_end=self.period_end,
            content_hash=self.content_hash,
        )


@dataclass(frozen=True)
class PITInferenceRow:
    """One manifest-bound proxy row with no target label or target value."""

    row_id: str
    observation_date: date
    available_at: datetime
    target_period: InferenceTargetCalendarPeriod
    proxies: tuple[ProxyObservation, ...]

    def __post_init__(self) -> None:
        require_token(self.row_id, "PITInferenceRow.row_id")
        require_aware(self.available_at, "PITInferenceRow.available_at")
        self.target_period.validated_copy()
        if self.observation_date > self.available_at.date():
            raise ValueError("inference observation cannot follow its availability")
        if not self.proxies:
            raise ValueError("PITInferenceRow.proxies cannot be empty")
        codes = tuple(item.asset_code for item in self.proxies)
        if len(codes) != len(set(codes)):
            raise ValueError("PITInferenceRow proxy identities must be unique")
        if any(
            item.fact_version.effective_at.date() != self.observation_date for item in self.proxies
        ):
            raise ValueError("inference proxy effective times must match observation_date")
        if self.available_at != max(item.fact_version.available_at for item in self.proxies):
            raise ValueError("inference available_at must equal latest proxy availability")

    def canonical_payload(self) -> dict[str, object]:
        """Return the label-free input and exact target-calendar identity."""

        return {
            "row_id": self.row_id,
            "observation_date": self.observation_date.isoformat(),
            "available_at": utc_text(self.available_at),
            "target_period": self.target_period.canonical_payload(),
            "proxies": [
                {
                    "asset_code": item.asset_code,
                    "value": decimal_text(item.value),
                    "fact_version": {
                        "version_id": item.fact_version.version_id,
                        "content_hash": item.fact_version.content_hash,
                        "effective_at": utc_text(item.fact_version.effective_at),
                        "available_at": utc_text(item.fact_version.available_at),
                    },
                }
                for item in sorted(self.proxies, key=lambda value: value.asset_code)
            ],
        }

    def proxy_value(self, asset_code: str) -> Decimal:
        """Return one exact proxy value after candidate-universe validation."""

        return next(item.value for item in self.proxies if item.asset_code == asset_code)

    def validated_copy(self) -> PITInferenceRow:
        """Reconstruct proxy facts and the target calendar before inference."""

        return PITInferenceRow(
            row_id=self.row_id,
            observation_date=self.observation_date,
            available_at=self.available_at,
            target_period=self.target_period.validated_copy(),
            proxies=tuple(item.validated_copy() for item in self.proxies),
        )


@dataclass(frozen=True)
class PITResearchRow:
    """One design row with observation and label-availability chronology."""

    row_id: str
    observation_date: date
    target_period_start: date
    target_period_end: date
    available_at: datetime
    label_available_at: datetime
    target_value: Decimal
    target_fact_version: PITSelectedFactVersion
    proxies: tuple[ProxyObservation, ...]

    def __post_init__(self) -> None:
        require_token(self.row_id, "PITResearchRow.row_id")
        require_aware(self.available_at, "PITResearchRow.available_at")
        require_aware(self.label_available_at, "PITResearchRow.label_available_at")
        require_finite(self.target_value, "PITResearchRow.target_value")
        if self.target_period_start > self.target_period_end:
            raise ValueError("PITResearchRow target period is invalid")
        if self.observation_date > self.target_period_end:
            raise ValueError("PITResearchRow target cannot precede observation")
        if self.label_available_at < self.available_at:
            raise ValueError("PITResearchRow label cannot be available before its design row")
        if not (
            self.target_period_start
            <= self.target_fact_version.effective_at.date()
            <= self.target_period_end
        ):
            raise ValueError("PITResearchRow target fact effective time is outside target period")
        if self.target_fact_version.available_at != self.label_available_at:
            raise ValueError("PITResearchRow label availability must match target fact")
        if not self.proxies:
            raise ValueError("PITResearchRow.proxies cannot be empty")
        codes = tuple(item.asset_code for item in self.proxies)
        if len(codes) != len(set(codes)):
            raise ValueError("PITResearchRow proxy identities must be unique")
        if any(
            item.fact_version.effective_at.date() != self.observation_date for item in self.proxies
        ):
            raise ValueError("proxy fact effective times must match observation_date")
        if self.available_at != max(item.fact_version.available_at for item in self.proxies):
            raise ValueError("row available_at must equal latest proxy fact availability")

    def canonical_payload(self) -> dict[str, object]:
        """Return stable row content used by dataset and fold design hashes."""

        return {
            "row_id": self.row_id,
            "observation_date": self.observation_date.isoformat(),
            "target_period_start": self.target_period_start.isoformat(),
            "target_period_end": self.target_period_end.isoformat(),
            "available_at": utc_text(self.available_at),
            "label_available_at": utc_text(self.label_available_at),
            "target_value": decimal_text(self.target_value),
            "target_fact_version": {
                "version_id": self.target_fact_version.version_id,
                "content_hash": self.target_fact_version.content_hash,
                "effective_at": utc_text(self.target_fact_version.effective_at),
                "available_at": utc_text(self.target_fact_version.available_at),
            },
            "proxies": [
                {
                    "asset_code": item.asset_code,
                    "value": decimal_text(item.value),
                    "fact_version": {
                        "version_id": item.fact_version.version_id,
                        "content_hash": item.fact_version.content_hash,
                        "effective_at": utc_text(item.fact_version.effective_at),
                        "available_at": utc_text(item.fact_version.available_at),
                    },
                }
                for item in sorted(self.proxies, key=lambda value: value.asset_code)
            ],
        }

    def proxy_value(self, asset_code: str) -> Decimal:
        """Return the exact proxy value for an already validated asset code."""

        return next(item.value for item in self.proxies if item.asset_code == asset_code)

    def validated_copy(self) -> PITResearchRow:
        """Reconstruct row summaries from live target and proxy fact clocks."""

        return PITResearchRow(
            row_id=self.row_id,
            observation_date=self.observation_date,
            target_period_start=self.target_period_start,
            target_period_end=self.target_period_end,
            available_at=self.available_at,
            label_available_at=self.label_available_at,
            target_value=self.target_value,
            target_fact_version=self.target_fact_version.validated_copy(),
            proxies=tuple(item.validated_copy() for item in self.proxies),
        )


@dataclass(frozen=True)
class PITResearchDataset:
    """In-memory, manifest-bound design rows; never a second fact store."""

    manifest_id: str
    manifest_hash: str
    manifest_content_hash: str
    manifest_as_of: datetime
    target_code: str
    candidate_asset_codes: tuple[str, ...]
    rows: tuple[PITResearchRow, ...]
    inference_row: PITInferenceRow | None = None

    def __post_init__(self) -> None:
        require_token(self.manifest_id, "PITResearchDataset.manifest_id")
        require_sha256(self.manifest_hash, "PITResearchDataset.manifest_hash")
        require_sha256(
            self.manifest_content_hash,
            "PITResearchDataset.manifest_content_hash",
        )
        require_aware(self.manifest_as_of, "PITResearchDataset.manifest_as_of")
        require_token(self.target_code, "PITResearchDataset.target_code")
        if not self.candidate_asset_codes:
            raise ValueError("PITResearchDataset.candidate_asset_codes cannot be empty")
        for asset_code in self.candidate_asset_codes:
            require_token(asset_code, "PITResearchDataset.candidate_asset_code")
        if len(self.candidate_asset_codes) != len(set(self.candidate_asset_codes)):
            raise ValueError("PITResearchDataset candidate identities must be unique")
        if not self.rows:
            raise ValueError("PITResearchDataset.rows cannot be empty")
        row_ids = tuple(item.row_id for item in self.rows)
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("PITResearchDataset row identities must be unique")
        expected_codes = frozenset(self.candidate_asset_codes)
        for row in self.rows:
            if frozenset(item.asset_code for item in row.proxies) != expected_codes:
                raise ValueError(
                    f"PIT row {row.row_id} does not cover the exact candidate universe"
                )
            if (
                row.available_at > self.manifest_as_of
                or row.label_available_at > self.manifest_as_of
            ):
                raise ValueError(f"PIT row {row.row_id} exceeds manifest knowledge time")
        if self.inference_row is not None:
            inference = self.inference_row
            if inference.row_id in set(row_ids):
                raise ValueError("inference row identity must be distinct from design rows")
            if frozenset(item.asset_code for item in inference.proxies) != expected_codes:
                raise ValueError("inference row does not cover the exact candidate universe")
            if inference.available_at > self.manifest_as_of:
                raise ValueError("inference row exceeds manifest knowledge time")

    @property
    def content_hash(self) -> str:
        """Seal exact PIT row IDs, values, and availability timestamps."""

        return hash_payload(
            {
                "manifest_id": self.manifest_id,
                "manifest_hash": self.manifest_hash.lower(),
                "manifest_content_hash": self.manifest_content_hash.lower(),
                "manifest_as_of": utc_text(self.manifest_as_of),
                "target_code": self.target_code,
                "candidate_asset_codes": list(self.candidate_asset_codes),
                "rows": [
                    row.canonical_payload()
                    for row in sorted(self.rows, key=lambda item: item.row_id)
                ],
                "inference_row": (
                    None if self.inference_row is None else self.inference_row.canonical_payload()
                ),
            }
        )

    @property
    def rows_by_id(self) -> dict[str, PITResearchRow]:
        """Return an ephemeral lookup for pure runner calculations."""

        return {item.row_id: item for item in self.rows}

    def validated_copy(self) -> PITResearchDataset:
        """Reconstruct all design rows before handing them to a runner."""

        return PITResearchDataset(
            manifest_id=self.manifest_id,
            manifest_hash=self.manifest_hash,
            manifest_content_hash=self.manifest_content_hash,
            manifest_as_of=self.manifest_as_of,
            target_code=self.target_code,
            candidate_asset_codes=self.candidate_asset_codes,
            rows=tuple(item.validated_copy() for item in self.rows),
            inference_row=(
                None if self.inference_row is None else self.inference_row.validated_copy()
            ),
        )


__all__ = [
    "ABSOLUTE_MAXIMUM_INPUT_KNOWLEDGE_AGE_SECONDS",
    "InferenceTargetCalendarPeriod",
    "InputKnowledgeFreshnessPolicy",
    "PITInferenceRow",
    "PITResearchDataset",
    "PITResearchRow",
    "ProxyObservation",
    "ResearchOutputValidityPolicy",
    "VersionedResearchContract",
]
