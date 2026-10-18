import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { buildDashboard } from './build.mjs';
import { installHooks } from './install-hooks.mjs';
import { changesBetween, serializeData, summarize, validateRegistry } from './model.mjs';

const assets = path.dirname(fileURLToPath(import.meta.url));
const unit = (id, status, mode = 'repository') => ({ id, status, execution_mode: mode, workstream_id: 'work', title: id, exit_gate: 'Actual scoped acceptance', depends_on: [] });
const ledger = units => ({ version: 'v1', execution_focus: { unit_id: units[0]?.id }, workstreams: [{ id: 'work', title: 'Work', documents: [] }], closure_backlog: { units } });
const runGit = (root, ...args) => execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
const decode = filename => JSON.parse(readFileSync(filename, 'utf8').match(/<script id="dashboard-data" type="application\/json">([\s\S]*?)<\/script>/)[1]);

function fixture(t) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'agom dashboard '));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  runGit(root, 'init');
  runGit(root, 'config', 'user.email', 'test@example.invalid');
  runGit(root, 'config', 'user.name', 'Dashboard test');
  runGit(root, 'config', 'commit.gpgsign', 'false');
  runGit(root, 'config', 'core.autocrlf', 'false');
  // Never inherit a developer's global hook path in a disposable test repository.
  runGit(root, 'config', 'core.hooksPath', '.git/hooks');
  mkdirSync(path.join(root, 'governance'), { recursive: true });
  writeFileSync(path.join(root, 'governance/active_plan_registry.json'), JSON.stringify(ledger([unit('A', 'active'), unit('B', 'deferred')])) + '\n');
  writeFileSync(path.join(root, 'governance/governance_baseline.json'), '{"version":"baseline","business_module_count":2}\n');
  runGit(root, 'add', '.');
  runGit(root, 'commit', '-m', 'test: initial ledger');
  return root;
}

test('counts exclude deferred and archived from completed, retain unknown states', () => {
  const summary = summarize([unit('A', 'completed'), unit('B', 'deferred'), unit('C', 'archived'), unit('D', 'new-status')]);
  assert.equal(summary.completed, 1);
  assert.equal(summary.total, 4);
  assert.equal(summary.statuses['new-status'], 1);
});

test('invalid references and duplicate IDs cannot silently create metrics', () => {
  assert.throws(() => validateRegistry(ledger([unit('A', 'active'), unit('A', 'completed')])), /Duplicate/);
  const bad = unit('A', 'active');
  bad.depends_on = ['missing'];
  assert.throws(() => validateRegistry(ledger([bad])), /Missing dependency/);
});

test('deltas distinguish reopened, added, removed and amended units', () => {
  const before = ledger([unit('A', 'completed'), unit('B', 'active'), unit('C', 'planned')]);
  const after = ledger([unit('A', 'active'), { ...unit('C', 'planned'), exit_gate: 'Amended' }, unit('D', 'planned')]);
  assert.deepEqual(changesBetween(before, after).map(item => [item.id, item.kind]), [['A', 'status'], ['C', 'details'], ['D', 'added'], ['B', 'removed']]);
});

test('embedded ledger cannot terminate the script element', () => {
  const malicious = { title: '</script><script>alert(1)</script>\u2028' };
  const encoded = serializeData(malicious);
  assert.ok(!encoded.includes('<'));
  assert.deepEqual(JSON.parse(encoded), malicious);
});

test('unexpected status names cannot modify count object prototypes', () => {
  const result = summarize([unit('A', '__proto__'), unit('B', 'constructor')]);
  assert.equal(result.completed, 0);
  assert.equal(result.statuses.__proto__, 1);
  assert.equal(result.statuses.constructor, 1);
});

