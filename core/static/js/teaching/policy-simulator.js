/**
 * Policy Simulator - Policy 档位模拟器
 * 功能：模拟不同政策事件对 Policy 档位的影响
 */

// 政策事件数据
const policyEvents = [
    {
        id: 'rrr_cut_50',
        name: '全面降准 50bp',
        impact: 2,
        direction: 'positive',
        description: '释放长期流动性约1万亿元',
        category: 'monetary'
    },
    {
        id: 'lpr_cut_10',
        name: 'LPR 下调 10bp',
        impact: 1,
        direction: 'positive',
        description: '降低实体经济融资成本',
        category: 'monetary'
    },
    {
        id: 'mlf_injection',
        name: 'MLF 超额续作',
        impact: 1,
        direction: 'positive',
        description: '投放中期流动性',
        category: 'monetary'
    },
    {
        id: 'regulation_tighten',
        name: '金融监管加强表态',
        impact: -1,
        direction: 'negative',
        description: '强调防范金融风险',
        category: 'regulation'
    },
    {
        id: 'rate_hike',
        name: '加息 25bp',
        impact: -2,
        direction: 'negative',
        description: '提高政策利率',
        category: 'monetary'
    },
    {
        id: 'rrr_hike',
        name: '升准 50bp',
        impact: -2,
        direction: 'negative',
        description: '回笼流动性',
        category: 'monetary'
    },
    {
        id: 'fiscal_stimulus',
        name: '万亿特别国债发行',
        impact: 1,
        direction: 'positive',
        description: '积极财政政策',
        category: 'fiscal'
    },
    {
        id: 'tax_cut',
        name: '减税降费措施',
        impact: 1,
        direction: 'positive',
        description: '减轻企业负担',
        category: 'fiscal'
    },
    {
        id: 'property_support',
        name: '房地产支持政策',
        impact: 1,
        direction: 'positive',
        description: '因城施策支持刚需',
        category: 'regulation'
    },
    {
        id: 'property_tighten',
        name: '房地产调控收紧',
        impact: -1,
        direction: 'negative',
        description: '坚持房住不炒',
        category: 'regulation'
    },
    {
        id: 'neutral',
        name: '政策维持现状',
        impact: 0,
        direction: 'neutral',
        description: '按兵不动',
        category: 'monetary'
    }
];

// Policy 档位配置
const policyLevels = {
    'P0': {
        name: '强力支持',
        description: '政策环境高度宽松，流动性充裕，可积极配置风险资产',
        minScore: 3,
        color: '#22c55e',
        actions: ['增配权益', '关注成长股', '适度杠杆', '可转债配置', '宽松受益板块']
    },
    'P1': {
        name: '温和支持',
        description: '政策温和偏宽松，结构性机会为主，可适度配置风险资产',
        minScore: 1,
        color: '#f59e0b',
        actions: ['标配权益', '关注政策受益板块', '均衡配置', '精选个股', '防御性成长']
    },
    'P2': {
        name: '政策收紧',
        description: '政策开始收紧，流动性边际收敛，应降低风险敞口',
        minScore: -1,
        color: '#fb923c',
        actions: ['降低仓位', '防御性配置', '高股息股票', '短久期债券', '现金管理']
    },
    'P3': {
        name: '强力收紧',
        description: '政策强力收紧，流动性紧张，应现金为主，等待时机',
        minScore: -2,
        color: '#ef4444',
        actions: ['现金为王', '货币基金', '短债', '等待机会', '规避风险资产']
    }
};

/**
 * 更新 Policy 档位显示
 */
