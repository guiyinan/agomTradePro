from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest import mock
from unittest.mock import Mock

PROPOSAL_ROOT = Path(__file__).resolve().parents[2]
MANAGER_PATH = PROPOSAL_ROOT / "scripts/manage_vps_migrations.py"
EXECUTOR_PATH = PROPOSAL_ROOT / "scripts/deploy_legacy_observed_runtime.py"


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load proposal module: {name}")
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeGraph:
    def __init__(
        self,
        leaves: list[tuple[str, str]],
        plans: dict[tuple[str, str], list[tuple[str, str]]],
    ) -> None:
        self._leaves = leaves
        self._plans = plans
        plan_nodes = {node for plan in plans.values() for node in plan}
        self.node_map = {node: object() for node in set(leaves) | plan_nodes}

    def leaf_nodes(self) -> list[tuple[str, str]]:
        return list(self._leaves)

    def forwards_plan(self, node: tuple[str, str]) -> list[tuple[str, str]]:
        return self._plans[node]


class ProposalMigrationPhasingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manager = _load_module("proposal_manage_vps_migrations", MANAGER_PATH)
        cls.executor_module = _load_module("proposal_observed_executor", EXECUTOR_PATH)

    def test_phase_a_requires_ai005_to_be_an_independent_leaf_and_targets_0004(self) -> None:
        manager = self.manager
        deferred = manager._OBSERVED_DEFERRED_MIGRATION
        predecessor = manager._OBSERVED_REQUIRED_PREDECESSOR
        other_leaf = ("portfolio", "0012_latest")
        graph = FakeGraph(
            [deferred, other_leaf],
            {
                deferred: [predecessor, deferred],
                other_leaf: [("portfolio", "0001_initial"), other_leaf],
            },
        )
        executor = SimpleNamespace(
            loader=SimpleNamespace(graph=graph),
            migration_plan=Mock(return_value=[]),
        )
        with mock.patch.object(manager, "MigrationExecutor", return_value=executor):
            self.assertEqual(
                manager._observed_phase_a_targets(),
                sorted([other_leaf, predecessor]),
            )

    def test_phase_a_blocks_if_any_other_leaf_depends_on_ai005(self) -> None:
        manager = self.manager
        later_leaf = ("ai_provider", "0006_later")
        graph = FakeGraph(
            [later_leaf],
            {later_leaf: [manager._OBSERVED_DEFERRED_MIGRATION, later_leaf]},
        )
        executor = SimpleNamespace(
            loader=SimpleNamespace(graph=graph),
            migration_plan=Mock(return_value=[]),
        )
        with mock.patch.object(manager, "MigrationExecutor", return_value=executor):
            with self.assertRaisesRegex(SystemExit, "OBSERVED_PHASE_A_DEFERRED_MIGRATION_INVALID"):
                manager._observed_phase_a_targets()

    def test_phase_a_blocks_any_reverse_migration_plan(self) -> None:
        manager = self.manager
        deferred = manager._OBSERVED_DEFERRED_MIGRATION
        predecessor = manager._OBSERVED_REQUIRED_PREDECESSOR
        other_leaf = ("portfolio", "0012_latest")
        graph = FakeGraph(
            [deferred, other_leaf],
            {
                deferred: [predecessor, deferred],
                other_leaf: [("portfolio", "0001_initial"), other_leaf],
            },
        )
        migration = SimpleNamespace(app_label="portfolio", name="0012_latest")
        executor = SimpleNamespace(
            loader=SimpleNamespace(graph=graph),
            migration_plan=Mock(return_value=[(migration, True)]),
        )
        with mock.patch.object(manager, "MigrationExecutor", return_value=executor):
            with self.assertRaisesRegex(SystemExit, "OBSERVED_PHASE_A_REVERSE_PLAN_UNSAFE"):
                manager._observed_phase_a_targets()

    def test_phase_a_executor_applies_only_other_leaves_and_ai0004(self) -> None:
        manager = self.manager
        deferred = manager._OBSERVED_DEFERRED_MIGRATION
        predecessor = manager._OBSERVED_REQUIRED_PREDECESSOR
        other_leaf = ("portfolio", "0012_latest")
        graph = FakeGraph(
            [deferred, other_leaf],
            {
                deferred: [predecessor, deferred],
                other_leaf: [("portfolio", "0001_initial"), other_leaf],
            },
        )
        fake_executor = SimpleNamespace(
            loader=SimpleNamespace(graph=graph),
            migration_plan=Mock(return_value=[]),
            migrate=Mock(),
        )
        with (
            mock.patch.object(manager, "MigrationExecutor", return_value=fake_executor),
            mock.patch.object(
                manager,
                "_migration_state",
                side_effect=(
                    (["ai_provider.0005_drop_plaintext_api_key"], []),
                    (["ai_provider.0005_drop_plaintext_api_key"], [".".join(predecessor)]),
                ),
            ),
        ):
            manager._run_observed_phase_a()
        fake_executor.migrate.assert_called_once_with(sorted([other_leaf, predecessor]))

    def test_phase_b_executes_original_full_migrate_then_requires_zero_pending(self) -> None:
        manager = self.manager
        with (
            mock.patch.object(manager, "execute_from_command_line") as run_migrate,
            mock.patch.object(
                manager,
                "_migration_state",
                return_value=([], ["ai_provider.0005_drop_plaintext_api_key"]),
            ),
        ):
            manager._run_observed_phase_b()
        run_migrate.assert_called_once_with(["manage.py", "migrate", "--noinput"])

        with (
            mock.patch.object(manager, "execute_from_command_line"),
            mock.patch.object(
                manager,
                "_migration_state",
                return_value=(
                    ["portfolio.0012_latest"],
                    ["ai_provider.0005_drop_plaintext_api_key"],
                ),
            ),
        ):
            with self.assertRaisesRegex(SystemExit, "OBSERVED_PHASE_B_SCHEMA_INCOMPLETE"):
                manager._run_observed_phase_b()

    def _make_executor(self, temp: Path) -> object:
        module = self.executor_module
        report_dir = temp / "reports"
        report_dir.mkdir()
        target = temp / "opt/agomtradepro"
        baseline = temp / "baseline.json"
        compatibility = temp / "compatibility.json"
        config = module.Config(
            target,
            "20261117153000",
            "b" * 40,
            "c" * 64,
            "sha256:" + "a" * 64,
            baseline,
            "d" * 64,
            compatibility,
            "e" * 64,
            report_dir,
            {},
            "f" * 32,
        )
        return module.Executor(config, Mock())

    def test_incomplete_phase_b_migration_recovers_only_readonly_modern_web(self) -> None:
        module = self.executor_module
        with tempfile.TemporaryDirectory(prefix="observed-phase-b-failure-") as name:
            executor = self._make_executor(Path(name))
            executor.preflight = lambda: None
            executor.stage_candidate_env = lambda: None

            def create_override() -> None:
                executor.override.parent.mkdir(parents=True, exist_ok=True)
                executor.override.write_text("services: {}\n", encoding="utf-8")
                executor.override_created = True

            executor.prepare_phase_a_override = create_override

            def complete_phase_a() -> None:
                executor.migration_started = True
                executor.legacy_schema_verified = True
                executor.committed = True

            executor.phase_a = complete_phase_a

            def fail_phase_b() -> None:
                executor.phase_b_migration_started = True
                raise module.Blocked("OBSERVED_TEST_PHASE_B_MIGRATION_FAILURE")

            executor.phase_b = fail_phase_b
            executor.stop_phase_b_workers = lambda: True
            executor.quiesce_owned_jobs = lambda: True
            executor.recover_modern_web = Mock(return_value=True)
            executor.restore_old_apps = Mock(side_effect=AssertionError("legacy restore forbidden"))

            status = executor.execute()
            executor.recover_modern_web.assert_called_once_with(read_only=True)
            executor.restore_old_apps.assert_not_called()
            self.assertEqual(status, 23)
            self.assertTrue(executor.readonly_override_retained)
            self.assertTrue(executor.override.is_file())
            report = json.loads(executor.report.read_text(encoding="utf-8"))
            self.assertFalse(report["full_schema_verified"])
            self.assertTrue(report["readonly_override_retained"])
            self.assertEqual(report["readonly_override_path"], str(executor.override))

    def test_executor_never_reports_deployed_without_full_schema_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="observed-phase-b-missing-proof-") as name:
            executor = self._make_executor(Path(name))
            executor.preflight = lambda: None
            executor.stage_candidate_env = lambda: None

            def create_override() -> None:
                executor.override.parent.mkdir(parents=True, exist_ok=True)
                executor.override.write_text("services: {}\n", encoding="utf-8")
                executor.override_created = True

            executor.prepare_phase_a_override = create_override

            def complete_phase_a() -> None:
                executor.migration_started = True
                executor.legacy_schema_verified = True
                executor.committed = True

            executor.phase_a = complete_phase_a
            executor.phase_b = lambda: None
            executor.stop_phase_b_workers = lambda: True
            executor.quiesce_owned_jobs = lambda: True
            executor.recover_modern_web = Mock(return_value=True)

            status = executor.execute()

            self.assertEqual(status, 23)
            executor.recover_modern_web.assert_called_once_with(read_only=True)
            report = json.loads(executor.report.read_text(encoding="utf-8"))
            self.assertEqual(report["outcome"], "partial")
            self.assertFalse(report["full_schema_verified"])

    def test_verified_full_schema_allows_normal_web_recovery_and_removes_override(self) -> None:
        module = self.executor_module
        with tempfile.TemporaryDirectory(prefix="observed-phase-b-verified-") as name:
            executor = self._make_executor(Path(name))
            executor.preflight = lambda: None
            executor.stage_candidate_env = lambda: None

            def create_override() -> None:
                executor.override.parent.mkdir(parents=True, exist_ok=True)
                executor.override.write_text("services: {}\n", encoding="utf-8")
                executor.override_created = True

            executor.prepare_phase_a_override = create_override

            def complete_phase_a() -> None:
                executor.migration_started = True
                executor.legacy_schema_verified = True
                executor.committed = True

            executor.phase_a = complete_phase_a

            def fail_after_schema() -> None:
                executor.full_schema_verified = True
                raise module.Blocked("OBSERVED_TEST_PHASE_B_METADATA_FAILURE")

            executor.phase_b = fail_after_schema
            executor.stop_phase_b_workers = lambda: True
            executor.quiesce_owned_jobs = lambda: True
            executor.recover_modern_web = Mock(return_value=True)
            executor.restore_old_apps = Mock(side_effect=AssertionError("legacy restore forbidden"))

            status = executor.execute()
            executor.recover_modern_web.assert_called_once_with(read_only=False)
            executor.restore_old_apps.assert_not_called()
            self.assertEqual(status, 23)
            self.assertFalse(executor.override.exists())
            report = json.loads(executor.report.read_text(encoding="utf-8"))
            self.assertTrue(report["full_schema_verified"])
            self.assertFalse(report["readonly_override_retained"])

    def test_phase_b_migration_and_readonly_canonical_check_precede_other_work(self) -> None:
        with tempfile.TemporaryDirectory(prefix="observed-phase-b-order-") as name:
            executor = self._make_executor(Path(name))
            executor.compose_run = Mock(return_value=self.executor_module.Result(0))
            executor.compose_override = Mock(return_value=self.executor_module.Result(0))

            executor.complete_phase_b_migrations()

            migration_args = executor.compose_run.call_args.args[1:]
            self.assertIn("AGOM_OBSERVED_MIGRATION_PHASE=phase_b", migration_args)
            self.assertEqual(migration_args[-1], "migrator")
            readonly_check_args = executor.compose_override.call_args.args
            self.assertIn("PGOPTIONS=-c default_transaction_read_only=on", readonly_check_args)
            self.assertEqual(readonly_check_args[-2:], ("verify_canonical_schema", "--json"))
            self.assertTrue(executor.phase_b_migration_started)
            self.assertTrue(executor.full_schema_verified)

    def test_phase_a_migrator_is_explicitly_limited_to_deferred_mode(self) -> None:
        with tempfile.TemporaryDirectory(prefix="observed-phase-a-mode-") as name:
            executor = self._make_executor(Path(name))
            executor.compose_run = Mock(return_value=self.executor_module.Result(0))

            executor.apply_phase_a_migrations()

            self.assertTrue(executor.migration_started)
            args = executor.compose_run.call_args.args[1:]
            self.assertIn("AGOM_OBSERVED_MIGRATION_PHASE=phase_a", args)
            self.assertEqual(args[-1], "migrator")

    def test_modern_web_recovery_uses_readonly_override_until_full_schema_is_verified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="observed-phase-b-recovery-mode-") as name:
            executor = self._make_executor(Path(name))
            executor.compose_override = Mock(return_value=self.executor_module.Result(0))
            executor.compose_run = Mock(return_value=self.executor_module.Result(0))
            executor.wait_web = Mock()
            executor.show_identity = Mock()
            executor.candidate_check = Mock()
            executor.infra_compare = Mock()

            self.assertTrue(executor.recover_modern_web(read_only=True))

            executor.compose_override.assert_called_once_with("up", "-d", "--no-deps", "web")
            executor.compose_run.assert_not_called()
            executor.candidate_check.assert_called_once_with("a")
            executor.infra_compare.assert_called_once_with()

            executor.compose_override.reset_mock()
            executor.recover_modern_web(read_only=False)

            executor.compose_run.assert_called_once_with(
                executor.c.release, "up", "-d", "--no-deps", "web"
            )


if __name__ == "__main__":
    unittest.main()
