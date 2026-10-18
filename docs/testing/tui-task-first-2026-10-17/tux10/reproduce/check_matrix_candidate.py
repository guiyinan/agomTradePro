"""Run only explicit read-only acceptance gates in the current TUX10 window."""

import subprocess
import sys
from pathlib import Path

qa = Path(__file__).resolve().parent
python = sys.executable
commands = [
    (
        "isort-check-02",
        [
            python,
            "-B",
            "-X",
            "utf8",
            "-m",
            "isort",
            "--check-only",
            "tests/component/test_tui_task_first_browser.py",
            "tests/component/test_tui_research_task_browser.py",
            "tests/component/test_tui_task_focus_browser.py",
            "tests/support/tui_research/market_consumer_state.py",
            str(qa / "test_tux10_surface_inventory.py"),
        ],
    ),
    (
        "black-check-02",
        [
            python,
            "-B",
            "-X",
            "utf8",
            "-m",
            "black",
            "--check",
            "tests/component/test_tui_task_first_browser.py",
            "tests/component/test_tui_research_task_browser.py",
            "tests/component/test_tui_task_focus_browser.py",
            "tests/support/tui_research/market_consumer_state.py",
            str(qa / "test_tux10_surface_inventory.py"),
        ],
    ),
    (
        "ruff-02",
        [
            python,
            "-B",
            "-X",
            "utf8",
            "-m",
            "ruff",
            "check",
            "tests/component/test_tui_task_first_browser.py",
            "tests/component/test_tui_research_task_browser.py",
            "tests/component/test_tui_task_focus_browser.py",
            "tests/support/tui_research/market_consumer_state.py",
            str(qa / "test_tux10_surface_inventory.py"),
        ],
    ),
    ("runtime-check-02", ["npm.cmd", "run", "check:tui"]),
    ("tui-static-final-03", [python, "-B", "-X", "utf8", "scripts/check_tui_static_contracts.py"]),
    ("tui-copy-01", [python, "-B", "-X", "utf8", "scripts/check_tui_action_copy_and_density.py"]),
    (
        "tui-source-01",
        [python, "-B", "-X", "utf8", "scripts/check_tui_metadata_source_consistency.py"],
    ),
    (
        "tui-presentation-01",
        [python, "-B", "-X", "utf8", "scripts/check_tui_presentation_details.py"],
    ),
    ("freshness-01", [python, "-B", "-X", "utf8", "scripts/check_current_data_contracts.py"]),
    ("doc-route-01", [python, "-B", "-X", "utf8", "scripts/check_doc_route_sdk_consistency.py"]),
    (
        "migration-01",
        [python, "-B", "-X", "utf8", "scripts/web_template_migration_inventory.py", "--check"],
    ),
    ("module-check-01", [python, "-B", "-X", "utf8", "scripts/check_module_map.py"]),
    (
        "retirement-01",
        [python, "-B", "-X", "utf8", "scripts/check_versioned_surface_retirement.py"],
    ),
]
failures = []
for label, command in commands:
    result = subprocess.run(
        [python, "-B", "-X", "utf8", str(qa / "run_phase.py"), label, *command], check=False
    )
    print(f"GATE {label} exit={result.returncode}", flush=True)
    if result.returncode:
        failures.append(label)
print("FAILED GATES", failures, flush=True)
raise SystemExit(bool(failures))
