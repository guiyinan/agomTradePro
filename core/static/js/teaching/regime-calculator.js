/**
 * Regime Calculator - Regime 计算器
 * 功能：根据 PMI 和 CPI 计算 Regime 象限
 * 注意：这是简化版本，用于教学演示。实际系统使用动量 Z-Score 判定。
 */

/**
 * 计算 Regime 象限
 * 使用简化的阈值判定（PMI=50, CPI=2%）
 */
function calculateRegime() {
    const pmi = parseFloat(document.getElementById('calcPMI').value);
    const cpi = parseFloat(document.getElementById('calcCPI').value);

    // 验证输入
    if (isNaN(pmi) || isNaN(cpi)) {
        alert('请输入有效的 PMI 和 CPI 值');
        return;
    }

    // PMI 范围检查
    if (pmi < 40 || pmi > 60) {
        alert('PMI 值超出正常范围 (40-60)，请检查输入');
        return;
    }

    // CPI 范围检查
    if (cpi < -2 || cpi > 10) {
        alert('CPI 值超出正常范围 (-2% - 10%)，请检查输入');
        return;
    }

    // 判定逻辑
    let regime, description, advice, color;

    // 增长判定：PMI >= 50 为扩张，< 50 为收缩
    const growthExpanding = pmi >= 50;

    // 通胀判定：CPI > 2% 为高通胀，<= 2% 为低通胀
    const inflationHigh = cpi > 2;

    // Regime 判定
    if (growthExpanding) {
        // 经济扩张
        if (inflationHigh) {
            // 扩张 + 高通胀 = Overheat (过热)
            regime = 'Overheat (过热)';
            description = `PMI ${pmi} 处于扩张区间，CPI ${cpi}% 高于温和通胀线。经济需求旺盛，但通胀压力上升。`;
            advice = '建议配置：商品、能源股、REITs。注意央行可能加息带来的估值压力。';
            color = '#ef4444';
        } else {
            // 扩张 + 低通胀 = Recovery (复苏)
            regime = 'Recovery (复苏)';
            description = `PMI ${pmi} 处于扩张区间，CPI ${cpi}% 处于温和水平。经济复苏，增长加速，通胀受控。`;
            advice = '建议配置：权益、可转债、成长股。这是股票投资的黄金窗口期。';
            color = '#22c55e';
        }
    } else {
        // 经济收缩
        if (inflationHigh) {
            // 收缩 + 高通胀 = Stagflation (滞胀)
            regime = 'Stagflation (滞胀)';
            description = `PMI ${pmi} 低于扩张线，CPI ${cpi}% 高于温和通胀线。增长放缓，但通胀压力仍存。这是最困难的投资环境。`;
            advice = '建议配置：现金、黄金、短债。回避风险资产，等待环境明朗。';
            color = '#f59e0b';
        } else {
            // 收缩 + 低通胀 = Deflation (通缩)
            regime = 'Deflation (通缩)';
            description = `PMI ${pmi} 低于扩张线，CPI ${cpi}% 处于低位。增长和通胀双双下行，需求不足。`;
            advice = '建议配置：长久期国债、高等级信用债。利率下行预期推动债券价格上涨。';
            color = '#3b82f6';
        }
    }

    // 显示结果
    const resultDiv = document.getElementById('regimeResult');
    const regimeDiv = document.getElementById('resultRegime');
    const descDiv = document.getElementById('resultDescription');
    const adviceDiv = document.getElementById('resultAdvice');

    resultDiv.style.display = 'block';
    regimeDiv.textContent = regime;
    regimeDiv.style.color = color;
    regimeDiv.style.fontWeight = 'bold';
    regimeDiv.style.fontSize = '24px';
    descDiv.textContent = description;
    adviceDiv.innerHTML = `<strong>💡 投资建议：</strong>${advice}`;

    // 添加动画效果
    resultDiv.style.animation = 'none';
    resultDiv.offsetHeight; // 触发重绘
    resultDiv.style.animation = 'fadeIn 0.3s ease';
}

/**
 * 重置计算器
 */
function resetRegimeCalculator() {
    document.getElementById('calcPMI').value = 49.3;
    document.getElementById('calcCPI').value = 0.8;
    document.getElementById('regimeResult').style.display = 'none';
}

/**
 * 获取 Regime 说明
 * @param {string} regimeType - Regime 类型
 * @returns {Object} Regime 说明对象
 */
function getRegimeInfo(regimeType) {
    const regimeMap = {
        'Recovery': {
            name: '复苏',
            englishName: 'Recovery',
            growth: '扩张',
            inflation: '低',
            color: '#22c55e',
            description: '经济从衰退中恢复，PMI 回升至 50 以上，通胀温和。企业盈利改善，估值提升。',
            bestAssets: ['股票', '可转债', '房地产'],
            avoidAssets: ['现金', '短债'],
            tip: '这是配置权益资产的黄金窗口期'
        },
        'Overheat': {
            name: '过热',
            englishName: 'Overheat',
            growth: '扩张',
            inflation: '高',
            color: '#ef4444',
            description: '经济增长强劲但通胀压力上升。央行可能收紧货币政策，企业盈利改善但估值承压。',
            bestAssets: ['商品', '能源股', 'REITs'],
            avoidAssets: ['长久期债券', '成长股'],
            tip: '关注实物资产和抗通胀品种'
        },
        'Stagflation': {
            name: '滞胀',
            englishName: 'Stagflation',
            growth: '收缩',
            inflation: '高',
            color: '#f59e0b',
            description: '经济增长停滞但通胀高企，是最困难的投资环境。企业盈利承压，估值受压。',
            bestAssets: ['现金', '黄金', '短债'],
            avoidAssets: ['股票', '长久期债券'],
            tip: '现金为王，保持流动性等待机会'
        },
        'Deflation': {
            name: '通缩',
            englishName: 'Deflation',
            growth: '收缩',
            inflation: '低',
            color: '#3b82f6',
            description: '经济增长放缓，通胀下行甚至通缩。央行可能降息刺激经济，利率下行利好债券。',
            bestAssets: ['长久期国债', '高等级信用债'],
            avoidAssets: ['商品', '周期股'],
            tip: '债券牛市配置窗口期'
        }
    };

    return regimeMap[regimeType] || null;
}

