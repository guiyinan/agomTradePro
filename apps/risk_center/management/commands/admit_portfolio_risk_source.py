"""Validate an operator-normalized source document and optionally retain it."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, NoReturn

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.data_center.application.raw_landing_public import RawPayloadLandingNotConfigured
from apps.risk_center.application.portfolio_risk_source_admission import (
    PortfolioRiskSourceAdmissionError,
    parse_portfolio_risk_source_admission_request,
)
from apps.risk_center.source_admission_composition import (
    build_portfolio_risk_source_admission_use_case,
)


class Command(BaseCommand):
    """Create a dry-run RawPayload candidate; ``--write`` opts into persistence."""

    help = (
        "Validate the shape of operator-reviewed risk facts and bind exact original bytes; "
        "does not parse vendor content. Writes RawPayload only with --write."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Require the fact document and its separately retained original bytes."""

        parser.add_argument(
            "--document",
            required=True,
            help="UTF-8 admission request JSON containing explicit source evidence and facts.",
        )
        parser.add_argument(
            "--original-body",
            required=True,
            help="Path to the exact original response bytes; the command does not parse them.",
        )
        parser.add_argument(
            "--write",
            action="store_true",
            help="Persist the validated candidate to the existing Data Center RawPayload store.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Build a candidate locally and write only after the explicit option."""

        document_path = Path(str(options["document"]))
        body_path = Path(str(options["original_body"]))
        persist = options.get("write") is True
        try:
            raw_document = _read_admission_document(document_path)
            original_body = body_path.read_bytes()
            request = parse_portfolio_risk_source_admission_request(
                raw_document,
                original_body=original_body,
            )
            result = build_portfolio_risk_source_admission_use_case().execute(
                request,
                persist=persist,
            )
        except (
            OSError,
            TypeError,
            ValueError,
            RawPayloadLandingNotConfigured,
        ) as exc:
            code = exc.code if isinstance(exc, PortfolioRiskSourceAdmissionError) else str(exc)
            raise CommandError(f"Risk source admission failed: {code}") from exc

        mode = "stored" if result.stored else "dry-run only; not stored"
        self.stdout.write(
            f"{mode}; payload_id={result.payload.payload_id}; "
            f"raw_payload_hash={result.payload.payload_hash}; "
            f"dataset={result.payload.dataset_key}"
        )


def _read_admission_document(path: Path) -> object:
    """Decode strict UTF-8 JSON while rejecting duplicate keys and non-finite values."""

    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(
            text,
            object_pairs_hook=_unique_object_pairs,
            parse_float=Decimal,
            parse_constant=_reject_nonfinite,
        )
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError("admission_document_json_invalid") from exc


def _unique_object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject duplicate keys instead of silently selecting one fact value."""

    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("admission_document_duplicate_key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> NoReturn:
    """Reject JSON NaN/Infinity constants before they enter the typed request."""

    raise ValueError(f"admission_document_nonfinite_number:{value}")
