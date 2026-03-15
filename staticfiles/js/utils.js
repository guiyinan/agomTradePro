/**
 * AgomSAAF - 前端工具函数库
 * 提供通用的辅助函数和 UI 组件封装
 */

// ========================================
// 格式化函数
// ========================================

/**
 * 格式化数字为千分位
 * @param {number} num - 数字
 * @param {number} decimals - 小数位数
 * @returns {string} 格式化后的字符串
 */
function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || isNaN(num)) {
        return '-';
    }
    return num.toLocaleString('zh-CN', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
    });
}

/**
 * 格式化货币
 * @param {number} amount - 金额
 * @param {string} currency - 货币符号
 * @returns {string} 格式化后的货币字符串
 */
function formatCurrency(amount, currency = '¥') {
    if (amount === null || amount === undefined || isNaN(amount)) {
        return '-';
    }
    const formatted = Math.abs(amount).toLocaleString('zh-CN', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    });
    const sign = amount < 0 ? '-' : '';
    return `${sign}${currency}${formatted}`;
}

/**
 * 格式化百分比
 * @param {number} value - 数值
 * @param {number} decimals - 小数位数
 * @returns {string} 格式化后的百分比字符串
 */
function formatPercent(value, decimals = 2) {
    if (value === null || value === undefined || isNaN(value)) {
        return '-';
    }
    const formatted = (value * 100).toFixed(decimals);
    const sign = value >= 0 ? '+' : '';
    return `${sign}${formatted}%`;
}

/**
 * 格式化日期
 * @param {Date|string|number} date - 日期
 * @param {string} format - 格式化模板
 * @returns {string} 格式化后的日期字符串
 */
function formatDate(date, format = 'YYYY-MM-DD') {
    if (!date) return '-';

    const d = new Date(date);
    if (isNaN(d.getTime())) return '-';

    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    const hours = String(d.getHours()).padStart(2, '0');
    const minutes = String(d.getMinutes()).padStart(2, '0');
    const seconds = String(d.getSeconds()).padStart(2, '0');

    return format
        .replace('YYYY', year)
        .replace('MM', month)
        .replace('DD', day)
        .replace('HH', hours)
        .replace('mm', minutes)
        .replace('ss', seconds);
}

/**
 * 相对时间（多久前）
 * @param {Date|string} date - 日期
 * @returns {string} 相对时间字符串
 */
function timeAgo(date) {
    if (!date) return '-';

    const d = new Date(date);
    const now = new Date();
    const diff = now - d;

    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    const months = Math.floor(days / 30);
    const years = Math.floor(days / 365);

    if (seconds < 60) return '刚刚';
    if (minutes < 60) return `${minutes}分钟前`;
    if (hours < 24) return `${hours}小时前`;
    if (days < 30) return `${days}天前`;
    if (months < 12) return `${months}个月前`;
    return `${years}年前`;
}

// ========================================
// SweetAlert2 封装
// ========================================

/**
 * 成功提示
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 */
function alertSuccess(title, message = '') {
    Swal.fire({
        icon: 'success',
        title: title,
        text: message,
        timer: 2000,
        showConfirmButton: false
    });
}

/**
 * 错误提示
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 */
function alertError(title, message = '') {
    Swal.fire({
        icon: 'error',
        title: title,
        text: message
    });
}

/**
 * 警告提示
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 */
function alertWarning(title, message = '') {
    Swal.fire({
        icon: 'warning',
        title: title,
        text: message
    });
}

/**
 * 信息提示
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 */
function alertInfo(title, message = '') {
    Swal.fire({
        icon: 'info',
        title: title,
        text: message
    });
}

/**
 * 确认对话框
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 * @param {string} confirmText - 确认按钮文字
 * @param {string} cancelText - 取消按钮文字
 * @returns {Promise<boolean>} 用户是否确认
 */
function confirmDialog(title, message = '', confirmText = '确认', cancelText = '取消') {
    return Swal.fire({
        title: title,
        text: message,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: confirmText,
        cancelButtonText: cancelText,
        confirmButtonColor: '#2563eb',
        cancelButtonColor: '#64748b'
    }).then((result) => result.isConfirmed);
}

/**
 * 危险操作确认
 * @param {string} title - 标题
 * @param {string} message - 消息内容
 * @returns {Promise<boolean>} 用户是否确认
 */
function confirmDanger(title, message = '') {
    return Swal.fire({
        title: title,
        text: message,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: '确定删除',
        cancelButtonText: '取消',
        confirmButtonColor: '#ef4444',
        cancelButtonColor: '#64748b'
    }).then((result) => result.isConfirmed);
}

