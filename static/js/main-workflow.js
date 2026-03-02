/**
 * Main Workflow Panel JavaScript
 *
 * 首页主流程面板交互逻辑
 *
 * @version 1.0.0
 * @updated 2026-03-01
 */

// ========== 全局变量 ==========
let currentCandidateId = null;
let currentRequestId = null;
let precheckResults = {};

async function refreshWorkflowCandidates() {
    try {
        const response = await fetch('/dashboard/api/workflow/refresh-candidates/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({})
        });
        const data = await response.json();

        if (!data.success) {
            showToast('候选刷新失败: ' + (data.error || '未知错误'), 'error');
            return;
        }

        const result = data.result || {};
        showToast(
            `刷新完成：新增${result.generated || 0}，提升可行动${result.promoted_to_actionable || 0}`,
            'success'
        );
        setTimeout(() => window.location.reload(), 600);
    } catch (error) {
        showToast('候选刷新失败: ' + error.message, 'error');
    }
}

// ========== 预检查功能 ==========

/**
 * 执行预检查
 *
 * @param {string} candidateId - 候选 ID
 * @param {string} assetCode - 资产代码
 */
async function performPrecheck(candidateId, assetCode) {
    const precheckButton = document.querySelector(`[data-candidate-id="${candidateId}"] .btn-precheck`);
    const resultContainer = document.querySelector(`[data-candidate-id="${candidateId}"] .precheck-result-container`);

    try {
        // 禁用按钮并显示加载状态
        precheckButton.disabled = true;
        precheckButton.innerHTML = '<span class="spinner"></span> 检查中...';

        // 调用预检查 API
        const response = await fetch('/api/decision-workflow/precheck/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify({
                candidate_id: candidateId
            })
        });

        const data = await response.json();

        // 保存预检查结果
        precheckResults[candidateId] = data.result;

        // 显示结果
        displayPrecheckResult(resultContainer, data.result, assetCode);

        // 更新按钮状态
        precheckButton.disabled = false;
        precheckButton.innerHTML = '✓ 重新检查';

        // 根据结果启用/禁用提交按钮
        const submitButton = document.querySelector(`[data-candidate-id="${candidateId}"] .btn-submit-decision`);
        if (data.result.errors && data.result.errors.length > 0) {
            submitButton.disabled = true;
            submitButton.title = '预检查未通过，无法提交';
        } else {
            submitButton.disabled = false;
            submitButton.title = '';
        }

    } catch (error) {
        console.error('Precheck failed:', error);
        showToast('预检查失败: ' + error.message, 'error');
        precheckButton.disabled = false;
        precheckButton.innerHTML = '重新检查';
    }
}

/**
 * 显示预检查结果
 *
 * @param {HTMLElement} container - 结果容器
 * @param {Object} result - 预检查结果
 * @param {string} assetCode - 资产代码
 */
function displayPrecheckResult(container, result, assetCode) {
    const hasErrors = result.errors && result.errors.length > 0;
    const hasWarnings = result.warnings && result.warnings.length > 0;

    let html = `<div class="precheck-result ${hasErrors ? 'failed' : 'passed'}">`;
    html += `<div class="precheck-result-item">`;
    html += `<span>${result.beta_gate_passed ? '✓' : '✗'}</span>`;
    html += `<span>Beta Gate: ${result.beta_gate_passed ? '通过' : '未通过'}</span>`;
    html += `</div>`;

    html += `<div class="precheck-result-item">`;
    html += `<span>${result.quota_ok ? '✓' : '✗'}</span>`;
    html += `<span>配额: ${result.quota_ok ? '充足' : '已耗尽'}</span>`;
    html += `</div>`;

    html += `<div class="precheck-result-item">`;
    html += `<span>${result.cooldown_ok ? '✓' : '✗'}</span>`;
    html += `<span>冷却期: ${result.cooldown_ok ? '已过' : '冷却中'}</span>`;
    html += `</div>`;

    html += `<div class="precheck-result-item">`;
    html += `<span>${result.candidate_valid ? '✓' : '✗'}</span>`;
    html += `<span>候选状态: ${result.candidate_valid ? '有效' : '无效'}</span>`;
    html += `</div>`;

    if (hasErrors) {
        html += `<div class="precheck-result-item" style="color: var(--color-error);">`;
        html += `<strong>阻断原因:</strong> ${result.errors.join(', ')}`;
        html += `</div>`;
    }

    if (hasWarnings) {
        html += `<div class="precheck-result-item" style="color: var(--color-warning);">`;
        html += `<strong>警告:</strong> ${result.warnings.join(', ')}`;
        html += `</div>`;
    }

    html += `</div>`;

    container.innerHTML = html;
}

