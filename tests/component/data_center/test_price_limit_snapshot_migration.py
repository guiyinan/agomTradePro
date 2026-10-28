"""Real migration forward/reverse behavior without erasing retained source history."""

from __future__ import annotations

from importlib import import_module

import pytest
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder

import apps.data_center.price_limit_capture_composition as capture_composition
from apps.data_center.infrastructure.models import PriceLimitSnapshotFactModel, RawPayloadModel
from apps.data_center.price_limit_snapshot_composition import build_price_limit_snapshot_capture
from tests.unit.data_center.test_price_limit_capture import (
    TRADE_DATE,
    ConfigReader,
    install_transport,
)

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = ("data_center", "0104_quote_snapshot_change_pct")
AFTER = ("data_center", "0105_price_limit_snapshot")
TABLE = "data_center_price_limit_snapshot_fact"


def test_empty_reverse_and_forward_then_refuse_reverse_with_real_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Allow empty-schema rollback but retain migrated facts and protected raw bytes."""
    try:
        MigrationExecutor(connection).migrate([BEFORE])
        assert TABLE not in connection.introspection.table_names()
        MigrationExecutor(connection).migrate([AFTER])
        assert TABLE in connection.introspection.table_names()

        migration = import_module("apps.data_center.migrations.0105_price_limit_snapshot")
        state = MigrationExecutor(connection).loader.project_state([AFTER])
        with connection.schema_editor(atomic=False) as schema_editor:
            with pytest.raises(IrreversibleError, match="transaction"):
                migration.preserve_price_limit_history(state.apps, schema_editor)

        install_transport(monkeypatch)
        monkeypatch.setattr(capture_composition, "ProviderConfigRepository", ConfigReader)
        saved = build_price_limit_snapshot_capture().execute(
            provider_id=19, asset_code="600000.SH", target_trade_date=TRADE_DATE
        )
        raw_id = saved.candidate.raw_reference.payload_id
        original_raw = RawPayloadModel.objects.get(pk=raw_id).payload
        with pytest.raises(IrreversibleError, match="price-limit history"):
            MigrationExecutor(connection).migrate([BEFORE])
        assert AFTER in MigrationRecorder(connection).applied_migrations()
        assert TABLE in connection.introspection.table_names()
        assert PriceLimitSnapshotFactModel.objects.get(pk=saved.snapshot_id).record_digest == (
            saved.record_digest
        )
        assert RawPayloadModel.objects.get(pk=raw_id).payload == original_raw
    finally:
        MigrationExecutor(connection).migrate([AFTER])
