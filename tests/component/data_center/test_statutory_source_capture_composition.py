"""Exercise unqualified configured capture on the real migrated PostgreSQL schema."""

from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from django.db import connection, transaction
from django.utils import timezone

from apps.data_center import statutory_source_capture_composition as composition
from apps.data_center.domain.egress_routing import EgressRequestContext
from apps.data_center.domain.provider_document_response import ProviderDocumentResponseCapture
from apps.data_center.domain.provider_response import ProviderResponseTransport
from apps.data_center.domain.statutory_source_documents import StatutorySourceDocumentAppendResult
from apps.data_center.infrastructure.models import ProviderConfigModel, PublisherCatalogModel
from apps.data_center.infrastructure.statutory_source_models import (
    StatutorySourceDocumentCaptureModel,
)
from core.exceptions import DataValidationError
from tests.component.data_center.test_statutory_source_repository import (
    require_real_native_source_schema as require_real_native_source_schema,
)
from tests.support.account_authority_generation_flush import (
    preserve_account_authority_generation as preserve_account_authority_generation,
)

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])
BODY = b"<html>Explicit synthetic configured-capture fixture, no legal authority.</html>"
URL = "https://documents.example.invalid/fixture"


@pytest.fixture(scope="module", autouse=True)
def require_document_provider_migration(django_db_setup: None, django_db_blocker: object) -> None:
    """Require the genuine dedicated-provider choices migration in the native database."""
    del django_db_setup
    with django_db_blocker.unblock():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM django_migrations WHERE app=%s AND name=%s",
                ["data_center", "0112_public_document_provider"],
            )
            assert cursor.fetchone() == (1,)


def catalog() -> dict[str, object]:
    return {
        "schema_version": "data_center.statutory_source_catalog.v1",
        "profile_id": "synthetic-source-catalog",
        "version": "fixture-v1",
        "publisher_code": "QA-STATUTORY",
        "enabled": True,
        "allowed_hosts": ["documents.example.invalid"],
        "max_capture_age_seconds": 600,
        "documents": [
            {
                "revision": {
                    "issuer": "Synthetic issuer",
                    "document_id": "synthetic-document",
                    "source_version": "synthetic-edition",
                    "canonical_url": URL,
                    "title": "Synthetic source without legal authority",
                    "legal_number": "SYNTHETIC-NONLEGAL-FIXTURE",
                    "publication_date": {"precision": "unknown", "value": None},
                    "effective_date": {"precision": "unknown", "value": None},
                    "body_sha256": sha256(BODY).hexdigest(),
                    "body_size_bytes": len(BODY),
                },
                "max_bytes": 1024,
                "allowed_media_types": ["text/html"],
            }
        ],
    }


@pytest.fixture
def configured_provider() -> tuple[ProviderConfigModel, PublisherCatalogModel]:
    publisher = PublisherCatalogModel._default_manager.create(
        code="QA-STATUTORY",
        canonical_name="Synthetic publisher",
        publisher_class="system",
        website="https://example.invalid/",
        is_active=True,
    )
    provider = ProviderConfigModel._default_manager.create(
        name="synthetic-public-documents",
        source_type="public_document",
        is_active=True,
        http_url="",
        api_endpoint="",
        extra_config={"statutory_source_catalog": catalog()},
    )
    return provider, publisher


def capture(context: EgressRequestContext, age_seconds: int = 0) -> ProviderDocumentResponseCapture:
    return ProviderDocumentResponseCapture(
        request_id=uuid4(),
        attempt=1,
        egress_id=None,
        target_url_sha256=sha256(context.target_url.encode()).hexdigest(),
        target_host="documents.example.invalid",
        body=BODY,
        body_sha256=sha256(BODY).hexdigest(),
        body_size_bytes=len(BODY),
        response_completed_at=timezone.now() - timedelta(seconds=age_seconds),
        status_code=200,
        content_type="text/html; charset=utf-8",
        transport=ProviderResponseTransport.EGRESS,
    )


def service(
    provider: ProviderConfigModel, path: Path
) -> composition.ConfiguredStatutorySourceCaptureService:
    return composition.ConfiguredStatutorySourceCaptureService(
        provider_id=provider.pk, body_store_root=path, deployment_region="synthetic-test-region"
    )


def execute(
    instance: composition.ConfiguredStatutorySourceCaptureService,
) -> StatutorySourceDocumentAppendResult:
    return instance.capture_document(
        issuer="Synthetic issuer",
        document_id="synthetic-document",
        source_version="synthetic-edition",
    )


