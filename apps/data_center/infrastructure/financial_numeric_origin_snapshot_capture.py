"""Derive optional configured-origin snapshot metadata while a capture UOW is locked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.data_center.application.statutory_source_catalog import (
    StatutorySourceCatalogDecodeError,
    decode_statutory_source_catalog_profile,
)
from apps.data_center.domain.financial_numeric_origin_snapshot import (
    FinancialNumericOriginProviderFacts,
    FinancialNumericOriginPublisherFacts,
    FinancialNumericSourceOriginSnapshot,
    origin_configuration_sha256,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.provider_document_response import (
    PUBLIC_DOCUMENT_SOURCE_TYPE,
    normalize_document_content_type,
)
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
)
from apps.data_center.infrastructure.financial_numeric_origin_snapshot_codec import (
    encode_origin_snapshot,
)
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from core.exceptions import DataValidationError

_CATALOG_CONFIG_KEY = "statutory_source_catalog"


class FinancialNumericOriginSnapshotDerivationError(DataValidationError):
    """Capture-time profile/publisher facts could not produce a valid snapshot."""

    default_message = "Financial numeric origin snapshot could not be derived."
    default_code = "FINANCIAL_NUMERIC_ORIGIN_SNAPSHOT_INVALID"


@dataclass(frozen=True, slots=True)
class FinancialNumericOriginSnapshotSeed:
    """Validated current profile and locked non-secret provider/publisher facts."""

    profile: StatutorySourceCatalogProfile
    provider: FinancialNumericOriginProviderFacts
    publisher: FinancialNumericOriginPublisherFacts
    selected_rule_index: int


def _blocked(message: str) -> FinancialNumericOriginSnapshotDerivationError:
    """Build a stable derivation error without exposing source configuration."""

    return FinancialNumericOriginSnapshotDerivationError(message)


def select_rule_index(
    profile: StatutorySourceCatalogProfile,
    capture: FinancialNumericSourceDocumentCaptureReference,
) -> int:
    """Require one rule to match issuer, document, URL, body, size, and MIME exactly."""

    try:
        media_type = normalize_document_content_type(capture.content_type)
    except (TypeError, ValueError) as error:
        raise _blocked("Capture content type is invalid") from error
    matches = tuple(
        index
        for index, rule in enumerate(profile.documents)
        if (
            rule.revision.issuer == capture.issuer
            and rule.revision.document_id == capture.document_id
            and rule.revision.canonical_url == capture.canonical_url
            and rule.revision.body_sha256 == capture.body_sha256
            and rule.revision.body_size_bytes == capture.body_size_bytes
            and capture.body_size_bytes <= rule.max_bytes
            and media_type in rule.allowed_media_types
        )
    )
    if len(matches) != 1:
        raise _blocked("Capture has no unique exact statutory source catalog rule")
    return matches[0]


def load_origin_snapshot_seed(
    *,
    provider: ProviderConfigModel,
    capture: FinancialNumericSourceDocumentCaptureReference,
    using: str,
) -> FinancialNumericOriginSnapshotSeed:
    """Read locked provider/publisher rows and strictly decode the existing profile."""

    if (
        provider._state.db != using
        or provider.source_type != PUBLIC_DOCUMENT_SOURCE_TYPE
        or provider.is_active is not True
        or provider.http_url
        or provider.api_endpoint
    ):
        raise _blocked("Public-document provider is not an exact active source")
    extra_config: object = provider.extra_config
    if type(extra_config) is not dict or _CATALOG_CONFIG_KEY not in extra_config:
        raise _blocked("Statutory source catalog is not configured")
    try:
        profile = decode_statutory_source_catalog_profile(extra_config[_CATALOG_CONFIG_KEY])
    except (StatutorySourceCatalogDecodeError, TypeError, ValueError) as error:
        raise _blocked("Statutory source catalog is invalid") from error
    if not profile.enabled:
        raise _blocked("Statutory source catalog is disabled")
    selected_index = select_rule_index(profile, capture)
    publisher_row = (
        PublisherCatalogModel._default_manager.using(using)
        .select_for_update()
        .filter(code=profile.publisher_code)
        .first()
    )
    if publisher_row is None or publisher_row.is_active is not True:
        raise _blocked("Configured publisher is unavailable")
    try:
        provider_facts = FinancialNumericOriginProviderFacts(
            provider_id=provider.pk,
            name=provider.name,
            source_type=provider.source_type,
            is_active=provider.is_active,
            updated_at=provider.updated_at,
        )
        publisher_facts = FinancialNumericOriginPublisherFacts(
            code=publisher_row.code,
            canonical_name=publisher_row.canonical_name,
            publisher_class=publisher_row.publisher_class,
            website=publisher_row.website,
            is_active=publisher_row.is_active,
            updated_at=publisher_row.updated_at,
        )
        publisher_facts.validate_profile_scope(profile)
    except (TypeError, ValueError) as error:
        raise _blocked("Provider and publisher origin scope is invalid") from error
    return FinancialNumericOriginSnapshotSeed(
        profile=profile,
        provider=provider_facts,
        publisher=publisher_facts,
        selected_rule_index=selected_index,
    )


def make_origin_snapshot(
    *,
    seed: FinancialNumericOriginSnapshotSeed,
    capture_reference: FinancialNumericSourceDocumentCaptureReference,
    dataset_key: str,
    deployment_region: str,
    recorded_at: datetime,
) -> FinancialNumericSourceOriginSnapshot:
    """Construct snapshot facts tied to the exact immutable numeric capture row."""

    configuration_sha = origin_configuration_sha256(
        seed.provider,
        seed.publisher,
        seed.profile,
    )
    return FinancialNumericSourceOriginSnapshot(
        snapshot_id=capture_reference.capture_id,
        recorded_at=recorded_at,
        capture_reference=capture_reference,
        dataset_key=dataset_key,
        deployment_region=deployment_region,
        provider=seed.provider,
        publisher=seed.publisher,
        profile=seed.profile,
        selected_rule_index=seed.selected_rule_index,
        configuration_sha256=configuration_sha,
    )


def derive_origin_snapshot_for_capture(
    *,
    seed: FinancialNumericOriginSnapshotSeed | None,
    capture_reference: FinancialNumericSourceDocumentCaptureReference,
    dataset_key: str,
    deployment_region: str,
    recorded_at: datetime,
) -> tuple[dict[str, object] | None, str | None]:
    """Encode origin evidence after its provider/publisher rows have been locked.

    Invalid, absent, disabled, stale, or nonmatching origin data leaves the
    document capture intact with a null metadata pair. The profile is always
    read from the locked provider row; no caller-supplied snapshot exists. The
    caller must acquire every configuration lock before sampling ``recorded_at``.
    """

    if seed is None:
        return None, None
    try:
        snapshot = make_origin_snapshot(
            seed=seed,
            capture_reference=capture_reference,
            dataset_key=dataset_key,
            deployment_region=deployment_region,
            recorded_at=recorded_at,
        )
        if recorded_at < capture_reference.captured_at:
            return None, None
        payload, digest = encode_origin_snapshot(snapshot)
        return payload, digest
    except (DataValidationError, TypeError, ValueError, OverflowError):
        return None, None


def prepare_origin_snapshot_seed_for_capture(
    *,
    provider: ProviderConfigModel,
    capture_reference: FinancialNumericSourceDocumentCaptureReference,
    using: str,
) -> FinancialNumericOriginSnapshotSeed | None:
    """Lock and validate matching current config before the capture record clock is sampled."""

    try:
        return load_origin_snapshot_seed(
            provider=provider,
            capture=capture_reference,
            using=using,
        )
    except (DataValidationError, TypeError, ValueError, OverflowError):
        return None


__all__ = [
    "FinancialNumericOriginSnapshotDerivationError",
    "FinancialNumericOriginSnapshotSeed",
    "derive_origin_snapshot_for_capture",
    "load_origin_snapshot_seed",
    "make_origin_snapshot",
    "prepare_origin_snapshot_seed_for_capture",
    "select_rule_index",
]
