"""PostgreSQL adapter for provider-free historical DATA-02 simulation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Final

from psycopg import Connection, Cursor, connect, sql

from apps.data_center.application.data02_isolated_simulation import (
    Data02HistoricalDatabaseSnapshot,
    Data02HistoricalDatasetSnapshot,
    Data02HistoricalFactReference,
    Data02HistoricalPublicationSnapshot,
)
from apps.data_center.domain.market_time import cn_market_date_start_utc

_CORE_DATASET_TABLES: Final[tuple[tuple[str, str], ...]] = (
    ("equity.quote.snapshot", "data_center_quote_snapshot"),
    ("equity.price.bar", "data_center_price_bar"),
    ("equity.valuation.fact", "data_center_valuation_fact"),
    ("equity.financial.fact", "data_center_financial_fact"),
)
_REQUIRED_TABLES: Final[frozenset[str]] = frozenset(
    {
        "data_center_asset_master",
        "data_center_canonical_publication",
        "data_center_dataset_contract",
        "data_center_financial_fact",
        "data_center_price_bar",
        "data_center_production_coverage_universe_config",
        "data_center_publication_member",
        "data_center_quote_snapshot",
        "data_center_valuation_fact",
        "django_migrations",
    }
)


def _text(value: object, field_name: str) -> str:
    """Narrow a required database text value."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value


def _aware(value: object, field_name: str) -> datetime:
    """Narrow a required aware database timestamp."""

    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _market_date(value: object, field_name: str) -> datetime:
    """Convert one persisted mainland-China market date to its source boundary."""

    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date")
    return cn_market_date_start_utc(value)


def _date(value: object, field_name: str) -> date:
    """Narrow a required database date without accepting datetimes."""

    if not isinstance(value, date) or isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a date")
    return value


def _integer(value: object, field_name: str) -> int:
    """Narrow a required database integer without accepting booleans."""

    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _reference(
    row: tuple[object, ...],
    *,
    fact_table: str,
    natural_key: str,
    observed_at: datetime,
    quality_status: str | None = None,
) -> Data02HistoricalFactReference:
    """Convert one selected fact row into an exact simulation reference."""

    asset_code = _text(row[1], "asset_code")
    source = _text(row[2], "source")
    persisted_quality = _text(row[4], "quality_status")
    return Data02HistoricalFactReference(
        natural_key=natural_key,
        asset_code=asset_code,
        fact_table=fact_table,
        fact_pk=str(row[0]),
        source=source,
        observed_at=observed_at,
        quality_status=quality_status or persisted_quality,
    )


