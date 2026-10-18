"""Record a source-bound TUX10 command only after a fresh explicit handoff."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    qa = Path(__file__).resolve().parent
    # The proposal is intentionally insufficient to run this helper.
    preflight_path = qa / "preflight-authorized.json"
    if not preflight_path.is_file():
        raise SystemExit("No explicit post-Fee-A shared handoff: runtime QA is forbidden")
    config = json.loads(preflight_path.read_text(encoding="utf8"))
    if config.get("explicit_root_handoff_received") is not True:
        raise SystemExit("No shared integration lease")
    root = Path(config["repository_root"]).resolve()
    if len(sys.argv) < 3:
        raise SystemExit("Supply one new immutable phase label and explicit command")
    label, command = sys.argv[1], sys.argv[2:]
    if not re.fullmatch(r"[A-Za-z0-9-]+", label):
        raise SystemExit("Invalid phase label")
    record_path, log_path = qa / f"{label}.json", qa / f"{label}.log"
    if record_path.exists() or log_path.exists():
        raise SystemExit("Preserve previous records; use a new phase label")

    def current_head() -> str:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    if current_head() != config["base_head"]:
        raise SystemExit("Shared HEAD changed; a fresh handoff is required")

    def inputs() -> dict[str, dict[str, str]]:
        values = {}
        for name in config["source_paths"]:
            raw = (root / name).read_bytes()
            values[name] = {
                "raw_sha256": digest(raw),
                "lf_sha256": digest(raw.replace(b"\r\n", b"\n")),
            }
        return values

    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": os.pathsep.join((str(qa), str(root))),
            "DJANGO_SETTINGS_MODULE": config["settings_module"],
            "TUX10_RUN_LABEL": label,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf8",
        }
    )
    record = {
        "scope": "Local repository acceptance only; no human, production or financial authority",
        "base_head": current_head(),
        "command": command,
        "cwd": str(root),
        "settings_module": config["settings_module"],
        "settings_sha256": digest((qa / (config["settings_module"] + ".py")).read_bytes()),
        "handoff_preflight_sha256": digest(preflight_path.read_bytes()),
        "source_inputs": inputs(),
        "started_at": datetime.now(UTC).isoformat(),
    }
    freeze_path = qa / "frozen-inputs.json"
    if freeze_path.exists():
        frozen = json.loads(freeze_path.read_text(encoding="utf8"))
        if frozen["source_inputs"] != record["source_inputs"]:
            raise SystemExit("Frozen inputs changed; repair under a new recorded freeze")
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    with log_path.open("wb") as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
        record["pid"] = child.pid
        record_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
        )
        code = child.wait()
    raw = log_path.read_bytes()
    output = raw.decode("utf8", errors="replace")
    record.update(
        {
            "exit_code": code,
            "finished_at": datetime.now(UTC).isoformat(),
            "raw_stdout_sha256": digest(raw),
            "utf8_output_roundtrip_sha256": digest(output.encode("utf8")),
            "output": output,
            "source_inputs_after": inputs(),
            "head_after": current_head(),
        }
    )
    record["source_inputs_unchanged"] = record["source_inputs"] == record["source_inputs_after"]
    record["frozen_acceptance_valid"] = not freeze_path.exists() or (
        record["source_inputs_unchanged"] and record["head_after"] == config["base_head"]
    )
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({"phase": label, "exit_code": code, "record": str(record_path)}), flush=True)
    print(output[-4000:], flush=True)
    return code if record["frozen_acceptance_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
