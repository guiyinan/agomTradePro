"""Mechanical reverse protection without a database or fabricated row evidence."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import cast

import pytest
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import StateApps
from django.db.models import Q

_MODULE = "apps.simulated_trading.migrations.0040_simulated_fee_correction"
_NAMES = (
    "SimulatedFeeCorrectionEventModel",
    "FeeCorrectionEvidenceBindingModel",
    "FeeCorrectionEvidenceArtifactModel",
    "FeeCorrectionEvidencePolicyModel",
)


class _Query:
    def __init__(self, table: str, exists: bool, trace: list[str]) -> None:
        self.table = table
        self.present = exists
        self.trace = trace
        self.conditions: tuple[Q, ...] = ()

    def using(self, alias: str) -> _Query:
        self.trace.append(f"alias:{alias}")
        return self

    def filter(self, *conditions: Q) -> _Query:
        self.conditions = conditions
        return self

    def exists(self) -> bool:
        self.trace.append(f"check:{self.table}")
        return self.present


class _Cursor:
    def __init__(self, trace: list[str]) -> None:
        self.trace = trace

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        assert sql.startswith("LOCK TABLE ") and sql.endswith(" IN ACCESS EXCLUSIVE MODE")
        self.trace.append(sql)


class _Apps:
    def __init__(self, present: str | None, watermark: bool, trace: list[str]) -> None:
        self.rows: dict[str, SimpleNamespace] = {}
        for name in ("SimulatedAccountModel", *_NAMES, "DailyNetValueModel"):
            table = name.casefold()
            self.rows[name] = SimpleNamespace(
                _meta=SimpleNamespace(db_table=table),
                _base_manager=_Query(
                    table, name == present or (name == "DailyNetValueModel" and watermark), trace
                ),
            )

    def get_model(self, label: str, name: str) -> SimpleNamespace:
        assert label == "simulated_trading"
        return self.rows[name]


def _call(
    *,
    present: str | None = None,
    watermark: bool = False,
    vendor: str = "postgresql",
    atomic: bool = True,
) -> tuple[list[str], _Apps]:
    trace: list[str] = []
    apps = _Apps(present, watermark, trace)
    connection = SimpleNamespace(
        vendor=vendor,
        in_atomic_block=atomic,
        alias="isolated_fee_guard",
        cursor=lambda: _Cursor(trace),
    )
    editor = SimpleNamespace(connection=connection, quote_name=lambda name: f'"{name}"')
    module = importlib.import_module(_MODULE)
    module.refuse_to_drop_fee_correction_evidence(
        cast(StateApps, apps), cast(BaseDatabaseSchemaEditor, editor)
    )
    return trace, apps


def test_guard_locks_all_protected_tables_before_any_row_check() -> None:
    """The read/drop gap is closed within the schema transaction."""
    trace, _ = _call()
    assert trace[0].startswith('LOCK TABLE "simulatedaccountmodel", ')
    for name in (*_NAMES, "DailyNetValueModel"):
        assert f'"{name.casefold()}"' in trace[0]
    assert not any(line.startswith("check:") for line in trace[:1])
    assert trace.count("alias:isolated_fee_guard") == 5


@pytest.mark.parametrize("present", _NAMES)
def test_any_persisted_fee_or_qualification_row_blocks_reversal(present: str) -> None:
    """A disabled policy or unattached upload is retained as audit evidence too."""
    with pytest.raises(IrreversibleError, match="financial or qualification evidence"):
        _call(present=present)


def test_captured_snapshot_coverage_blocks_reversal() -> None:
    """Captured prefix coverage must not be silently removed from snapshots."""
    with pytest.raises(IrreversibleError, match="captured watermarks"):
        _call(watermark=True)


def test_legacy_null_coverage_is_the_only_empty_snapshot_case() -> None:
    """The guard checks either persisted watermark component, including zero."""
    _, apps = _call(vendor="sqlite")
    query = apps.rows["DailyNetValueModel"]._base_manager
    condition = query.conditions[0]
    assert condition.connector == "OR"
    assert set(condition.children) == {
        ("correction_event_watermark__isnull", False),
        ("correction_event_watermark_sha256__isnull", False),
    }


def test_reversal_outside_a_schema_transaction_is_rejected() -> None:
    """Without atomicity a row check cannot protect later destructive DDL."""
    with pytest.raises(IrreversibleError, match="atomic schema transaction"):
        _call(atomic=False)


def test_reverse_guard_is_first_reverse_operation_and_forward_is_noop() -> None:
    """Inspect actual migration ordering rather than mocking migration execution."""
    from django.db import migrations

    module = importlib.import_module(_MODULE)
    assert module.Migration.atomic is True
    last = module.Migration.operations[-1]
    assert isinstance(last, migrations.RunPython)
    assert last.code is migrations.RunPython.noop
    assert last.reverse_code is module.refuse_to_drop_fee_correction_evidence
