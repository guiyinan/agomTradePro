/**
 * Interactive Charts - Phase 3
 * 功能：互动式图表，动态展示 Regime 变化、资产配置矩阵、历史数据
 */

/**
 * 初始化 Regime 四象限互动图表
 */
function initRegimeQuadrantChart(containerId) {
    const container = document.getElementById(containerId);
    if (!container || typeof echarts === 'undefined') return;

    const chart = echarts.init(container);

    const option = {
        title: {
            text: 'Regime 四象限',
            left: 'center',
            top: 10,
            textStyle: { fontSize: 16, fontWeight: 600 }
        },
        tooltip: {
            trigger: 'item',
            formatter: function(params) {
                const regimeData = {
                    '复苏': { desc: '增长↑ 通胀↓', advice: '增配权益、可转债' },
                    '过热': { desc: '增长↑ 通胀↑', advice: '增配商品、能源股' },
                    '通缩': { desc: '增长↓ 通胀↓', advice: '增配长久期国债' },
                    '滞胀': { desc: '增长↓ 通胀↑', advice: '现金为王' }
                };
                const data = regimeData[params.name];
                return `<strong>${params.name}</strong><br/>${data.desc}<br/><em style="color:#666">${data.advice}</em>`;
            }
        },
        grid: {
            left: '10%',
            right: '10%',
            top: '15%',
            bottom: '15%'
        },
        xAxis: {
            min: -3,
            max: 3,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { show: false },
            splitLine: { show: false }
        },
        yAxis: {
            min: -3,
            max: 3,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { show: false },
            splitLine: { show: false }
        },
        series: [{
            type: 'scatter',
            symbolSize: function(data) {
                return data[2] * 30;
            },
            data: [
                { name: '复苏', value: [1.5, 1.5, 1.2], itemStyle: { color: '#22c55e' } },
                { name: '过热', value: [1.5, -1.5, 1.2], itemStyle: { color: '#ef4444' } },
                { name: '通缩', value: [-1.5, -1.5, 1.2], itemStyle: { color: '#3b82f6' } },
                { name: '滞胀', value: [-1.5, 1.5, 1.2], itemStyle: { color: '#f59e0b' } }
            ],
            label: {
                show: true,
                formatter: '{b}',
                fontSize: 14,
                fontWeight: 600,
                color: 'white',
                position: 'inside'
            },
            emphasis: {
                scale: 1.1,
                itemStyle: {
                    shadowBlur: 10,
                    shadowColor: 'rgba(0, 0, 0, 0.3)'
                }
            }
        }, {
            // 坐标轴箭头
            type: 'line',
            data: [[-3, 0], [3, 0]],
            lineStyle: { color: '#94a3b8', width: 2 },
            symbol: 'none',
            silent: true
        }, {
            type: 'line',
            data: [[0, -3], [0, 3]],
            lineStyle: { color: '#94a3b8', width: 2 },
            symbol: 'none',
            silent: true
        }],
        graphic: [
            {
                type: 'text',
                left: '85%',
                top: '50%',
                style: { text: '增长 →', fontSize: 12, fill: '#64748b' }
            },
            {
                type: 'text',
                left: '50%',
                top: '5%',
                style: { text: '↑ 通胀', fontSize: 12, fill: '#64748b', textAlign: 'center' }
            }
        ]
    };

    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());

    return chart;
}

/**
 * 初始化资产配置矩阵互动图表
 */
