/**
 * Attribution Charts for Audit Module
 *
 * Provides Chart.js-based visualization for:
 * - PnL waterfall charts
 * - Time-series attribution trends
 * - Sector/asset breakdown charts
 */

// Chart.js 默认配置
Chart.defaults.font.family = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
Chart.defaults.color = '#64748b';

/**
 * 初始化瀑布图（收益分解）
 */
function initWaterfallChart(reportData) {
    const ctx = document.getElementById('waterfallChart');
    if (!ctx) return;

    const labels = ['起始', '择时收益', '选股收益', '交互收益', '交易成本', '最终'];
    const data = [
        0,
        reportData.regime_timing_pnl || 0,
        reportData.asset_selection_pnl || 0,
        reportData.interaction_pnl || 0,
        reportData.transaction_cost_pnl || 0,
        reportData.total_pnl || 0
    ];

    // 计算累积值
    let cumulative = 0;
    const cumulativeData = data.map(value => {
        cumulative += value;
        return cumulative;
    });

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: '收益贡献',
                data: data,
                backgroundColor: data.map(v => v >= 0 ? 'rgba(16, 185, 129, 0.8)' : 'rgba(239, 68, 68, 0.8)'),
                borderRadius: 6
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
                            const value = context.parsed.y;
                            return value.toFixed(4) + ' (' + (value * 100).toFixed(2) + '%)';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return (value * 100).toFixed(1) + '%';
                        }
                    }
                }
            }
        }
    });
}

/**
 * 初始化趋势图（按周期归因）
 */
function initTrendChart(reportData) {
    const ctx = document.getElementById('trendChart');
    if (!ctx) return;

    const periodData = reportData.period_attributions || [];

    const labels = periodData.map((p, i) => `周期 ${i + 1}`);
    const timingData = periodData.map(p => p.regime_timing_pnl || 0);
    const selectionData = periodData.map(p => p.asset_selection_pnl || 0);
    const interactionData = periodData.map(p => p.interaction_pnl || 0);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '择时收益',
                    data: timingData,
                    borderColor: 'rgba(16, 185, 129, 1)',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: '选股收益',
                    data: selectionData,
                    borderColor: 'rgba(59, 130, 246, 1)',
                    backgroundColor: 'rgba(59, 130, 246, 0.1)',
                    fill: true,
                    tension: 0.4
                },
                {
                    label: '交互收益',
                    data: interactionData,
                    borderColor: 'rgba(245, 158, 11, 1)',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    fill: true,
                    tension: 0.4
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'top',
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + (context.parsed.y * 100).toFixed(2) + '%';
                        }
                    }
                }
            },
            scales: {
                y: {
                    ticks: {
                        callback: function(value) {
                            return (value * 100).toFixed(1) + '%';
                        }
                    }
                }
            }
        }
    });
}

/**
 * 初始化饼图（资产类别分解）
 */
function initSectorChart(reportData) {
    const ctx = document.getElementById('sectorChart');
    if (!ctx) return;

    const sectorData = reportData.sector_breakdown || {};
    const labels = Object.keys(sectorData);
    const data = labels.map(label => {
        const item = sectorData[label];
        return (item.allocation || 0) + (item.selection || 0) + (item.interaction || 0);
    });

    new Chart(ctx, {
        type: 'pie',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: [
                    'rgba(102, 126, 234, 0.8)',
                    'rgba(118, 75, 162, 0.8)',
                    'rgba(16, 185, 129, 0.8)',
                    'rgba(245, 158, 11, 0.8)',
                    'rgba(239, 68, 68, 0.8)'
                ]
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'right',
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const value = context.parsed;
                            const total = context.dataset.data.reduce((a, b) => a + b, 0);
                            const percentage = (value / total * 100).toFixed(1);
                            return context.label + ': ' + percentage + '%';
                        }
                    }
                }
            }
        }
    });
}

/**
 * 初始化 Brinson 分解图表
 */
