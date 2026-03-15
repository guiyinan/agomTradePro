/**
 * Performance Dashboard for Audit Module
 *
 * Provides Chart.js-based visualization for:
 * - F1 score distribution
 * - Stability vs F1 scatter plot
 * - Indicator ranking
 * - Action distribution
 */

/**
 * 初始化 F1 分数分布直方图
 */
function initF1DistributionChart(indicatorData) {
    const ctx = document.getElementById('f1DistributionChart');
    if (!ctx) return;

    // 计算分布
    const bins = {
        '0.0-0.2': 0,
        '0.2-0.4': 0,
        '0.4-0.6': 0,
        '0.6-0.8': 0,
        '0.8-1.0': 0
    };

    indicatorData.forEach(item => {
        const f1 = item.f1_score || 0;
        if (f1 < 0.2) bins['0.0-0.2']++;
        else if (f1 < 0.4) bins['0.2-0.4']++;
        else if (f1 < 0.6) bins['0.4-0.6']++;
        else if (f1 < 0.8) bins['0.6-0.8']++;
        else bins['0.8-1.0']++;
    });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: Object.keys(bins),
            datasets: [{
                label: '指标数量',
                data: Object.values(bins),
                backgroundColor: [
                    'rgba(239, 68, 68, 0.8)',
                    'rgba(245, 158, 11, 0.8)',
                    'rgba(251, 191, 36, 0.8)',
                    'rgba(16, 185, 129, 0.8)',
                    'rgba(5, 150, 105, 0.8)'
                ],
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });
}

/**
 * 初始化稳定性 vs F1 散点图
 */
function initStabilityF1Chart(indicatorData) {
    const ctx = document.getElementById('stabilityF1Chart');
    if (!ctx) return;

    const scatterData = indicatorData.map(item => ({
        x: item.f1_score || 0,
        y: item.stability_score || 0,
        label: item.indicator_code,
        name: item.indicator_name,
        action: item.recommended_action
    }));

    // 按建议操作着色
    const colorMap = {
        'KEEP': 'rgba(16, 185, 129, 0.7)',
        'INCREASE': 'rgba(59, 130, 246, 0.7)',
        'DECREASE': 'rgba(245, 158, 11, 0.7)',
        'REMOVE': 'rgba(239, 68, 68, 0.7)'
    };

    new Chart(ctx, {
        type: 'scatter',
        data: {
            datasets: [{
                label: '指标',
                data: scatterData,
                backgroundColor: scatterData.map(d => colorMap[d.action] || 'rgba(107, 114, 128, 0.7)'),
                pointRadius: 8,
                pointHoverRadius: 12
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const data = context.raw;
                            return [
                                data.name || data.label,
                                `F1: ${data.x.toFixed(3)}`,
                                `稳定性: ${data.y.toFixed(3)}`,
                                `建议: ${data.action}`
                            ];
                        }
                    }
                }
            },
            scales: {
                x: {
                    title: {
                        display: true,
                        text: 'F1 分数'
                    },
                    min: 0,
                    max: 1
                },
                y: {
                    title: {
                        display: true,
                        text: '稳定性分数'
                    },
                    min: 0,
                    max: 1
                }
            }
        }
    });
}

/**
 * 初始化指标排行榜（水平条形图）
 */
function initRankingChart(indicatorData) {
    const ctx = document.getElementById('rankingChart');
    if (!ctx) return;

    // 按 F1 分数排序，取前 10
    const sortedData = [...indicatorData]
        .sort((a, b) => (b.f1_score || 0) - (a.f1_score || 0))
        .slice(0, 10);

    const labels = sortedData.map(d => d.indicator_code);
    const data = sortedData.map(d => d.f1_score || 0);

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'F1 分数',
                data: data,
                backgroundColor: data.map(v => {
                    if (v >= 0.6) return 'rgba(16, 185, 129, 0.8)';
                    if (v >= 0.4) return 'rgba(245, 158, 11, 0.8)';
                    return 'rgba(239, 68, 68, 0.8)';
                }),
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    max: 1
                }
            }
        }
    });
}

/**
 * 初始化建议操作分布（饼图）
 */