// ========== 决策提交功能 ==========

/**
 * 提交决策请求
 *
 * @param {string} candidateId - 候选 ID
 * @param {string} assetCode - 资产代码
 * @param {string} assetClass - 资产类别
 * @param {string} direction - 方向
 * @param {number} confidence - 置信度
 * @param {string} thesis - 投资论点
 */
async function submitDecision(candidateId, assetCode, assetClass, direction, confidence, thesis) {
    const submitButton = document.querySelector(`[data-candidate-id="${candidateId}"] .btn-submit-decision`);

    try {
        // 禁用按钮
        submitButton.disabled = true;
        submitButton.innerHTML = '<span class="spinner"></span> 提交中...';

        // 构造请求
        const payload = {
            asset_code: assetCode,
            asset_class: assetClass || 'unknown',
            direction: direction === 'SHORT' ? 'SELL' : 'BUY',
            priority: 'high',
            trigger_id: candidateId,
            candidate_id: candidateId,
            reason: thesis || `来源候选 ${candidateId}`,
            expected_confidence: Number(confidence || 0),
            quota_period: 'weekly'
        };

        // 调用提交 API
        const response = await fetch('/api/decision-rhythm/submit/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.success) {
            showToast('决策请求已提交', 'success');

            // 保存 request_id 以供执行使用
            currentRequestId = data.result.request_id;

            // 更新 UI：启用执行按钮
            const executeButton = document.querySelector(`[data-candidate-id="${candidateId}"] .btn-execute`);
            executeButton.disabled = false;
            executeButton.dataset.requestId = currentRequestId;

            // 更新步骤状态
            updateWorkflowStep(2, 'completed'); // 决策步骤完成
            updateWorkflowStep(3, 'active');    // 执行步骤激活

            // 滚动到执行按钮
            executeButton.scrollIntoView({ behavior: 'smooth', block: 'center' });
        } else {
            showToast('提交失败: ' + (data.error || '未知错误'), 'error');
            submitButton.disabled = false;
            submitButton.innerHTML = '提交决策';
        }

    } catch (error) {
        console.error('Submit decision failed:', error);
        showToast('提交失败: ' + error.message, 'error');
        submitButton.disabled = false;
        submitButton.innerHTML = '提交决策';
    }
}

// ========== 执行功能 ==========

/**
 * 打开执行模态框
 *
 * @param {string} candidateId - 候选 ID
 * @param {string} requestId - 决策请求 ID
 * @param {string} assetCode - 资产代码
 * @param {string} direction - 方向
 */
function openExecuteModal(candidateId, requestId, assetCode, direction) {
    currentCandidateId = candidateId;
    currentRequestId = requestId;

    const modal = document.getElementById('executeModal');
    const modalAssetCode = document.getElementById('modalAssetCode');
    const modalDirection = document.getElementById('modalDirection');
    const assetCodeInput = document.getElementById('executeAssetCode');
    const actionSelect = document.getElementById('executeAction');

    // 填充模态框信息
    modalAssetCode.textContent = assetCode;
    modalDirection.textContent = direction === 'BUY' ? '做多' : '做空';
    assetCodeInput.value = assetCode;
    actionSelect.value = direction === 'BUY' ? 'buy' : 'sell';

    // 显示模态框
    modal.classList.add('active');

    // 加载模拟账户列表
    loadSimulatedAccounts();
}

/**
 * 关闭执行模态框
 */
function closeExecuteModal() {
    const modal = document.getElementById('executeModal');
    modal.classList.remove('active');

    // 重置表单
    document.getElementById('executeForm').reset();
    currentCandidateId = null;
    currentRequestId = null;
}

/**
 * 选择执行目标
 *
 * @param {string} target - 执行目标 (SIMULATED/ACCOUNT)
 */
function selectExecutionTarget(target) {
    // 更新选择状态
    document.querySelectorAll('.target-option').forEach(option => {
        option.classList.remove('selected');
    });
    document.querySelector(`[data-target="${target}"]`).classList.add('selected');

    // 显示对应的表单字段
    const simFields = document.getElementById('simulatedFields');
    const accountFields = document.getElementById('accountFields');

    if (target === 'SIMULATED') {
        simFields.style.display = 'block';
        accountFields.style.display = 'none';
    } else {
        simFields.style.display = 'none';
        accountFields.style.display = 'block';
    }

    // 保存选择
    document.getElementById('executionTarget').value = target;
}

/**
 * 加载模拟账户列表
 */
