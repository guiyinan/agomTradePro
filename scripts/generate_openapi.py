"""Generate the canonical OpenAPI YAML, check drift, or export a temporary copy."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs/testing/api/openapi.yaml"


def generate_openapi(
    output: Path,
    *,
    output_format: Literal["yaml", "json"],
    check: bool,
    settings: str | None,
) -> int:
    """Generate with Django; preserve the destination on failure or in check mode."""
    with tempfile.TemporaryDirectory(prefix="agom-openapi-") as directory:
        generated = Path(directory) / "openapi"
        command = [
            sys.executable,
            str(REPO_ROOT / "manage.py"),
            "spectacular",
            "--format",
            "openapi-json" if output_format == "json" else "openapi",
            "--file",
            str(generated),
        ]
        if settings is not None:
            command.extend(["--settings", settings])
        result = subprocess.run(command, cwd=REPO_ROOT, check=False)
        if result.returncode != 0:
            print("OpenAPI generation failed; destination unchanged.", file=sys.stderr)
            return result.returncode
        expected = generated.read_text(encoding="utf-8")

    if check:
        if not output.is_file() or output.read_text(encoding="utf-8") != expected:
            print(f"OpenAPI missing or stale: {output}", file=sys.stderr)
            return 1
        print(f"OpenAPI is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8", newline="\n")
    print(f"Generated OpenAPI: {output}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the single entry point for versioned generation and temporary exports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check drift without writing output.")
    parser.add_argument("--format", choices=("yaml", "json"), default="yaml")
    parser.add_argument(
        "--output", type=Path, help="Export path (default: docs/testing/api/openapi.yaml)."
    )
    parser.add_argument(
        "--settings",
        default="core.settings.openapi",
        help="Django settings module (default: core.settings.openapi, PostgreSQL metadata).",
    )
    args = parser.parse_args(argv)
    output_format = cast(Literal["yaml", "json"], args.format)
    requested_output = cast(Path | None, args.output)
    output = requested_output if requested_output is not None else DEFAULT_OUTPUT
    if output_format == "json":
        if requested_output is None:
            parser.error("--format json requires --output for a temporary export")
        if output.resolve() == DEFAULT_OUTPUT.resolve():
            parser.error("JSON export must not overwrite the canonical YAML")
    return generate_openapi(
        output,
        output_format=output_format,
        check=bool(args.check),
        settings=cast(str | None, args.settings),
    )


if __name__ == "__main__":
    raise SystemExit(main())
