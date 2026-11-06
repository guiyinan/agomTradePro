"""Black-box tests for the REF-01 generated-model delta gate.

Each case creates a tiny Git repository with committed generated projections.
The repository copies the real checker and AST builder, so the tests exercise
the public CLI and exact commit-tree inputs without Django or a database.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Sequence
from pathlib import Path

PLAN_PATH = "docs/plans/ref01-fixture.md"
PLAN_HEADING = "### REF-01"
PLAN_HEADER = (
    "| base_sha | identity | change_kind | rationale | consumer_audit | "
    "compatibility_or_rollback |"
)
PLAN_SEPARATOR = "| --- | --- | --- | --- | --- | --- |"


def _workspace_root() -> Path:
    """Find the repository containing the real dictionary scripts."""

    for candidate in (Path.cwd(), *Path(__file__).resolve().parents):
        if (candidate / "scripts" / "build_data_dictionary.py").is_file() and (
            candidate / "scripts" / "check_data_dictionary.py"
        ).is_file():
            return candidate
    raise RuntimeError("could not locate the repository data-dictionary scripts")


def _plan_document(rows: Sequence[str] = ()) -> str:
    """Build a minimal existing-plan document with the frozen REF-01 table."""

    body = ["# REF-01 test plan", "", PLAN_HEADING, "", PLAN_HEADER, PLAN_SEPARATOR]
    body.extend(rows)
    return "\n".join(body) + "\n"


def _row(
    base_sha: str,
    identity: str,
    change_kind: str,
    *,
    rationale: str = "Adds a concrete model for an explicitly identified consumer need.",
    consumer_audit: str = "Reviewed tracked application, SQL, and configuration references.",
    compatibility_or_rollback: str = "Revert this model change and regenerate both projections.",
) -> str:
    """Format one exact REF-01 explanation row."""

    return (
        f"| {base_sha} | {identity} | {change_kind} | {rationale} | "
        f"{consumer_audit} | {compatibility_or_rollback} |"
    )


class _TemporaryProjectionRepository:
    """A committed base/head fixture that invokes the copied public CLI."""

    def __init__(self, owner: unittest.TestCase, initial_models: str) -> None:
        self._owner = owner
        self._temporary_directory = tempfile.TemporaryDirectory(prefix="ref01-dictionary-")
        owner.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name) / "repo"
        self.root.mkdir()
        scripts = self.root / "scripts"
        scripts.mkdir()
        source_scripts = _workspace_root() / "scripts"
        shutil.copy2(source_scripts / "build_data_dictionary.py", scripts)
        shutil.copy2(source_scripts / "check_data_dictionary.py", scripts)
        shutil.copy2(source_scripts / "check_data_dictionary_model_delta.py", scripts)
        self._git("init", "-q")
        self._git("config", "user.name", "REF-01 test")
        self._git("config", "user.email", "ref01-test@example.invalid")
        self._write("apps/demo/infrastructure/models.py", initial_models)
        self._write(PLAN_PATH, _plan_document())
        self._build_projection()
        self.base_sha = self._commit("base projection")

    def _git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        return completed.stdout.strip()

    def _write(self, relative_path: str, content: str) -> Path:
        destination = self.root / Path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="\n")
        return destination

    def _build_projection(self) -> None:
        completed = subprocess.run(
            [sys.executable, "scripts/build_data_dictionary.py"],
            cwd=self.root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )
        self._owner.assertEqual(
            completed.returncode,
            0,
            msg=f"fixture projection build failed:\n{completed.stdout}",
        )

    def _commit(self, message: str) -> str:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)
        return self._git("rev-parse", "HEAD")

    def commit_head(
        self,
        *,
        models: str | None = None,
        plan_rows: Sequence[str] | None = None,
        extra_files: dict[str, str] | None = None,
        removed_files: Sequence[str] = (),
        regenerate: bool = True,
        message: str = "head projection",
    ) -> str:
        """Commit a head tree, optionally leaving projection files stale."""

        if models is not None:
            self._write("apps/demo/infrastructure/models.py", models)
        if plan_rows is not None:
            self._write(PLAN_PATH, _plan_document(plan_rows))
        for relative_path, content in (extra_files or {}).items():
            self._write(relative_path, content)
        for relative_path in removed_files:
            target = self.root / Path(relative_path)
            if target.exists():
                target.unlink()
        if regenerate:
            self._build_projection()
        return self._commit(message)

    def run_checker(
        self,
        *,
        base_ref: str | None = None,
        head_ref: str | None = None,
        plan_path: str = PLAN_PATH,
        include_plan_path: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Invoke the checker in the temporary repository."""

        command = [sys.executable, "scripts/check_data_dictionary.py"]
        if base_ref is not None:
            command.extend(["--base-ref", base_ref])
        if head_ref is not None:
            command.extend(["--head-ref", head_ref])
        if include_plan_path:
            command.extend(["--plan-file", plan_path])
        return subprocess.run(
            command,
            cwd=self.root,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )

    def current_sha(self) -> str:
        """Return the exact checked-out temporary HEAD commit."""

        return self._git("rev-parse", "HEAD")

    def projection(self) -> dict[str, object]:
        """Read the checked-in head JSON projection for semantic assertions."""

        value = json.loads(
            (self.root / "governance" / "data_dictionary.json").read_text(encoding="utf-8")
        )
        if not isinstance(value, dict):
            raise AssertionError("fixture projection root must be an object")
        return value