/**
 * 预设案例值
 */
const regimePresets = {
    'current': { pmi: 49.3, cpi: 0.8, note: '2024年1月中国数据' },
    'recovery': { pmi: 51.5, cpi: 1.8, note: '典型复苏场景' },
    'overheat': { pmi: 52.5, cpi: 3.5, note: '经济过热场景' },
    'stagflation': { pmi: 48.5, cpi: 3.0, note: '滞胀场景' },
    'deflation': { pmi: 47.0, cpi: 0.2, note: '通缩场景' },
    'covid_low': { pmi: 35.7, cpi: 5.4, note: '2020年2月疫情冲击' },
    'covid_recover': { pmi: 50.8, cpi: 1.5, note: '2020年4月恢复期' }
};

/**
 * 应用预设值
 * @param {string} presetKey - 预设键名
 */
function applyRegimePreset(presetKey) {
    const preset = regimePresets[presetKey];
    if (preset) {
        document.getElementById('calcPMI').value = preset.pmi;
        document.getElementById('calcCPI').value = preset.cpi;
        calculateRegime();
    }
}

/**
 * 增量调节 PMI/CPI
 * @param {string} field - 'pmi' 或 'cpi'
 * @param {number} delta - 增量值
 */
function adjustValue(field, delta) {
    const input = document.getElementById(field === 'pmi' ? 'calcPMI' : 'calcCPI');
    let value = parseFloat(input.value) || 0;
    value = Math.round((value + delta) * 10) / 10; // 保留一位小数

    // 设置边界
    if (field === 'pmi') {
        value = Math.max(40, Math.min(60, value));
    } else {
        value = Math.max(-2, Math.min(10, value));
    }

    input.value = value;
    calculateRegime();
}

/**
 * 初始化快捷按钮
 */
function initRegimeCalculatorShortcuts() {
    // 为输入框添加 +/- 按钮
    const pmiInput = document.getElementById('calcPMI');
    const cpiInput = document.getElementById('calcCPI');

    if (pmiInput && cpiInput) {
        // 创建快捷按钮容器
        const pmiShortcuts = document.createElement('div');
        pmiShortcuts.className = 'input-shortcuts';
        pmiShortcuts.innerHTML = `
            <button type="button" class="shortcut-btn" onclick="adjustValue('pmi', -0.5)">-0.5</button>
            <button type="button" class="shortcut-btn" onclick="adjustValue('pmi', 0.5)">+0.5</button>
            <button type="button" class="shortcut-btn preset" onclick="applyRegimePreset('recovery')">复苏案例</button>
        `;

        const cpiShortcuts = document.createElement('div');
        cpiShortcuts.className = 'input-shortcuts';
        cpiShortcuts.innerHTML = `
            <button type="button" class="shortcut-btn" onclick="adjustValue('cpi', -0.5)">-0.5</button>
            <button type="button" class="shortcut-btn" onclick="adjustValue('cpi', 0.5)">+0.5</button>
            <button type="button" class="shortcut-btn preset" onclick="applyRegimePreset('overheat')">过热案例</button>
        `;

        // 插入到输入框后面
        pmiInput.parentNode.appendChild(pmiShortcuts);
        cpiInput.parentNode.appendChild(cpiShortcuts);
    }
}

/**
 * 实时计算（输入时自动计算）
 */
function enableRealtimeCalculation() {
    const pmiInput = document.getElementById('calcPMI');
    const cpiInput = document.getElementById('calcCPI');

    const calcHandler = function() {
        const pmi = parseFloat(pmiInput.value);
        const cpi = parseFloat(cpiInput.value);

        if (!isNaN(pmi) && !isNaN(cpi)) {
            calculateRegime();
        }
    };

    if (pmiInput) {
        pmiInput.addEventListener('input', calcHandler);
    }
    if (cpiInput) {
        cpiInput.addEventListener('input', calcHandler);
    }
}

/**
 * 导出全局函数
 */
window.calculateRegime = calculateRegime;
window.resetRegimeCalculator = resetRegimeCalculator;
window.applyRegimePreset = applyRegimePreset;
window.adjustValue = adjustValue;

/**
 * 初始化（DOM 加载后）
 */
document.addEventListener('DOMContentLoaded', function() {
    // 延迟初始化，确保教学模态窗已加载
    setTimeout(function() {
        initRegimeCalculatorShortcuts();
        // 可选：启用实时计算
        // enableRealtimeCalculation();
    }, 500);
});

// 添加快捷按钮样式
const style = document.createElement('style');
style.textContent = `
    .input-shortcuts {
        display: flex;
        gap: 8px;
        margin-top: 8px;
        flex-wrap: wrap;
    }
    .shortcut-btn {
        padding: 4px 10px;
        background: var(--color-bg, #ffffff);
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: 4px;
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
    }
    .shortcut-btn:hover {
        background: var(--color-surface, #f8fafc);
        border-color: var(--color-primary, #3366cc);
    }
    .shortcut-btn.preset {
        background: var(--color-primary-light, #e8f0fe);
        border-color: var(--color-primary, #3366cc);
        color: var(--color-primary, #3366cc);
    }
`;
document.head.appendChild(style);
