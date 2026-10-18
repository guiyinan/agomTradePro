"""Publish only completed, source-bound TUX10 local evidence."""
from __future__ import annotations
import hashlib
import json
import re
import xml.etree.ElementTree as ET
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path.cwd()
QA = ROOT / ".tmp/tux10-final-f79b22a4a-02"
OUT = ROOT / "docs/testing/tui-task-first-2026-10-17/tux10"
OWNED = [
 "frontend/tui-workbench/src/50-shell.js",
 "frontend/tui-workbench/src/38-task-focus-panels.js",
 "frontend/tui-workbench/tests/workbench-browser.test.mjs",
 "core/templates/terminal/tui_workbench.html",
 "tests/component/test_tui_task_first_browser.py",
 "tests/component/test_tui_research_task_browser.py",
 "tests/component/test_tui_task_focus_browser.py",
 "tests/support/tui_research/market_consumer_state.py",
 "static/js/tui-workbench.js",
 "config/tui/agomtui-runtime.manifest.json",
]

def sha(path: Path) -> str:
 return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(path: Path, value: object) -> None:
 path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf8")

def main() -> None:
 freeze = json.loads((QA/"frozen-inputs.json").read_text())
 base = freeze["base_head"]
 assert subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()==base
 assert not subprocess.check_output(["git","diff","--cached","--name-only"],text=True).strip()
 for name, record in freeze["source_inputs"].items():
  assert sha(ROOT/name)==record["raw_sha256"], name
 required = ["node-full-final-01","browser-inventory-final-01","backend-integration-final-01","runtime-check-02","tui-static-final-03","retirement-01"]
 for label in required:
  d=json.loads((QA/(label+".json")).read_text())
  assert d.get("exit_code")==0 and d.get("frozen_acceptance_valid") is True and d.get("source_inputs_unchanged") is True,label
 backend_cases=list(ET.parse(QA/"backend-integration-final-01.xml").iter("testcase"))
 browser_cases=list(ET.parse(QA/"browser-inventory-final-01.xml").iter("testcase"))
 assert len(backend_cases)==428 and len(browser_cases)==19
 assert not any(c.find("failure") is not None or c.find("error") is not None or c.find("skipped") is not None for c in backend_cases+browser_cases)
 node_output=(QA/"node-full-final-01.log").read_text(encoding="utf8")
 assert re.search(r"tests 160\b",node_output) and re.search(r"pass 160\b",node_output) and re.search(r"fail 0\b",node_output)
 protected={"tests/unit/simulated_trading/test_ash01_settlement_regressions.py":("7014ccdbf73d6ac77e0d10e5232b67f2c54ebca2790964ffddae670fb8e8add1"," A"),"tests/unit/account/test_manual_trade_fee_availability.py":("763363a4be8e52d1398e6ba650419eccae8dd97f5b088a87a8ac594dd6b13521","??")}
 for name,(expected,status) in protected.items():
  assert sha(ROOT/name)==expected,name
  assert subprocess.check_output(["git","status","--porcelain","--",name],text=True).rstrip("\n")[:2]==status,name
 assert not OUT.exists(),"Never overwrite evidence"
 OUT.mkdir(parents=True)
 checks={}
 for p in sorted(QA.glob("*.json")):
  d=json.loads(p.read_text())
  if "command" in d:
   assert d.get("exit_code")==0,p.name
   checks[p.stem]={"record":p.name,"exit_code":d["exit_code"],"source_inputs_unchanged":d.get("source_inputs_unchanged"),"frozen_acceptance_valid":d.get("frozen_acceptance_valid")}
   shutil.copy2(p,OUT/p.name)
   log=p.with_suffix(".log")
   if log.exists():shutil.copy2(log,OUT/log.name)
 for name in ["frozen-inputs.json","preflight-authorized.json","browser-inventory-final-01.xml","backend-integration-final-01.xml"]:
  shutil.copy2(QA/name,OUT/name)
 for directory in ["browser","source-artifacts","surface-report"]:
  if (QA/directory).exists():shutil.copytree(QA/directory,OUT/directory)
 shutil.copytree(ROOT/".tmp/tux10-final-reviews-02",OUT/"reviews")
 repro=OUT/"reproduce";repro.mkdir()
 for name in ["run_phase.py","tux10_isolated_settings.py","test_tux10_surface_inventory.py","test_quote_snapshot_market_date_boundary.py","build_surface_report.py","check_matrix_candidate.py"]:
  shutil.copy2(QA/name,repro/name)
 shutil.copy2(__file__,repro/"package_evidence.py")
 previous=OUT/"previous-round";previous.mkdir()
 old=ROOT/".tmp/tux10-final-f79b22a4a-01"
 for p in old.glob("*.json"):
  d=json.loads(p.read_text())
  if "command" in d or p.name=="frozen-inputs.json":
   shutil.copy2(p,previous/p.name)
   log=p.with_suffix(".log")
   if log.exists():shutil.copy2(log,previous/log.name)
 shutil.copy2(ROOT/".tmp/tux10-final-handoff-doc-candidate/human-study-protocol.md",OUT/"human-study-protocol.md")
 shutil.copy2(ROOT/".tmp/tux10-final-docs-02/user-guide.md",OUT/"user-guide.md")
 acceptance={"unit":"TUX-10","status":"Frozen local repository journeys verified; final registry/governance/commit and handoff pending","base_commit":base,"recorded_at":datetime.now(UTC).isoformat(),"freeze_sha256":sha(QA/"frozen-inputs.json"),"frozen_input_count":len(freeze["source_inputs"]),"owned_content_paths":OWNED,"actual_checks":checks,"counts":{"backend":428,"frontend_node":160,"real_django_browser_cases":10,"metadata_role_inventory":1,"quote_repository_boundary":2,"existing_pure_market_date_boundary":6},"scope":"Actual local owner execution over synthetic source-bearing research facts and local authorized account records. One frozen integrated source; no mocked successful owner response. Metadata inventory proves declarations/role visibility, not all action execution.","type_and_architecture_scope":"No production Python, model, schema, owner API or module structure changed. Incremental production mypy is not applicable. Official runtime/check/static-source/metadata/freshness/module/retirement gates were executed. Existing ASH financial and execution-focus objects must remain exact.","network_evidence_limit":"Commands target local disposable SQLite/browser paths with in-test loopback fences where recorded. Those fences do not prove process-wide Django initialization or all external integrations.","remaining":["Five-person untrained-user study not executed; protocol supplied","Normal real external market owner200 remains unverified; unavailable recovery is real,200 projection tests are not live-source proof","Native PostgreSQL and large-portfolio scale performance unverified","No production deployment/release acceptance, paid runtime AI,QMT or real trading","Seventeen actions retain explicit review_dedupe disposition; independent diagnostic policy is not inferred from raw_debug"],"rollback":"Revert only TUX10-owned change set and matching official workbench/manifest/template asset versions; preserve all A-share commits, user files and financial records. Use a new unique rollback asset query key, verify official build/check and actual asset requests. No model migration or business DB rollback. Rollback procedure recorded, no production rollback executed."}
 dump(OUT/"acceptance.json",acceptance)
 print(json.dumps({"out":str(OUT),"checks":len(checks),"freeze":acceptance["freeze_sha256"]}))

if __name__=="__main__": main()
