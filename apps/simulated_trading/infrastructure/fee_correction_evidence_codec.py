"""Finite CSV codec for operator-attested simulated fee evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TypedDict

from apps.simulated_trading.application.fee_correction_evidence import (
    MAX_UPLOAD_BYTES,
    OPERATOR_FEE_CSV_SCHEMA,
    FeeEvidenceFeeMetadataJSON,
    FeeEvidenceParsedMetadataJSON,
    FeeEvidenceRawRowJSON,
    OperatorAttestedFeeEvidenceRow,
)

_HEADERS: tuple[str, ...] = (
    "schema_version",
    "currency_code",
    "source_account_ref",
    "source_trade_ref",
    "asset_code",
    "side",
    "quantity",
    "price",
    "amount",
    "execution_at",
    "source_observed_at",
    "commission",
    "transfer_fee",
    "stamp_duty",
)
_UNAVAILABLE = r"\N"
_DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_ASSET_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,19}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


class _CanonicalEvidencePayload(TypedDict):
    """Canonical digest payload, with raw lexemes and parsed values retained."""

    schema: str
    raw_row: dict[str, str]
    parsed_metadata: FeeEvidenceParsedMetadataJSON


class FeeEvidenceCsvParseError(ValueError):
    """Raised when an upload is not the single-row operator evidence schema."""


def parse_operator_fee_evidence_csv(content: bytes) -> OperatorAttestedFeeEvidenceRow:
    """Parse one exact UTF-8 CSV row without defaulting any unknown fee to zero."""

    if type(content) is not bytes or not content or len(content) > MAX_UPLOAD_BYTES:
        raise FeeEvidenceCsvParseError("upload bytes are empty or exceed the local size limit")
    try:
        decoded = content.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as error:
        raise FeeEvidenceCsvParseError("CSV must be valid UTF-8") from error
    if "\x00" in decoded:
        raise FeeEvidenceCsvParseError("CSV must not contain NUL bytes")
    try:
        reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
        rows = list(reader)
    except csv.Error as error:
        raise FeeEvidenceCsvParseError("CSV syntax is invalid") from error
    if len(rows) != 2:
        raise FeeEvidenceCsvParseError("CSV must contain one header and exactly one data row")
    header, values = rows
    if tuple(header) != _HEADERS or len(set(header)) != len(_HEADERS):
        raise FeeEvidenceCsvParseError("CSV headers do not match the fixed v2 schema")
    if len(values) != len(_HEADERS):
        raise FeeEvidenceCsvParseError("CSV row has missing or extra cells")
    raw: FeeEvidenceRawRowJSON = {
        "schema_version": values[0],
        "currency_code": values[1],
        "source_account_ref": values[2],
        "source_trade_ref": values[3],
        "asset_code": values[4],
        "side": values[5],
        "quantity": values[6],
        "price": values[7],
        "amount": values[8],
        "execution_at": values[9],
        "source_observed_at": values[10],
        "commission": values[11],
        "transfer_fee": values[12],
        "stamp_duty": values[13],
    }
    if raw["schema_version"] != OPERATOR_FEE_CSV_SCHEMA:
        raise FeeEvidenceCsvParseError("CSV schema version is unsupported")
    source_account_ref = _required_token(raw["source_account_ref"], "source_account_ref", 128)
    source_trade_ref = _required_token(raw["source_trade_ref"], "source_trade_ref", 128)
    currency_code = raw["currency_code"]
    if not _CURRENCY_PATTERN.fullmatch(currency_code):
        raise FeeEvidenceCsvParseError(
            "currency_code must be an explicit uppercase three-letter code"
        )
    asset_code = raw["asset_code"]
    if not _ASSET_PATTERN.fullmatch(asset_code):
        raise FeeEvidenceCsvParseError("asset_code must be a canonical uppercase token")
    side = raw["side"]
    if side not in ("buy", "sell"):
        raise FeeEvidenceCsvParseError("side must be exactly buy or sell")
    quantity, _ = _parse_decimal(raw["quantity"], "quantity", max_precision=6, positive=True)
    price, _ = _parse_decimal(raw["price"], "price", max_precision=4, positive=True)
    amount, _ = _parse_decimal(raw["amount"], "amount", max_precision=2, positive=True)
    execution_at = _parse_datetime(raw["execution_at"], "execution_at")
    source_observed_at = _parse_datetime(raw["source_observed_at"], "source_observed_at")
    fee_fields: tuple[str, str, str] = ("commission", "transfer_fee", "stamp_duty")
    fee_lexemes = (raw["commission"], raw["transfer_fee"], raw["stamp_duty"])
    fee_values: list[Decimal | None] = []
    fee_precisions: list[int | None] = []
    fee_known: list[bool] = []
    fee_payloads: list[FeeEvidenceFeeMetadataJSON] = []
    for field, lexeme in zip(fee_fields, fee_lexemes, strict=True):
        if lexeme == _UNAVAILABLE:
            fee_values.append(None)
            fee_precisions.append(None)
            fee_known.append(False)
            fee_payloads.append(
                {"field": field, "raw": lexeme, "known": False, "precision": None, "value": None}
            )
            continue
        fee_value, precision = _parse_decimal(
            lexeme,
            field,
            max_precision=None,
            positive=False,
        )
        fee_values.append(fee_value)
        fee_precisions.append(precision)
        fee_known.append(True)
        fee_payloads.append(
            {
                "field": field,
                "raw": lexeme,
                "known": True,
                "precision": precision,
                "value": format(fee_value, "f"),
            }
        )
    parsed_metadata: FeeEvidenceParsedMetadataJSON = {
        "schema": "operator-fee-parsed-metadata.v2",
        "currency_code": currency_code,
        "quantity": format(quantity, "f"),
        "price": format(price, "f"),
        "amount": format(amount, "f"),
        "execution_at_utc": _canonical_datetime(execution_at),
        "source_observed_at_utc": _canonical_datetime(source_observed_at),
        "fees": fee_payloads,
    }
    parsed_payload: _CanonicalEvidencePayload = {
        "schema": "operator-attested-fee-row.v2",
        "raw_row": {
            "schema_version": raw["schema_version"],
            "currency_code": raw["currency_code"],
            "source_account_ref": raw["source_account_ref"],
            "source_trade_ref": raw["source_trade_ref"],
            "asset_code": raw["asset_code"],
            "side": raw["side"],
            "quantity": raw["quantity"],
            "price": raw["price"],
            "amount": raw["amount"],
            "execution_at": raw["execution_at"],
            "source_observed_at": raw["source_observed_at"],
            "commission": raw["commission"],
            "transfer_fee": raw["transfer_fee"],
            "stamp_duty": raw["stamp_duty"],
        },
        "parsed_metadata": parsed_metadata,
    }
    encoded = json.dumps(
        parsed_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return OperatorAttestedFeeEvidenceRow(
        schema_version=raw["schema_version"],
        source_account_ref=source_account_ref,
        source_trade_ref=source_trade_ref,
        currency_code=currency_code,
        asset_code=asset_code,
        side=side,
        quantity=quantity,
        price=price,
        amount=amount,
        execution_at=execution_at,
        source_observed_at=source_observed_at,
        fee_lexemes=(fee_lexemes[0], fee_lexemes[1], fee_lexemes[2]),
        fee_amounts=(fee_values[0], fee_values[1], fee_values[2]),
        fee_precisions=(fee_precisions[0], fee_precisions[1], fee_precisions[2]),
        fee_known=(fee_known[0], fee_known[1], fee_known[2]),
        raw_row=raw,
        parsed_metadata=parsed_metadata,
        payload_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _required_token(value: str, field_name: str, max_length: int) -> str:
    """Require a bounded nonblank token while preserving its exact spelling."""

    if (
        type(value) is not str
        or not value
        or value.strip() != value
        or len(value) > max_length
        or any(ord(character) < 32 for character in value)
    ):
        raise FeeEvidenceCsvParseError(f"{field_name} is empty or malformed")
    return value


def _parse_decimal(
    value: str,
    field_name: str,
    *,
    max_precision: int | None,
    positive: bool,
) -> tuple[Decimal, int]:
    """Parse an exact unsigned decimal lexeme and reject unsupported scale."""

    if type(value) is not str or len(value) > 32 or not _DECIMAL_PATTERN.fullmatch(value):
        raise FeeEvidenceCsvParseError(f"{field_name} is not a plain decimal lexeme")
    precision = len(value.partition(".")[2]) if "." in value else 0
    if max_precision is not None and precision > max_precision:
        raise FeeEvidenceCsvParseError(f"{field_name} has unsupported precision")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise FeeEvidenceCsvParseError(f"{field_name} is not a Decimal") from error
    if not amount.is_finite() or (amount <= 0 if positive else amount < 0):
        raise FeeEvidenceCsvParseError(
            f"{field_name} must be {'positive' if positive else 'nonnegative'}"
        )
    return amount, precision


def _parse_datetime(value: str, field_name: str) -> datetime:
    """Parse an ISO timestamp only when it carries an explicit UTC offset."""

    if type(value) is not str or not value or value.strip() != value:
        raise FeeEvidenceCsvParseError(f"{field_name} is empty or malformed")
    iso_value = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(iso_value)
    except ValueError as error:
        raise FeeEvidenceCsvParseError(f"{field_name} must be ISO-8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FeeEvidenceCsvParseError(f"{field_name} must include an explicit timezone offset")
    return parsed


def _canonical_datetime(value: datetime) -> str:
    """Encode an aware timestamp in UTC with fixed microsecond precision."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


__all__ = ["FeeEvidenceCsvParseError", "parse_operator_fee_evidence_csv"]
