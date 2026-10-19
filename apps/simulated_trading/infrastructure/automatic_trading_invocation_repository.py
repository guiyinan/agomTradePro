"""Default-database repository for durable automatic invocation claims."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import cast
from uuid import UUID, uuid4

from django.db import DEFAULT_DB_ALIAS, IntegrityError, transaction
from django.utils import timezone

from apps.simulated_trading.application.automatic_invocation import (
    AutoTradingInvocationClaim,
    AutoTradingInvocationConflict,
    AutoTradingInvocationRequest,
    AutoTradingInvocationUnavailable,
    FrozenAutoTradingScope,
)
from apps.simulated_trading.domain.auto_trading_outcomes import (
    AutoTradingBatchOutcome,
    AutoTradingOutcomeContractError,
)
from apps.simulated_trading.infrastructure.models import AutomaticTradingInvocationModel
from core.exceptions import InvalidInputError


class DjangoAutoTradingInvocationRepository:
    """Persist caller identity, frozen scope, and exactly one final batch outcome."""

    def __init__(self) -> None:
        """Bind this first implementation to Django's configured default database."""

        self._using = DEFAULT_DB_ALIAS

    def find_scope(self, request: AutoTradingInvocationRequest) -> FrozenAutoTradingScope | None:
        """Return the original scope for an exact key/request pair, if already stored."""

        self._validate_request(request)
        row = (
            AutomaticTradingInvocationModel._base_manager.using(self._using)
            .filter(namespace=request.namespace, invocation_key=request.invocation_key)
            .first()
        )
        if row is None:
            return None
        self._assert_request_binding(row, request)
        return self._scope_from_row(row)

    def claim(
        self, request: AutoTradingInvocationRequest, scope: FrozenAutoTradingScope
    ) -> AutoTradingInvocationClaim:
        """Acquire a new/released preparation or read the immutable prior run state."""

        self._validate_request(request)
        self._validate_scope(scope)
        if (
            request.trade_date is not None
            and request.trade_date != scope.trade_date
            or request.requested_account_ids is not None
            and request.requested_account_ids != scope.account_ids
        ):
            raise AutoTradingInvocationUnavailable(
                "resolved invocation scope disagrees with explicit request input"
            )
        manager = AutomaticTradingInvocationModel._base_manager.using(self._using)
        defaults = {
            "request_hash": request.content_hash,
            "request_payload": request.to_payload(),
            "trade_date": scope.trade_date,
            "account_ids": list(scope.account_ids),
            "state": AutomaticTradingInvocationModel.STATE_READY,
        }
        try:
            with transaction.atomic(using=self._using):
                manager.get_or_create(
                    namespace=request.namespace,
                    invocation_key=request.invocation_key,
                    defaults=defaults,
                )
                row = (
                    manager.select_for_update()
                    .filter(namespace=request.namespace, invocation_key=request.invocation_key)
                    .first()
                )
                if row is None:
                    raise AutoTradingInvocationUnavailable(
                        "automatic invocation disappeared while being claimed"
                    )
                return self._claim_locked(row, request)
        except IntegrityError as error:
            # get_or_create handles unique races; remaining failures are unavailable.
            raise AutoTradingInvocationUnavailable(
                "automatic invocation claim could not be committed"
            ) from error

    def release_preparation(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Release only the exact token while execution has not started."""

        with transaction.atomic(using=self._using):
            row = self._locked_by_id(invocation_id)
            if not self._matches_claim(
                row, claim_token, AutomaticTradingInvocationModel.STATE_PREPARING
            ):
                raise AutoTradingInvocationUnavailable(
                    "automatic invocation preparation claim is no longer current"
                )
            row.state = AutomaticTradingInvocationModel.STATE_READY
            row.claim_token = None
            row.updated_at = self._aware_now()
            row.save(using=self._using, update_fields=("state", "claim_token", "updated_at"))

    def mark_started(self, *, invocation_id: UUID, claim_token: UUID) -> None:
        """Persist the terminal no-reentry boundary using the active preparation token."""

        with transaction.atomic(using=self._using):
            row = self._locked_by_id(invocation_id)
            if not self._matches_claim(
                row, claim_token, AutomaticTradingInvocationModel.STATE_PREPARING
            ):
                raise AutoTradingInvocationUnavailable(
                    "automatic invocation cannot cross the start boundary"
                )
            now = self._aware_now()
            row.state = AutomaticTradingInvocationModel.STATE_STARTED
            row.started_at = now
            row.updated_at = now
            row.save(using=self._using, update_fields=("state", "started_at", "updated_at"))

    def finish(
        self, *, invocation_id: UUID, claim_token: UUID, outcome: AutoTradingBatchOutcome
    ) -> None:
        """Store one strict result only for the started run and its exact account scope."""

        if type(outcome) is not AutoTradingBatchOutcome:
            raise AutoTradingInvocationUnavailable("automatic invocation result is not typed")
        with transaction.atomic(using=self._using):
            row = self._locked_by_id(invocation_id)
            if not self._matches_claim(
                row, claim_token, AutomaticTradingInvocationModel.STATE_STARTED
            ):
                raise AutoTradingInvocationUnavailable(
                    "automatic invocation result claim is no longer current"
                )
            scope = self._scope_from_row(row)
            if outcome.requested_account_ids != scope.account_ids:
                raise AutoTradingInvocationUnavailable(
                    "automatic invocation result does not match the frozen account scope"
                )
            now = self._aware_now()
            row.state = AutomaticTradingInvocationModel.STATE_FINISHED
            row.outcome_payload = outcome.to_payload()
            row.finished_at = now
            row.updated_at = now
            row.save(
                using=self._using,
                update_fields=("state", "outcome_payload", "finished_at", "updated_at"),
            )

    def get_preparing_scope(self, *, invocation_id: UUID) -> FrozenAutoTradingScope:
        """Read frozen construction metadata without granting another run claim."""
        if type(invocation_id) is not UUID:
            raise AutoTradingInvocationUnavailable("automatic invocation ID is invalid")
        row = (
            AutomaticTradingInvocationModel._base_manager.using(self._using)
            .filter(invocation_id=invocation_id)
            .first()
        )
        if row is None or row.state != AutomaticTradingInvocationModel.STATE_PREPARING:
            raise AutoTradingInvocationUnavailable("automatic invocation is not preparing")
        self._decode_request_payload(row.request_payload, row.request_hash)
        return self._scope_from_row(row)

    def _claim_locked(
        self, row: AutomaticTradingInvocationModel, request: AutoTradingInvocationRequest
    ) -> AutoTradingInvocationClaim:
        """Resolve and transition one locked row without changing its first scope."""

        self._assert_request_binding(row, request)
        invocation_id = self._uuid_field(row.invocation_id, "invocation_id")
        state = row.state
        if state == AutomaticTradingInvocationModel.STATE_READY:
            token = uuid4()
            now = self._aware_now()
            row.state = AutomaticTradingInvocationModel.STATE_PREPARING
            row.claim_token = token
            row.updated_at = now
            row.save(using=self._using, update_fields=("state", "claim_token", "updated_at"))
            return AutoTradingInvocationClaim(
                invocation_id=invocation_id,
                claim_token=token,
                scope=self._scope_from_row(row),
                acquired=True,
                outcome=None,
            )

        scope = self._scope_from_row(row)
        token = self._uuid_field(row.claim_token, "claim_token")
        if state in {
            AutomaticTradingInvocationModel.STATE_PREPARING,
            AutomaticTradingInvocationModel.STATE_STARTED,
        }:
            if row.outcome_payload is not None:
                raise AutoTradingInvocationUnavailable(
                    "unfinished automatic invocation unexpectedly contains a result"
                )
            return AutoTradingInvocationClaim(invocation_id, token, scope, False, None)
        if state == AutomaticTradingInvocationModel.STATE_FINISHED:
            if row.outcome_payload is None:
                raise AutoTradingInvocationUnavailable(
                    "finished automatic invocation has no stored result"
                )
            try:
                outcome = AutoTradingBatchOutcome.from_payload(row.outcome_payload)
            except AutoTradingOutcomeContractError as error:
                raise AutoTradingInvocationUnavailable(
                    "stored automatic invocation result failed strict validation"
                ) from error
            if outcome.requested_account_ids != scope.account_ids:
                raise AutoTradingInvocationUnavailable(
                    "stored automatic invocation result disagrees with its frozen scope"
                )
            return AutoTradingInvocationClaim(invocation_id, token, scope, False, outcome)
        raise AutoTradingInvocationUnavailable("automatic invocation has an unknown state")

    def _locked_by_id(self, invocation_id: UUID) -> AutomaticTradingInvocationModel:
        """Lock and return one run by its stable public UUID."""

        if type(invocation_id) is not UUID:
            raise AutoTradingInvocationUnavailable("automatic invocation ID is invalid")
        row = (
            AutomaticTradingInvocationModel._base_manager.using(self._using)
            .select_for_update()
            .filter(invocation_id=invocation_id)
            .first()
        )
        if row is None:
            raise AutoTradingInvocationUnavailable("automatic invocation record is unavailable")
        return row

    @staticmethod
    def _matches_claim(
        row: AutomaticTradingInvocationModel, claim_token: UUID, expected_state: str
    ) -> bool:
        """Compare the persisted state and opaque token without changing the row."""

        return (
            type(claim_token) is UUID
            and row.state == expected_state
            and row.claim_token == claim_token
        )

    @staticmethod
    def _validate_request(request: AutoTradingInvocationRequest) -> None:
        """Require a valid exact application request before touching persistence."""

        if type(request) is not AutoTradingInvocationRequest:
            raise AutoTradingInvocationUnavailable("automatic invocation request is invalid")
        request.__post_init__()

    @staticmethod
    def _validate_scope(scope: FrozenAutoTradingScope) -> None:
        """Require a valid exact first-resolved scope before creating a run row."""

        if type(scope) is not FrozenAutoTradingScope:
            raise AutoTradingInvocationUnavailable("automatic invocation scope is invalid")
        scope.__post_init__()

    @staticmethod
    def _assert_request_binding(
        row: AutomaticTradingInvocationModel, request: AutoTradingInvocationRequest
    ) -> None:
        """Separate corrupted stored request data from a valid caller-key conflict."""

        stored_payload = DjangoAutoTradingInvocationRepository._decode_request_payload(
            row.request_payload, row.request_hash
        )
        DjangoAutoTradingInvocationRepository._scope_from_row(row)
        if (
            row.namespace != request.namespace
            or row.invocation_key != request.invocation_key
            or row.request_hash != request.content_hash
            or stored_payload != request.to_payload()
        ):
            raise AutoTradingInvocationConflict()

    @staticmethod
    def _decode_request_payload(payload: object, request_hash: object) -> dict[str, object]:
        """Validate the immutable original JSON body and its canonical digest."""

        if type(payload) is not dict or type(request_hash) is not str:
            raise AutoTradingInvocationUnavailable("stored invocation request is malformed")
        body = cast(dict[str, object], payload)
        if set(body) != {"schema", "trade_date", "account_ids"}:
            raise AutoTradingInvocationUnavailable("stored invocation request shape is invalid")
        schema = body.get("schema")
        date_text = body.get("trade_date")
        account_ids = body.get("account_ids")
        if schema != "simulated_auto_invocation_request.v1":
            raise AutoTradingInvocationUnavailable("stored invocation request version is invalid")
        if date_text is not None:
            if type(date_text) is not str:
                raise AutoTradingInvocationUnavailable("stored invocation trade date is invalid")
            try:
                parsed_date = date.fromisoformat(date_text)
            except ValueError as error:
                raise AutoTradingInvocationUnavailable(
                    "stored invocation trade date is invalid"
                ) from error
            if parsed_date.isoformat() != date_text:
                raise AutoTradingInvocationUnavailable(
                    "stored invocation trade date is not canonical"
                )
        if account_ids is not None:
            if type(account_ids) is not list or any(
                type(account_id) is not int or account_id <= 0 for account_id in account_ids
            ):
                raise AutoTradingInvocationUnavailable("stored invocation account scope is invalid")
            if len(set(account_ids)) != len(account_ids):
                raise AutoTradingInvocationUnavailable("stored invocation accounts are duplicated")
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if request_hash != digest:
            raise AutoTradingInvocationUnavailable("stored invocation request hash is invalid")
        return body

    @staticmethod
    def _scope_from_row(row: AutomaticTradingInvocationModel) -> FrozenAutoTradingScope:
        """Decode the first resolved date and ordered account IDs from JSON/ORM fields."""

        trade_date = row.trade_date
        raw_account_ids = row.account_ids
        if type(trade_date) is not date or type(raw_account_ids) is not list:
            raise AutoTradingInvocationUnavailable("stored invocation scope is malformed")
        if any(type(account_id) is not int for account_id in raw_account_ids):
            raise AutoTradingInvocationUnavailable("stored invocation account IDs are malformed")
        try:
            account_ids = tuple(cast(int, account_id) for account_id in raw_account_ids)
            scope = FrozenAutoTradingScope(trade_date=trade_date, account_ids=account_ids)
        except (InvalidInputError, TypeError) as error:
            raise AutoTradingInvocationUnavailable(
                "stored invocation scope failed strict validation"
            ) from error
        body = DjangoAutoTradingInvocationRepository._decode_request_payload(
            row.request_payload, row.request_hash
        )
        if (
            body["trade_date"] is not None
            and body["trade_date"] != scope.trade_date.isoformat()
            or body["account_ids"] is not None
            and body["account_ids"] != list(scope.account_ids)
        ):
            raise AutoTradingInvocationUnavailable(
                "stored frozen scope disagrees with explicit request input"
            )
        return scope

    @staticmethod
    def _uuid_field(value: object, field_name: str) -> UUID:
        """Require Django to return a real UUID value for persisted identifiers."""

        if type(value) is not UUID:
            raise AutoTradingInvocationUnavailable(f"stored invocation {field_name} is malformed")
        return value

    @staticmethod
    def _aware_now() -> datetime:
        """Return one timezone-aware Django timestamp for state transitions."""

        now = timezone.now()
        if not timezone.is_aware(now):
            raise AutoTradingInvocationUnavailable(
                "automatic invocation clock is not timezone-aware"
            )
        return now
