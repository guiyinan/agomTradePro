/**
 * AgomSAAF - HTMX 配置文件
 * 提供 HTMX 的全局配置和自定义行为
 */

// ========================================
// HTMX 全局配置
// ========================================

// 设置默认配置
if (typeof htmx !== 'undefined') {
    htmx.defineExtension('agom-extensions', {
        onEvent: function(name, evt) {
            if (name === 'htmx:afterRequest') {
                const xhr = evt.detail.xhr;
                const path = evt.detail.pathInfo.requestPath;

                // 记录请求
                console.log(`[HTMX] ${xhr.status} ${path}`);

                // 处理自定义错误头
                if (xhr.status >= 400) {
                    const errorTitle = xhr.getResponseHeader('X-Error-Title') || '请求失败';
                    const errorMessage = xhr.getResponseHeader('X-Error-Message') || xhr.responseText;

                    if (typeof Swal !== 'undefined') {
                        Swal.fire({
                            icon: 'error',
                            title: errorTitle,
                            text: errorMessage || '请稍后重试'
                        });
                    }
                }
            }
        }
    });
}

// ========================================
// HTMX 事件监听
// ========================================

document.body.addEventListener('htmx:configRequest', function(evt) {
    // 为所有 HTMX 请求添加 CSRF Token
    const csrfToken = window.csrfToken || getCookie('csrftoken');
    if (csrfToken) {
        evt.detail.headers['X-CSRFToken'] = csrfToken;
    }

    // 添加自定义头部
    evt.detail.headers['X-Requested-With'] = 'HTMX';
    evt.detail.headers['X-HTMX-Request'] = 'true';
});

document.body.addEventListener('htmx:beforeRequest', function(evt) {
    // 请求前显示加载状态
    const target = evt.detail.target;
    if (target) {
        target.classList.add('htmx-loading');
    }

    // 可以在这里添加请求拦截逻辑
    const path = evt.detail.pathInfo.requestPath;
    console.log(`[HTMX] 请求: ${path}`);
});

document.body.addEventListener('htmx:afterRequest', function(evt) {
    // 请求完成后移除加载状态
    const target = evt.detail.target;
    if (target) {
        target.classList.remove('htmx-loading');
    }

    const xhr = evt.detail.xhr;

    // 处理错误响应
    if (xhr.status >= 400) {
        console.error(`[HTMX] 错误 ${xhr.status}:`, xhr.responseText);

        // 如果目标元素存在，显示错误消息
        if (target && xhr.responseText) {
            // 如果服务器返回错误消息，显示它
            if (typeof showToast !== 'undefined') {
                showToast(xhr.responseText || '请求失败', 'error');
            }
        }
    } else {
        // 成功响应
        // 检查是否有自定义消息
        const successMsg = xhr.getResponseHeader('X-Success-Message');
        if (successMsg && typeof showToast !== 'undefined') {
            showToast(successMsg, 'success');
        }
    }
});

document.body.addEventListener('htmx:beforeSwap', function(evt) {
    // 在内容交换前执行
    // 可以在这里修改要插入的内容
});

document.body.addEventListener('htmx:afterSwap', function(evt) {
    // 内容交换后执行
    const target = evt.detail.target;
    const targetId = target.id || 'unknown';

    console.log(`[HTMX] 内容已更新: #${targetId}`);

    // 重新初始化日期选择器
    if (typeof flatpickr !== 'undefined') {
        target.querySelectorAll('input[data-datepicker]').forEach(function(input) {
            if (!input._flatpickr) {
                flatpickr(input, {
                    locale: 'zh',
                    dateFormat: 'Y-m-d',
                    allowInput: true
                });
            }
        });
    }

    // 重新初始化其他组件
    if (typeof initModals === 'function') {
        initModals();
    }
    if (typeof initTabs === 'function') {
        initTabs();
    }
    if (typeof initAccordions === 'function') {
        initAccordions();
    }

    // 触发自定义事件
    target.dispatchEvent(new CustomEvent('htmx:contentUpdated', {
        bubbles: true,
        detail: evt.detail
    }));
});