class DataDictionaryDeltaGateTests(unittest.TestCase):
    """Exercise accepted semantic deltas and fail-closed Git/projection cases."""

    _BASE_MODELS = """from django.db import models

class LedgerModel(models.Model):
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_ledger"
"""

    def _assert_passes(
        self, repository: _TemporaryProjectionRepository, base_sha: str, head_sha: str
    ) -> None:
        result = repository.run_checker(base_ref=base_sha, head_ref=head_sha)
        self.assertEqual(result.returncode, 0, msg=result.stdout)

    def _assert_fails(
        self, repository: _TemporaryProjectionRepository, base_sha: str, head_sha: str
    ) -> None:
        result = repository.run_checker(base_ref=base_sha, head_ref=head_sha)
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)

    def test_no_argument_checker_mode_and_docs_only_change_remain_valid(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        head_sha = repository.commit_head(
            extra_files={"docs/notes.md": "Documentation-only change.\n"},
            message="docs only",
        )

        default_result = repository.run_checker(include_plan_path=False)
        self.assertEqual(default_result.returncode, 0, msg=default_result.stdout)
        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_paired_refs_must_be_full_distinct_oids_and_head_must_be_checked_out(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        head_sha = repository.commit_head(
            extra_files={"docs/notes.md": "No model projection change.\n"}
        )

        missing_head = repository.run_checker(base_ref=repository.base_sha)
        self.assertNotEqual(missing_head.returncode, 0, msg=missing_head.stdout)
        invalid_base = repository.run_checker(base_ref="f" * 40, head_ref=head_sha)
        self.assertNotEqual(invalid_base.returncode, 0, msg=invalid_base.stdout)
        short_base = repository.run_checker(base_ref=repository.base_sha[:7], head_ref=head_sha)
        self.assertNotEqual(short_base.returncode, 0, msg=short_base.stdout)
        same_ref = repository.run_checker(base_ref=head_sha, head_ref=head_sha)
        self.assertNotEqual(same_ref.returncode, 0, msg=same_ref.stdout)
        non_head = repository.run_checker(
            base_ref=repository.base_sha, head_ref=repository.base_sha
        )
        self.assertNotEqual(non_head.returncode, 0, msg=non_head.stdout)

    def test_git_text_checkout_line_endings_do_not_look_like_a_builder_shadow(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        builder = repository.root / "scripts/build_data_dictionary.py"
        builder.write_bytes(builder.read_bytes().replace(b"\r\n", b"\n"))
        repository._git("config", "core.autocrlf", "false")
        repository._git("add", "scripts/build_data_dictionary.py")
        repository._git("commit", "--allow-empty", "-q", "-m", "LF builder")
        repository.base_sha = repository.current_sha()
        head_sha = repository.commit_head(extra_files={"docs/notes.md": "No model change.\n"})
        builder.write_bytes(builder.read_bytes().replace(b"\n", b"\r\n"))

        self._assert_passes(repository, repository.base_sha, head_sha)
        builder.write_bytes(builder.read_bytes() + b"\r\n# uncommitted builder shadow\r\n")
        self._assert_fails(repository, repository.base_sha, head_sha)

    def test_docstring_only_change_is_not_an_orm_semantic_delta(self) -> None:
        initial = '''from django.db import models

class LedgerModel(models.Model):
    """Original descriptive text."""
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_ledger"
'''
        changed = initial.replace("Original descriptive text.", "Reworded descriptive text.")
        repository = _TemporaryProjectionRepository(self, initial)
        head_sha = repository.commit_head(models=changed)

        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_pure_model_source_move_is_not_a_schema_delta(self) -> None:
        moved_model = """from django.db import models

class LedgerModel(models.Model):
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_ledger"
"""
        initial = moved_model + "\nclass OtherModel(models.Model):\n    pass\n"
        repository = _TemporaryProjectionRepository(self, initial)
        head_main = "from django.db import models\n\nclass OtherModel(models.Model):\n    pass\n"
        repository._write("apps/demo/infrastructure/models.py", head_main)
        repository._write("apps/demo/infrastructure/models/ledger.py", moved_model)
        repository._build_projection()
        head_sha = repository._commit("move model source")

        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_new_concrete_and_higher_version_require_exact_explanations(self) -> None:
        initial = """from django.db import models

class InvoiceV1Model(models.Model):
    value = models.IntegerField()

    class Meta:
        db_table = "demo_invoice_v1"
"""
        repository = _TemporaryProjectionRepository(self, initial)
        rows = [
            _row(repository.base_sha, "demo.InvoiceV2Model", "new_version"),
            _row(repository.base_sha, "demo.AuditTrailModel", "added_concrete"),
        ]
        changed = initial + """
class InvoiceV2Model(models.Model):
    value = models.IntegerField()

    class Meta:
        db_table = "demo_invoice_v2"

class AuditTrailModel(models.Model):
    event = models.CharField(max_length=64)
"""
        head_sha = repository.commit_head(models=changed, plan_rows=rows)

        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_checker_discovers_changed_existing_plan_without_plan_file_flag(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        changed = self._BASE_MODELS + "\nclass RiskAuditModel(models.Model):\n    pass\n"
        row = _row(repository.base_sha, "demo.RiskAuditModel", "added_concrete")
        plan = _plan_document([row]).replace(PLAN_HEADING, "### Feature model changes")
        head_sha = repository.commit_head(models=changed, extra_files={PLAN_PATH: plan})

        result = repository.run_checker(
            base_ref=repository.base_sha,
            head_ref=head_sha,
            include_plan_path=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout)

    def test_comment_only_builder_maintenance_with_identical_projections_passes(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        builder_path = repository.root / "scripts" / "build_data_dictionary.py"
        builder_source = builder_path.read_text(encoding="utf-8")
        head_sha = repository.commit_head(
            extra_files={
                "scripts/build_data_dictionary.py": builder_source
                + "\n# Non-functional maintenance note for the AST projection.\n"
            },
            message="comment-only builder maintenance",
        )

        for projection_path in (
            "governance/data_dictionary.json",
            "docs/architecture/DATA_DICTIONARY.md",
        ):
            base_projection = repository._git("show", f"{repository.base_sha}:{projection_path}")
            head_projection = repository._git("show", f"{head_sha}:{projection_path}")
            self.assertEqual(base_projection, head_projection)
        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_abstract_and_inherited_fields_keep_distinct_projection_semantics(self) -> None:
        initial = """from django.db import models

class AuditBaseModel(models.Model):
    inherited_code = models.CharField(max_length=20)

    class Meta:
        abstract = True
"""
        repository = _TemporaryProjectionRepository(self, initial)
        changed = initial + """
class AuditChildModel(AuditBaseModel):
    own_flag = models.BooleanField(default=False)

class AbstractMarkerModel(models.Model):
    marker = models.CharField(max_length=20)

    class Meta:
        abstract = True
"""
        rows = [
            _row(repository.base_sha, "demo.AuditChildModel", "added_concrete"),
            _row(repository.base_sha, "demo.AbstractMarkerModel", "added_abstract"),
        ]
        head_sha = repository.commit_head(models=changed, plan_rows=rows)
        self._assert_passes(repository, repository.base_sha, head_sha)

        apps = repository.projection()["apps"]
        self.assertIsInstance(apps, dict)
        demo = apps["demo"]
        self.assertIsInstance(demo, dict)
        model_records = demo["models"]
        self.assertIsInstance(model_records, list)
        by_name = {
            str(record["class_name"]): record
            for record in model_records
            if isinstance(record, dict)
        }
        child = by_name["AuditChildModel"]
        child_fields = child["fields"]
        self.assertIsInstance(child_fields, list)
        self.assertEqual([field["name"] for field in child_fields], ["own_flag"])
        self.assertTrue(by_name["AbstractMarkerModel"]["abstract"])

    def test_field_and_declared_table_change_cannot_be_hidden_as_file_move(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        changed = """from django.db import models

class LedgerModel(models.Model):
    code = models.TextField()

    class Meta:
        db_table = "demo_ledger_v2"
"""
        rows = [_row(repository.base_sha, "demo.LedgerModel", "model_change")]
        repository._write("apps/demo/infrastructure/models.py", "")
        repository._write("apps/demo/infrastructure/models/ledger_models.py", changed)
        repository._write(PLAN_PATH, _plan_document(rows))
        repository._build_projection()
        head_sha = repository._commit("move and change model schema")
        self._assert_passes(repository, repository.base_sha, head_sha)

        wrong_kind_rows = [_row(repository.base_sha, "demo.LedgerModel", "file_move")]
        repository._write(PLAN_PATH, _plan_document(wrong_kind_rows))
        wrong_kind_head = repository._commit("misclassify schema change as move")
        self._assert_fails(repository, repository.base_sha, wrong_kind_head)

    def test_class_rename_is_not_paired_by_a_shared_declared_table(self) -> None:
        initial = """from django.db import models

class PreviousLedgerModel(models.Model):
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_shared_ledger"
"""
        repository = _TemporaryProjectionRepository(self, initial)
        replacement = """from django.db import models

class ReplacementLedgerModel(models.Model):
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_shared_ledger"
"""
        # A note for the new class alone must not hide the independently
        # deleted old identity merely because both declare the same table name.
        add_only = [_row(repository.base_sha, "demo.ReplacementLedgerModel", "added_concrete")]
        head_sha = repository.commit_head(models=replacement, plan_rows=add_only)
        self._assert_fails(repository, repository.base_sha, head_sha)

        # This checker has no database inventory input, so a source-level
        # declaration cannot prove physical-table retirement either.
        rows = [
            _row(repository.base_sha, "demo.ReplacementLedgerModel", "added_concrete"),
            _row(
                repository.base_sha,
                "demo.PreviousLedgerModel",
                "deleted_concrete",
                rationale="Rename the Python model while retaining its declared table.",
                consumer_audit="Tracked source references were reviewed; physical inventory is unknown.",
                compatibility_or_rollback="Restore the old model identity if application imports regress.",
            ),
        ]
        head_sha = repository.commit_head(models=replacement, plan_rows=rows)
        self._assert_fails(repository, repository.base_sha, head_sha)

    def test_missing_duplicate_unused_malformed_or_wildcard_explanations_fail(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        changed = self._BASE_MODELS + "\nclass NewLedgerAuditModel(models.Model):\n    pass\n"
        repository._write("apps/demo/infrastructure/models.py", changed)
        repository._build_projection()
        first_head = repository._commit("add new model without explanation")
        self._assert_fails(repository, repository.base_sha, first_head)

        exact = _row(repository.base_sha, "demo.NewLedgerAuditModel", "added_concrete")
        malformed_rows = [
            [exact, exact],
            [
                "| "
                + repository.base_sha
                + " | demo.* | added_concrete | broad | reviewed | revert |"
            ],
            [
                _row(
                    repository.base_sha,
                    "demo.NewLedgerAuditModel",
                    "added_concrete",
                    consumer_audit="   ",
                )
            ],
            [
                _row(
                    "0" * 40,
                    "demo.NewLedgerAuditModel",
                    "added_concrete",
                )
            ],
        ]
        for index, rows in enumerate(malformed_rows):
            with self.subTest(explanation_case=index):
                repository._write(PLAN_PATH, _plan_document(rows))
                head_sha = repository._commit(f"invalid explanation {index}")
                self._assert_fails(repository, repository.base_sha, head_sha)

        repository._write(
            PLAN_PATH,
            _plan_document([exact, _row(repository.base_sha, "demo.GhostModel", "added_concrete")]),
        )
        unused_sha = repository._commit("unused current-base explanation")
        self._assert_fails(repository, repository.base_sha, unused_sha)

    def test_historical_explanation_for_another_base_is_inert(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        historical = _row("0" * 40, "demo.OldModel", "added_concrete")
        head_sha = repository.commit_head(
            plan_rows=[historical],
            extra_files={"docs/notes.md": "No current model delta.\n"},
        )

        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_deleted_model_with_live_reference_or_unknown_audit_is_blocked(self) -> None:
        initial = """from django.db import models

class LegacyLedgerModel(models.Model):
    code = models.CharField(max_length=20)

    class Meta:
        db_table = "demo_legacy_ledger"
"""
        repository = _TemporaryProjectionRepository(self, initial)
        deletion_row = _row(
            repository.base_sha,
            "demo.LegacyLedgerModel",
            "deleted_concrete",
            consumer_audit="Reviewed tracked references; no direct consumer remains.",
        )
        head_sha = repository.commit_head(
            models="from django.db import models\n",
            plan_rows=[deletion_row],
            extra_files={
                "apps/demo/application/ledger_reader.py": (
                    "from apps.demo.infrastructure.models import LegacyLedgerModel\n"
                    "MODEL = LegacyLedgerModel  # fixture_reference_line_not_for_diagnostics\n"
                )
            },
        )
        referenced = repository.run_checker(base_ref=repository.base_sha, head_ref=head_sha)
        self.assertNotEqual(referenced.returncode, 0, msg=referenced.stdout)
        self.assertIn("still has tracked references", referenced.stdout)
        self.assertNotIn("fixture_reference_line_not_for_diagnostics", referenced.stdout)

        unknown_audit = _row(
            repository.base_sha,
            "demo.LegacyLedgerModel",
            "deleted_concrete",
            consumer_audit="unknown",
        )
        blocked_sha = repository.commit_head(
            models="from django.db import models\n",
            plan_rows=[unknown_audit],
            extra_files={"apps/demo/application/ledger_reader.py": "# No direct model import.\n"},
        )
        unaudited = repository.run_checker(base_ref=repository.base_sha, head_ref=blocked_sha)
        self.assertNotEqual(unaudited.returncode, 0, msg=unaudited.stdout)
        self.assertIn("unknown consumer audit", unaudited.stdout)
        audited_sha = repository.commit_head(
            plan_rows=[deletion_row],
            extra_files={"apps/demo/application/ledger_reader.py": "# No direct model import.\n"},
        )
        self._assert_passes(repository, repository.base_sha, audited_sha)

    def test_duplicate_model_identity_is_ambiguous_even_with_distinct_tables(self) -> None:
        duplicate = self._BASE_MODELS + """
class LedgerModel(models.Model):
    value = models.IntegerField()

    class Meta:
        db_table = "second_demo_ledger"
"""
        repository = _TemporaryProjectionRepository(self, duplicate)
        head_sha = repository.commit_head(extra_files={"docs/notes.md": "unchanged models\n"})

        self._assert_fails(repository, repository.base_sha, head_sha)

    def test_model_declared_outside_projection_scope_does_not_pass_as_noop(self) -> None:
        repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        head_sha = repository.commit_head(
            extra_files={"apps/demo/infrastructure/schema.py": """from django.db import models

class UnsupportedSchemaModel(models.Model):
    value = models.CharField(max_length=20)
"""}
        )

        self._assert_fails(repository, repository.base_sha, head_sha)

    def test_unprojected_version_subclass_does_not_pass_as_noop(self) -> None:
        initial = """from django.db import models

class FooV1Model(models.Model):
    value = models.CharField(max_length=20)
"""
        repository = _TemporaryProjectionRepository(self, initial)
        head_sha = repository.commit_head(
            extra_files={
                "apps/demo/infrastructure/schema.py": """from apps.demo.infrastructure.models import FooV1Model

class FooV2Model(FooV1Model):
    pass
"""
            }
        )

        self._assert_fails(repository, repository.base_sha, head_sha)

    def test_method_and_docstring_only_change_on_unprojected_model_is_not_schema_delta(
        self,
    ) -> None:
        initial = """from django.db import models

class FooModel(models.Model):
    value = models.CharField(max_length=20)
"""
        repository = _TemporaryProjectionRepository(self, initial)
        original_child = """from apps.demo.infrastructure.models import FooModel

class FooChildModel(FooModel):
    \"\"\"Original helper documentation.\"\"\"

    def display_value(self):
        return self.value.upper()
"""
        changed_child = """from apps.demo.infrastructure.models import FooModel

class FooChildModel(FooModel):
    \"\"\"Reworded helper documentation.\"\"\"

    def display_value(self):
        return self.value.casefold()
"""
        child_path = "apps/demo/infrastructure/schema.py"
        repository._write(child_path, original_child)
        repository._git("add", "-A")
        repository._git("commit", "-q", "--amend", "--no-edit")
        repository.base_sha = repository.current_sha()
        head_sha = repository.commit_head(extra_files={child_path: changed_child})

        for projection_path in (
            "governance/data_dictionary.json",
            "docs/architecture/DATA_DICTIONARY.md",
        ):
            base_projection = repository._git("show", f"{repository.base_sha}:{projection_path}")
            head_projection = repository._git("show", f"{head_sha}:{projection_path}")
            self.assertEqual(base_projection, head_projection)
        self._assert_passes(repository, repository.base_sha, head_sha)

    def test_stale_base_or_head_projection_and_missing_markdown_fail_closed(self) -> None:
        base_stale = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        json_path = base_stale.root / "governance" / "data_dictionary.json"
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        payload["projection_notice"] = "stale base projection"
        json_path.write_text(json.dumps(payload), encoding="utf-8", newline="\n")
        base_stale._git("add", "governance/data_dictionary.json")
        base_stale._git("commit", "-q", "--amend", "--no-edit")
        base_sha = base_stale.current_sha()
        base_stale._write("apps/demo/infrastructure/models.py", self._BASE_MODELS + "\n# head\n")
        base_stale._build_projection()
        head_sha = base_stale._commit("head after stale base")
        self._assert_fails(base_stale, base_sha, head_sha)

        head_stale = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        changed = self._BASE_MODELS + "\nclass NewLedgerModel(models.Model):\n    pass\n"
        stale_head = head_stale.commit_head(
            models=changed,
            plan_rows=[_row(head_stale.base_sha, "demo.NewLedgerModel", "added_concrete")],
            regenerate=False,
        )
        self._assert_fails(head_stale, head_stale.base_sha, stale_head)

        missing_markdown = _TemporaryProjectionRepository(self, self._BASE_MODELS)
        missing_markdown.commit_head(
            models=changed,
            plan_rows=[_row(missing_markdown.base_sha, "demo.NewLedgerModel", "added_concrete")],
        )
        (missing_markdown.root / "docs/architecture/DATA_DICTIONARY.md").unlink()
        missing_head = missing_markdown._commit("remove Markdown projection")
        result = missing_markdown.run_checker(
            base_ref=missing_markdown.base_sha, head_ref=missing_head
        )
        self.assertNotEqual(result.returncode, 0, msg=result.stdout)
        self.assertIn("data dictionary Markdown missing", result.stdout)
        self.assertIn("docs/architecture/DATA_DICTIONARY.md", result.stdout.replace("\\", "/"))

    def test_missing_or_malformed_base_json_projection_fails_closed(self) -> None:
        for projection_case in ("missing", "malformed"):
            with self.subTest(projection_case=projection_case):
                repository = _TemporaryProjectionRepository(self, self._BASE_MODELS)
                base_json = repository.root / "governance" / "data_dictionary.json"
                if projection_case == "missing":
                    base_json.unlink()
                else:
                    base_json.write_text("{not json", encoding="utf-8", newline="\n")
                repository._git("add", "-A")
                repository._git("commit", "-q", "--amend", "--no-edit")
                base_sha = repository.current_sha()
                head_sha = repository.commit_head(
                    extra_files={"docs/notes.md": "The source tree is unchanged.\n"}
                )
                self._assert_fails(repository, base_sha, head_sha)


if __name__ == "__main__":
    unittest.main()
