"""Behavioral tests for the candidate-bound S6 orchestration skeleton."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from apps.data_center.infrastructure.rehearsal_identity import (
    parse_rehearsal_identities,
    rehearsal_identities_digest,
)
from scripts.build_release_rehearsal_manifest import REQUIRED_SCHEMAS, build_manifest
from scripts.run_release_rehearsal import (
    Command,
    CommandResult,
    RehearsalBlocked,
    RehearsalConfig,
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
    ) -> None:
        self.fail_label = fail_label
        self.wrong_identity_label = wrong_identity_label
        self.mutate_bundle_on_validation = mutate_bundle_on_validation
        self.dirty_worktree = dirty_worktree
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
            "isolated_postgresql_write",
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
        if command.label == self.wrong_identity_label:
            image_value = f"sha256:{'d' * 64}"
        filenames = {
            "provider_probe": "probe.json",
            "response_replay": "output/real-response-unit-replay.json",
            "full_universe_capacity": "output/full-universe-capacity.json",
            "isolated_postgresql_write": "output/isolated-write-rehearsal.json",
            "github_ci_evidence": "candidate-regression-evidence.json",
        }
        kinds = {
            "response_replay": "real_response_unit_replay",
            "full_universe_capacity": "full_universe_capacity",
            "isolated_postgresql_write": "isolated_write_rehearsal",
            "github_ci_evidence": "candidate_regression_evidence",
        }
        payload: dict[str, object] = {
            "outcome": "success",
            "candidate_sha": CANDIDATE_SHA,
            "target_trade_date": TRADE_DATE,
            "universe_sha256": UNIVERSE_SHA256,
            "provider_identities_sha256": _provider_digest(),
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
                "isolated_postgresql_write": "isolated_postgresql",
                "github_ci_evidence": "candidate_ci",
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
                "isolated_write_rehearsal": "--isolated-write-rehearsal",
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
            candidate_image_id=args[args.index("--candidate-image-id") + 1],
        )


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
    password_path = tmp_path / "password.txt"
    password_path.write_text("not-a-real-secret", encoding="utf-8")
    provider_env = tmp_path / "provider.env"
    provider_env.write_text("DJANGO_SETTINGS_MODULE=config.settings\n", encoding="utf-8")
    isolated_env = tmp_path / "isolated.env"
    isolated_env.write_text("AGOM_RELEASE_REHEARSAL_DATABASE=1\n", encoding="utf-8")
    return RehearsalConfig(
        root=root,
        output_dir=tmp_path / "rehearsal-run",
        build_host="builder.example.invalid",
        build_user="builder",
        password_file=password_path,
        target_trade_date=TRADE_DATE,
        universe_sha256=UNIVERSE_SHA256,
        provider_identities_path=provider_path,
        unit_contract_path=unit_path,
        quote_provider_id=11,
        valuation_provider_id=12,
        provider_env_file=provider_env,
        isolated_postgres_env_file=isolated_env,
        docker_network="agomtradepro_rehearsal",
        isolated_database_name="agom_release_rehearsal_abcdefghij",
        isolated_database_host="agom-s6-postgres-abcdefghij",
        provider_request_limit=100,
        provider_window_seconds=60.0,
        task_deadline_seconds=900.0,
        lock_wait_limit_seconds=10.0,
        github_repository=GITHUB_REPOSITORY,
        github_run_id=GITHUB_RUN_ID,
    )


def _fake_checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    return root


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
        "isolated_postgresql_write",
        "github_ci_evidence",
        "bundle_build",
        "release_validator",
    ]
    observed_stages = [label for label in runner.labels if label in expected_stages]
    assert observed_stages == expected_stages
    assert "deploy" not in runner.labels
    provider_command = next(item for item in runner.commands if item.label == "provider_probe")
    target_index = provider_command.argv.index("--target-trade-date")
    assert provider_command.argv[target_index + 1] == TRADE_DATE
    for label in expected_stages[:4]:
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
    for directory in (
        "provider-probe",
        "response-replay",
        "full-universe-capacity",
        "isolated-postgresql",
    ):
        writable_mode = 0o2770 if os.name == "posix" else 0o770
        assert chmod_calls[directory] == [writable_mode, 0o750]


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
    assert "isolated_postgresql_write" not in runner.labels
    assert "github_ci_evidence" not in runner.labels
    assert not (config.output_dir / "s6-handoff-receipt.json").exists()


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
