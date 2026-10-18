#!/usr/bin/env node
/** Install a managed hook alongside existing hooks, without changing core.hooksPath. */
import { execFileSync } from 'node:child_process';
import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const marker = '# agom-engineering-dashboard-v1';

/** Preserve any existing hook as a sibling and invoke it first.
 * @param {string} root @returns {string[]}
 */
export function installHooks(root) {
  const configured = execFileSync('git', ['-C', root, 'rev-parse', '--git-path', 'hooks'], { encoding: 'utf8' }).trim();
  const hooks = path.resolve(root, configured);
  mkdirSync(hooks, { recursive: true });
  const installed = [];
  for (const name of ['post-commit', 'post-merge', 'post-checkout']) {
    const target = path.join(hooks, name);
    const backup = `${target}.before-engineering-dashboard`;
    if (existsSync(target)) {
      const current = readFileSync(target, 'utf8');
      if (current.includes(marker)) { installed.push(target); continue; }
      if (existsSync(backup)) throw new Error(`Backup already exists; refusing to overwrite ${backup}`);
      writeFileSync(backup, current, { mode: 0o755 });
      chmodSync(backup, 0o755);
    }
    const source = `#!/bin/sh
${marker}
previous="$(dirname "$0")/${name}.before-engineering-dashboard"
previous_status=0
if [ -x "$previous" ]; then "$previous" "$@" || previous_status=$?; fi
root="$(git rev-parse --show-toplevel)" || exit 0
if [ -f "$root/scripts/engineering-dashboard/build.mjs" ]; then
  if command -v node >/dev/null 2>&1; then
    node "$root/scripts/engineering-dashboard/build.mjs" --root "$root" || echo "Engineering dashboard refresh failed; rerun the build command. Existing HTML may be stale." >&2
  else
    echo "Engineering dashboard requires Node.js on PATH. Existing HTML may be stale." >&2
  fi
fi
exit "$previous_status"
`;
    writeFileSync(target, source, { mode: 0o755 });
    chmodSync(target, 0o755);
    installed.push(target);
  }
  return installed;
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = process.argv[2] ? path.resolve(process.argv[2]) : path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
  for (const hook of installHooks(root)) console.log(`Installed ${hook}`);
}