function initAllocationMatrixChart(containerId) {
    const container = document.getElementById(containerId);
    if (!container || typeof echarts === 'undefined') return;

    const chart = echarts.init(container);

    const regimes = ['Recovery', 'Overheat', 'Deflation', 'Stagflation'];
    const policies = ['P0', 'P1', 'P2', 'P3'];
    const assets = ['权益', '债券', '商品', '现金'];

    // 推荐配置数据 (1=推荐, 0=中性, -1=回避)
    const data = [
        // Recovery
        [[0, 0, 1], [1, 0, 1], [2, 0, 0], [3, 0, -1], [0, 1, 1], [1, 1, 0], [2, 1, 0], [3, 1, -1]],
        // Overheat
        [[0, 2, 0], [1, 2, 0], [2, 2, -1], [3, 2, -1], [0, 3, 1], [1, 3, -1], [2, 3, -1], [3, 3, -1]],
        // 补充完整数据...
    ];

    const option = {
        title: {
            text: '资产配置建议矩阵',
            left: 'center',
            textStyle: { fontSize: 16, fontWeight: 600 }
        },
        tooltip: {
            position: 'top',
            formatter: function(params) {
                const regime = regimes[params.value[0]];
                const policy = policies[params.value[1]];
                const asset = assets[params.value[2]];
                const value = params.value[3];
                const status = value === 1 ? '推荐' : value === 0 ? '中性' : '回避';
                const color = value === 1 ? '#22c55e' : value === 0 ? '#94a3b8' : '#ef4444';
                return `${regime} × ${policy}<br/><strong>${asset}</strong>: <span style="color:${color}">${status}</span>`;
            }
        },
        grid: {
            height: '70%',
            top: '15%'
        },
        xAxis: {
            type: 'category',
            data: policies,
            splitArea: { show: true },
            axisLabel: { fontSize: 12 }
        },
        yAxis: {
            type: 'category',
            data: regimes,
            splitArea: { show: true },
            axisLabel: { fontSize: 12 }
        },
        visualMap: {
            min: -1,
            max: 1,
            calculable: false,
            orient: 'horizontal',
            left: 'center',
            bottom: '5%',
            show: false,
            inRange: {
                color: ['#ef4444', '#f1f5f9', '#22c55e']
            }
        },
        series: [{
            name: '配置建议',
            type: 'heatmap',
            data: [
                [0, 0, 1], [1, 0, 1], [2, 0, 0], [3, 0, -1],
                [0, 1, 0], [1, 1, 0], [2, 1, 0], [3, 1, -1],
                [0, 2, -1], [1, 2, -1], [2, 2, 1], [3, 2, 1],
                [0, 3, -1], [1, 3, -1], [2, 3, 0], [3, 3, 0]
            ],
            label: {
                show: true,
                formatter: function(params) {
                    const value = params.value[2];
                    return value === 1 ? '↑' : value === 0 ? '→' : '↓';
                },
                fontSize: 20
            },
            emphasis: {
                itemStyle: {
                    shadowBlur: 10,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            }
        }]
    };

    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());

    return chart;
}

/**
 * 初始化历史 Regime 变化时间线图表
 */
function initRegimeTimelineChart(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container || typeof echarts === 'undefined') return;

    const chart = echarts.init(container);

    const option = {
        title: {
            text: 'Regime 历史变化',
            left: 'center',
            textStyle: { fontSize: 16, fontWeight: 600 }
        },
        tooltip: {
            trigger: 'axis',
            formatter: function(params) {
                const date = params[0].name;
                let result = `<strong>${date}</strong><br/>`;
                params.forEach(param => {
                    result += `${param.seriesName}: <span style="color:${param.color}">${param.value}%</span><br/>`;
                });
                return result;
            }
        },
        legend: {
            data: ['PMI', 'CPI', '增长动量', '通胀动量'],
            top: '8%'
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '15%',
            top: '20%',
            containLabel: true
        },
        xAxis: {
            type: 'category',
            boundaryGap: false,
            data: data.dates || ['2020-01', '2020-04', '2020-07', '2020-10', '2021-01', '2021-04', '2021-07', '2021-10']
        },
        yAxis: [
            {
                type: 'value',
                name: 'PMI / CPI',
                position: 'left',
                axisLabel: { formatter: '{value}' }
            },
            {
                type: 'value',
                name: '动量 Z-Score',
                position: 'right',
                axisLabel: { formatter: '{value}' }
            }
        ],
        series: [
            {
                name: 'PMI',
                type: 'line',
                data: data.pmi || [35.7, 50.8, 51.5, 51.2, 51.0, 50.8, 50.3, 49.8],
                smooth: true,
                itemStyle: { color: '#3366cc' }
            },
            {
                name: 'CPI',
                type: 'line',
                data: data.cpi || [5.4, 3.3, 2.7, 0.5, -0.3, 1.5, 2.3, 2.8],
                smooth: true,
                itemStyle: { color: '#ef4444' }
            },
            {
                name: '增长动量',
                type: 'line',
                yAxisIndex: 1,
                data: data.growthMomentum || [-2.5, 1.2, 1.8, 1.5, 1.2, 0.8, 0.3, -0.5],
                smooth: true,
                itemStyle: { color: '#22c55e' },
                lineStyle: { type: 'dashed' }
            },
            {
                name: '通胀动量',
                type: 'line',
                yAxisIndex: 1,
                data: data.inflationMomentum || [2.0, 1.5, 0.8, -1.2, -1.8, -0.5, 0.3, 1.0],
                smooth: true,
                itemStyle: { color: '#f59e0b' },
                lineStyle: { type: 'dashed' }
            }
        ]
    };

    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());

    return chart;
}

