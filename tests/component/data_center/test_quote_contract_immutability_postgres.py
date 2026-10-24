"""Prove quote contract first-writer immutability against real PostgreSQL."""

from __future__ import annotations

from collections.abc import Callable
from queue import Queue
from threading import Barrier, BrokenBarrierError, Lock, Thread, get_ident
from typing import cast

import pytest
from django.db import close_old_connections, connections
from django.db.backends.utils import CursorWrapper

from apps.data_center.domain.contracts import DatasetContract, DatasetFieldContract, DatasetKey
from apps.data_center.infrastructure.catalog_models import DatasetContractModel
from apps.data_center.infrastructure.catalog_runtime_repositories import DatasetContractRepository
from tests.support.isolated_schema import isolated_schema

_DATASET_KEY = "equity.quote.snapshot"
_CONTRACT_VERSION = "quote-first-writer-race-91.0"
_SCHEMA_VERSION = "quote-first-writer-race-91.0"
_TABLE_NAME = "data_center_dataset_contract"
_CONFLICT_MESSAGE = "quote dataset contract semantics require a new contract version"

pytestmark = pytest.mark.django_db(transaction=True, available_apps=["apps.data_center"])


def _contract(*, zero_allowed: bool) -> DatasetContract:
    """Build two test-only versions of the same quote contract identity."""

    return DatasetContract(
        key=DatasetKey(_DATASET_KEY, _CONTRACT_VERSION, _SCHEMA_VERSION),
        owner="quote-first-writer-test",
        frequency="intraday",
        decision_critical=True,
        fields=(
            DatasetFieldContract(
                name="change_pct",
                value_type="decimal",
                unit="percent",
                nullable=True,
                zero_allowed=zero_allowed,
            ),
        ),
    )


def test_concurrent_first_creation_cannot_rewrite_quote_contract_semantics() -> None:
    """Both real PostgreSQL reads miss before competing to create one immutable row."""

    from django.db import connection

    if connection.vendor != "postgresql":
        pytest.skip("quote contract first-writer race requires two PostgreSQL connections")

    barrier = Barrier(2, timeout=8)
    observations: Queue[tuple[int, int]] = Queue()
    outcomes: Queue[tuple[str, DatasetContract, int]] = Queue()
    failures: Queue[str] = Queue()
    seen_threads: set[int] = set()
    seen_threads_lock = Lock()
    contracts = (_contract(zero_allowed=True), _contract(zero_allowed=False))

    def _write(contract: DatasetContract) -> None:
        """Save one semantic variant and collect worker errors for the main thread."""

        close_old_connections()
        db_connection = connections["default"]
        try:
            with db_connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '8000ms'")
                cursor.execute("SET statement_timeout = '12000ms'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_pid_value = cursor.fetchone()
                if backend_pid_value is None:
                    raise RuntimeError("PostgreSQL did not return a backend PID")
                worker_pid = int(backend_pid_value[0])

            def _synchronize_real_empty_select(
                execute: Callable[..., object],
                sql: str,
                params: object,
                many: bool,
                context: dict[str, object],
            ) -> object:
                """Wait after the real keyed SELECT confirms no row was returned."""

                result = execute(sql, params, many, context)
                normalized_sql = sql.casefold().replace('"', "")
                if not normalized_sql.lstrip().startswith("select") or (
                    f"from {_TABLE_NAME}" not in normalized_sql
                ):
                    return result
                if isinstance(params, dict):
                    values = tuple(params.values())
                elif isinstance(params, (tuple, list)):
                    values = tuple(params)
                else:
                    return result
                if not all(
                    value in values for value in (_DATASET_KEY, _CONTRACT_VERSION, _SCHEMA_VERSION)
                ):
                    return result

                thread_id = get_ident()
                with seen_threads_lock:
                    if thread_id in seen_threads:
                        return result
                    seen_threads.add(thread_id)

                rowcount = cast(CursorWrapper, context["cursor"]).rowcount
                observations.put((worker_pid, rowcount))
                try:
                    barrier.wait()
                except BrokenBarrierError as error:
                    raise RuntimeError(
                        "both quote contract reads did not reach the race"
                    ) from error
                if rowcount != 0:
                    raise RuntimeError(
                        "the synchronized quote contract SELECT was not empty "
                        f"(rowcount={rowcount})"
                    )
                return result

            with db_connection.execute_wrapper(_synchronize_real_empty_select):
                try:
                    saved = DatasetContractRepository().save(contract)
                except ValueError as error:
                    if _CONFLICT_MESSAGE not in str(error):
                        raise
                    outcomes.put(("immutable_conflict", contract, worker_pid))
                else:
                    if saved != contract:
                        raise AssertionError("repository returned semantics other than its request")
                    outcomes.put(("created", contract, worker_pid))
        except BaseException as error:
            failures.put(f"{type(error).__name__}: {error}")
            barrier.abort()
        finally:
            db_connection.close()

    writers = tuple(Thread(target=_write, args=(contract,), daemon=True) for contract in contracts)
    with isolated_schema((DatasetContractModel,)):
        try:
            for writer in writers:
                writer.start()
            for writer in writers:
                writer.join(timeout=20)
            if any(writer.is_alive() for writer in writers):
                barrier.abort()
                for writer in writers:
                    writer.join(timeout=3)

            assert all(
                not writer.is_alive() for writer in writers
            ), "quote contract writers did not exit within the bounded join"
            failure_messages = [failures.get_nowait() for _ in range(failures.qsize())]
            assert not failure_messages, failure_messages
            observed = [observations.get_nowait() for _ in range(observations.qsize())]
            assert len(observed) == 2
            assert all(rowcount == 0 for _pid, rowcount in observed)
            assert len({pid for pid, _rowcount in observed}) == 2

            results = [outcomes.get_nowait() for _ in range(outcomes.qsize())]
            assert sorted(status for status, _contract, _pid in results) == [
                "created",
                "immutable_conflict",
            ]
            assert len({pid for _status, _contract, pid in results}) == 2
            winner = next(contract for status, contract, _pid in results if status == "created")
            rows = DatasetContractModel._default_manager.filter(
                dataset_key=_DATASET_KEY,
                contract_version=_CONTRACT_VERSION,
                schema_version=_SCHEMA_VERSION,
            )
            assert rows.count() == 1
            stored = DatasetContractRepository().get_active(_DATASET_KEY)
            assert stored is not None
            assert stored == winner
        finally:
            barrier.abort()
            for writer in writers:
                if writer.ident is not None:
                    writer.join(timeout=15)
