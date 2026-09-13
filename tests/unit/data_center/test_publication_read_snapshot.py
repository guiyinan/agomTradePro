from __future__ import annotations

import pytest

from apps.data_center.infrastructure import publication_read_snapshot as snapshot_module


class _Ops:
    @staticmethod
    def quote_name(value: str) -> str:
        return f'"{value}"'


class _Cursor:
    def __init__(
        self,
        *,
        isolation: str = "read committed",
        read_only: str = "off",
        lock_timeout: str = "0",
    ) -> None:
        self.isolation = isolation
        self.read_only = read_only
        self.lock_timeout = lock_timeout
        self.statements: list[str] = []

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def fetchone(self) -> tuple[str]:
        statement = self.statements[-1]
        if statement == "SHOW transaction_isolation":
            return (self.isolation,)
        if statement == "SHOW transaction_read_only":
            return (self.read_only,)
        if statement == "SHOW lock_timeout":
            return (self.lock_timeout,)
        raise AssertionError(f"unexpected fetchone after {statement!r}")


class _Connection:
    def __init__(
        self,
        *,
        vendor: str = "postgresql",
        alias: str = "default",
        in_atomic_block: bool = False,
        autocommit: bool = True,
        isolation: str = "read committed",
        read_only: str = "off",
        lock_timeout: str = "0",
    ) -> None:
        self.vendor = vendor
        self.alias = alias
        self.in_atomic_block = in_atomic_block
        self.autocommit = autocommit
        self.ops = _Ops()
        self.cursor_value = _Cursor(
            isolation=isolation,
            read_only=read_only,
            lock_timeout=lock_timeout,
        )

    def get_autocommit(self) -> bool:
        return self.autocommit

    def cursor(self) -> _Cursor:
        return self.cursor_value


class _Atomic:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0
        self.rolled_back = False

    def __enter__(self) -> None:
        self.entered += 1

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> bool:
        self.exited += 1
        self.rolled_back = exc_type is not None
        return False


def _patch_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connection: _Connection,
    atomic: _Atomic,
) -> None:
    monkeypatch.setattr(snapshot_module, "connection", connection)
    monkeypatch.setattr(snapshot_module.transaction, "atomic", lambda **_: atomic)


def test_standalone_postgresql_starts_read_only_repeatable_read_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.valuation.fact"):
        pass

    assert connection.cursor_value.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
    ]
    assert atomic.entered == atomic.exited == 1
    assert not atomic.rolled_back


@pytest.mark.parametrize("isolation", ["repeatable read", "serializable"])
def test_nested_stable_postgresql_transaction_reuses_existing_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    isolation: str,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, isolation=isolation)
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.valuation.fact"):
        pass

    assert connection.cursor_value.statements == ["SHOW transaction_isolation"]
    assert atomic.entered == atomic.exited == 1


def test_nested_writable_read_committed_locks_tables_in_fixed_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False)
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.valuation.fact"):
        pass

    assert connection.cursor_value.statements == [
        "SHOW transaction_isolation",
        "SHOW transaction_read_only",
        "SHOW lock_timeout",
        "SET LOCAL lock_timeout = '5s'",
        'LOCK TABLE "data_center_dataset_contract" IN SHARE MODE',
        'LOCK TABLE "data_center_asset_master" IN SHARE MODE',
        'LOCK TABLE "data_center_asset_alias" IN SHARE MODE',
        'LOCK TABLE "data_center_valuation_fact" IN SHARE MODE',
        'LOCK TABLE "data_center_dataset_publication_policy" IN SHARE MODE',
        'LOCK TABLE "data_center_canonical_publication" IN SHARE MODE',
        'LOCK TABLE "data_center_publication_member" IN SHARE MODE',
        "SET LOCAL lock_timeout = '0'",
    ]
    assert atomic.entered == atomic.exited == 1


@pytest.mark.parametrize(
    ("dataset_key", "metadata_tables"),
    [
        ("macro.fact", ("data_center_dataset_contract", "data_center_indicator_catalog")),
        ("fund.nav", ("data_center_dataset_contract",)),
        ("sector.membership", ("data_center_dataset_contract",)),
        *[
            (
                key,
                (
                    "data_center_dataset_contract",
                    "data_center_asset_master",
                    "data_center_asset_alias",
                ),
            )
            for key in (
                "equity.price.bar",
                "equity.quote.snapshot",
                "equity.financial.fact",
                "equity.valuation.fact",
                "market.news",
                "market.capital_flow",
            )
        ],
    ],
)
def test_nested_read_committed_protects_all_query_metadata_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    dataset_key: str,
    metadata_tables: tuple[str, ...],
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False)
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read(dataset_key):
        locks = [
            statement
            for statement in connection.cursor_value.statements
            if statement.startswith("LOCK TABLE")
        ]
        expected = (
            *metadata_tables,
            snapshot_module._DATASET_FACT_TABLES[dataset_key],
            "data_center_dataset_publication_policy",
            "data_center_canonical_publication",
            "data_center_publication_member",
        )
        assert locks == [f'LOCK TABLE "{table}" IN SHARE MODE' for table in expected]


