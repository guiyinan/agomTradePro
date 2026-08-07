"""Portfolio-owned temporal split values for R4 rolling research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


def _require_token(value: str, field_name: str, *, maximum: int = 160) -> None:
    if not value.strip() or len(value) > maximum:
        raise ValueError(f"{field_name} must be a bounded non-blank string")
    if any(character.isspace() for character in value):
        raise ValueError(f"{field_name} cannot contain whitespace")


def _require_positive_int(value: int, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True)
class SampleWindow:
    """Closed date window for one Portfolio research sample partition."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("SampleWindow.start cannot follow end")


@dataclass(frozen=True)
class WalkForwardFold:
    """One ordered Portfolio train/validation/OOS walk-forward fold."""

    fold_id: str
    training: SampleWindow
    validation: SampleWindow
    out_of_sample: SampleWindow

    def __post_init__(self) -> None:
        _require_token(self.fold_id, "WalkForwardFold.fold_id")
        if self.training.end >= self.validation.start:
            raise ValueError("walk-forward training must precede validation")
        if self.validation.end >= self.out_of_sample.start:
            raise ValueError("walk-forward validation must precede out-of-sample")


def _has_embargo(left: SampleWindow, right: SampleWindow, embargo_days: int) -> bool:
    return (right.start - left.end).days > embargo_days


@dataclass(frozen=True)
class TemporalSplitSpec:
    """Versioned Portfolio train/validation/OOS and embargo policy."""

    policy_version: str
    training: SampleWindow
    validation: SampleWindow
    out_of_sample: SampleWindow
    walk_forward_folds: tuple[WalkForwardFold, ...]
    embargo_days: int

    def __post_init__(self) -> None:
        _require_token(self.policy_version, "TemporalSplitSpec.policy_version")
        _require_positive_int(self.embargo_days, "TemporalSplitSpec.embargo_days")
        if not _has_embargo(self.training, self.validation, self.embargo_days):
            raise ValueError("training/validation embargo is missing")
        if not _has_embargo(self.validation, self.out_of_sample, self.embargo_days):
            raise ValueError("validation/out-of-sample embargo is missing")
        if not self.walk_forward_folds:
            raise ValueError("TemporalSplitSpec.walk_forward_folds cannot be empty")
        fold_ids = tuple(fold.fold_id for fold in self.walk_forward_folds)
        if len(fold_ids) != len(set(fold_ids)):
            raise ValueError("walk-forward fold identities must be unique")
        for fold in self.walk_forward_folds:
            if not _has_embargo(fold.training, fold.validation, self.embargo_days):
                raise ValueError(f"walk-forward fold {fold.fold_id} lacks train embargo")
            if not _has_embargo(fold.validation, fold.out_of_sample, self.embargo_days):
                raise ValueError(f"walk-forward fold {fold.fold_id} lacks OOS embargo")


__all__ = ["SampleWindow", "TemporalSplitSpec", "WalkForwardFold"]
