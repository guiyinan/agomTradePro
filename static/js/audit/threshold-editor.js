/**
 * Threshold Editor for Audit Module
 *
 * Provides interactive threshold adjustment functionality:
 * - Real-time slider updates
 * - Signal distribution preview
 * - Historical validation comparison
 * - Save/Reset functionality
 */

// 全局状态
const ThresholdEditor = {
    thresholdData: {},
    originalValues: {},
    previewCharts: {}
};

/**
 * 初始化阈值编辑器
 */
function initThresholdEditor(data) {
    ThresholdEditor.thresholdData = data;

    // 保存原始值
    Object.keys(data).forEach(indicatorCode => {
        ThresholdEditor.originalValues[indicatorCode] = {
            level_low: data[indicatorCode].level_low,
            level_high: data[indicatorCode].level_high
        };

        // 初始化预览图表
        initPreviewChart(indicatorCode, data[indicatorCode]);
    });
}

/**
 * 更新低阈值滑块值
 */
function updateLowValue(indicatorCode, value) {
    const displayValue = document.getElementById(`lowValue_${indicatorCode}`);
    if (displayValue) {
        displayValue.textContent = parseFloat(value).toFixed(2);
    }

    // 更新预览
    updatePreviewChart(indicatorCode, parseFloat(value), null);
}

/**
 * 更新高阈值滑块值
 */
function updateHighValue(indicatorCode, value) {
    const displayValue = document.getElementById(`highValue_${indicatorCode}`);
    if (displayValue) {
        displayValue.textContent = parseFloat(value).toFixed(2);
    }

    // 更新预览
    updatePreviewChart(indicatorCode, null, parseFloat(value));
}

/**
 * 初始化预览小图表
 */
function initPreviewChart(indicatorCode, data) {
    const canvasId = `previewMini_${indicatorCode}`;
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;

    const ctx = canvas.getContext('2d');

    // 生成模拟数据（实际应从历史数据获取）
    const signalCounts = generateSignalDistribution(data.level_low, data.level_high);

    ThresholdEditor.previewCharts[indicatorCode] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: ['看空', '中性', '看多'],
            datasets: [{
                data: [signalCounts.bearish, signalCounts.neutral, signalCounts.bullish],
                backgroundColor: [
                    'rgba(239, 68, 68, 0.8)',
                    'rgba(107, 114, 128, 0.8)',
                    'rgba(16, 185, 129, 0.8)'
                ],
                borderRadius: 4
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
                    },
                    grid: {
                        display: false
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            },
            plugins: {
                tooltip: {
                    enabled: false
                }
            }
        }
    });
}

/**
 * 生成信号分布（模拟数据）
 */
function generateSignalDistribution(low, high) {
    // 基于 正态分布的简化模拟
    const total = 100;
    const bearish = Math.max(0, Math.round(total * (low / 100) * 0.8));
    const bullish = Math.max(0, Math.round(total * ((100 - high) / 100) * 0.8));
    const neutral = total - bearish - bullish;

    return { bearish, neutral, bullish };
}

/**
 * 更新预览图表
 */
function updatePreviewChart(indicatorCode, low, high) {
    const chart = ThresholdEditor.previewCharts[indicatorCode];
    if (!chart) return;

    const data = ThresholdEditor.thresholdData[indicatorCode];
    const currentLow = low !== null ? low : data.level_low;
    const currentHigh = high !== null ? high : data.level_high;

    const signalCounts = generateSignalDistribution(currentLow, currentHigh);

    chart.data.datasets[0].data = [
        signalCounts.bearish,
        signalCounts.neutral,
        signalCounts.bullish
    ];
    chart.update('none');
}

/**
 * 保存单个阈值
 */
function saveThreshold(indicatorCode) {
    const lowSlider = document.getElementById(`lowSlider_${indicatorCode}`);
    const highSlider = document.getElementById(`highSlider_${indicatorCode}`);

    if (!lowSlider || !highSlider) return;

    const payload = {
        indicator_code: indicatorCode,
        level_low: parseFloat(lowSlider.value),
        level_high: parseFloat(highSlider.value)
    };

    // 发送 API 请求
    fetch('/audit/api/update-threshold/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 更新本地数据
            ThresholdEditor.thresholdData[indicatorCode].level_low = payload.level_low;
            ThresholdEditor.thresholdData[indicatorCode].level_high = payload.level_high;
            ThresholdEditor.originalValues[indicatorCode] = {
                level_low: payload.level_low,
                level_high: payload.level_high
            };
            showNotification('阈值已保存', 'success');
        } else {
            showNotification('保存失败: ' + (data.error || '未知错误'), 'error');
        }
    })
    .catch(error => {
        showNotification('保存失败: ' + error.message, 'error');
    });
}

/**
 * 保存所有阈值
 */
function saveAllThresholds() {
    const indicatorCodes = Object.keys(ThresholdEditor.thresholdData);
    let savedCount = 0;
    let errorCount = 0;

    indicatorCodes.forEach(code => {
        saveThresholdSync(code)
            .then(() => savedCount++)
            .catch(() => errorCount++);
    });

    setTimeout(() => {
        if (errorCount === 0) {
            showNotification(`成功保存 ${savedCount} 个阈值`, 'success');
        } else {
            showNotification(`保存完成: ${savedCount} 成功, ${errorCount} 失败`, 'warning');
        }
    }, 1000);
}

