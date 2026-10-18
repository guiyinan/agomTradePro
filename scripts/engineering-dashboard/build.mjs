#!/usr/bin/env node
/** Build an offline dashboard from one immutable Git revision (or explicit draft). */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { BASELINE, HIERARCHY, REGISTRY, changesBetween, serializeData, summarize, validateRegistry } from './model.mjs';

const assets = path.dirname(fileURLToPath(import.meta.url));

/** Execute Git without a shell. @param {string} root @param {string[]} args @returns {string} */
function git(root, args) {
  return execFileSync('git', ['-C', root, ...args], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }).trimEnd();
}

/** Read a path at a frozen revision. @param {string} root @param {string} sha @param {string} name @returns {string|null} */
function atRevision(root, sha, name) {
  const files = git(root, ['ls-tree', '--name-only', sha, '--', name]).split('\n');
  return files.includes(name) ? execFileSync('git', ['-C', root, 'show', `${sha}:${name}`], { encoding: 'utf8', maxBuffer: 16 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] }) : null;
}

/** Generate a single portable HTML without modifying the ledger or Git index.
 * @param {{root?: string, output?: string, ref?: string, workingTree?: boolean, history?: number}} options
 * @returns {string}
 */
export function buildDashboard(options = {}) {
  const root = path.resolve(options.root ?? path.join(assets, '../..'));
  const sha = git(root, ['rev-parse', '--verify', '--end-of-options', `${options.ref ?? 'HEAD'}^{commit}`]);
  const output = path.resolve(root, options.output ?? 'reports/engineering-progress/index.html');
  const read = name => options.workingTree ? readFileSync(path.join(root, name), 'utf8') : atRevision(root, sha, name);
  const registryText = read(REGISTRY);
  if (!registryText) throw new Error(`No ${REGISTRY} at ${sha}`);
  const registry = validateRegistry(JSON.parse(registryText));
  const warnings = [];
  const sources = [{ path: REGISTRY, sha256: createHash('sha256').update(registryText).digest('hex') }];
  const optional = name => {
    let raw;
    try { raw = read(name); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    if (!raw) { warnings.push(`缺少辅助账本：${name}`); return null; }
    sources.push({ path: name, sha256: createHash('sha256').update(raw).digest('hex') });
    return JSON.parse(raw);
  };
  const baseline = optional(BASELINE);
  const hierarchy = optional(HIERARCHY);
  if (hierarchy && hierarchy.registry_version !== registry.version) {
    warnings.push(`层次快照 ${hierarchy.registry_version} 落后或不同于主注册表 ${registry.version}；所有状态与执行焦点均读取主注册表。`);
  }
  const unknown = registry.closure_backlog.units.filter(unit => !['repository', 'production', 'external', 'governance'].includes(unit.execution_mode));
  if (unknown.length) warnings.push(`存在未知执行模式：${unknown.map(unit => unit.id).join('、')}`);
  const unknownStatuses = registry.closure_backlog.units.filter(unit => !['completed', 'active', 'planned', 'waiting_dependency', 'awaiting_production', 'blocked_external', 'deferred', 'archived'].includes(unit.status));
  if (unknownStatuses.length) warnings.push(`存在未知状态，保留原文且不计为完成：${unknownStatuses.map(unit => unit.id).join('、')}`);
  const historyLimit = options.history ?? 12;
  if (!Number.isInteger(historyLimit) || historyLimit < 1 || historyLimit > 100) throw new Error('History must be an integer from 1 to 100');
  const commits = git(root, ['log', '--first-parent', `-n${historyLimit}`, '--format=%H', sha]).split('\n').filter(Boolean);
  const history = commits.map(commit => {
    const raw = atRevision(root, commit, REGISTRY);
    const snapshot = raw ? validateRegistry(JSON.parse(raw)) : null;
    return { sha: commit, date: git(root, ['show', '-s', '--format=%cI', commit]), subject: git(root, ['show', '-s', '--format=%s', commit]), summary: snapshot ? summarize(snapshot.closure_backlog.units) : null };
  });
  const parent = git(root, ['rev-list', '--parents', '-n1', sha]).split(' ')[1];
  const previousRaw = options.workingTree ? atRevision(root, sha, REGISTRY) : parent ? atRevision(root, parent, REGISTRY) : null;
  const previous = previousRaw ? validateRegistry(JSON.parse(previousRaw)) : null;
  const sourceBase = process.env.GITHUB_ACTIONS === 'true' && /^[\w.-]+\/[\w.-]+$/.test(process.env.GITHUB_REPOSITORY ?? '')
    ? `https://github.com/${process.env.GITHUB_REPOSITORY}/blob/${sha}/`
    : `${path.relative(path.dirname(output), root).split(path.sep).join('/') || '.'}/`;
  const payload = {
    registry, baseline, warnings, sources, history, sourceBase,
    snapshot: { sha, committedAt: history[0].date, subject: history[0].subject, mode: options.workingTree ? 'working-tree' : 'commit', comparison: previous ? (options.workingTree ? 'HEAD' : 'first-parent') : 'unavailable' },
    summary: summarize(registry.closure_backlog.units), changes: changesBetween(previous, registry),
    inventory: git(root, ['ls-tree', '-r', '--name-only', sha, '--', 'governance']).split('\n').filter(name => name.endsWith('.json')),
  };
  const html = readFileSync(path.join(assets, 'index.template.html'), 'utf8')
    .replace('/* DASHBOARD_CSS */', () => readFileSync(path.join(assets, 'dashboard.css'), 'utf8'))
    .replace('/* DASHBOARD_DATA */', () => serializeData(payload))
    .replace('/* DASHBOARD_JS */', () => readFileSync(path.join(assets, 'dashboard.js'), 'utf8'));
  mkdirSync(path.dirname(output), { recursive: true });
  const temporary = `${output}.${process.pid}.tmp`;
  writeFileSync(temporary, html, 'utf8');
  renameSync(temporary, output);
  return output;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const { values } = parseArgs({ options: { root: { type: 'string' }, output: { type: 'string' }, ref: { type: 'string' }, 'working-tree': { type: 'boolean' }, history: { type: 'string' } } });
    if (values.ref && values['working-tree']) throw new Error('--ref and --working-tree are mutually exclusive');
    console.log(buildDashboard({ ...values, workingTree: values['working-tree'], history: values.history ? Number(values.history) : undefined }));
  } catch (error) {
    console.error(`Dashboard build failed: ${error.message}`);
    process.exitCode = 1;
  }
}
