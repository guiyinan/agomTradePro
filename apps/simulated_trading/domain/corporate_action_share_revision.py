"""Pure normalization rules for audited simulated share-action revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from apps.simulated_trading.domain.corporate_action_posting import (
    CorporateActionEntryKind,
    CorporateActionInputValidationError,
    CorporateActionKind,
    CorporateActionStage,
    CorporateActionStageRequest,
)

_ORDINARY_ENTRIES = frozenset(
    {CorporateActionEntryKind.POSTING, CorporateActionEntryKind.SUCCESSOR}
)
_CORRECTION_ENTRIES = frozenset(
    {CorporateActionEntryKind.REVERSAL, CorporateActionEntryKind.SUCCESSOR}
)
_SHARE_STAGE_ORDER = {
    CorporateActionStage.SHARE_ENTITLEMENT: 0,
    CorporateActionStage.SHARE_DELIVERY: 1,
    CorporateActionStage.SHARE_SELLABLE_RELEASE: 2,
}
_REVISION_IDENTITY_FIELDS = (
    "account_id",
    "owner_user_id",
    "security_id",
    "asset_code",
    "asset_name",
    "source_namespace",
    "source_record_id",
    "source_event_id",
    "source_revision_id",
    "supersedes_revision_id",
    "record_date",
    "effective_date",
    "source_payload_sha256",
    "qualification_sha256",
    "qualifier_identity",
    "source_observed_at",
    "qualified_at",
    "posted_at",
    "action_kind",
)


@dataclass(frozen=True, slots=True)
class CorporateActionShareRevisionPlan:
    """Canonical write order, exact owner-gate anchor and original receipt order."""

    requests: tuple[CorporateActionStageRequest, ...]
    gate_anchor: CorporateActionStageRequest
    caller_stage_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require a complete immutable plan with one exact stage key per input."""

        if type(self.requests) is not tuple or not self.requests:
            raise CorporateActionInputValidationError(
                "share revision plan requires one exact request tuple",
                "CORPORATE_ACTION_INPUT_INVALID",
            )
        if any(type(request) is not CorporateActionStageRequest for request in self.requests):
            raise CorporateActionInputValidationError(
                "share revision plan contains an invalid stage request",
                "CORPORATE_ACTION_INPUT_INVALID",
            )
        if type(self.gate_anchor) is not CorporateActionStageRequest or not any(
            request is self.gate_anchor for request in self.requests
        ):
            raise CorporateActionInputValidationError(
                "share revision plan gate anchor is outside its exact request tuple",
                "CORPORATE_ACTION_INPUT_INVALID",
            )
        if (
            type(self.caller_stage_keys) is not tuple
            or len(self.caller_stage_keys) != len(self.requests)
            or any(
                type(stage_key) is not str or not stage_key for stage_key in self.caller_stage_keys
            )
            or len(set(self.caller_stage_keys)) != len(self.caller_stage_keys)
            or set(self.caller_stage_keys) != {request.stage_key for request in self.requests}
        ):
            raise CorporateActionInputValidationError(
                "share revision plan caller receipt order is incomplete",
                "CORPORATE_ACTION_INPUT_INVALID",
            )


def _invalid(message: str, code: str) -> NoReturn:
    """Raise one stable Domain validation error for an invalid revision plan."""

    raise CorporateActionInputValidationError(message, code)


def _same_revision_identity(
    first: CorporateActionStageRequest,
    request: CorporateActionStageRequest,
) -> bool:
    """Compare every stable account and source fact shared by one revision."""

    return all(
        getattr(first, field_name) == getattr(request, field_name)
        for field_name in _REVISION_IDENTITY_FIELDS
    )


def _plan(
    requests: tuple[CorporateActionStageRequest, ...],
    *,
    canonical_requests: tuple[CorporateActionStageRequest, ...] | None = None,
    gate_anchor: CorporateActionStageRequest | None = None,
) -> CorporateActionShareRevisionPlan:
    """Create a checked plan while preserving the caller's stage-key order."""

    ordered = requests if canonical_requests is None else canonical_requests
    anchor = requests[0] if gate_anchor is None else gate_anchor
    return CorporateActionShareRevisionPlan(
        requests=ordered,
        gate_anchor=anchor,
        caller_stage_keys=tuple(request.stage_key for request in requests),
    )


