"""R4-owned immutable evidence projections for rolling macro-risk research.

Portfolio consumes macro-factor and regime owner evidence through these narrow
projections.  It does not own or recalculate either upstream model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from apps.macro_factor.domain.entities import SampleWindow
from apps.portfolio.domain.macro_factor_risk import MacroExposureVersion


def _require_text(value: str, field_name: str, *, maximum: int = 200) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} cannot be blank")
    if "\0" in value:
        raise ValueError(f"{field_name} cannot contain a null character")
    if len(value) > maximum:
        raise ValueError(f"{field_name} exceeds {maximum} characters")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdefABCDEF" for character in value):
        raise ValueError(f"{field_name} must be a sha256 digest")


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_finite(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError(f"{field_name} must be a finite Decimal")


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    return "0" if normalized == 0 else format(normalized, "f")


def _utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _hash_parts(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _validate_source_hashes(values: tuple[str, ...]) -> None:
    if not values or values != tuple(sorted(set(values))):
        raise ValueError("source hashes must be non-empty, unique, and ordered")
    for value in values:
        _require_sha256(value, "source_content_hash")


@dataclass(frozen=True)
class R4AssetReturn:
    """One finite OOS asset return."""

    asset_code: str
    value: Decimal

    def __post_init__(self) -> None:
        _require_text(self.asset_code, "asset_code", maximum=80)
        _require_finite(self.value, "asset return")
        if self.value < -1:
            raise ValueError("asset return cannot be below -100%")


@dataclass(frozen=True)
class R4ReturnObservation:
    """One ordered OOS return vector observed at a period end."""

    period_end: datetime
    asset_returns: tuple[R4AssetReturn, ...]

    def __post_init__(self) -> None:
        _require_aware(self.period_end, "period_end")
        codes = tuple(item.asset_code for item in self.asset_returns)
        if not codes or codes != tuple(sorted(set(codes))):
            raise ValueError("return observation assets must be non-empty, unique, and ordered")


@dataclass(frozen=True)
class R4AssetCovarianceEvidence:
    """Portfolio-owned asset covariance known at one formation cutoff."""

    owner: str
    covariance_id: str
    covariance_version: str
    universe_id: str
    universe_hash: str
    asset_codes: tuple[str, ...]
    values: tuple[tuple[Decimal, ...], ...]
    estimator_version: str
    condition_number: Decimal
    matrix_rank: int
    expected_observation_count: int
    missing_observation_count: int
    missing_value_policy_version: str
    estimation_window: SampleWindow
    observed_at: datetime
    available_at: datetime
    knowledge_as_of: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    source_content_hashes: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        covariance_id: str,
        covariance_version: str,
        universe_id: str,
        universe_hash: str,
        asset_codes: tuple[str, ...],
        values: tuple[tuple[Decimal, ...], ...],
        estimator_version: str,
        condition_number: Decimal,
        matrix_rank: int,
        expected_observation_count: int,
        missing_observation_count: int,
        missing_value_policy_version: str,
        estimation_window: SampleWindow,
        observed_at: datetime,
        available_at: datetime,
        knowledge_as_of: datetime,
        valid_until: datetime,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        source_content_hashes: tuple[str, ...],
    ) -> R4AssetCovarianceEvidence:
        """Create and seal one Portfolio-owned covariance projection."""

        digest = _asset_covariance_hash(
            covariance_id=covariance_id,
            covariance_version=covariance_version,
            universe_id=universe_id,
            universe_hash=universe_hash,
            asset_codes=asset_codes,
            values=values,
            estimator_version=estimator_version,
            condition_number=condition_number,
            matrix_rank=matrix_rank,
            expected_observation_count=expected_observation_count,
            missing_observation_count=missing_observation_count,
            missing_value_policy_version=missing_value_policy_version,
            estimation_window=estimation_window,
            observed_at=observed_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hashes=source_content_hashes,
        )
        return cls(
            owner="portfolio",
            covariance_id=covariance_id,
            covariance_version=covariance_version,
            universe_id=universe_id,
            universe_hash=universe_hash,
            asset_codes=asset_codes,
            values=values,
            estimator_version=estimator_version,
            condition_number=condition_number,
            matrix_rank=matrix_rank,
            expected_observation_count=expected_observation_count,
            missing_observation_count=missing_observation_count,
            missing_value_policy_version=missing_value_policy_version,
            estimation_window=estimation_window,
            observed_at=observed_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hashes=source_content_hashes,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "portfolio":
            raise ValueError("asset covariance owner must be portfolio")
        for text_name, text_value in (
            ("covariance_id", self.covariance_id),
            ("covariance_version", self.covariance_version),
            ("universe_id", self.universe_id),
            ("estimator_version", self.estimator_version),
            ("missing_value_policy_version", self.missing_value_policy_version),
            ("pit_manifest_id", self.pit_manifest_id),
        ):
            _require_text(text_value, text_name)
        _require_sha256(self.universe_hash, "universe_hash")
        _require_sha256(self.pit_manifest_hash, "pit_manifest_hash")
        if not self.asset_codes or self.asset_codes != tuple(sorted(set(self.asset_codes))):
            raise ValueError("covariance assets must be non-empty, unique, and ordered")
        size = len(self.asset_codes)
        if len(self.values) != size or any(len(row) != size for row in self.values):
            raise ValueError("asset covariance must be square")
        for row in self.values:
            for matrix_value in row:
                _require_finite(matrix_value, "asset covariance value")
        _require_finite(self.condition_number, "condition_number")
        if self.condition_number < 1:
            raise ValueError("condition_number must be at least one")
        if isinstance(self.matrix_rank, bool) or not 1 <= self.matrix_rank <= size:
            raise ValueError("matrix_rank must be within the covariance dimension")
        if isinstance(self.expected_observation_count, bool) or self.expected_observation_count < 1:
            raise ValueError("expected_observation_count must be positive")
        if isinstance(self.missing_observation_count, bool) or self.missing_observation_count < 0:
            raise ValueError("missing_observation_count cannot be negative")
        if self.missing_observation_count > self.expected_observation_count:
            raise ValueError("missing observations cannot exceed expected observations")
        for clock_name, clock_value in (
            ("observed_at", self.observed_at),
            ("available_at", self.available_at),
            ("knowledge_as_of", self.knowledge_as_of),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, clock_name)
        if not self.observed_at <= self.available_at <= self.knowledge_as_of < self.valid_until:
            raise ValueError("asset covariance bitemporal clocks are invalid")
        if self.estimation_window.end > self.observed_at.date():
            raise ValueError(
                "asset covariance cannot be observed before its estimation window ends"
            )
        _validate_source_hashes(self.source_content_hashes)
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _asset_covariance_hash(
            covariance_id=self.covariance_id,
            covariance_version=self.covariance_version,
            universe_id=self.universe_id,
            universe_hash=self.universe_hash,
            asset_codes=self.asset_codes,
            values=self.values,
            estimator_version=self.estimator_version,
            condition_number=self.condition_number,
            matrix_rank=self.matrix_rank,
            expected_observation_count=self.expected_observation_count,
            missing_observation_count=self.missing_observation_count,
            missing_value_policy_version=self.missing_value_policy_version,
            estimation_window=self.estimation_window,
            observed_at=self.observed_at,
            available_at=self.available_at,
            knowledge_as_of=self.knowledge_as_of,
            valid_until=self.valid_until,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            source_content_hashes=self.source_content_hashes,
        ):
            raise ValueError("asset covariance content_hash mismatch")


def _asset_covariance_hash(
    *,
    covariance_id: str,
    covariance_version: str,
    universe_id: str,
    universe_hash: str,
    asset_codes: tuple[str, ...],
    values: tuple[tuple[Decimal, ...], ...],
    estimator_version: str,
    condition_number: Decimal,
    matrix_rank: int,
    expected_observation_count: int,
    missing_observation_count: int,
    missing_value_policy_version: str,
    estimation_window: SampleWindow,
    observed_at: datetime,
    available_at: datetime,
    knowledge_as_of: datetime,
    valid_until: datetime,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    source_content_hashes: tuple[str, ...],
) -> str:
    return _hash_parts(
        "r4-asset-covariance.v3",
        covariance_id,
        covariance_version,
        universe_id,
        universe_hash.lower(),
        *asset_codes,
        *("|".join(_decimal_text(value) for value in row) for row in values),
        estimator_version,
        _decimal_text(condition_number),
        str(matrix_rank),
        str(expected_observation_count),
        str(missing_observation_count),
        missing_value_policy_version,
        estimation_window.start.isoformat(),
        estimation_window.end.isoformat(),
        _utc_text(observed_at),
        _utc_text(available_at),
        _utc_text(knowledge_as_of),
        _utc_text(valid_until),
        pit_manifest_id,
        pit_manifest_hash.lower(),
        *source_content_hashes,
    )


@dataclass(frozen=True)
class R4OOSReturnPathEvidence:
    """Portfolio-owned realized returns for one exact OOS window."""

    owner: str
    path_id: str
    path_version: str
    universe_id: str
    universe_hash: str
    out_of_sample: SampleWindow
    observations: tuple[R4ReturnObservation, ...]
    observed_at: datetime
    available_at: datetime
    knowledge_as_of: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    source_content_hashes: tuple[str, ...]
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        path_id: str,
        path_version: str,
        universe_id: str,
        universe_hash: str,
        out_of_sample: SampleWindow,
        observations: tuple[R4ReturnObservation, ...],
        observed_at: datetime,
        available_at: datetime,
        knowledge_as_of: datetime,
        valid_until: datetime,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        source_content_hashes: tuple[str, ...],
    ) -> R4OOSReturnPathEvidence:
        """Create and seal one exact OOS return path."""

        digest = _oos_return_path_hash(
            path_id=path_id,
            path_version=path_version,
            universe_id=universe_id,
            universe_hash=universe_hash,
            out_of_sample=out_of_sample,
            observations=observations,
            observed_at=observed_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hashes=source_content_hashes,
        )
        return cls(
            owner="portfolio",
            path_id=path_id,
            path_version=path_version,
            universe_id=universe_id,
            universe_hash=universe_hash,
            out_of_sample=out_of_sample,
            observations=observations,
            observed_at=observed_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hashes=source_content_hashes,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "portfolio":
            raise ValueError("OOS return path owner must be portfolio")
        for text_name, text_value in (
            ("path_id", self.path_id),
            ("path_version", self.path_version),
            ("universe_id", self.universe_id),
            ("pit_manifest_id", self.pit_manifest_id),
        ):
            _require_text(text_value, text_name)
        _require_sha256(self.universe_hash, "universe_hash")
        _require_sha256(self.pit_manifest_hash, "pit_manifest_hash")
        if len(self.observations) < 2:
            raise ValueError("OOS return path requires at least two observations")
        times = tuple(item.period_end for item in self.observations)
        if times != tuple(sorted(set(times))):
            raise ValueError("OOS observations must be unique and ordered")
        assets = tuple(item.asset_code for item in self.observations[0].asset_returns)
        if any(
            tuple(item.asset_code for item in row.asset_returns) != assets
            for row in self.observations
        ):
            raise ValueError("OOS return path asset universe changes between periods")
        if any(
            not self.out_of_sample.start <= item.period_end.date() <= self.out_of_sample.end
            for item in self.observations
        ):
            raise ValueError("OOS observations fall outside the typed window")
        for clock_name, clock_value in (
            ("observed_at", self.observed_at),
            ("available_at", self.available_at),
            ("knowledge_as_of", self.knowledge_as_of),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, clock_name)
        if self.observed_at < self.observations[-1].period_end:
            raise ValueError("OOS evidence cannot be observed before its final return")
        if not self.observed_at <= self.available_at <= self.knowledge_as_of < self.valid_until:
            raise ValueError("OOS return bitemporal clocks are invalid")
        _validate_source_hashes(self.source_content_hashes)
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _oos_return_path_hash(
            path_id=self.path_id,
            path_version=self.path_version,
            universe_id=self.universe_id,
            universe_hash=self.universe_hash,
            out_of_sample=self.out_of_sample,
            observations=self.observations,
            observed_at=self.observed_at,
            available_at=self.available_at,
            knowledge_as_of=self.knowledge_as_of,
            valid_until=self.valid_until,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            source_content_hashes=self.source_content_hashes,
        ):
            raise ValueError("OOS return path content_hash mismatch")


def _oos_return_path_hash(
    *,
    path_id: str,
    path_version: str,
    universe_id: str,
    universe_hash: str,
    out_of_sample: SampleWindow,
    observations: tuple[R4ReturnObservation, ...],
    observed_at: datetime,
    available_at: datetime,
    knowledge_as_of: datetime,
    valid_until: datetime,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    source_content_hashes: tuple[str, ...],
) -> str:
    rows = tuple(
        "|".join(
            (
                _utc_text(item.period_end),
                *(
                    f"{value.asset_code},{_decimal_text(value.value)}"
                    for value in item.asset_returns
                ),
            )
        )
        for item in observations
    )
    return _hash_parts(
        "r4-oos-return-path.v1",
        path_id,
        path_version,
        universe_id,
        universe_hash.lower(),
        out_of_sample.start.isoformat(),
        out_of_sample.end.isoformat(),
        *rows,
        _utc_text(observed_at),
        _utc_text(available_at),
        _utc_text(knowledge_as_of),
        _utc_text(valid_until),
        pit_manifest_id,
        pit_manifest_hash.lower(),
        *source_content_hashes,
    )


@dataclass(frozen=True)
class R4RegimeAssignmentEvidence:
    """Regime-owned PIT assignment known at one formation cutoff."""

    owner: str
    assignment_id: str
    assignment_version: str
    taxonomy_version: str
    regime_code: str
    effective_at: datetime
    available_at: datetime
    knowledge_as_of: datetime
    valid_until: datetime
    pit_manifest_id: str
    pit_manifest_hash: str
    source_content_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        assignment_id: str,
        assignment_version: str,
        taxonomy_version: str,
        regime_code: str,
        effective_at: datetime,
        available_at: datetime,
        knowledge_as_of: datetime,
        valid_until: datetime,
        pit_manifest_id: str,
        pit_manifest_hash: str,
        source_content_hash: str,
    ) -> R4RegimeAssignmentEvidence:
        """Create and seal exact Regime-owner evidence."""

        digest = _regime_hash(
            assignment_id=assignment_id,
            assignment_version=assignment_version,
            taxonomy_version=taxonomy_version,
            regime_code=regime_code,
            effective_at=effective_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hash=source_content_hash,
        )
        return cls(
            owner="regime",
            assignment_id=assignment_id,
            assignment_version=assignment_version,
            taxonomy_version=taxonomy_version,
            regime_code=regime_code,
            effective_at=effective_at,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            valid_until=valid_until,
            pit_manifest_id=pit_manifest_id,
            pit_manifest_hash=pit_manifest_hash,
            source_content_hash=source_content_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "regime":
            raise ValueError("regime assignment owner must be regime")
        for text_name, text_value in (
            ("assignment_id", self.assignment_id),
            ("assignment_version", self.assignment_version),
            ("taxonomy_version", self.taxonomy_version),
            ("regime_code", self.regime_code),
            ("pit_manifest_id", self.pit_manifest_id),
        ):
            _require_text(text_value, text_name)
        for clock_name, clock_value in (
            ("effective_at", self.effective_at),
            ("available_at", self.available_at),
            ("knowledge_as_of", self.knowledge_as_of),
            ("valid_until", self.valid_until),
        ):
            _require_aware(clock_value, clock_name)
        if not self.effective_at <= self.available_at <= self.knowledge_as_of < self.valid_until:
            raise ValueError("regime assignment bitemporal clocks are invalid")
        _require_sha256(self.pit_manifest_hash, "pit_manifest_hash")
        _require_sha256(self.source_content_hash, "source_content_hash")
        _require_sha256(self.content_hash, "content_hash")
        if self.content_hash.lower() != _regime_hash(
            assignment_id=self.assignment_id,
            assignment_version=self.assignment_version,
            taxonomy_version=self.taxonomy_version,
            regime_code=self.regime_code,
            effective_at=self.effective_at,
            available_at=self.available_at,
            knowledge_as_of=self.knowledge_as_of,
            valid_until=self.valid_until,
            pit_manifest_id=self.pit_manifest_id,
            pit_manifest_hash=self.pit_manifest_hash,
            source_content_hash=self.source_content_hash,
        ):
            raise ValueError("regime assignment content_hash mismatch")


def _regime_hash(
    *,
    assignment_id: str,
    assignment_version: str,
    taxonomy_version: str,
    regime_code: str,
    effective_at: datetime,
    available_at: datetime,
    knowledge_as_of: datetime,
    valid_until: datetime,
    pit_manifest_id: str,
    pit_manifest_hash: str,
    source_content_hash: str,
) -> str:
    return _hash_parts(
        "r4-regime-assignment.v1",
        assignment_id,
        assignment_version,
        taxonomy_version,
        regime_code,
        _utc_text(effective_at),
        _utc_text(available_at),
        _utc_text(knowledge_as_of),
        _utc_text(valid_until),
        pit_manifest_id,
        pit_manifest_hash.lower(),
        source_content_hash.lower(),
    )


@dataclass(frozen=True)
class R4MacroExposureProjectionEvidence:
    """Immutable macro_factor output consumed by Portfolio for one window."""

    owner: str
    exposure_version: MacroExposureVersion
    factor_artifact_id: str
    factor_artifact_version: str
    factor_artifact_content_hash: str
    promotion_decision_id: str
    promotion_decision_version: str
    promotion_decision_content_hash: str
    available_at: datetime
    knowledge_as_of: datetime
    source_content_hash: str
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        exposure_version: MacroExposureVersion,
        factor_artifact_id: str,
        factor_artifact_version: str,
        factor_artifact_content_hash: str,
        promotion_decision_id: str,
        promotion_decision_version: str,
        promotion_decision_content_hash: str,
        available_at: datetime,
        knowledge_as_of: datetime,
    ) -> R4MacroExposureProjectionEvidence:
        """Create a consumed projection without transferring model ownership."""

        source_hash = _macro_exposure_hash(exposure_version)
        digest = _macro_projection_hash(
            exposure_version=exposure_version,
            factor_artifact_id=factor_artifact_id,
            factor_artifact_version=factor_artifact_version,
            factor_artifact_content_hash=factor_artifact_content_hash,
            promotion_decision_id=promotion_decision_id,
            promotion_decision_version=promotion_decision_version,
            promotion_decision_content_hash=promotion_decision_content_hash,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            source_content_hash=source_hash,
        )
        return cls(
            owner="macro_factor",
            exposure_version=exposure_version,
            factor_artifact_id=factor_artifact_id,
            factor_artifact_version=factor_artifact_version,
            factor_artifact_content_hash=factor_artifact_content_hash,
            promotion_decision_id=promotion_decision_id,
            promotion_decision_version=promotion_decision_version,
            promotion_decision_content_hash=promotion_decision_content_hash,
            available_at=available_at,
            knowledge_as_of=knowledge_as_of,
            source_content_hash=source_hash,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "macro_factor":
            raise ValueError("macro exposure projection owner must be macro_factor")
        for name, value in (
            ("factor_artifact_id", self.factor_artifact_id),
            ("factor_artifact_version", self.factor_artifact_version),
            ("promotion_decision_id", self.promotion_decision_id),
            ("promotion_decision_version", self.promotion_decision_version),
        ):
            _require_text(value, name)
        for name, value in (
            ("factor_artifact_content_hash", self.factor_artifact_content_hash),
            ("promotion_decision_content_hash", self.promotion_decision_content_hash),
            ("source_content_hash", self.source_content_hash),
            ("content_hash", self.content_hash),
        ):
            _require_sha256(value, name)
        _require_aware(self.available_at, "available_at")
        _require_aware(self.knowledge_as_of, "knowledge_as_of")
        if not (
            self.exposure_version.observed_at
            <= self.available_at
            <= self.knowledge_as_of
            < self.exposure_version.valid_until
        ):
            raise ValueError("macro exposure projection clocks are invalid")
        if self.factor_artifact_version != self.exposure_version.promoted_factor_version:
            raise ValueError("projection factor artifact version mismatch")
        if self.promotion_decision_id != self.exposure_version.promotion_decision_id:
            raise ValueError("projection promotion decision mismatch")
        if self.source_content_hash.lower() != _macro_exposure_hash(self.exposure_version):
            raise ValueError("macro exposure source hash mismatch")
        if self.content_hash.lower() != _macro_projection_hash(
            exposure_version=self.exposure_version,
            factor_artifact_id=self.factor_artifact_id,
            factor_artifact_version=self.factor_artifact_version,
            factor_artifact_content_hash=self.factor_artifact_content_hash,
            promotion_decision_id=self.promotion_decision_id,
            promotion_decision_version=self.promotion_decision_version,
            promotion_decision_content_hash=self.promotion_decision_content_hash,
            available_at=self.available_at,
            knowledge_as_of=self.knowledge_as_of,
            source_content_hash=self.source_content_hash,
        ):
            raise ValueError("macro exposure projection content_hash mismatch")


def _macro_exposure_hash(exposure: MacroExposureVersion) -> str:
    exposure_parts = tuple(
        "|".join(
            (
                item.asset_code,
                _decimal_text(item.residual_variance),
                _decimal_text(item.r_squared),
                _decimal_text(item.stability_score),
                *(
                    ",".join(
                        (
                            beta.factor_code,
                            _decimal_text(beta.beta),
                            _decimal_text(beta.confidence_low),
                            _decimal_text(beta.confidence_high),
                        )
                    )
                    for beta in item.betas
                ),
            )
        )
        for item in sorted(exposure.exposures, key=lambda value: value.asset_code)
    )
    return _hash_parts(
        "r4-consumed-macro-exposure.v1",
        exposure.version_id,
        exposure.promoted_factor_version,
        exposure.promotion_decision_id,
        exposure.pit_manifest_id,
        exposure.code_version,
        exposure.parameter_version,
        _utc_text(exposure.observed_at),
        _utc_text(exposure.valid_until),
        *exposure_parts,
    )


def _macro_projection_hash(
    *,
    exposure_version: MacroExposureVersion,
    factor_artifact_id: str,
    factor_artifact_version: str,
    factor_artifact_content_hash: str,
    promotion_decision_id: str,
    promotion_decision_version: str,
    promotion_decision_content_hash: str,
    available_at: datetime,
    knowledge_as_of: datetime,
    source_content_hash: str,
) -> str:
    return _hash_parts(
        "r4-macro-exposure-projection.v1",
        exposure_version.version_id,
        factor_artifact_id,
        factor_artifact_version,
        factor_artifact_content_hash.lower(),
        promotion_decision_id,
        promotion_decision_version,
        promotion_decision_content_hash.lower(),
        _utc_text(available_at),
        _utc_text(knowledge_as_of),
        source_content_hash.lower(),
    )


@dataclass(frozen=True)
class ExactR3PromotionAttestation:
    """Authoritative Research approval for one exact R3 factor artifact."""

    owner: str
    capability_key: str
    purpose: str
    artifact_id: str
    artifact_version: str
    artifact_content_hash: str
    decision_id: str
    decision_version: str
    decision_content_hash: str
    approved_at: datetime
    valid_until: datetime
    retired_at: datetime | None
    content_hash: str

    @classmethod
    def create(
        cls,
        *,
        artifact_id: str,
        artifact_version: str,
        artifact_content_hash: str,
        decision_id: str,
        decision_version: str,
        decision_content_hash: str,
        approved_at: datetime,
        valid_until: datetime,
        retired_at: datetime | None = None,
    ) -> ExactR3PromotionAttestation:
        """Create a sealed R3 attestation for R4 research only."""

        digest = _r3_attestation_hash(
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            artifact_content_hash=artifact_content_hash,
            decision_id=decision_id,
            decision_version=decision_version,
            decision_content_hash=decision_content_hash,
            approved_at=approved_at,
            valid_until=valid_until,
            retired_at=retired_at,
        )
        return cls(
            owner="research",
            capability_key="macro_factor_r3",
            purpose="r4_macro_risk_research",
            artifact_id=artifact_id,
            artifact_version=artifact_version,
            artifact_content_hash=artifact_content_hash,
            decision_id=decision_id,
            decision_version=decision_version,
            decision_content_hash=decision_content_hash,
            approved_at=approved_at,
            valid_until=valid_until,
            retired_at=retired_at,
            content_hash=digest,
        )

    def __post_init__(self) -> None:
        if self.owner != "research":
            raise ValueError("R3 promotion owner must be research")
        if self.capability_key != "macro_factor_r3":
            raise ValueError("R3 promotion capability mismatch")
        if self.purpose != "r4_macro_risk_research":
            raise ValueError("R3 promotion purpose mismatch")
        for name, value in (
            ("artifact_id", self.artifact_id),
            ("artifact_version", self.artifact_version),
            ("decision_id", self.decision_id),
            ("decision_version", self.decision_version),
        ):
            _require_text(value, name)
        for name, value in (
            ("artifact_content_hash", self.artifact_content_hash),
            ("decision_content_hash", self.decision_content_hash),
            ("content_hash", self.content_hash),
        ):
            _require_sha256(value, name)
        _require_aware(self.approved_at, "approved_at")
        _require_aware(self.valid_until, "valid_until")
        if self.valid_until <= self.approved_at:
            raise ValueError("R3 promotion validity is invalid")
        if self.retired_at is not None:
            _require_aware(self.retired_at, "retired_at")
            if self.retired_at <= self.approved_at:
                raise ValueError("R3 promotion retirement is invalid")
        if self.content_hash.lower() != _r3_attestation_hash(
            artifact_id=self.artifact_id,
            artifact_version=self.artifact_version,
            artifact_content_hash=self.artifact_content_hash,
            decision_id=self.decision_id,
            decision_version=self.decision_version,
            decision_content_hash=self.decision_content_hash,
            approved_at=self.approved_at,
            valid_until=self.valid_until,
            retired_at=self.retired_at,
        ):
            raise ValueError("R3 promotion attestation content_hash mismatch")

    def is_active_at(self, as_of: datetime) -> bool:
        """Return whether this exact approval is active at the supplied cutoff."""

        _require_aware(as_of, "as_of")
        return self.approved_at <= as_of < self.valid_until and (
            self.retired_at is None or as_of < self.retired_at
        )


def _r3_attestation_hash(
    *,
    artifact_id: str,
    artifact_version: str,
    artifact_content_hash: str,
    decision_id: str,
    decision_version: str,
    decision_content_hash: str,
    approved_at: datetime,
    valid_until: datetime,
    retired_at: datetime | None,
) -> str:
    return _hash_parts(
        "r3-promotion-attestation-for-r4.v1",
        artifact_id,
        artifact_version,
        artifact_content_hash.lower(),
        decision_id,
        decision_version,
        decision_content_hash.lower(),
        _utc_text(approved_at),
        _utc_text(valid_until),
        "" if retired_at is None else _utc_text(retired_at),
    )


__all__ = [
    "ExactR3PromotionAttestation",
    "R4AssetCovarianceEvidence",
    "R4AssetReturn",
    "R4MacroExposureProjectionEvidence",
    "R4OOSReturnPathEvidence",
    "R4RegimeAssignmentEvidence",
    "R4ReturnObservation",
]
