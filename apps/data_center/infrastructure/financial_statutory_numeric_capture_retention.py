"""Retain one actual response in both source catalogs in one transaction.

The statutory revision is selected from existing configured source metadata.
This append adapter creates neither an approval nor a qualification. Transport
and its successful egress audit precede this database-only operation; failure
preserves the transport audit and may leave a retained orphan body.
"""

from __future__ import annotations

from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections, transaction

from apps.data_center.application.financial_numeric_catalog import (
    FinancialNumericSourceDocumentCaptureRepositoryPort,
)
from apps.data_center.application.statutory_source_documents import (
    RetainStatutorySourceDocumentUseCase,
)
from apps.data_center.domain.financial_numeric_source_qualification import (
    FinancialNumericSourceDocumentCaptureReference,
)
from apps.data_center.domain.provider_document_response import ProviderDocumentResponseCapture
from apps.data_center.domain.statutory_source_documents import StatutorySourceDocumentRevision
from core.exceptions import DataValidationError


class FinancialStatutoryNumericCaptureRetentionError(DataValidationError):
    """Reject an inconsistent pair or an unsupported retention transaction."""

    default_message = "The exact statutory and numeric capture pair could not be retained."
    default_code = "FINANCIAL_STATUTORY_NUMERIC_CAPTURE_RETENTION_INVALID"


class FinancialStatutoryNumericPairCaptureRepository:
    """Append statutory first, then numeric, with the actual same response UUID."""

    def __init__(
        self,
        *,
        revision: StatutorySourceDocumentRevision,
        source_retainer: RetainStatutorySourceDocumentUseCase,
        numeric_repository: FinancialNumericSourceDocumentCaptureRepositoryPort,
        using: str,
    ) -> None:
        """Bind a configured native revision and the existing retention ports."""

        if type(revision) is not StatutorySourceDocumentRevision:
            raise TypeError("An exact configured statutory revision is required")
        if type(using) is not str or using != DEFAULT_DB_ALIAS:
            raise FinancialStatutoryNumericCaptureRetentionError(
                "Paired capture retention requires the default database alias."
            )
        self._revision = revision
        self._source_retainer = source_retainer
        self._numeric_repository = numeric_repository
        self._using = using

    def append_document_capture(
        self,
        *,
        provider_id: int,
        dataset_key: str,
        deployment_region: str,
        reference: FinancialNumericSourceDocumentCaptureReference,
        response: ProviderDocumentResponseCapture,
    ) -> FinancialNumericSourceDocumentCaptureReference:
        """Persist both exact references or roll back both metadata appends."""

        if (
            type(reference) is not FinancialNumericSourceDocumentCaptureReference
            or type(response) is not ProviderDocumentResponseCapture
        ):
            raise FinancialStatutoryNumericCaptureRetentionError(
                "Paired capture requires the actual typed document response and reference."
            )
        reference.__post_init__()
        response.__post_init__()
        revision = self._revision
        if (
            reference.capture_id != response.request_id
            or reference.issuer != revision.issuer
            or reference.document_id != revision.document_id
            or reference.canonical_url != revision.canonical_url
            or reference.body_sha256 != revision.body_sha256
            or reference.body_size_bytes != revision.body_size_bytes
            or reference.captured_at != response.response_completed_at
            or reference.content_type != response.content_type
            or not revision.verifies_source_document(response.body)
        ):
            raise FinancialStatutoryNumericCaptureRetentionError(
                "The response differs from the exact configured statutory revision."
            )
        connection = connections[self._using]
        if connection.vendor != "postgresql" or connection.in_atomic_block:
            raise FinancialStatutoryNumericCaptureRetentionError(
                "Paired retention requires PostgreSQL and no ambient transaction."
            )
        with transaction.atomic(using=self._using):
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SHOW transaction_isolation")
                    row = cursor.fetchone()
            except DatabaseError as error:
                raise FinancialStatutoryNumericCaptureRetentionError(
                    "Paired capture cannot verify transaction isolation."
                ) from error
            if row != ("read committed",):
                raise FinancialStatutoryNumericCaptureRetentionError(
                    "Paired capture requires READ COMMITTED isolation."
                )
            # Readers use the same source -> numeric lock order. Neither
            # append commits until this outer retention operation commits.
            self._source_retainer.execute(
                revision=revision,
                capture_id=response.request_id,
                captured_at=response.response_completed_at,
                content_type=response.content_type,
                body=response.body,
            )
            retained = self._numeric_repository.append_document_capture(
                provider_id=provider_id,
                dataset_key=dataset_key,
                deployment_region=deployment_region,
                reference=reference,
                response=response,
            )
            if retained != reference:
                raise FinancialStatutoryNumericCaptureRetentionError(
                    "Numeric retention returned a different capture identity."
                )
            return retained
