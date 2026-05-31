"""Manual broker trade import and decision replay orchestration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

from apps.account.application.repository_provider import (
    build_broker_trade_file_parser,
    get_manual_trade_sync_repository,
    get_portfolio_api_repository,
)
from apps.decision_rhythm.application.repository_provider import (
    get_unified_recommendation_repository,
)
from apps.decision_rhythm.domain.entities import UserDecisionAction
from apps.simulated_trading.application.unified_position_service import UnifiedPositionService

REQUIRED_COLUMNS = {"traded_at", "action", "asset_code", "shares", "price"}
OPTIONAL_COLUMNS = {"commission", "stamp_duty", "transfer_fee", "external_trade_id", "notes"}
ACTION_TO_SIDE = {"buy": "BUY", "sell": "SELL"}


@dataclass(frozen=True)
class NormalizedTradeRow:
    row_number: int
    traded_at: datetime
    action: str
    asset_code: str
    shares: float
    price: Decimal
    commission: Decimal
    stamp_duty: Decimal
    transfer_fee: Decimal
    external_trade_id: str
    notes: str
    broker_trade_key: str
    raw_payload: dict[str, Any]

    def to_preview_dict(self, *, duplicate: bool = False) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "traded_at": self.traded_at.isoformat(),
            "action": self.action,
            "asset_code": self.asset_code,
            "shares": self.shares,
            "price": str(self.price),
            "commission": str(self.commission),
            "stamp_duty": str(self.stamp_duty),
            "transfer_fee": str(self.transfer_fee),
            "external_trade_id": self.external_trade_id,
            "broker_trade_key": self.broker_trade_key,
            "duplicate": duplicate,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class BrokerTradeImportResult:
    total_rows: int
    valid_rows: int
    duplicate_rows: int
    error_rows: int
    rows: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    imported_rows: int = 0
    skipped_rows: int = 0
    batch_id: int | None = None


class ManualTradeImportUseCase:
    """Preview and confirm manual broker trade imports."""

    def __init__(
        self,
        *,
        sync_repo=None,
        portfolio_repo=None,
        recommendation_repo=None,
        parser=None,
        position_service=None,
    ) -> None:
        self.sync_repo = sync_repo or get_manual_trade_sync_repository()
        self.portfolio_repo = portfolio_repo or get_portfolio_api_repository()
        self.recommendation_repo = recommendation_repo or get_unified_recommendation_repository()
        self.parser = parser or build_broker_trade_file_parser()
        self.position_service = position_service or UnifiedPositionService.default()

    def preview(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        filename: str,
        content: bytes,
    ) -> BrokerTradeImportResult:
        portfolio = self.sync_repo.get_owned_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        if portfolio is None:
            raise LookupError(f"Portfolio {portfolio_id} does not exist or is not owned by user")

        raw_rows = self.parser.parse(content=content, filename=filename)
        normalized_rows, errors = self._normalize_rows(
            raw_rows,
            broker_name=broker_name,
            portfolio_id=portfolio_id,
        )
        preview_rows = []
        duplicate_rows = 0
        for row in normalized_rows:
            duplicate = self.sync_repo.broker_trade_key_exists(row.broker_trade_key)
            duplicate_rows += 1 if duplicate else 0
            preview_rows.append(row.to_preview_dict(duplicate=duplicate))

        return BrokerTradeImportResult(
            total_rows=len(raw_rows),
            valid_rows=len(normalized_rows),
            duplicate_rows=duplicate_rows,
            error_rows=len(errors),
            rows=preview_rows,
            errors=errors,
        )

    def confirm(
        self,
        *,
        user_id: int,
        portfolio_id: int,
        broker_name: str,
        filename: str,
        content: bytes,
    ) -> BrokerTradeImportResult:
        portfolio = self.sync_repo.get_owned_portfolio(user_id=user_id, portfolio_id=portfolio_id)
        if portfolio is None:
            raise LookupError(f"Portfolio {portfolio_id} does not exist or is not owned by user")

        file_hash = hashlib.sha256(content).hexdigest()
        raw_rows = self.parser.parse(content=content, filename=filename)
        normalized_rows, errors = self._normalize_rows(
            raw_rows,
            broker_name=broker_name,
            portfolio_id=portfolio_id,
        )
        preview_rows = [row.to_preview_dict() for row in normalized_rows[:50]]
        batch = self.sync_repo.create_import_batch(
            user_id=user_id,
            portfolio_id=portfolio_id,
            broker_name=broker_name,
            source_filename=filename,
            file_hash=file_hash,
            total_rows=len(raw_rows),
            preview_rows=preview_rows,
        )

        account_id = self.portfolio_repo.ensure_real_account(portfolio)
        imported_rows = 0
        skipped_rows = 0
        rows: list[dict[str, Any]] = []
        for row in normalized_rows:
            if self.sync_repo.broker_trade_key_exists(row.broker_trade_key):
                skipped_rows += 1
                rows.append(row.to_preview_dict(duplicate=True) | {"status": "skipped_duplicate"})
                continue

            try:
                legacy_projection = self._apply_position_change(
                    account_id=account_id,
                    portfolio=portfolio,
                    row=row,
                )
                transaction = self.sync_repo.create_imported_transaction(
                    portfolio=portfolio,
                    position=legacy_projection,
                    action=row.action,
                    asset_code=row.asset_code,
                    shares=row.shares,
                    price=row.price,
                    commission=row.commission,
                    stamp_duty=row.stamp_duty,
                    transfer_fee=row.transfer_fee,
                    traded_at=row.traded_at,
                    notes=row.notes,
                    broker_name=broker_name,
                    external_trade_id=row.external_trade_id,
                    broker_trade_key=row.broker_trade_key,
                    raw_payload=row.raw_payload,
                    import_batch=batch,
                )
                match_payload = self._match_recommendation(
                    account_id=str(account_id),
                    transaction_id=transaction.id,
                    row=row,
                )
                imported_rows += 1
                rows.append(
                    row.to_preview_dict()
                    | {
                        "status": "imported",
                        "transaction_id": transaction.id,
                        "match": match_payload,
                    }
                )
            except Exception as exc:  # pragma: no cover - surfaced as row-level import error
                errors.append({"row_number": row.row_number, "error": str(exc)})

        batch = self.sync_repo.update_import_batch_result(
            batch,
            imported_rows=imported_rows,
            skipped_rows=skipped_rows,
            error_rows=len(errors),
            errors=errors,
        )
        return BrokerTradeImportResult(
            total_rows=len(raw_rows),
            valid_rows=len(normalized_rows),
            duplicate_rows=skipped_rows,
            error_rows=len(errors),
            rows=rows,
            errors=errors,
            imported_rows=imported_rows,
            skipped_rows=skipped_rows,
            batch_id=batch.id,
        )

    def _apply_position_change(self, *, account_id: int, portfolio, row: NormalizedTradeRow):
        if row.action == "buy":
            unified_model = self.position_service.create_position(
                account_id=account_id,
                asset_code=row.asset_code,
                shares=row.shares,
                price=row.price,
                current_price=row.price,
                asset_name=row.asset_code,
                asset_type="equity",
                source="manual",
                entry_reason=row.notes or "manual broker import",
                traded_at=row.traded_at,
            )
            return self.portfolio_repo.upsert_legacy_projection_from_unified(
                unified_position=unified_model,
                portfolio=portfolio,
                asset_class="equity",
                region="CN",
                cross_border="domestic",
                source="manual",
            )

        existing = self.portfolio_repo.get_unified_position_for_account_asset(
            account_id=account_id,
            asset_code=row.asset_code,
        )
        if existing is None:
            raise ValueError(f"Cannot sell {row.asset_code}: no open position")
        result = self.position_service.close_position(
            account_id=account_id,
            asset_code=row.asset_code,
            close_shares=row.shares,
            close_price=row.price,
            reason=row.notes or "manual broker import",
            traded_at=row.traded_at,
        )
        if result is None:
            return self.portfolio_repo.mark_legacy_projection_closed_for_unified(
                target_id=existing.id,
                closed_at=row.traded_at,
            )
        unified_model = self.portfolio_repo.get_unified_position_for_account_asset(
            account_id=account_id,
            asset_code=row.asset_code,
        )
        if unified_model is None:
            raise ValueError(f"Cannot refresh position for {row.asset_code}")
        return self.portfolio_repo.upsert_legacy_projection_from_unified(
            unified_position=unified_model,
            portfolio=portfolio,
            asset_class="equity",
            region="CN",
            cross_border="domestic",
            source="manual",
        )

    def _match_recommendation(
        self,
        *,
        account_id: str,
        transaction_id: int,
        row: NormalizedTradeRow,
    ) -> dict[str, Any]:
        side = ACTION_TO_SIDE[row.action]
        match = self.recommendation_repo.find_execution_match(
            account_id=account_id,
            security_code=row.asset_code,
            side=side,
            traded_at=row.traded_at,
        )
        if match is None:
            return self.recommendation_repo.record_execution_link(
                recommendation_id="",
                transaction_id=transaction_id,
                account_id=account_id,
                security_code=row.asset_code,
                actual_action=row.action,
                match_method="manual_only",
                match_confidence=0.0,
                notes="No matching system recommendation",
            )

        self.recommendation_repo.update_user_action(
            recommendation_id=match["recommendation_id"],
            user_action=UserDecisionAction.ADOPTED,
            note=f"Matched imported transaction {transaction_id}",
            account_id=account_id,
        )
        return self.recommendation_repo.record_execution_link(
            recommendation_id=match["recommendation_id"],
            transaction_id=transaction_id,
            account_id=account_id,
            security_code=row.asset_code,
            actual_action=row.action,
            match_method="auto",
            match_confidence=match["match_confidence"],
            notes="Matched by account/security/side/time window",
        )

    def _normalize_rows(
        self,
        raw_rows: list[dict[str, Any]],
        *,
        broker_name: str,
        portfolio_id: int,
    ) -> tuple[list[NormalizedTradeRow], list[dict[str, Any]]]:
        rows: list[NormalizedTradeRow] = []
        errors: list[dict[str, Any]] = []
        for index, raw in enumerate(raw_rows, start=2):
            lowered = {str(key).strip().lower(): value for key, value in raw.items()}
            missing = sorted(REQUIRED_COLUMNS - set(lowered))
            if missing:
                errors.append({"row_number": index, "error": f"Missing columns: {', '.join(missing)}"})
                continue
            try:
                action = str(lowered.get("action", "")).strip().lower()
                if action not in ACTION_TO_SIDE:
                    raise ValueError("action must be buy or sell")
                traded_at = self._parse_traded_at(lowered["traded_at"])
                asset_code = str(lowered.get("asset_code", "")).strip().upper()
                if not asset_code:
                    raise ValueError("asset_code is required")
                shares = float(lowered["shares"])
                if shares <= 0:
                    raise ValueError("shares must be positive")
                price = self._parse_decimal(lowered["price"], "price")
                if price <= 0:
                    raise ValueError("price must be positive")
                commission = self._parse_decimal(lowered.get("commission", 0), "commission")
                stamp_duty = self._parse_decimal(lowered.get("stamp_duty", 0), "stamp_duty")
                transfer_fee = self._parse_decimal(lowered.get("transfer_fee", 0), "transfer_fee")
                external_trade_id = str(lowered.get("external_trade_id", "") or "").strip()
                notes = str(lowered.get("notes", "") or "").strip()
                broker_trade_key = self._build_broker_trade_key(
                    broker_name=broker_name,
                    portfolio_id=portfolio_id,
                    external_trade_id=external_trade_id,
                    traded_at=traded_at,
                    action=action,
                    asset_code=asset_code,
                    shares=shares,
                    price=price,
                )
                rows.append(
                    NormalizedTradeRow(
                        row_number=index,
                        traded_at=traded_at,
                        action=action,
                        asset_code=asset_code,
                        shares=shares,
                        price=price,
                        commission=commission,
                        stamp_duty=stamp_duty,
                        transfer_fee=transfer_fee,
                        external_trade_id=external_trade_id,
                        notes=notes,
                        broker_trade_key=broker_trade_key,
                        raw_payload={str(k): v for k, v in raw.items()},
                    )
                )
            except (ValueError, InvalidOperation) as exc:
                errors.append({"row_number": index, "error": str(exc)})
        return rows, errors

    @staticmethod
    def _parse_traded_at(value: Any) -> datetime:
        if isinstance(value, datetime):
            dt = value
        else:
            raw = str(value or "").strip()
            if not raw:
                raise ValueError("traded_at is required")
            try:
                dt = datetime.fromisoformat(raw.replace("/", "-"))
            except ValueError as exc:
                raise ValueError("traded_at must be ISO datetime or date") from exc
        if timezone.is_naive(dt):
            return timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    @staticmethod
    def _parse_decimal(value: Any, field_name: str) -> Decimal:
        raw = str(value if value is not None else "0").strip()
        if raw == "":
            raw = "0"
        try:
            decimal_value = Decimal(raw)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} must be numeric") from exc
        if decimal_value < 0:
            raise ValueError(f"{field_name} must not be negative")
        return decimal_value

    @staticmethod
    def _build_broker_trade_key(
        *,
        broker_name: str,
        portfolio_id: int,
        external_trade_id: str,
        traded_at: datetime,
        action: str,
        asset_code: str,
        shares: float,
        price: Decimal,
    ) -> str:
        if external_trade_id:
            raw_key = f"{broker_name}|{portfolio_id}|{external_trade_id}"
        else:
            raw_key = (
                f"{broker_name}|{portfolio_id}|{traded_at.isoformat()}|"
                f"{action}|{asset_code}|{shares:.6f}|{price}"
            )
        return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class ManualTradeReviewSummaryUseCase:
    """Build a compact manual trade review payload for audit pages."""

    def __init__(self, *, sync_repo=None) -> None:
        self.sync_repo = sync_repo or get_manual_trade_sync_repository()

    def execute(self, *, user_id: int) -> dict[str, Any]:
        batches = self.sync_repo.list_recent_import_batches(user_id=user_id, limit=20)
        transactions = self.sync_repo.list_imported_transactions(user_id=user_id, limit=50)
        return {
            "batches": [
                {
                    "id": batch.id,
                    "portfolio_name": batch.portfolio.name,
                    "broker_name": batch.broker_name,
                    "source_filename": batch.source_filename,
                    "status": batch.status,
                    "total_rows": batch.total_rows,
                    "imported_rows": batch.imported_rows,
                    "skipped_rows": batch.skipped_rows,
                    "error_rows": batch.error_rows,
                    "created_at": batch.created_at,
                }
                for batch in batches
            ],
            "transactions": [
                {
                    "id": tx.id,
                    "portfolio_name": tx.portfolio.name,
                    "asset_code": tx.asset_code,
                    "action": tx.action,
                    "shares": tx.shares,
                    "price": tx.price,
                    "notional": tx.notional,
                    "traded_at": tx.traded_at,
                    "broker_name": tx.broker_name,
                    "external_trade_id": tx.external_trade_id,
                }
                for tx in transactions
            ],
        }