/**
 * 初始化资产配置饼图
 */
function initAllocationPieChart(containerId, data) {
    const container = document.getElementById(containerId);
    if (!container || typeof echarts === 'undefined') return;

    const chart = echarts.init(container);

    const allocationData = data || [
        { value: 45, name: '权益' },
        { value: 30, name: '债券' },
        { value: 15, name: '商品' },
        { value: 10, name: '现金' }
    ];

    const option = {
        title: {
            text: '目标资产配置',
            left: 'center',
            textStyle: { fontSize: 16, fontWeight: 600 }
        },
        tooltip: {
            trigger: 'item',
            formatter: '{b}: {c}% ({d}%)'
        },
        legend: {
            orient: 'vertical',
            left: 'left',
            top: 'middle'
        },
        series: [{
            name: '资产配置',
            type: 'pie',
            radius: ['40%', '70%'],
            center: ['60%', '50%'],
            avoidLabelOverlap: false,
            itemStyle: {
                borderRadius: 10,
                borderColor: '#fff',
                borderWidth: 2
            },
            label: {
                show: true,
                formatter: '{b}\n{d}%'
            },
            emphasis: {
                label: {
                    show: true,
                    fontSize: 16,
                    fontWeight: 'bold'
                },
                itemStyle: {
                    shadowBlur: 10,
                    shadowOffsetX: 0,
                    shadowColor: 'rgba(0, 0, 0, 0.5)'
                }
            },
            labelLine: {
                show: true
            },
            data: allocationData
        }]
    };

    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());

    return chart;
}

/**
 * 初始化互动式 Regime 计算器图表
 */