function updatePolicyLevel() {
    const checkboxes = document.querySelectorAll('.event-checkbox:checked');
    let totalScore = 0;
    const selectedEvents = [];

    checkboxes.forEach(checkbox => {
        const impact = parseInt(checkbox.value);
        totalScore += impact;

        const eventItem = checkbox.closest('.policy-event-item');
        const eventName = eventItem.querySelector('.event-name').textContent;
        selectedEvents.push({
            name: eventName,
            impact: impact
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

        // 更新档位显示
        levelDisplay.textContent = level;
        levelDisplay.className = `current-level level-${level}`;

        const levelInfo = policyLevels[level];
        levelName.textContent = levelInfo.name;
        levelDesc.textContent = levelInfo.description;

        // 更新建议操作
        actionTags.innerHTML = levelInfo.actions.map(action =>
            `<span class="action-tag">${action}</span>`
        ).join('');

        // 添加动画效果
        resultDiv.style.animation = 'none';
        resultDiv.offsetHeight;
        resultDiv.style.animation = 'fadeIn 0.3s ease';
    } else {
        resultDiv.style.display = 'none';
    }
}

/**
 * 重置 Policy 模拟器
 */
function resetPolicySimulator() {
    const checkboxes = document.querySelectorAll('.event-checkbox');
    checkboxes.forEach(checkbox => {
        checkbox.checked = false;
    });

    const eventItems = document.querySelectorAll('.policy-event-item');
    eventItems.forEach(item => {
        item.classList.remove('selected');
    });

    document.getElementById('policyResult').style.display = 'none';
}

/**
 * 选择预设场景
 * @param {string} scenario - 场景名称
 */
function selectPolicyScenario(scenario) {
    resetPolicySimulator();

    const scenarios = {
        'highly_supportive': ['rrr_cut_50', 'lpr_cut_10', 'fiscal_stimulus'],
        'mildly_supportive': ['lpr_cut_10', 'mlf_injection'],
        'neutral': ['neutral'],
        'tightening': ['regulation_tighten'],
        'highly_restrictive': ['rate_hike', 'rrr_hike', 'regulation_tighten'],
        'mixed': ['rrr_cut_50', 'property_tighten'] // 混合场景
    };

    const events = scenarios[scenario];
    if (events) {
        events.forEach(eventId => {
            const checkbox = document.querySelector(`.event-checkbox[value="${policyEvents.find(e => e.id === eventId)?.impact}"]`);
            // 简化处理：直接根据影响值找到对应的多选框（实际实现中需要改进）
        });
    }
}

/**
 * 获取 Policy 档位说明
 * @param {string} level - Policy 档位 (P0, P1, P2, P3)
 * @returns {Object} 档位信息
 */
function getPolicyLevelInfo(level) {
    return policyLevels[level] || null;
}

/**
 * 计算组合得分（考虑时间衰减）
 * @param {Array} events - 事件数组，每个事件包含 {impact, monthsAgo}
 * @returns {Object} 包含 totalScore 和 effectiveScore
 */
function calculateEffectiveScore(events) {
    let totalScore = 0;
    let effectiveScore = 0;

    events.forEach(event => {
        const decayFactor = getTimeDecayFactor(event.monthsAgo);
        totalScore += event.impact;
        effectiveScore += event.impact * decayFactor;
    });

    return { totalScore, effectiveScore };
}

/**
 * 获取时间衰减因子
 * @param {number} monthsAgo - 事件距今月数
 * @returns {number} 衰减因子 (0-1)
 */
function getTimeDecayFactor(monthsAgo) {
    if (monthsAgo <= 3) return 1.0;
    if (monthsAgo <= 6) return 0.5;
    return 0.25;
}

/**
 * 添加事件高亮效果
 */
function initEventHighlight() {
    const eventItems = document.querySelectorAll('.policy-event-item');

    eventItems.forEach(item => {
        const checkbox = item.querySelector('.event-checkbox');

        // 监听复选框变化
        checkbox.addEventListener('change', function() {
            if (this.checked) {
                item.classList.add('selected');
            } else {
                item.classList.remove('selected');
            }
        });

        // 点击整行选择
        item.addEventListener('click', function(e) {
            if (e.target !== checkbox) {
                checkbox.checked = !checkbox.checked;
                // 触发 change 事件
                checkbox.dispatchEvent(new Event('change'));
            }
        });
    });
}

/**
 * 导出全局函数
 */
window.updatePolicyLevel = updatePolicyLevel;
window.resetPolicySimulator = resetPolicySimulator;
window.selectPolicyScenario = selectPolicyScenario;

/**
 * 初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    // 延迟初始化，确保 DOM 已加载
    setTimeout(function() {
        initEventHighlight();
    }, 500);
});

// 添加选中状态样式
const style = document.createElement('style');
style.textContent = `
    .policy-event-item.selected {
        border-color: var(--color-primary, #3366cc) !important;
        background: rgba(51, 102, 204, 0.05) !important;
    }

    .policy-event-item {
        cursor: pointer;
        user-select: none;
    }

    .event-checkbox {
        cursor: pointer;
    }
`;
document.head.appendChild(style);

/**
 * 扩展：添加更多政策事件
 */
function addCustomEvent(name, impact, category = 'monetary') {
    const direction = impact > 0 ? 'positive' : impact < 0 ? 'negative' : 'neutral';
    const eventList = document.querySelector('.policy-events-list');

    if (eventList) {
        const eventItem = document.createElement('label');
        eventItem.className = 'policy-event-item';
        eventItem.innerHTML = `
            <input type="checkbox" class="event-checkbox" value="${impact}" onchange="updatePolicyLevel()">
            <div class="event-info">
                <div class="event-name">${name}</div>
                <div class="event-impact">影响: ${impact > 0 ? '+' : ''}${impact} (${direction === 'positive' ? '宽松' : direction === 'negative' ? '收紧' : '中性'})</div>
            </div>
            <span class="event-direction ${direction}">${direction === 'positive' ? '宽松' : direction === 'negative' ? '收紧' : '中性'}</span>
        `;

        eventList.appendChild(eventItem);

        // 重新初始化高亮效果
        initEventHighlight();
    }
}

// 导出添加自定义事件函数
window.addCustomEvent = addCustomEvent;

/**
 * 导出当前配置
 */
function exportPolicyConfig() {
    const checkboxes = document.querySelectorAll('.event-checkbox:checked');
    const config = {
        timestamp: new Date().toISOString(),
        selectedEvents: [],
        totalScore: 0
    };

    checkboxes.forEach(checkbox => {
        const eventItem = checkbox.closest('.policy-event-item');
        const name = eventItem.querySelector('.event-name').textContent;
        const impact = parseInt(checkbox.value);
        config.selectedEvents.push({ name, impact });
        config.totalScore += impact;
    });

    return JSON.stringify(config, null, 2);
}

/**
 * 导入配置
 * @param {string} configJson - JSON 配置字符串
 */
function importPolicyConfig(configJson) {
    try {
        const config = JSON.parse(configJson);

        resetPolicySimulator();

        config.selectedEvents.forEach(event => {
            const checkboxes = document.querySelectorAll('.event-checkbox');
            checkboxes.forEach(checkbox => {
                const eventItem = checkbox.closest('.policy-event-item');
                const name = eventItem.querySelector('.event-name').textContent;
                if (name === event.name && parseInt(checkbox.value) === event.impact) {
                    checkbox.checked = true;
                    eventItem.classList.add('selected');
                }
            });
        });

        updatePolicyLevel();
    } catch (e) {
        console.error('Failed to import config:', e);
        alert('配置导入失败，请检查格式');
    }
}

// 导出配置函数
window.exportPolicyConfig = exportPolicyConfig;
window.importPolicyConfig = importPolicyConfig;