/**
 * 同步保存单个阈值
 */
function saveThresholdSync(indicatorCode) {
    const lowSlider = document.getElementById(`lowSlider_${indicatorCode}`);
    const highSlider = document.getElementById(`highSlider_${indicatorCode}`);

    if (!lowSlider || !highSlider) {
        return Promise.reject('滑块未找到');
    }

    const payload = {
        indicator_code: indicatorCode,
        level_low: parseFloat(lowSlider.value),
        level_high: parseFloat(highSlider.value)
    };

    return fetch('/audit/api/update-threshold/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify(payload)
    })
    .then(response => {
        if (!response.ok) throw new Error('保存失败');
        return response.json();
    })
    .then(data => {
        if (!data.success) throw new Error(data.error || '未知错误');
        // 更新本地数据
        ThresholdEditor.thresholdData[indicatorCode].level_low = payload.level_low;
        ThresholdEditor.thresholdData[indicatorCode].level_high = payload.level_high;
        return data;
    });
}

/**
 * 重置单个阈值
 */
function resetThreshold(indicatorCode) {
    const original = ThresholdEditor.originalValues[indicatorCode];
    if (!original) return;

    const lowSlider = document.getElementById(`lowSlider_${indicatorCode}`);
    const highSlider = document.getElementById(`highSlider_${indicatorCode}`);

    if (lowSlider) {
        lowSlider.value = original.level_low;
        updateLowValue(indicatorCode, original.level_low);
    }

    if (highSlider) {
        highSlider.value = original.level_high;
        updateHighValue(indicatorCode, original.level_high);
    }
}

/**
 * 重置所有阈值
 */
function resetAllThresholds() {
    Object.keys(ThresholdEditor.originalValues).forEach(code => {
        resetThreshold(code);
    });
    showNotification('所有阈值已重置', 'info');
}

/**
 * 预览单个阈值
 */
function previewThreshold(indicatorCode) {
    const data = ThresholdEditor.thresholdData[indicatorCode];
    if (!data) return;

    // 打开预览对话框或导航到预览页面
    window.open(`/audit/preview/${indicatorCode}/`, '_blank');
}

/**
 * 运行完整验证
 */
function runValidation() {
    showNotification('正在运行验证...', 'info');

    fetch('/audit/api/run-validation/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.validation_run_id) {
            showNotification('验证已启动', 'success');
            // 可以跳转到验证结果页面
            setTimeout(() => {
                window.location.href = `/audit/validation/${data.validation_run_id}/`;
            }, 1000);
        } else {
            showNotification('验证启动失败', 'error');
        }
    })
    .catch(error => {
        showNotification('验证失败: ' + error.message, 'error');
    });
}

/**
 * 导出配置
 */
function exportConfig() {
    const config = Object.keys(ThresholdEditor.thresholdData).map(code => {
        const data = ThresholdEditor.thresholdData[code];
        return {
            indicator_code: code,
            level_low: data.level_low,
            level_high: data.level_high
        };
    });

    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `threshold-config-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);

    showNotification('配置已导出', 'success');
}

/**
 * 导入配置
 */
function importConfig() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json';

    input.onchange = (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const config = JSON.parse(event.target.result);
                applyImportedConfig(config);
            } catch (error) {
                showNotification('配置文件格式错误', 'error');
            }
        };
        reader.readAsText(file);
    };

    input.click();
}

/**
 * 应用导入的配置
 */
function applyImportedConfig(config) {
    config.forEach(item => {
        const { indicator_code, level_low, level_high } = item;
        const lowSlider = document.getElementById(`lowSlider_${indicator_code}`);
        const highSlider = document.getElementById(`highSlider_${indicator_code}`);

        if (lowSlider && highSlider) {
            lowSlider.value = level_low;
            highSlider.value = level_high;
            updateLowValue(indicator_code, level_low);
            updateHighValue(indicator_code, level_high);
        }
    });

    showNotification(`已导入 ${config.length} 个配置`, 'success');
}

/**
 * 获取 CSRF Token
 */
function getCsrfToken() {
    const cookies = document.cookie.split(';');
    for (let cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrftoken') return decodeURIComponent(value);
    }
    return '';
}

/**
 * 显示通知
 */
function showNotification(message, type = 'info') {
    // 简单的通知实现
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.textContent = message;
    notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : type === 'warning' ? '#f59e0b' : '#64748b'};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 9999;
        animation: slideIn 0.3s ease-out;
    `;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

// 添加动画样式
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// 全局暴露
window.ThresholdEditor = ThresholdEditor;
window.updateLowValue = updateLowValue;
window.updateHighValue = updateHighValue;
window.saveThreshold = saveThreshold;
window.saveAllThresholds = saveAllThresholds;
window.resetThreshold = resetThreshold;
window.resetAllThresholds = resetAllThresholds;
window.previewThreshold = previewThreshold;
window.runValidation = runValidation;
window.exportConfig = exportConfig;
window.importConfig = importConfig;