function initInteractiveRegimeCalculator(containerId) {
    const container = document.getElementById(containerId);
    if (!container || typeof echarts === 'undefined') return;

    const chart = echarts.init(container);

    // 默认值
    let pmi = 50;
    let cpi = 2;

    const updateChart = () => {
        const growthZ = (pmi - 50) / 5; // 简化 Z-Score 计算
        const inflationZ = (cpi - 2) / 2;

        const option = {
            title: {
                text: `当前位置: PMI ${pmi}, CPI ${cpi}%`,
                left: 'center',
                textStyle: { fontSize: 14, fontWeight: 600 }
            },
            xAxis: {
                min: -3,
                max: 3,
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: { show: true, lineStyle: { color: '#e2e8f0' } },
                axisLabel: { show: false }
            },
            yAxis: {
                min: -3,
                max: 3,
                axisLine: { show: false },
                axisTick: { show: false },
                splitLine: { show: true, lineStyle: { color: '#e2e8f0' } },
                axisLabel: { show: false }
            },
            series: [{
                type: 'scatter',
                data: [[growthZ, inflationZ]],
                symbolSize: 20,
                itemStyle: {
                    color: growthZ >= 0 && inflationZ < 0 ? '#22c55e' :
                           growthZ >= 0 && inflationZ >= 0 ? '#ef4444' :
                           growthZ < 0 && inflationZ < 0 ? '#3b82f6' : '#f59e0b',
                    borderColor: '#0f172a',
                    borderWidth: 2
                },
                label: {
                    show: true,
                    formatter: '●',
                    fontSize: 24,
                    position: 'inside'
                }
            }, {
                type: 'line',
                data: [[0, -3], [0, 3]],
                lineStyle: { color: '#94a3b8', type: 'solid', width: 2 },
                symbol: 'none',
                silent: true
            }, {
                type: 'line',
                data: [[-3, 0], [3, 0]],
                lineStyle: { color: '#94a3b8', type: 'solid', width: 2 },
                symbol: 'none',
                silent: true
            }],
            graphic: [
                {
                    type: 'text',
                    right: 10,
                    top: '50%',
                    style: { text: '增长 →', fontSize: 12, fill: '#64748b' }
                },
                {
                    type: 'text',
                    left: '50%',
                    top: 10,
                    style: { text: '↑ 通胀', fontSize: 12, fill: '#64748b', textAlign: 'center' }
                },
                {
                    type: 'rect',
                    shape: { x: '0%', y: '0%', width: '50%', height: '50%' },
                    style: { fill: 'rgba(34, 197, 94, 0.1)' }
                },
                {
                    type: 'rect',
                    shape: { x: '50%', y: '0%', width: '50%', height: '50%' },
                    style: { fill: 'rgba(239, 68, 68, 0.1)' }
                },
                {
                    type: 'rect',
                    shape: { x: '0%', y: '50%', width: '50%', height: '50%' },
                    style: { fill: 'rgba(59, 130, 246, 0.1)' }
                },
                {
                    type: 'rect',
                    shape: { x: '50%', y: '50%', width: '50%', height: '50%' },
                    style: { fill: 'rgba(245, 158, 11, 0.1)' }
                }
            ]
        };

        chart.setOption(option);
    };

    updateChart();

    // 返回更新函数
    return {
        update: (newPMI, newCPI) => {
            pmi = newPMI;
            cpi = newCPI;
            updateChart();
        },
        resize: () => chart.resize()
    };
}

/**
 * 渲染所有互动图表
 */
function renderAllInteractiveCharts() {
    setTimeout(() => {
        // Regime 四象限
        if (document.getElementById('regimeQuadrantChart')) {
            initRegimeQuadrantChart('regimeQuadrantChart');
        }

        // 资产配置矩阵
        if (document.getElementById('allocationMatrixChart')) {
            initAllocationMatrixChart('allocationMatrixChart');
        }

        // Regime 时间线
        if (document.getElementById('regimeTimelineChart')) {
            initRegimeTimelineChart('regimeTimelineChart');
        }

        // 资产配置饼图
        if (document.getElementById('allocationPieChart')) {
            initAllocationPieChart('allocationPieChart');
        }

        // 互动式计算器
        if (document.getElementById('interactiveRegimeCalc')) {
            window.regimeCalcChart = initInteractiveRegimeCalculator('interactiveRegimeCalc');
        }
    }, 500);
}

/**
 * 导出全局函数
 */
window.initRegimeQuadrantChart = initRegimeQuadrantChart;
window.initAllocationMatrixChart = initAllocationMatrixChart;
window.initRegimeTimelineChart = initRegimeTimelineChart;
window.initAllocationPieChart = initAllocationPieChart;
window.initInteractiveRegimeCalculator = initInteractiveRegimeCalculator;
window.renderAllInteractiveCharts = renderAllInteractiveCharts;

/**
 * 初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    // 等待教学模态窗打开后渲染图表
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const modal = document.getElementById('teachingModal');
                if (modal && modal.classList.contains('show')) {
                    renderAllInteractiveCharts();
                }
            }
        });
    });

    const teachingModal = document.getElementById('teachingModal');
    if (teachingModal) {
        observer.observe(teachingModal, { attributes: true });
    }
});