def test_nested_writable_read_committed_restores_existing_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, lock_timeout="3s")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.price.bar"):
        pass

    assert connection.cursor_value.statements[-1] == "SET LOCAL lock_timeout = '3s'"


@pytest.mark.parametrize("lock_timeout", ["2s", "150ms"])
def test_nested_writable_read_committed_preserves_stricter_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
    lock_timeout: str,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, lock_timeout=lock_timeout)
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.price.bar"):
        pass

    assert connection.cursor_value.statements[3] == f"SET LOCAL lock_timeout = '{lock_timeout}'"
    assert connection.cursor_value.statements[-1] == f"SET LOCAL lock_timeout = '{lock_timeout}'"


def test_nested_writable_read_committed_bounds_timeout_above_five_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, lock_timeout="10s")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.price.bar"):
        pass

    assert connection.cursor_value.statements[3] == "SET LOCAL lock_timeout = '5s'"
    assert connection.cursor_value.statements[-1] == "SET LOCAL lock_timeout = '10s'"


def test_nested_writable_read_committed_rejects_invalid_lock_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, lock_timeout="invalid")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(snapshot_module.PublicationReadSnapshotError, match="lock_timeout"):
        with snapshot_module.consistent_publication_read("equity.price.bar"):
            pytest.fail("invalid lock_timeout must not yield")

    assert connection.cursor_value.statements == [
        "SHOW transaction_isolation",
        "SHOW transaction_read_only",
        "SHOW lock_timeout",
    ]
    assert atomic.rolled_back


def test_nested_read_only_read_committed_transaction_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=True, autocommit=False, read_only="on")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(snapshot_module.PublicationReadSnapshotError, match="read-only"):
        with snapshot_module.consistent_publication_read("equity.valuation.fact"):
            pytest.fail("read-only READ COMMITTED must not yield")

    assert connection.cursor_value.statements == [
        "SHOW transaction_isolation",
        "SHOW transaction_read_only",
    ]
    assert atomic.entered == atomic.exited == 1
    assert atomic.rolled_back


def test_unknown_dataset_fails_before_opening_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(ValueError, match="unknown dataset"):
        with snapshot_module.consistent_publication_read("unknown.dataset"):
            pass

    assert atomic.entered == 0
    assert connection.cursor_value.statements == []


def test_sqlite_uses_atomic_without_postgresql_statements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(vendor="sqlite")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with snapshot_module.consistent_publication_read("equity.valuation.fact"):
        pass

    assert connection.cursor_value.statements == []
    assert atomic.entered == atomic.exited == 1


def test_exception_inside_snapshot_propagates_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(vendor="sqlite")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(KeyError, match="caller failure"):
        with snapshot_module.consistent_publication_read("equity.valuation.fact"):
            raise KeyError("caller failure")

    assert atomic.entered == atomic.exited == 1
    assert atomic.rolled_back


def test_dataset_whitelist_contains_exact_nine_fact_routes() -> None:
    assert snapshot_module._DATASET_FACT_TABLES == {
        "macro.fact": "data_center_macro_fact",
        "fund.nav": "data_center_fund_nav_fact",
        "equity.price.bar": "data_center_price_bar",
        "equity.quote.snapshot": "data_center_quote_snapshot",
        "equity.financial.fact": "data_center_financial_fact",
        "equity.valuation.fact": "data_center_valuation_fact",
        "sector.membership": "data_center_sector_membership",
        "market.news": "data_center_news_fact",
        "market.capital_flow": "data_center_capital_flow_fact",
    }


def test_unmanaged_postgresql_transaction_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(in_atomic_block=False, autocommit=False)
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(snapshot_module.PublicationReadSnapshotError, match="managed"):
        with snapshot_module.consistent_publication_read("equity.valuation.fact"):
            pass

    assert atomic.entered == 0


def test_wrong_default_connection_alias_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection(alias="other")
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(snapshot_module.PublicationReadSnapshotError, match="default"):
        with snapshot_module.consistent_publication_read("equity.valuation.fact"):
            pass

    assert atomic.entered == 0


def test_runtime_type_boundary_does_not_accept_non_string_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Connection()
    atomic = _Atomic()
    _patch_runtime(monkeypatch, connection=connection, atomic=atomic)

    with pytest.raises(ValueError, match="dataset"):
        with snapshot_module.consistent_publication_read(object()):  # type: ignore[arg-type]
            pass
