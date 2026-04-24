#!/usr/bin/env python
"""Generate an application-side provider module for architecture remediation."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ProviderSpec:
    """A single provider getter specification."""

    function_name: str
    module_path: str
    symbol_name: str


def parse_provider_spec(raw_value: str) -> ProviderSpec:
    """Parse `function_name=module.path:SymbolName`."""

    function_name, separator, import_target = raw_value.partition("=")
    module_path, symbol_separator, symbol_name = import_target.partition(":")
    if not function_name or not separator or not module_path or not symbol_separator or not symbol_name:
        raise ValueError(
            "Provider spec must use the format function_name=module.path:SymbolName"
        )
    return ProviderSpec(
        function_name=function_name.strip(),
        module_path=module_path.strip(),
        symbol_name=symbol_name.strip(),
    )


def build_default_output_path(module_name: str) -> Path:
    """Return the default provider module path for an app."""

    return REPO_ROOT / "apps" / module_name / "application" / "repository_provider.py"


def normalize_output_path(path_text: str | None, module_name: str) -> Path:
    """Resolve the output file path inside the repository."""

    if not path_text:
        output_path = build_default_output_path(module_name)
    else:
        candidate = Path(path_text)
        output_path = candidate if candidate.is_absolute() else REPO_ROOT / candidate

    resolved = output_path.resolve()
    resolved.relative_to(REPO_ROOT)
    return resolved


def render_provider_module(module_name: str, provider_specs: Sequence[ProviderSpec]) -> str:
    """Render the provider module source code."""

    grouped_imports: dict[str, list[str]] = defaultdict(list)
    for spec in provider_specs:
        grouped_imports[spec.module_path].append(spec.symbol_name)

    lines = [
        f'"""Provider helpers for {module_name} application consumers."""',
        "",
        "from __future__ import annotations",
        "",
    ]

    for module_path in sorted(grouped_imports):
        symbols = sorted(set(grouped_imports[module_path]))
        if len(symbols) == 1:
            lines.append(f"from {module_path} import {symbols[0]}")
        else:
            lines.append(f"from {module_path} import (")
            for symbol in symbols:
                lines.append(f"    {symbol},")
            lines.append(")")
        lines.append("")

    exported_names: list[str] = []
    for spec in provider_specs:
        lines.extend(
            [
                f"def {spec.function_name}() -> {spec.symbol_name}:",
                f'    """Return the default {spec.symbol_name} instance."""',
                "",
                f"    return {spec.symbol_name}()",
                "",
            ]
        )
        exported_names.append(spec.function_name)

    lines.append(f"__all__ = {sorted(exported_names)!r}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold an application provider module.")
    parser.add_argument(
        "--module",
        required=True,
        help="App module name under apps/.",
    )
    parser.add_argument(
        "--output",
        help="Output file path. Defaults to apps/<module>/application/repository_provider.py",
    )
    parser.add_argument(
        "--provider",
        action="append",
        required=True,
        help="Provider spec in the form function_name=module.path:SymbolName",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists.",
    )
    args = parser.parse_args()

    provider_specs = [parse_provider_spec(item) for item in args.provider]
    output_path = normalize_output_path(args.output, args.module)

    if output_path.exists() and not args.force:
        parser.error(f"Output file already exists: {output_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_provider_module(args.module, provider_specs),
        encoding="utf-8",
    )
    print(output_path.relative_to(REPO_ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
