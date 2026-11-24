"""Portfolio's authenticated live-inception, daily close and exact-current valuation workflows."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from django.db import connections
from django.utils import timezone
from rest_framework.request import Request

from apps.portfolio.application.benchmark_daily_sources import DayOwner, benchmark_day_sources
from apps.portfolio.benchmark_predecessor_composition import configuration_digest as _config_hash
from apps.portfolio.benchmark_predecessor_composition import daily_valuation_digest as _row_hash
from apps.portfolio.benchmark_predecessor_composition import (
    require_benchmark_predecessors,
    require_uncorrected_benchmark_day,
)
from apps.portfolio.benchmark_predecessor_composition import valuation_digest as _hash
from apps.portfolio.domain.benchmark_execution_approval import (
    BenchmarkArtifactRef,
    BenchmarkValuationFacts,
)
from apps.portfolio.domain.policy_benchmark_daily_valuation import (
    BenchmarkDayUnavailable,
    ShadowBalance,
    close_single_stock_day,
    read_day_ledger,
)
from apps.portfolio.infrastructure.benchmark_daily_configuration import (
    DailyConfiguration,
    read_daily_configuration,
)
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    PortfolioBenchmarkDailyValuationModel as Daily,
)
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    PortfolioBenchmarkValuationEpochModel as Epoch,
)
from apps.portfolio.infrastructure.policy_benchmark_daily_valuation_models import (
    _claim_valuation_insert,
)


def _before_expiry(deadlines: list[datetime]) -> None:
    if not deadlines or timezone.now() >= min(deadlines):
        raise BenchmarkDayUnavailable("valuation authority expired before commit")


def _owner(namespace: str, account: str, actor: int, using: str) -> DayOwner:
    owner = benchmark_day_sources().owner(
        namespace=namespace, account_id=account, user_id=actor, using=using
    )
    if owner is None or (
        owner.scope.account_namespace,
        owner.scope.account_id,
        owner.scope.owner_user_id,
    ) != (namespace, account, actor):
        raise BenchmarkDayUnavailable("current live account owner unavailable")
    return owner


def _scope_hash(owner: DayOwner) -> str:
    return _hash(asdict(owner.scope), owner.physical_id, owner.identity_hash, owner.policy_hash)


def _epoch_hash(epoch: Epoch) -> str:
    return _hash(
        epoch.pk,
        epoch.account_namespace,
        epoch.account_id,
        epoch.owner_user_id,
        epoch.sequence,
        epoch.scope_hash,
        epoch.definition_id,
        epoch.policy_id,
        epoch.configuration_hash,
        epoch.started_at.astimezone(UTC),
    )


def start_benchmark_epoch(
    *,
    request: Request,
    account_namespace: str,
    account_id: str,
    definition_id: str,
    policy_id: str,
    previous_epoch: UUID | None = None,
    using: str = "default",
) -> UUID:
    """Begin an owner-certified buy-and-hold epoch prospectively, using current Portfolio heads."""
    deadlines: list[datetime] = []
    with benchmark_day_sources().signer(
        request=request, using=using, before_commit=lambda: _before_expiry(deadlines)
    ) as actor:
        owner = _owner(account_namespace, account_id, actor, using)
        now = timezone.now()
        config = read_daily_configuration(
            definition_id=definition_id, policy_id=policy_id, at=now, using=using
        )
        deadlines.extend((owner.valid_until, config.valid_until))
        previous = (
            Epoch._default_manager.using(using)
            .select_for_update()
            .filter(account_namespace=account_namespace, account_id=account_id)
            .order_by("-sequence")
            .first()
        )
        if previous is not None and previous.content_hash != _epoch_hash(previous):
            raise BenchmarkDayUnavailable("prior valuation epoch integrity failure")
        if previous is not None and previous.pk != previous_epoch:
            same = previous.configuration_hash == _config_hash(
                config
            ) and previous.scope_hash == _scope_hash(owner)
            predecessor = (
                Epoch._default_manager.using(using)
                .filter(
                    account_namespace=account_namespace,
                    account_id=account_id,
                    sequence=previous.sequence - 1,
                )
                .values_list("id", flat=True)
                .first()
            )
            if same and predecessor == previous_epoch:
                return previous.id
            raise BenchmarkDayUnavailable("expected previous valuation epoch changed")
        if previous is None and previous_epoch is not None:
            raise BenchmarkDayUnavailable("unknown previous valuation epoch")
        epoch = Epoch(
            id=uuid4(),
            account_namespace=account_namespace,
            account_id=account_id,
            owner_user_id=actor,
            sequence=1 if previous is None else previous.sequence + 1,
            scope_hash=_scope_hash(owner),
            definition_id=definition_id,
            policy_id=policy_id,
            configuration_hash=_config_hash(config),
            started_at=now,
        )
        epoch.content_hash = _epoch_hash(epoch)
        with _claim_valuation_insert(epoch):
            epoch.save(force_insert=True, using=using)
        return epoch.id


def _current_epoch(
    epoch_id: UUID, actor: int | None, using: str
) -> tuple[Epoch, DayOwner, DailyConfiguration]:
    selector = (
        Epoch._default_manager.using(using)
        .filter(pk=epoch_id)
        .values_list("account_namespace", "account_id", "owner_user_id")
        .first()
    )
    if selector is None or (actor is not None and actor != selector[2]):
        raise BenchmarkDayUnavailable("valuation epoch unavailable")
    owner = _owner(selector[0], selector[1], selector[2], using)
    epoch = (
        Epoch._default_manager.using(using)
        .select_for_update()
        .filter(account_namespace=selector[0], account_id=selector[1])
        .order_by("-sequence")
        .first()
    )
    if (
        epoch is None
        or epoch.pk != epoch_id
        or epoch.content_hash != _epoch_hash(epoch)
        or epoch.scope_hash != _scope_hash(owner)
    ):
        raise BenchmarkDayUnavailable("valuation epoch or account authority superseded")
    config = read_daily_configuration(
        definition_id=epoch.definition_id, policy_id=epoch.policy_id, at=timezone.now(), using=using
    )
    if epoch.configuration_hash != _config_hash(config):
        raise BenchmarkDayUnavailable("valuation epoch configuration superseded")
    return epoch, owner, config


def _sessions(config: DailyConfiguration) -> list[datetime]:
    definition = config.definition
    zone = ZoneInfo(config.calendar.timezone)
    if (
        definition.valuation_timezone != config.calendar.timezone
        or config.price.timezone != config.calendar.timezone
    ):
        raise BenchmarkDayUnavailable("fixing and valuation timezones disagree")
    sessions = []
    for day in config.calendar.days:
        if day.is_valuation_day and day.valuation_cutoff_local is not None:
            instant = datetime.combine(day.calendar_date, day.valuation_cutoff_local, zone)
            if (
                instant.time().strftime("%H:%M") != definition.valuation_cutoff[:5]
                or day.valuation_cutoff_local != config.price.valuation_cutoff_local
            ):
                raise BenchmarkDayUnavailable("fixing and valuation cutoffs disagree")
            sessions.append(instant.astimezone(UTC))
    return sessions


def _balance_payload(value: ShadowBalance) -> dict[str, object]:
    return {
        "units": str(value.units),
        "cash": str(value.cash),
        "quantities": {k: str(v) for k, v in value.quantities.items()},
        "unit_nav": str(value.unit_nav),
        "total_value": str(value.total_value),
    }


def _restore(row: Daily) -> ShadowBalance:
    if (
        _row_hash(row) != row.content_hash
        or hashlib.sha256(bytes(row.original_statement)).hexdigest() != row.original_hash
    ):
        raise BenchmarkDayUnavailable("daily valuation integrity failure")
    payload = row.balance
    if not isinstance(payload, dict) or not isinstance(payload.get("quantities"), dict):
        raise BenchmarkDayUnavailable("invalid daily valuation balances")
    return ShadowBalance(
        Decimal(payload["units"]),
        Decimal(payload["cash"]),
        {k: Decimal(v) for k, v in payload["quantities"].items()},
        Decimal(payload["unit_nav"]),
        Decimal(payload["total_value"]),
    )


def _facts(
    epoch: Epoch, row: Daily, owner: DayOwner, config: DailyConfiguration
) -> BenchmarkValuationFacts:
    definition = config.definition
    return BenchmarkValuationFacts(
        epoch.id,
        row.version,
        row.content_hash,
        owner.scope,
        BenchmarkArtifactRef(
            definition.definition_id, definition.definition_version, definition.content_hash
        ),
        config.method_ref,
        config.policy_ref,
        config.planning_ref,
        row.observation_date,
        row.observed_at,
        row.recorded_at,
        row.valid_until,
    )


def _input_marks(
    config: DailyConfiguration, day: date, at: datetime, using: str
) -> tuple[dict[str, Decimal], str, dict[str, str]]:
    marks: dict[str, Decimal] = {}
    refs: dict[str, object] = {}
    historical: dict[str, str] = {}
    for constituent in config.definition.constituents:
        fixing = benchmark_day_sources().fixing(
            asset=constituent.price_identifier, day=day, at=at, using=using
        )
        if (
            fixing is None
            or fixing.asset_class != "stock"
            or (fixing.venue, config.price.venue) not in {("SSE", "XSHG"), ("SZSE", "XSHE")}
            or fixing.published_at > at
            or not 0
            <= (at - fixing.observed_at).total_seconds()
            <= min(config.definition.max_price_age_seconds, config.price.stale_after_seconds)
        ):
            raise BenchmarkDayUnavailable("fresh published constituent fixing unavailable")
        marks[constituent.benchmark_code] = fixing.price
        refs[constituent.benchmark_code] = asdict(fixing)
        historical[constituent.benchmark_code] = fixing.member_hash
    return marks, _hash(refs), historical


def publish_benchmark_day(
    *,
    request: Request,
    epoch_id: UUID,
    snapshot_id: int,
    original_statement: bytes,
    using: str = "default",
) -> BenchmarkValuationFacts:
    """Certify coverage of an original day statement and append its computed live shadow balance."""
    deadlines: list[datetime] = []
    ledger = read_day_ledger(original_statement)
    original_hash = hashlib.sha256(original_statement).hexdigest()
    with benchmark_day_sources().signer(
        request=request, using=using, before_commit=lambda: _before_expiry(deadlines)
    ) as actor:
        epoch, owner, config = _current_epoch(epoch_id, actor, using)
        now = timezone.now()
        head = Daily._default_manager.using(using).filter(epoch=epoch).order_by("-version").first()
        sessions = _sessions(config)
        if ledger.cutoff not in sessions or sessions.index(ledger.cutoff) + 1 >= len(sessions):
            raise BenchmarkDayUnavailable("no current and next approved valuation session")
        deadlines.extend(
            (owner.valid_until, config.valid_until, sessions[sessions.index(ledger.cutoff) + 1])
        )
        day = ledger.cutoff.astimezone(ZoneInfo(config.calendar.timezone)).date()
        next_cut = sessions[sessions.index(ledger.cutoff) + 1]
        source = benchmark_day_sources().reconciliation(
            snapshot_id=snapshot_id, owner=owner, using=using
        )
        if (
            source is None
            or source.account_ref_hash != ledger.source_account_hash
            or source.total_asset != ledger.closing_live_equity
            or not ledger.covered_from <= ledger.cutoff <= now < next_cut
            or not 0
            <= (ledger.cutoff - source.captured_at).total_seconds()
            <= source.max_snapshot_age_seconds
            or (
                source.cash_available,
                source.cash_frozen,
                source.position_market_value,
                source.positions,
                source.currency,
            )
            != (
                ledger.cash_available,
                ledger.cash_frozen,
                ledger.position_market_value,
                ledger.positions,
                ledger.currency,
            )
            or source.captured_at.astimezone(ZoneInfo(config.calendar.timezone)).date() != day
            or source.completed_at > now
            or ledger.currency != config.definition.base_currency
        ):
            raise BenchmarkDayUnavailable(
                "broker close, account, currency, date or source time mismatch"
            )
        if head is not None and head.observation_date == day:
            if (
                head.original_hash != original_hash
                or head.snapshot_id != snapshot_id
                or head.reconciliation_hash != source.content_hash
            ):
                raise BenchmarkDayUnavailable("day already closed with different evidence")
            current = get_current_benchmark_valuation(
                valuation_id=epoch.id, valuation_version=head.version, using=using
            )
            if current is None:
                raise BenchmarkDayUnavailable("daily valuation is no longer current")
            return current
        prior = None
        if head is None:
            if epoch.started_at > ledger.cutoff or any(
                epoch.started_at <= s < ledger.cutoff for s in sessions
            ):
                raise BenchmarkDayUnavailable("live inception is not the first prospective fixing")
        else:
            require_benchmark_predecessors(
                epoch=epoch,
                through_version=head.version,
                expected_hash=head.content_hash,
                owner=owner,
                using=using,
            )
            prior = _restore(head)
            if (
                ledger.covered_from != head.observed_at
                or sessions.index(ledger.cutoff) == 0
                or sessions[sessions.index(ledger.cutoff) - 1] != head.observed_at
                or read_day_ledger(bytes(head.original_statement)).closing_live_equity
                != ledger.opening_live_equity
            ):
                raise BenchmarkDayUnavailable(
                    "missing daily predecessor or unverified opening equity"
                )
        if (
            ledger.economic_event_ids
            and Daily._default_manager.using(using)
            .filter(epoch=epoch, balance__economic_events__has_any_keys=ledger.economic_event_ids)
            .exists()
        ):
            raise BenchmarkDayUnavailable(
                "an original economic event has already been booked in this epoch"
            )
        marks, fixing_hash, historical = _input_marks(config, day, now, using)
        for constituent in config.definition.constituents:
            if constituent.currency != ledger.currency:
                raise BenchmarkDayUnavailable(
                    "no independently published foreign-currency fixing for this source"
                )
            if (
                constituent.currency == ledger.currency
                and ledger.instrument_terms.get(constituent.benchmark_code, (0, 0, 0))[2] != 1
            ):
                raise BenchmarkDayUnavailable("base-currency fixing must be exactly one")
        underlying = config.definition.constituents[0]
        live_holding = ledger.positions.get(underlying.price_identifier)
        if (
            live_holding is not None
            and live_holding[0] * marks[underlying.benchmark_code] != live_holding[2]
        ):
            raise BenchmarkDayUnavailable(
                "custody and benchmark use different closing marks for the same stock"
            )
        code = config.definition.constituents[0].benchmark_code
        coverage_hash = None
        if prior is not None:
            from apps.portfolio.infrastructure.benchmark_action_coverage import (
                verify_no_action_coverage,
            )

            coverage_hash = verify_no_action_coverage(
                raw_packet=original_statement,
                source_ref=config.action_source,
                asset=config.definition.constituents[0].price_identifier,
                covered_from=ledger.covered_from,
                cutoff=ledger.cutoff,
                as_of=now,
            )
        fee = config.trade_charge
        if fee.rate is None:
            raise BenchmarkDayUnavailable("approved trade fee lacks an exact rate")
        balance = close_single_stock_day(
            ledger=ledger,
            mark=marks[code],
            code=code,
            prior=prior,
            rate=fee.rate,
            rounding_increment=fee.rounding_increment,
        )
        valid_until = min(next_cut, owner.valid_until, config.valid_until)
        if timezone.now() >= valid_until:
            raise BenchmarkDayUnavailable("daily valuation expired before publication")
        row = Daily(
            epoch=epoch,
            version=1 if head is None else head.version + 1,
            observation_date=day,
            observed_at=ledger.cutoff,
            recorded_at=now,
            valid_until=valid_until,
            snapshot_id=snapshot_id,
            reconciliation_hash=source.content_hash,
            original_statement=original_statement,
            original_hash=original_hash,
            fixing_hash=fixing_hash,
            predecessor_hash="" if head is None else head.content_hash,
            balance=_balance_payload(balance)
            | {
                "economic_events": dict.fromkeys(ledger.economic_event_ids, True),
                "historical_fixings": historical,
                "action_coverage_hash": coverage_hash,
                "signed_broker_receipt": source.signed_receipt,
            },
        )
        row.content_hash = _row_hash(row)
        with _claim_valuation_insert(row):
            row.save(force_insert=True, using=using)
        return _facts(epoch, row, owner, config)


def get_current_benchmark_valuation(
    *, valuation_id: UUID, valuation_version: int, using: str = "default"
) -> BenchmarkValuationFacts | None:
    """Verify the current day, exact scope, source, configuration and clock in the caller's transaction."""
    if not connections[using].in_atomic_block:
        raise RuntimeError("benchmark current read requires caller transaction")
    try:
        epoch, owner, config = _current_epoch(valuation_id, None, using)
        head = Daily._default_manager.using(using).filter(epoch=epoch).order_by("-version").first()
        if (
            head is None
            or head.version != valuation_version
            or not head.recorded_at <= timezone.now() < head.valid_until
        ):
            return None
        _restore(head)
        require_uncorrected_benchmark_day(head, using=using)
        require_benchmark_predecessors(
            epoch=epoch,
            through_version=head.version - 1,
            expected_hash=head.predecessor_hash,
            owner=owner,
            using=using,
        )
        if head.version > 1:
            from apps.portfolio.infrastructure.benchmark_action_coverage import (
                verify_no_action_coverage,
            )

            ledger = read_day_ledger(bytes(head.original_statement))
            if verify_no_action_coverage(
                raw_packet=bytes(head.original_statement),
                source_ref=config.action_source,
                asset=config.definition.constituents[0].price_identifier,
                covered_from=ledger.covered_from,
                cutoff=ledger.cutoff,
                as_of=timezone.now(),
            ) != head.balance.get("action_coverage_hash"):
                return None
        source = benchmark_day_sources().reconciliation(
            snapshot_id=head.snapshot_id, owner=owner, using=using
        )
        if (
            source is None
            or source.content_hash != head.reconciliation_hash
            or not 0
            <= (head.observed_at - source.captured_at).total_seconds()
            <= source.max_snapshot_age_seconds
        ):
            return None
        _, fixing, historical = _input_marks(config, head.observation_date, timezone.now(), using)
        if (
            historical != head.balance.get("historical_fixings")
            or fixing != head.fixing_hash
            or timezone.now() >= min(head.valid_until, owner.valid_until, config.valid_until)
        ):
            return None
        return _facts(epoch, head, owner, config)
    except BenchmarkDayUnavailable:
        return None