test('HEAD build excludes dirty changes, preserves source hash and is deterministic', t => {
  const root = fixture(t);
  const raw = readFileSync(path.join(root, 'governance/active_plan_registry.json'), 'utf8');
  writeFileSync(path.join(root, 'governance/active_plan_registry.json'), JSON.stringify(ledger([unit('A', 'completed')])));
  const filename = buildDashboard({ root });
  const first = readFileSync(filename, 'utf8');
  const data = decode(filename);
  assert.equal(data.summary.completed, 0);
  assert.equal(data.summary.total, 2);
  assert.equal(data.sources[0].sha256, createHash('sha256').update(raw).digest('hex'));
  assert.equal(data.snapshot.comparison, 'unavailable');
  assert.ok(data.warnings.some(message => message.includes('active-plan-hierarchy')));
  buildDashboard({ root });
  assert.equal(readFileSync(filename, 'utf8'), first);
  const draft = decode(buildDashboard({ root, workingTree: true, output: 'reports/draft.html' }));
  assert.equal(draft.snapshot.mode, 'working-tree');
  assert.equal(draft.summary.completed, 1);
  assert.equal(draft.changes.length, 2);
  writeFileSync(path.join(root, 'governance/active_plan_registry.json'), '{broken');
  assert.throws(() => buildDashboard({ root, workingTree: true }));
  assert.equal(readFileSync(filename, 'utf8'), first, 'A failed build must retain the previous complete HTML');
});

test('history and comparison bind to commit rather than file timestamps', t => {
  const root = fixture(t);
  const initial = runGit(root, 'rev-parse', 'HEAD');
  writeFileSync(path.join(root, 'governance/active_plan_registry.json'), JSON.stringify(ledger([unit('A', 'completed'), unit('B', 'deferred')])));
  runGit(root, 'add', 'governance/active_plan_registry.json');
  runGit(root, 'commit', '-m', 'test: scoped closure');
  const current = decode(buildDashboard({ root }));
  assert.equal(current.history[0].summary.completed, 1);
  assert.equal(current.history[1].summary.completed, 0);
  assert.deepEqual(current.changes.map(change => change.id), ['A']);
  const historical = decode(buildDashboard({ root, ref: initial }));
  assert.equal(historical.summary.completed, 0);
  assert.equal(historical.snapshot.sha, initial);
});

test('stale hierarchy never overrides canonical focus or counts', t => {
  const root = fixture(t);
  mkdirSync(path.join(root, 'docs/governance'), { recursive: true });
  writeFileSync(path.join(root, 'docs/governance/active-plan-hierarchy.json'), JSON.stringify({ registry_version: 'old', execution_focus: { unit_id: 'WRONG' }, summary: { closure_unit_count: 999 } }));
  const data = decode(buildDashboard({ root, workingTree: true }));
  assert.equal(data.registry.execution_focus.unit_id, 'A');
  assert.equal(data.summary.total, 2);
  assert.ok(data.warnings.some(message => message.includes('落后或不同')));
});

test('commit hook refreshes automatically, chains prior hooks, installs idempotently in paths with spaces', t => {
  const root = fixture(t);
  cpSync(assets, path.join(root, 'scripts/engineering-dashboard'), { recursive: true });
  const hook = path.join(root, '.git/hooks/post-commit');
  writeFileSync(hook, '#!/bin/sh\nprintf preserved > previous-hook.txt\n', { mode: 0o755 });
  chmodSync(hook, 0o755);
  installHooks(root);
  const installed = readFileSync(hook, 'utf8');
  installHooks(root);
  assert.equal(readFileSync(hook, 'utf8'), installed);
  runGit(root, 'add', 'scripts');
  runGit(root, 'commit', '-m', 'test: trigger dashboard');
  assert.ok(existsSync(path.join(root, 'previous-hook.txt')));
  const data = decode(path.join(root, 'reports/engineering-progress/index.html'));
  assert.equal(data.snapshot.sha, runGit(root, 'rev-parse', 'HEAD'));
  assert.equal(data.snapshot.mode, 'commit');
});
