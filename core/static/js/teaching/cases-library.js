/**
 * Historical Cases Library - Enhanced - Phase 2
 * 功能：扩展历史案例库，支持搜索、筛选、对比
 */

// 扩展历史案例数据库
const historicalCases = [
    // 原有案例
    {
        id: 'case2020',
        year: '2020',
        title: '新冠疫情危机与复苏',
        regime: 'recovery',
        regimeFull: 'Recovery → Deflation',
        summary: '2020年初新冠疫情爆发，全球经济陷入休克。中国迅速控制疫情后，经济率先复苏。',
        pmi: { low: 35.7, high: 51.5 },
        cpi: { low: 5.4, high: 1.5 },
        policyLevel: 'P0',
        marketReturn: 'V型反转 +30%',
        category: 'crisis',
        tags: ['疫情', '复苏', '政策支持', 'V型反转'],
        difficulty: 'beginner',
        duration: '2020年1月-12月',
        timeline: [
            { date: '2020年1月', event: '疫情爆发，经济停摆', details: 'PMI 从 50 暴跌至 35.7，创历史新低' },
            { date: '2020年2-3月', event: '政策强力应对', details: '降准降息，万亿级刺激计划' },
            { date: '2020年4-6月', event: '中国率先控制疫情', details: 'PMI 回升至 50 以上，进入扩张区间' },
            { date: '2020年下半年', event: '出口超预期', details: '上证综指从低点反弹超 30%' }
        ],
        lessons: [
            '黑天鹅冲击会迅速改变 Regime，需快速响应',
            'P0 档位强力支持可以有效对冲外部冲击',
            'Recovery + P0 是黄金配置窗口期',
            'Regime 变化领先于市场'
        ]
    },
    {
        id: 'case2022',
        year: '2022',
        title: '全球通胀压力',
        regime: 'stagflation',
        regimeFull: 'Stagflation → Overheat',
        summary: '2022年全球通胀高企，美联储激进加息。中国面临"内冷外热"的复杂局面。',
        pmi: { low: 47.0, high: 50.1 },
        cpi: { low: 0.9, high: 2.8 },
        policyLevel: 'P2',
        marketReturn: '震荡下行 -15%',
        category: 'inflation',
        tags: ['通胀', '加息', '内外分化', '结构调整'],
        difficulty: 'intermediate',
        duration: '2022年全年',
        timeline: [
            { date: '2022年初', event: '全球通胀抬头', details: '美联储开始加息周期' },
            { date: '2022年4-6月', event: '国内疫情反复', details: 'PMI 跌破 50，滞胀苗头' },
            { date: '2022年下半年', event: '政策相对克制', details: '与美国不同，保持 P2 档位' },
            { date: '2022年底', event: '股市全年调整', details: '上证综指全年下跌 15%' }
        ],
        lessons: [
            '中美经济周期错位，政策可以不同步',
            'CPI 突破 2% 后对权益资产压力明显',
            'P2 档位环境下权益资产承压但非无机会',
            '弱复苏环境下结构机会丰富'
        ]
    },
    {
        id: 'case2023',
        year: '2023',
        title: '"波浪式复苏"',
        regime: 'deflation',
        regimeFull: 'Deflation → Recovery',
        summary: '2023年中国经济呈现"波浪式发展、曲折式前进"特征，通缩压力显现。',
        pmi: { low: 49.0, high: 50.8 },
        cpi: { low: -0.3, high: 2.1 },
        policyLevel: 'P1',
        marketReturn: '结构分化',
        category: 'deflation',
        tags: ['通缩', '波浪式复苏', '债券牛市', '结构分化'],
        difficulty: 'intermediate',
        duration: '2023年全年',
        timeline: [
            { date: '2023年1-2月', event: '重启预期', details: 'PMI 回升至 50 以上' },
            { date: '2023年4-7月', event: '复苏不及预期', details: 'PMI 震荡回落，CPI 跌破 0' },
            { date: '2023年8-10月', event: '政策托底', details: '降准降息，P1 档位' },
            { date: '2023年底', event: '股市分化', details: '红利、科技表现好，整体低迷' }
        ],
        lessons: [
            'CPI 为负的环境下企业盈利承压',
            'P1 档位可托底但不足以推动强劲复苏',
            'Deflation + P1 是债券友好环境',
            '弱复苏下结构性机会丰富'
        ]
    },
    // 新增案例
    {
        id: 'case2008',
        year: '2008',
        title: '全球金融危机',
        regime: 'deflation',
        regimeFull: 'Overheat → Deflation',
        summary: '2008年雷曼兄弟破产引发全球金融海啸，中国推出"四万亿"刺激计划应对。',
        pmi: { low: 38.8, high: 53.0 },
        cpi: { low: -1.6, high: 8.7 },
        policyLevel: 'P0',
        marketReturn: 'V型反转 +80%',
        category: 'crisis',
        tags: ['金融危机', '四万亿', 'V型反转', '基建投资'],
        difficulty: 'advanced',
        duration: '2008年9月-2009年',
        timeline: [
            { date: '2008年9月', event: '雷曼破产', details: '全球金融海啸爆发' },
            { date: '2008年10月', event: '中国紧急应对', details: '降准降息，出台"四万亿"计划' },
            { date: '2008年11-12月', event: 'PMI 暴跌', details: 'PMI 跌至 38.8，历史低点' },
            { date: '2009年', event: '强劲复苏', details: 'PMI 快速回升，股市上涨 80%' }
        ],
        lessons: [
            '外部金融危机可通过强力内需刺激对冲',
            'P0 档位的"四万亿"有效拉动经济复苏',
            '危机时刻果断出手比精准更重要',
            '基建投资是短期稳增长的有效工具'
        ]
    },
    {
        id: 'case2015',
        year: '2015',
        title: '股市大起大落',
        regime: 'recovery',
        regimeFull: 'Recovery → Deflation',
        summary: '2015年A股经历大牛市到股灾，政策从宽松转向去杠杆。',
        pmi: { low: 49.4, high: 51.1 },
        cpi: { low: 1.2, high: 2.0 },
        policyLevel: 'P2',
        marketReturn: '暴涨暴跌',
        category: 'market_crash',
        tags: ['股灾', '去杠杆', '流动性危机', '救市'],
        difficulty: 'advanced',
        duration: '2015年1月-2016年',
        timeline: [
            { date: '2015年上半年', event: '杠杆牛市', details: '上证综指从 3200 涨到 5178' },
            { date: '2015年6月', event: '股灾爆发', details: '去杠杆引发踩踏，千股跌停' },
            { date: '2015年7月', event: '国家队救市', details: '多部委联合出手稳定市场' },
            { date: '2016年', event: '缓慢恢复', details: '市场逐步企稳，进入慢牛' }
        ],
        lessons: [
            '杠杆泡沫破裂会导致流动性危机',
            'Regime 突变时政策反应速度至关重要',
            '市场情绪可以脱离基本面独立运行',
            '强平连锁反应是股灾的放大器'
        ]
    },
    {
        id: 'case2017',
        year: '2017',
        title: '金融去杠杆',
        regime: 'recovery',
        regimeFull: 'Recovery (经济回暖)',
        summary: '2017年经济回暖，但政策重点转向金融去杠杆，市场呈现结构性行情。',
        pmi: { low: 51.3, high: 54.6 },
        cpi: { low: 0.8, high: 2.5 },
        policyLevel: 'P2',
        marketReturn: '结构分化',
        category: 'regulation',
        tags: ['去杠杆', '结构行情', '漂亮50', '价值投资'],
        difficulty: 'intermediate',
        duration: '2017年全年',
        timeline: [
            { date: '2017年初', event: '经济企稳', details: 'PMI 稳定在 51 以上' },
            { date: '2017年4月', event: '金融监管加强', details: '三会合一，严监管启动' },
            { date: '2017年5-12月', event: '结构分化', details: '漂亮50上涨，中小创下跌' },
            { date: '2017年底', event: '去杠杆深化', details: '资管新规征求意见' }
        ],
        lessons: [
            '经济向好不等于股市普涨',
            '去杠杆环境下估值承压',
            '结构分化是政策收紧期的常态',
            '价值投资在监管收紧期相对抗跌'
        ]
    },
    {
        id: 'case2018',
        year: '2018',
        title: '贸易摩擦与去杠杆',
        regime: 'deflation',
        regimeFull: 'Recovery → Deflation',
        summary: '2018年中美贸易摩擦升级，叠加去杠杆政策，A股全年下跌。',
        pmi: { low: 49.4, high: 51.9 },
        cpi: { low: 1.5, high: 2.1 },
        policyLevel: 'P2',
        marketReturn: '全年下跌 -25%',
        category: 'geopolitical',
        tags: ['贸易摩擦', '去杠杆', '熊市', '外部冲击'],
        difficulty: 'advanced',
        duration: '2018年全年',
        timeline: [
            { date: '2018年3月', event: '贸易摩擦开始', details: '美国对华加征关税' },
            { date: '2018年4-6月', event: '去杠杆深化', details: '社融增速大幅下滑' },
            { date: '2018年7-10月', event: '市场持续下跌', details: '上证综指从 3200 跌至 2449' },
            { date: '2018年底', event: '政策转向', details: '央行降准，民企支持政策出台' }
        ],
        lessons: [
            '外部贸易冲击可以改变内部 Regime',
            '去杠杆叠加外部冲击会加速经济下行',
            '政策转向时市场通常已经充分反应',
            '中美关系是影响A股的重要因素'
        ]
    },
    {
        id: 'case2019',
        year: '2019',
        title: '科创板与结构性机会',
        regime: 'recovery',
        regimeFull: 'Deflation → Recovery',
        summary: '2019年经济底部企稳，科创板推出，科技股行情启动。',
        pmi: { low: 49.5, high: 50.8 },
        cpi: { low: 1.5, high: 4.5 },
        policyLevel: 'P1',
        marketReturn: '结构性行情',
        category: 'policy',
        tags: ['科创板', '科技股', '结构性机会', '注册制'],
        difficulty: 'beginner',
        duration: '2019年全年',
        timeline: [
            { date: '2019年1月', event: '央行降准', details: '全面降准 1 个百分点' },
            { date: '2019年7月', event: '科创板开市', details: '注册制试点落地' },
            { date: '2019年8-12月', event: '科技股牛市', details: '半导体、5G 领涨' },
            { date: '2019年底', event: '中美达成协议', details: '第一阶段贸易协议签署' }
        ],
        lessons: [
            '政策创新可以催生结构性行情',
            '科技周期独立于经济周期',
            '注册制改革提升市场效率',
            '结构性机会在弱复苏期依然存在'
        ]
    },
    {
        id: 'case2024',
        year: '2024',
        title: '新质生产力转型',
        regime: 'deflation',
        regimeFull: 'Deflation (低通胀环境)',
        summary: '2024年中国持续推进经济转型，低通胀环境下政策温和支持，新质生产力成为主线。',
        pmi: { low: 49.1, high: 50.8 },
        cpi: { low: 0.1, high: 0.7 },
        policyLevel: 'P1',
        marketReturn: '结构分化',
        category: 'transformation',
        tags: ['新质生产力', '低通胀', '结构转型', 'AI产业'],
        difficulty: 'intermediate',
        duration: '2024年全年',
        timeline: [
            { date: '2024年1-3月', event: '平稳开局', details: 'PMI 围绕 50 波动' },
            { date: '2024年4-9月', event: '政策温和支持', details: '降准降息，P1 档位维持' },
            { date: '2024年10-12月', event: '新质生产力发力', details: 'AI、高端制造领涨' },
            { date: '持续', event: '低通胀环境', details: 'CPI 维持低位，政策空间充裕' }
        ],
        lessons: [
            '低通胀环境为政策提供空间',
            '经济转型期新旧动能切换是常态',
            '新质生产力是长期投资主线',
            '温和政策环境有利于结构性机会'
        ]
    }
];

