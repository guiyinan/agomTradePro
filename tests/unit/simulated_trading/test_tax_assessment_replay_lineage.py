"""In-memory contracts for locked tax assessment revision-chain reads."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest

from apps.simulated_trading.domain.corporate_action_tax_assessment import (
    CorporateActionTaxAssessment,
)
from apps.simulated_trading.infrastructure import (
    corporate_action_tax_assessment_repository as repository_module,
)
from core.exceptions import BusinessLogicError
from tests.unit.simulated_trading.test_corporate_action_tax_assessment import _assessment

_ALIAS = "default"
_BASE_TIME = datetime(2026, 11, 14, 8, 0, tzinfo=UTC)


def _row(
    assessment: CorporateActionTaxAssessment,
    *,
    pk: int,
    revision_id: str,
    parent_id: int | None = None,
    parent_revision_id: str | None = None,
    recorded_at: datetime | None = None,
    **overrides: object,
) -> SimpleNamespace:
    """Build one unsaved row with the exact scope and revision-link columns."""
    values: dict[str, object] = {
        "pk": pk,
        "account_id": assessment.account_id,
        "owner_user_id": assessment.owner_user_id,
        "assessment_revision_id": revision_id,
        "supersedes_id": parent_id,
        "supersedes_assessment_revision_id": parent_revision_id,
        "asset_code": assessment.asset_code,
        "security_id": assessment.security_id,
        "corporate_action_id": assessment.action.corporate_action_id,
        "record_date": assessment.history.record_date,
        "settlement_date": assessment.target_settlement_date,
        "disposition_id": assessment.calculation.disposition_id,
        "idempotency_key": assessment.calculation.idempotency_key,
        "semantic_sha256": "a" * 64,
        "recorded_at": (_BASE_TIME + timedelta(seconds=pk) if recorded_at is None else recorded_at),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _HeaderQuery:
    """Only the read operations used by the repository's locked query path."""

    def __init__(self, rows: tuple[SimpleNamespace, ...], state: dict[str, object]) -> None:
        self._rows = rows
        self._state = state
        self._query_kind = ""

    def select_for_update(self) -> _HeaderQuery:
        self._state["header_rows_locked"] = True
        return self

    def filter(self, **filters: object) -> _HeaderQuery:
        filter_calls = cast(list[dict[str, object]], self._state["header_filters"])
        filter_calls.append(filters)
        self._query_kind = "stream" if "idempotency_key" in filters else "alias"
        if self._query_kind == "stream":
            self._state["stream_filter"] = filters
        return self

    def exclude(self, **filters: object) -> _HeaderQuery:
        self._state["alias_exclude"] = filters
        return self

    def exists(self) -> bool:
        assert self._query_kind == "alias"
        return False

    def order_by(self, *fields: str) -> tuple[SimpleNamespace, ...]:
        assert self._query_kind == "stream"
        assert fields == ("id",)
        return self._rows


class _HeaderManager:
    def __init__(self, rows: tuple[SimpleNamespace, ...], state: dict[str, object]) -> None:
        self._rows = rows
        self._state = state

    def using(self, using: str) -> _HeaderQuery:
        assert using == _ALIAS
        return _HeaderQuery(self._rows, self._state)


class _AccountQuery:
    def __init__(self, owner_user_id: int, state: dict[str, object]) -> None:
        self._owner_user_id = owner_user_id
        self._state = state

    def using(self, using: str) -> _AccountQuery:
        assert using == _ALIAS
        return self

    def select_for_update(self) -> _AccountQuery:
        self._state["account_locked"] = True
        return self

    def filter(self, **filters: object) -> _AccountQuery:
        self._state["account_filter"] = filters
        return self

    def first(self) -> SimpleNamespace:
        return SimpleNamespace(user_id=self._owner_user_id)


def _repository(
    monkeypatch: pytest.MonkeyPatch,
    assessment: CorporateActionTaxAssessment,
    rows: tuple[SimpleNamespace, ...],
    *,
    owner_user_id: int | None = None,
    corrupt_ids: frozenset[int] = frozenset(),
) -> tuple[repository_module.DjangoCorporateActionTaxAssessmentRepository, dict[str, object]]:
    """Compose the repository around mocked managers and its existing integrity verifier."""
    state: dict[str, object] = {
        "account_locked": False,
        "header_rows_locked": False,
        "header_filters": [],
        "verified": [],
    }
    account_row_owner = assessment.owner_user_id if owner_user_id is None else owner_user_id
    account_manager = _AccountQuery(account_row_owner, state)
    header_manager = _HeaderManager(rows, state)
    monkeypatch.setattr(
        repository_module,
        "connections",
        {_ALIAS: SimpleNamespace(in_atomic_block=True, vendor="sqlite")},
    )
    monkeypatch.setattr(
        repository_module,
        "SimulatedAccountModel",
        SimpleNamespace(_default_manager=account_manager),
    )
    monkeypatch.setattr(
        repository_module,
        "Header",
        SimpleNamespace(_default_manager=header_manager),
    )
    repository = repository_module.DjangoCorporateActionTaxAssessmentRepository(using=_ALIAS)

    def verify_retained(header: SimpleNamespace) -> None:
        verified = cast(list[int], state["verified"])
        verified.append(header.pk)
        if header.pk in corrupt_ids:
            raise BusinessLogicError("retained lineage material is damaged")

    monkeypatch.setattr(repository, "verify_retained_integrity", verify_retained)
    return repository, state


