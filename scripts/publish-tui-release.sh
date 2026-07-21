#!/bin/sh
set -eu

backend_version="${1:-${AGOM_RELEASE_VERSION:-unknown}}"
metadata_path="${TUI_METADATA_PATH:-config/tui/published/tui_operation_graph.published.json}"
evidence_path="${TUI_EVIDENCE_PATH:-config/tui/generated/tui_operation_evidence.generated.json}"
registry_key="${TUI_REGISTRY_KEY:-default}"
publisher="tui-metadata-compiler/scripts/publish_tui_metadata.py"
review_note="Automatic release publish ${backend_version}"

if [ ! -f "$metadata_path" ]; then
  echo "[ERROR] reviewed TUI metadata is missing: $metadata_path" >&2
  exit 1
fi

echo "[INFO] publishing reviewed TUI metadata for release $backend_version"
if [ -f "$evidence_path" ]; then
  python "$publisher" "$metadata_path" \
    --approve \
    --registry-key "$registry_key" \
    --generation-source mixed \
    --backend-version "$backend_version" \
    --review-note "$review_note" \
    --source-evidence-path "$evidence_path"
else
  python "$publisher" "$metadata_path" \
    --approve \
    --registry-key "$registry_key" \
    --generation-source mixed \
    --backend-version "$backend_version" \
    --review-note "$review_note"
fi

echo "[INFO] verifying active TUI metadata against release $backend_version"
python "$publisher" "$metadata_path" \
  --check \
  --registry-key "$registry_key"
