/**
 * Policy Simulator Enhanced - Phase 2
 * 功能：Policy 档位模拟器增强版（时间线、自定义事件、场景对比）
 */

// 扩展政策事件数据库
const enhancedPolicyEvents = {
    monetary: [
        { id: 'rrr_cut_50', name: '全面降准 50bp', impact: 2, category: 'monetary', direction: 'positive', description: '释放长期流动性约1万亿元', color: '#22c55e' },
        { id: 'rrr_cut_25', name: '定向降准 25bp', impact: 1, category: 'monetary', direction: 'positive', description: '定向支持小微企业', color: '#22c55e' },
        { id: 'lpr_cut_10', name: 'LPR 下调 10bp', impact: 1, category: 'monetary', direction: 'positive', description: '降低实体经济融资成本', color: '#22c55e' },
        { id: 'lpr_cut_5', name: 'LPR 下调 5bp', impact: 0.5, category: 'monetary', direction: 'positive', description: '温和降息', color: '#22c55e' },
        { id: 'mlf_injection', name: 'MLF 超额续作', impact: 1, category: 'monetary', direction: 'positive', description: '投放中期流动性', color: '#22c55e' },
        { id: 'reverse_repo', name: '逆回购放量', impact: 0.5, category: 'monetary', direction: 'positive', description: '短期流动性投放', color: '#22c55e' },
        { id: 'rrr_hike', name: '升准 50bp', impact: -2, category: 'monetary', direction: 'negative', description: '回笼流动性', color: '#ef4444' },
        { id: 'rate_hike_25', name: '加息 25bp', impact: -2, category: 'monetary', direction: 'negative', description: '提高政策利率', color: '#ef4444' },
        { id: 'rate_hike_10', name: '加息 10bp', impact: -1, category: 'monetary', direction: 'negative', description: '温和加息', color: '#ef4444' },
        { id: 'mlf_rollback', name: 'MLF 缩量续作', impact: -1, category: 'monetary', direction: 'negative', description: '回笼中期流动性', color: '#ef4444' },
    ],
    fiscal: [
        { id: 'fiscal_stimulus', name: '万亿特别国债', impact: 2, category: 'fiscal', direction: 'positive', description: '积极财政政策', color: '#3b82f6' },
        { id: 'tax_cut', name: '减税降费', impact: 1, category: 'fiscal', direction: 'positive', description: '减轻企业负担', color: '#3b82f6' },
        { id: 'infrastructure', name: '基建投资加码', impact: 1, category: 'fiscal', direction: 'positive', description: '专项债发行提速', color: '#3b82f6' },
        { id: 'consumption_voucher', name: '消费券发放', impact: 0.5, category: 'fiscal', direction: 'positive', description: '刺激居民消费', color: '#3b82f6' },
        { id: 'fiscal_austerity', name: '财政紧缩', impact: -1, category: 'fiscal', direction: 'negative', description: '削减财政支出', color: '#f59e0b' },
    ],
    regulation: [
        { id: 'property_support', name: '房地产支持政策', impact: 1, category: 'regulation', direction: 'positive', description: '因城施策支持刚需', color: '#8b5cf6' },
        { id: 'platform_easing', name: '平台经济监管放松', impact: 1, category: 'regulation', direction: 'positive', description: '支持平台经济发展', color: '#8b5cf6' },
        { id: 'regulation_tighten', name: '金融监管加强', impact: -1, category: 'regulation', direction: 'negative', description: '防范金融风险', color: '#f59e0b' },
        { id: 'property_tighten', name: '房地产调控收紧', impact: -1, category: 'regulation', direction: 'negative', description: '坚持房住不炒', color: '#f59e0b' },
        { id: 'tech_regulation', name: '科技行业监管', impact: -1, category: 'regulation', direction: 'negative', description: '加强反垄断', color: '#f59e0b' },
    ]
};