def test_read_locked_assessment_lineage_returns_and_verifies_root_to_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    root = _row(assessment, pk=1, revision_id="revision-root")
    middle = _row(
        assessment,
        pk=2,
        revision_id="revision-middle",
        parent_id=1,
        parent_revision_id="revision-root",
    )
    head = _row(
        assessment,
        pk=3,
        revision_id="revision-head",
        parent_id=2,
        parent_revision_id="revision-middle",
    )
    repository, state = _repository(monkeypatch, assessment, (head, root, middle))

    lineage = repository.read_locked_assessment_lineage(assessment)

    assert tuple(row.pk for row in lineage) == (1, 2, 3)
    assert state["verified"] == [1, 2, 3]
    assert state["account_locked"] is True
    assert state["header_rows_locked"] is True
    assert "owner_user_id" not in cast(dict[str, object], state["stream_filter"])


def test_empty_assessment_stream_returns_an_empty_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    repository, state = _repository(monkeypatch, assessment, ())

    assert repository.read_locked_assessment_lineage(assessment) == ()
    assert state["verified"] == []


@pytest.mark.parametrize("defect", ("missing_parent", "wrong_parent_revision", "foreign_scope"))
def test_missing_parent_wrong_parent_revision_and_scope_mismatch_block(
    monkeypatch: pytest.MonkeyPatch,
    defect: str,
) -> None:
    assessment = _assessment()
    root = _row(assessment, pk=1, revision_id="revision-root")
    child_values: dict[str, object] = {
        "parent_id": 1,
        "parent_revision_id": "revision-root",
    }
    rows = (root,)
    if defect == "missing_parent":
        child_values["parent_id"] = 99
        child_values["parent_revision_id"] = "foreign-revision"
    elif defect == "wrong_parent_revision":
        child_values["parent_revision_id"] = "not-the-parent-revision"
    elif defect == "foreign_scope":
        child_values["owner_user_id"] = assessment.owner_user_id + 1
    child = _row(
        assessment,
        pk=2,
        revision_id="revision-child",
        **child_values,
    )
    repository, _ = _repository(monkeypatch, assessment, rows + (child,))

    with pytest.raises(BusinessLogicError):
        repository.read_locked_assessment_lineage(assessment)


@pytest.mark.parametrize(
    "rows_factory",
    (
        "fork",
        "cycle_plus_normal_chain",
        "disconnected_roots",
        "backwards_recorded_at",
    ),
)
def test_fork_cycle_disconnection_and_backwards_time_block(
    monkeypatch: pytest.MonkeyPatch,
    rows_factory: str,
) -> None:
    assessment = _assessment()
    if rows_factory == "fork":
        rows = (
            _row(assessment, pk=1, revision_id="root"),
            _row(assessment, pk=2, revision_id="left", parent_id=1, parent_revision_id="root"),
            _row(assessment, pk=3, revision_id="right", parent_id=1, parent_revision_id="root"),
        )
    elif rows_factory == "cycle_plus_normal_chain":
        rows = (
            _row(
                assessment, pk=1, revision_id="cycle-a", parent_id=2, parent_revision_id="cycle-b"
            ),
            _row(
                assessment, pk=2, revision_id="cycle-b", parent_id=1, parent_revision_id="cycle-a"
            ),
            _row(assessment, pk=3, revision_id="root"),
            _row(assessment, pk=4, revision_id="head", parent_id=3, parent_revision_id="root"),
        )
    elif rows_factory == "disconnected_roots":
        rows = (
            _row(assessment, pk=1, revision_id="root-a"),
            _row(assessment, pk=2, revision_id="root-b"),
        )
    else:
        rows = (
            _row(
                assessment,
                pk=1,
                revision_id="root",
                recorded_at=_BASE_TIME + timedelta(seconds=10),
            ),
            _row(
                assessment,
                pk=2,
                revision_id="head",
                parent_id=1,
                parent_revision_id="root",
                recorded_at=_BASE_TIME + timedelta(seconds=5),
            ),
        )
    repository, _ = _repository(monkeypatch, assessment, rows)

    with pytest.raises(BusinessLogicError):
        repository.read_locked_assessment_lineage(assessment)


def test_damaged_non_head_predecessor_blocks_even_when_head_semantic_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    root = _row(assessment, pk=1, revision_id="revision-root")
    head = _row(
        assessment,
        pk=2,
        revision_id="revision-head",
        parent_id=1,
        parent_revision_id="revision-root",
        semantic_sha256="f" * 64,
    )
    repository, state = _repository(
        monkeypatch,
        assessment,
        (root, head),
        corrupt_ids=frozenset({1}),
    )

    with pytest.raises(BusinessLogicError, match="material is damaged"):
        repository.find_exact_semantic_head(assessment)

    assert state["verified"] == [1]


def test_exact_match_uses_only_verified_current_head_after_full_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessment = _assessment()
    root = _row(assessment, pk=1, revision_id="revision-root")
    head = _row(
        assessment,
        pk=2,
        revision_id="revision-head",
        parent_id=1,
        parent_revision_id="revision-root",
        semantic_sha256=assessment.semantic_sha256,
    )
    repository, state = _repository(monkeypatch, assessment, (root, head))
    verify_stored = SimpleNamespace(calls=[])

    def verify_exact(header: SimpleNamespace, candidate: CorporateActionTaxAssessment) -> None:
        assert header is head
        assert candidate is assessment
        verify_stored.calls.append(header.pk)

    monkeypatch.setattr(repository, "verify_stored", verify_exact)

    result = repository.find_exact_semantic_head(assessment)

    assert result is not None and result.header is head and result.replayed is True
    assert state["verified"] == [1, 2]
    assert verify_stored.calls == [2]
