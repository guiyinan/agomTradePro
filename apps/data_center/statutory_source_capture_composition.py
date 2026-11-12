"""Compose configured public-document acquisition without legal-policy authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

from django.db import DEFAULT_DB_ALIAS, connections, transaction
from django.utils import timezone

from apps.data_center.application.egress_service import execute_provider_document_request
from apps.data_center.application.statutory_source_capture import (
    CaptureStatutorySourceDocumentUseCase,
)
from apps.data_center.application.statutory_source_catalog import (
    decode_statutory_source_catalog_profile,
)
from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.provider_document_response import PUBLIC_DOCUMENT_SOURCE_TYPE
from apps.data_center.domain.statutory_source_catalog import (
    StatutorySourceCatalogProfile,
    StatutorySourceDocumentCaptureRule,
)
from apps.data_center.domain.statutory_source_documents import StatutorySourceDocumentAppendResult
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.infrastructure.statutory_source_body_store import StatutorySourceBodyStore
from apps.data_center.infrastructure.statutory_source_repository import (
    DjangoStatutorySourceRepository,
)
from core.exceptions import DataValidationError

_CATALOG_CONFIG_KEY = "statutory_source_catalog"
_DATASET_KEY = "statutory_source_documents"


def _invalid(
    message: str, code: str = "STATUTORY_SOURCE_CONFIGURATION_INVALID"
) -> DataValidationError:
    """Classify configuration failures without exposing arbitrary provider JSON."""
    return DataValidationError(message, code=code)


def _fingerprint(value: dict[str, object]) -> str:
    """Hash explicit selected configuration facts with strict JSON encoding."""
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _publisher_scope(
    profile: StatutorySourceCatalogProfile, publisher: PublisherCatalogModel
) -> None:
    """Require every configured document to remain within its declared publisher origin.

    This is configured-origin consistency, not independent proof that a
    publisher is official or that any document is currently applicable law.
    """
    try:
        origin = urlsplit(publisher.website)
        root = origin.hostname
        port = 443 if origin.port is None else origin.port
    except ValueError as error:
        raise _invalid("Configured publisher website is invalid.") from error
    if (
        origin.scheme != "https"
        or not root
        or not root.isascii()
        or root != root.lower()
        or root.endswith(".")
        or origin.username is not None
        or origin.password is not None
        or origin.fragment
        or port <= 0
        or any(character.isspace() for character in publisher.website)
    ):
        raise _invalid("Configured publisher requires an explicit canonical HTTPS origin.")
    if any(host != root and not host.endswith(f".{root}") for host in profile.allowed_hosts):
        raise _invalid("Configured source hosts lie outside the declared publisher origin.")
    if any(
        (urlsplit(rule.revision.canonical_url).port or 443) != port for rule in profile.documents
    ):
        raise _invalid("Configured source port differs from the declared publisher origin.")


@dataclass(frozen=True, slots=True)
class _Configuration:
    """One immutable observation of mutable provider and publisher configuration."""

    profile: StatutorySourceCatalogProfile
    fingerprint: str


class ConfiguredStatutorySourceCaptureService:
    """Retain exact configured documents as unqualified historical evidence.

    Neither an active provider/catalog nor successful configured-origin checks
    authenticate legal status, activate a tax policy, or authorize financial
    posting. Existing egress audit remains best-effort. A configuration change
    after acquisition blocks this operation; already retained observations are
    preserved and remain unqualified.
    """

    def __init__(
        self,
        *,
        provider_id: int,
        body_store_root: Path,
        deployment_region: str,
        using: str = DEFAULT_DB_ALIAS,
    ) -> None:
        """Bind an explicit provider, private storage location, region and database alias."""
        if (
            type(provider_id) is not int
            or provider_id <= 0
            or not isinstance(body_store_root, Path)
        ):
            raise _invalid("Configured source provider or storage binding is invalid.")
        if any(
            type(value) is not str or not value or value != value.strip()
            for value in (using, deployment_region)
        ):
            raise _invalid("Configured source region or database alias is invalid.")
        self._provider_id = provider_id
        self._body_store_root = body_store_root
        self._deployment_region = deployment_region
        self._using = using

    def _configuration(self) -> _Configuration:
        """Read and briefly lock exact provider/publisher facts without network I/O."""
        with transaction.atomic(using=self._using):
            provider = (
                ProviderConfigModel._default_manager.using(self._using)
                .select_for_update()
                .filter(pk=self._provider_id)
                .first()
            )
            if (
                provider is None
                or not provider.is_active
                or provider.source_type != PUBLIC_DOCUMENT_SOURCE_TYPE
            ):
                raise _invalid("An active dedicated public-document provider is required.")
            if provider.http_url or provider.api_endpoint:
                raise _invalid("Public-document targets must come from exact catalog revisions.")
            raw: object = provider.extra_config
            if type(raw) is not dict or _CATALOG_CONFIG_KEY not in raw:
                raise _invalid("An explicit source catalog is required.")
            profile = decode_statutory_source_catalog_profile(raw[_CATALOG_CONFIG_KEY])
            if not profile.enabled:
                raise _invalid("The explicit source catalog is disabled.")
            publisher = (
                PublisherCatalogModel._default_manager.using(self._using)
                .select_for_update()
                .filter(code=profile.publisher_code)
                .first()
            )
            if publisher is None or not publisher.is_active:
                raise _invalid("An active explicitly selected publisher is required.")
            _publisher_scope(profile, publisher)
            return _Configuration(
                profile=profile,
                fingerprint=_fingerprint(
                    {
                        "provider_id": self._provider_id,
                        "provider_name": provider.name,
                        "source_type": provider.source_type,
                        "provider_active": provider.is_active,
                        "provider_updated_at": provider.updated_at.isoformat(),
                        "profile_sha256": profile.content_sha256,
                        "publisher_code": publisher.code,
                        "publisher_name": publisher.canonical_name,
                        "publisher_class": publisher.publisher_class,
                        "publisher_website": publisher.website,
                        "publisher_active": publisher.is_active,
                        "publisher_updated_at": publisher.updated_at.isoformat(),
                    }
                ),
            )

    def read_catalog(self) -> StatutorySourceCatalogProfile:
        """Read a validated configuration snapshot without granting source qualification."""
        return self._configuration().profile

    def capture_document(
        self, *, issuer: str, document_id: str, source_version: str
    ) -> StatutorySourceDocumentAppendResult:
        """Acquire one exact native key, retain its observation, then recheck configuration.

        Caller inputs select a configured identity; they cannot provide a URL,
        body, capture UUID, observation time, MIME policy or publisher binding.
        Mutable configuration is never locked while waiting on HTTP or files.
        """
        if connections[self._using].in_atomic_block:
            raise _invalid(
                "Document acquisition must precede any caller database transaction.",
                "STATUTORY_SOURCE_CAPTURE_OUTER_TRANSACTION",
            )
        snapshot = self._configuration()
        identity = (issuer, document_id, source_version)
        if any(type(value) is not str or not value or value != value.strip() for value in identity):
            raise _invalid("An exact native source identity is required.")
        selected = tuple(
            rule for rule in snapshot.profile.documents if rule.revision.identity_key == identity
        )
        if len(selected) != 1:
            raise _invalid(
                "The exact source revision is not configured.",
                "STATUTORY_SOURCE_DOCUMENT_NOT_CONFIGURED",
            )
        rule: StatutorySourceDocumentCaptureRule = selected[0]
        body_store = StatutorySourceBodyStore(self._body_store_root, max_body_bytes=rule.max_bytes)
        repository = DjangoStatutorySourceRepository(body_store=body_store, using=self._using)
        result = CaptureStatutorySourceDocumentUseCase(
            retainer=RetainStatutorySourceDocumentUseCase(
                body_store=body_store, document_repository=repository
            ),
            document_fetch=execute_provider_document_request,
            provider_id=self._provider_id,
            dataset_key=_DATASET_KEY,
            deployment_region=self._deployment_region,
        ).execute(
            revision=rule.revision,
            max_bytes=rule.max_bytes,
            allowed_media_types=rule.allowed_media_types,
        )
        if self._configuration().fingerprint != snapshot.fingerprint:
            raise _invalid(
                "Source configuration changed during acquisition; retained history is unqualified.",
                "STATUTORY_SOURCE_CAPTURE_CONFIGURATION_CHANGED",
            )
        checked_at = timezone.now()
        captured_at = result.capture.captured_at
        if captured_at > checked_at or checked_at - captured_at > timedelta(
            seconds=snapshot.profile.max_capture_age_seconds
        ):
            raise _invalid(
                "The retained response is outside its configured observation window.",
                "STATUTORY_SOURCE_CAPTURE_OUTSIDE_WINDOW",
            )
        return result


__all__ = ["ConfiguredStatutorySourceCaptureService"]
