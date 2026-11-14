"""Focused contract tests for the double-read raw NAV mark composition."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from apps.data_center.application.published_price_source import (
    PublishedPriceSourceEvidence,
    PublishedPriceSourceResult,
)
from apps.simulated_trading.application.corporate_action_nav_mark import (
    SimulatedCorporateActionNavRawMarkPolicyBinding,
    SimulatedCorporateActionNavRawMarkQuery,
)
from apps.simulated_trading.domain.corporate_action_nav_mark_policy import (
    SimulatedCorporateActionNavRawMarkPolicy,
)
from apps.simulated_trading.infrastructure.corporate_action_nav_mark_reader import (
    PublishedPriceCorporateActionNavRawMarkReader,
)
from tests.unit.simulated_trading.test_published_price_initial_position_mark_reader import (
    _AS_OF,
    _ASSET_CODE,
    _ASSET_TYPE,
    _POLICY_KEY,
    _calendar,
    _classification,
    _source_evidence,
)

_TRADE_DATE = _AS_OF.astimezone(UTC).date() - timedelta(days=1)


def _query(**changes: object) -> SimulatedCorporateActionNavRawMarkQuery:
    """Return a complete owner and security scope for the reader tests."""

    values: dict[str, object] = {
        "physical_account_id": 17,
        "canonical_account_id": "simulated:17",
        "owner_user_id": 23,
        "security_id": "risk-security-fixture-001",
        "asset_code": _ASSET_CODE,
        "asset_type": _ASSET_TYPE,
    }
    values.update(changes)
    return SimulatedCorporateActionNavRawMarkQuery(**values)  # type: ignore[arg-type]


def _policy() -> SimulatedCorporateActionNavRawMarkPolicy:
    """Build an explicit current raw mark policy with a finite 24-hour age."""

    return SimulatedCorporateActionNavRawMarkPolicy(
        schema_version="simulated-corporate-action-nav-raw-mark-policy.v1",
        purpose="simulated_corporate_action_nav_raw_mark",
        policy_id="nav-raw-mark-policy",
        version="v1",
        source="tushare",
        publication_key=_POLICY_KEY,
        frequency="1d",
        adjustment="none",
        observation_basis="daily_interval_end",
        currency="CNY",
        supported_asset_types=(_ASSET_TYPE,),
        freshness_window_seconds=86400,
    )


def _binding(as_of: datetime) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
    """Bind the local policy to the same selected profile as the source fixture."""

    return SimulatedCorporateActionNavRawMarkPolicyBinding(
        policy=_policy(),
        runtime_environment="development",
        profile_id="initial-mark-profile-7",
        profile_key="simulated-initial-mark",
        profile_version=7,
        profile_content_sha256="a" * 64,
        profile_activated_at=_AS_OF - timedelta(hours=5),
        snapshot_id="initial-mark-snapshot-7",
        snapshot_content_sha256="b" * 64,
        snapshot_generated_at=_AS_OF - timedelta(hours=4),
        snapshot_effective_from=_AS_OF - timedelta(hours=5),
        known_at=_AS_OF - timedelta(hours=3),
        valid_from=_AS_OF - timedelta(hours=5),
        valid_until=_AS_OF + timedelta(days=1),
        checked_at=as_of,
    )


class _Clock:
    """Return a known monotonic clock sequence for source-boundary tests."""

    def __init__(self, values: tuple[datetime, ...]) -> None:
        self.values = values
        self.calls = 0

    def now(self) -> datetime:
        """Return the next preconfigured clock value."""

        index = min(self.calls, len(self.values) - 1)
        self.calls += 1
        return self.values[index]


class _PolicyReader:
    """Return one current configured policy binding for each exact cutoff."""

    def __init__(
        self,
        transform: (
            Callable[[datetime], SimulatedCorporateActionNavRawMarkPolicyBinding] | None
        ) = None,
    ) -> None:
        self.transform = transform or _binding
        self.calls: list[datetime] = []

    def read_policy(
        self, *, query: SimulatedCorporateActionNavRawMarkQuery, as_of: datetime
    ) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
        """Record cutoff and return the exact current policy selection."""

        self.calls.append(as_of)
        return self.transform(as_of)


class _ClassificationReader:
    """Return retained source classification and record exact current reads."""

    def __init__(
        self, evidence: object | None = None, *, sequence: tuple[object | None, ...] = ()
    ) -> None:
        self.evidence = evidence or _classification(_AS_OF)
        self.sequence = sequence
        self.calls: list[datetime] = []

    def resolve_simulated_instrument_classification(
        self, *, security_id: str, asset_code: str, as_of: datetime
    ) -> object | None:
        """Record the cutoff and return only the configured classification."""

        self.calls.append(as_of)
        index = min(len(self.calls) - 1, len(self.sequence) - 1)
        return self.sequence[index] if self.sequence else self.evidence


class _CalendarReader:
    """Return the same published full calendar unless a test changes it."""

    def __init__(
        self, evidence: object | None = None, *, sequence: tuple[object, ...] = ()
    ) -> None:
        self.evidence = evidence or _calendar(_AS_OF)
        self.sequence = sequence
        self.calls: list[datetime] = []

    def get_effective_execution_calendar(
        self, *, exchange: str, as_of: datetime, coverage_start: object = None
    ) -> object | None:
        """Record the exact current exchange-calendar query."""

        self.calls.append(as_of)
        index = min(len(self.calls) - 1, len(self.sequence) - 1)
        return self.sequence[index] if self.sequence else self.evidence


class _PriceReader:
    """Return the same source receipt at each requested knowledge cutoff."""

    def __init__(self, transform: Callable[[datetime], object] | None = None) -> None:
        evidence = _source_evidence(_AS_OF, trade_date=_TRADE_DATE)
        self.base = evidence
        self.transform = transform or (lambda cutoff: replace(evidence, knowledge_cutoff=cutoff))
        self.calls: list[tuple[str, datetime, str]] = []

    def __call__(
        self,
        asset_code: str,
        *,
        trade_date: object,
        knowledge_cutoff: datetime,
        publication_key: str,
    ) -> PublishedPriceSourceResult:
        """Record each request and return exactly the configured retained row."""

        self.calls.append((asset_code, knowledge_cutoff, publication_key))
        return PublishedPriceSourceResult(self.transform(knowledge_cutoff), "", "fresh")


def _reader(
    *,
    clock_values: tuple[datetime, ...] | None = None,
    policy_reader: _PolicyReader | None = None,
    classification_reader: _ClassificationReader | None = None,
    calendar_reader: _CalendarReader | None = None,
    price_reader: _PriceReader | None = None,
) -> tuple[PublishedPriceCorporateActionNavRawMarkReader, tuple[object, ...]]:
    """Compose the reader with deterministic no-write fake ports."""

    clock = _Clock(
        clock_values or (_AS_OF, _AS_OF + timedelta(seconds=1), _AS_OF + timedelta(seconds=2))
    )
    policies = policy_reader or _PolicyReader()
    classifications = classification_reader or _ClassificationReader()
    calendars = calendar_reader or _CalendarReader()
    prices = price_reader or _PriceReader()
    reader = PublishedPriceCorporateActionNavRawMarkReader(
        policy_reader=policies,
        classification_reader=classifications,
        calendar_reader=calendars,
        get_price_source=prices,
        clock=clock,
    )
    return reader, (clock, policies, classifications, calendars, prices)


def test_reader_returns_exact_raw_close_and_preserves_unknown_source_observation() -> None:
    reader, dependencies = _reader()

    proof = reader.read_current_mark(_query())

    assert proof is not None
    assert proof.price == _PriceReader().base.values.close
    assert proof.source_observed_at is None
    assert proof.source_evidence.source_observed_at is None
    assert proof.must_not_use_for_decision is True
    assert proof.scope_reason == "raw_price_only"
    assert dependencies[0].calls == 5
    assert len(dependencies[1].calls) == 2
    assert len(dependencies[2].calls) == 2
    assert len(dependencies[3].calls) == 2
    assert len(dependencies[4].calls) == 2
    assert proof.verify_for(_query(), as_of=proof.checked_at) is None
    with pytest.raises(ValueError):
        proof.verify_for(_query(), as_of=proof.checked_at - timedelta(microseconds=1))


def test_reader_rejects_clock_reversal_and_trade_date_boundary_crossing() -> None:
    reversed_reader, _ = _reader(
        clock_values=(_AS_OF, _AS_OF + timedelta(seconds=1), _AS_OF - timedelta(seconds=1))
    )
    boundary = datetime(2026, 10, 28, 6, 59, 59, tzinfo=UTC)
    boundary_reader, _ = _reader(
        clock_values=(boundary, boundary, datetime(2026, 10, 28, 7, 0, 1, tzinfo=UTC))
    )

    assert reversed_reader.read_current_mark(_query()) is None
    assert boundary_reader.read_current_mark(_query()) is None


def test_reader_rejects_asset_type_not_equal_to_current_classification() -> None:
    reader, dependencies = _reader()

    assert reader.read_current_mark(_query(asset_type="another_type")) is None
    assert dependencies[3].calls == []
    assert dependencies[4].calls == []


def test_reader_requires_calendar_coverage_for_the_current_local_date() -> None:
    calendar = _calendar(_AS_OF, end_before_today=True)
    reader, dependencies = _reader(calendar_reader=_CalendarReader(calendar))

    assert reader.read_current_mark(_query()) is None
    assert dependencies[4].calls == []


def test_reader_rejects_policy_or_price_publication_change_during_final_reads() -> None:
    def changed_policy(as_of: datetime) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
        """Return a different selected policy only after the initial read."""

        if as_of > _AS_OF:
            return replace(_binding(as_of), policy=replace(_policy(), version="v2"))
        return _binding(as_of)

    changed_policy_reader, _ = _reader(policy_reader=_PolicyReader(changed_policy))

    assert changed_policy_reader.read_current_mark(_query()) is None


def test_reader_rejects_expiry_that_occurs_during_final_source_io() -> None:
    short_policy = replace(_policy(), freshness_window_seconds=86343)

    def expiring_binding(as_of: datetime) -> SimulatedCorporateActionNavRawMarkPolicyBinding:
        """Set a freshness deadline that expires after final re-reads complete."""

        return replace(_binding(as_of), policy=short_policy)

    final_clock = _AS_OF.astimezone(UTC) + timedelta(seconds=4)
    reader, _ = _reader(
        clock_values=(_AS_OF, _AS_OF + timedelta(seconds=1), final_clock),
        policy_reader=_PolicyReader(expiring_binding),
    )

    assert reader.read_current_mark(_query()) is None


def test_reader_rejects_changed_current_price_publication_on_final_read() -> None:
    base = _source_evidence(_AS_OF, trade_date=_TRADE_DATE)
    calls = 0

    def changed_price(cutoff: datetime) -> PublishedPriceSourceEvidence:
        """Return a different exact publication member on the final source read."""

        nonlocal calls
        calls += 1
        evidence = replace(base, knowledge_cutoff=cutoff)
        if calls == 2:
            return replace(evidence, publication_id="changed-publication")
        return evidence

    reader, _ = _reader(price_reader=_PriceReader(changed_price))

    assert reader.read_current_mark(_query()) is None


def test_reader_rejects_retained_payload_capture_clock_after_final_check() -> None:
    base = _source_evidence(_AS_OF, trade_date=_TRADE_DATE)
    future_capture = replace(
        base.raw_payload_reference,
        response_completed_at=_AS_OF + timedelta(seconds=3),
    )

    def future_capture_source(cutoff: datetime) -> PublishedPriceSourceEvidence:
        """Keep the retained capture's original future clock instead of masking it."""

        return replace(
            base,
            raw_payload_reference=future_capture,
            knowledge_cutoff=cutoff,
        )

    reader, _ = _reader(price_reader=_PriceReader(future_capture_source))

    assert reader.read_current_mark(_query()) is None