// 预设场景
const policyScenarios = {
    'crisis_response': {
        name: '危机应对模式',
        description: '模拟经济危机时期的强力政策应对',
        events: ['rrr_cut_50', 'lpr_cut_10', 'fiscal_stimulus', 'tax_cut', 'property_support'],
        timeline: '2020年疫情期间实际政策组合'
    },
    'normal_supportive': {
        name: '常规支持模式',
        description: '经济温和放缓时的政策支持',
        events: ['lpr_cut_5', 'mlf_injection', 'tax_cut'],
        timeline: '2019年经济下行期政策组合'
    },
    'inflation_fighting': {
        name: '抗通胀模式',
        description: '通胀高企时的政策收紧',
        events: ['rate_hike_10', 'mlf_rollback', 'regulation_tighten'],
        timeline: '2022年全球通胀时期政策组合'
    },
    'structural_adjustment': {
        name: '结构调整模式',
        description: '经济转型期的政策组合',
        events: ['rrr_cut_25', 'infrastructure', 'property_tighten', 'platform_easing'],
        timeline: '2023年经济结构调整期政策组合'
    },
    'tightening_cycle': {
        name: '收紧周期模式',
        description: '经济过热时的全面收紧',
        events: ['rate_hike_25', 'rrr_hike', 'fiscal_austerity', 'regulation_tighten'],
        timeline: '2017年金融去杠杆时期政策组合'
    }
};

// 时间线数据存储
let policyTimeline = [];

/**
 * 增强版更新 Policy 档位显示
 */
function updatePolicyLevelEnhanced() {
    const checkboxes = document.querySelectorAll('.event-checkbox:checked');
    let totalScore = 0;
    const selectedEvents = [];

    checkboxes.forEach(checkbox => {
        const impact = parseFloat(checkbox.value);
        totalScore += impact;

        const eventItem = checkbox.closest('.policy-event-item');
        const eventId = eventItem.dataset.eventId;
        const eventName = eventItem.querySelector('.event-name').textContent;
        const eventCategory = eventItem.dataset.category || 'monetary';

        selectedEvents.push({
            id: eventId,
            name: eventName,
            impact: impact,
            category: eventCategory,
            timestamp: new Date().toISOString()
        });
    });

    // 确定档位
    let level;
    if (totalScore >= 3) {
        level = 'P0';
    } else if (totalScore >= 1) {
        level = 'P1';
    } else if (totalScore >= -1) {
        level = 'P2';
    } else {
        level = 'P3';
    }

    // 更新显示
    const resultDiv = document.getElementById('policyResult');
    const levelDisplay = document.getElementById('policyLevelDisplay');
    const levelName = document.getElementById('policyLevelName');
    const levelDesc = document.getElementById('policyLevelDesc');
    const actionTags = document.getElementById('policyActionTags');

    if (selectedEvents.length > 0) {
        resultDiv.style.display = 'block';

        levelDisplay.textContent = level;
        levelDisplay.className = `current-level level-${level}`;

        const levelInfo = policyLevels[level];
        levelName.textContent = levelInfo.name;
        levelDesc.textContent = levelInfo.description;

        actionTags.innerHTML = levelInfo.actions.map(action =>
            `<span class="action-tag">${action}</span>`
        ).join('');

        // 更新时间线
        updateTimelineVisualization(selectedEvents, totalScore, level);

        // 添加动画
        resultDiv.style.animation = 'none';
        resultDiv.offsetHeight;
        resultDiv.style.animation = 'fadeIn 0.3s ease';
    } else {
        resultDiv.style.display = 'none';
        clearTimeline();
    }
}

/**
 * 更新时间线可视化
 */
function updateTimelineVisualization(events, totalScore, level) {
    const timelineContainer = document.getElementById('policyTimelineContainer');
    if (!timelineContainer) return;

    // 生成时间线HTML
    let timelineHTML = '<div class="policy-timeline">';
    timelineHTML += '<h5 style="margin: 0 0 12px 0; font-size: 14px; color: var(--color-text-secondary, #475569);">政策时间线</h5>';

    let cumulativeScore = 0;
    events.forEach((event, index) => {
        cumulativeScore += event.impact;
        const isPositive = event.impact > 0;

        timelineHTML += `
            <div class="timeline-event ${isPositive ? 'positive' : 'negative'}">
                <div class="timeline-marker"></div>
                <div class="timeline-content">
                    <div class="timeline-header">
                        <span class="timeline-name">${event.name}</span>
                        <span class="timeline-impact ${isPositive ? 'positive' : 'negative'}">
                            ${isPositive ? '+' : ''}${event.impact}
                        </span>
                    </div>
                    <div class="timeline-score">累计得分: ${cumulativeScore > 0 ? '+' : ''}${cumulativeScore}</div>
                </div>
            </div>
        `;
    });

    timelineHTML += `
        <div class="timeline-result">
            <div class="result-label">最终档位</div>
            <div class="result-level level-${level}">${level}</div>
            <div class="result-score">总分: ${totalScore > 0 ? '+' : ''}${totalScore}</div>
        </div>
    `;

    timelineHTML += '</div>';
    timelineContainer.innerHTML = timelineHTML;
}

