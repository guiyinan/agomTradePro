/* Offline, read-only project management view. Ledger text always uses textContent. */
(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('dashboard-data').textContent);
  const registry = data.registry;
  const units = registry.closure_backlog.units;
  const statuses = { completed: '已完成', active: '进行中', planned: '已规划', waiting_dependency: '等待依赖', awaiting_production: '待生产验收', blocked_external: '外部阻塞', deferred: '已延期', archived: '已归档' };
  const modes = { repository: '仓库实现', production: '生产验收', external: '外部验收', governance: '工程治理' };
  const streamStatuses = { active: '推进中', production_validation: '生产验证', external_validation: '外部验证', blocked_external: '外部阻塞' };
  // Display translations only; identity, status, scope and ownership remain in the ledger.
  const streamNames = {
    'evidence-hard-gate': '证据治理与决策硬闸', 'strategy-research-production': '策略研究与生产验收',
    'data-production-reliability': '数据中心与生产可靠性', 'system-audit-consolidation': '统一审计',
    'web-to-tui-m5': 'Web → TUI 生产切换', 'terminal-agent-multi-user-runtime': 'Agent 多用户运行时',
    'ai-native-release': 'AI Native 发布验收', 'qmt-live-bridge': 'QMT 实盘桥接',
    'tui-usability-governance': 'TUI 可用性与交互治理', 'index-dividend-thermometer': '指数红利温度分析',
    'repository-maintenance-governance': '工程维护与存量治理', 'manager-holdings-plan-review': '机构持仓计划审查',
    'a-share-usability': 'A 股研究与交易闭环', 'review-queue': '历史计划审查',
  };
  const viewInfo = {
    overview: ['项目总览', '把握项目主线、当前重点与交付状态。'],
    tasks: ['任务看板', '按主线、状态与验收范围组织任务，点击卡片查看完整上下文。'],
    roadmap: ['阶段路线', '沿登记阶段查看任务分布与退出条件。'],
    activity: ['提交动态', '追踪机器账本随提交发生的变化。'],
    sources: ['数据来源', '核对来源版本、文件校验值与统计口径。'],
  };
  const lookup = (map, key, fallback = key) => Object.hasOwn(map, key) ? map[key] : fallback;
  const statusName = status => lookup(statuses, status, `未知状态：${status}`);
  const byId = new Map(units.map(unit => [unit.id, unit]));
  const focusId = registry.execution_focus?.unit_id;
  const focusUnit = byId.get(focusId);
  const streamMap = new Map(registry.workstreams.map(stream => [stream.id, stream]));
  for (const unit of units) if (!streamMap.has(unit.workstream_id)) streamMap.set(unit.workstream_id, { id: unit.workstream_id, title: `历史 / 特殊归属 · ${unit.workstream_id}`, documents: [], legacy: true });
  const streams = [...streamMap.values()].sort((a, b) => Number(b.id === focusUnit?.workstream_id) - Number(a.id === focusUnit?.workstream_id));
  const streamName = id => lookup(streamNames, id, streamMap.get(id)?.title ?? id);
  const closed = records => records.filter(unit => unit.status === 'completed').length;
  const unresolved = unit => unit.depends_on.filter(id => byId.get(id)?.status !== 'completed');
  const attentionNeeded = unit => !['completed', 'deferred', 'archived'].includes(unit.status) && (['waiting_dependency', 'awaiting_production', 'blocked_external'].includes(unit.status) || unresolved(unit).length > 0);
  const attentionUnits = units.filter(attentionNeeded);
  const date = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'short', timeStyle: 'short', hour12: false }).format(new Date(value));
  const $ = id => document.getElementById(id);
  const node = (tag, text, className) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
  };
  const add = (parent, ...children) => { parent.append(...children); return parent; };
  const button = (text, action, className) => {
    const element = node('button', text, className);
    element.type = 'button';
    element.addEventListener('click', action);
    return element;
  };
  const badge = status => node('span', statusName(status), `tag ${Object.hasOwn(statuses, status) ? status : ''}`);
  const link = (name, label = name) => {
    if (typeof name !== 'string' || !/^[\w./-]+$/.test(name) || name.startsWith('/') || name.split('/').includes('..')) return node('span', label);
    const element = node('a', label);
    element.href = data.sourceBase + name.split('/').map(encodeURIComponent).join('/');
    return element;
  };
  const progress = (completed, total) => {
    const bar = node('progress');
    bar.max = total || 1;
    bar.value = completed;
    bar.setAttribute('aria-label', `已完成 ${completed} / ${total}`);
    return bar;
  };
  let layout = 'board';
  let attentionOnly = false;
  let currentView = 'overview';

  /** Switch the workspace view and retain the current task filters. @param {string} view @param {boolean} updateHash @returns {void} */
  function showView(view, updateHash = true) {
    if (!Object.hasOwn(viewInfo, view)) view = 'overview';
    currentView = view;
    for (const section of document.querySelectorAll('.view')) section.hidden = section.id !== `view-${view}`;
    for (const item of document.querySelectorAll('nav button')) {
      if (item.dataset.view === view) item.setAttribute('aria-current', 'page');
      else item.removeAttribute('aria-current');
    }
    $('page-title').textContent = viewInfo[view][0];
    $('breadcrumb-view').textContent = viewInfo[view][0];
    $('page-description').textContent = viewInfo[view][1];
    if (updateHash) history.replaceState(null, '', `#${view}`);
    window.scrollTo(0, 0);
  }

  /** Reset filters before following a project or summary shortcut. @returns {void} */
  function clearFilters() {
    for (const id of ['search', 'stream', 'status', 'mode']) $(id).value = '';
    attentionOnly = false;
    $('attention-filter').setAttribute('aria-pressed', 'false');
  }

  /** Open a task selection without changing the source ledger. @param {object} filters @returns {void} */
  function openTasks(filters = {}) {
    clearFilters();
    for (const id of ['stream', 'status', 'mode']) if (filters[id]) $(id).value = filters[id];
    attentionOnly = Boolean(filters.attention);
    $('attention-filter').setAttribute('aria-pressed', String(attentionOnly));
    renderTasks();
    showView('tasks');
  }

  /** Show the full task contract and upstream/downstream dependencies. @param {string} id @returns {void} */
  function openDetail(id) {
    const unit = byId.get(id);
    if (!unit) return;
    const stream = streamMap.get(unit.workstream_id);
    const content = $('detail-content');
    content.replaceChildren();
    $('detail-code').textContent = `TASK / ${unit.id}`;
    const heading = node('h2', unit.title, 'detail-title');
    heading.id = 'detail-title';
    add(content, node('p', streamName(unit.workstream_id), 'detail-eyebrow'), heading, badge(unit.status));
    const facts = node('dl', undefined, 'detail-facts');
    for (const [label, value] of [['优先级', unit.priority ?? '未登记'], ['验收范围', lookup(modes, unit.execution_mode)], ['所属阶段', `Wave ${unit.wave ?? '未登记'}`], ['主线负责人', stream?.owner ?? '未登记'], ['任务负责人', unit.owner ?? '未单独登记'], ['截止日期', '未登记']]) add(facts, node('dt', label), node('dd', value));
    content.append(facts);
    const section = (title, text) => add(node('section', undefined, 'detail-section'), node('h3', title), node('p', text));
    content.append(section('完成 / 退出条件', unit.exit_gate));
    if (id === focusId) content.append(add(node('section', undefined, 'detail-section'), add(node('details'), node('summary', '展开当前执行约束（账本原文）'), node('p', registry.execution_focus?.policy ?? '未登记'))));
    const dependencies = add(node('section', undefined, 'detail-section'), node('h3', '前置依赖'));
    for (const dependency of unit.depends_on) {
      const jump = button('', () => openDetail(dependency), 'dependency');
      add(jump, node('code', dependency), node('span', streamName(byId.get(dependency)?.workstream_id)), badge(byId.get(dependency)?.status ?? 'unknown'));
      dependencies.append(jump);
    }
    if (!unit.depends_on.length) dependencies.append(node('p', '无登记依赖。'));
    const pending = unresolved(unit);
    if (pending.length) dependencies.append(node('p', `尚未完成的前置单元：${pending.join('、')}。这不改变本任务的登记状态。`, 'detail-notice'));
    content.append(dependencies);
    const downstream = units.filter(item => item.depends_on.includes(id));
    const next = add(node('section', undefined, 'detail-section'), node('h3', `后续依赖本任务 · ${downstream.length}`));
    for (const item of downstream) next.append(add(button('', () => openDetail(item.id), 'dependency'), node('code', item.id), badge(item.status)));
    if (!downstream.length) next.append(node('p', '没有登记的下游依赖。'));
    content.append(next);
    const documents = add(node('section', undefined, 'detail-section'), node('h3', '所属主线与计划文档'));
    documents.append(node('p', stream?.title ?? unit.workstream_id));
    if (stream?.next_gate) documents.append(add(node('details'), node('summary', '主线下一退出门'), node('p', stream.next_gate)));
    for (const document of stream?.documents ?? []) documents.append(link(document.path, `${lookup({ primary: '主计划', evidence: '证据', supporting: '支撑', matrix: '矩阵' }, document.role)} · ${document.path.split('/').at(-1)}`));
    if (!stream?.documents?.length) documents.append(node('p', '未登记关联文档。'));
    content.append(documents);
    content.append(node('p', '此视图只读。任务状态与退出门由机器注册表维护。', 'detail-notice'));
    if (!$('task-dialog').open) $('task-dialog').showModal();
    $('task-dialog').scrollTop = 0;
    $('close-detail').focus();
  }

  /** Create an accessible task card. @param {object} unit @returns {HTMLButtonElement} */
  function taskCard(unit) {
    const card = button('', () => openDetail(unit.id), `task-card${unit.id === focusId ? ' is-focus' : ''}`);
    card.dataset.unitId = unit.id;
    add(card, add(node('div', undefined, 'card-top'), node('code', unit.id), node('span', unit.priority ?? '—', 'priority')), node('h3', unit.title), node('p', streamName(unit.workstream_id), 'card-stream'), add(node('div', undefined, 'card-bottom'), badge(unit.status), node('span', unresolved(unit).length ? `${unresolved(unit).length} 项前置未完成` : lookup(modes, unit.execution_mode))));
    return card;
  }

  /** Render the same filtered task set as a board or table. @returns {void} */
  function renderTasks() {
    const query = $('search').value.trim().toLowerCase();
    const selected = units.filter(unit => (!$('stream').value || unit.workstream_id === $('stream').value) && (!$('status').value || unit.status === $('status').value) && (!$('mode').value || unit.execution_mode === $('mode').value) && (!attentionOnly || attentionNeeded(unit)) && (!query || [unit.id, unit.title, unit.exit_gate, unit.workstream_id, streamName(unit.workstream_id), streamMap.get(unit.workstream_id)?.owner].join(' ').toLowerCase().includes(query)));
    $('result-count').textContent = `${selected.length} / ${units.length} 个任务`;
    $('board-toggle').setAttribute('aria-pressed', String(layout === 'board'));
    $('list-toggle').setAttribute('aria-pressed', String(layout === 'list'));
    const context = $('task-context');
    context.replaceChildren();
    if ($('stream').value) {
      const stream = streamMap.get($('stream').value);
      const block = add(node('div', undefined, 'task-context'), add(node('div'), node('h2', streamName(stream.id)), node('p', `${stream.title} · ${stream.owner ?? '未登记负责人'}`)), button('返回全部主线', () => openTasks(), 'quiet-button'));
      context.append(block);
    }
    const container = $('task-results');
    container.replaceChildren();
    if (!selected.length) { container.append(node('p', '没有匹配的任务。调整筛选条件或点击重置。', 'empty')); return; }
    if (layout === 'list') {
      const table = node('table', undefined, 'task-table');
      const head = node('tr');
      for (const title of ['任务', '状态', '优先级', '验收范围', '前置未完成']) { const th = node('th', title); th.scope = 'col'; head.append(th); }
      table.append(add(node('thead'), head));
      const body = node('tbody');
      for (const unit of selected) {
        const row = node('tr');
        row.dataset.unitId = unit.id;
        add(row, add(node('td'), node('code', unit.id), button(unit.title, () => openDetail(unit.id), 'title-button'), node('small', streamName(unit.workstream_id))), add(node('td'), badge(unit.status)), node('td', unit.priority ?? '—'), node('td', lookup(modes, unit.execution_mode)), node('td', String(unresolved(unit).length)));
        body.append(row);
      }
      table.append(body);
      container.append(add(node('div', undefined, 'panel table-scroll'), table));
      return;
    }
    const lanes = [
      ['queued', '待推进', ['planned', 'waiting_dependency']], ['active', '进行中', ['active']],
      ['acceptance', '验收 / 阻塞', ['awaiting_production', 'blocked_external']],
      ['completed', '已完成', ['completed']], ['parked', '延期 / 归档', ['deferred', 'archived']],
    ];
    const known = new Set(lanes.flatMap(lane => lane[2]));
    const unknown = [...new Set(selected.map(unit => unit.status).filter(status => !known.has(status)))];
    if (unknown.length) lanes.push(['unknown', '待识别状态', unknown]);
    const board = node('div', undefined, 'board');
    for (const [key, title, states] of lanes) {
      const records = selected.filter(unit => states.includes(unit.status));
      const lane = node('section', undefined, `lane ${key}`);
      lane.setAttribute('aria-label', `${title} ${records.length} 个任务`);
      add(lane, add(node('div', undefined, 'lane-heading'), node('span', '', 'lane-dot'), node('h2', title), node('span', String(records.length))));
      records.sort((a, b) => Number(b.id === focusId) - Number(a.id === focusId));
      for (const unit of records) lane.append(taskCard(unit));
      if (!records.length) lane.append(node('p', '暂无匹配任务', 'lane-empty'));
      board.append(lane);
    }
    container.append(board);
  }

  $('header-sha').textContent = data.snapshot.sha.slice(0, 10);
  add($('snapshot'), node('strong', data.snapshot.mode === 'commit' ? '已提交版本 · 按提交更新' : '工作区预览 · 未提交'), node('span', `${date(data.snapshot.committedAt)}（上海）`));
  $('footer-version').textContent = `Registry ${registry.version} · ${data.snapshot.sha.slice(0, 10)}`;
  $('nav-count').textContent = String(units.length);
  $('sidebar-focus-id').textContent = focusId ?? '未指定';
  $('sidebar-focus-open').disabled = !focusUnit;
  $('sidebar-focus-open').addEventListener('click', () => openDetail(focusId));
  if (data.snapshot.mode === 'working-tree') $('draft-warning').append(node('div', '当前展示未提交账本；提交 SHA 仅为比较基准。', 'warning'));
  const activeCount = units.filter(unit => unit.status === 'active').length;
  const parkedCount = units.filter(unit => ['deferred', 'archived'].includes(unit.status)).length;
  for (const [title, count, hint, icon, style, filter] of [
    ['登记任务', units.length, `${registry.workstreams.length} 条主线 · ${parkedCount} 项延期 / 归档`, '▤', '', {}],
    ['已完成', closed(units), `按单元退出门确认 · ${units.length ? Math.round(closed(units) / units.length * 100) + '%' : '—'} 单元完成率`, '✓', 'accent', { status: 'completed' }],
    ['进行中', activeCount, focusId ? `仓库焦点 ${focusId}` : '尚未指定仓库执行焦点', '↗', '', { status: 'active' }],
    ['待关注', attentionUnits.length, '依赖未完成 / 待验收 / 外部阻塞', '◇', 'amber', { attention: true }],
  ]) $('metrics').append(add(button('', () => openTasks(filter), `metric ${style}`), node('span', title, 'metric-label'), node('span', icon, 'metric-icon'), node('strong', String(count), 'metric-number'), node('span', hint, 'metric-hint')));

  $('stream-count').textContent = `${registry.workstreams.length} 条主线`;
  for (const stream of streams) {
    const records = units.filter(unit => unit.workstream_id === stream.id);
    const row = node('tr', undefined, stream.id === focusUnit?.workstream_id ? 'focus-row' : '');
    const name = button(streamName(stream.id), () => openTasks({ stream: stream.id }));
    if (stream.id === focusUnit?.workstream_id) name.append(node('span', '', 'focus-marker'));
    const identity = add(node('div', undefined, 'project-name'), node('span', String(streams.indexOf(stream) + 1).padStart(2, '0'), 'project-avatar'), add(node('div'), name, node('small', stream.owner ?? '历史登记归属')));
    identity.title = stream.title;
    const percent = records.length ? `${Math.round(closed(records) / records.length * 100)}%` : '—';
    const completion = add(node('div', undefined, 'cell-progress'), add(node('div', undefined, 'ratio'), node('strong', `${closed(records)} / ${records.length}`), node('span', percent)), progress(closed(records), records.length));
    const attention = records.filter(attentionNeeded).length;
    const action = button('↗', () => openTasks({ stream: stream.id }), 'row-open');
    action.setAttribute('aria-label', `查看${streamName(stream.id)}任务`);
    add(row, add(node('td'), identity), add(node('td'), node('span', stream.legacy ? '历史归属' : lookup(streamStatuses, stream.status, stream.status ?? '未登记'), `tag ${Object.hasOwn(streamStatuses, stream.status) ? stream.status : ''}`)), add(node('td'), completion), add(node('td'), node('span', attention ? String(attention) : '—', attention ? 'attention-number' : 'muted')), add(node('td'), action));
    $('portfolio-body').append(row);
  }

  add($('focus'), node('p', 'CURRENT FOCUS / 当前重点', 'eyebrow'));
  if (focusUnit) add($('focus'), add(node('div', undefined, 'focus-code'), node('span', focusId), badge(focusUnit.status)), node('h2', focusUnit.title), node('p', streamName(focusUnit.workstream_id), 'focus-stream'), node('p', focusUnit.exit_gate, 'focus-exit'), button('查看任务详情 →', () => openDetail(focusId)));
  else $('focus').append(node('h2', '未指定执行焦点'));
  $('attention-count').textContent = String(attentionUnits.length);
  for (const unit of attentionUnits.slice(0, 4)) {
    const item = button('', () => openDetail(unit.id));
    add(item, add(node('div', undefined, 'topline'), node('code', unit.id), badge(unit.status)), node('p', unit.title), node('small', unresolved(unit).length ? `前置未完成：${unresolved(unit).join('、')}` : lookup(modes, unit.execution_mode)));
    $('attention').append(add(node('div', undefined, 'attention-item'), item));
  }
  if (!attentionUnits.length) $('attention').append(node('p', '暂无登记的待关注事项。', 'panel-foot'));
  $('attention-all').addEventListener('click', () => openTasks({ attention: true }));
  $('source-notice').textContent = data.warnings.length ? `查看 ${data.warnings.length} 项快照提示 →` : '查看数据来源与统计口径 →';
  $('source-notice').addEventListener('click', () => showView('sources'));
  for (const mode of new Set([...Object.keys(modes), ...units.map(unit => unit.execution_mode)])) {
    const scoped = units.filter(unit => unit.execution_mode === mode);
    $('modes').append(add(node('div', undefined, 'scope-item'), node('p', lookup(modes, mode)), add(node('strong', String(closed(scoped))), node('span', ` / ${scoped.length}`)), progress(closed(scoped), scoped.length)));
  }
  for (const [id, options] of [['stream', streams.map(stream => [stream.id, streamName(stream.id)])], ['status', [...new Set([...Object.keys(statuses), ...units.map(unit => unit.status)])].map(status => [status, `${statusName(status)} (${units.filter(unit => unit.status === status).length})`])], ['mode', [...new Set(units.map(unit => unit.execution_mode))].map(mode => [mode, lookup(modes, mode)])]]) {
    for (const [value, label] of options) { const option = node('option', label); option.value = value; $(id).append(option); }
  }
  for (const id of ['stream', 'status', 'mode']) $(id).addEventListener('change', renderTasks);
  $('search').addEventListener('input', renderTasks);
  $('reset').addEventListener('click', () => { clearFilters(); renderTasks(); });
  $('attention-filter').addEventListener('click', () => { attentionOnly = !attentionOnly; $('attention-filter').setAttribute('aria-pressed', String(attentionOnly)); renderTasks(); });
  $('board-toggle').addEventListener('click', () => { layout = 'board'; renderTasks(); });
  $('list-toggle').addEventListener('click', () => { layout = 'list'; renderTasks(); });
  $('close-detail').addEventListener('click', () => $('task-dialog').close());
  for (const item of document.querySelectorAll('nav button')) item.addEventListener('click', () => showView(item.dataset.view));
  renderTasks();

  const waves = [...(registry.closure_backlog.waves ?? [])];
  const registeredWaves = new Set(waves.map(wave => String(wave.id)));
  for (const unit of units) if (!registeredWaves.has(String(unit.wave))) { registeredWaves.add(String(unit.wave)); waves.push({ id: unit.wave, title: unit.wave === undefined ? '未登记阶段' : `未定义阶段 ${unit.wave}`, rule: '账本没有提供本阶段的规则。' }); }
  for (const wave of waves) {
    const records = units.filter(unit => String(unit.wave) === String(wave.id));
    const panel = node('section', undefined, 'panel');
    add(panel, add(node('div', undefined, 'panel-heading'), add(node('div'), node('h2', wave.title), node('p', `${new Set(records.map(unit => unit.workstream_id)).size} 条归属主线 · ${records.length} 个任务`)), node('span', `${closed(records)} / ${records.length} 已完成`, 'subtle-chip')), add(node('details', undefined, 'wave-rule'), node('summary', '阶段规则与执行边界'), node('p', wave.rule ?? '未登记')));
    const tasks = node('div', undefined, 'wave-tasks');
    for (const unit of records) tasks.append(add(button('', () => openDetail(unit.id), 'wave-task'), node('code', unit.id), badge(unit.status)));
    if (!records.length) tasks.append(node('p', '本阶段没有登记任务。', 'caption'));
    panel.append(tasks);
    $('roadmap').append(add(node('div', undefined, 'wave'), add(node('div', undefined, 'wave-marker'), node('span', 'WAVE'), node('strong', wave.id === undefined ? '—' : String(wave.id).padStart(2, '0'))), panel));
  }

  $('comparison').textContent = data.snapshot.comparison === 'unavailable' ? '没有可比较的前序账本。' : data.snapshot.mode === 'working-tree' ? '工作区与 HEAD 对比，尚未提交。' : '与第一父提交比较，按单元记录变化。';
  $('delta-count').textContent = `${data.changes.length} 项`;
  for (const change of data.changes) {
    const kind = lookup({ added: '新增任务', removed: '移除任务', details: '范围 / 字段更新', status: '状态变化' }, change.kind);
    const title = `${change.id} · ${kind}`;
    const control = byId.has(change.id) ? button(title, () => openDetail(change.id)) : node('span', title);
    $('changes').append(add(node('div', undefined, 'change'), control, node('p', `${change.from ? statusName(change.from) : '未登记'} → ${change.to ? statusName(change.to) : '已移除'}`)));
  }
  if (!data.changes.length) $('changes').append(node('p', '未检测到单元变化。主线与执行策略以本版本账本为准。', 'panel-foot'));
  for (const commit of data.history) $('history').append(add(node('div', undefined, 'commit'), add(node('div', undefined, 'commit-top'), node('code', commit.sha.slice(0, 10)), node('span', commit.summary ? `${commit.summary.completed} / ${commit.summary.total} 已完成` : '该版本无账本')), node('p', commit.subject), node('time', `${date(commit.date)}（上海）`)));
  for (const warning of data.warnings) $('warnings').append(node('div', warning, 'warning'));
  for (const source of data.sources) $('source-list').append(add(node('div', undefined, 'source-row'), link(source.path), node('code', `SHA-256 ${source.sha256}`)));
  $('inventory').className = 'inventory';
  for (const name of data.inventory) $('inventory').append(link(name, name.replace('governance/', '')));
  $('baseline').textContent = data.baseline ? `治理基线 ${data.baseline.version}：业务模块 ${data.baseline.business_module_count ?? '未登记'}；静态测试函数 ${data.baseline.static_test_function_count ?? '未登记'}。这是登记规模，不是本次测试通过数量。治理目录包含 ${data.inventory.length} 个 JSON。` : '本版本缺少治理规模基线。';
  const route = () => {
    const hash = location.hash.slice(1);
    if (hash.startsWith('unit-') && byId.has(hash.slice(5))) { showView('tasks', false); openDetail(hash.slice(5)); }
    else showView(hash || 'overview', false);
  };
  $('task-dialog').addEventListener('close', () => { if (location.hash.startsWith('#unit-')) history.replaceState(null, '', `#${currentView}`); });
  window.addEventListener('hashchange', route);
  route();
})();
