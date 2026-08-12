"""Read-only Macro Factor adapter over Data Center canonical R3 PIT evidence."""

from __future__ import annotations

from typing import Any, Protocol, cast

from apps.macro_factor.domain.entities import (
    PITDatasetSlice,
    PITInferenceCalendarPeriodEvidence,
    PITManifestEvidence,
    PITSelectedFactVersion,
)
from apps.macro_factor.domain.runner_inputs import (
    InferenceTargetCalendarPeriod,
    PITInferenceRow,
    PITResearchDataset,
    PITResearchRow,
    ProxyObservation,
)


class _ExactPITProjectionProvider(Protocol):
    @property
    def unit_of_work_key(self) -> str: ...

    def get_exact_projection(
        self, *, manifest_id: str, expected_manifest_hash: str | None
    ) -> object: ...


class DataCenterMacroFactorPITProjectionAdapter:
    """Expose only exact manifest/dataset reads; never a runner or writer."""

    __slots__ = ("_expected_provider_id", "_expected_uow_key", "_provider")

    def __init__(self, provider: object) -> None:
        self._provider = cast(_ExactPITProjectionProvider, provider)
        self._expected_provider_id = id(provider)
        self._expected_uow_key = _uow_key(self._provider.unit_of_work_key)

    @property
    def unit_of_work_key(self) -> str:
        """Return the unchanged Data Center read/snapshot identity."""

        self._require_live_provider()
        return self._expected_uow_key

    def get_manifest(self, manifest_id: str) -> PITManifestEvidence | None:
        """Return one full canonical manifest projection or ``None``."""

        try:
            manifest_id = _token(manifest_id, "manifest_id")
            projection = self._read(manifest_id=manifest_id, expected_manifest_hash=None)
            return None if projection is None else _to_manifest(projection)
        except Exception:
            return None

    def get_dataset(
        self,
        *,
        manifest_id: str,
        manifest_hash: str,
        target_code: str,
        candidate_asset_codes: tuple[str, ...],
    ) -> PITResearchDataset | None:
        """Build label-aware design rows and one label-free inference row in memory."""

        try:
            manifest_id = _token(manifest_id, "manifest_id")
            manifest_hash = _hash(manifest_hash, "manifest_hash")
            target_code = _token(target_code, "target_code")
            candidates = _candidate_codes(candidate_asset_codes)
            projection = self._read(
                manifest_id=manifest_id,
                expected_manifest_hash=manifest_hash,
            )
            if projection is None:
                return None
            definition = projection.source.definition
            if (
                definition.target_code != target_code
                or definition.candidate_asset_codes != candidates
            ):
                return None
            return _to_dataset(projection, _to_manifest(projection))
        except Exception:
            return None

    def _read(
        self,
        *,
        manifest_id: str,
        expected_manifest_hash: str | None,
    ) -> Any | None:
        self._require_live_provider()
        value = self._provider.get_exact_projection(
            manifest_id=manifest_id,
            expected_manifest_hash=expected_manifest_hash,
        )
        self._require_live_provider()
        if value is None:
            return None
        validator = getattr(value, "validated_copy", None)
        if not callable(validator):
            raise TypeError("Data Center PIT projection is not recursively validated")
        projection = cast(Any, validator())
        if projection != value:
            raise ValueError("Data Center PIT projection is noncanonical")
        if projection.manifest_id != manifest_id or (
            expected_manifest_hash is not None
            and projection.manifest_hash.lower() != expected_manifest_hash
        ):
            raise ValueError("Data Center PIT projection identity differs")
        return projection

    def _require_live_provider(self) -> None:
        if (
            id(self._provider) != self._expected_provider_id
            or _uow_key(self._provider.unit_of_work_key) != self._expected_uow_key
        ):
            raise ValueError("Data Center PIT projection provider changed")