def plan_corporate_action_share_revision(
    requests: tuple[CorporateActionStageRequest, ...],
) -> CorporateActionShareRevisionPlan:
    """Normalize one share stage, complete correction, or no-exercise rights row.

    Correction reversals are ordered from sellable release back to entitlement.
    Successors are then ordered from entitlement through delivery to release. The
    ledger repository remains responsible for proving every reversal target is the
    complete current predecessor set before writing any row.
    """

    if type(requests) is not tuple or not requests:
        _invalid(
            "share revision must contain an exact non-empty request tuple",
            "CORPORATE_ACTION_INPUT_INVALID",
        )
    for request in requests:
        if type(request) is not CorporateActionStageRequest:
            _invalid(
                "share revision contains an invalid stage request",
                "CORPORATE_ACTION_INPUT_INVALID",
            )
        try:
            request.__post_init__()
        except CorporateActionInputValidationError:
            raise
        except (TypeError, ValueError) as error:
            raise CorporateActionInputValidationError(
                "share revision contains an invalid stage request",
                "CORPORATE_ACTION_INPUT_INVALID",
            ) from error

    first = requests[0]
    if first.action_kind is CorporateActionKind.RIGHTS_ISSUE:
        if (
            len(requests) != 1
            or first.stage is not CorporateActionStage.RIGHTS_NOT_EXERCISED
            or first.entry_kind is not CorporateActionEntryKind.NO_EFFECT
        ):
            _invalid(
                "rights support is limited to one exact no-exercise stage",
                "CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return _plan(requests)

    share_stages = frozenset(_SHARE_STAGE_ORDER)
    if first.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION or any(
        request.action_kind is not CorporateActionKind.SHARE_DISTRIBUTION
        or request.stage not in share_stages
        for request in requests
    ):
        _invalid(
            "share revision excludes cash, rights exercise, and mixed action families",
            "CORPORATE_ACTION_STAGE_UNSUPPORTED",
        )

    for request in requests[1:]:
        if not _same_revision_identity(first, request):
            _invalid(
                "share revision stages must share exact account and source identity",
                "CORPORATE_ACTION_BATCH_IDENTITY_INVALID",
            )

    stage_keys = tuple(request.stage_key for request in requests)
    if len(set(stage_keys)) != len(stage_keys):
        _invalid(
            "share revision contains a duplicate stage key",
            "CORPORATE_ACTION_DUPLICATE_STAGE",
        )

    if len(requests) == 1:
        if first.entry_kind not in _ORDINARY_ENTRIES:
            _invalid(
                "one share stage must be an ordinary posting or successor",
                "CORPORATE_ACTION_STAGE_UNSUPPORTED",
            )
        return _plan(requests)

    if any(request.entry_kind not in _CORRECTION_ENTRIES for request in requests):
        _invalid(
            "a multi-stage share revision must contain reversals and successors",
            "CORPORATE_ACTION_STAGE_UNSUPPORTED",
        )

    reversals = tuple(
        request for request in requests if request.entry_kind is CorporateActionEntryKind.REVERSAL
    )
    successors = tuple(
        request for request in requests if request.entry_kind is CorporateActionEntryKind.SUCCESSOR
    )
    reversal_stages = {request.stage for request in reversals}
    successor_stages = {request.stage for request in successors}
    if not reversals or not successors or reversal_stages != successor_stages:
        _invalid(
            "share correction must reverse and replace the same complete stage set",
            "CORPORATE_ACTION_REVISION_CONFLICT",
        )

    ordered_reversals = tuple(
        sorted(reversals, key=lambda request: _SHARE_STAGE_ORDER[request.stage], reverse=True)
    )
    ordered_successors = tuple(
        sorted(successors, key=lambda request: _SHARE_STAGE_ORDER[request.stage])
    )
    canonical_requests = ordered_reversals + ordered_successors
    return _plan(
        requests,
        canonical_requests=canonical_requests,
        gate_anchor=ordered_successors[0],
    )


__all__ = [
    "CorporateActionShareRevisionPlan",
    "plan_corporate_action_share_revision",
]
