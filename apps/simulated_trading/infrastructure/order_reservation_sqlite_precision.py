"""SQLite-safe decimal envelopes and exact-unit reservation predicates.

SQLite stores Django ``DecimalField`` values as binary floating point. This
module limits only SQLite-backed reservation persistence to values whose
declared decimal quantum and binary64 representation can be checked exactly.
PostgreSQL keeps the full existing NUMERIC/Domain range.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal, InvalidOperation, localcontext
from math import isfinite
from typing import Literal, cast

from django.db import NotSupportedError, connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import BooleanField, Expression, F
from django.db.models.expressions import Combinable
from django.db.models.sql.compiler import SQLCompiler
from django.db.utils import DEFAULT_DB_ALIAS

from apps.simulated_trading.application.execution_settlement_uow import (
    SimulatedTradeExecutionBlocked,
)

PrecisionFamily = Literal["money", "quantity", "price"]
PrecisionValue = tuple[str, object, PrecisionFamily]
_SQLParameter = str | int
_SQLParameters = tuple[_SQLParameter, ...]
_CompiledSQL = tuple[str, _SQLParameters]
PrecisionErrorCode = Literal[
    "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED",
    "ORDER_RESERVATION_STATE_INVALID",
]

_SQLITE_MAX_EXACT_INTEGER = 9_007_199_254_740_991
_FAMILY_SPECS: dict[PrecisionFamily, tuple[Decimal, Decimal, int]] = {
    "money": (Decimal("10000000000000"), Decimal("0.01"), 2),
    "quantity": (Decimal("1000000000"), Decimal("0.000001"), 6),
    "price": (Decimal("1000000"), Decimal("0.0001"), 4),
}

_MONEY_COLUMNS: tuple[tuple[str, bool], ...] = (
    ("notional", False),
    ("fee_estimate", False),
    ("fee_budget", True),
    ("commission_estimate", False),
    ("transfer_fee_estimate", False),
    ("stamp_duty_estimate", False),
    ("slippage_estimate", False),
    ("cash_reserved", False),
    ("cash_consumed", False),
    ("cash_released", False),
    ("source_book_cash", True),
)
_QUANTITY_COLUMNS: tuple[tuple[str, bool], ...] = (
    ("quantity", False),
    ("shares_reserved", False),
    ("filled_quantity", False),
    ("shares_consumed", False),
    ("shares_released", False),
    ("source_sellable_quantity", True),
)
_PRICE_COLUMNS: tuple[tuple[str, bool], ...] = (("limit_price", False),)
_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "sqlite_envelope": tuple(
        name for fields in (_MONEY_COLUMNS, _QUANTITY_COLUMNS, _PRICE_COLUMNS) for name, _ in fields
    ),
    "amounts_conserved": (
        "filled_quantity",
        "quantity",
        "cash_consumed",
        "cash_reserved",
        "cash_released",
        "shares_consumed",
        "shares_reserved",
        "shares_released",
    ),
    "side_resources": (
        "side",
        "shares_reserved",
        "shares_consumed",
        "shares_released",
        "fee_budget",
        "fee_estimate",
        "cash_reserved",
        "notional",
        "quantity",
        "filled_quantity",
    ),
    "state_conservation": (
        "status",
        "cancelled_at",
        "filled_quantity",
        "quantity",
        "cash_released",
        "shares_released",
        "side",
        "cash_consumed",
        "cash_reserved",
        "shares_consumed",
        "shares_reserved",
    ),
}


def sqlite_decimal_fits(value: object, family: PrecisionFamily) -> bool:
    """Return whether one exact Decimal fits SQLite's supported ledger range.

    ``money`` supports the complete DecimalField(15, 2) range, ``price`` the
    complete DecimalField(10, 4) range, and ``quantity`` the intentionally
    narrower 9-integer-digit by 6-decimal-place SQLite envelope.
    """

    if type(value) is not Decimal or type(family) is not str or family not in _FAMILY_SPECS:
        return False
    limit, quantum, decimal_places = _FAMILY_SPECS[family]
    amount = value
    if not amount.is_finite() or amount < 0 or amount >= limit:
        return False
    try:
        with localcontext() as context:
            context.prec = 80
            canonical = amount.quantize(quantum)
            if canonical != amount:
                return False
            scaled = amount.scaleb(decimal_places)
            if scaled != scaled.to_integral_value():
                return False
            if abs(int(scaled)) > _SQLITE_MAX_EXACT_INTEGER:
                return False
            binary64 = float(amount)
            if not isfinite(binary64):
                return False
            sqlite_round_trip = Decimal(str(binary64)).quantize(quantum)
    except (ArithmeticError, InvalidOperation, OverflowError, ValueError):
        return False
    return sqlite_round_trip == amount


def require_sqlite_values(
    *,
    values: Iterable[PrecisionValue],
    using: str = DEFAULT_DB_ALIAS,
    error_code: PrecisionErrorCode = "ORDER_RESERVATION_STORAGE_PRECISION_UNSUPPORTED",
) -> None:
    """Reject known ledger values outside the exact SQLite storage envelope.

    Call this before writing a new ledger value and before consuming a known
    persisted value. PostgreSQL keeps its full NUMERIC range. Callers must omit
    unknown values represented by ``None`` rather than substituting zero.
    """

    if connections[using].vendor != "sqlite":
        return
    for field_name, value, family in values:
        if value is None or sqlite_decimal_fits(value, family):
            continue
        if error_code == "ORDER_RESERVATION_STATE_INVALID":
            message = f"stored {field_name} exceeds the supported SQLite precision range"
        else:
            message = f"{field_name} exceeds the supported SQLite ledger precision range"
        raise SimulatedTradeExecutionBlocked(message, code=error_code)


class OrderReservationPrecisionCheck(Expression):
    """Serialize backend-aware reservation storage and unit constraints.

    The SQLite envelope is a backend capability guard. The conservation
    predicates use integer decimal units only on SQLite; PostgreSQL compiles
    the pre-existing exact NUMERIC predicates unchanged.
    """

    _KINDS = frozenset(
        {
            "sqlite_envelope",
            "amounts_conserved",
            "side_resources",
            "state_conservation",
        }
    )

    def __init__(self, kind: str) -> None:
        """Create one named, migration-serializable check expression."""

        if type(kind) is not str or kind not in self._KINDS:
            raise ValueError("unsupported simulated-order precision check kind")
        super().__init__(output_field=BooleanField())
        self.kind = kind
        self._source_expressions: list[Expression] = [
            cast(Expression, F(name)) for name in _FIELDS_BY_KIND[kind]
        ]

    def get_source_expressions(self) -> list[Expression]:
        """Return F references so model validation and schema compilation see columns."""

        return list(self._source_expressions)

    def set_source_expressions(self, expressions: Sequence[Combinable | Expression]) -> None:
        """Retain the resolved F/Col expressions supplied by Django's query compiler."""

        if len(expressions) != len(_FIELDS_BY_KIND[self.kind]):
            raise ValueError("reservation precision expression columns are incomplete")
        self._source_expressions = cast(list[Expression], list(expressions))

    def deconstruct(self) -> tuple[str, tuple[object, ...], dict[str, object]]:
        """Return stable migration state for the selected check kind."""

        return f"{type(self).__module__}.{type(self).__qualname__}", (self.kind,), {}

    def as_sql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: object,
    ) -> _CompiledSQL:
        """Select the explicit SQLite or PostgreSQL implementation."""

        del extra_context
        if connection.vendor == "sqlite":
            return self.as_sqlite(compiler, connection)
        if connection.vendor == "postgresql":
            return self.as_postgresql(compiler, connection)
        raise NotSupportedError(
            "simulated-order reservation precision checks support SQLite and PostgreSQL"
        )

    def as_sqlite(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: object,
    ) -> _CompiledSQL:
        """Compile SQLite envelopes and scaled-integer resource comparisons."""

        del connection, extra_context
        compiled = self._compiled_columns(compiler)
        markers = self._column_markers()
        if self.kind == "sqlite_envelope":
            sql = self._sqlite_envelope(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        if self.kind == "amounts_conserved":
            sql = self._sqlite_amounts_conserved(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        if self.kind == "side_resources":
            sql = self._sqlite_side_resources(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        if self.kind == "state_conservation":
            sql = self._sqlite_state_conservation(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        raise NotSupportedError("unknown reservation precision constraint")

    def as_postgresql(
        self,
        compiler: SQLCompiler,
        connection: BaseDatabaseWrapper,
        **extra_context: object,
    ) -> _CompiledSQL:
        """Preserve PostgreSQL's full exact NUMERIC range and prior predicates."""

        del connection, extra_context
        if self.kind == "sqlite_envelope":
            return "TRUE", ()
        compiled = self._compiled_columns(compiler)
        markers = self._column_markers()
        if self.kind == "amounts_conserved":
            sql = self._postgres_amounts_conserved(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        if self.kind == "side_resources":
            sql = self._postgres_side_resources(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        if self.kind == "state_conservation":
            sql = self._postgres_state_conservation(markers)
            return self._bind_column_parameters(sql, compiled, markers)
        raise NotSupportedError("unknown reservation precision constraint")

    def _compiled_columns(self, compiler: SQLCompiler) -> dict[str, _CompiledSQL]:
        """Compile each F/Col or validation Value with its bound parameters."""

        columns: dict[str, _CompiledSQL] = {}
        for name, expression in zip(
            _FIELDS_BY_KIND[self.kind], self.get_source_expressions(), strict=True
        ):
            if isinstance(expression, F):
                expression = cast(
                    Expression,
                    expression.resolve_expression(compiler.query, allow_joins=False),
                )
            sql, params = compiler.compile(expression)
            columns[name] = (sql, tuple(params))
        return columns

    def _column_markers(self) -> dict[str, str]:
        """Return private placeholders that survive predicate construction."""

        return {
            name: f"\x00ORC{index}\x00" for index, name in enumerate(_FIELDS_BY_KIND[self.kind])
        }

    @staticmethod
    def _bind_column_parameters(
        sql_template: str,
        compiled: dict[str, _CompiledSQL],
        markers: dict[str, str],
    ) -> _CompiledSQL:
        """Expand field SQL in occurrence order and duplicate bound values as needed."""

        marker_names = {marker: name for name, marker in markers.items()}
        pieces: list[str] = []
        parameters: list[_SQLParameter] = []
        cursor = 0
        while cursor < len(sql_template):
            matches = [
                (position, marker)
                for marker in marker_names
                if (position := sql_template.find(marker, cursor)) >= 0
            ]
            if not matches:
                pieces.append(sql_template[cursor:])
                break
            position, marker = min(matches, key=lambda match: match[0])
            pieces.append(sql_template[cursor:position])
            name = marker_names[marker]
            column_sql, column_parameters = compiled[name]
            pieces.append(column_sql)
            parameters.extend(column_parameters)
            cursor = position + len(marker)
        return "".join(pieces), tuple(parameters)

    @staticmethod
    def _units(columns: dict[str, str], name: str, family: PrecisionFamily) -> str:
        """Return a rounded integer unit expression for one bounded column."""

        _, _, decimal_places = _FAMILY_SPECS[family]
        return f"ROUND({columns[name]} * {10**decimal_places}, 0)"

    @classmethod
    def _sqlite_envelope(cls, columns: dict[str, str]) -> str:
        """Check every stored monetary, share, and price decimal separately."""

        clauses: list[str] = []
        families: tuple[tuple[PrecisionFamily, tuple[tuple[str, bool], ...]], ...] = (
            ("money", _MONEY_COLUMNS),
            ("quantity", _QUANTITY_COLUMNS),
            ("price", _PRICE_COLUMNS),
        )
        for family, fields in families:
            limit, _, decimal_places = _FAMILY_SPECS[family]
            limit_text = format(limit, "f")
            for name, nullable in fields:
                column = columns[name]
                accepted = (
                    f"({column} >= 0 AND {column} < {limit_text} "
                    f"AND ROUND({column}, {decimal_places}) = {column})"
                )
                if nullable:
                    clauses.append(f"({column} IS NULL OR {accepted})")
                else:
                    clauses.append(f"({column} IS NOT NULL AND {accepted})")
        return "(" + " AND ".join(clauses) + ")"

    @classmethod
    def _sqlite_amounts_conserved(cls, columns: dict[str, str]) -> str:
        """Compare SQLite integer units instead of chained REAL arithmetic."""

        return " AND ".join(
            (
                f"({cls._units(columns, 'filled_quantity', 'quantity')} <= "
                f"{cls._units(columns, 'quantity', 'quantity')})",
                f"({cls._units(columns, 'cash_consumed', 'money')} <= "
                f"({cls._units(columns, 'cash_reserved', 'money')} - "
                f"{cls._units(columns, 'cash_released', 'money')}))",
                f"({cls._units(columns, 'shares_consumed', 'quantity')} <= "
                f"({cls._units(columns, 'shares_reserved', 'quantity')} - "
                f"{cls._units(columns, 'shares_released', 'quantity')}))",
            )
        )

    @classmethod
    def _sqlite_side_resources(cls, columns: dict[str, str]) -> str:
        """Preserve the BUY/SELL resource contract in scaled SQLite units."""

        side = columns["side"]
        buy = " AND ".join(
            (
                f"{side} = 'buy'",
                f"{cls._units(columns, 'shares_reserved', 'quantity')} = 0",
                f"{cls._units(columns, 'shares_consumed', 'quantity')} = 0",
                f"{cls._units(columns, 'shares_released', 'quantity')} = 0",
                f"{columns['fee_budget']} IS NOT NULL",
                f"{cls._units(columns, 'fee_budget', 'money')} >= "
                f"{cls._units(columns, 'fee_estimate', 'money')}",
                f"{cls._units(columns, 'cash_reserved', 'money')} = "
                f"({cls._units(columns, 'notional', 'money')} + "
                f"{cls._units(columns, 'fee_budget', 'money')})",
            )
        )
        sell = " AND ".join(
            (
                f"{side} = 'sell'",
                f"{cls._units(columns, 'shares_reserved', 'quantity')} = "
                f"{cls._units(columns, 'quantity', 'quantity')}",
                f"{cls._units(columns, 'shares_consumed', 'quantity')} = "
                f"{cls._units(columns, 'filled_quantity', 'quantity')}",
                f"{columns['fee_budget']} IS NULL",
            )
        )
        return f"({buy} OR {sell})"

    @classmethod
    def _sqlite_state_conservation(cls, columns: dict[str, str]) -> str:
        """Validate active and terminal state conservation with exact units."""

        status = columns["status"]
        cancelled_at = columns["cancelled_at"]
        filled = cls._units(columns, "filled_quantity", "quantity")
        quantity = cls._units(columns, "quantity", "quantity")
        cash_consumed = cls._units(columns, "cash_consumed", "money")
        cash_reserved = cls._units(columns, "cash_reserved", "money")
        cash_released = cls._units(columns, "cash_released", "money")
        shares_consumed = cls._units(columns, "shares_consumed", "quantity")
        shares_reserved = cls._units(columns, "shares_reserved", "quantity")
        shares_released = cls._units(columns, "shares_released", "quantity")
        side = columns["side"]
        active = (
            f"({status} = 'active' AND {cancelled_at} IS NULL AND {filled} < {quantity} "
            f"AND {cash_released} = 0 AND {shares_released} = 0 AND "
            f"(({side} = 'buy' AND {cash_consumed} < {cash_reserved}) OR "
            f"({side} = 'sell' AND {shares_consumed} < {shares_reserved})))"
        )
        completed = (
            f"({status} = 'completed' AND {cancelled_at} IS NULL AND {filled} = {quantity} "
            f"AND {cash_consumed} = ({cash_reserved} - {cash_released}) "
            f"AND {shares_consumed} = ({shares_reserved} - {shares_released}))"
        )
        cancelled = (
            f"({status} = 'cancelled' AND {cancelled_at} IS NOT NULL AND {filled} < {quantity} "
            f"AND {cash_consumed} = ({cash_reserved} - {cash_released}) "
            f"AND {shares_consumed} = ({shares_reserved} - {shares_released}))"
        )
        return f"({active} OR {completed} OR {cancelled})"

    @staticmethod
    def _postgres_amounts_conserved(columns: dict[str, str]) -> str:
        """Preserve the original exact PostgreSQL NUMERIC conservation check."""

        return (
            f"({columns['filled_quantity']} <= {columns['quantity']}) AND "
            f"({columns['cash_consumed']} <= "
            f"({columns['cash_reserved']} - {columns['cash_released']})) AND "
            f"({columns['shares_consumed']} <= "
            f"({columns['shares_reserved']} - {columns['shares_released']}))"
        )

    @staticmethod
    def _postgres_side_resources(columns: dict[str, str]) -> str:
        """Preserve the original exact PostgreSQL BUY/SELL resource check."""

        buy = (
            f"({columns['side']} = 'buy' AND {columns['shares_reserved']} = 0 "
            f"AND {columns['shares_consumed']} = 0 "
            f"AND {columns['shares_released']} = 0 "
            f"AND {columns['fee_budget']} IS NOT NULL "
            f"AND {columns['fee_budget']} >= {columns['fee_estimate']} "
            f"AND {columns['cash_reserved']} = "
            f"({columns['notional']} + {columns['fee_budget']}))"
        )
        sell = (
            f"({columns['side']} = 'sell' "
            f"AND {columns['shares_reserved']} = {columns['quantity']} "
            f"AND {columns['shares_consumed']} = {columns['filled_quantity']} "
            f"AND {columns['fee_budget']} IS NULL)"
        )
        return f"({buy} OR {sell})"

    @staticmethod
    def _postgres_state_conservation(columns: dict[str, str]) -> str:
        """Preserve the original exact PostgreSQL reservation-state check."""

        active = (
            f"({columns['status']} = 'active' "
            f"AND {columns['cancelled_at']} IS NULL "
            f"AND {columns['filled_quantity']} < {columns['quantity']} "
            f"AND {columns['cash_released']} = 0 "
            f"AND {columns['shares_released']} = 0 "
            f"AND (({columns['side']} = 'buy' "
            f"AND {columns['cash_consumed']} < {columns['cash_reserved']}) "
            f"OR ({columns['side']} = 'sell' "
            f"AND {columns['shares_consumed']} < {columns['shares_reserved']})))"
        )
        completed = (
            f"({columns['status']} = 'completed' "
            f"AND {columns['cancelled_at']} IS NULL "
            f"AND {columns['filled_quantity']} = {columns['quantity']} "
            f"AND {columns['cash_consumed']} = "
            f"({columns['cash_reserved']} - {columns['cash_released']}) "
            f"AND {columns['shares_consumed']} = "
            f"({columns['shares_reserved']} - {columns['shares_released']}))"
        )
        cancelled = (
            f"({columns['status']} = 'cancelled' "
            f"AND {columns['cancelled_at']} IS NOT NULL "
            f"AND {columns['filled_quantity']} < {columns['quantity']} "
            f"AND {columns['cash_consumed']} = "
            f"({columns['cash_reserved']} - {columns['cash_released']}) "
            f"AND {columns['shares_consumed']} = "
            f"({columns['shares_reserved']} - {columns['shares_released']}))"
        )
        return f"({active} OR {completed} OR {cancelled})"


__all__: tuple[str, ...] = (
    "OrderReservationPrecisionCheck",
    "PrecisionErrorCode",
    "PrecisionFamily",
    "PrecisionValue",
    "require_sqlite_values",
    "sqlite_decimal_fits",
)