def test_reader_rejects_changed_calendar_publication_on_final_read() -> None:
    first_calendar = _calendar(_AS_OF)
    publication = first_calendar.publication
    assert publication is not None
    second_calendar = replace(
        first_calendar,
        publication=replace(publication, policy_hash="8" * 64),
    )
    reader, _ = _reader(calendar_reader=_CalendarReader(sequence=(first_calendar, second_calendar)))

    assert reader.read_current_mark(_query()) is None


def test_reader_rejects_classification_that_disappears_on_final_read() -> None:
    classification = _classification(_AS_OF)
    reader, _ = _reader(
        classification_reader=_ClassificationReader(sequence=(classification, None))
    )

    assert reader.read_current_mark(_query()) is None


def test_retained_proof_rejects_forged_session_interval_end() -> None:
    """Replay validation independently binds the date to its published session close."""
    reader, _ = _reader()
    proof = reader.read_current_mark(_query())
    assert proof is not None
    shifted = proof.interval_end_at - timedelta(minutes=1)
    with pytest.raises(ValueError):
        replace(
            proof,
            interval_end_at=shifted,
            source_evidence=replace(proof.source_evidence, observed_at=shifted),
            valid_until=shifted
            + timedelta(seconds=proof.policy_binding.policy.freshness_window_seconds),
        )


