"""Native PostgreSQL and real Admin HTTP checks for published calendar catalogs."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC
from uuid import uuid4

import pytest
from django.apps import apps
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.management import create_permissions
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import path, reverse
from django.utils import timezone

from apps.data_center.application.calendar_catalog_bootstrap import (
    CALENDAR_DATASET_KEY,
    CalendarCatalogBootstrapRows,
    CreateCalendarCatalogBootstrapUseCase,
)
from apps.data_center.domain.contracts import (
    DataOwnerRegistration,
    DatasetContract,
    DatasetFieldContract,
    DatasetKey,
    ProviderBinding,
    PublicationPolicy,
)
from apps.data_center.domain.control_plane import CalendarNullableMemberCodecVersion
from apps.data_center.infrastructure.calendar_catalog_bootstrap_repository import (
    DjangoCalendarCatalogBootstrapRepository,
)
from apps.data_center.infrastructure.calendar_catalog_history_guard import (
    calendar_catalog_history_guard_applied_at,
)
from apps.data_center.infrastructure.catalog_models import (
    DataOwnerRegistrationModel,
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
)
from apps.data_center.infrastructure.publication_rollback_models import (
    CanonicalPublicationModel,
)

pytestmark = pytest.mark.django_db(transaction=True)

_CATALOG_MODELS = (
    DatasetContractModel,
    DatasetProviderBindingModel,
    DatasetPublicationPolicyModel,
    DataOwnerRegistrationModel,
)
_ADMIN_MODELS = _CATALOG_MODELS
_CHANGE_DENIED = re.compile(r"^\s*(?:INSERT|UPDATE|DELETE|REPLACE)\b", re.IGNORECASE)
urlpatterns = [path("admin/", admin.site.urls)]


@pytest.fixture(autouse=True)
def _require_real_0115_postgres_guard() -> Iterator[None]:
    """Require the migrated native PostgreSQL schema and installed 0115 triggers."""

    if connection.vendor != "postgresql":
        pytest.skip("published calendar Admin contract requires native PostgreSQL")
    table_names = set(connection.introspection.table_names())
    user_model = get_user_model()
    required_tables = {
        "django_migrations",
        user_model._meta.db_table,
        "auth_permission",
        "django_content_type",
        *(model._meta.db_table for model in _CATALOG_MODELS),
        CanonicalPublicationModel._meta.db_table,
    }
    assert required_tables <= table_names
    assert (
        calendar_catalog_history_guard_applied_at(
            connection, server_now=timezone.now().astimezone(UTC)
        )
        is not None
    ), "the actual 0115 calendar catalog guard must be installed"
    # A preceding available_apps test can flush auth rows without post_migrate.
    ContentType.objects.clear_cache()
    create_permissions(
        apps.get_app_config("data_center"),
        verbosity=0,
        interactive=False,
        using=connection.alias,
        apps=apps,
    )
    yield


def _calendar_catalog_rows() -> CalendarCatalogBootstrapRows:
    """Build the exact four typed rows consumed by the create-only calendar bootstrap."""

    key = DatasetKey(CALENDAR_DATASET_KEY, "1.0", "exchange-calendar-snapshot-v1")
    return CalendarCatalogBootstrapRows(
        contract=DatasetContract(
            key=key,
            owner="data-platform",
            frequency="calendar",
            decision_critical=True,
            fields=(
                DatasetFieldContract("exchange", "string", None, False, False),
                DatasetFieldContract("calendar_date", "date", None, False, False),
                DatasetFieldContract("is_open", "boolean", None, False, False),
                DatasetFieldContract("previous_open_date", "date", None, False, False),
            ),
            calendar_response_max_age_seconds=900,
        ),
        binding=ProviderBinding(
            dataset=key,
            provider="tushare",
            capability="exchange_calendar",
            priority=10,
            freshness_seconds=None,
            validator_key="exchange_calendar.tushare.trade_cal.full_date.v1",
            enabled=True,
        ),
        policy=PublicationPolicy(
            dataset=key,
            minimum_coverage_ratio=1.0,
            allow_partial=False,
            conflict_action="block",
            required_evidence=("source", "fact_content_hash"),
            retention_days=3650,
            policy_version="calendar-reference-v1",
            member_codec_version=CalendarNullableMemberCodecVersion.V1,
        ),
        owner=DataOwnerRegistration(
            dataset_key=CALENDAR_DATASET_KEY,
            data_platform_owner="data-platform",
            business_owner="simulated_trading",
            acceptance_owner="data-platform",
            active=True,
        ),
    )


def _calendar_catalog_rowsets() -> dict[str, list[dict[str, object]]]:
    """Return every persisted field for all four calendar catalog histories."""

    return {
        model._meta.db_table: list(
            model._default_manager.filter(dataset_key=CALENDAR_DATASET_KEY).order_by("pk").values()
        )
        for model in _CATALOG_MODELS
    }


def _seed_guarded_calendar_catalog() -> None:
    """Activate the real DB guard with a state fixture, without member/Audit authority."""

    assert all(not rows for rows in _calendar_catalog_rowsets().values())
    candidate = _calendar_catalog_rows()
    CreateCalendarCatalogBootstrapUseCase(DjangoCalendarCatalogBootstrapRepository()).execute(
        candidate
    )
    CanonicalPublicationModel._default_manager.create(
        dataset_key=CALENDAR_DATASET_KEY,
        publication_key=f"exchange-calendar:admin-http-{uuid4().hex}",
        policy_version=candidate.policy.policy_version,
        state="published",
        selected_source="admin-http-contract-test",
        publication_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
        member_count=1,
        must_not_use_for_decision=True,
        published_at=timezone.now().astimezone(UTC),
    )
    assert all(len(rows) == 1 for rows in _calendar_catalog_rowsets().values())


def _change_only_staff_client() -> Client:
    """Return an authenticated staff client with only the four catalog change grants."""

    user_model = get_user_model()
    password = f"Calendar-{uuid4().hex}"
    user = user_model.objects.create_user(
        username=f"calendar-admin-read-{uuid4().hex}",
        password=password,
        is_staff=True,
        is_superuser=False,
    )
    for model in _ADMIN_MODELS:
        content_type = ContentType.objects.get_for_model(model)
        permission = Permission.objects.get(
            content_type=content_type,
            codename=f"change_{model._meta.model_name}",
        )
        user.user_permissions.add(permission)
        assert not user.has_perm(f"{model._meta.app_label}.view_{model._meta.model_name}")
    client = Client()
    assert client.login(username=user.get_username(), password=password) is True
    return client


def _object_change_url(model: type[models.Model], obj: models.Model) -> str:
    """Build the registered Django Admin object-change URL for a catalog row."""

    return reverse(
        f"admin:{model._meta.app_label}_{model._meta.model_name}_change",
        args=(obj.pk,),
    )


@pytest.mark.parametrize("catalog_kind", ["contract", "binding", "policy", "owner"])
@override_settings(ROOT_URLCONF=__name__)
def test_change_only_staff_can_view_but_cannot_post_guarded_calendar_catalog(
    catalog_kind: str,
) -> None:
    """Real Admin GET stays readable while calendar POST is denied before any model write."""

    _seed_guarded_calendar_catalog()
    model = {
        "contract": DatasetContractModel,
        "binding": DatasetProviderBindingModel,
        "policy": DatasetPublicationPolicyModel,
        "owner": DataOwnerRegistrationModel,
    }[catalog_kind]
    obj = model._default_manager.get(dataset_key=CALENDAR_DATASET_KEY)
    client = _change_only_staff_client()
    url = _object_change_url(model, obj)

    get_response = client.get(url)
    assert get_response.status_code == 200
    assert get_response.headers["Content-Type"].split(";", 1)[0] == "text/html"
    assert CALENDAR_DATASET_KEY.encode("utf-8") in get_response.content
    assert b'name="_save"' not in get_response.content

    before = _calendar_catalog_rowsets()
    forged_field = {
        "contract": {"owner": "tampered"},
        "binding": {"validator_key": "tampered"},
        "policy": {"allow_partial": "True"},
        "owner": {"business_owner": "tampered"},
    }[catalog_kind]
    with CaptureQueriesContext(connection) as captured:
        post_response = client.post(url, {"_save": "Save", **forged_field})
    assert post_response.status_code == 403
    assert post_response.headers["Content-Type"].split(";", 1)[0] == "text/html"
    assert _calendar_catalog_rowsets() == before
    write_queries = [
        query["sql"]
        for query in captured.captured_queries
        if _CHANGE_DENIED.match(query["sql"])
        and any(model._meta.db_table in query["sql"] for model in _CATALOG_MODELS)
    ]
    assert write_queries == []