/**
 * 加载提示
 * @param {string} message - 消息内容
 * @returns {Object} Swal 实例，用于关闭
 */
function alertLoading(message = '加载中...') {
    return Swal.fire({
        title: message,
        allowOutsideClick: false,
        didOpen: () => {
            Swal.showLoading();
        }
    });
}

// ========================================
// 模态框操作
// ========================================

/**
 * 打开模态框
 * @param {string} modalId - 模态框 ID
 */
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('show');
        document.body.style.overflow = 'hidden';
    }
}

/**
 * 关闭模态框
 * @param {string} modalId - 模态框 ID
 */
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('show');
        document.body.style.overflow = '';
    }
}

/**
 * 初始化所有模态框（点击背景关闭）
 */
function initModals() {
    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal || e.target.classList.contains('modal-backdrop')) {
                closeModal(modal.id);
            }
        });

        // 关闭按钮
        modal.querySelectorAll('.modal-close').forEach(btn => {
            btn.addEventListener('click', () => closeModal(modal.id));
        });
    });
}

// ========================================
// 标签页操作
// ========================================

/**
 * 切换标签页
 * @param {string} tabId - 标签项 ID
 * @param {string} contentId - 内容区域 ID
 */
function switchTab(tabId, contentId) {
    // 移除所有 active 类
    document.querySelectorAll('.tab-item').forEach(tab => {
        tab.classList.remove('active');
    });
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });

    // 添加 active 类到当前标签
    document.getElementById(tabId)?.classList.add('active');
    document.getElementById(contentId)?.classList.add('active');
}

/**
 * 初始化标签页
 */
function initTabs() {
    document.querySelectorAll('.tab-item').forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.target;
            const content = tab.dataset.content;
            if (target && content) {
                switchTab(target, content);
            }
        });
    });
}

// ========================================
// 手风琴操作
// ========================================

/**
 * 切换手风琴
 * @param {string} itemId - 手风琴项 ID
 */
function toggleAccordion(itemId) {
    const item = document.getElementById(itemId);
    if (item) {
        item.classList.toggle('open');
    }
}

/**
 * 初始化手风琴
 */
function initAccordions() {
    document.querySelectorAll('.accordion-header').forEach(header => {
        header.addEventListener('click', () => {
            const item = header.closest('.accordion-item');
            const isAlreadyOpen = item.classList.contains('open');

            // 如果不是手风琴组（允许同时打开多个），则关闭其他
            const accordion = item.closest('.accordion');
            if (accordion && !accordion.dataset.multiple) {
                accordion.querySelectorAll('.accordion-item.open').forEach(openItem => {
                    if (openItem !== item) {
                        openItem.classList.remove('open');
                    }
                });
            }

            // 切换当前项
            item.classList.toggle('open', !isAlreadyOpen);
        });
    });
}

// ========================================
// 表单辅助函数
// ========================================

/**
 * 序列化表单为对象
 * @param {HTMLFormElement} form - 表单元素
 * @returns {Object} 表单数据对象
 */
function serializeForm(form) {
    const formData = new FormData(form);
    const data = {};

    for (const [key, value] of formData.entries()) {
        // 处理多选框
        if (key.endsWith('[]')) {
            const cleanKey = key.slice(0, -2);
            if (!data[cleanKey]) {
                data[cleanKey] = [];
            }
            data[cleanKey].push(value);
        } else {
            data[key] = value;
        }
    }

    return data;
}

/**
 * 重置表单
 * @param {HTMLFormElement} form - 表单元素
 */
function resetForm(form) {
    form.reset();
    // 清除自定义验证样式
    form.querySelectorAll('.is-invalid, .is-valid').forEach(el => {
        el.classList.remove('is-invalid', 'is-valid');
    });
}

/**
 * 显示表单验证错误
 * @param {HTMLInputElement} input - 输入框元素
 * @param {string} message - 错误消息
 */
function showFieldError(input, message) {
    input.classList.add('is-invalid');
    input.classList.remove('is-valid');

    let feedback = input.parentElement.querySelector('.invalid-feedback');
    if (!feedback) {
        feedback = document.createElement('div');
        feedback.className = 'invalid-feedback';
        input.parentElement.appendChild(feedback);
    }
    feedback.textContent = message;
}

/**
 * 清除表单验证错误
 * @param {HTMLInputElement} input - 输入框元素
 */
function clearFieldError(input) {
    input.classList.remove('is-invalid');
    const feedback = input.parentElement.querySelector('.invalid-feedback');
    if (feedback) {
        feedback.remove();
    }
}

// ========================================
// 数据表格辅助函数
// ========================================