document.body.addEventListener('htmx:beforeCleanup', function(evt) {
    // 清理前执行（用于 morph-swap）
});

// ========================================
// HTMX 错误处理
// ========================================

document.body.addEventListener('htmx:responseError', function(evt) {
    const xhr = evt.detail.xhr;
    const status = xhr.status;

    let errorMsg = '请求失败';
    switch (status) {
        case 400:
            errorMsg = '请求参数错误';
            break;
        case 401:
            errorMsg = '请先登录';
            // 可以跳转到登录页
            setTimeout(() => {
                window.location.href = '/account/login/';
            }, 1500);
            break;
        case 403:
            errorMsg = '没有权限访问';
            break;
        case 404:
            errorMsg = '请求的资源不存在';
            break;
        case 500:
            errorMsg = '服务器错误';
            break;
        default:
            errorMsg = `请求失败 (${status})`;
    }

    if (typeof showToast !== 'undefined') {
        showToast(errorMsg, 'error');
    }
});

document.body.addEventListener('htmx:sendError', function(evt) {
    // 网络错误或超时
    if (typeof showToast !== 'undefined') {
        showToast('网络错误，请检查连接', 'error');
    }
});

document.body.addEventListener('htmx:timeout', function(evt) {
    if (typeof showToast !== 'undefined') {
        showToast('请求超时，请稍后重试', 'warning');
    }
});

// ========================================
// HTMX 工具函数
// ========================================

/**
 * 触发 HTMX 请求
 * @param {string} url - 请求 URL
 * @param {string} target - 目标元素选择器
 * @param {string} method - 请求方法
 * @param {Object} values - 表单数据
 */
function htmxRequest(url, target = 'body', method = 'GET', values = null) {
    if (typeof htmx === 'undefined') {
        console.error('HTMX 未加载');
        return;
    }

    const targetEl = typeof target === 'string'
        ? document.querySelector(target)
        : target;

    if (!targetEl) {
        console.error('目标元素不存在:', target);
        return;
    }

    if (method === 'GET') {
        htmx.ajax('GET', url, { target: targetEl });
    } else {
        htmx.ajax(method, url, {
            target: targetEl,
            values: values
        });
    }
}

/**
 * 刷新 HTMX 元素
 * @param {string} selector - 元素选择器
 */
function htmxRefresh(selector) {
    const el = document.querySelector(selector);
    if (el && htmx) {
        // 从当前 URL 重新加载
        const url = el.getAttribute('hx-get') || window.location.href;
        htmx.ajax('GET', url, { target: el });
    }
}

/**
 * 轮询 HTMX 元素
 * @param {string} selector - 元素选择器
 * @param {number} interval - 间隔时间（毫秒）
 * @returns {number} 定时器 ID
 */
function htmxPoll(selector, interval = 5000) {
    return setInterval(() => {
        htmxRefresh(selector);
    }, interval);
}

// ========================================
// HTMX 加载状态样式
// ========================================

// 动态添加 HTMX 加载状态的 CSS
const htmxStyles = document.createElement('style');
htmxStyles.textContent = `
    .htmx-loading {
        opacity: 0.6;
        pointer-events: none;
        position: relative;
    }

    .htmx-loading::after {
        content: '';
        position: absolute;
        top: 50%;
        left: 50%;
        width: 20px;
        height: 20px;
        margin: -10px 0 0 -10px;
        border: 2px solid #e2e8f0;
        border-top-color: #2563eb;
        border-radius: 50%;
        animation: htmx-spin 0.6s linear infinite;
    }

    @keyframes htmx-spin {
        to { transform: rotate(360deg); }
    }

    .htmx-request .htmx-indicator {
        display: inline-block !important;
        opacity: 1 !important;
    }
`;
document.head.appendChild(htmxStyles);

// ========================================
// 导出函数
// ========================================

if (typeof window !== 'undefined') {
    Object.assign(window, {
        htmxRequest,
        htmxRefresh,
        htmxPoll
    });
}
