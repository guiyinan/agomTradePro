/**
 * Bilingual Support - Phase 3
 * 功能：中英文双语支持，语言切换
 */

// 语言配置
const supportedLanguages = {
    'zh': {
        name: '简体中文',
        flag: '🇨🇳'
    },
    'en': {
        name: 'English',
        flag: '🇺🇸'
    }
};

// 翻译数据
const translations = {
    // 模态窗标题
    'modal.title': {
        zh: '📚 AgomSAAF 宏观经济教学指南',
        en: '📚 AgomSAAF Macro Economics Teaching Guide'
    },

    // 导航
    'nav.basics': { zh: '宏观经济基础', en: 'Macro Economics Basics' },
    'nav.regime': { zh: 'Regime 判定', en: 'Regime Determination' },
    'nav.policy': { zh: 'Policy 档位', en: 'Policy Levels' },
    'nav.allocation': { zh: '资产配置', en: 'Asset Allocation' },
    'nav.cases': { zh: '历史案例', en: 'Historical Cases' },

    // 章节 - 宏观经济基础
    'basics.pmi.title': { zh: '什么是 PMI (采购经理人指数)?', en: 'What is PMI (Purchasing Managers\' Index)?' },
    'basics.pmi.key_points': { zh: '关键要点：', en: 'Key Points:' },
    'basics.pmi.divider': { zh: '分界线是 50', en: 'Divider is 50' },
    'basics.pmi.expanding': { zh: 'PMI ≥ 50 表示经济扩张', en: 'PMI ≥ 50 indicates economic expansion' },
    'basics.pmi.contracting': { zh: 'PMI < 50 表示经济收缩', en: 'PMI < 50 indicates economic contraction' },
    'basics.pmi.leading': { zh: '领先性', en: 'Leading Indicator' },
    'basics.pmi.components': { zh: '构成', en: 'Components' },

    'basics.cpi.title': { zh: '什么是 CPI (消费者物价指数)?', en: 'What is CPI (Consumer Price Index)?' },
    'basics.cpi.levels': { zh: '通胀等级划分：', en: 'Inflation Levels:' },

    'basics.cycle.title': { zh: '经济周期的四个阶段', en: 'Four Stages of Economic Cycle' },
    'basics.cycle.recovery': { zh: '复苏', en: 'Recovery' },
    'basics.cycle.overheat': { zh: '过热', en: 'Overheat' },
    'basics.cycle.deflation': { zh: '通缩', en: 'Deflation' },
    'basics.cycle.stagflation': { zh: '滞胀', en: 'Stagflation' },

    'basics.momentum.title': { zh: '什么是"动量"（Momentum）？', en: 'What is "Momentum"?' },

    // 章节 - Regime 判定
    'regime.quadrant.title': { zh: 'Regime 四象限划分', en: 'Regime Quadrant Classification' },
    'regime.quadrant.table_header': { zh: '象限 | 增长 | 通胀 | 投资策略 | 核心逻辑', en: 'Quadrant | Growth | Inflation | Strategy | Core Logic' },
    'regime.momentum.title': { zh: '动量 vs 水平判定', en: 'Momentum vs Level Determination' },
    'regime.confidence.title': { zh: '置信度的含义', en: 'Meaning of Confidence' },
    'regime.calculator.title': { zh: '🎮 Regime 计算器 (试一试!)', en: '🎮 Regime Calculator (Try it!)' },

    // 章节 - Policy 档位
    'policy.levels.title': { zh: 'P0-P3 档位说明', en: 'P0-P3 Level Description' },
    'policy.events.title': { zh: '政策事件分类', en: 'Policy Event Classification' },
    'policy.rules.title': { zh: '档位响应规则', en: 'Level Response Rules' },
    'policy.simulator.title': { zh: '🎮 Policy 模拟器 (试一试!)', en: '🎮 Policy Simulator (Try it!)' },

    // 章节 - 资产配置
    'allocation.matrix.title': { zh: 'Regime × Policy 准入矩阵', en: 'Regime × Policy Admission Matrix' },
    'allocation.assets.title': { zh: '资产类别特性', en: 'Asset Class Characteristics' },
    'allocation.risk.title': { zh: '风险控制原则', en: 'Risk Control Principles' },

    // 章节 - 历史案例
    'cases.list': { zh: '历史案例库', en: 'Historical Cases Library' },
    'cases.back': { zh: '返回案例列表', en: 'Back to Cases' },
    'cases.timeline': { zh: '事件时间线', en: 'Event Timeline' },
    'cases.lessons': { zh: '经验教训', en: 'Lessons Learned' },

    // 按钮和操作
    'btn.calculate': { zh: '计算 Regime', en: 'Calculate Regime' },
    'btn.reset': { zh: '重置', en: 'Reset' },
    'btn.close': { zh: '关闭', en: 'Close' },
    'btn.teaching_guide': { zh: '📚 教学指南', en: '📚 Teaching Guide' },

    // 计算器
    'calc.pmi': { zh: 'PMI (采购经理人指数)', en: 'PMI (Purchasing Managers\' Index)' },
    'calc.cpi': { zh: 'CPI (消费者物价指数 %)', en: 'CPI (Consumer Price Index %)' },
    'calc.result': { zh: '计算结果：', en: 'Calculation Result:' },
    'calc.advice': { zh: '投资建议：', en: 'Investment Advice:' },

    // Policy 模拟器
    'policy.select_events': { zh: '选择政策事件：', en: 'Select Policy Events:' },
    'policy.level': { zh: '档位', en: 'Level' },
    'policy.actions': { zh: '建议操作：', en: 'Suggested Actions:' },

    // 学习进度
    'progress.title': { zh: '学习进度', en: 'Learning Progress' },
    'progress.sections': { zh: '完成章节', en: 'Completed Sections' },
    'progress.total': { zh: '总进度', en: 'Total Progress' },
    'achievements.title': { zh: '成就', en: 'Achievements' },
    'achievements.unlocked': { zh: '已解锁', en: 'Unlocked' },

    // Regime 名称
    'regime.recovery': { zh: '复苏', en: 'Recovery' },
    'regime.overheat': { zh: '过热', en: 'Overheat' },
    'regime.deflation': { zh: '通缩', en: 'Deflation' },
    'regime.stagflation': { zh: '滞胀', en: 'Stagflation' },

    // 错误提示
    'error.invalid_input': { zh: '请输入有效的数值', en: 'Please enter valid numbers' },
    'error.out_of_range': { zh: '输入值超出范围', en: 'Input value out of range' }
};