class PostgresData02HistoricalSnapshotAdapter:
    """Collect four DATA-02 datasets from one disposable PostgreSQL database."""

    def __init__(self, *, database_url: str) -> None:
        if not database_url.strip():
            raise ValueError("database_url cannot be empty")
        self._database_url = database_url

    def collect(self) -> Data02HistoricalDatabaseSnapshot:
        """Collect one repeatable-read read-only snapshot with no ORM or provider calls."""

        with connect(
            self._database_url,
            options="-c default_transaction_read_only=on",
        ) as connection:
            return self._collect_from_connection(connection)

    def _collect_from_connection(
        self,
        connection: Connection[tuple[object, ...]],
    ) -> Data02HistoricalDatabaseSnapshot:
        """Collect and validate the isolated database within one read-only transaction."""

        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            cursor.execute("SHOW transaction_read_only")
            transaction_read_only = cursor.fetchone()
            if transaction_read_only != ("on",):
                raise RuntimeError("isolated DATA-02 transaction is not read-only")
            cursor.execute("SELECT current_database(), CURRENT_TIMESTAMP")
            identity = cursor.fetchone()
            if identity is None:
                raise RuntimeError("isolated database identity is unavailable")
            database_name = _text(identity[0], "database_name")
            captured_at = _aware(identity[1], "captured_at")
            self._validate_schema(cursor)
            migrations = self._migrations(cursor)
            universe_id, universe_codes = self._universe(cursor)
            datasets = tuple(
                self._dataset_snapshot(
                    cursor,
                    dataset_key=dataset_key,
                    fact_table=fact_table,
                    universe_codes=universe_codes,
                )
                for dataset_key, fact_table in _CORE_DATASET_TABLES
            )
        return Data02HistoricalDatabaseSnapshot(
            database_name=database_name,
            captured_at=captured_at,
            transaction_read_only=True,
            data_center_migrations=migrations,
            universe_id=universe_id,
            universe_codes=universe_codes,
            datasets=datasets,
        )

    @staticmethod
    def _validate_schema(cursor: Cursor[tuple[object, ...]]) -> None:
        """Fail closed when any required historical table is absent."""

        cursor.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """)
        tables = {str(row[0]) for row in cursor.fetchall()}
        missing = sorted(_REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError(f"isolated DATA-02 schema is missing tables: {missing}")

    @staticmethod
    def _migrations(cursor: Cursor[tuple[object, ...]]) -> tuple[str, ...]:
        """Return the ordered Data Center migration identity."""

        cursor.execute("""
            SELECT name
            FROM django_migrations
            WHERE app = 'data_center'
            ORDER BY applied, name
            """)
        migrations = tuple(str(row[0]) for row in cursor.fetchall())
        if not migrations:
            raise RuntimeError("isolated DATA-02 database has no Data Center migrations")
        return migrations

    @staticmethod
    def _universe(cursor: Cursor[tuple[object, ...]]) -> tuple[str, tuple[str, ...]]:
        """Load the exact production coverage configuration and universe codes."""

        cursor.execute("""
            SELECT universe_id, asset_type, exchanges, include_inactive
            FROM data_center_production_coverage_universe_config
            WHERE id = 1
            """)
        config = cursor.fetchone()
        if config is None:
            raise RuntimeError("MISSING_CONFIG: production coverage universe is absent")
        universe_id = _text(config[0], "universe_id")
        asset_type = _text(config[1], "asset_type")
        raw_exchanges = config[2]
        if not isinstance(raw_exchanges, list) or any(
            not isinstance(exchange, str) or not exchange.strip() for exchange in raw_exchanges
        ):
            raise RuntimeError("coverage universe exchanges are invalid")
        exchanges = tuple(sorted({exchange.strip().upper() for exchange in raw_exchanges}))
        if not exchanges:
            raise RuntimeError("coverage universe exchanges are empty")
        include_inactive = config[3]
        if not isinstance(include_inactive, bool):
            raise RuntimeError("coverage universe include_inactive is invalid")
        cursor.execute(
            """
            SELECT code
            FROM data_center_asset_master
            WHERE asset_type = %s
              AND exchange = ANY(%s::text[])
              AND (%s OR is_active)
            ORDER BY code
            """,
            (asset_type, list(exchanges), include_inactive),
        )
        universe_codes = tuple(str(row[0]) for row in cursor.fetchall())
        if not universe_codes:
            raise RuntimeError("isolated DATA-02 universe is empty")
        return universe_id, universe_codes

    def _dataset_snapshot(
        self,
        cursor: Cursor[tuple[object, ...]],
        *,
        dataset_key: str,
        fact_table: str,
        universe_codes: tuple[str, ...],
    ) -> Data02HistoricalDatasetSnapshot:
        """Collect selected latest facts and current publication members."""

        cursor.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(fact_table)))
        count_row = cursor.fetchone()
        fact_row_count = _integer(count_row[0], "fact_row_count") if count_row else 0
        selector = self._selector(dataset_key)
        facts = selector(cursor, universe_codes)
        publication = self._publication(cursor, dataset_key, fact_table)
        return Data02HistoricalDatasetSnapshot(
            dataset_key=dataset_key,
            fact_table=fact_table,
            fact_row_count=fact_row_count,
            freshness_seconds=self._freshness_seconds(cursor, dataset_key),
            facts=facts,
            publication=publication,
        )

    @staticmethod
    def _freshness_seconds(cursor: Cursor[tuple[object, ...]], dataset_key: str) -> int | None:
        """Load the single active runtime freshness policy for one dataset."""

        cursor.execute(
            """
            SELECT freshness_seconds
            FROM data_center_dataset_contract
            WHERE dataset_key = %s AND active
            ORDER BY contract_version, schema_version
            """,
            (dataset_key,),
        )
        rows = cursor.fetchall()
        if len(rows) > 1:
            raise RuntimeError(f"multiple active dataset contracts for {dataset_key}")
        if not rows or rows[0][0] is None:
            return None
        return _integer(rows[0][0], "freshness_seconds")

    def _selector(
        self,
        dataset_key: str,
    ) -> Callable[
        [Cursor[tuple[object, ...]], tuple[str, ...]],
        tuple[Data02HistoricalFactReference, ...],
    ]:
        """Return the fixed selector for one closed-world core dataset."""

        selectors: dict[
            str,
            Callable[
                [Cursor[tuple[object, ...]], tuple[str, ...]],
                tuple[Data02HistoricalFactReference, ...],
            ],
        ] = {
            "equity.financial.fact": self._financial_facts,
            "equity.price.bar": self._price_facts,
            "equity.quote.snapshot": self._quote_facts,
            "equity.valuation.fact": self._valuation_facts,
        }
        try:
            return selectors[dataset_key]
        except KeyError as exc:
            raise ValueError(f"unsupported DATA-02 dataset: {dataset_key}") from exc

    @staticmethod
    def _quote_facts(
        cursor: Cursor[tuple[object, ...]],
        universe_codes: tuple[str, ...],
    ) -> tuple[Data02HistoricalFactReference, ...]:
        """Select the latest immutable quote per asset."""

        cursor.execute(
            """
            SELECT id, asset_code, source, snapshot_at, quality_status
            FROM (
                SELECT id, asset_code, source, snapshot_at, quality_status,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_code
                           ORDER BY snapshot_at DESC, fetched_at DESC NULLS LAST,
                                    revision_number DESC, id DESC
                       ) AS row_number
                FROM data_center_quote_snapshot
                WHERE asset_code = ANY(%s::text[])
            ) AS selected
            WHERE row_number = 1
            ORDER BY asset_code
            """,
            (list(universe_codes),),
        )
        references: list[Data02HistoricalFactReference] = []
        for row in cursor.fetchall():
            observed_at = _aware(row[3], "quote.snapshot_at")
            natural_key = f"{row[1]}:{observed_at.isoformat()}:{row[2]}"
            references.append(
                _reference(
                    row,
                    fact_table="data_center_quote_snapshot",
                    natural_key=natural_key,
                    observed_at=observed_at,
                )
            )
        return tuple(references)

    @staticmethod
    def _price_facts(
        cursor: Cursor[tuple[object, ...]],
        universe_codes: tuple[str, ...],
    ) -> tuple[Data02HistoricalFactReference, ...]:
        """Select the latest daily unadjusted price per asset."""

        cursor.execute(
            """
            SELECT id, asset_code, source, bar_date, quality_status, freq, adjustment
            FROM (
                SELECT id, asset_code, source, bar_date, quality_status, freq, adjustment,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_code
                           ORDER BY bar_date DESC, fetched_at DESC,
                                    revision_number DESC, id DESC
                       ) AS row_number
                FROM data_center_price_bar
                WHERE asset_code = ANY(%s::text[])
                  AND freq = '1d'
                  AND adjustment = 'none'
            ) AS selected
            WHERE row_number = 1
            ORDER BY asset_code
            """,
            (list(universe_codes),),
        )
        references: list[Data02HistoricalFactReference] = []
        for row in cursor.fetchall():
            bar_date = _date(row[3], "price.bar_date")
            observed_at = _market_date(bar_date, "price.bar_date")
            natural_key = f"{row[1]}:{bar_date.isoformat()}:{row[5]}:{row[6]}:{row[2]}"
            references.append(
                _reference(
                    row,
                    fact_table="data_center_price_bar",
                    natural_key=natural_key,
                    observed_at=observed_at,
                )
            )
        return tuple(references)

    @staticmethod
    def _valuation_facts(
        cursor: Cursor[tuple[object, ...]],
        universe_codes: tuple[str, ...],
    ) -> tuple[Data02HistoricalFactReference, ...]:
        """Select the deterministic latest valuation per asset."""

        cursor.execute(
            """
            SELECT id, asset_code, source, val_date, quality_status, available_at
            FROM (
                SELECT id, asset_code, source, val_date, quality_status, available_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY asset_code
                           ORDER BY val_date DESC, available_at DESC NULLS LAST,
                                    fetched_at DESC, revision_number DESC, id DESC
                       ) AS row_number
                FROM data_center_valuation_fact
                WHERE asset_code = ANY(%s::text[])
            ) AS selected
            WHERE row_number = 1
            ORDER BY asset_code
            """,
            (list(universe_codes),),
        )
        references: list[Data02HistoricalFactReference] = []
        for row in cursor.fetchall():
            valuation_date = _date(row[3], "valuation.val_date")
            observed_at = _market_date(valuation_date, "valuation.val_date")
            natural_key = f"{row[1]}:{valuation_date.isoformat()}:{row[2]}"
            references.append(
                _reference(
                    row,
                    fact_table="data_center_valuation_fact",
                    natural_key=natural_key,
                    observed_at=observed_at,
                    quality_status=(
                        _text(row[4], "quality_status")
                        if row[5] is not None
                        else "available_at_unverified"
                    ),
                )
            )
        return tuple(references)

    @staticmethod
    def _financial_facts(
        cursor: Cursor[tuple[object, ...]],
        universe_codes: tuple[str, ...],
    ) -> tuple[Data02HistoricalFactReference, ...]:
        """Select every metric from each asset's latest evidence-safe period."""

        cursor.execute(
            """
            WITH latest_period AS (
                SELECT asset_code, MAX(period_end) AS period_end
                FROM data_center_financial_fact
                WHERE asset_code = ANY(%s::text[]) AND available_at IS NOT NULL
                GROUP BY asset_code
            ), ranked AS (
                SELECT fact.id, fact.asset_code, fact.source, fact.available_at,
                       fact.quality_status, fact.period_end, fact.period_type,
                       fact.metric_code,
                       ROW_NUMBER() OVER (
                           PARTITION BY fact.asset_code, fact.period_end,
                                        fact.period_type, fact.metric_code
                           ORDER BY fact.available_at DESC, fact.revision_number DESC,
                                    fact.fetched_at DESC, fact.id DESC
                       ) AS row_number
                FROM data_center_financial_fact AS fact
                JOIN latest_period
                  ON latest_period.asset_code = fact.asset_code
                 AND latest_period.period_end = fact.period_end
                WHERE fact.available_at IS NOT NULL
            )
            SELECT id, asset_code, source, available_at, quality_status,
                   period_end, period_type, metric_code
            FROM ranked
            WHERE row_number = 1
            ORDER BY asset_code, period_type, metric_code
            """,
            (list(universe_codes),),
        )
        references: list[Data02HistoricalFactReference] = []
        for row in cursor.fetchall():
            observed_at = _aware(row[3], "financial.available_at")
            period_end = _date(row[5], "financial.period_end")
            natural_key = f"{row[1]}:{period_end.isoformat()}:{row[6]}:{row[7]}:{row[2]}"
            references.append(
                _reference(
                    row,
                    fact_table="data_center_financial_fact",
                    natural_key=natural_key,
                    observed_at=observed_at,
                )
            )
        return tuple(references)

    @staticmethod
    def _publication(
        cursor: Cursor[tuple[object, ...]],
        dataset_key: str,
        fact_table: str,
    ) -> Data02HistoricalPublicationSnapshot | None:
        """Load the latest published current identity and its exact members."""

        cursor.execute(
            """
            SELECT publication_id, publication_hash, state,
                   must_not_use_for_decision, blocked_reason
            FROM data_center_canonical_publication
            WHERE dataset_key = %s
              AND publication_key = 'current'
              AND state = 'published'
            ORDER BY published_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            (dataset_key,),
        )
        publication = cursor.fetchone()
        if publication is None:
            return None
        publication_id = str(publication[0])
        cursor.execute(
            """
            SELECT natural_key, fact_table, fact_pk, source, observed_at, quality_status
            FROM data_center_publication_member
            WHERE publication_id = %s AND dataset_key = %s
            ORDER BY natural_key
            """,
            (publication[0], dataset_key),
        )
        members: list[Data02HistoricalFactReference] = []
        for row in cursor.fetchall():
            natural_key = _text(row[0], "publication.natural_key")
            member_fact_table = _text(row[1], "publication.fact_table")
            if member_fact_table != fact_table:
                raise RuntimeError(f"publication fact_table mismatch for {dataset_key}")
            members.append(
                Data02HistoricalFactReference(
                    natural_key=natural_key,
                    asset_code=natural_key.split(":", 1)[0].strip().upper(),
                    fact_table=member_fact_table,
                    fact_pk=_text(row[2], "publication.fact_pk"),
                    source=_text(row[3], "publication.source"),
                    observed_at=_aware(row[4], "publication.observed_at"),
                    quality_status=_text(row[5], "publication.quality_status"),
                )
            )
        return Data02HistoricalPublicationSnapshot(
            publication_id=publication_id,
            publication_hash=_text(publication[1], "publication_hash"),
            state=_text(publication[2], "publication_state"),
            must_not_use_for_decision=bool(publication[3]),
            blocked_reason=str(publication[4] or ""),
            members=tuple(members),
        )


__all__ = ["PostgresData02HistoricalSnapshotAdapter"]
