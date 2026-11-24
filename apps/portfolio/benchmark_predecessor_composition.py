"""Trace a cumulative benchmark to authenticated original statements and exact market members."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from django.db import connections
from django.utils import timezone
from rest_framework.request import Request

from apps.portfolio.application.benchmark_daily_sources import DayOwner, benchmark_day_sources
from apps.portfolio.domain.policy_benchmark_daily_valuation import (
    BenchmarkDayUnavailable,
    read_day_ledger,
)
from apps.portfolio.infrastructure.benchmark_action_coverage import verify_no_action_coverage
from apps.portfolio.infrastructure.benchmark_daily_configuration import (
    DailyConfiguration,
    read_daily_configuration,
)
from apps.portfolio.infrastructure.benchmark_statement_revocation_models import (
    BenchmarkStatementRevocationModel,
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


def valuation_digest(*fields: object) -> str:
    """Seal the owner ledger's canonical JSON representation."""
    return hashlib.sha256(
        json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def configuration_digest(config: DailyConfiguration) -> str:
    """Identify the exact definition, five-source activation and planning approval."""
    return valuation_digest(
        config.definition.content_hash,
        asdict(config.method_ref),
        asdict(config.policy_ref),
        asdict(config.planning_ref),
    )


def daily_valuation_digest(row: Daily) -> str:
    """Recompute the original issue seal over the complete daily valuation."""
    return valuation_digest(
        row.epoch_id,
        row.version,
        row.observation_date,
        row.observed_at.astimezone(UTC),
        row.recorded_at.astimezone(UTC),
        row.valid_until.astimezone(UTC),
        row.snapshot_id,
        row.reconciliation_hash,
        row.original_hash,
        row.fixing_hash,
        row.predecessor_hash,
        row.balance,
    )


def require_uncorrected_benchmark_day(row: Daily, *, using: str) -> None:
    """Reject a permanently withdrawn original under the caller's epoch lock."""
    if not connections[using].in_atomic_block:
        raise RuntimeError("benchmark correction read requires caller transaction")
    if BenchmarkStatementRevocationModel._default_manager.using(using).filter(day=row).exists():
        raise BenchmarkDayUnavailable("benchmark_statement_revoked")


def revoke_benchmark_statement(
    *, request: Request, epoch_id: UUID, day: date, original_hash: str, using: str = "default"
) -> None:
    """Withdraw one exact certified original and every cumulative valuation that depends on it."""
    sources = benchmark_day_sources()
    expiry: datetime | None = None

    def check_owner() -> None:
        if expiry is None or timezone.now() >= expiry:
            raise BenchmarkDayUnavailable("benchmark_statement_owner_expired")

    with sources.signer(request=request, using=using, before_commit=check_owner) as actor:
        scope = (
            Epoch._default_manager.using(using)
            .filter(pk=epoch_id, owner_user_id=actor)
            .values_list("account_namespace", "account_id")
            .first()
        )
        if scope is None:
            raise BenchmarkDayUnavailable("benchmark_statement_owner_unavailable")
        owner = sources.owner(namespace=scope[0], account_id=scope[1], user_id=actor, using=using)
        if owner is None or (
            owner.scope.account_namespace,
            owner.scope.account_id,
            owner.scope.owner_user_id,
        ) != (*scope, actor):
            raise BenchmarkDayUnavailable("benchmark_statement_owner_unavailable")
        expiry = owner.valid_until
        epoch = Epoch._default_manager.using(using).select_for_update().get(pk=epoch_id)
        if epoch.scope_hash != valuation_digest(
            asdict(owner.scope), owner.physical_id, owner.identity_hash, owner.policy_hash
        ):
            raise BenchmarkDayUnavailable("benchmark_statement_owner_changed")
        row = Daily._default_manager.using(using).filter(epoch=epoch, observation_date=day).first()
        if (
            row is None
            or row.original_hash != original_hash
            or row.content_hash != daily_valuation_digest(row)
            or hashlib.sha256(bytes(row.original_statement)).hexdigest() != original_hash
        ):
            raise BenchmarkDayUnavailable("benchmark_statement_original_mismatch")
        if (
            not BenchmarkStatementRevocationModel._default_manager.using(using)
            .filter(day=row)
            .exists()
        ):
            revoked = BenchmarkStatementRevocationModel(
                day=row,
                original_hash=row.original_hash,
                owner_user_id=actor,
                recorded_at=timezone.now(),
            )
            with _claim_valuation_insert(revoked):
                revoked.save(force_insert=True, using=using)


def require_benchmark_predecessors(
    *, epoch: Epoch, through_version: int, expected_hash: str, owner: DayOwner, using: str
) -> None:
    """Revalidate each predecessor in genesis order in the current owner's epoch transaction."""
    if not connections[using].in_atomic_block:
        raise RuntimeError("benchmark history read requires caller transaction")
    if type(through_version) is not int or through_version < 0:
        raise BenchmarkDayUnavailable("benchmark_history_chain_invalid")
    if through_version == 0:
        if expected_hash:
            raise BenchmarkDayUnavailable("benchmark_history_chain_invalid")
        return
    sources = benchmark_day_sources()
    previous_hash = ""
    prior_cutoff: datetime | None = None
    clock = timezone.now()
    rows = (
        Daily._default_manager.using(using)
        .filter(epoch=epoch, version__lte=through_version)
        .order_by("version")
    )
    count = 0
    for count, row in enumerate(rows.iterator(chunk_size=8), 1):
        if (row.version, row.predecessor_hash, row.content_hash) != (
            count,
            previous_hash,
            daily_valuation_digest(row),
        ):
            raise BenchmarkDayUnavailable("benchmark_history_chain_invalid")
        if hashlib.sha256(bytes(row.original_statement)).hexdigest() != row.original_hash:
            raise BenchmarkDayUnavailable("benchmark_history_original_changed")
        require_uncorrected_benchmark_day(row, using=using)
        ledger = read_day_ledger(bytes(row.original_statement))
        config = read_daily_configuration(
            definition_id=epoch.definition_id,
            policy_id=epoch.policy_id,
            at=row.recorded_at,
            using=using,
        )
        if configuration_digest(config) != epoch.configuration_hash:
            raise BenchmarkDayUnavailable("benchmark_history_configuration_changed")
        if (
            ledger.cutoff != row.observed_at
            or (prior_cutoff is not None and ledger.covered_from != prior_cutoff)
            or row.observation_date
            != row.observed_at.astimezone(ZoneInfo(config.calendar.timezone)).date()
            or not epoch.started_at <= row.observed_at <= row.recorded_at < row.valid_until
            or row.recorded_at > clock
        ):
            raise BenchmarkDayUnavailable("benchmark_history_chain_invalid")
        if count > 1 and (
            not isinstance(row.balance, dict)
            or verify_no_action_coverage(
                raw_packet=bytes(row.original_statement),
                source_ref=config.action_source,
                asset=config.definition.constituents[0].price_identifier,
                covered_from=ledger.covered_from,
                cutoff=ledger.cutoff,
                as_of=row.recorded_at,
            )
            != row.balance.get("action_coverage_hash")
        ):
            raise BenchmarkDayUnavailable("benchmark_history_action_coverage_changed")
        source = sources.reconciliation(snapshot_id=row.snapshot_id, owner=owner, using=using)
        if (
            source is None
            or source.content_hash != row.reconciliation_hash
            or source.account_ref_hash != ledger.source_account_hash
            or source.completed_at > row.recorded_at
        ):
            raise BenchmarkDayUnavailable("benchmark_history_broker_receipt_changed")
        members = row.balance.get("historical_fixings") if isinstance(row.balance, dict) else None
        constituents = config.definition.constituents
        if not isinstance(members, dict) or members.keys() != {
            c.benchmark_code for c in constituents
        }:
            raise BenchmarkDayUnavailable("benchmark_history_price_members_unavailable")
        for constituent in constituents:
            digest = members[constituent.benchmark_code]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or digest
                != sources.historical_member(
                    asset=constituent.price_identifier,
                    day=row.observation_date,
                    issued_at=row.recorded_at,
                    at=clock,
                    using=using,
                )
            ):
                raise BenchmarkDayUnavailable("benchmark_history_price_member_changed")
        previous_hash, prior_cutoff = row.content_hash, row.observed_at
    if count != through_version or previous_hash != expected_hash:
        raise BenchmarkDayUnavailable("benchmark_history_chain_invalid")