def test_retained_proof_rejects_old_session_when_later_session_has_closed() -> None:
    """A reusable raw-mark proof must independently verify latest closed-session status."""
    reader, _ = _reader()
    proof = reader.read_current_mark(_query())
    assert proof is not None
    later = datetime(2026, 10, 28, 7, 0, 1, tzinfo=UTC)
    extended_policy = replace(proof.policy_binding.policy, freshness_window_seconds=172800)
    with pytest.raises(ValueError):
        replace(
            proof,
            checked_at=later,
            policy_binding=replace(proof.policy_binding, policy=extended_policy),
            valid_until=proof.interval_end_at + timedelta(seconds=172800),
        )


def test_reader_accepts_original_policy_completion_after_entry_cutoff():
    """Source reads follow the actual policy completion, without backdating it."""
    policies = _PolicyReader(
        lambda as_of: replace(_binding(as_of), checked_at=as_of + timedelta(seconds=1))
    )
    reader, _ = _reader(
        policy_reader=policies,
        clock_values=(
            _AS_OF,
            _AS_OF + timedelta(seconds=2),
            _AS_OF + timedelta(seconds=3),
            _AS_OF + timedelta(seconds=5),
            _AS_OF + timedelta(seconds=6),
        ),
    )
    proof = reader.read_current_mark(_query())
    assert proof is not None
    assert proof.policy_binding.checked_at == _AS_OF + timedelta(seconds=4)
