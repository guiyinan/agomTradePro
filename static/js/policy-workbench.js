// 状态
let currentTab = 'all';
let currentOffset = 0;
let selectedIds = new Set();
let allFetchSources = [];
let showMediaSources = false;

// 初始化
document.addEventListener('DOMContentLoaded', () => {
    const mediaToggle = document.getElementById('toggle-media-sources');
    if (mediaToggle) {
        mediaToggle.checked = false;
        mediaToggle.addEventListener('change', () => {
            showMediaSources = !!mediaToggle.checked;
            renderFetchSources();
        });
    }
    loadSummary();
    loadEvents();
    loadFetchSources();
    initTabHandlers();
    initEventActionHandlers();
});

async function loadFetchSources() {
    const select = document.getElementById('fetch-source');
    if (!select) return;

    try {
        const response = await fetch('/api/policy/workbench/bootstrap/');
        const data = await response.json();
        allFetchSources = data?.filter_options?.sources || [];
        renderFetchSources();
    } catch (error) {
        console.error('Failed to load source options:', error);
    }
}

function renderFetchSources() {
    const select = document.getElementById('fetch-source');
    if (!select) return;

    const previousValue = select.value;
    select.innerHTML = '<option value="">指定源抓取...</option>';

    const filtered = allFetchSources.filter((source) => {
        const category = (source.category || '').toLowerCase();
        const isMedia = category === 'media';
        return showMediaSources || !isMedia;
    });

    filtered.forEach((source) => {
        const option = document.createElement('option');
        option.value = source.id;
        option.textContent = source.name;
        select.appendChild(option);
    });

    if (previousValue && filtered.some((source) => String(source.id) === previousValue)) {
        select.value = previousValue;
    }
}

// Tab 切换
function initTabHandlers() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            currentTab = btn.dataset.tab;
            currentOffset = 0;
            loadEvents();
        });
    });
}

// 加载概览
async function loadSummary() {
    try {
        const response = await fetch('/api/policy/workbench/summary/');
        const data = await response.json();

        if (data.success || data.policy_level) {
            document.getElementById('policy-level-value').textContent = data.policy_level || 'P0';
            document.getElementById('policy-level-event').textContent = data.policy_level_event || '';
            document.getElementById('heat-value').textContent =
                data.global_heat_score ? data.global_heat_score.toFixed(0) : '-';
            document.getElementById('gate-level').textContent =
                data.global_gate_level ? `(${data.global_gate_level})` : '(L0)';
            document.getElementById('sentiment-value').textContent =
                `情绪: ${data.global_sentiment_score ? data.global_sentiment_score.toFixed(2) : '-'}`;
            document.getElementById('pending-count').textContent = data.pending_review_count || 0;
            document.getElementById('sla-count').textContent = data.sla_exceeded_count || 0;
        }
    } catch (error) {
        console.error('Failed to load summary:', error);
    }
}

