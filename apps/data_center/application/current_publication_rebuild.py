"""Application use cases for rebuilding full-universe current publications."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Protocol, runtime_checkable
from uuid import NAMESPACE_URL, uuid5

from apps.data_center.domain.control_plane import (
    CanonicalPublication,
    CoverageSnapshot,
    PublicationFactReference,
    PublicationScopeBlock,
    PublicationState,
)
from apps.data_center.domain.market_time import (
    cn_market_date_from_observation,
    cn_market_session_close_utc,
)
from apps.data_center.domain.protocols import PublicationPolicyRepositoryProtocol
from apps.data_center.domain.publication_evidence import validate_publication_evidence
from apps.data_center.domain.publication_snapshot_policy import publication_selected_source_summary

from .control_plane import CanonicalPublicationRepositoryPort, PublishCanonicalDatasetUseCase
from .publication_idempotence import publication_replay_matches
from .publication_utils import (
    current_publication_id_for_hash,
    publication_hash,
    publication_member_from_reference,
)

_EVIDENCE_ASSET_CODE_LIMIT = 20


class CurrentPublicationCandidateRepositoryProtocol(Protocol):
    """Port selecting the decision-current canonical facts for an asset universe."""

    def list_current_publication_candidates(
        self,
        asset_codes: tuple[str, ...],
    ) -> list[PublicationFactReference]:
        """Return deterministic current fact references for the requested assets."""


@runtime_checkable
class TargetDatePublicationObservationProbeProtocol(Protocol):
    """Port proving whether requested assets have persisted observations on one date."""

    def list_asset_codes_with_observation_on_date(
        self,
        asset_codes: tuple[str, ...],
        observation_date: date,
    ) -> tuple[str, ...]:
        """Return exact requested asset identities observed on the target market date."""


@dataclass(frozen=True)
class CurrentPublicationDataset:
    """Static identity for one full-universe current publication."""

    dataset_key: str
    fact_table: str
    created_by: str

    def __post_init__(self) -> None:
        for field_name in ("dataset_key", "fact_table", "created_by"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"CurrentPublicationDataset.{field_name} cannot be empty")


@dataclass(frozen=True)
class CurrentPublicationScopeExclusion:
    """One externally verified asset exclusion for a dataset-specific current scope."""

    asset_code: str
    reason_code: str
    target_trade_date: date
    evidence_source: str

    def __post_init__(self) -> None:
        if not self.asset_code.strip() or self.asset_code != self.asset_code.strip().upper():
            raise ValueError("Current publication scope exclusion asset code is not canonical")
        if not self.reason_code.strip() or self.reason_code != self.reason_code.strip():
            raise ValueError("Current publication scope exclusion reason code is not canonical")
        if not isinstance(self.target_trade_date, date) or isinstance(
            self.target_trade_date, datetime
        ):
            raise ValueError("Current publication scope exclusion target date is invalid")
        if not self.evidence_source.strip() or self.evidence_source != self.evidence_source.strip():
            raise ValueError("Current publication scope exclusion evidence source is required")


@dataclass(frozen=True)
class CurrentPublicationPreview:
    """Read-only coverage evidence for one proposed current publication."""

    dataset_key: str
    requested_asset_count: int
    covered_asset_count: int
    member_count: int
    missing_asset_codes: tuple[str, ...]
    unexpected_asset_codes: tuple[str, ...]
    oldest_observed_at: datetime | None
    newest_observed_at: datetime | None

    @property
    def ready(self) -> bool:
        """Return whether the selection exactly covers a non-empty universe."""

        return (
            self.requested_asset_count > 0
            and self.covered_asset_count == self.requested_asset_count
            and self.member_count > 0
            and not self.missing_asset_codes
            and not self.unexpected_asset_codes
        )

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe preview evidence with bounded code samples."""

        return {
            "dataset_key": self.dataset_key,
            "ready": self.ready,
            "requested_asset_count": self.requested_asset_count,
            "covered_asset_count": self.covered_asset_count,
            "member_count": self.member_count,
            "missing_asset_count": len(self.missing_asset_codes),
            "missing_asset_codes": list(self.missing_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]),
            "missing_asset_codes_truncated": (
                len(self.missing_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "unexpected_asset_count": len(self.unexpected_asset_codes),
            "unexpected_asset_codes": list(
                self.unexpected_asset_codes[:_EVIDENCE_ASSET_CODE_LIMIT]
            ),
            "unexpected_asset_codes_truncated": (
                len(self.unexpected_asset_codes) > _EVIDENCE_ASSET_CODE_LIMIT
            ),
            "oldest_observed_at": (
                self.oldest_observed_at.isoformat() if self.oldest_observed_at is not None else None
            ),
            "newest_observed_at": (
                self.newest_observed_at.isoformat() if self.newest_observed_at is not None else None
            ),
        }


@dataclass(frozen=True)
class _CurrentPublicationSelection:
    """Internal exact selection shared by preview and mutation paths."""

    asset_codes: tuple[str, ...]
    references: tuple[PublicationFactReference, ...]
    excluded_target_date_asset_codes: tuple[str, ...]
    preview: CurrentPublicationPreview


def _valuation_reference_trade_date(reference: PublicationFactReference) -> date:
    """Return the validated trade date encoded by one valuation natural key."""

    parts = reference.natural_key.split(":")
    if len(parts) < 3:
        raise ValueError("Current valuation natural key lacks its trade date and source")
    asset_code, raw_trade_date = parts[0], parts[1]
    try:
        target_trade_date = date.fromisoformat(raw_trade_date)
    except ValueError as exc:
        raise ValueError("Current valuation natural key has an invalid trade date") from exc
    natural_key_source = ":".join(parts[2:])
    if (
        target_trade_date.isoformat() != raw_trade_date
        or not asset_code.strip()
        or natural_key_source != reference.source
    ):
        raise ValueError("Current valuation natural key identity is inconsistent")
    return target_trade_date


def _valuation_target_trade_date(
    references: Sequence[PublicationFactReference],
) -> date:
    """Return the one trade date shared by selected valuation facts."""

    if not references:
        raise ValueError("Partial current valuation requires selected valuation facts")
    target_dates = {_valuation_reference_trade_date(reference) for reference in references}
    if len(target_dates) != 1:
        raise ValueError("Current valuation candidates must share one target trade date")
    return next(iter(target_dates))


class CurrentPublicationRebuildUseCase:
    """Publish one immutable current snapshot only at exact universe coverage."""

    publication_key = "current"

    def __init__(
        self,
        *,
        dataset: CurrentPublicationDataset,
        candidate_repository: CurrentPublicationCandidateRepositoryProtocol,
        publication_repository: CanonicalPublicationRepositoryPort,
        policy_repository: PublicationPolicyRepositoryProtocol,
    ) -> None:
        self.dataset = dataset
        self._candidates = candidate_repository
        self._publications = publication_repository
        self._policies = policy_repository
        self._publisher = PublishCanonicalDatasetUseCase(publication_repository)

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime,
        scope_exclusions: Sequence[CurrentPublicationScopeExclusion] = (),
        required_observation_date: date | None = None,
    ) -> CurrentPublicationPreview:
        """Inspect exact coverage without writing publication state."""

        normalized_codes = self._normalize_asset_codes(asset_codes)
        exclusions = self._normalize_scope_exclusions(
            asset_codes=normalized_codes,
            scope_exclusions=scope_exclusions,
        )
        selection = self._select(
            asset_codes=normalized_codes,
            published_at=published_at,
            excluded_asset_codes=frozenset(item.asset_code for item in exclusions),
            exclusion_target_trade_date=(exclusions[0].target_trade_date if exclusions else None),
            required_observation_date=required_observation_date,
        )
        self._validate_quote_suspension_candidate_conflicts(
            selection=selection,
            exclusions=exclusions,
        )
        return selection.preview

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime,
        run_id: str = "",
        scope_exclusions: Sequence[CurrentPublicationScopeExclusion] = (),
        required_observation_date: date | None = None,
    ) -> CanonicalPublication:
        """Build and atomically publish a complete current member snapshot."""

        normalized_codes = self._normalize_asset_codes(asset_codes)
        exclusions = self._normalize_scope_exclusions(
            asset_codes=normalized_codes,
            scope_exclusions=scope_exclusions,
        )
        selection = self._select(
            asset_codes=normalized_codes,
            published_at=published_at,
            excluded_asset_codes=frozenset(item.asset_code for item in exclusions),
            exclusion_target_trade_date=(exclusions[0].target_trade_date if exclusions else None),
            required_observation_date=required_observation_date,
        )
        policy = self._policies.get_active(self.dataset.dataset_key)
        if policy is None:
            raise ValueError(f"No active publication policy for {self.dataset.dataset_key}")
        if policy.dataset.value != self.dataset.dataset_key:
            raise ValueError("Publication policy dataset mismatch")
        coverage_ratio = (
            selection.preview.covered_asset_count / selection.preview.requested_asset_count
        )
        partial_valuation_allowed = (
            self.dataset.dataset_key == "equity.valuation.fact"
            and policy.allow_partial
            and policy.uses_versioned_evidence
            and coverage_ratio >= policy.minimum_coverage_ratio
            and selection.preview.member_count > 0
            and not selection.preview.unexpected_asset_codes
        )
        suspension_scope_allowed = self._validate_quote_suspension_scope(
            selection=selection,
            exclusions=exclusions,
            policy_uses_versioned_evidence=policy.uses_versioned_evidence,
            run_id=run_id,
        )
        if not selection.preview.ready and not (
            partial_valuation_allowed or suspension_scope_allowed
        ):
            missing = ",".join(selection.preview.missing_asset_codes[:20])
            unexpected = ",".join(selection.preview.unexpected_asset_codes[:20])
            raise ValueError(
                "Current publication is missing active assets or contains unexpected assets: "
                f"missing=[{missing}] unexpected=[{unexpected}]"
            )
        if "payload_hash" in policy.required_evidence and any(
            not reference.raw_payload_hash.strip() for reference in selection.references
        ):
            raise ValueError("Current publication requires payload_hash evidence")

        validate_publication_evidence(policy, selection.references, published_at=published_at)
        is_valuation_partial = bool(selection.preview.missing_asset_codes) and not exclusions
        source_summary = publication_selected_source_summary(selection.references)
        block_target_trade_date = (
            _valuation_target_trade_date(selection.references) if is_valuation_partial else None
        )
        if is_valuation_partial and not run_id.strip():
            raise ValueError("Partial current valuation requires publication run id")
        block_drafts = (
            tuple(
                PublicationScopeBlock(
                    asset_code=item.asset_code,
                    reason_code=item.reason_code,
                    target_trade_date=item.target_trade_date,
                    source=source_summary,
                    publication_run_id=run_id,
                    policy_version=policy.identity,
                    evidence_source=item.evidence_source,
                )
                for item in exclusions
            )
            if exclusions
            else tuple(
                PublicationScopeBlock(
                    asset_code=asset_code,
                    reason_code="valuation_source_data_unavailable",
                    target_trade_date=block_target_trade_date,
                    source=source_summary,
                    publication_run_id=run_id,
                    policy_version=policy.identity,
                )
                for asset_code in selection.preview.missing_asset_codes
            )
        )
        digest = publication_hash(
            selection.references,
            policy_identity=policy.identity if policy.uses_versioned_evidence else None,
            scope_blocks=block_drafts,
        )
        publication_id = current_publication_id_for_hash(
            self.dataset.dataset_key,
            self.publication_key,
            digest,
        )
        scope_blocks = tuple(
            replace(block, publication_id=publication_id) for block in block_drafts
        )
        current = self._publications.get_current(
            self.dataset.dataset_key,
            self.publication_key,
        )
        if current is not None and publication_replay_matches(
            policy,
            current,
            selection.references,
            self._publications.list_members(current.publication_id),
            knowledge_cutoff=published_at,
            scope_blocks=scope_blocks,
        ):
            return current

        members = tuple(
            publication_member_from_reference(
                reference,
                member_id=str(uuid5(uuid5(NAMESPACE_URL, publication_id), reference.natural_key)),
                publication_id=publication_id,
                dataset_key=self.dataset.dataset_key,
            )
            for reference in selection.references
        )
        as_of = max(reference.observed_at for reference in selection.references)
        has_scope_blocks = bool(scope_blocks)
        coverage_requested = (
            len(selection.asset_codes) if has_scope_blocks else len(selection.references)
        )
        coverage_eligible = (
            selection.preview.covered_asset_count if has_scope_blocks else len(selection.references)
        )
        publication = CanonicalPublication(
            publication_id=publication_id,
            dataset_key=self.dataset.dataset_key,
            publication_key=self.publication_key,
            policy_version=policy.identity,
            state=PublicationState.PUBLISHED,
            selected_source=source_summary,
            publication_hash=digest,
            coverage=CoverageSnapshot(
                coverage_id=str(uuid5(NAMESPACE_URL, f"coverage:{publication_id}")),
                publication_id=publication_id,
                requested_count=coverage_requested,
                eligible_count=coverage_eligible,
                selected_count=len(selection.references),
                missing_count=len(scope_blocks),
                conflict_count=0,
                generated_at=published_at,
            ),
            member_count=len(members),
            conflict_count=0,
            as_of=as_of,
            published_at=published_at,
            created_by=self.dataset.created_by,
            run_id=run_id,
            scope_blocks=scope_blocks,
        )
        return self._publisher.execute(
            policy=policy,
            publication=publication,
            members=members,
        )

    def _validate_quote_suspension_scope(
        self,
        *,
        selection: _CurrentPublicationSelection,
        exclusions: tuple[CurrentPublicationScopeExclusion, ...],
        policy_uses_versioned_evidence: bool,
        run_id: str,
    ) -> bool:
        """Accept only an exact, fully evidenced quote suspension partition."""

        if not exclusions:
            return False
        if self.dataset.dataset_key != "equity.quote.snapshot":
            raise ValueError("Scope exclusions are unsupported for this current dataset")
        if not policy_uses_versioned_evidence:
            raise ValueError("Quote suspension scope requires a versioned publication policy")
        if not run_id.strip():
            raise ValueError("Quote suspension scope requires publication run id")
        exclusion_codes = {item.asset_code for item in exclusions}
        if exclusion_codes != set(selection.preview.missing_asset_codes):
            raise ValueError("Quote suspension scope exclusions must match publication gaps")
        if selection.preview.unexpected_asset_codes:
            raise ValueError("Quote suspension scope contains unexpected assets")
        if not selection.references:
            raise ValueError("Quote suspension scope cannot exclude the full requested universe")
        if any(item.reason_code != "quote_full_day_suspension" for item in exclusions):
            raise ValueError("Quote suspension scope has an unsupported scope exclusion")
        target_dates = {item.target_trade_date for item in exclusions}
        if len(target_dates) != 1:
            raise ValueError("Quote suspension scope must share one target trade date")
        target_trade_date = next(iter(target_dates))
        self._validate_quote_suspension_candidate_conflicts(
            selection=selection,
            exclusions=exclusions,
        )
        if any(
            cn_market_date_from_observation(reference.observed_at) != target_trade_date
            for reference in selection.references
        ):
            raise ValueError("Quote suspension scope target trade date differs from members")
        return selection.preview.covered_asset_count == (
            selection.preview.requested_asset_count - len(exclusions)
        )

    @staticmethod
    def _validate_quote_suspension_candidate_conflicts(
        *,
        selection: _CurrentPublicationSelection,
        exclusions: tuple[CurrentPublicationScopeExclusion, ...],
    ) -> None:
        """Reject a full-day suspension claim contradicted by persisted target-day quotes."""

        if not exclusions:
            return
        if selection.excluded_target_date_asset_codes:
            raise ValueError(
                "Quote suspension scope conflicts with a target-session quote observation"
            )

    def _normalize_scope_exclusions(
        self,
        *,
        asset_codes: tuple[str, ...],
        scope_exclusions: Sequence[CurrentPublicationScopeExclusion],
    ) -> tuple[CurrentPublicationScopeExclusion, ...]:
        """Validate exclusions before they can narrow candidate selection."""

        exclusions = tuple(sorted(scope_exclusions, key=lambda item: item.asset_code))
        if not exclusions:
            return ()
        if self.dataset.dataset_key != "equity.quote.snapshot":
            raise ValueError("Scope exclusions are unsupported for this current dataset")
        exclusion_codes = {item.asset_code for item in exclusions}
        if len(exclusion_codes) != len(exclusions):
            raise ValueError("Current publication scope exclusions must use unique asset codes")
        requested_codes = set(asset_codes)
        if not exclusion_codes.issubset(requested_codes):
            raise ValueError("Quote suspension scope exclusions must match publication gaps")
        if exclusion_codes == requested_codes:
            raise ValueError("Quote suspension scope cannot exclude the full requested universe")
        if any(item.reason_code != "quote_full_day_suspension" for item in exclusions):
            raise ValueError("Quote suspension scope has an unsupported scope exclusion")
        target_dates = {item.target_trade_date for item in exclusions}
        if len(target_dates) != 1:
            raise ValueError("Quote suspension scope must share one target trade date")
        return exclusions

    @staticmethod
    def _normalize_asset_codes(asset_codes: Sequence[str]) -> tuple[str, ...]:
        """Return one sorted, canonical, non-empty asset universe."""

        normalized_codes = tuple(
            sorted(
                {
                    str(asset_code or "").strip().upper()
                    for asset_code in asset_codes
                    if str(asset_code or "").strip()
                }
            )
        )
        if not normalized_codes:
            raise ValueError("active asset universe cannot be empty")
        return normalized_codes

    def _select(
        self,
        *,
        asset_codes: tuple[str, ...],
        published_at: datetime,
        excluded_asset_codes: frozenset[str] = frozenset(),
        exclusion_target_trade_date: date | None = None,
        required_observation_date: date | None = None,
    ) -> _CurrentPublicationSelection:
        """Normalize a universe and validate deterministic candidate identities."""

        if published_at.tzinfo is None or published_at.utcoffset() is None:
            raise ValueError("published_at must be timezone-aware")
        requested = set(asset_codes)
        eligible = requested - excluded_asset_codes
        eligible_codes = tuple(sorted(eligible))
        references = self._load_references(
            asset_codes=eligible_codes,
            published_at=published_at,
            required_observation_date=required_observation_date,
        )
        excluded_target_date_codes: tuple[str, ...] = ()
        if excluded_asset_codes:
            if exclusion_target_trade_date is None:
                raise ValueError("Quote suspension scope requires a target trade date")
            if not isinstance(
                self._candidates,
                TargetDatePublicationObservationProbeProtocol,
            ):
                raise ValueError("Quote suspension scope requires a target-date observation probe")
            probed_codes = self._candidates.list_asset_codes_with_observation_on_date(
                tuple(sorted(excluded_asset_codes)),
                exclusion_target_trade_date,
            )
            excluded_target_date_codes = tuple(
                sorted(str(code or "").strip().upper() for code in probed_codes)
            )
        if (
            any(not code for code in excluded_target_date_codes)
            or len(excluded_target_date_codes) != len(set(excluded_target_date_codes))
            or not set(excluded_target_date_codes).issubset(excluded_asset_codes)
        ):
            raise ValueError("Quote suspension candidate probe contains unexpected assets")

        covered = {
            reference.natural_key.split(":", 1)[0].strip().upper() for reference in references
        }
        missing = tuple(sorted((eligible - covered).union(excluded_asset_codes)))
        unexpected = tuple(sorted(covered - eligible))
        observations = [reference.observed_at for reference in references]
        preview = CurrentPublicationPreview(
            dataset_key=self.dataset.dataset_key,
            requested_asset_count=len(asset_codes),
            covered_asset_count=len(covered & eligible),
            member_count=len(references),
            missing_asset_codes=missing,
            unexpected_asset_codes=unexpected,
            oldest_observed_at=min(observations) if observations else None,
            newest_observed_at=max(observations) if observations else None,
        )
        return _CurrentPublicationSelection(
            asset_codes=asset_codes,
            references=references,
            excluded_target_date_asset_codes=excluded_target_date_codes,
            preview=preview,
        )

    def _load_references(
        self,
        *,
        asset_codes: tuple[str, ...],
        published_at: datetime,
        required_observation_date: date | None,
    ) -> tuple[PublicationFactReference, ...]:
        """Load and validate deterministic candidate identities for one scope."""

        if not asset_codes:
            return ()
        by_natural_key: dict[str, PublicationFactReference] = {}
        by_fact_reference: dict[tuple[str, str], str] = {}
        for reference in self._candidates.list_current_publication_candidates(asset_codes):
            if reference.fact_table != self.dataset.fact_table:
                raise ValueError(
                    f"Current publication fact table mismatch for {self.dataset.dataset_key}"
                )
            if reference.observed_at > published_at:
                raise ValueError(
                    f"Current publication contains a future observation for "
                    f"{self.dataset.dataset_key}"
                )
            observation_date = cn_market_date_from_observation(reference.observed_at)
            reference_date = observation_date
            if self.dataset.dataset_key == "equity.valuation.fact":
                reference_date = _valuation_reference_trade_date(reference)
                if reference_date != observation_date:
                    raise ValueError(
                        "Current valuation trade date differs from its observation date"
                    )
            if (
                required_observation_date is not None
                and reference_date != required_observation_date
            ):
                continue
            if self.dataset.dataset_key == "equity.quote.snapshot":
                if reference.observed_at < cn_market_session_close_utc(observation_date):
                    raise ValueError(
                        "Current quote publication contains an observation before the "
                        "official China-market close"
                    )
            prior = by_natural_key.get(reference.natural_key)
            if prior is not None and prior.fact_pk != reference.fact_pk:
                raise ValueError("Current publication natural key resolves to multiple facts")
            fact_identity = (reference.fact_table, reference.fact_pk)
            prior_natural_key = by_fact_reference.get(fact_identity)
            if prior_natural_key is not None and prior_natural_key != reference.natural_key:
                raise ValueError("Current publication fact resolves to multiple natural keys")
            by_natural_key[reference.natural_key] = reference
            by_fact_reference[fact_identity] = reference.natural_key
        return tuple(sorted(by_natural_key.values(), key=lambda item: item.natural_key))