// 案例分类配置
const caseCategories = [
    { id: 'all', name: '全部案例', icon: '📚' },
    { id: 'crisis', name: '危机应对', icon: '🚨' },
    { id: 'inflation', name: '通胀周期', icon: '📈' },
    { id: 'deflation', name: '通缩周期', icon: '📉' },
    { id: 'regulation', name: '监管政策', icon: '⚖️' },
    { id: 'market_crash', name: '市场波动', icon: '🎢' },
    { id: 'geopolitical', name: '地缘政治', icon: '🌍' },
    { id: 'policy', name: '政策创新', icon: '🏛️' },
    { id: 'transformation', name: '经济转型', icon: '🔄' }
];

// 难度级别配置
const difficultyLevels = {
    'beginner': { name: '入门', color: '#22c55e', icon: '🟢' },
    'intermediate': { name: '进阶', color: '#f59e0b', icon: '🟡' },
    'advanced': { name: '高级', color: '#ef4444', icon: '🔴' }
};

/**
 * 渲染案例库
 */
function renderCasesLibrary() {
    const container = document.getElementById('casesLibraryContainer');
    if (!container) return;

    // 生成筛选器和案例列表
    let html = `
        <div class="cases-library">
            <!-- 搜索和筛选 -->
            <div class="cases-filters">
                <div class="search-box">
                    <input type="text" id="caseSearchInput" placeholder="搜索案例..." oninput="filterCases()">
                </div>
                <div class="filter-tabs" id="categoryTabs">
                    ${caseCategories.map(cat => `
                        <button class="filter-tab ${cat.id === 'all' ? 'active' : ''}" data-category="${cat.id}" onclick="filterByCategory('${cat.id}')">
                            <span class="tab-icon">${cat.icon}</span>
                            <span class="tab-name">${cat.name}</span>
                        </button>
                    `).join('')}
                </div>
                <div class="filter-options">
                    <select id="difficultyFilter" onchange="filterCases()">
                        <option value="all">全部难度</option>
                        <option value="beginner">🟢 入门</option>
                        <option value="intermediate">🟡 进阶</option>
                        <option value="advanced">🔴 高级</option>
                    </select>
                    <select id="yearFilter" onchange="filterCases()">
                        <option value="all">全部年份</option>
                        ${[2024, 2023, 2022, 2020, 2019, 2018, 2017, 2015, 2008].map(year =>
                            `<option value="${year}">${year}</option>`
                        ).join('')}
                    </select>
                    <select id="regimeFilter" onchange="filterCases()">
                        <option value="all">全部 Regime</option>
                        <option value="recovery">复苏 Recovery</option>
                        <option value="overheat">过热 Overheat</option>
                        <option value="deflation">通缩 Deflation</option>
                        <option value="stagflation">滞胀 Stagflation</option>
                    </select>
                </div>
            </div>

            <!-- 案例列表 -->
            <div class="cases-grid" id="casesGrid">
                ${renderCasesCards(historicalCases)}
            </div>

            <!-- 案例统计 -->
            <div class="cases-stats">
                <span>共 <strong id="casesCount">${historicalCases.length}</strong> 个案例</span>
                <span id="filteredInfo" style="display:none;">
                    已筛选 <strong id="filteredCount">0</strong> 个
                </span>
            </div>
        </div>
    `;

    container.innerHTML = html;
}