def _to_manifest(projection: Any) -> PITManifestEvidence:
    definition = projection.source.definition
    calendar = definition.calendar
    inference = definition.inference_period
    return PITManifestEvidence.create(
        manifest_id=projection.manifest_id,
        manifest_hash=projection.manifest_hash,
        as_of_time=projection.manifest_as_of,
        knowledge_scope=projection.knowledge_scope,
        calendar_id=calendar.calendar_id,
        calendar_version=calendar.calendar_version,
        calendar_hash=calendar.content_hash,
        inference_periods=(
            PITInferenceCalendarPeriodEvidence.create(
                calendar_id=calendar.calendar_id,
                calendar_version=calendar.calendar_version,
                calendar_hash=calendar.content_hash,
                period_id=inference.period_id,
                period_start=inference.target_period_start,
                period_end=inference.target_period_end,
            ),
        ),
        slices=tuple(
            sorted(
                (
                    PITDatasetSlice(
                        dataset_key=fact.dataset_key,
                        business_key=fact.business_key,
                        version_ids=(fact.version_id,),
                        selected_versions=(_selected_version(fact),),
                    )
                    for fact in projection.facts
                ),
                key=lambda item: (item.dataset_key, item.business_key),
            )
        ),
        coverage_ratio=projection.coverage_ratio,
        missing_count=projection.missing_count,
        estimated_count=projection.estimated_count,
        unknown_count=projection.unknown_count,
        is_verified=projection.is_verified,
    ).validated_copy()


def _to_dataset(
    projection: Any,
    manifest: PITManifestEvidence,
) -> PITResearchDataset:
    definition = projection.source.definition
    facts = {(item.row_id, item.role.value, item.member_code): item for item in projection.facts}
    rows: list[PITResearchRow] = []
    inference_row: PITInferenceRow | None = None
    for period in definition.periods:
        proxies = tuple(
            ProxyObservation(
                asset_code=asset_code,
                value=facts[(period.row_id, "proxy", asset_code)].value,
                fact_version=_selected_version(facts[(period.row_id, "proxy", asset_code)]),
            )
            for asset_code in definition.candidate_asset_codes
        )
        available_at = max(item.fact_version.available_at for item in proxies)
        if period.kind.value == "historical":
            target = facts[
                (
                    period.row_id,
                    "target",
                    definition.target_code,
                )
            ]
            rows.append(
                PITResearchRow(
                    row_id=period.row_id,
                    observation_date=period.observation_date,
                    target_period_start=period.target_period_start,
                    target_period_end=period.target_period_end,
                    available_at=available_at,
                    label_available_at=target.available_at,
                    target_value=target.value,
                    target_fact_version=_selected_version(target),
                    proxies=proxies,
                )
            )
        else:
            target_period = InferenceTargetCalendarPeriod.create(
                calendar_id=definition.calendar.calendar_id,
                period_id=period.period_id,
                calendar_version=definition.calendar.calendar_version,
                calendar_hash=definition.calendar.content_hash,
                period_start=period.target_period_start,
                period_end=period.target_period_end,
            )
            inference_row = PITInferenceRow(
                row_id=period.row_id,
                observation_date=period.observation_date,
                available_at=available_at,
                target_period=target_period,
                proxies=proxies,
            )
    if inference_row is None:
        raise ValueError("Data Center source omitted its inference row")
    return PITResearchDataset(
        manifest_id=projection.manifest_id,
        manifest_hash=projection.manifest_hash,
        manifest_content_hash=manifest.content_hash,
        manifest_as_of=projection.manifest_as_of,
        target_code=definition.target_code,
        candidate_asset_codes=definition.candidate_asset_codes,
        rows=tuple(rows),
        inference_row=inference_row,
    ).validated_copy()


def _selected_version(fact: Any) -> PITSelectedFactVersion:
    return PITSelectedFactVersion(
        version_id=fact.version_id,
        content_hash=fact.content_hash,
        effective_at=fact.effective_at,
        available_at=fact.available_at,
    )


def _candidate_codes(value: object) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise ValueError("candidate_asset_codes must be an exact non-empty tuple")
    candidates = tuple(_token(item, "candidate_asset_code") for item in value)
    if candidates != tuple(sorted(set(candidates))):
        raise ValueError("candidate_asset_codes must be canonical")
    return candidates


def _uow_key(value: object) -> str:
    return _token(value, "unit_of_work_key")


def _token(value: object, field_name: str, *, maximum: int = 192) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact bounded token")
    return value


def _hash(value: object, field_name: str) -> str:
    text = _token(value, field_name, maximum=64)
    if len(text) != 64 or any(character not in "0123456789abcdefABCDEF" for character in text):
        raise ValueError(f"{field_name} must be a SHA-256 digest")
    return text.lower()


__all__ = ["DataCenterMacroFactorPITProjectionAdapter"]