// 加载事件列表
async function loadEvents() {
    const tbody = document.getElementById('events-tbody');
    tbody.innerHTML = `
        <tr>
            <td colspan="8" class="wb-loading-cell">
                <div class="wb-loading">
                    <span class="wb-loading-spinner" aria-hidden="true"></span>
                    <span>加载中...</span>
                </div>
            </td>
        </tr>
    `;

    const params = new URLSearchParams({
        tab: currentTab,
        limit: 50,
        offset: currentOffset,
        event_type: document.getElementById('filter-event-type').value,
        level: document.getElementById('filter-level').value,
        gate_level: document.getElementById('filter-gate-level').value,
        start_date: document.getElementById('filter-start-date').value,
        end_date: document.getElementById('filter-end-date').value,
        search: document.getElementById('filter-search').value,
    });

    try {
        const response = await fetch(`/api/policy/workbench/items/?${params}`);
        const data = await response.json();

        if (data.success && data.items.length > 0) {
            renderEvents(data.items);
            renderPagination(data.total);
        } else {
            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="empty-state">
                        <h3>暂无数据</h3>
                        <p>当前筛选条件下没有找到事件</p>
                    </td>
                </tr>
            `;
        }
    } catch (error) {
        console.error('Failed to load events:', error);
        tbody.innerHTML = '<tr><td colspan="8" class="wb-loading-cell">加载失败</td></tr>';
    }
}

// 渲染事件列表
function renderEvents(items) {
    const tbody = document.getElementById('events-tbody');
    tbody.innerHTML = items.map(item => `
        <tr data-id="${item.id}">
            <td><input type="checkbox" class="event-checkbox" value="${item.id}" onchange="updateSelection()"></td>
            <td>${item.event_date}</td>
            <td><span class="type-badge ${item.event_type}">${getEventTypeName(item.event_type)}</span></td>
            <td><span class="level-badge ${item.level.toLowerCase()}">${item.level}</span></td>
            <td>${item.gate_level ? `<span class="level-badge ${item.gate_level.toLowerCase()}">${item.gate_level}</span>` : '-'}</td>
            <td>
                <div style="max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                    ${item.title}
                </div>
            </td>
            <td>
                ${item.ai_confidence !== null ? `
                    ${item.ai_confidence.toFixed(2)}
                    <span class="confidence-bar">
                        <span class="fill ${getConfidenceClass(item.ai_confidence)}" style="width: ${item.ai_confidence * 100}%"></span>
                    </span>
                ` : '-'}
            </td>
            <td>
                <div class="actions">
                    ${currentTab === 'pending' ? `
                        <button class="btn btn-success btn-sm" data-action="approve" data-id="${item.id}">通过</button>
                        <button class="btn btn-danger btn-sm" data-action="reject" data-id="${item.id}">拒绝</button>
                        <button class="btn btn-outline btn-sm" data-action="detail" data-id="${item.id}">详情</button>
                    ` : `
                        <button class="btn btn-warning btn-sm" data-action="rollback" data-id="${item.id}">回滚</button>
                        <button class="btn btn-outline btn-sm" data-action="detail" data-id="${item.id}">详情</button>
                    `}
                </div>
            </td>
        </tr>
    `).join('');
}

function initEventActionHandlers() {
    const tbody = document.getElementById('events-tbody');
    if (!tbody) return;

    tbody.addEventListener('click', (event) => {
        const button = event.target.closest('button[data-action]');
        if (!button) return;

        const action = button.dataset.action;
        const eventId = parseInt(button.dataset.id || '', 10);
        if (!eventId) return;

        if (action === 'approve') {
            approveEvent(eventId);
            return;
        }
        if (action === 'reject') {
            showRejectModal(eventId);
            return;
        }
        if (action === 'rollback') {
            showRollbackModal(eventId);
            return;
        }
        if (action === 'detail') {
            showDetail(eventId);
        }
    });
}

// 渲染分页
function renderPagination(total) {
    const pagination = document.getElementById('pagination');
    const limit = 50;
    const pages = Math.ceil(total / limit);
    const currentPage = Math.floor(currentOffset / limit) + 1;

    if (pages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';
    for (let i = 1; i <= Math.min(pages, 10); i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    pagination.innerHTML = html;
}

function goToPage(page) {
    currentOffset = (page - 1) * 50;
    loadEvents();
}

// 选择功能
function toggleSelectAll() {
    const checked = document.getElementById('select-all').checked;
    document.querySelectorAll('.event-checkbox').forEach(cb => {
        cb.checked = checked;
        if (checked) {
            selectedIds.add(parseInt(cb.value));
        } else {
            selectedIds.delete(parseInt(cb.value));
        }
    });
    updateSelection();
}

function updateSelection() {
    document.querySelectorAll('.event-checkbox:checked').forEach(cb => {
        selectedIds.add(parseInt(cb.value));
    });
    document.querySelectorAll('.event-checkbox:not(:checked)').forEach(cb => {
        selectedIds.delete(parseInt(cb.value));
    });
    document.getElementById('selected-count').textContent = selectedIds.size;
}

// 审核操作
async function approveEvent(eventId) {
    try {
        const response = await fetch(`/api/policy/workbench/items/${eventId}/approve/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({ reason: '' })
        });
        const data = await response.json();
        if (data.success) {
            loadEvents();
            loadSummary();
        } else {
            alert('操作失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        alert('操作失败: ' + error.message);
    }
}

function showRejectModal(eventId) {
    document.getElementById('modal-title').textContent = '拒绝审核';
    document.getElementById('modal-body').innerHTML = `
        <div class="form-group">
            <label>拒绝原因（必填）</label>
            <textarea id="reject-reason" placeholder="请说明拒绝原因..."></textarea>
        </div>
    `;
    document.getElementById('modal-confirm').onclick = () => rejectEvent(eventId);
    document.getElementById('modal-confirm').textContent = '确认拒绝';
    document.getElementById('modal-confirm').className = 'btn btn-danger';
    document.getElementById('review-modal').classList.add('active');
}

async function rejectEvent(eventId) {
    const reason = document.getElementById('reject-reason').value;
    if (!reason.trim()) {
        alert('请填写拒绝原因');
        return;
    }

    try {
        const response = await fetch(`/api/policy/workbench/items/${eventId}/reject/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({ reason })
        });
        const data = await response.json();
        if (data.success) {
            closeReviewModal();
            loadEvents();
            loadSummary();
        } else {
            alert('操作失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        alert('操作失败: ' + error.message);
    }
}

function showRollbackModal(eventId) {
    document.getElementById('modal-title').textContent = '回滚生效';
    document.getElementById('modal-body').innerHTML = `
        <div class="form-group">
            <label>回滚原因（必填）</label>
            <textarea id="rollback-reason" placeholder="请说明回滚原因..."></textarea>
        </div>
    `;
    document.getElementById('modal-confirm').onclick = () => rollbackEvent(eventId);
    document.getElementById('modal-confirm').textContent = '确认回滚';
    document.getElementById('modal-confirm').className = 'btn btn-warning';
    document.getElementById('review-modal').classList.add('active');
}

async function rollbackEvent(eventId) {
    const reason = document.getElementById('rollback-reason').value;
    if (!reason.trim()) {
        alert('请填写回滚原因');
        return;
    }

    try {
        const response = await fetch(`/api/policy/workbench/items/${eventId}/rollback/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({ reason })
        });
        const data = await response.json();
        if (data.success) {
            closeReviewModal();
            loadEvents();
            loadSummary();
        } else {
            alert('操作失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        alert('操作失败: ' + error.message);
    }
}

async function showDetail(eventId) {
    try {
        const response = await fetch(`/api/policy/workbench/items/${eventId}/`);
        const data = await response.json();

        if (!data.success) {
            alert('加载详情失败: ' + (data.error || '未知错误'));
            return;
        }

        const item = data.item || {};

        // 构建详情内容
        let detailHtml = `
            <div class="detail-section">
                <h4>基本信息</h4>
                <div class="detail-row"><span class="label">日期:</span> ${item.event_date || '-'}</div>
                <div class="detail-row"><span class="label">类型:</span> ${getEventTypeName(item.event_type)}</div>
                <div class="detail-row"><span class="label">档位:</span> ${item.level || '-'}</div>
                <div class="detail-row"><span class="label">闸门:</span> ${item.gate_level || '-'}</div>
                <div class="detail-row"><span class="label">标题:</span> ${item.title || '-'}</div>
            </div>
            <div class="detail-section">
                <h4>详细描述</h4>
                <p>${item.description || '无描述'}</p>
            </div>
            <div class="detail-section">
                <h4>AI 分析</h4>
                <div class="detail-row"><span class="label">置信度:</span> ${formatNumber(item.ai_confidence, 2)}</div>
                <div class="detail-row"><span class="label">热度:</span> ${formatNumber(item.heat_score, 1)}</div>
                <div class="detail-row"><span class="label">情绪:</span> ${formatNumber(item.sentiment_score, 2)}</div>
            </div>
            <div class="detail-section">
                <h4>来源信息</h4>
                <div class="detail-row"><span class="label">来源:</span> ${item.rss_source_name || '手动录入'}</div>
                <div class="detail-row"><span class="label">链接:</span> ${item.evidence_url ? `<a href="${item.evidence_url}" target="_blank">查看原文</a>` : '-'}</div>
            </div>
            <div class="detail-section">
                <h4>审核状态</h4>
                <div class="detail-row"><span class="label">状态:</span> ${item.audit_status || '-'}</div>
                <div class="detail-row"><span class="label">审核人:</span> ${item.reviewed_by_name || '-'}</div>
                <div class="detail-row"><span class="label">审核时间:</span> ${item.reviewed_at || '-'}</div>
                ${item.review_notes ? `<div class="detail-row"><span class="label">备注:</span> ${item.review_notes}</div>` : ''}
            </div>
        `;

        // 在模态框中显示详情
        document.getElementById('modal-title').textContent = '事件详情';
        document.getElementById('modal-body').innerHTML = detailHtml;
        document.getElementById('modal-confirm').textContent = '关闭';
        document.getElementById('modal-confirm').className = 'btn btn-primary';
        document.getElementById('modal-confirm').onclick = closeModal;
        document.getElementById('review-modal').classList.add('active');

    } catch (error) {
        alert('加载详情失败: ' + error.message);
    }
}

// 批量操作
async function batchApprove() {
    if (selectedIds.size === 0) {
        alert('请先选择要操作的事件');
        return;
    }

    if (!confirm(`确认批量通过 ${selectedIds.size} 个事件？`)) {
        return;
    }

    for (const eventId of selectedIds) {
        await approveEvent(eventId);
    }
    selectedIds.clear();
    loadEvents();
}

function batchReject() {
    if (selectedIds.size === 0) {
        alert('请先选择要操作的事件');
        return;
    }

    document.getElementById('modal-title').textContent = '批量拒绝';
    document.getElementById('modal-body').innerHTML = `
        <p>已选择 ${selectedIds.size} 个事件</p>
        <div class="form-group">
            <label>拒绝原因（必填）</label>
            <textarea id="batch-reject-reason" placeholder="请说明拒绝原因..."></textarea>
        </div>
    `;
    document.getElementById('modal-confirm').onclick = executeBatchReject;
    document.getElementById('modal-confirm').textContent = '确认拒绝';
    document.getElementById('modal-confirm').className = 'btn btn-danger';
    document.getElementById('review-modal').classList.add('active');
}

async function executeBatchReject() {
    const reason = document.getElementById('batch-reject-reason').value;
    if (!reason.trim()) {
        alert('请填写拒绝原因');
        return;
    }

    for (const eventId of selectedIds) {
        await fetch(`/api/policy/workbench/items/${eventId}/reject/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({ reason })
        });
    }

    closeReviewModal();
    selectedIds.clear();
    loadEvents();
    loadSummary();
}

// 工具函数
function closeReviewModal() {
    document.getElementById('review-modal').classList.remove('active');
}

function getEventTypeName(type) {
    const names = {
        'policy': '政策',
        'hotspot': '热点',
        'sentiment': '情绪',
        'mixed': '混合'
    };
    return names[type] || type;
}

function getConfidenceClass(confidence) {
    if (confidence >= 0.85) return '';
    if (confidence >= 0.7) return 'low';
    return 'very-low';
}

function formatNumber(value, fractionDigits) {
    if (value === null || value === undefined || value === '') {
        return '-';
    }
    const num = Number(value);
    if (!Number.isFinite(num)) {
        return '-';
    }
    return num.toFixed(fractionDigits);
}

function applyFilters() {
    currentOffset = 0;
    loadEvents();
}

function resetFilters() {
    document.getElementById('filter-event-type').value = '';
    document.getElementById('filter-level').value = '';
    document.getElementById('filter-gate-level').value = '';
    document.getElementById('filter-start-date').value = '';
    document.getElementById('filter-end-date').value = '';
    document.getElementById('filter-search').value = '';
    currentOffset = 0;
    loadEvents();
}

function refreshData() {
    loadSummary();
    loadEvents();
}

async function fetchAll() {
    if (!confirm('确认立即抓取所有 RSS 源？')) return;

    try {
        const response = await fetch('/api/policy/workbench/fetch/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({})
        });
        const data = await response.json();
        if (data.success) {
            alert(`抓取完成：处理 ${data.sources_processed || 0} 个源，${data.new_policy_events || 0} 条新事件`);
            refreshData();
        } else {
            alert('抓取失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        alert('抓取失败: ' + error.message);
    }
}

async function fetchBySource(sourceId) {
    try {
        const response = await fetch('/api/policy/workbench/fetch/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({ source_id: sourceId })
        });
        const data = await response.json();
        if (data.success) {
            alert(`抓取完成：${data.new_policy_events || 0} 条新事件`);
            refreshData();
        } else {
            alert('抓取失败: ' + (data.error || '未知错误'));
        }
    } catch (error) {
        alert('抓取失败: ' + error.message);
    }
}

function fetchSelectedSource() {
    const select = document.getElementById('fetch-source');
    const sourceId = select ? select.value : '';
    if (!sourceId) {
        alert('请先选择一个 RSS 源');
        return;
    }
    fetchBySource(parseInt(sourceId, 10));
}