/**
 * 清除时间线
 */
function clearTimeline() {
    const timelineContainer = document.getElementById('policyTimelineContainer');
    if (timelineContainer) {
        timelineContainer.innerHTML = '';
    }
}

/**
 * 应用预设场景
 */
function applyPolicyScenario(scenarioId) {
    const scenario = policyScenarios[scenarioId];
    if (!scenario) return;

    resetPolicySimulatorEnhanced();

    scenario.events.forEach(eventId => {
        // 查找对应的事件复选框
        const allEvents = [...enhancedPolicyEvents.monetary, ...enhancedPolicyEvents.fiscal, ...enhancedPolicyEvents.regulation];
        const eventData = allEvents.find(e => e.id === eventId);

        if (eventData) {
            const checkboxes = document.querySelectorAll('.event-checkbox');
            checkboxes.forEach(checkbox => {
                if (parseFloat(checkbox.value) === eventData.impact) {
                    const eventItem = checkbox.closest('.policy-event-item');
                    const name = eventItem.querySelector('.event-name').textContent;
                    if (name === eventData.name) {
                        checkbox.checked = true;
                        eventItem.classList.add('selected');
                    }
                }
            });
        }
    });

    updatePolicyLevelEnhanced();

    // 显示场景说明
    showScenarioNotification(scenario);
}

/**
 * 显示场景通知
 */