/**
 * 渲染案例卡片
 */
function renderCasesCards(cases) {
    return cases.map(case_item => {
        const difficulty = difficultyLevels[case_item.difficulty];
        return `
            <div class="case-card enhanced" data-case-id="${case_item.id}" onclick="showCaseDetailEnhanced('${case_item.id}')">
                <div class="case-card-header">
                    <div class="case-year">${case_item.year}</div>
                    <div class="case-difficulty" title="${difficulty.name}">
                        ${difficulty.icon}
                    </div>
                </div>
                <div class="case-card-body">
                    <div class="case-title">${case_item.title}</div>
                    <div class="case-regime regime-${case_item.regime}">${case_item.regimeFull}</div>
                    <p class="case-summary">${case_item.summary}</p>
                    <div class="case-key-metrics">
                        <div class="key-metric">
                            <div class="key-metric-label">PMI</div>
                            <div class="key-metric-value">${case_item.pmi.low} - ${case_item.pmi.high}</div>
                        </div>
                        <div class="key-metric">
                            <div class="key-metric-label">CPI</div>
                            <div class="key-metric-value">${case_item.cpi.low}% - ${case_item.cpi.high}%</div>
                        </div>
                        <div class="key-metric">
                            <div class="key-metric-label">Policy</div>
                            <div class="key-metric-value">${case_item.policyLevel}</div>
                        </div>
                    </div>
                    <div class="case-tags">
                        ${case_item.tags.slice(0, 3).map(tag => `<span class="case-tag">${tag}</span>`).join('')}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

/**
 * 按分类筛选
 */
function filterByCategory(category) {
    // 更新激活状态
    document.querySelectorAll('.filter-tab').forEach(tab => {
        tab.classList.toggle('active', tab.dataset.category === category);
    });

    // 设置隐藏的 category filter
    const categoryFilter = document.getElementById('categoryFilter');
    if (!categoryFilter) {
        const input = document.createElement('input');
        input.id = 'categoryFilter';
        input.type = 'hidden';
        input.value = category;
        document.body.appendChild(input);
    } else {
        categoryFilter.value = category;
    }

    filterCases();
}

/**
 * 筛选案例
 */
function filterCases() {
    const searchTerm = document.getElementById('caseSearchInput').value.toLowerCase();
    const difficulty = document.getElementById('difficultyFilter').value;
    const year = document.getElementById('yearFilter').value;
    const regime = document.getElementById('regimeFilter').value;
    const category = document.getElementById('categoryFilter')?.value || 'all';

    const filtered = historicalCases.filter(case_item => {
        // 搜索匹配
        const matchesSearch = !searchTerm ||
            case_item.title.toLowerCase().includes(searchTerm) ||
            case_item.summary.toLowerCase().includes(searchTerm) ||
            case_item.tags.some(tag => tag.toLowerCase().includes(searchTerm));

        // 分类匹配
        const matchesCategory = category === 'all' || case_item.category === category;

        // 难度匹配
        const matchesDifficulty = difficulty === 'all' || case_item.difficulty === difficulty;

        // 年份匹配
        const matchesYear = year === 'all' || case_item.year === year;

        // Regime 匹配
        const matchesRegime = regime === 'all' || case_item.regime === regime;

        return matchesSearch && matchesCategory && matchesDifficulty && matchesYear && matchesRegime;
    });

    // 更新显示
    const grid = document.getElementById('casesGrid');
    if (grid) {
        grid.innerHTML = renderCasesCards(filtered);
    }

    // 更新统计
    const filteredInfo = document.getElementById('filteredInfo');
    const filteredCount = document.getElementById('filteredCount');
    if (filteredInfo) {
        if (filtered.length < historicalCases.length) {
            filteredInfo.style.display = 'inline';
            if (filteredCount) filteredCount.textContent = filtered.length;
        } else {
            filteredInfo.style.display = 'none';
        }
    }
}

/**
 * 显示增强版案例详情
 */
function showCaseDetailEnhanced(caseId) {
    const caseData = historicalCases.find(c => c.id === caseId);
    if (!caseData) return;

    // 隐藏案例列表
    const casesList = document.getElementById('casesList');
    const libraryContainer = document.getElementById('casesLibraryContainer');
    if (casesList) casesList.style.display = 'none';
    if (libraryContainer) libraryContainer.style.display = 'none';

    // 显示案例详情
    const detailContainer = document.getElementById('caseDetailEnhanced');
    if (detailContainer) {
        const difficulty = difficultyLevels[caseData.difficulty];

        detailContainer.innerHTML = `
            <div class="case-detail-enhanced">
                <div class="case-detail-header">
                    <button class="case-back-btn" onclick="hideCaseDetailEnhanced()">
                        <span>←</span>
                        <span>返回案例列表</span>
                    </button>
                    <div class="case-meta-info">
                        <span class="case-year-badge">${caseData.year}</span>
                        <span class="case-difficulty-badge" style="background: ${difficulty.color}20; color: ${difficulty.color}">
                            ${difficulty.icon} ${difficulty.name}
                        </span>
                        <span class="case-regime-badge regime-${caseData.regime}">${caseData.regimeFull}</span>
                    </div>
                </div>

                <h2 class="case-detail-title">${caseData.title}</h2>
                <p class="case-detail-summary">${caseData.summary}</p>

                <div class="case-detail-content">
                    <div class="case-timeline-section">
                        <h4>📅 事件时间线</h4>
                        <div class="timeline-items">
                            ${caseData.timeline.map(item => `
                                <div class="timeline-item">
                                    <div class="timeline-date">${item.date}</div>
                                    <div class="timeline-content">
                                        <h5>${item.event}</h5>
                                        <p>${item.details}</p>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>

                    <div class="case-metrics-section">
                        <h4>📊 关键指标</h4>
                        <div class="metrics-grid">
                            <div class="metric-item">
                                <span class="metric-label">PMI 区间</span>
                                <span class="metric-value">${caseData.pmi.low} - ${case_data.pmi.high}</span>
                            </div>
                            <div class="metric-item">
                                <span class="metric-label">CPI 区间</span>
                                <span class="metric-value">${caseData.cpi.low}% - ${caseData.cpi.high}%</span>
                            </div>
                            <div class="metric-item">
                                <span class="metric-label">Policy 档位</span>
                                <span class="metric-value level-${caseData.policyLevel}">${caseData.policyLevel}</span>
                            </div>
                            <div class="metric-item">
                                <span class="metric-label">市场表现</span>
                                <span class="metric-value">${caseData.marketReturn}</span>
                            </div>
                        </div>
                    </div>

                    <div class="case-lessons-section">
                        <h4>💡 经验教训</h4>
                        <div class="lessons-list">
                            ${caseData.lessons.map((lesson, index) => `
                                <div class="lesson-item">
                                    <span class="lesson-number">${index + 1}</span>
                                    <p>${lesson}</p>
                                </div>
                            `).join('')}
                        </div>
                    </div>

                    <div class="case-tags-section">
                        <h4>🏷️ 相关标签</h4>
                        <div class="tags-list">
                            ${caseData.tags.map(tag => `<span class="tag-item">${tag}</span>`).join('')}
                        </div>
                    </div>
                </div>
            </div>
        `;
        detailContainer.style.display = 'block';
    }
}

/**
 * 隐藏案例详情
 */
function hideCaseDetailEnhanced() {
    const detailContainer = document.getElementById('caseDetailEnhanced');
    const casesList = document.getElementById('casesList');
    const libraryContainer = document.getElementById('casesLibraryContainer');

    if (detailContainer) detailContainer.style.display = 'none';
    if (casesList) casesList.style.display = 'grid';
    if (libraryContainer) libraryContainer.style.display = 'block';
}

/**
 * 案例对比功能
 */
function compareCases(caseIds) {
    const cases = caseIds.map(id => historicalCases.find(c => c.id === id)).filter(Boolean);
    if (cases.length < 2) {
        alert('请至少选择两个案例进行对比');
        return;
    }

    const comparisonModal = document.createElement('div');
    comparisonModal.className = 'comparison-modal show';
    comparisonModal.innerHTML = `
        <div class="comparison-backdrop" onclick="this.parentElement.remove()"></div>
        <div class="comparison-dialog">
            <div class="comparison-header">
                <h3>案例对比分析</h3>
                <button class="close-btn" onclick="this.closest('.comparison-modal').remove()">×</button>
            </div>
            <div class="comparison-body">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>对比维度</th>
                            ${cases.map(c => `<th>${c.year}<br><small>${c.title.slice(0, 8)}...</small></th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        <tr>
                            <td>Regime</td>
                            ${cases.map(c => `<td class="regime-${c.regime}">${c.regimeFull}</td>`).join('')}
                        </tr>
                        <tr>
                            <td>Policy 档位</td>
                            ${cases.map(c => `<td class="level-${c.policyLevel}">${c.policyLevel}</td>`).join('')}
                        </tr>
                        <tr>
                            <td>PMI 区间</td>
                            ${cases.map(c => `<td>${c.pmi.low} - ${c.pmi.high}</td>`).join('')}
                        </tr>
                        <tr>
                            <td>CPI 区间</td>
                            ${cases.map(c => `<td>${c.cpi.low}% - ${c.cpi.high}%</td>`).join('')}
                        </tr>
                        <tr>
                            <td>市场表现</td>
                            ${cases.map(c => `<td>${c.marketReturn}</td>`).join('')}
                        </tr>
                        <tr>
                            <td>核心教训</td>
                            ${cases.map(c => `<td><small>${c.lessons[0]}</small></td>`).join('')}
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;

    document.body.appendChild(comparisonModal);
}

/**
 * 导出全局函数
 */
window.renderCasesLibrary = renderCasesLibrary;
window.filterByCategory = filterByCategory;
window.filterCases = filterCases;
window.showCaseDetailEnhanced = showCaseDetailEnhanced;
window.hideCaseDetailEnhanced = hideCaseDetailEnhanced;
window.compareCases = compareCases;
window.historicalCases = historicalCases;

/**
 * 添加样式
 */
(function() {
    const style = document.createElement('style');
    style.textContent = `
        /* 案例库增强样式 */
        .cases-library {
            padding: 20px 0;
        }

        .cases-filters {
            margin-bottom: 24px;
        }

        .search-box input {
            width: 100%;
            padding: 12px 16px;
            border: 1px solid var(--color-border, #e2e8f0);
            border-radius: var(--radius-md, 10px);
            font-size: 14px;
            margin-bottom: 16px;
        }

        .search-box input:focus {
            outline: none;
            border-color: var(--color-primary, #3366cc);
            box-shadow: 0 0 0 3px rgba(51, 102, 204, 0.1);
        }

    .filter-tabs {
        display: flex;
        gap: 8px;
        overflow-x: auto;
        padding-bottom: 8px;
        margin-bottom: 16px;
    }

    .filter-tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 14px;
        background: white;
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: var(--radius-sm, 6px);
        cursor: pointer;
        transition: all 0.2s ease;
        white-space: nowrap;
        font-size: 13px;
    }

    .filter-tab:hover {
        background: var(--color-surface, #f8fafc);
    }

    .filter-tab.active {
        background: var(--color-primary, #3366cc);
        color: white;
        border-color: var(--color-primary, #3366cc);
    }

    .filter-options {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
    }

    .filter-options select {
        padding: 8px 12px;
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: var(--radius-sm, 6px);
        font-size: 13px;
        background: white;
        cursor: pointer;
    }

    .cases-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
    }

    .case-card.enhanced {
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .case-card.enhanced:hover {
        transform: translateY(-4px);
        box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.1));
    }

    .case-difficulty {
        position: absolute;
        top: 16px;
        right: 16px;
        font-size: 18px;
    }

    .case-tags {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin-top: 12px;
    }

    .case-tag {
        padding: 3px 8px;
        background: var(--color-surface, #f8fafc);
        border-radius: var(--radius-sm, 6px);
        font-size: 11px;
        color: var(--color-text-secondary, #475569);
    }

    .cases-stats {
        margin-top: 20px;
        padding-top: 16px;
        border-top: 1px solid var(--color-border, #e2e8f0);
        font-size: 13px;
        color: var(--color-text-secondary, #475569);
    }

    /* 案例详情增强 */
    .case-detail-enhanced {
        animation: fadeIn 0.3s ease;
    }

    .case-meta-info {
        display: flex;
        gap: 10px;
        align-items: center;
    }

    .case-year-badge {
        padding: 4px 12px;
        background: var(--color-surface, #f8fafc);
        border-radius: var(--radius-sm, 6px);
        font-size: 13px;
        font-weight: 600;
    }

    .case-difficulty-badge {
        padding: 4px 10px;
        border-radius: var(--radius-sm, 6px);
        font-size: 12px;
        font-weight: 600;
    }

    .case-regime-badge {
        padding: 4px 10px;
        border-radius: var(--radius-sm, 6px);
        font-size: 11px;
        font-weight: 600;
        text-transform: uppercase;
    }

    .case-regime-badge.recovery { background: #dcfce7; color: #166534; }
    .case-regime-badge.overheat { background: #fee2e2; color: #991b1b; }
    .case-regime-badge.deflation { background: #dbeafe; color: #1e40af; }
    .case-regime-badge.stagflation { background: #fef3c7; color: #92400e; }

    .case-detail-title {
        font-size: 24px;
        font-weight: 700;
        margin: 16px 0;
        color: var(--color-text-primary, #0f172a);
    }

    .case-detail-summary {
        font-size: 16px;
        color: var(--color-text-secondary, #475569);
        line-height: 1.6;
        margin-bottom: 24px;
    }

    .case-detail-content {
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 24px;
    }

    .case-timeline-section,
    .case-metrics-section,
    .case-lessons-section,
    .case-tags-section {
        background: var(--color-surface, #f8fafc);
        padding: 20px;
        border-radius: var(--radius-md, 10px);
        margin-bottom: 16px;
    }

    .case-timeline-section h4,
    .case-metrics-section h4,
    .case-lessons-section h4,
    .case-tags-section h4 {
        margin: 0 0 16px 0;
        font-size: 16px;
        color: var(--color-text-primary, #0f172a);
    }

    .timeline-items {
        display: flex;
        flex-direction: column;
        gap: 16px;
    }

    .metrics-grid {
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 12px;
    }

    .metric-item {
        display: flex;
        flex-direction: column;
        gap: 4px;
    }

    .metric-label {
        font-size: 12px;
        color: var(--color-text-muted, #94a3b8);
    }

    .metric-value {
        font-size: 16px;
        font-weight: 600;
        color: var(--color-text-primary, #0f172a);
    }

    .metric-value.level-P0 { background: #dcfce7; color: #166534; padding: 4px 8px; border-radius: 4px; text-align: center; }
    .metric-value.level-P1 { background: #fef3c7; color: #92400e; padding: 4px 8px; border-radius: 4px; text-align: center; }
    .metric-value.level-P2 { background: #fed7aa; color: #9a3412; padding: 4px 8px; border-radius: 4px; text-align: center; }
    .metric-value.level-P3 { background: #fee2e2; color: #991b1b; padding: 4px 8px; border-radius: 4px; text-align: center; }

    .lessons-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .lesson-item {
        display: flex;
        gap: 12px;
        padding: 12px;
        background: white;
        border-radius: var(--radius-sm, 6px);
        border-left: 3px solid var(--color-primary, #3366cc);
    }

    .lesson-number {
        width: 24px;
        height: 24px;
        background: var(--color-primary, #3366cc);
        color: white;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: 600;
        flex-shrink: 0;
    }

    .lesson-item p {
        margin: 0;
        font-size: 14px;
        color: var(--color-text-secondary, #475569);
        line-height: 1.5;
    }

    .tags-list {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
    }

    .tag-item {
        padding: 6px 12px;
        background: white;
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: var(--radius-sm, 6px);
        font-size: 13px;
        color: var(--color-text-secondary, #475569);
    }

    /* 案例对比模态窗 */
    .comparison-modal {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        z-index: 10001;
        display: none;
        align-items: center;
        justify-content: center;
    }

    .comparison-modal.show {
        display: flex;
    }

    .comparison-backdrop {
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.5);
    }

    .comparison-dialog {
        position: relative;
        width: 90%;
        max-width: 900px;
        max-height: 80vh;
        background: white;
        border-radius: var(--radius-lg, 16px);
        overflow: hidden;
        z-index: 1;
    }

    .comparison-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 16px 20px;
        background: var(--color-surface, #f8fafc);
        border-bottom: 1px solid var(--color-border, #e2e8f0);
    }

    .comparison-header h3 {
        margin: 0;
        font-size: 18px;
    }

    .comparison-body {
        padding: 20px;
        overflow-y: auto;
        max-height: calc(80vh - 60px);
    }

    .comparison-table {
        width: 100%;
        border-collapse: collapse;
    }

    .comparison-table th,
    .comparison-table td {
        padding: 12px 16px;
        text-align: left;
        border-bottom: 1px solid var(--color-border, #e2e8f0);
    }

    .comparison-table th {
        background: var(--color-surface, #f8fafc);
        font-weight: 600;
        color: var(--color-text-secondary, #475569);
    }

    .comparison-table th small {
        font-weight: 400;
        color: var(--color-text-muted, #94a3b8);
    }

    /* 响应式 */
    @media (max-width: 768px) {
        .case-detail-content {
            grid-template-columns: 1fr;
        }

        .metrics-grid {
            grid-template-columns: 1fr;
        }

        .cases-grid {
            grid-template-columns: 1fr;
        }

        .comparison-dialog {
            width: 95%;
        }

        .comparison-table {
            font-size: 12px;
        }

        .comparison-table th,
        .comparison-table td {
            padding: 8px;
        }
    }
    `;
    document.head.appendChild(style);
})();
