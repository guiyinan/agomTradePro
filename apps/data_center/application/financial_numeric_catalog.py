"""Application ports and use cases for exact financial numeric source metadata."""

from __future__ import annotations

import hashlib
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from apps.data_center.domain.egress_routing import EgressRequestContext, target_hostname
from apps.data_center.domain.financial_numeric_catalog import (
    FinancialNumericCatalogResolutionPurpose,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
    FinancialNumericSourceQualification,
)
from apps.data_center.domain.provider_document_response import (
    ProviderDocumentResponseCapture,
    normalize_document_content_type,
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from core.exceptions import DataValidationError

_MAX_DOCUMENT_TEXT = 240


class FinancialNumericSourceDocumentCaptureRepositoryPort(Protocol):
    """Persist one raw source-document capture after independent audit checks."""

    def append_document_capture(
        self,
        *,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        reference: FinancialNumericSourceDocumentCaptureReference,
        response: ProviderDocumentResponseCapture,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Retain exact bytes and append immutable capture metadata or fail closed."""
        ...


class FinancialNumericSourceCatalogRepositoryPort(Protocol):
    """Own immutable qualification rows, authenticated owner events, and exact reads."""

    def append_qualification(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append one exact qualification and its authenticated apply event atomically."""
        ...

    def append_revocation(
        self,
        entry_id: UUID,
        *,
        expected_qualification_identity: str,
        expected_qualification_sha256: str,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append one exact revoke event without mutating the original catalog row."""
        ...

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve an evidence-only qualification using body, Owner, and clock checks."""
        ...

    def resolve_exact_in_uow(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        purpose: FinancialNumericCatalogResolutionPurpose,
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve while acquiring DB locks retained by the caller's outer transaction.

        Current use must fail closed when known_at is stale relative to a newly
        recorded Owner event. Point-in-time reads use known_at exactly and do
        not include later events. This method never creates a transaction or
        reports production eligibility by itself.
        """
        ...


class ProviderDocumentFetchPort(Protocol):
    """Trusted application adapter for controlled-egress exact document capture."""

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        """Return exact successful bytes for the server-bound request attempt."""
        ...


def _invalid(message: str, *, code: str) -> DataValidationError:
    """Return a stable application error without echoing provider bytes or user input."""

    return DataValidationError(message, code=code)


def _canonical_https_url(value: str) -> str:
    """Validate the exact canonical HTTPS document URL before any network call."""

    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or any(character.isspace() for character in value)
        or "#" in value
        or "\\" in value
    ):
        raise ValueError("document URL must be bounded canonical HTTPS text")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ValueError("document URL is malformed") from error
    if (
        parsed.scheme != "https"
        or not hostname
        or not hostname.isascii()
        or hostname != hostname.lower()
        or hostname.endswith(".")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port == 443
        or (port is not None and port < 1)
    ):
        raise ValueError("document URL must use a canonical HTTPS origin")
    expected_netloc = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        expected_netloc = f"{expected_netloc}:{port}"
    if parsed.netloc != expected_netloc:
        raise ValueError("document URL must use a canonical HTTPS origin")
    return value


def _bounded_document_identity_text(value: object, *, field_name: str) -> str:
    """Validate issuer and document identifiers before any network request."""

    if (
        type(value) is not str
        or not value
        or len(value) > _MAX_DOCUMENT_TEXT
        or value != value.strip()
        or unicodedata.normalize("NFC", value) != value
        or any(unicodedata.category(character).startswith("C") for character in value)
    ):
        raise ValueError(f"{field_name} must be explicit bounded text")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field_name} must be UTF-8 representable") from error
    return value


class CaptureFinancialNumericSourceDocumentUseCase:
    """Capture a documentation body through configured egress and retain it exactly.

    This use case proves only exact response/request binding and retained bytes.
    It does not authenticate that the issuer is official, that the document is
    correct, or that any metric/unit configuration is authorized.
    """

    def __init__(
        self,
        *,
        document_fetch: ProviderDocumentFetchPort,
        capture_repository: FinancialNumericSourceDocumentCaptureRepositoryPort,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
    ) -> None:
        """Bind the controlled document fetch, append-only repository, and route scope."""

        if type(provider_id) is not int or provider_id <= 0:
            raise ValueError("provider_id must be a positive integer")
        for name, value in (
            ("dataset_key", dataset_key),
            ("deployment_region", deployment_region),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{name} must be explicit text")
        if len(dataset_key) > 120 or len(deployment_region) > 40:
            raise ValueError("document route dimensions exceed their persisted bounds")
        self._document_fetch = document_fetch
        self._capture_repository = capture_repository
        self._provider_id = provider_id
        self._dataset_key = dataset_key
        self._deployment_region = deployment_region

    def execute(
        self,
        *,
        issuer: str,
        document_id: str,
        canonical_url: str,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int = 2,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Fetch one explicitly addressed document, then append its exact capture.

        No publisher-native source version is accepted or created. The returned
        local capture UUID identifies retained bytes only and is never presented
        as a publisher document version.
        """

        try:
            issuer = _bounded_document_identity_text(issuer, field_name="issuer")
            document_id = _bounded_document_identity_text(document_id, field_name="document_id")
            canonical_url = _canonical_https_url(canonical_url)
        except ValueError as error:
            raise _invalid(
                "A bounded document identity and canonical HTTPS URL are required.",
                code="FINANCIAL_NUMERIC_CAPTURE_INPUT_INVALID",
            ) from error
        if type(max_bytes) is not int or not 0 < max_bytes < 2**63:
            raise _invalid(
                "A positive document body limit is required.",
                code="FINANCIAL_NUMERIC_CAPTURE_INPUT_INVALID",
            )
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise _invalid(
                "The document attempt limit is invalid.",
                code="FINANCIAL_NUMERIC_CAPTURE_INPUT_INVALID",
            )
        try:
            canonical_url = _canonical_https_url(canonical_url)
            media_types = normalize_document_media_type_allowlist(allowed_media_types)
            request = EgressRequestContext(
                provider_id=self._provider_id,
                dataset_key=self._dataset_key,
                target_url=canonical_url,
                deployment_region=self._deployment_region,
            )
            host = target_hostname(canonical_url)
        except (TypeError, ValueError) as error:
            raise _invalid(
                "The exact document request scope is invalid.",
                code="FINANCIAL_NUMERIC_CAPTURE_INPUT_INVALID",
            ) from error
        capture = self._document_fetch(
            request,
            max_bytes=max_bytes,
            allowed_media_types=media_types,
            max_attempts=max_attempts,
        )
        if type(capture) is not ProviderDocumentResponseCapture:
            raise _invalid(
                "Controlled egress did not return a typed document capture.",
                code="FINANCIAL_NUMERIC_CAPTURE_BINDING_INVALID",
            )
        try:
            media_type = normalize_document_content_type(capture.content_type)
            reference = FinancialNumericSourceDocumentCaptureReference(
                capture_id=capture.request_id,
                document_id=document_id,
                issuer=issuer,
                canonical_url=canonical_url,
                body_sha256=capture.body_sha256,
                body_size_bytes=capture.body_size_bytes,
                captured_at=capture.response_completed_at,
                content_type=capture.content_type,
            )
        except (TypeError, ValueError) as error:
            raise _invalid(
                "The exact document response metadata is invalid.",
                code="FINANCIAL_NUMERIC_CAPTURE_BINDING_INVALID",
            ) from error
        if (
            capture.target_url_sha256 != hashlib.sha256(canonical_url.encode("utf-8")).hexdigest()
            or capture.target_host != host
            or capture.transport is not ProviderResponseTransport.EGRESS
            or capture.body_size_bytes > max_bytes
            or media_type not in media_types
            or capture.attempt > max_attempts
        ):
            raise _invalid(
                "The document response is not bound to the requested egress capture.",
                code="FINANCIAL_NUMERIC_CAPTURE_BINDING_INVALID",
            )
        return self._capture_repository.append_document_capture(
            provider_id=self._provider_id,
            dataset_key=self._dataset_key,
            deployment_region=self._deployment_region,
            reference=reference,
            response=capture,
        )


class FinancialNumericSourceCatalogUseCase:
    """Expose authenticated command writes and strict typed qualification resolution.

    This use case is intended only for the authenticated management-command
    composition; an Interface or unauthenticated API must not expose the write
    methods. Infrastructure independently loads and checks the user row.
    """

    def __init__(self, repository: FinancialNumericSourceCatalogRepositoryPort) -> None:
        """Require one repository that verifies stored evidence and real owner events."""

        if repository is None:
            raise TypeError("financial numeric source catalog repository is required")
        self._repository = repository

    def apply(
        self,
        qualification: FinancialNumericSourceQualification,
        *,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append an exact source qualification under the authenticated Owner identity."""

        if type(qualification) is not FinancialNumericSourceQualification:
            raise _invalid(
                "A typed exact financial qualification is required.",
                code="FINANCIAL_NUMERIC_CATALOG_INPUT_INVALID",
            )
        if (
            type(actor_id) is not int
            or actor_id <= 0
            or type(actor_username) is not str
            or not actor_username
            or actor_username != actor_username.strip()
        ):
            raise _invalid(
                "An authenticated Owner identity is required.",
                code="FINANCIAL_NUMERIC_OWNER_AUTH_REQUIRED",
            )
        return self._repository.append_qualification(
            qualification,
            actor_id=actor_id,
            actor_username=actor_username,
        )

    def revoke(
        self,
        entry_id: UUID,
        *,
        expected_qualification_identity: str,
        expected_qualification_sha256: str,
        actor_id: int,
        actor_username: str,
    ) -> UUID:
        """Append a revoke event only for the exact catalog entry named by its hash."""

        if type(entry_id) is not UUID:
            raise _invalid(
                "A catalog entry UUID is required.",
                code="FINANCIAL_NUMERIC_CATALOG_INPUT_INVALID",
            )
        if (
            type(actor_id) is not int
            or actor_id <= 0
            or type(actor_username) is not str
            or not actor_username
            or actor_username != actor_username.strip()
        ):
            raise _invalid(
                "An authenticated Owner identity is required.",
                code="FINANCIAL_NUMERIC_OWNER_AUTH_REQUIRED",
            )
        return self._repository.append_revocation(
            entry_id,
            expected_qualification_identity=expected_qualification_identity,
            expected_qualification_sha256=expected_qualification_sha256,
            actor_id=actor_id,
            actor_username=actor_username,
        )

    def resolve_exact(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve one exact contract using endpoint, original source time, row context, and cutoff."""

        return self._repository.resolve_exact(
            contract_identity,
            endpoint=endpoint,
            source_response_completed_at=source_response_completed_at,
            source_context=source_context,
            known_at=known_at,
        )

    def resolve_exact_in_uow(
        self,
        contract_identity: str,
        *,
        endpoint: str,
        source_response_completed_at: datetime,
        source_context: Mapping[str, object],
        purpose: FinancialNumericCatalogResolutionPurpose,
        known_at: datetime,
    ) -> FinancialNumericSourceQualification | None:
        """Resolve under locks held until the caller's write/publication UOW commits."""

        return self._repository.resolve_exact_in_uow(
            contract_identity,
            endpoint=endpoint,
            source_response_completed_at=source_response_completed_at,
            source_context=source_context,
            purpose=purpose,
            known_at=known_at,
        )


__all__ = [
    "CaptureFinancialNumericSourceDocumentUseCase",
    "FinancialNumericSourceCatalogRepositoryPort",
    "FinancialNumericSourceCatalogUseCase",
    "FinancialNumericSourceDocumentCaptureRepositoryPort",
    "ProviderDocumentFetchPort",
]