/**
 * 获取当前语言
 */
function getCurrentLanguage() {
    return localStorage.getItem('teaching_language') || 'zh';
}

/**
 * 设置语言
 */
function setLanguage(lang) {
    if (supportedLanguages[lang]) {
        localStorage.setItem('teaching_language', lang);
        applyLanguage(lang);
    }
}

/**
 * 获取翻译文本
 */
function t(key, lang = null) {
    const language = lang || getCurrentLanguage();
    if (translations[key] && translations[key][language]) {
        return translations[key][language];
    }
    // 如果找不到翻译，返回中文作为默认
    if (translations[key] && translations[key]['zh']) {
        return translations[key]['zh'];
    }
    return key;
}

/**
 * 应用语言到页面
 */
function applyLanguage(lang) {
    // 更新所有带有 data-i18n 属性的元素
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        const translation = t(key, lang);

        if (element.tagName === 'INPUT' && element.hasAttribute('placeholder')) {
            element.setAttribute('placeholder', translation);
        } else {
            element.textContent = translation;
        }
    });

    // 更新语言切换器显示
    const langSwitcher = document.getElementById('languageSwitcher');
    if (langSwitcher) {
        updateLanguageSwitcher(lang);
    }

    // 触发自定义事件
    document.dispatchEvent(new CustomEvent('languageChanged', { detail: { language: lang } }));
}

/**
 * 切换语言
 */
function toggleLanguage() {
    const current = getCurrentLanguage();
    const newLang = current === 'zh' ? 'en' : 'zh';
    setLanguage(newLang);
}

/**
 * 渲染语言切换器
 */
function renderLanguageSwitcher() {
    const container = document.getElementById('languageSwitcher');
    if (!container) return;

    const currentLang = getCurrentLanguage();

    container.innerHTML = `
        <div class="language-switcher">
            <button class="lang-btn ${currentLang === 'zh' ? 'active' : ''}" onclick="setLanguage('zh')">
                <span class="lang-flag">🇨🇳</span>
                <span class="lang-name">简体</span>
            </button>
            <button class="lang-btn ${currentLang === 'en' ? 'active' : ''}" onclick="setLanguage('en')">
                <span class="lang-flag">🇺🇸</span>
                <span class="lang-name">EN</span>
            </button>
        </div>
    `;
}

/**
 * 更新语言切换器状态
 */
function updateLanguageSwitcher(lang) {
    const btns = document.querySelectorAll('.lang-btn');
    btns.forEach(btn => {
        btn.classList.remove('active');
        if (btn.onclick.toString().includes(`'${lang}'`)) {
            btn.classList.add('active');
        }
    });
}

/**
 * 获取本地化章节配置
 */
function getLocalizedSections(lang = null) {
    const language = lang || getCurrentLanguage();

    const sections = [
        {
            id: 'basics',
            name: t('nav.basics', language),
            icon: '📊',
            order: 1
        },
        {
            id: 'regime',
            name: t('nav.regime', language),
            icon: '🎯',
            order: 2
        },
        {
            id: 'policy',
            name: t('nav.policy', language),
            icon: '📰',
            order: 3
        },
        {
            id: 'allocation',
            name: t('nav.allocation', language),
            icon: '💼',
            order: 4
        },
        {
            id: 'cases',
            name: t('nav.cases', language),
            icon: '📖',
            order: 5
        }
    ];

    return sections;
}

