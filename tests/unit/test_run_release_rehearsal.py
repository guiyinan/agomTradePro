"""Behavioral tests for the candidate-bound S6 orchestration skeleton."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest

from apps.data_center.infrastructure.rehearsal_identity import (
    parse_rehearsal_identities,
    rehearsal_identities_digest,
)
from scripts.build_release_rehearsal_manifest import REQUIRED_SCHEMAS, build_manifest
from scripts.rehearsal_checkpoint import run_lock, seal_container_input_tree
from scripts.run_release_rehearsal import (
    Command,
    CommandResult,
    RehearsalBlocked,
    RehearsalConfig,
    SubprocessRunner,
    _assert_launcher_provenance,
    _invoke,
    _invoke_container_stage,
    bundle_tree_digest,
    run_release_rehearsal,
    verify_evidence_handoff_receipt,
)

CANDIDATE_SHA = "a" * 40
IMAGE_ID = f"sha256:{'c' * 64}"
TRADE_DATE = "2026-09-24"
UNIVERSE_SHA256 = "b" * 64
GITHUB_REPOSITORY = "owner/repository"
GITHUB_RUN_ID = 12345
PROVIDER_IDENTITIES: list[dict[str, object]] = [
    {
        "role": "quote",
        "provider_id": 11,
        "source": "tushare",
        "version": "v1",
        "endpoint_id": "quote.daily",
    },
    {
        "role": "valuation",
        "provider_id": 12,
        "source": "tushare",
        "version": "v1",
        "endpoint_id": "quote.daily_basic",
    },
]


class FakeRunner:
    """Create stage outputs at the real filesystem boundaries and record order."""

    def __init__(
        self,
        *,
        fail_label: str | None = None,
        wrong_identity_label: str | None = None,
        mutate_bundle_on_validation: bool = False,
        dirty_worktree: bool = False,
        mutate_settings_on_build: Path | None = None,
    ) -> None:
        self.fail_label = fail_label
        self.wrong_identity_label = wrong_identity_label
        self.mutate_bundle_on_validation = mutate_bundle_on_validation
        self.dirty_worktree = dirty_worktree
        self.mutate_settings_on_build = mutate_settings_on_build
        self.commands: list[Command] = []

    def run(self, command: Command) -> CommandResult:
        """Simulate Git, Docker, producer, bundle and validator commands."""
        self.commands.append(command)
        if command.label == self.fail_label:
            return CommandResult(returncode=2, stderr="private provider detail")
        if command.label == "git_head":
            return CommandResult(returncode=0, stdout=f"{CANDIDATE_SHA}\n")
        if command.label == "git_status":
            dirty = self.dirty_worktree
            return CommandResult(returncode=0, stdout=" M changed.py\n" if dirty else "")
        if command.label == "build_only":
            self._create_build_artifacts(command)
            if self.mutate_settings_on_build is not None:
                self.mutate_settings_on_build.write_text('{"status":"replaced"}\n')
        elif command.label == "docker_inspect":
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "Id": IMAGE_ID,
                        "Config": {"Labels": {"org.opencontainers.image.revision": CANDIDATE_SHA}},
                    }
                ),
            )
        elif command.label == "docker_gid":
            gid = os.getgid() if hasattr(os, "getgid") else 1000
            return CommandResult(returncode=0, stdout=f"{gid}\n")
        elif command.label == "preflight_isolated_database_container":
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "id": "f" * 64,
                        "name": "/agom-s6-pg-abcdefghij",
                        "running": True,
                        "networks": {
                            "agomtradepro_rehearsal": {
                                "Aliases": ["agom-s6-postgres-abcdefghij"],
                                "DNSNames": [
                                    "agom-s6-pg-abcdefghij",
                                    "agom-s6-postgres-abcdefghij",
                                ],
                            }
                        },
                    }
                ),
            )
        elif command.label == "preflight_isolated_redis_container":
            return CommandResult(
                returncode=0,
                stdout=json.dumps(
                    {
                        "id": "e" * 64,
                        "name": "/agom-s6-redis-abcdefghij",
                        "running": True,
                        "networks": {
                            "agomtradepro_rehearsal": {
                                "Aliases": ["agom-s6-redis-abcdefghij"],
                                "DNSNames": ["agom-s6-redis-abcdefghij"],
                            }
                        },
                    }
                ),
            )
        elif command.label == "github_ci_evidence":
            assert command.artifact_dir is not None
            output_dir = Path(command.argv[command.argv.index("--output-dir") + 1])
            assert output_dir == command.artifact_dir
            if command.artifact_dir.exists():
                return CommandResult(
                    returncode=2,
                    stderr="blocked: REHEARSAL_OUTPUT_DIRECTORY_EXISTS",
                )
            self._create_stage_report(command)
        elif command.label in {
            "provider_probe",
            "response_replay",
            "full_universe_capacity",
            "production_policy_parity",
            "isolated_postgresql_write",
            "akshare_financial_slice",
        }:
            self._create_stage_report(command)
        elif command.label == "bundle_build":
            self._create_bundle(command)
        elif command.label == "release_validator" and self.mutate_bundle_on_validation:
            assert command.artifact_dir is not None
            manifest_path = command.artifact_dir / "release-rehearsal-manifest.json"
            manifest_path.chmod(0o644)
            manifest_path.write_bytes(manifest_path.read_bytes() + b" ")
        return CommandResult(returncode=0)

    @property
    def labels(self) -> list[str]:
        """Return command labels in execution order."""
        return [command.label for command in self.commands]

    def _create_build_artifacts(self, command: Command) -> None:
        assert command.artifact_dir is not None
        report_dir = Path(command.argv[command.argv.index("--report-dir") + 1])
        image_dir = Path(command.argv[command.argv.index("--built-image-dir") + 1])
        source_sha = command.argv[command.argv.index("--expected-source-commit") + 1]
        release_tag = "20260925123045"
        image_tag = f"agomtradepro-web:{release_tag}"
        report_dir.mkdir(parents=True, exist_ok=True)
        image_dir.mkdir(parents=True, exist_ok=True)
        (report_dir / f"remote-build-report-{release_tag}.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "release_tag": release_tag,
                    "source_commit": source_sha,
                    "image_tag": image_tag,
                    "image_id": IMAGE_ID,
                    "source_mode": "source-upload",
                    "build_started_at": "2026-09-25T04:30:00Z",
                    "build_finished_at": "2026-09-25T04:31:00Z",
                }
            ),
            encoding="utf-8",
        )
        (image_dir / f"agomtradepro-web-{release_tag}.tar").write_bytes(b"fake docker image")

    def _create_stage_report(self, command: Command) -> None:
        assert command.artifact_dir is not None
        image_value = command.env.get("AGOM_CANDIDATE_IMAGE_ID", IMAGE_ID)
        if "--provider-identities-sha256" in command.argv:
            provider_digest = command.argv[command.argv.index("--provider-identities-sha256") + 1]
        elif "--provider-identities-json" in command.argv:
            provider_values = json.loads(
                Path(command.argv[command.argv.index("--provider-identities-json") + 1]).read_text(
                    encoding="utf-8"
                )
            )
            provider_digest = rehearsal_identities_digest(
                parse_rehearsal_identities(provider_values)
            )
        else:
            try:
                provider_values = json.loads(
                    self._mounted_path(
                        command.argv,
                        target="/run/agom/provider-identities.json",
                    ).read_text(encoding="utf-8")
                )
                provider_digest = rehearsal_identities_digest(
                    parse_rehearsal_identities(provider_values)
                )
            except AssertionError:
                provider_digest = _provider_digest()
        if command.label == self.wrong_identity_label:
            image_value = f"sha256:{'d' * 64}"
        filenames = {
            "provider_probe": "probe.json",
            "response_replay": "output/real-response-unit-replay.json",
            "full_universe_capacity": "output/full-universe-capacity.json",
            "production_policy_parity": "output/production-policy-parity.json",
            "isolated_postgresql_write": "output/isolated-write-rehearsal.json",
            "github_ci_evidence": "candidate-regression-evidence.json",
            "akshare_financial_slice": "output/akshare-financial-slice.json",
        }
        kinds = {
            "response_replay": "real_response_unit_replay",
            "full_universe_capacity": "full_universe_capacity",
            "production_policy_parity": "production_policy_parity",
            "isolated_postgresql_write": "isolated_write_rehearsal",
            "github_ci_evidence": "candidate_regression_evidence",
            "akshare_financial_slice": "akshare_financial_slice",
        }
        payload: dict[str, object] = {
            "outcome": "success",
            "candidate_sha": CANDIDATE_SHA,
            "target_trade_date": TRADE_DATE,
            "universe_sha256": UNIVERSE_SHA256,
            "provider_identities_sha256": provider_digest,
        }
        if command.label == "production_policy_parity":
            payload["provider_identities"] = json.loads(
                self._mounted_path(
                    command.argv,
                    target="/run/agom/provider-identities.json",
                ).read_text(encoding="utf-8")
            )
            payload["provider_settings"] = json.loads(
                self._provider_settings_path(command.argv).read_text(encoding="utf-8")
            )
            payload["provider_settings_raw_file_sha256"] = command.argv[
                command.argv.index("--expected-provider-settings-raw-file-sha256") + 1
            ]
            payload["provider_settings_canonical_payload_sha256"] = command.argv[
                command.argv.index("--expected-provider-settings-canonical-payload-sha256") + 1
            ]
            payload["preflight"] = {
                "name": "provider_policy_and_routes",
                "status": "pass",
                "blocked_codes": [],
                "detail": "",
                "evidence": {
                    "provider_settings_sha256": payload[
                        "provider_settings_canonical_payload_sha256"
                    ],
                    "preferred_route": "tushare",
                    "probe_asset_count": 2,
                    "route_capabilities": [
                        {
                            "route": "tushare",
                            "source_type": "tushare",
                            "provider_id": 11,
                            "batch_preparation": True,
                            "audited_per_asset_fetch": False,
                            "provider_identity": True,
                        }
                    ],
                },
            }
        if command.label != "github_ci_evidence":
            payload["candidate_image_id"] = image_value
        if command.label == "provider_probe":
            payload["schema"] = "market.provider-rehearsal.v1"
            payload["response_retention_enabled"] = True
        else:
            kind = kinds[command.label]
            payload["kind"] = kind
            payload["schema"] = REQUIRED_SCHEMAS[kind]
            payload["evidence_mode"] = {
                "response_replay": "real_provider",
                "full_universe_capacity": "measured_full_universe",
                "production_policy_parity": "production_policy_snapshot",
                "isolated_postgresql_write": "isolated_postgresql",
                "github_ci_evidence": "candidate_ci",
                "akshare_financial_slice": "isolated_postgresql_redis_real_provider",
            }[command.label]
        report_path = command.artifact_dir / filenames[command.label]
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def _create_bundle(self, command: Command) -> None:
        args = command.argv
        report_paths = {
            kind: Path(args[args.index(option) + 1])
            for kind, option in {
                "real_response_unit_replay": "--real-response-unit-replay",
                "full_universe_capacity": "--full-universe-capacity",
                "production_policy_parity": "--production-policy-parity",
                "isolated_write_rehearsal": "--isolated-write-rehearsal",
                "akshare_financial_slice": "--akshare-financial-slice",
                "candidate_regression_evidence": "--candidate-regression-evidence",
            }.items()
        }
        output_dir = Path(args[args.index("--output-dir") + 1])
        build_manifest(
            reports=report_paths,
            output_dir=output_dir,
            candidate_sha=args[args.index("--candidate-sha") + 1],
            target_trade_date=args[args.index("--target-trade-date") + 1],
            universe_sha256=args[args.index("--universe-sha256") + 1],
            provider_identities_sha256=args[args.index("--provider-identities-sha256") + 1],
            provider_settings_raw_file_sha256=(
                args[args.index("--provider-settings-raw-file-sha256") + 1]
            ),
            provider_settings_canonical_payload_sha256=(
                args[args.index("--provider-settings-canonical-payload-sha256") + 1]
            ),
            candidate_image_id=args[args.index("--candidate-image-id") + 1],
        )

    @staticmethod
    def _provider_settings_path(argv: tuple[str, ...]) -> Path:
        return FakeRunner._mounted_path(argv, target="/run/agom/provider-settings.json")

    @staticmethod
    def _mounted_path(argv: tuple[str, ...], *, target: str) -> Path:
        suffix = f":{target}:ro"
        for index, value in enumerate(argv):
            if value == "--volume" and argv[index + 1].endswith(suffix):
                return Path(argv[index + 1][: -len(suffix)])
        raise AssertionError(f"snapshot mount is missing: {target}")


def _provider_digest() -> str:
    identities = parse_rehearsal_identities(PROVIDER_IDENTITIES)
    return rehearsal_identities_digest(identities)


def _config(tmp_path: Path, *, root: Path) -> RehearsalConfig:
    """Create isolated input files for a fake-only rehearsal test."""
    provider_path = tmp_path / "provider-identities.json"
    provider_path.write_text(json.dumps(PROVIDER_IDENTITIES), encoding="utf-8")
    unit_path = tmp_path / "unit-contract.json"
    unit_path.write_text(
        json.dumps(
            {
                "schema": "release.provider-unit-contract.v1",
                "candidate_sha": CANDIDATE_SHA,
                "provider_identities_sha256": _provider_digest(),
                "datasets": {},
                "source_reference": "unit-test-provider-contract",
            }
        ),
        encoding="utf-8",
    )
    settings_path = tmp_path / "provider-settings.json"
    settings_path.write_text(
        json.dumps(
            {
                "status": "active",
                "default_source": "tushare",
                "enable_failover": True,
                "failover_tolerance": 0.01,
            }
        ),
        encoding="utf-8",
    )
    password_path = tmp_path / "password.txt"
    password_path.write_text("not-a-real-secret", encoding="utf-8")
    provider_env = tmp_path / "provider.env"
    provider_env.write_text("DJANGO_SETTINGS_MODULE=config.settings\n", encoding="utf-8")
    isolated_env = tmp_path / "isolated.env"
    isolated_env.write_text(
        "POSTGRES_HOST=agom-s6-postgres-abcdefghij\n"
        "POSTGRES_DB=agom_release_rehearsal_abcdefghij\n"
        "DATABASE_URL=postgresql://user:not-a-real-secret@"
        "agom-s6-postgres-abcdefghij/agom_release_rehearsal_abcdefghij\n"
        "MIGRATOR_DATABASE_URL=postgresql://migrator:not-a-real-secret@"
        "agom-s6-postgres-abcdefghij/agom_release_rehearsal_abcdefghij\n"
        "REDIS_HOST=agom-s6-redis-abcdefghij\n"
        "REDIS_URL=redis://:not-a-real-secret@agom-s6-redis-abcdefghij:6379/0\n"
        "AGOM_RELEASE_REHEARSAL_DATABASE=1\n",
        encoding="utf-8",
    )
    return RehearsalConfig(
        root=root,
        output_dir=tmp_path / "rehearsal-run",
        build_host="builder.example.invalid",
        build_user="builder",
        password_file=password_path,
        target_trade_date=TRADE_DATE,
        universe_sha256=UNIVERSE_SHA256,
        provider_identities_path=provider_path,
        provider_settings_json=settings_path,
        unit_contract_path=unit_path,
        quote_provider_id=11,
        valuation_provider_id=12,
        provider_env_file=provider_env,
        isolated_postgres_env_file=isolated_env,
        docker_network="agomtradepro_rehearsal",
        isolated_database_name="agom_release_rehearsal_abcdefghij",
        isolated_database_host="agom-s6-postgres-abcdefghij",
        isolated_database_container="agom-s6-pg-abcdefghij",
        isolated_redis_host="agom-s6-redis-abcdefghij",
        isolated_redis_container="agom-s6-redis-abcdefghij",
        provider_request_limit=100,
        provider_window_seconds=60.0,
        task_deadline_seconds=900.0,
        lock_wait_limit_seconds=10.0,
        github_repository=GITHUB_REPOSITORY,
        github_run_id=GITHUB_RUN_ID,
    )


def test_launcher_must_come_from_selected_checkout(tmp_path: Path) -> None:
    root = _fake_checkout(tmp_path)
    selected = root / "scripts" / "run_release_rehearsal.py"
    selected.parent.mkdir()
    selected.write_text("# selected launcher\n", encoding="utf-8")
    copied = tmp_path / "copied-old-launcher.py"
    copied.write_text("# stale launcher\n", encoding="utf-8")

    _assert_launcher_provenance(root, launcher_path=selected)
    with pytest.raises(RehearsalBlocked, match="S6_LAUNCHER_PROVENANCE_INVALID"):
        _assert_launcher_provenance(root, launcher_path=copied)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("POSTGRES_HOST=agom-s6-postgres-abcdefghij", "POSTGRES_HOST=old-postgres"),
        (
            "agom-s6-postgres-abcdefghij/agom_release_rehearsal_abcdefghij",
            "old-postgres/old_database",
        ),
        ("POSTGRES_DB=agom_release_rehearsal_abcdefghij", "POSTGRES_DB=old_database"),
        ("REDIS_HOST=agom-s6-redis-abcdefghij", "REDIS_HOST=old-redis"),
        ("agom-s6-redis-abcdefghij:6379/0", "old-redis:6379/0"),
        ("AGOM_RELEASE_REHEARSAL_DATABASE=1", "AGOM_RELEASE_REHEARSAL_DATABASE=0"),
    ],
)
def test_isolated_environment_identity_mismatch_blocks_before_build(
    tmp_path: Path, old: str, new: str
) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    raw = config.isolated_postgres_env_file.read_text(encoding="utf-8")
    config.isolated_postgres_env_file.write_text(raw.replace(old, new), encoding="utf-8")
    runner = FakeRunner()

    with pytest.raises(RehearsalBlocked, match="S6_ISOLATED_ENV_IDENTITY_MISMATCH") as error:
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels
    assert "not-a-real-secret" not in str(error.value)


def test_duplicate_isolated_environment_key_fails_closed_without_secret_leak(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with config.isolated_postgres_env_file.open("a", encoding="utf-8") as stream:
        stream.write("REDIS_HOST=redis://duplicate:private-secret@old-redis\n")
    runner = FakeRunner()

    with pytest.raises(RehearsalBlocked, match="S6_ISOLATED_ENV_INVALID") as error:
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels
    assert "private-secret" not in str(error.value)


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


def test_rehearsal_accepts_frozen_failover_route_identities(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    identities = [
        *PROVIDER_IDENTITIES,
        {
            "role": "model_market_route:31",
            "provider_id": 31,
            "source": "tencent",
            "version": "requests-test",
            "endpoint_id": "provider-config-failover",
        },
    ]
    config.provider_identities_path.write_text(json.dumps(identities), encoding="utf-8")
    digest = rehearsal_identities_digest(parse_rehearsal_identities(identities))
    unit = json.loads(config.unit_contract_path.read_text(encoding="utf-8"))
    unit["provider_identities_sha256"] = digest
    config.unit_contract_path.write_text(json.dumps(unit), encoding="utf-8")

    receipt = run_release_rehearsal(config, runner=FakeRunner())

    assert verify_evidence_handoff_receipt(receipt)["provider_identities_sha256"] == digest


@pytest.mark.parametrize(
    "failed_stage",
    [
        "docker_load",
        "provider_probe",
        "response_replay",
        "full_universe_capacity",
        "production_policy_parity",
        "isolated_postgresql_write",
        "github_ci_evidence",
        "akshare_financial_slice",
        "bundle_build",
        "release_validator",
    ],
)
def test_resume_reuses_verified_prefix_without_rebuilding(
    tmp_path: Path, failed_stage: str
) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    first = FakeRunner(fail_label=failed_stage)
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=first)
    second = FakeRunner()
    receipt = run_release_rehearsal(replace(config, resume=True), runner=second)
    assert verify_evidence_handoff_receipt(receipt)["candidate_sha"] == CANDIDATE_SHA
    assert "build_only" not in second.labels
    assert failed_stage in second.labels
    stages = [
        "provider_probe",
        "response_replay",
        "full_universe_capacity",
        "production_policy_parity",
        "isolated_postgresql_write",
        "github_ci_evidence",
        "akshare_financial_slice",
        "bundle_build",
        "release_validator",
    ]
    if failed_stage in stages:
        assert not set(stages[: stages.index(failed_stage)]) & set(second.labels)


def test_resume_rejects_changed_artifact_before_commands(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=FakeRunner(fail_label="response_replay"))
    probe = config.output_dir / "provider-probe" / "probe.json"
    probe.write_bytes(probe.read_bytes() + b" ")
    runner = FakeRunner()
    with pytest.raises(RehearsalBlocked, match="S6_CHECKPOINT_ARTIFACT_CHANGED"):
        run_release_rehearsal(replace(config, resume=True), runner=runner)
    assert "build_only" not in runner.labels
    assert "provider_probe" not in runner.labels


def test_resume_rejects_checkpoint_copied_to_another_output_directory(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=FakeRunner(fail_label="provider_probe"))
    copied = tmp_path / "copied-rehearsal-run"
    shutil.copytree(config.output_dir, copied)
    runner = FakeRunner()

    with pytest.raises(RehearsalBlocked, match="S6_CHECKPOINT_INPUT_CHANGED"):
        run_release_rehearsal(replace(config, output_dir=copied, resume=True), runner=runner)

    assert "build_only" not in runner.labels
    assert "provider_probe" not in runner.labels


@pytest.mark.parametrize(
    "change", ["env", "budget", "scope", "ci", "provider_timeout", "outer_timeout"]
)
def test_resume_rejects_input_drift(tmp_path: Path, change: str) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=FakeRunner(fail_label="provider_probe"))
    if change == "env":
        config.provider_env_file.write_text("CHANGED=1\n", encoding="utf-8")
    elif change == "budget":
        config = replace(config, max_dispatches=101)
    elif change == "scope":
        config = replace(config, universe_sha256="e" * 64)
    elif change == "ci":
        config = replace(config, github_run_id=54321)
    elif change == "provider_timeout":
        config = replace(config, provider_probe_timeout_seconds=1801)
    else:
        config = replace(config, stage_timeout_seconds=3601)
    with pytest.raises(RehearsalBlocked, match="S6_CHECKPOINT_INPUT_CHANGED"):
        run_release_rehearsal(replace(config, resume=True), runner=FakeRunner())


@pytest.mark.parametrize(
    "label",
    [
        "preflight_docker",
        "preflight_network",
        "preflight_isolated_database_container",
        "preflight_isolated_redis_container",
    ],
)
def test_environment_failure_precedes_expensive_build(tmp_path: Path, label: str) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = FakeRunner(fail_label=label)
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=runner)
    assert "build_only" not in runner.labels


def test_database_container_must_be_running_on_the_selected_network(tmp_path: Path) -> None:
    class WrongNetworkRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            if command.label == "preflight_isolated_database_container":
                self.commands.append(command)
                return CommandResult(
                    returncode=0,
                    stdout=json.dumps(
                        {
                            "id": "f" * 64,
                            "name": "/agom-s6-pg-abcdefghij",
                            "running": True,
                            "networks": {"unexpected-network": {}},
                        }
                    ),
                )
            return super().run(command)

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = WrongNetworkRunner()

    with pytest.raises(RehearsalBlocked, match="S6_ISOLATED_DATABASE_CONTAINER_INVALID"):
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels


def test_database_container_replacement_blocks_isolated_write(tmp_path: Path) -> None:
    class ReplacedContainerRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.container_inspections = 0

        def run(self, command: Command) -> CommandResult:
            result = super().run(command)
            if command.label == "preflight_isolated_database_container":
                self.container_inspections += 1
                if self.container_inspections == 3:
                    payload = json.loads(result.stdout)
                    payload["id"] = "e" * 64
                    return CommandResult(returncode=0, stdout=json.dumps(payload))
            return result

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = ReplacedContainerRunner()

    with pytest.raises(RehearsalBlocked, match="S6_ISOLATED_DATABASE_CONTAINER_CHANGED"):
        run_release_rehearsal(config, runner=runner)

    # The container identity recheck runs before the parallel group starts.
    assert "response_replay" not in runner.labels
    assert "full_universe_capacity" not in runner.labels
    assert "production_policy_parity" not in runner.labels
    assert "isolated_postgresql_write" not in runner.labels


def test_database_preflight_precedes_provider_and_is_read_only(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = FakeRunner(fail_label="preflight_database")
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=runner)
    assert "provider_probe" not in runner.labels
    assert "isolated_postgresql_write" not in runner.labels


def test_provider_stages_override_stale_provider_database_with_isolated_env(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    config.provider_env_file.write_text(
        "DATABASE_URL=postgresql://user:secret@old-db/old_rehearsal\n",
        encoding="utf-8",
    )
    runner = FakeRunner()

    run_release_rehearsal(config, runner=runner)

    def env_files(label: str) -> list[Path]:
        command = next(item for item in runner.commands if item.label == label)
        return [
            Path(command.argv[index + 1])
            for index, value in enumerate(command.argv)
            if value == "--env-file"
        ]

    provider_then_isolated = [
        config.provider_env_file.resolve(),
        config.isolated_postgres_env_file.resolve(),
    ]
    for label in (
        "provider_probe",
        "response_replay",
        "full_universe_capacity",
        "production_policy_parity",
    ):
        assert env_files(label) == provider_then_isolated
    assert env_files("preflight_database") == provider_then_isolated
    assert env_files("isolated_postgresql_write") == [config.isolated_postgres_env_file.resolve()]


def test_missing_isolated_environment_fails_closed_before_build(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    config.isolated_postgres_env_file.unlink()
    runner = FakeRunner()

    with pytest.raises(RehearsalBlocked, match="S6_INPUT_OR_ARTIFACT_INVALID"):
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels


def test_outer_stage_timeout_does_not_expand_provider_probe_budget(tmp_path: Path) -> None:
    config = replace(
        _config(tmp_path, root=_fake_checkout(tmp_path)),
        stage_timeout_seconds=3600,
        provider_probe_timeout_seconds=1800,
    )
    runner = FakeRunner()

    run_release_rehearsal(config, runner=runner)

    probe = next(command for command in runner.commands if command.label == "provider_probe")
    assert probe.timeout_seconds == 3600
    assert probe.argv[probe.argv.index("--max-seconds") + 1] == "1800"


def test_database_preflight_executes_existing_scope_guard_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from django.core.management.base import CommandError

    from apps.data_center.infrastructure import isolated_write_rehearsal_runner as isolated
    from core.exceptions import DataFetchError

    observed: list[dict[str, object]] = []

    def guard(**kwargs: object) -> tuple[str, str, str]:
        observed.append(kwargs)
        raise DataFetchError("private detail", code="REHEARSAL_WRITE_MIGRATIONS_PENDING")

    monkeypatch.setattr(isolated, "preflight_isolated_write_rehearsal", guard)
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = FakeRunner(fail_label="preflight_database")
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=runner)
    command = next(c for c in runner.commands if c.label == "preflight_database")
    code = command.argv[command.argv.index("-c") + 1]
    with pytest.raises(CommandError, match="^REHEARSAL_WRITE_MIGRATIONS_PENDING$"):
        exec(compile(code, "<s6-preflight>", "exec"), {})
    assert observed[0]["expected_database_name"] == config.isolated_database_name
    assert observed[0]["expected_database_host"] == config.isolated_database_host
    assert observed[0]["require_ephemeral_host"] is True


def test_resume_keeps_failed_attempt_outputs_and_only_reloads_missing_image(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=FakeRunner(fail_label="provider_probe"))
    failed = config.output_dir / "provider-probe" / "failed-response.json"
    failed.write_text('{"failed": true}', encoding="utf-8")
    runner = FakeRunner(fail_label="docker_image_available")
    run_release_rehearsal(replace(config, resume=True), runner=runner)
    assert "build_only" not in runner.labels
    assert runner.labels.count("docker_load") == 1
    archived = list(
        (config.output_dir / "failed-attempts").glob("*/provider-probe/failed-response.json")
    )
    assert len(archived) == 1
    assert archived[0].read_text(encoding="utf-8") == '{"failed": true}'


@pytest.mark.parametrize("invalid", ["missing", "expired", "future", "active", "prefix"])
def test_resume_rejects_missing_expired_or_active_checkpoint(tmp_path: Path, invalid: str) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    with pytest.raises(RehearsalBlocked):
        run_release_rehearsal(config, runner=FakeRunner(fail_label="provider_probe"))
    path = config.output_dir / "checkpoint.json"
    if invalid == "missing":
        path.unlink()
        expected = "S6_CHECKPOINT_MISSING"
    elif invalid in {"expired", "future"}:
        data = json.loads(path.read_text(encoding="utf-8"))
        offset = timedelta(days=-2 if invalid == "expired" else 2)
        data["stages"]["build_artifacts"]["completed_at"] = (datetime.now(UTC) + offset).isoformat()
        path.write_text(json.dumps(data), encoding="utf-8")
        expected = "S6_CHECKPOINT_EXPIRED"
    elif invalid == "prefix":
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["stages"]["build_only"]
        path.write_text(json.dumps(data), encoding="utf-8")
        expected = "S6_CHECKPOINT_INVALID"
    else:
        with run_lock(config.output_dir):
            with pytest.raises(RehearsalBlocked, match="S6_RUN_ALREADY_ACTIVE"):
                run_release_rehearsal(replace(config, resume=True), runner=FakeRunner())
        # Lock release permits a later resume without deleting a lock file.
        run_release_rehearsal(replace(config, resume=True), runner=FakeRunner())
        return
    with pytest.raises(RehearsalBlocked, match=expected):
        run_release_rehearsal(replace(config, resume=True), runner=FakeRunner())


def test_resume_blocks_orphan_stage_container(tmp_path: Path) -> None:
    class OrphanRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            if command.label == "preflight_containers":
                return CommandResult(0, "container-still-running")
            return super().run(command)

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = OrphanRunner()
    with pytest.raises(RehearsalBlocked, match="S6_RUN_CONTAINERS_ACTIVE"):
        run_release_rehearsal(config, runner=runner)
    assert "build_only" not in runner.labels


def test_process_diagnostics_keep_categories_without_private_output(tmp_path: Path) -> None:
    runner = SubprocessRunner(tmp_path / "diagnostics")
    result = runner.run(
        Command(
            (sys.executable, "-c", "raise PermissionError('secret-token-123')"),
            tmp_path,
            {},
            10,
            "probe",
        )
    )
    assert result.returncode != 0
    reports = [
        path
        for path in (tmp_path / "diagnostics").glob("*.json")
        if path.name != "active-commands.json"
    ]
    assert len(reports) == 2
    for path in reports:
        text = path.read_text(encoding="utf-8")
        assert "secret-token-123" not in text
        assert json.loads(text)["diagnostic_categories"] == ["permission"]
    active = json.loads(
        (tmp_path / "diagnostics" / "active-commands.json").read_text(encoding="utf-8")
    )
    assert active["active_count"] == 0
    assert active["active_commands"] == []


def test_parallel_command_progress_keeps_each_active_invocation_and_heartbeats(
    tmp_path: Path,
) -> None:
    progress_dir = tmp_path / "diagnostics"
    runner = SubprocessRunner(progress_dir)
    results: dict[str, CommandResult] = {}

    def execute(label: str, delay: float) -> None:
        results[label] = runner.run(
            Command(
                (sys.executable, "-c", f"import time; time.sleep({delay})"),
                tmp_path,
                {},
                15,
                label,
            )
        )

    slow = threading.Thread(target=execute, args=("slow", 6.5))
    quick = threading.Thread(target=execute, args=("quick", 0.5))
    slow.start()
    quick.start()

    summary_path = progress_dir / "active-commands.json"
    deadline = time.monotonic() + 5
    summary: dict[str, object] = {}
    while time.monotonic() < deadline:
        if summary_path.exists():
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            if summary.get("active_count") == 2:
                break
        time.sleep(0.02)
    assert summary["active_count"] == 2
    active_commands = cast(list[dict[str, object]], summary["active_commands"])
    assert {item["command"] for item in active_commands} == {"quick", "slow"}
    slow_first_update = next(
        item["updated_at"] for item in active_commands if item["command"] == "slow"
    )

    quick.join(timeout=3)
    assert not quick.is_alive()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["active_count"] == 1
    assert [item["command"] for item in summary["active_commands"]] == ["slow"]

    deadline = time.monotonic() + 7
    while time.monotonic() < deadline:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        active_commands = cast(list[dict[str, object]], summary["active_commands"])
        if active_commands and active_commands[0]["updated_at"] != slow_first_update:
            break
        time.sleep(0.05)
    assert active_commands[0]["updated_at"] != slow_first_update

    slow.join(timeout=4)
    assert not slow.is_alive()
    assert results["quick"].returncode == 0
    assert results["slow"].returncode == 0
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["active_count"] == 0
    assert summary["active_commands"] == []
    histories = list(progress_dir.glob("quick-*.json")) + list(progress_dir.glob("slow-*.json"))
    assert len(histories) == 2


def test_parallel_subprocess_progress_keeps_each_active_command_until_it_finishes(
    tmp_path: Path,
) -> None:
    runner = SubprocessRunner(tmp_path / "diagnostics")
    start_barrier = threading.Barrier(3)
    releases = {name: tmp_path / f"release-{name}" for name in ("first", "second")}
    ready = {name: tmp_path / f"ready-{name}" for name in ("first", "second")}
    completed = {name: threading.Event() for name in ("first", "second")}
    results: dict[str, CommandResult] = {}
    secret = "progress-secret-sentinel"

    def command_for(name: str) -> Command:
        source = (
            "from pathlib import Path\n"
            "import time\n"
            f"Path({str(ready[name])!r}).write_text('ready')\n"
            f"release = Path({str(releases[name])!r})\n"
            "deadline = time.monotonic() + 8\n"
            "while not release.exists() and time.monotonic() < deadline:\n"
            "    time.sleep(0.01)\n"
            f"print({secret!r})\n"
        )
        return Command(
            (sys.executable, "-c", source, "private-argv-sentinel"),
            tmp_path,
            {"PRIVATE_ENV_SENTINEL": "private-env-sentinel"},
            12,
            "parallel",
        )

    def execute(name: str) -> None:
        start_barrier.wait(timeout=5)
        results[name] = runner.run(command_for(name))
        completed[name].set()

    workers = [threading.Thread(target=execute, args=(name,)) for name in releases]
    for worker in workers:
        worker.start()
    start_barrier.wait(timeout=5)

    active_dir = tmp_path / "diagnostics" / "active-commands"

    def wait_until(predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert predicate()

    try:
        wait_until(lambda: all(path.exists() for path in ready.values()))
        wait_until(lambda: len(list(active_dir.glob("*.json"))) == 2)
        initial_active_paths = set(active_dir.glob("*.json"))
        active_payloads = [
            json.loads(path.read_text(encoding="utf-8")) for path in initial_active_paths
        ]
        assert {payload["outcome"] for payload in active_payloads} == {"running"}
        assert {payload["command"] for payload in active_payloads} == {"parallel"}

        releases["first"].touch()
        assert completed["first"].wait(timeout=5)
        remaining_active_paths = set(active_dir.glob("*.json"))
        assert len(remaining_active_paths) == 1
        assert remaining_active_paths.issubset(initial_active_paths)
        assert (
            json.loads(next(iter(remaining_active_paths)).read_text(encoding="utf-8"))["outcome"]
            == "running"
        )

        releases["second"].touch()
        assert completed["second"].wait(timeout=5)
    finally:
        for release_path in releases.values():
            release_path.touch()
        for worker in workers:
            worker.join(timeout=5)

    assert all(not worker.is_alive() for worker in workers)
    assert all(result.returncode == 0 for result in results.values())
    assert list(active_dir.glob("*.json")) == []
    history_paths = list((tmp_path / "diagnostics").glob("parallel-*.json"))
    assert len(history_paths) == 2
    assert {json.loads(path.read_text(encoding="utf-8"))["outcome"] for path in history_paths} == {
        "success"
    }
    persisted = "\n".join(
        path.read_text(encoding="utf-8") for path in (tmp_path / "diagnostics").glob("*.json")
    )
    assert secret not in persisted
    assert "private-argv-sentinel" not in persisted
    assert "private-env-sentinel" not in persisted
    current = json.loads(
        (tmp_path / "diagnostics" / "current-command.json").read_text(encoding="utf-8")
    )
    assert current["outcome"] == "success"


def test_process_timeout_is_distinct_and_has_terminal_progress(tmp_path: Path) -> None:
    runner = SubprocessRunner(tmp_path / "diagnostics")
    with pytest.raises(RehearsalBlocked, match="S6_STAGE_TIMEOUT"):
        _invoke(
            runner,
            argv=(sys.executable, "-c", "import time; time.sleep(10)"),
            root=tmp_path,
            label="probe",
            timeout=0.3,
        )
    progress = json.loads(
        (tmp_path / "diagnostics" / "current-command.json").read_text(encoding="utf-8")
    )
    assert progress["outcome"] == "timed_out"
    assert progress["returncode"] == 124


def test_subprocess_runner_cancel_stops_active_process_group(tmp_path: Path) -> None:
    marker = tmp_path / "started.txt"
    runner = SubprocessRunner(tmp_path / "diagnostics")
    results: list[CommandResult] = []

    def execute() -> None:
        results.append(
            runner.run(
                Command(
                    (
                        sys.executable,
                        "-c",
                        (
                            "from pathlib import Path; import time; "
                            f"Path({str(marker)!r}).write_text('started'); time.sleep(60)"
                        ),
                    ),
                    tmp_path,
                    {},
                    120,
                    "probe",
                )
            )
        )

    worker = threading.Thread(target=execute)
    worker.start()
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert marker.exists()

    runner.cancel()
    worker.join(timeout=10)

    assert not worker.is_alive()
    assert [result.returncode for result in results] == [130]
    reports = list((tmp_path / "diagnostics").glob("probe-*.json"))
    assert reports
    assert json.loads(reports[-1].read_text(encoding="utf-8"))["outcome"] == "interrupted"


def test_parallel_operator_interrupt_cancels_runner_and_updates_status(tmp_path: Path) -> None:
    class InterruptingRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_called = False

        def run(self, command: Command) -> CommandResult:
            if command.label == "response_replay":
                self.commands.append(command)
                raise KeyboardInterrupt
            return super().run(command)

        def cancel(self) -> None:
            self.cancel_called = True

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = InterruptingRunner()

    with pytest.raises(KeyboardInterrupt):
        run_release_rehearsal(config, runner=runner)

    assert runner.cancel_called is True
    status = json.loads((config.output_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "interrupted"
    assert status["error_code"] == "S6_RUN_INTERRUPTED"
    assert status["current_stage"] == "response_replay"
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()


def test_preflight_operator_interrupt_updates_status(tmp_path: Path) -> None:
    class InterruptingRunner(FakeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.cancel_called = False

        def run(self, command: Command) -> CommandResult:
            if command.label == "preflight_docker":
                raise KeyboardInterrupt
            return super().run(command)

        def cancel(self) -> None:
            self.cancel_called = True

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = InterruptingRunner()

    with pytest.raises(KeyboardInterrupt):
        run_release_rehearsal(config, runner=runner)

    assert runner.cancel_called is True
    status = json.loads((config.output_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status == {
        "schema": "release.rehearsal-launch-status.v1",
        "outcome": "interrupted",
        "completed_stages": [],
        "current_stage": "preflight",
        "error_code": "S6_RUN_INTERRUPTED",
        "updated_at": status["updated_at"],
    }


def test_rehearsal_runs_ordered_stages_and_emits_non_authorizing_evidence_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chmod_calls: dict[str, list[int]] = {}
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int) -> None:
        chmod_calls.setdefault(path.name, []).append(mode)
        original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", record_chmod)
    runner = FakeRunner()
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    receipt_path = run_release_rehearsal(config, runner=runner)

    assert runner.labels.count("build_only") == 1
    assert runner.labels.index("build_only") < runner.labels.index("docker_load")
    assert runner.labels.index("docker_load") < runner.labels.index("docker_inspect")
    expected_stages = [
        "provider_probe",
        "response_replay",
        "full_universe_capacity",
        "production_policy_parity",
        "isolated_postgresql_write",
        "github_ci_evidence",
        "akshare_financial_slice",
        "bundle_build",
        "release_validator",
    ]
    observed_stages = [label for label in runner.labels if label in expected_stages]
    assert observed_stages[0] == "provider_probe"
    assert observed_stages[1] == "full_universe_capacity"
    # The remaining group members run concurrently after capacity measurement.
    assert set(observed_stages[2:5]) == {
        "response_replay",
        "production_policy_parity",
        "isolated_postgresql_write",
    }
    assert observed_stages[5:] == [
        "github_ci_evidence",
        "akshare_financial_slice",
        "bundle_build",
        "release_validator",
    ]
    assert "deploy" not in runner.labels
    provider_command = next(item for item in runner.commands if item.label == "provider_probe")
    target_index = provider_command.argv.index("--target-trade-date")
    assert provider_command.argv[target_index + 1] == TRADE_DATE
    for label in expected_stages[:5]:
        command = next(item for item in runner.commands if item.label == label)
        assert command.env["AGOM_CANDIDATE_IMAGE_ID"] == IMAGE_ID
        assert command.env["AGOM_RELEASE_MANIFEST_PATH"].endswith("candidate-release-manifest.json")
        assert IMAGE_ID in command.argv
        if label != "provider_probe":
            output_index = command.argv.index("--output-dir")
            assert command.argv[output_index + 1] == "/run/agom/stage/output"
            assert (command.artifact_dir / "output").is_dir()
    isolated_command = next(
        item for item in runner.commands if item.label == "isolated_postgresql_write"
    )
    assert "--initialize-reviewed-catalog" in isolated_command.argv
    parity_command = next(
        item for item in runner.commands if item.label == "production_policy_parity"
    )
    assert "/run/agom/provider-settings.json" in parity_command.argv
    assert "/run/agom/provider-identities.json" in parity_command.argv
    receipt = verify_evidence_handoff_receipt(receipt_path)
    assert receipt["candidate_sha"] == CANDIDATE_SHA
    assert receipt["candidate_image_id"] == IMAGE_ID
    assert receipt["github_run_id"] == GITHUB_RUN_ID
    assert receipt["deployable"] is False
    assert receipt["receipt_status"] == "evidence_complete"
    assert receipt["bundle_tree_sha256"] == bundle_tree_digest(
        Path(cast(str, receipt["bundle_dir"]))
    )
    identity_path = config.output_dir / "inputs" / "candidate-identity.json"
    assert identity_path.stat().st_mode & 0o222 == 0
    manifest = json.loads(
        (config.output_dir / "inputs" / "candidate-release-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["candidate_image_id"] == IMAGE_ID
    assert manifest["target_trade_date"] == TRADE_DATE
    assert manifest["universe_sha256"] == UNIVERSE_SHA256
    raw_settings = config.provider_settings_json.read_bytes()
    canonical_settings = json.dumps(
        json.loads(raw_settings), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    settings_identity = json.loads(identity_path.read_text(encoding="utf-8"))
    assert (
        settings_identity["provider_settings_raw_file_sha256"]
        == hashlib.sha256(raw_settings).hexdigest()
    )
    assert (
        settings_identity["provider_settings_canonical_payload_sha256"]
        == hashlib.sha256(canonical_settings).hexdigest()
    )
    assert (
        manifest["provider_settings_raw_file_sha256"]
        == settings_identity["provider_settings_raw_file_sha256"]
    )
    assert (
        manifest["provider_settings_canonical_payload_sha256"]
        == settings_identity["provider_settings_canonical_payload_sha256"]
    )
    frozen_settings = config.output_dir / "inputs" / "provider-settings.json"
    assert frozen_settings.stat().st_mode & 0o222 == 0
    assert (
        receipt["provider_settings_raw_file_sha256"]
        == settings_identity["provider_settings_raw_file_sha256"]
    )
    assert (
        receipt["provider_settings_canonical_payload_sha256"]
        == settings_identity["provider_settings_canonical_payload_sha256"]
    )
    for directory in (
        "provider-probe",
        "response-replay",
        "full-universe-capacity",
        "production-policy-parity",
        "isolated-postgresql",
    ):
        writable_mode = 0o2770 if os.name == "posix" else 0o770
        assert chmod_calls[directory] == [writable_mode, 0o750]


def test_parity_mount_uses_startup_copy_after_external_snapshot_changes(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    startup_bytes = config.provider_settings_json.read_bytes()
    runner = FakeRunner(mutate_settings_on_build=config.provider_settings_json)

    run_release_rehearsal(config, runner=runner)

    parity_command = next(
        item for item in runner.commands if item.label == "production_policy_parity"
    )
    mounted_snapshot = runner._provider_settings_path(parity_command.argv)
    assert mounted_snapshot == config.output_dir / "inputs" / "provider-settings.json"
    assert mounted_snapshot.read_bytes() == startup_bytes
    assert config.provider_settings_json.read_bytes() != startup_bytes
    expected_raw = parity_command.argv[
        parity_command.argv.index("--expected-provider-settings-raw-file-sha256") + 1
    ]
    assert expected_raw == hashlib.sha256(startup_bytes).hexdigest()


def test_capacity_measurement_isolated_before_remaining_parallel_group(tmp_path: Path) -> None:
    """Capacity runs alone while the three compatible stages still overlap."""
    barrier = threading.Barrier(3)
    capacity_started = threading.Event()
    capacity_finished = threading.Event()
    capacity_overlap = threading.Event()

    class BarrierRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            if command.label == "full_universe_capacity":
                capacity_started.set()
                capacity_finished.wait(timeout=0.2)
                result = super().run(command)
                capacity_finished.set()
                return result
            if command.label in {
                "response_replay",
                "production_policy_parity",
                "isolated_postgresql_write",
            }:
                if capacity_started.is_set() and not capacity_finished.is_set():
                    capacity_overlap.set()
                barrier.wait(timeout=30)
            return super().run(command)

    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = BarrierRunner()

    receipt_path = run_release_rehearsal(config, runner=runner)

    assert verify_evidence_handoff_receipt(receipt_path)["candidate_sha"] == CANDIDATE_SHA
    assert capacity_started.is_set()
    assert capacity_finished.is_set()
    assert not capacity_overlap.is_set()


def test_parallel_group_failure_records_only_completed_prefix(tmp_path: Path) -> None:
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    runner = FakeRunner(fail_label="full_universe_capacity")

    with pytest.raises(RehearsalBlocked) as exc_info:
        run_release_rehearsal(config, runner=runner)

    assert exc_info.value.stage == "full_universe_capacity"
    assert exc_info.value.code == "S6_STAGE_COMMAND_FAILED"
    # All four group members started; the failure never cancels siblings.
    for label in (
        "response_replay",
        "full_universe_capacity",
        "production_policy_parity",
        "isolated_postgresql_write",
    ):
        assert label in runner.labels
    records = json.loads((config.output_dir / "checkpoint.json").read_text(encoding="utf-8"))[
        "stages"
    ]
    assert "response_replay" in records
    assert "full_universe_capacity" not in records
    assert "production_policy_parity" not in records
    assert "isolated_postgresql_write" not in records
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()

    resumed = FakeRunner()
    receipt = run_release_rehearsal(replace(config, resume=True), runner=resumed)
    assert verify_evidence_handoff_receipt(receipt)["candidate_sha"] == CANDIDATE_SHA
    assert "response_replay" not in resumed.labels
    assert "full_universe_capacity" in resumed.labels
    assert "production_policy_parity" in resumed.labels
    assert "isolated_postgresql_write" in resumed.labels


def test_output_inside_checkout_is_rejected_before_build(tmp_path: Path) -> None:
    runner = FakeRunner()
    root = Path(__file__).resolve().parents[2]
    config = _config(tmp_path, root=root)
    config = replace(config, output_dir=root / "output" / f"s6-test-{tmp_path.name}")

    with pytest.raises(RehearsalBlocked, match="S6_INPUT_OR_ARTIFACT_INVALID"):
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels


def test_failed_provider_stage_stops_before_replay_and_never_emits_receipt(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(fail_label="provider_probe")
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked, match="S6_STAGE_COMMAND_FAILED"):
        run_release_rehearsal(config, runner=runner)

    assert "provider_probe" in runner.labels
    assert "response_replay" not in runner.labels
    assert "full_universe_capacity" not in runner.labels
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()
    status = json.loads((config.output_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "blocked"
    assert status["current_stage"] == "provider_probe"
    assert status["error_code"] == "S6_STAGE_COMMAND_FAILED"


@pytest.mark.parametrize(
    "stable_code",
    [
        "REHEARSAL_BUILD_DISK_HEADROOM_INSUFFICIENT",
        "REHEARSAL_BUILD_DISK_HEADROOM_UNAVAILABLE",
    ],
)
def test_failed_build_only_preserves_remote_disk_headroom_rehearsal_code(
    tmp_path: Path, stable_code: str
) -> None:

    class BuildHeadroomFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            if command.label == "build_only":
                return CommandResult(
                    returncode=1,
                    stderr=(
                        "[ERROR] Remote build failed. Exit=1. "
                        f"Stderr=[ERROR] {stable_code}: only 8 GiB available"
                    ),
                )
            return super().run(command)

    runner = BuildHeadroomFailureRunner()
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked) as exc_info:
        run_release_rehearsal(config, runner=runner)

    assert exc_info.value.stage == "build_only"
    assert exc_info.value.code == stable_code
    assert "docker_load" not in runner.labels
    status = json.loads((config.output_dir / "run-status.json").read_text(encoding="utf-8"))
    assert status["outcome"] == "blocked"
    assert status["current_stage"] == "build_only"
    assert status["error_code"] == stable_code


@pytest.mark.parametrize(
    "stderr",
    [
        "[ERROR] REHEARSAL_BUILD_TAG_ALREADY_ACTIVE: build tag is in use",
        (
            "[ERROR] REHEARSAL_BUILD_DISK_HEADROOM_INSUFFICIENT: low space\n"
            "[ERROR] REHEARSAL_BUILD_DISK_HEADROOM_UNAVAILABLE: df failed"
        ),
    ],
)
def test_failed_build_only_rejects_nonunique_or_non_headroom_error_codes(
    tmp_path: Path, stderr: str
) -> None:
    class BuildFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            if command.label == "build_only":
                return CommandResult(returncode=1, stderr=stderr)
            return super().run(command)

    runner = BuildFailureRunner()

    with pytest.raises(RehearsalBlocked) as exc_info:
        run_release_rehearsal(_config(tmp_path, root=_fake_checkout(tmp_path)), runner=runner)

    assert exc_info.value.stage == "build_only"
    assert exc_info.value.code == "S6_STAGE_COMMAND_FAILED"


def test_preoccupied_ci_evidence_directory_fails_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    sentinel_contents = "operator-owned-evidence"

    class PreoccupyingRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            result = super().run(command)
            if command.label == "isolated_postgresql_write" and result.returncode == 0:
                assert command.artifact_dir is not None
                ci_dir = command.artifact_dir.parent / "github-ci-evidence"
                ci_dir.mkdir()
                (ci_dir / "sentinel.txt").write_text(
                    sentinel_contents,
                    encoding="utf-8",
                )
            return result

    runner = PreoccupyingRunner()
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked, match="S6_STAGE_COMMAND_FAILED"):
        run_release_rehearsal(config, runner=runner)

    ci_dir = config.output_dir / "github-ci-evidence"
    assert (ci_dir / "sentinel.txt").read_text(encoding="utf-8") == sentinel_contents
    assert not (ci_dir / "candidate-regression-evidence.json").exists()
    assert "github_ci_evidence" in runner.labels
    assert "bundle_build" not in runner.labels
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()


def test_ci_evidence_is_group_readable_before_financial_container(
    tmp_path: Path,
) -> None:
    class RestrictiveCiRunner(FakeRunner):
        observed_container_input = False

        def run(self, command: Command) -> CommandResult:
            if command.label == "akshare_financial_slice":
                ci_dir = self._mounted_path(command.argv, target="/run/agom/ci")
                directory_mode = stat.S_IMODE(ci_dir.stat().st_mode)
                expected_directory_mode = 0o550 if os.name == "posix" else 0o555
                expected_file_mode = 0o440 if os.name == "posix" else 0o444
                assert directory_mode == expected_directory_mode
                for path in ci_dir.iterdir():
                    assert stat.S_IMODE(path.stat().st_mode) == expected_file_mode
                    if os.name == "posix":
                        assert path.stat().st_gid == os.getgid()
                    path.read_bytes()
                self.observed_container_input = True
            result = super().run(command)
            if command.label == "github_ci_evidence" and result.returncode == 0:
                assert command.artifact_dir is not None
                command.artifact_dir.chmod(0o700)
                for path in command.artifact_dir.iterdir():
                    path.chmod(0o600)
            return result

    runner = RestrictiveCiRunner()
    run_release_rehearsal(_config(tmp_path, root=_fake_checkout(tmp_path)), runner=runner)

    assert runner.observed_container_input is True


def test_container_input_tree_rejects_nested_symlink(tmp_path: Path) -> None:
    root = tmp_path / "ci"
    root.mkdir()
    (root / "report.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "outside.xml"
    target.write_text("<testsuites />", encoding="utf-8")
    link = root / "contracts.xml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(RehearsalBlocked, match="S6_CONTAINER_INPUT_TREE_INVALID"):
        seal_container_input_tree(
            root,
            os.getgid() if os.name == "posix" else 0,
            RehearsalBlocked,
        )


def test_failed_container_stage_seals_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "stage"
    destination.mkdir()
    calls: list[int] = []
    original_chmod = Path.chmod

    def record_chmod(path: Path, mode: int) -> None:
        calls.append(mode)
        original_chmod(path, mode)

    monkeypatch.setattr(Path, "chmod", record_chmod)
    gid = os.getgid() if hasattr(os, "getgid") else 1000

    with pytest.raises(RehearsalBlocked, match="S6_STAGE_COMMAND_FAILED"):
        _invoke_container_stage(
            FakeRunner(fail_label="stage"),
            argv=("candidate",),
            root=tmp_path,
            label="stage",
            timeout=1,
            env={},
            artifact_dir=destination,
            container_gid=gid,
        )

    assert calls[-1] == 0o750


@pytest.mark.parametrize(
    "stable_code",
    [
        "REHEARSAL_WRITE_CATALOG_UNAVAILABLE",
        "REHEARSAL_WRITE_SCOPE_VENDOR_INVALID",
        "REHEARSAL_WRITE_SCOPE_TRANSACTION_ACTIVE",
        "REHEARSAL_WRITE_SCOPE_OPT_IN_MISSING",
        "REHEARSAL_WRITE_SCOPE_DATABASE_NAME_INVALID",
        "REHEARSAL_WRITE_SCOPE_DATABASE_NAME_MISMATCH",
        "REHEARSAL_WRITE_SCOPE_HOST_CONFIG_MISMATCH",
        "REHEARSAL_WRITE_SCOPE_HOST_NOT_EPHEMERAL",
        "REHEARSAL_WRITE_SCOPE_HOST_UNRESOLVED",
        "REHEARSAL_WRITE_SCOPE_CONNECTED_DATABASE_MISMATCH",
        "REHEARSAL_WRITE_SCOPE_CONNECTED_PORT_MISMATCH",
        "REHEARSAL_WRITE_SCOPE_CONNECTED_ADDRESS_MISMATCH",
    ],
)
def test_failed_container_stage_preserves_one_stable_rehearsal_code(
    tmp_path: Path,
    stable_code: str,
) -> None:
    class StableFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            return CommandResult(
                returncode=1,
                stderr=("sensitive diagnostic omitted\n" f"CommandError: {stable_code}"),
            )

    destination = tmp_path / "stage"
    destination.mkdir()
    gid = os.getgid() if hasattr(os, "getgid") else 1000

    with pytest.raises(RehearsalBlocked) as exc_info:
        _invoke_container_stage(
            StableFailureRunner(),
            argv=("candidate",),
            root=tmp_path,
            label="stage",
            timeout=1,
            env={},
            artifact_dir=destination,
            container_gid=gid,
        )

    assert exc_info.value.code == stable_code


def test_failed_stage_preserves_exact_validator_json_code(tmp_path: Path) -> None:
    stable_code = "REHEARSAL_PROVIDER_IDENTITY_INVALID"

    class ValidatorFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            return CommandResult(
                returncode=1,
                stdout=json.dumps({"outcome": "blocked", "code": stable_code}),
            )

    with pytest.raises(RehearsalBlocked) as exc_info:
        _invoke(
            ValidatorFailureRunner(),
            argv=("validator",),
            root=tmp_path,
            label="release_validator",
            timeout=1,
        )

    assert exc_info.value.code == stable_code


def test_failed_capacity_stage_extracts_machine_code_alongside_diagnostics(
    tmp_path: Path,
) -> None:
    stable_code = "REHEARSAL_CAPACITY_QUOTE_SCOPE_INCOMPLETE"

    class CapacityFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            return CommandResult(
                returncode=1,
                stdout=json.dumps({"outcome": "blocked", "code": stable_code}),
                stderr='CommandError: quote scope incomplete {"missing": ["600000.SH"]}',
            )

    with pytest.raises(RehearsalBlocked) as exc_info:
        _invoke(
            CapacityFailureRunner(),
            argv=("capacity",),
            root=tmp_path,
            label="full_universe_capacity",
            timeout=1,
        )

    assert exc_info.value.code == stable_code


@pytest.mark.parametrize(
    "stderr",
    [
        "provider mentioned REHEARSAL_WRITE_CATALOG_UNAVAILABLE in a diagnostic",
        (
            "CommandError: REHEARSAL_WRITE_CATALOG_UNAVAILABLE\n"
            "CommandError: REHEARSAL_WRITE_SCOPE_INVALID"
        ),
        json.dumps(
            {
                "outcome": "blocked",
                "code": "REHEARSAL_PROVIDER_IDENTITY_INVALID",
                "detail": "untrusted diagnostic",
            }
        ),
    ],
)
def test_failed_container_stage_rejects_ambiguous_or_unanchored_codes(
    tmp_path: Path,
    stderr: str,
) -> None:
    class UnsafeFailureRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            return CommandResult(returncode=1, stderr=stderr)

    destination = tmp_path / "stage"
    destination.mkdir()
    gid = os.getgid() if hasattr(os, "getgid") else 1000

    with pytest.raises(RehearsalBlocked) as exc_info:
        _invoke_container_stage(
            UnsafeFailureRunner(),
            argv=("candidate",),
            root=tmp_path,
            label="stage",
            timeout=1,
            env={},
            artifact_dir=destination,
            container_gid=gid,
        )

    assert exc_info.value.code == "S6_STAGE_COMMAND_FAILED"


def test_container_stage_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")
    gid = os.getgid() if hasattr(os, "getgid") else 1000
    with pytest.raises(RehearsalBlocked, match="S6_ARTIFACT_DIRECTORY_INVALID"):
        _invoke_container_stage(
            FakeRunner(),
            argv=("candidate",),
            root=tmp_path,
            label="stage",
            timeout=1,
            env={},
            artifact_dir=link,
            container_gid=gid,
        )


def test_container_stage_rejects_inode_replacement(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    gid = os.getgid() if hasattr(os, "getgid") else 1000

    class ReplacingRunner(FakeRunner):
        def run(self, command: Command) -> CommandResult:
            shutil.rmtree(target)
            target.mkdir()
            return CommandResult(returncode=0)

    with pytest.raises(RehearsalBlocked, match="S6_ARTIFACT_DIRECTORY_CHANGED"):
        _invoke_container_stage(
            ReplacingRunner(),
            argv=("candidate",),
            root=tmp_path,
            label="stage",
            timeout=1,
            env={},
            artifact_dir=target,
            container_gid=gid,
        )


def test_identity_mismatch_stops_before_later_business_stages(tmp_path: Path) -> None:
    runner = FakeRunner(wrong_identity_label="full_universe_capacity")
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked, match="S6_STAGE_IDENTITY_MISMATCH"):
        run_release_rehearsal(config, runner=runner)

    assert "full_universe_capacity" in runner.labels
    assert "github_ci_evidence" not in runner.labels
    assert "bundle_build" not in runner.labels
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()
    # Only the ordered prefix before the failing group member is recorded.
    records = json.loads((config.output_dir / "checkpoint.json").read_text(encoding="utf-8"))[
        "stages"
    ]
    assert "response_replay" in records
    assert "full_universe_capacity" not in records
    assert "production_policy_parity" not in records
    assert "isolated_postgresql_write" not in records


def test_dirty_worktree_fails_before_build_or_remote_command(tmp_path: Path) -> None:
    runner = FakeRunner(dirty_worktree=True)
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked, match="S6_WORKTREE_DIRTY"):
        run_release_rehearsal(config, runner=runner)

    assert "build_only" not in runner.labels
    assert not config.output_dir.exists()


def test_bundle_change_during_validation_blocks_evidence_handoff(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(mutate_bundle_on_validation=True)
    config = _config(tmp_path, root=_fake_checkout(tmp_path))

    with pytest.raises(RehearsalBlocked, match="S6_BUNDLE_CHANGED_AFTER_VALIDATION"):
        run_release_rehearsal(config, runner=runner)

    assert "release_validator" in runner.labels
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()


def test_bundle_digest_and_evidence_handoff_detect_post_validation_mutation(
    tmp_path: Path,
) -> None:
    runner = FakeRunner()
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    receipt_path = run_release_rehearsal(config, runner=runner)
    receipt = verify_evidence_handoff_receipt(receipt_path)
    bundle_dir = Path(cast(str, receipt["bundle_dir"]))
    original_digest = bundle_tree_digest(bundle_dir)
    nested_report = bundle_dir / "real_response_unit_replay" / "real-response-unit-replay.json"
    nested_report.chmod(0o644)
    nested_report.write_bytes(nested_report.read_bytes() + b" ")

    assert bundle_tree_digest(bundle_dir) != original_digest
    with pytest.raises(RehearsalBlocked, match="S6_HANDOFF_RECEIPT_MISMATCH"):
        verify_evidence_handoff_receipt(receipt_path)


def test_forged_validator_owned_receipt_is_rejected(tmp_path: Path) -> None:
    runner = FakeRunner()
    config = _config(tmp_path, root=_fake_checkout(tmp_path))
    receipt_path = run_release_rehearsal(config, runner=runner)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt_path.chmod(0o644)
    receipt.update(
        {
            "schema": "release.rehearsal-deployment-receipt.v1",
            "issuer": "release_rehearsal_validator",
            "receipt_status": "validated",
            "deployable": True,
        }
    )
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(RehearsalBlocked, match="S6_HANDOFF_RECEIPT_MISMATCH"):
        verify_evidence_handoff_receipt(receipt_path)
