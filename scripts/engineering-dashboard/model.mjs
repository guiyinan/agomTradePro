/** Pure projections of the canonical engineering ledger. No inferred completion. */
export const REGISTRY = 'governance/active_plan_registry.json';
export const BASELINE = 'governance/governance_baseline.json';
export const HIERARCHY = 'docs/governance/active-plan-hierarchy.json';
export const STATUSES = {
  completed: '已完成', active: '进行中', planned: '已规划',
  waiting_dependency: '等待依赖', awaiting_production: '待生产验收',
  blocked_external: '外部阻塞', deferred: '已延期', archived: '已归档',
};
export const MODES = { repository: '仓库实现', production: '生产验收', external: '外部验收', governance: '工程治理' };

/** Validate structural assumptions so malformed ledgers cannot produce green metrics.
 * @param {object} registry @returns {object}
 */
export function validateRegistry(registry) {
  if (!Array.isArray(registry.workstreams) || !Array.isArray(registry.closure_backlog?.units)) {
    throw new Error('Registry requires workstreams and closure_backlog.units arrays');
  }
  const units = registry.closure_backlog.units;
  const ids = new Set();
  for (const unit of units) {
    for (const field of ['id', 'title', 'status', 'execution_mode', 'workstream_id', 'exit_gate']) {
      if (typeof unit[field] !== 'string' || !unit[field]) throw new Error(`Invalid unit ${field}`);
    }
    if (ids.has(unit.id)) throw new Error(`Duplicate unit: ${unit.id}`);
    ids.add(unit.id);
    if (!Array.isArray(unit.depends_on) || unit.depends_on.some(id => typeof id !== 'string')) {
      throw new Error(`Invalid dependencies: ${unit.id}`);
    }
  }
  for (const unit of units) {
    for (const id of unit.depends_on) if (!ids.has(id)) throw new Error(`Missing dependency: ${id}`);
  }
  if (registry.execution_focus?.unit_id && !ids.has(registry.execution_focus.unit_id)) {
    throw new Error('Execution focus does not reference a registered unit');
  }
  return registry;
}

/** Count only explicit statuses; deferred/archived are never counted as completed.
 * @param {object[]} units @returns {object}
 */
export function summarize(units) {
  const statuses = Object.fromEntries(Object.keys(STATUSES).map(key => [key, 0]));
  for (const unit of units) {
    const count = Object.hasOwn(statuses, unit.status) ? statuses[unit.status] : 0;
    Object.defineProperty(statuses, unit.status, { value: count + 1, enumerable: true, writable: true, configurable: true });
  }
  return { total: units.length, completed: statuses.completed, statuses };
}

/** Compare ledger records, including removed and reopened units.
 * @param {object|null} previous @param {object} current @returns {object[]}
 */
export function changesBetween(previous, current) {
  if (!previous) return [];
  const before = new Map(previous.closure_backlog.units.map(unit => [unit.id, unit]));
  const after = new Map(current.closure_backlog.units.map(unit => [unit.id, unit]));
  const changes = [];
  for (const [id, unit] of after) {
    const old = before.get(id);
    if (!old) changes.push({ id, kind: 'added', from: null, to: unit.status });
    else if (old.status !== unit.status) changes.push({ id, kind: 'status', from: old.status, to: unit.status });
    else if (JSON.stringify(old) !== JSON.stringify(unit)) changes.push({ id, kind: 'details', from: old.status, to: unit.status });
  }
  for (const [id, unit] of before) if (!after.has(id)) changes.push({ id, kind: 'removed', from: unit.status, to: null });
  return changes;
}

/** Safely embed JSON inside an HTML script data block.
 * @param {object} value @returns {string}
 */
export function serializeData(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/\u2028/g, '\\u2028').replace(/\u2029/g, '\\u2029');
}
