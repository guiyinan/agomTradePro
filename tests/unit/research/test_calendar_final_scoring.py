"""Receipt-bound CAL-03 final scoring exercises synthetic observations only."""

import json
from dataclasses import replace

import pytest

from apps.research.application.calendar_validation import (
    FinalCalendarEvaluator,
    FinalCalendarInputs,
)
from apps.research.application.event_study_control import EventStudyControl
from apps.research.domain.event_study_control import (
    EventStudyBinding,
    EventStudyControlError,
    FinalOOSClaim,
)
from apps.research.infrastructure.calendar_final_report import publish_final_calendar_report
from apps.research.infrastructure.validation_ridge import ridge_predict
from scripts.run_cal03_synthetic_walk_forward import _fixture_series, synthetic_case


class SyntheticRegistry:
    def __init__(self, binding, stamp):
        self.binding = binding
        self.stamp = stamp
        self.used = False

    def claim(self, study_key, *, actor_user_id):
        assert study_key == self.binding.study_key
        if self.used:
            raise EventStudyControlError("FINAL_OOS_ALREADY_USED")
        self.used = True
        return FinalOOSClaim(1, self.binding, self.stamp, actor_user_id, 1)


@pytest.fixture(scope="module")
def case():
    design, cal, _ = synthetic_case()
    binding = EventStudyBinding(
        "fixture", "trial", "experiment", "family", "a" * 64, "pit", "b" * 64, "c" * 64
    )
    targets = {
        code: _fixture_series(code, 1103 + i, cal, len(cal.sessions), design)
        for i, code in enumerate(design.targets)
    }
    stop = len(cal.sessions) - max(design.clock.horizons)
    family = tuple(
        f"trial/{code}/{h}/{s}"
        for code in design.targets
        for h in design.clock.horizons
        for s in ("all", "single_event", "exclusive_window")
    )
    return FinalCalendarInputs(
        binding,
        design,
        cal,
        targets,
        cal.sessions[stop - 504].session_on,
        cal.sessions[stop - 1].session_on,
        family,
        {},
        0.05,
    )


def run(case):
    registry = SyntheticRegistry(case.binding, case.calendar.known_at)
    reads = []

    def read(claim):
        assert registry.used
        reads.append(claim)
        return case

    reports = []
    control = EventStudyControl(registry)
    evaluator = FinalCalendarEvaluator(read, reports.append, ridge_predict)
    claim = control.run_final_once(case.binding.study_key, actor_user_id=1, evaluator=evaluator)
    with pytest.raises(EventStudyControlError, match="FINAL_OOS_ALREADY_USED"):
        control.run_final_once(case.binding.study_key, actor_user_id=1, evaluator=evaluator)
    assert reads == [claim] and len(reports) == 1 and reports[0].claim == claim
    return reports[0]


def test_full_rehearsal_scores_registered_504_origins(case, tmp_path):
    report = run(case)
    publish_final_calendar_report(tmp_path, report)
    dest = tmp_path / "cal03-final-1.json"
    original = dest.read_bytes()
    published = json.loads(original)
    assert published["claim"]["binding"]["manifest_id"] == case.binding.manifest_id
    assert len(published["targets"]) == 9
    publish_final_calendar_report(tmp_path, report)
    with pytest.raises(EventStudyControlError, match="FINAL_REPORT_RECEIPT_CONFLICT"):
        publish_final_calendar_report(tmp_path, replace(report, family_complete=False))
    assert dest.read_bytes() == original
    assert report.family_complete and len(report.targets) == 9
    for result in report.targets:
        assert result.final.validation_expected == result.final.validation_valid == 504
        assert (result.final.first_validation, result.final.last_validation) == (
            case.first_origin,
            case.last_origin,
        )
        assert result.final.score_at <= case.calendar.known_at
        assert len(result.training_mse) == 3 and len(result.validation.folds) >= 5
        assert result.estimates[0].inference.count == 504
        for e in result.estimates:
            assert e.holm_p is not None and e.exploratory_bh_q is not None
            assert e.support.training_events.isdisjoint(e.support.oos_events)
            assert e.status in ("not_confirmed", "oos_supported")


@pytest.mark.parametrize("error", ["binding", "split", "family", "unregistered_trial"])
def test_stale_identity_rejected_before_reading_any_price(case, error):
    class Blocked(dict):
        def get(self, *args):
            pytest.fail("prices accessed before checking binding and split")

    sample = replace(case, series={k: replace(v, prices=Blocked()) for k, v in case.series.items()})
    if error == "binding":
        sample = replace(sample, binding=replace(sample.binding, manifest_id="other"))
    if error == "split":
        sample = replace(sample, first_origin=sample.last_origin)
    if error == "family":
        sample = replace(sample, family=sample.family[:-1])
    if error == "unregistered_trial":
        sample = replace(sample, family=(*sample.family, "other_trial/contrast"))
    registry = SyntheticRegistry(case.binding, case.calendar.known_at)
    with pytest.raises(EventStudyControlError, match="MISMATCH"):
        EventStudyControl(registry).run_final_once(
            "fixture",
            actor_user_id=1,
            evaluator=FinalCalendarEvaluator(
                lambda claim: sample, lambda r: pytest.fail("unexpected report"), ridge_predict
            ),
        )


def test_missing_oos_windows_do_not_grant_sibling_hypotheses_support(case):
    code = case.design.targets[0]
    design = replace(
        case.design, targets=(code,), clock=replace(case.design.clock, horizons=(1, 3, 5))
    )
    data = case.series[code]
    data = replace(data, features={d: v for d, v in data.features.items() if d < case.first_origin})
    result = run(
        replace(
            case,
            design=design,
            series={code: data},
            family=tuple(k for k in case.family if f"/{code}/" in k),
        )
    )
    assert not result.family_complete
    for row in result.targets:
        assert row.final.validation_valid == 0
        assert all(
            s.status == "insufficient_data"
            and "OOS_EVENTS_INSUFFICIENT" in s.reasons
            and s.holm_p is None
            for s in row.estimates
        )