async function loadSimulatedAccounts() {
    try {
        const response = await fetch('/api/simulated-trading/accounts/', {
            headers: {
                'X-CSRFToken': window.csrfToken
            }
        });

        const data = await response.json();

        if (data.success) {
            const select = document.getElementById('simAccountId');
            select.innerHTML = '<option value="">请选择账户</option>';

            data.results.forEach(account => {
                const option = document.createElement('option');
                option.value = account.account_id;
                option.textContent = `${account.name} (${account.initial_capital}元)`;
                select.appendChild(option);
            });
        }
    } catch (error) {
        console.error('Failed to load simulated accounts:', error);
    }
}

/**
 * 确认执行
 */
async function confirmExecute() {
    const target = document.getElementById('executionTarget').value;

    if (!target) {
        showToast('请选择执行目标', 'error');
        return;
    }

    const confirmButton = document.getElementById('confirmExecuteButton');
    confirmButton.disabled = true;
    confirmButton.innerHTML = '<span class="spinner"></span> 执行中...';

    try {
        let payload = {
            target: target
        };

        if (target === 'SIMULATED') {
            // 模拟盘执行
            const simAccountId = document.getElementById('simAccountId').value;
            const assetCode = document.getElementById('executeAssetCode').value;
            const action = document.getElementById('executeAction').value;
            const quantity = parseInt(document.getElementById('executeQuantity').value);
            const price = parseFloat(document.getElementById('executePrice').value);

            if (!simAccountId || !quantity || !price) {
                showToast('请填写完整的执行参数', 'error');
                confirmButton.disabled = false;
                confirmButton.innerHTML = '确认执行';
                return;
            }

            payload = {
                ...payload,
                sim_account_id: parseInt(simAccountId),
                asset_code: assetCode,
                action: action,
                quantity: quantity,
                price: price,
                reason: '按决策请求执行'
            };
        } else {
            // 账户持仓记录
            const portfolioId = document.getElementById('portfolioId').value;
            const assetCode = document.getElementById('executeAssetCode').value;
            const shares = parseInt(document.getElementById('executeShares').value);
            const avgCost = parseFloat(document.getElementById('executeAvgCost').value);
            const currentPrice = parseFloat(document.getElementById('executeCurrentPrice').value);

            if (!portfolioId || !shares || !avgCost || !currentPrice) {
                showToast('请填写完整的持仓参数', 'error');
                confirmButton.disabled = false;
                confirmButton.innerHTML = '确认执行';
                return;
            }

            payload = {
                ...payload,
                portfolio_id: parseInt(portfolioId),
                asset_code: assetCode,
                shares: shares,
                avg_cost: avgCost,
                current_price: currentPrice,
                reason: '按决策请求落地持仓'
            };
        }

        // 调用执行 API
        const response = await fetch(`/api/decision-rhythm/requests/${currentRequestId}/execute/`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': window.csrfToken
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (data.success) {
            showToast('执行成功', 'success');

            // 关闭模态框
            closeExecuteModal();

            // 更新步骤状态
            updateWorkflowStep(3, 'completed'); // 执行步骤完成
            updateWorkflowStep(4, 'active');    // 回写步骤激活

            // 刷新页面以显示最新状态
            setTimeout(() => {
                window.location.reload();
            }, 1500);
        } else {
            showToast('执行失败: ' + (data.error || '未知错误'), 'error');
            confirmButton.disabled = false;
            confirmButton.innerHTML = '确认执行';
        }

    } catch (error) {
        console.error('Execute failed:', error);
        showToast('执行失败: ' + error.message, 'error');
        confirmButton.disabled = false;
        confirmButton.innerHTML = '确认执行';
    }
}

// ========== 工作流步骤更新 ==========

/**
 * 更新工作流步骤状态
 *
 * @param {number} stepIndex - 步骤索引 (0-based)
 * @param {string} status - 状态 (active/completed)
 */
function updateWorkflowStep(stepIndex, status) {
    const steps = document.querySelectorAll('.workflow-step');

    if (steps[stepIndex]) {
        steps[stepIndex].classList.remove('active', 'completed');
        steps[stepIndex].classList.add(status);
    }
}

// ========== Toast 提示 ==========

/**
 * 显示 Toast 提示
 *
 * @param {string} message - 提示消息
 * @param {string} type - 类型 (success/error/warning/info)
 */
function showToast(message, type = 'info') {
    const colors = {
        success: '#10b981',
        error: '#ef4444',
        warning: '#f59e0b',
        info: '#3b82f6'
    };

    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 12px 20px;
        background: ${colors[type]};
        color: white;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
    `;
    toast.textContent = message;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ========== 初始化 ==========

document.addEventListener('DOMContentLoaded', function() {
    // 点击模态框外部关闭
    document.getElementById('executeModal')?.addEventListener('click', function(e) {
        if (e.target === this) {
            closeExecuteModal();
        }
    });

    // ESC 键关闭模态框
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeExecuteModal();
        }
    });
});