@dataclass(frozen=True)
class CoreCurrentPublicationPreview:
    """Read-only combined preview for all configured core datasets."""

    datasets: tuple[CurrentPublicationPreview, ...]

    @property
    def ready(self) -> bool:
        """Return whether every configured dataset has exact universe coverage."""

        return bool(self.datasets) and all(item.ready for item in self.datasets)

    @property
    def member_count(self) -> int:
        """Return the proposed member count across all datasets."""

        return sum(item.member_count for item in self.datasets)

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe combined preview evidence."""

        return {
            "ready": self.ready,
            "dataset_count": len(self.datasets),
            "member_count": self.member_count,
            "datasets": [item.to_dict() for item in self.datasets],
        }


@dataclass(frozen=True)
class CoreCurrentPublicationRebuildResult:
    """Exact publication identities committed by one coordinated rebuild."""

    publications: tuple[CanonicalPublication, ...]
    covered_asset_count: int

    def __post_init__(self) -> None:
        if self.covered_asset_count <= 0:
            raise ValueError("covered_asset_count must be positive")

    @property
    def published_count(self) -> int:
        """Return the committed member count across all publications."""

        return sum(publication.member_count for publication in self.publications)

    @property
    def publication_ids(self) -> tuple[str, ...]:
        """Return committed immutable publication ids."""

        return tuple(publication.publication_id for publication in self.publications)

    @property
    def run_id(self) -> str:
        """Return the single publication run identity shared by every dataset."""

        run_ids = {publication.run_id for publication in self.publications}
        if len(run_ids) != 1:
            raise ValueError("Core current publications do not share one run identity")
        return next(iter(run_ids))

    def to_dict(self) -> dict[str, object]:
        """Return stable JSON-safe publication evidence."""

        return {
            "published_count": self.published_count,
            "run_id": self.run_id,
            "publication_ids": list(self.publication_ids),
            "datasets": [
                {
                    "dataset_key": publication.dataset_key,
                    "publication_id": publication.publication_id,
                    "publication_hash": publication.publication_hash,
                    "member_count": publication.member_count,
                    "requested_asset_count": publication.coverage.requested_count,
                    "covered_asset_count": publication.coverage.eligible_count,
                    "missing_asset_count": publication.coverage.missing_count,
                    "outcome": ("partial" if publication.coverage.missing_count else "success"),
                    "scope_blocks": [block.to_dict() for block in publication.scope_blocks],
                    "policy_identity": publication.policy_version,
                    "as_of": publication.as_of.isoformat() if publication.as_of else None,
                    "published_at": (
                        publication.published_at.isoformat() if publication.published_at else None
                    ),
                }
                for publication in self.publications
            ],
        }


class CoreCurrentPublicationRebuildUseCase:
    """Preview or atomically publish all configured core current datasets."""

    def __init__(
        self,
        *,
        rebuilders: tuple[CurrentPublicationRebuildUseCase, ...],
        transaction: Callable[[], AbstractContextManager[None]],
        authority_preflight: Callable[[datetime], None],
    ) -> None:
        if not rebuilders:
            raise ValueError("At least one current-publication rebuilder is required")
        dataset_keys = [rebuilder.dataset.dataset_key for rebuilder in rebuilders]
        if len(dataset_keys) != len(set(dataset_keys)):
            raise ValueError("Current-publication rebuilders must have unique datasets")
        self._rebuilders = rebuilders
        self._transaction = transaction
        self._authority_preflight = authority_preflight

    def preview(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime | None = None,
        scope_exclusions_by_dataset: (
            Mapping[str, Sequence[CurrentPublicationScopeExclusion]] | None
        ) = None,
        required_observation_dates: Mapping[str, date] | None = None,
    ) -> CoreCurrentPublicationPreview:
        """Return one consistent read-only coverage preview."""

        observed_at = published_at or datetime.now(UTC)
        exclusions_by_dataset = scope_exclusions_by_dataset or {}
        self._validate_scope_exclusion_dataset_keys(exclusions_by_dataset)
        observation_dates = required_observation_dates or {}
        self._validate_dataset_keys(
            observation_dates,
            label="required observation dates",
        )
        with self._transaction():
            previews = tuple(
                rebuilder.preview(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                    scope_exclusions=exclusions_by_dataset.get(
                        rebuilder.dataset.dataset_key,
                        (),
                    ),
                    required_observation_date=observation_dates.get(rebuilder.dataset.dataset_key),
                )
                for rebuilder in self._rebuilders
            )
        return CoreCurrentPublicationPreview(datasets=previews)

    def execute(
        self,
        *,
        asset_codes: Sequence[str],
        published_at: datetime | None = None,
        run_id: str = "",
        scope_exclusions_by_dataset: (
            Mapping[str, Sequence[CurrentPublicationScopeExclusion]] | None
        ) = None,
        required_observation_dates: Mapping[str, date] | None = None,
    ) -> CoreCurrentPublicationRebuildResult:
        """Publish all datasets in one transaction or leave all current rows intact."""

        observed_at = published_at or datetime.now(UTC)
        self._authority_preflight(observed_at)
        exclusions_by_dataset = scope_exclusions_by_dataset or {}
        self._validate_scope_exclusion_dataset_keys(exclusions_by_dataset)
        observation_dates = required_observation_dates or {}
        self._validate_dataset_keys(
            observation_dates,
            label="required observation dates",
        )
        with self._transaction():
            publications = tuple(
                rebuilder.execute(
                    asset_codes=asset_codes,
                    published_at=observed_at,
                    run_id=run_id,
                    scope_exclusions=exclusions_by_dataset.get(rebuilder.dataset.dataset_key, ()),
                    required_observation_date=observation_dates.get(rebuilder.dataset.dataset_key),
                )
                for rebuilder in self._rebuilders
            )
        covered_asset_count = len(
            {
                str(asset_code or "").strip().upper()
                for asset_code in asset_codes
                if str(asset_code or "").strip()
            }
        )
        return CoreCurrentPublicationRebuildResult(
            publications=publications,
            covered_asset_count=covered_asset_count,
        )

    def _validate_scope_exclusion_dataset_keys(
        self,
        exclusions_by_dataset: Mapping[
            str,
            Sequence[CurrentPublicationScopeExclusion],
        ],
    ) -> None:
        """Reject exclusions for datasets outside this coordinated rebuild."""

        self._validate_dataset_keys(
            exclusions_by_dataset,
            label="scope exclusions",
        )

    def _validate_dataset_keys(
        self,
        values_by_dataset: Mapping[str, object],
        *,
        label: str,
    ) -> None:
        """Reject per-dataset controls outside this coordinated rebuild."""

        known_dataset_keys = {rebuilder.dataset.dataset_key for rebuilder in self._rebuilders}
        unknown_dataset_keys = set(values_by_dataset) - known_dataset_keys
        if unknown_dataset_keys:
            raise ValueError(
                f"Current publication {label} contain unknown datasets: "
                + ",".join(sorted(unknown_dataset_keys))
            )


__all__ = [
    "CoreCurrentPublicationPreview",
    "CoreCurrentPublicationRebuildResult",
    "CoreCurrentPublicationRebuildUseCase",
    "CurrentPublicationCandidateRepositoryProtocol",
    "CurrentPublicationDataset",
    "CurrentPublicationPreview",
    "CurrentPublicationRebuildUseCase",
    "CurrentPublicationScopeExclusion",
    "TargetDatePublicationObservationProbeProtocol",
]
