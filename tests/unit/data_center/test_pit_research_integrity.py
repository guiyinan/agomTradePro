from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.data_center.domain.pit import KnowledgeScope
from apps.data_center.infrastructure.pit_models import PITFactVersionModel
from apps.data_center.infrastructure.pit_repository import (
    DjangoPITDataView,
    ManifestBoundPITDataView,
    PITManifestRepository,
)


@pytest.mark.django_db
def test_pit_view_selects_only_revision_publicly_available_at_as_of() -> None:
    effective_at = datetime(2025, 1, 1, tzinfo=UTC)
    first_publication = datetime(2025, 1, 10, tzinfo=UTC)
    revision_publication = datetime(2025, 2, 10, tzinfo=UTC)
    PITFactVersionModel.objects.create(
        dataset="macro",
        business_key="CN_GDP:2024Q4",
        effective_at=effective_at,
        available_at=first_publication,
        ingested_at=first_publication + timedelta(hours=1),
        revision_number=0,
        source_record_id="gdp-initial",
        content_hash="a" * 64,
        pit_quality="verified",
        payload={"value": "100"},
    )
    PITFactVersionModel.objects.create(
        dataset="macro",
        business_key="CN_GDP:2024Q4",
        effective_at=effective_at,
        available_at=revision_publication,
        ingested_at=revision_publication + timedelta(hours=1),
        revision_number=1,
        source_record_id="gdp-revision",
        content_hash="b" * 64,
        pit_quality="verified",
        payload={"value": "120"},
    )

    view = DjangoPITDataView()
    before_revision = view.query(
        "macro",
        datetime(2025, 1, 31, tzinfo=UTC),
        KnowledgeScope.PUBLIC,
        {"business_key": "CN_GDP:2024Q4"},
    )
    after_revision = view.query(
        "macro",
        datetime(2025, 2, 28, tzinfo=UTC),
        KnowledgeScope.PUBLIC,
        {"business_key": "CN_GDP:2024Q4"},
    )

    assert before_revision[0].payload["value"] == "100"
    assert after_revision[0].payload["value"] == "120"


@pytest.mark.django_db
def test_manifest_is_deterministic_and_unknown_evidence_blocks_verification() -> None:
    as_of = datetime(2025, 3, 1, tzinfo=UTC)
    PITFactVersionModel.objects.create(
        dataset="price_bar",
        business_key="000001.SZ",
        effective_at=as_of - timedelta(days=1),
        available_at=as_of - timedelta(hours=1),
        ingested_at=as_of - timedelta(minutes=30),
        revision_number=0,
        source_record_id="price-1",
        content_hash="c" * 64,
        pit_quality="unknown",
        payload={"close": str(Decimal("10.50"))},
    )
    repository = PITManifestRepository()
    kwargs = {
        "as_of_time": as_of,
        "knowledge_scope": KnowledgeScope.PUBLIC,
        "calendar_version": "sse-2025-v1",
        "query_spec": {"price_bar": {"business_key": "000001.SZ"}},
        "required_keys": {"price_bar": ["000001.SZ"]},
    }

    first = repository.build(**kwargs)
    second = repository.build(**kwargs)

    assert first.manifest_id == second.manifest_id
    assert first.manifest_hash == second.manifest_hash
    assert first.coverage == {"price_bar": 1.0}
    assert first.unknown
    assert first.is_verified is False


@pytest.mark.django_db
def test_manifest_bound_view_ignores_versions_added_after_freeze() -> None:
    effective_at = datetime(2025, 1, 1, tzinfo=UTC)
    cutoff = datetime(2025, 2, 28, tzinfo=UTC)
    for revision, published, value in (
        (0, datetime(2025, 1, 10, tzinfo=UTC), "100"),
        (1, datetime(2025, 2, 10, tzinfo=UTC), "110"),
    ):
        PITFactVersionModel.objects.create(
            dataset="macro",
            business_key="CN_GDP:2024Q4",
            effective_at=effective_at,
            available_at=published,
            ingested_at=published + timedelta(hours=1),
            revision_number=revision,
            source_record_id=f"gdp-{revision}",
            content_hash=str(revision + 1) * 64,
            pit_quality="verified",
            payload={"value": value},
        )
    manifest = PITManifestRepository().build(
        as_of_time=cutoff,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version="sse-2025-v1",
        query_spec={"macro": {"business_key": "CN_GDP:2024Q4"}},
        required_keys={"macro": ["CN_GDP:2024Q4"]},
    )
    PITFactVersionModel.objects.create(
        dataset="macro",
        business_key="CN_GDP:2024Q4",
        effective_at=effective_at,
        available_at=cutoff - timedelta(days=1),
        ingested_at=cutoff - timedelta(hours=1),
        revision_number=2,
        source_record_id="late-ingested-revision",
        content_hash="9" * 64,
        pit_quality="verified",
        payload={"value": "999"},
    )

    rows = ManifestBoundPITDataView(manifest.manifest_id).query(
        "macro",
        cutoff,
        KnowledgeScope.PUBLIC,
        {"business_key": "CN_GDP:2024Q4"},
    )

    assert rows[0].payload["value"] == "110"


@pytest.mark.django_db
def test_manifest_bound_view_rejects_payload_tampering_after_freeze() -> None:
    cutoff = datetime(2025, 2, 28, tzinfo=UTC)
    fact = PITFactVersionModel.objects.create(
        dataset="price_bar",
        business_key="000001.SZ",
        effective_at=cutoff - timedelta(days=1),
        available_at=cutoff - timedelta(hours=1),
        ingested_at=cutoff - timedelta(minutes=30),
        source_record_id="price-v1",
        content_hash="8" * 64,
        pit_quality="verified",
        payload={"close": "10.00"},
    )
    manifest = PITManifestRepository().build(
        as_of_time=cutoff,
        knowledge_scope=KnowledgeScope.PUBLIC,
        calendar_version="sse-2025-v1",
        query_spec={"price_bar": {"business_key": "000001.SZ"}},
        required_keys={"price_bar": ["000001.SZ"]},
    )
    view = ManifestBoundPITDataView(manifest.manifest_id)
    PITFactVersionModel._default_manager.filter(pk=fact.pk).update(payload={"close": "999.00"})

    with pytest.raises(ValueError, match="missing or altered"):
        view.query(
            "price_bar",
            cutoff,
            KnowledgeScope.PUBLIC,
            {"business_key": "000001.SZ"},
        )