function showScenarioNotification(scenario) {
    const notification = document.createElement('div');
    notification.className = 'scenario-notification';
    notification.innerHTML = `
        <div class="scenario-notification-content">
            <strong>${scenario.name}</strong>
            <p style="margin: 4px 0 0 0; font-size: 13px; color: var(--color-text-secondary, #475569);">${scenario.description}</p>
            <small style="color: var(--color-text-muted, #94a3b8);">${scenario.timeline}</small>
            <button class="close-btn" onclick="this.parentElement.parentElement.remove()">×</button>
        </div>
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.classList.add('show');
    }, 10);

    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

/**
 * 打开自定义事件对话框
 */
function openCustomEventDialog() {
    const existingDialog = document.getElementById('customEventDialog');
    if (existingDialog) {
        existingDialog.remove();
    }

    const dialog = document.createElement('div');
    dialog.id = 'customEventDialog';
    dialog.className = 'custom-event-modal';
    dialog.innerHTML = `
        <div class="custom-event-backdrop" onclick="closeCustomEventDialog()"></div>
        <div class="custom-event-dialog">
            <div class="custom-event-header">
                <h4>添加自定义政策事件</h4>
                <button class="close-btn" onclick="closeCustomEventDialog()">×</button>
            </div>
            <div class="custom-event-body">
                <div class="form-group">
                    <label>事件名称</label>
                    <input type="text" id="customEventName" placeholder="例如：地方债发行提速">
                </div>
                <div class="form-group">
                    <label>政策方向</label>
                    <select id="customEventDirection">
                        <option value="positive">宽松 (+)</option>
                        <option value="negative">收紧 (-)</option>
                        <option value="neutral">中性 (0)</option>
                    </select>
                </div>
                <div class="form-group">
                    <label>影响力度</label>
                    <div class="impact-slider">
                        <input type="range" id="customEventImpact" min="-2" max="2" step="0.5" value="1">
                        <span id="impactValue">+1</span>
                    </div>
                </div>
                <div class="form-group">
                    <label>事件类别</label>
                    <select id="customEventCategory">
                        <option value="monetary">货币政策</option>
                        <option value="fiscal">财政政策</option>
                        <option value="regulation">监管政策</option>
                    </select>
                </div>
            </div>
            <div class="custom-event-footer">
                <button class="btn btn-secondary" onclick="closeCustomEventDialog()">取消</button>
                <button class="btn btn-primary" onclick="addCustomEventFromDialog()">添加事件</button>
            </div>
        </div>
    `;

    document.body.appendChild(dialog);

    // 绑定滑块事件
    const slider = document.getElementById('customEventImpact');
    const valueDisplay = document.getElementById('impactValue');
    slider.addEventListener('input', function() {
        const value = parseFloat(this.value);
        valueDisplay.textContent = value > 0 ? `+${value}` : value.toString();
        valueDisplay.style.color = value > 0 ? '#22c55e' : value < 0 ? '#ef4444' : '#64748b';
    });

    setTimeout(() => dialog.classList.add('show'), 10);
}

/**
 * 关闭自定义事件对话框
 */
function closeCustomEventDialog() {
    const dialog = document.getElementById('customEventDialog');
    if (dialog) {
        dialog.classList.remove('show');
        setTimeout(() => dialog.remove(), 300);
    }
}

/**
 * 从对话框添加自定义事件
 */
function addCustomEventFromDialog() {
    const name = document.getElementById('customEventName').value.trim();
    const direction = document.getElementById('customEventDirection').value;
    const impact = parseFloat(document.getElementById('customEventImpact').value);
    const category = document.getElementById('customEventCategory').value;

    if (!name) {
        alert('请输入事件名称');
        return;
    }

    addCustomPolicyEvent(name, impact, category, direction);
    closeCustomEventDialog();
}

/**
 * 添加自定义政策事件到列表
 */
function addCustomPolicyEvent(name, impact, category, direction) {
    const eventList = document.querySelector('.policy-events-list');
    if (!eventList) return;

    const eventItem = document.createElement('label');
    eventItem.className = 'policy-event-item custom-event';
    eventItem.dataset.category = category;
    eventItem.dataset.eventId = 'custom_' + Date.now();

    const directionClass = direction || (impact > 0 ? 'positive' : impact < 0 ? 'negative' : 'neutral');
    const directionText = directionClass === 'positive' ? '宽松' : directionClass === 'negative' ? '收紧' : '中性';

    eventItem.innerHTML = `
        <input type="checkbox" class="event-checkbox" value="${impact}" onchange="updatePolicyLevelEnhanced()">
        <div class="event-info">
            <div class="event-name">${name} <span class="custom-badge">自定义</span></div>
            <div class="event-impact">影响: ${impact > 0 ? '+' : ''}${impact} (${directionText})</div>
        </div>
        <span class="event-direction ${directionClass}">${directionText}</span>
        <button class="remove-custom-event" onclick="removeCustomEvent(this)" title="删除">×</button>
    `;

    eventList.appendChild(eventItem);

    // 重新绑定事件
    bindEventItemEvents(eventItem);
}

/**
 * 删除自定义事件
 */
function removeCustomEvent(button) {
    const eventItem = button.closest('.policy-event-item');
    eventItem.remove();
    updatePolicyLevelEnhanced();
}

/**
 * 绑定事件项的事件
 */
function bindEventItemEvents(eventItem) {
    const checkbox = eventItem.querySelector('.event-checkbox');

    checkbox.addEventListener('change', function() {
        if (this.checked) {
            eventItem.classList.add('selected');
        } else {
            eventItem.classList.remove('selected');
        }
    });

    eventItem.addEventListener('click', function(e) {
        if (e.target.classList.contains('remove-custom-event')) return;
        if (e.target !== checkbox) {
            checkbox.checked = !checkbox.checked;
            checkbox.dispatchEvent(new Event('change'));
        }
    });
}

/**
 * 增强版重置
 */
function resetPolicySimulatorEnhanced() {
    const checkboxes = document.querySelectorAll('.event-checkbox');
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
    });

    const eventItems = document.querySelectorAll('.policy-event-item');
    eventItems.forEach(item => {
        item.classList.remove('selected');
    });

    document.getElementById('policyResult').style.display = 'none';
    clearTimeline();
}

/**
 * 渲染场景选择器
 */
function renderScenarioSelector() {
    const container = document.getElementById('scenarioSelector');
    if (!container) return;

    let html = '<div class="scenario-selector"><h5 style="margin: 0 0 12px 0;">快速场景</h5><div class="scenario-grid">';

    Object.entries(policyScenarios).forEach(([key, scenario]) => {
        html += `
            <button class="scenario-card" onclick="applyPolicyScenario('${key}')" title="${scenario.description}">
                <div class="scenario-icon">📋</div>
                <div class="scenario-name">${scenario.name}</div>
                <div class="scenario-desc">${scenario.timeline}</div>
            </button>
        `;
    });

    html += '</div></div>';
    container.innerHTML = html;
}

/**
 * 导出全局函数
 */
window.updatePolicyLevelEnhanced = updatePolicyLevelEnhanced;
window.resetPolicySimulatorEnhanced = resetPolicySimulatorEnhanced;
window.applyPolicyScenario = applyPolicyScenario;
window.openCustomEventDialog = openCustomEventDialog;
window.closeCustomEventDialog = closeCustomEventDialog;
window.addCustomEventFromDialog = addCustomEventFromDialog;
window.addCustomPolicyEvent = addCustomPolicyEvent;
window.removeCustomEvent = removeCustomEvent;

/**
 * 初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(() => {
        renderScenarioSelector();
    }, 600);
});

// 添加样式
(function() {
    const style = document.createElement('style');
    style.textContent = `
        /* 场景选择器 */
        .scenario-selector {
            margin: 20px 0;
        }

        .scenario-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
            gap: 10px;
        }

        .scenario-card {
            padding: 12px;
            background: white;
            border: 1px solid var(--color-border, #e2e8f0);
            border-radius: var(--radius-sm, 6px);
            cursor: pointer;
            transition: all 0.2s ease;
            text-align: center;
        }

        .scenario-card:hover {
            border-color: var(--color-primary, #3366cc);
        background: rgba(51, 102, 204, 0.05);
        transform: translateY(-2px);
    }

    .scenario-icon {
        font-size: 24px;
        margin-bottom: 8px;
    }

    .scenario-name {
        font-weight: 600;
        font-size: 13px;
        color: var(--color-text-primary, #0f172a);
        margin-bottom: 4px;
    }

    .scenario-desc {
        font-size: 11px;
        color: var(--color-text-muted, #94a3b8);
    }

    /* 时间线 */
    .policy-timeline {
        margin-top: 20px;
        padding: 16px;
        background: var(--color-surface, #f8fafc);
        border-radius: var(--radius-md, 10px);
    }

    .timeline-event {
        display: flex;
        gap: 12px;
        margin-bottom: 12px;
        position: relative;
    }

    .timeline-event:not(:last-child)::after {
        content: '';
        position: absolute;
        left: 7px;
        top: 24px;
        bottom: -12px;
        width: 2px;
        background: var(--color-border, #e2e8f0);
    }

    .timeline-marker {
        width: 16px;
        height: 16px;
        border-radius: 50%;
        flex-shrink: 0;
        margin-top: 2px;
    }

    .timeline-event.positive .timeline-marker {
        background: #22c55e;
    }

    .timeline-event.negative .timeline-marker {
        background: #ef4444;
    }

    .timeline-content {
        flex: 1;
    }

    .timeline-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 4px;
    }

    .timeline-name {
        font-weight: 600;
        font-size: 13px;
        color: var(--color-text-primary, #0f172a);
    }

    .timeline-impact {
        padding: 2px 8px;
        border-radius: var(--radius-sm, 6px);
        font-size: 11px;
        font-weight: 600;
    }

    .timeline-impact.positive {
        background: #dcfce7;
        color: #166534;
    }

    .timeline-impact.negative {
        background: #fee2e2;
        color: #991b1b;
    }

    .timeline-score {
        font-size: 11px;
        color: var(--color-text-muted, #94a3b8);
    }

    .timeline-result {
        display: flex;
        align-items: center;
        gap: 16px;
        margin-top: 16px;
        padding-top: 16px;
        border-top: 1px solid var(--color-border, #e2e8f0);
    }

    .result-label {
        font-size: 13px;
        color: var(--color-text-secondary, #475569);
    }

    .result-level {
        padding: 8px 16px;
        border-radius: var(--radius-md, 10px);
        font-size: 20px;
        font-weight: 700;
        color: white;
    }

    .result-score {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-text-primary, #0f172a);
    }

    /* 自定义事件 */
    .custom-badge {
        display: inline-block;
        padding: 2px 6px;
        background: #f59e0b;
        color: white;
        border-radius: 4px;
        font-size: 10px;
        margin-left: 6px;
    }

    .remove-custom-event {
        width: 20px;
        height: 20px;
        border: none;
        background: #fee2e2;
        color: #991b1b;
        border-radius: 50%;
        cursor: pointer;
        font-size: 14px;
        line-height: 1;
        margin-left: 8px;
        opacity: 0;
        transition: opacity 0.2s;
    }

    .custom-event:hover .remove-custom-event {
        opacity: 1;
    }

    .remove-custom-event:hover {
        background: #ef4444;
        color: white;
    }

    /* 自定义事件对话框 */
    .custom-event-modal {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10000;
        display: none;
        align-items: center;
        justify-content: center;
    }

    .custom-event-modal.show {
        display: flex;
    }

    .custom-event-backdrop {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
    }

    .custom-event-dialog {
        position: relative;
        width: 90%;
        max-width: 400px;
        background: white;
        border-radius: var(--radius-lg, 16px);
        box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));
        z-index: 1;
    }

    .custom-event-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        border-bottom: 1px solid var(--color-border, #e2e8f0);
    }

    .custom-event-header h4 {
        margin: 0;
        font-size: 16px;
    }

    .custom-event-header .close-btn {
        width: 28px;
        height: 28px;
        border: none;
        background: var(--color-surface, #f8fafc);
        border-radius: 50%;
        cursor: pointer;
        font-size: 18px;
    }

    .custom-event-body {
        padding: 20px;
    }

    .custom-event-body .form-group {
        margin-bottom: 16px;
    }

    .custom-event-body label {
        display: block;
        margin-bottom: 6px;
        font-size: 13px;
        font-weight: 600;
        color: var(--color-text-secondary, #475569);
    }

    .custom-event-body input,
    .custom-event-body select {
        width: 100%;
        padding: 10px 12px;
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: var(--radius-sm, 6px);
        font-size: 14px;
    }

    .impact-slider {
        display: flex;
        align-items: center;
        gap: 12px;
    }

    .impact-slider input {
        flex: 1;
    }

    .impact-slider span {
        min-width: 40px;
        text-align: center;
        font-weight: 600;
    }

    .custom-event-footer {
        display: flex;
        justify-content: flex-end;
        gap: 10px;
        padding: 16px 20px;
        border-top: 1px solid var(--color-border, #e2e8f0);
    }

    .btn {
        padding: 8px 16px;
        border-radius: var(--radius-sm, 6px);
        font-size: 13px;
        font-weight: 500;
        cursor: pointer;
        border: none;
        transition: all 0.2s ease;
    }

    .btn-primary {
        background: var(--color-primary, #3366cc);
        color: white;
    }

    .btn-primary:hover {
        background: var(--primary-hover, #1d4ed8);
    }

    .btn-secondary {
        background: var(--color-surface, #f8fafc);
        color: var(--color-text-secondary, #475569);
    }

    .btn-secondary:hover {
        background: var(--color-border, #e2e8f0);
    }

    /* 场景通知 */
    .scenario-notification {
        position: fixed;
        top: 80px;
        right: 20px;
        z-index: 9998;
        opacity: 0;
        transform: translateX(100%);
        transition: all 0.3s ease;
    }

    .scenario-notification.show {
        opacity: 1;
        transform: translateX(0);
    }

    .scenario-notification-content {
        background: white;
        border-radius: var(--radius-md, 10px);
        box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));
        padding: 16px 20px;
        min-width: 300px;
        position: relative;
        border-left: 4px solid var(--color-primary, #3366cc);
    }

    .scenario-notification-content .close-btn {
        position: absolute;
        top: 10px;
        right: 10px;
        width: 24px;
        height: 24px;
        border: none;
        background: transparent;
        cursor: pointer;
        font-size: 18px;
        color: var(--color-text-muted, #94a3b8);
    }
    `;
    document.head.appendChild(style);
})();