/**
 * 获取本地化 Regime 数据
 */
function getLocalizedRegimeData(lang = null) {
    const language = lang || getCurrentLanguage();

    return {
        recovery: {
            name: t('regime.recovery', language),
            growth: language === 'zh' ? '扩张' : 'Expansion',
            inflation: language === 'zh' ? '低' : 'Low',
            strategy: language === 'zh' ? '增配权益' : 'Increase Equity'
        },
        overheat: {
            name: t('regime.overheat', language),
            growth: language === 'zh' ? '扩张' : 'Expansion',
            inflation: language === 'zh' ? '高' : 'High',
            strategy: language === 'zh' ? '增配商品' : 'Increase Commodities'
        },
        deflation: {
            name: t('regime.deflation', language),
            growth: language === 'zh' ? '收缩' : 'Contraction',
            inflation: language === 'zh' ? '低' : 'Low',
            strategy: language === 'zh' ? '增配国债' : 'Increase Bonds'
        },
        stagflation: {
            name: t('regime.stagflation', language),
            growth: language === 'zh' ? '收缩' : 'Contraction',
            inflation: language === 'zh' ? '高' : 'High',
            strategy: language === 'zh' ? '现金为王' : 'Cash is King'
        }
    };
}

/**
 * 获取本地化 Policy 档位数据
 */
function getLocalizedPolicyData(lang = null) {
    const language = lang || getCurrentLanguage();

    return {
        P0: {
            name: language === 'zh' ? '强力支持' : 'Strong Support',
            description: language === 'zh' ? '政策环境高度宽松' : 'Highly accommodative policy environment'
        },
        P1: {
            name: language === 'zh' ? '温和支持' : 'Moderate Support',
            description: language === 'zh' ? '政策温和偏宽松' : 'Mildly accommodative policy environment'
        },
        P2: {
            name: language === 'zh' ? '政策收紧' : 'Policy Tightening',
            description: language === 'zh' ? '政策开始收紧' : 'Policy beginning to tighten'
        },
        P3: {
            name: language === 'zh' ? '强力收紧' : 'Strong Tightening',
            description: language === 'zh' ? '政策强力收紧' : 'Strongly tightening policy environment'
        }
    };
}

/**
 * 格式化数字（本地化）
 */
function formatNumber(num, lang = null) {
    const language = lang || getCurrentLanguage();
    if (language === 'en') {
        return num.toLocaleString('en-US');
    }
    return num.toLocaleString('zh-CN');
}

/**
 * 格式化日期（本地化）
 */
function formatDate(date, lang = null) {
    const language = lang || getCurrentLanguage();
    const d = new Date(date);

    if (language === 'en') {
        return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    }
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });
}

/**
 * 导出全局函数
 */
window.t = t;
window.getCurrentLanguage = getCurrentLanguage;
window.setLanguage = setLanguage;
window.toggleLanguage = toggleLanguage;
window.renderLanguageSwitcher = renderLanguageSwitcher;
window.getLocalizedSections = getLocalizedSections;
window.getLocalizedRegimeData = getLocalizedRegimeData;
window.getLocalizedPolicyData = getLocalizedPolicyData;
window.formatNumber = formatNumber;
window.formatDate = formatDate;

/**
 * 初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    renderLanguageSwitcher();

    // 监听语言变化事件
    document.addEventListener('languageChanged', function(event) {
        const lang = event.detail.language;
        console.log('Language changed to:', lang);
        // 可以在这里添加更多语言切换后的处理逻辑
    });
});

/**
 * 添加样式
 */
(function() {
    const style = document.createElement('style');
    style.textContent = `
        /* 语言切换器 */
        .language-switcher {
            display: inline-flex;
            background: white;
            border: 1px solid var(--color-border, #e2e8f0);
            border-radius: var(--radius-sm, 6px);
            overflow: hidden;
            box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.08));
        }

        .lang-btn {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 8px 14px;
            background: transparent;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 13px;
        }

        .lang-btn:hover {
        background: var(--color-surface, #f8fafc);
    }

    .lang-btn.active {
        background: var(--color-primary, #3366cc);
        color: white;
    }

    .lang-flag {
        font-size: 16px;
    }

    .lang-name {
        font-weight: 500;
    }

    /* 教学模态窗中的语言切换器 */
    .teaching-modal .language-switcher-container {
        position: absolute;
        top: 20px;
        right: 80px;
        z-index: 10;
    }

    /* 响应式 */
    @media (max-width: 768px) {
        .lang-btn {
            padding: 6px 10px;
        }

        .lang-name {
            display: none;
        }

        .lang-btn.active .lang-name {
            display: inline;
        }
    }
    `;
    document.head.appendChild(style);
})();