/**
 * 排序表格
 * @param {HTMLTableElement} table - 表格元素
 * @param {number} colIndex - 列索引
 * @param {string} type - 排序类型 (number|string|date)
 */
function sortTable(table, colIndex, type = 'string') {
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    const isAsc = tbody.dataset.sortOrder !== 'asc';

    rows.sort((a, b) => {
        const aValue = a.cells[colIndex].textContent.trim();
        const bValue = b.cells[colIndex].textContent.trim();

        let comparison = 0;
        if (type === 'number') {
            comparison = parseFloat(aValue) - parseFloat(bValue);
        } else if (type === 'date') {
            comparison = new Date(aValue) - new Date(bValue);
        } else {
            comparison = aValue.localeCompare(bValue, 'zh-CN');
        }

        return isAsc ? comparison : -comparison;
    });

    rows.forEach(row => tbody.appendChild(row));
    tbody.dataset.sortOrder = isAsc ? 'asc' : 'desc';
}

/**
 * 过滤表格
 * @param {HTMLTableElement} table - 表格元素
 * @param {number} colIndex - 列索引
 * @param {string} keyword - 关键词
 */
function filterTable(table, colIndex, keyword) {
    const tbody = table.querySelector('tbody');
    const rows = tbody.querySelectorAll('tr');

    rows.forEach(row => {
        const cell = row.cells[colIndex];
        const value = cell?.textContent.trim().toLowerCase() || '';
        const matches = value.includes(keyword.toLowerCase());
        row.style.display = matches ? '' : 'none';
    });
}

// ========================================
// 复制到剪贴板
// ========================================

/**
 * 复制文本到剪贴板
 * @param {string} text - 要复制的文本
 * @returns {Promise<boolean>} 是否成功
 */
async function copyToClipboard(text) {
    try {
        if (navigator.clipboard) {
            await navigator.clipboard.writeText(text);
            showToast('复制成功', 'success');
            return true;
        } else {
            // 兼容旧浏览器
            const textarea = document.createElement('textarea');
            textarea.value = text;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            showToast('复制成功', 'success');
            return true;
        }
    } catch (err) {
        showToast('复制失败', 'error');
        return false;
    }
}

// ========================================
// 下载文件
// ========================================

/**
 * 下载文件
 * @param {string} url - 文件 URL
 * @param {string} filename - 文件名
 */
function downloadFile(url, filename) {
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || '';
    link.click();
}

/**
 * 下载 CSV
 * @param {Array} data - 数据数组
 * @param {string} filename - 文件名
 */
function downloadCSV(data, filename = 'data.csv') {
    if (!data || data.length === 0) {
        showToast('没有数据可导出', 'warning');
        return;
    }

    const headers = Object.keys(data[0]);
    const csv = [
        headers.join(','),
        ...data.map(row => headers.map(h => `"${row[h] || ''}"`).join(','))
    ].join('\n');

    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    downloadFile(url, filename);
    URL.revokeObjectURL(url);
}

// ========================================
// 防抖和节流
// ========================================

/**
 * 防抖函数
 * @param {Function} func - 要执行的函数
 * @param {number} delay - 延迟时间（毫秒）
 * @returns {Function} 防抖后的函数
 */
function debounce(func, delay = 300) {
    let timeoutId;
    return function (...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => func.apply(this, args), delay);
    };
}

/**
 * 节流函数
 * @param {Function} func - 要执行的函数
 * @param {number} interval - 间隔时间（毫秒）
 * @returns {Function} 节流后的函数
 */
function throttle(func, interval = 300) {
    let lastTime = 0;
    return function (...args) {
        const now = Date.now();
        if (now - lastTime >= interval) {
            lastTime = now;
            func.apply(this, args);
        }
    };
}

// ========================================
// DOM 加载完成后初始化
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    // 初始化模态框
    initModals();

    // 初始化标签页
    initTabs();

    // 初始化手风琴
    initAccordions();
});

// 导出函数供全局使用
if (typeof window !== 'undefined') {
    Object.assign(window, {
        // 格式化函数
        formatNumber,
        formatCurrency,
        formatPercent,
        formatDate,
        timeAgo,

        // SweetAlert2 封装
        alertSuccess,
        alertError,
        alertWarning,
        alertInfo,
        confirmDialog,
        confirmDanger,
        alertLoading,

        // 模态框
        openModal,
        closeModal,

        // 标签页
        switchTab,

        // 手风琴
        toggleAccordion,

        // 表单
        serializeForm,
        resetForm,
        showFieldError,
        clearFieldError,

        // 表格
        sortTable,
        filterTable,

        // 工具函数
        copyToClipboard,
        downloadFile,
        downloadCSV,
        debounce,
        throttle
    });
}
