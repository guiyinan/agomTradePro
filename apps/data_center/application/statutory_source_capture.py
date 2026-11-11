"""Capture a pinned native document through governed egress before retention."""

from __future__ import annotations

import hashlib
import sys
from typing import Protocol

from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.egress_routing import EgressRequestContext, target_hostname
from apps.data_center.domain.provider_document_response import (
    ProviderDocumentResponseCapture,
    normalize_document_content_type,
    normalize_document_media_type_allowlist,
)
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import (
    StatutorySourceDocumentAppendResult,
    StatutorySourceDocumentRevision,
)
from core.exceptions import DataValidationError


class StatutorySourceDocumentFetchPort(Protocol):
    """Governed fetch whose implementation verifies request/attempt binding.

    The composition must supply ``execute_provider_document_request`` or an
    equivalent trusted implementation. HTTP/configuration input must never
    supply this capability or a preconstructed response capture. Existing
    egress auditing is best-effort; this port does not prove audit persistence.
    """

    def __call__(
        self,
        context: EgressRequestContext,
        *,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int,
    ) -> ProviderDocumentResponseCapture:
        """Fetch exact bytes, with a server-issued UUID and actual completion time."""
        ...


def _invalid(message: str) -> DataValidationError:
    """Return a stable error without echoing untrusted response data."""
    return DataValidationError(message, code="STATUTORY_SOURCE_CAPTURE_BINDING_INVALID")


class CaptureStatutorySourceDocumentUseCase:
    """Fetch an exact configured revision and retain its server observation.

    Destination/body integrity does not establish official publisher status,
    legal applicability, completeness, or an active business policy. Those
    require independently qualified catalog/rule and policy consumers.
    """

    def __init__(
        self,
        *,
        retainer: RetainStatutorySourceDocumentUseCase,
        document_fetch: StatutorySourceDocumentFetchPort,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
    ) -> None:
        """Bind server-side retention, governed fetch and explicit route dimensions."""
        self._retainer = retainer
        self._document_fetch = document_fetch
        self._provider_id = provider_id
        self._dataset_key = dataset_key
        self._deployment_region = deployment_region

    def execute(
        self,
        *,
        revision: StatutorySourceDocumentRevision,
        max_bytes: int,
        allowed_media_types: frozenset[str],
        max_attempts: int = 2,
    ) -> StatutorySourceDocumentAppendResult:
        """Fetch the revision URL, verify pinned bytes, then retain exact observation.

        No caller-supplied capture UUID, capture clock, alternate URL, headers,
        or query parameters are accepted. The response request UUID becomes
        the retained capture UUID, permitting association with egress attempts.
        Original publication/effective date precision remains unchanged.
        """
        if type(revision) is not StatutorySourceDocumentRevision:
            raise _invalid("Statutory source revision input is invalid.")
        if (
            type(max_bytes) is not int
            or not 0 < max_bytes < sys.maxsize
            or revision.body_size_bytes > max_bytes
        ):
            raise _invalid("Statutory source capture byte limit is invalid or insufficient.")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 2:
            raise _invalid("Statutory source capture attempt limit is invalid.")
        try:
            media_types = normalize_document_media_type_allowlist(allowed_media_types)
        except ValueError as error:
            raise _invalid("Statutory source capture MIME allowlist is invalid.") from error
        context = EgressRequestContext(
            provider_id=self._provider_id,
            dataset_key=self._dataset_key,
            target_url=revision.canonical_url,
            deployment_region=self._deployment_region,
        )
        capture = self._document_fetch(
            context,
            max_bytes=max_bytes,
            allowed_media_types=media_types,
            max_attempts=max_attempts,
        )
        if type(capture) is not ProviderDocumentResponseCapture:
            raise _invalid("Governed source fetch did not return a document capture.")
        try:
            media_type = normalize_document_content_type(capture.content_type)
        except ValueError as error:
            raise _invalid("Governed source fetch returned an invalid MIME type.") from error
        if (
            capture.target_url_sha256
            != hashlib.sha256(revision.canonical_url.encode("utf-8")).hexdigest()
            or capture.target_host != target_hostname(revision.canonical_url)
            or capture.transport is not ProviderResponseTransport.EGRESS
            or capture.attempt > max_attempts
            or capture.body_size_bytes > max_bytes
            or media_type not in media_types
            or len(capture.content_type) > 200
            or not revision.verifies_source_document(capture.body)
        ):
            raise _invalid("Governed source capture differs from the pinned document request.")
        return self._retainer.execute(
            revision=revision,
            capture_id=capture.request_id,
            captured_at=capture.response_completed_at,
            content_type=capture.content_type,
            body=capture.body,
        )


__all__ = ["CaptureStatutorySourceDocumentUseCase", "StatutorySourceDocumentFetchPort"]