def test_native_configured_document_retains_exact_server_observation(
    configured_provider: tuple[ProviderConfigModel, PublisherCatalogModel],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _ = configured_provider
    instance = service(provider, tmp_path / "retained")
    response = capture(
        EgressRequestContext(
            provider.pk, "statutory_source_documents", URL, "synthetic-test-region"
        )
    )
    fetch = Mock(return_value=response)
    monkeypatch.setattr(composition, "execute_provider_document_request", fetch)
    result = execute(instance)
    assert result.capture.capture_id == response.request_id
    assert result.capture.captured_at == response.response_completed_at
    assert result.capture.revision.publication_date.date_value is None
    assert (
        StatutorySourceDocumentCaptureModel._default_manager.filter(
            capture_id=response.request_id
        ).count()
        == 1
    )
    assert (tmp_path / "retained" / f"{response.request_id}.body").read_bytes() == BODY
    context = fetch.call_args.args[0]
    assert context.provider_id == provider.pk and context.target_url == URL
    assert fetch.call_args.kwargs["allowed_media_types"] == frozenset({"text/html"})


@pytest.mark.parametrize(
    "failure",
    [
        "provider_disabled",
        "catalog_disabled",
        "publisher_disabled",
        "outside_publisher",
        "invalid_publisher_port",
    ],
)
def test_native_invalid_configuration_blocks_before_fetch(
    configured_provider: tuple[ProviderConfigModel, PublisherCatalogModel],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    provider, publisher = configured_provider
    if failure == "provider_disabled":
        provider.is_active = False
        provider.save(update_fields=["is_active", "updated_at"])
    elif failure == "catalog_disabled":
        value = catalog()
        value["enabled"] = False
        provider.extra_config = {"statutory_source_catalog": value}
        provider.save(update_fields=["extra_config", "updated_at"])
    elif failure == "publisher_disabled":
        publisher.is_active = False
        publisher.save(update_fields=["is_active", "updated_at"])
    elif failure == "outside_publisher":
        publisher.website = "https://other.invalid/"
        publisher.save(update_fields=["website", "updated_at"])
    else:
        publisher.website = "https://example.invalid:0/"
        publisher.save(update_fields=["website", "updated_at"])
    fetch = Mock()
    monkeypatch.setattr(composition, "execute_provider_document_request", fetch)
    with pytest.raises(DataValidationError):
        execute(service(provider, tmp_path / "unused"))
    fetch.assert_not_called()
    assert not StatutorySourceDocumentCaptureModel._default_manager.exists()
    assert not (tmp_path / "unused").exists()


def test_native_configuration_drift_preserves_unqualified_capture(
    configured_provider: tuple[ProviderConfigModel, PublisherCatalogModel],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _ = configured_provider
    original_ids: list[UUID] = []

    def fetch(context: EgressRequestContext, **kwargs: object) -> ProviderDocumentResponseCapture:
        value = catalog()
        value["version"] = "fixture-v2"
        provider.extra_config = {"statutory_source_catalog": value}
        provider.save(update_fields=["extra_config", "updated_at"])
        response = capture(context)
        original_ids.append(response.request_id)
        return response

    monkeypatch.setattr(composition, "execute_provider_document_request", fetch)
    with pytest.raises(DataValidationError) as error:
        execute(service(provider, tmp_path / "retained"))
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_CONFIGURATION_CHANGED"
    assert StatutorySourceDocumentCaptureModel._default_manager.filter(
        capture_id=original_ids[0]
    ).exists()
    assert (tmp_path / "retained" / f"{original_ids[0]}.body").read_bytes() == BODY


def test_native_old_observation_is_retained_but_rejected_for_capture_window(
    configured_provider: tuple[ProviderConfigModel, PublisherCatalogModel],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _ = configured_provider
    response = capture(
        EgressRequestContext(
            provider.pk, "statutory_source_documents", URL, "synthetic-test-region"
        ),
        age_seconds=601,
    )
    monkeypatch.setattr(
        composition, "execute_provider_document_request", Mock(return_value=response)
    )
    with pytest.raises(DataValidationError) as error:
        execute(service(provider, tmp_path / "retained"))
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_OUTSIDE_WINDOW"
    stored = StatutorySourceDocumentCaptureModel._default_manager.get(
        capture_id=response.request_id
    )
    assert stored.captured_at == response.response_completed_at


def test_native_capture_rejects_ambient_transaction_before_network(
    configured_provider: tuple[ProviderConfigModel, PublisherCatalogModel],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider, _ = configured_provider
    fetch = Mock()
    monkeypatch.setattr(composition, "execute_provider_document_request", fetch)
    with transaction.atomic():
        with pytest.raises(DataValidationError) as error:
            execute(service(provider, tmp_path / "unused"))
    assert error.value.code == "STATUTORY_SOURCE_CAPTURE_OUTER_TRANSACTION"
    fetch.assert_not_called()
    assert not StatutorySourceDocumentCaptureModel._default_manager.exists()