function initBrinsonChart(brinsonData) {
    const ctx = document.getElementById('brinsonChart');
    if (!ctx) return;

    new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['配置效应', '选股效应', '交互效应'],
            datasets: [{
                label: '贡献',
                data: [
                    brinsonData.allocation_effect || 0,
                    brinsonData.selection_effect || 0,
                    brinsonData.interaction_effect || 0
                ],
                backgroundColor: [
                    'rgba(59, 130, 246, 0.8)',
                    'rgba(16, 185, 129, 0.8)',
                    'rgba(245, 158, 11, 0.8)'
                ],
                borderRadius: 6
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
                            const value = context.parsed.y;
                            return value.toFixed(4) + ' (' + (value * 100).toFixed(2) + '%)';
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: {
                        callback: function(value) {
                            return (value * 100).toFixed(2) + '%';
                        }
                    }
                }
            }
        }
    });
}

/**
 * 填充周期表格
 */
function populatePeriodTable(reportData) {
    const tbody = document.getElementById('periodTableBody');
    if (!tbody) return;

    const periodData = reportData.period_attributions || [];

    tbody.innerHTML = periodData.map(period => `
        <tr>
            <td>${period.start_date} - ${period.end_date}</td>
            <td class="${period.portfolio_return >= 0 ? 'text-success' : 'text-danger'}">
                ${(period.portfolio_return * 100).toFixed(2)}%
            </td>
            <td>${(period.benchmark_return * 100).toFixed(2)}%</td>
            <td class="${period.excess_return >= 0 ? 'text-success' : 'text-danger'}">
                ${(period.excess_return * 100).toFixed(2)}%
            </td>
            <td>${(period.regime_timing_pnl * 100).toFixed(2)}%</td>
            <td>${(period.asset_selection_pnl * 100).toFixed(2)}%</td>
            <td>${(period.interaction_pnl * 100).toFixed(2)}%</td>
        </tr>
    `).join('');
}

/**
 * 创建堆叠面积图（多周期归因）
 */
function createStackedAreaChart(periodData) {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');

    const labels = periodData.map((p, i) => `P${i + 1}`);

    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '择时',
                    data: periodData.map(p => p.regime_timing_pnl || 0),
                    backgroundColor: 'rgba(16, 185, 129, 0.5)',
                    borderColor: 'rgba(16, 185, 129, 1)',
                    fill: true
                },
                {
                    label: '选股',
                    data: periodData.map(p => p.asset_selection_pnl || 0),
                    backgroundColor: 'rgba(59, 130, 246, 0.5)',
                    borderColor: 'rgba(59, 130, 246, 1)',
                    fill: true
                },
                {
                    label: '交互',
                    data: periodData.map(p => p.interaction_pnl || 0),
                    backgroundColor: 'rgba(245, 158, 11, 0.5)',
                    borderColor: 'rgba(245, 158, 11, 1)',
                    fill: true
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                tooltip: {
                    mode: 'index',
                    intersect: false
                }
            },
            scales: {
                y: {
                    stacked: true,
                    ticks: {
                        callback: function(value) {
                            return (value * 100).toFixed(1) + '%';
                        }
                    }
                },
                x: {
                    stacked: true
                }
            }
        }
    });

    return canvas;
}

/**
 * 导出图表为图片
 */
function exportChartAsImage(chartId, filename) {
    const canvas = document.getElementById(chartId);
    if (!canvas) return;

    const link = document.createElement('a');
    link.download = filename || 'chart.png';
    link.href = canvas.toDataURL('image/png');
    link.click();
}

/**
 * 批量导出所有图表
 */
function exportAllCharts() {
    const chartIds = ['waterfallChart', 'trendChart', 'sectorChart'];
    chartIds.forEach((id, index) => {
        setTimeout(() => {
            exportChartAsImage(id, `chart_${index + 1}.png`);
        }, index * 500);
    });
}

// 全局暴露
window.AuditCharts = {
    initWaterfallChart,
    initTrendChart,
    initSectorChart,
    initBrinsonChart,
    populatePeriodTable,
    createStackedAreaChart,
    exportChartAsImage,
    exportAllCharts
};
