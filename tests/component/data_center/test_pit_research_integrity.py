from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.db import connection, models

from apps.data_center.domain.pit import (
    KnowledgeScope,
    PITDatasetManifest,
    calculate_pit_manifest_hash,
)
from apps.data_center.infrastructure.pit_models import (
    PITDatasetManifestModel,
    PITFactVersionModel,
)
from apps.data_center.infrastructure.pit_repository import (
    DjangoPITDataView,
    ManifestBoundPITDataView,
    PITManifestRepository,
)


def _force_out_of_band_update(
    model: type[models.Model],
    *,
    identity_field: str,
    identity: object,
    values: dict[str, object],
) -> None:
    """Simulate storage corruption beneath the append-only ORM boundary."""

    quote = connection.ops.quote_name
    assignments: list[str] = []
    parameters: list[object] = []
    for field_name, raw_value in values.items():
        field = model._meta.get_field(field_name)
        value = raw_value
        if isinstance(field, models.JSONField):
            value = connection.ops.adapt_json_value(raw_value, field.encoder)
        assignments.append(f"{quote(field_name)} = %s")
        parameters.append(value)
    parameters.append(identity)
    statement = (
        f"UPDATE {quote(model._meta.db_table)} SET {', '.join(assignments)} "
        f"WHERE {quote(identity_field)} = %s"
    )
    with connection.cursor() as cursor:
        cursor.execute(statement, parameters)


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
def test_pit_view_selects_latest_revision_deterministically_for_each_key() -> None:
    cutoff = datetime(2025, 3, 1, tzinfo=UTC)
    for business_key in ("A", "B"):
        for revision in (0, 1):
            PITFactVersionModel.objects.create(
                dataset="price_bar",
                business_key=business_key,
                effective_at=cutoff - timedelta(days=1),
                available_at=cutoff - timedelta(hours=1),
                ingested_at=cutoff - timedelta(minutes=30),
                revision_number=revision,
                source_record_id=f"{business_key}-{revision}",
                content_hash=str(revision + 1) * 64,
                pit_quality="verified",
                payload={"revision": revision},
            )

    rows = DjangoPITDataView().query(
        "price_bar",
        cutoff,
        KnowledgeScope.PUBLIC,
        {},
    )

    assert [(row.business_key, row.revision_number) for row in rows] == [("A", 1), ("B", 1)]


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
    _force_out_of_band_update(
        PITFactVersionModel,
        identity_field="id",
        identity=fact.pk,
        values={"payload": {"close": "999.00"}},
    )

    with pytest.raises(ValueError, match="missing or altered"):
        view.query(
            "price_bar",
            cutoff,
            KnowledgeScope.PUBLIC,
            {"business_key": "000001.SZ"},
        )


@pytest.mark.django_db
def test_manifest_rebuild_rejects_conflicting_persisted_evidence() -> None:
    cutoff = datetime(2025, 2, 28, tzinfo=UTC)
    PITFactVersionModel.objects.create(
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
    repository = PITManifestRepository()
    kwargs = {
        "as_of_time": cutoff,
        "knowledge_scope": KnowledgeScope.PUBLIC,
        "calendar_version": "sse-2025-v1",
        "query_spec": {"price_bar": {"business_key": "000001.SZ"}},
        "required_keys": {"price_bar": ["000001.SZ"]},
    }
    manifest = repository.build(**kwargs)
    _force_out_of_band_update(
        PITDatasetManifestModel,
        identity_field="manifest_id",
        identity=manifest.manifest_id,
        values={"calendar_version": "tampered"},
    )

    with pytest.raises(ValueError, match="conflicts with the requested snapshot"):
        repository.build(**kwargs)


@pytest.mark.django_db
def test_manifest_bound_view_rejects_duplicate_selected_version_ids() -> None:
    cutoff = datetime(2025, 2, 28, tzinfo=UTC)
    PITFactVersionModel.objects.create(
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
    selected = list(manifest.selected_versions)
    duplicated = PITDatasetManifest(
        manifest_id=manifest.manifest_id,
        as_of_time=manifest.as_of_time,
        knowledge_scope=manifest.knowledge_scope,
        calendar_version=manifest.calendar_version,
        query_spec=manifest.query_spec,
        selected_versions=(*manifest.selected_versions, manifest.selected_versions[0]),
        coverage=manifest.coverage,
        missing=manifest.missing,
        estimated=manifest.estimated,
        unknown=manifest.unknown,
        manifest_hash="",
    )
    _force_out_of_band_update(
        PITDatasetManifestModel,
        identity_field="manifest_id",
        identity=manifest.manifest_id,
        values={
            "selected_versions": [*selected, selected[0]],
            "manifest_hash": calculate_pit_manifest_hash(duplicated),
        },
    )

    with pytest.raises(ValueError, match="version evidence is invalid"):
        ManifestBoundPITDataView(manifest.manifest_id)
