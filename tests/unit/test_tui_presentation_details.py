"""Machine contracts for TUX-05 field translation and internal-key cleanup."""

from __future__ import annotations

from scripts.check_tui_presentation_details import (
    AUDITED_FIELD_LABELS,
    build_report,
    check_tui_presentation_details,
)


def test_guard_reports_raw_fields_missing_mappings_and_visible_screen_locator() -> None:
    """Every TUX-05 machine rule emits a stable violation."""

    broken_labels = dict(AUDITED_FIELD_LABELS)
    broken_labels.pop("quota_charged")
    payload = {
        "actions": [
            {
                "key": "usage.logs",
                "fields": [
                    {
                        "key": "quota_charged",
                        "label": "Quota Charged",
                        "placeholder": "输入Quota Charged",
                    }
                ],
            }
        ]
    }

    report = check_tui_presentation_details(
        published_payload=payload,
        generated_payload=payload,
        runtime_labels=broken_labels,
        compiler_labels=broken_labels,
        template_text='<input data-current-location value="screen:boot">',
    )

    assert not report.passed
    assert report.raw_field_name_count == 2
    assert report.internal_screen_locator_count == 2
    assert {
        "field_translation:graph_label",
        "field_translation:raw_fragment",
        "field_translation:source_mapping",
        "internal_key:visible_locator",
    } <= {violation.rule_id for violation in report.violations}


def test_real_tui_sources_close_audited_field_and_internal_key_debt() -> None:
    """Reviewed graphs and runtime sources satisfy the TUX-05 machine contract."""

    report = build_report()

    assert report.passed, report.as_json()
    assert report.audited_field_count == len(AUDITED_FIELD_LABELS)
    assert report.graph_field_occurrence_count > 0
    assert report.raw_field_name_count == 0
    assert report.internal_screen_locator_count == 0