function initActionDistributionChart(indicatorData) {
    const ctx = document.getElementById('actionDistributionChart');
    if (!ctx) return;

    // 统计各操作的数量
    const actionCounts = {
        'KEEP': 0,
        'INCREASE': 0,
        'DECREASE': 0,
        'REMOVE': 0
    };

    indicatorData.forEach(item => {
        const action = item.recommended_action;
        if (actionCounts.hasOwnProperty(action)) {
            actionCounts[action]++;
        }
    });

    const labels = {
        'KEEP': '保持',
        'INCREASE': '增加',
        'DECREASE': '降低',
        'REMOVE': '移除'
    };

    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(actionCounts).map(k => labels[k]),
            datasets: [{
                data: Object.values(actionCounts),
                backgroundColor: [
                    'rgba(16, 185, 129, 0.8)',
                    'rgba(59, 130, 246, 0.8)',
                    'rgba(245, 158, 11, 0.8)',
                    'rgba(239, 68, 68, 0.8)'
                ],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right'
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const label = context.label || '';
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = (value / total * 100).toFixed(1);
                            return `${label}: ${value} (${percentage}%)`;
                        }
                    }
                }
            }
        }
    });
}

/**
 * 初始化筛选功能
 */
function initFilters() {
    const categoryFilter = document.getElementById('categoryFilter');
    const actionFilter = document.getElementById('actionFilter');
    const f1Filter = document.getElementById('f1Filter');

    if (!categoryFilter || !actionFilter || !f1Filter) return;

    const filterFunction = () => {
        const category = categoryFilter.value;
        const action = actionFilter.value;
        const f1Range = f1Filter.value;

        const cards = document.querySelectorAll('.indicator-card');
        cards.forEach(card => {
            const cardCategory = card.dataset.category || '';
            const cardAction = card.dataset.action || '';
            const cardF1 = parseFloat(card.dataset.f1 || 0);

            let show = true;

            if (category && cardCategory !== category) show = false;
            if (action && cardAction !== action) show = false;
            if (f1Range === 'high' && cardF1 < 0.6) show = false;
            if (f1Range === 'medium' && (cardF1 < 0.4 || cardF1 >= 0.6)) show = false;
            if (f1Range === 'low' && cardF1 >= 0.4) show = false;

            card.style.display = show ? 'block' : 'none';
        });
    };

    categoryFilter.addEventListener('change', filterFunction);
    actionFilter.addEventListener('change', filterFunction);
    f1Filter.addEventListener('change', filterFunction);
}

/**
 * 创建混淆矩阵热力图
 */
function createConfusionMatrixHeatmap(tp, fp, tn, fn) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    const data = [
        [tp, fp],
        [fn, tn]
    ];

    const maxValue = Math.max(tp, fp, tn, fn);

    new Chart(ctx, {
        type: 'matrix',
        data: {
            datasets: [{
                label: '混淆矩阵',
                data: data,
                backgroundColor: (ctx) => {
                    const value = ctx.dataset.data[ctx.dataIndex][ctx.datasetIndex];
                    const alpha = value / maxValue;
                    if (ctx.dataIndex === 0 && ctx.datasetIndex === 0) {
                        return `rgba(16, 185, 129, ${alpha})`; // TP
                    } else if (ctx.dataIndex === 0 && ctx.datasetIndex === 1) {
                        return `rgba(239, 68, 68, ${alpha})`; // FP
                    } else if (ctx.dataIndex === 1 && ctx.datasetIndex === 0) {
                        return `rgba(245, 158, 11, ${alpha})`; // FN
                    } else {
                        return `rgba(107, 114, 128, ${alpha})`; // TN
                    }
                },
                borderColor: '#fff',
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: () => '',
                        label: function(context) {
                            const value = context.dataset.data[context.dataIndex][context.datasetIndex];
                            const labels = [['真阳性', '假阳性'], ['假阴性', '真阴性']];
                            return `${labels[context.dataIndex][context.datasetIndex]}: ${value}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    type: 'category',
                    labels: ['预测正类', '预测负类']
                },
                y: {
                    type: 'category',
                    labels: ['实际正类', '实际负类'],
                    offset: true
                }
            }
        }
    });

    return canvas;
}

/**
 * 创建领先时间分布图
 */
function createLeadTimeDistribution(leadTimes) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    // 计算分布
    const bins = {
        '0-1月': 0,
        '1-2月': 0,
        '2-3月': 0,
        '3-6月': 0,
        '>6月': 0
    };

    leadTimes.forEach(lt => {
        if (lt < 1) bins['0-1月']++;
        else if (lt < 2) bins['1-2月']++;
        else if (lt < 3) bins['2-3月']++;
        else if (lt < 6) bins['3-6月']++;
        else bins['>6月']++;
    });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: Object.keys(bins),
            datasets: [{
                label: '指标数量',
                data: Object.values(bins),
                backgroundColor: 'rgba(102, 126, 234, 0.8)',
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        stepSize: 1
                    }
                }
            }
        }
    });

    return canvas;
}

// 全局暴露
window.PerformanceDashboard = {
    initF1DistributionChart,
    initStabilityF1Chart,
    initRankingChart,
    initActionDistributionChart,
    initFilters,
    createConfusionMatrixHeatmap,
    createLeadTimeDistribution
};
