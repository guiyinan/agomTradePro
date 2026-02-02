/**
 * Teaching Modal - AgomSAAF 教学模块模态窗管理
 * 功能：模态窗打开/关闭、章节导航、手风琴折叠
 */

// ========================================
// 模态窗控制
// ========================================

/**
 * 打开教学模态窗
 */
function openTeachingModal() {
    const modal = document.getElementById('teachingModal');
    if (modal) {
        modal.classList.add('show');
        // 阻止背景滚动
        document.body.style.overflow = 'hidden';
    }
}

/**
 * 关闭教学模态窗
 */
function closeTeachingModal() {
    const modal = document.getElementById('teachingModal');
    if (modal) {
        modal.classList.remove('show');
        // 恢复背景滚动
        document.body.style.overflow = '';
    }
}

/**
 * ESC 键关闭模态窗
 */
document.addEventListener('keydown', function(event) {
    if (event.key === 'Escape') {
        const modal = document.getElementById('teachingModal');
        if (modal && modal.classList.contains('show')) {
            closeTeachingModal();
        }
    }
});

/**
 * 点击模态窗外部关闭
 */
document.addEventListener('click', function(event) {
    const modal = document.getElementById('teachingModal');
    if (modal && modal.classList.contains('show')) {
        const backdrop = modal.querySelector('.modal-backdrop');
        if (event.target === backdrop) {
            closeTeachingModal();
        }
    }
});

// ========================================
// 章节导航
// ========================================

/**
 * 初始化教学导航
 */
function initTeachingNav() {
    const navItems = document.querySelectorAll('.teaching-nav-item');
    const sections = document.querySelectorAll('.teaching-section');

    navItems.forEach(item => {
        item.addEventListener('click', function() {
            const target = this.dataset.target;
            if (!target) return;

            // 更新导航状态
            navItems.forEach(nav => nav.classList.remove('active'));
            this.classList.add('active');

            // 切换内容区
            sections.forEach(section => section.classList.remove('active'));
            const targetSection = document.getElementById(`section-${target}`);
            if (targetSection) {
                targetSection.classList.add('active');
                // 滚动到顶部
                targetSection.scrollTop = 0;
            }
        });
    });
}

// ========================================
// 手风琴折叠
// ========================================

/**
 * 切换手风琴展开/折叠状态
 * @param {HTMLElement} header - 点击的 accordion-header 元素
 */
function toggleAccordion(header) {
    const item = header.closest('.accordion-item');
    const isOpen = item.classList.contains('open');

    // 如果是手风琴模式（同时只能展开一个），关闭其他所有
    const accordion = header.closest('.accordion');
    const siblings = accordion.querySelectorAll('.accordion-item.open');
    siblings.forEach(sibling => {
        if (sibling !== item) {
            sibling.classList.remove('open');
        }
    });

    // 切换当前项
    item.classList.toggle('open', !isOpen);
}

/**
 * 初始化所有手风琴
 */
function initAccordions() {
    // 默认展开第一个手风琴项（如果有 .open 类）
    const openItems = document.querySelectorAll('.accordion-item.open');
    openItems.forEach(item => {
        const content = item.querySelector('.accordion-content');
        if (content) {
            content.style.maxHeight = content.scrollHeight + 'px';
        }
    });
}

// ========================================
// 历史案例导航
// ========================================

/**
 * 显示案例详情
 * @param {string} caseId - 案例ID (如 'case2020')
 */
function showCaseDetail(caseId) {
    // 隐藏案例列表
    const casesList = document.getElementById('casesList');
    if (casesList) {
        casesList.style.display = 'none';
    }

    // 显示对应案例详情
    const caseDetail = document.getElementById(`caseDetail${caseId.replace('case', '')}`);
    if (caseDetail) {
        caseDetail.classList.add('active');
    }
}

/**
 * 隐藏案例详情，返回列表
 */
function hideCaseDetail() {
    // 隐藏所有案例详情
    const caseDetails = document.querySelectorAll('.case-detail');
    caseDetails.forEach(detail => {
        detail.classList.remove('active');
    });

    // 显示案例列表
    const casesList = document.getElementById('casesList');
    if (casesList) {
        casesList.style.display = 'grid';
    }
}

// ========================================
// 移动端菜单切换
// ========================================

/**
 * 切换移动端侧边栏
 */
function toggleMobileSidebar() {
    const sidebar = document.querySelector('.teaching-sidebar');
    if (sidebar) {
        sidebar.classList.toggle('mobile-open');
    }
}

// ========================================
// 初始化
// ========================================

/**
 * DOM 加载完成后初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    initTeachingNav();
    initAccordions();

    // 添加动画效果到模态窗打开
    const modal = document.getElementById('teachingModal');
    if (modal) {
        modal.addEventListener('transitionend', function() {
            if (this.classList.contains('show')) {
                // 模态窗打开后的操作
                console.log('Teaching modal opened');
            }
        });
    }
});

// ========================================
// 导出全局函数（供 HTML 调用）
// ========================================

// 确保 HTML 中的 onclick 可以调用这些函数
window.openTeachingModal = openTeachingModal;
window.closeTeachingModal = closeTeachingModal;
window.toggleAccordion = toggleAccordion;
window.showCaseDetail = showCaseDetail;
window.hideCaseDetail = hideCaseDetail;

// ========================================
// 平滑滚动优化
// ========================================

/**
 * 为章节内容添加平滑滚动
 */
function smoothScrollToSection(sectionId) {
    const section = document.getElementById(`section-${sectionId}`);
    if (section) {
        section.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
        });
    }
}

// ========================================
// 学习进度追踪（可选功能）
// ========================================

/**
 * 记录已读章节
 * @param {string} sectionId - 章节ID
 */
function markSectionRead(sectionId) {
    try {
        const readSections = JSON.parse(localStorage.getItem('teaching_read_sections') || '[]');
        if (!readSections.includes(sectionId)) {
            readSections.push(sectionId);
            localStorage.setItem('teaching_read_sections', JSON.stringify(readSections));
        }
    } catch (e) {
        console.warn('Failed to save read sections:', e);
    }
}

/**
 * 获取已读章节列表
 * @returns {Array} 已读章节ID数组
 */
function getReadSections() {
    try {
        return JSON.parse(localStorage.getItem('teaching_read_sections') || '[]');
    } catch (e) {
        return [];
    }
}

/**
 * 更新章节导航的已读状态
 */
function updateReadStatus() {
    const readSections = getReadSections();
    const navItems = document.querySelectorAll('.teaching-nav-item');

    navItems.forEach(item => {
        const target = item.dataset.target;
        if (readSections.includes(target)) {
            // 添加已读标记
            if (!item.querySelector('.read-indicator')) {
                const indicator = document.createElement('span');
                indicator.className = 'read-indicator';
                indicator.innerHTML = '✓';
                indicator.style.cssText = 'margin-left: auto; color: var(--color-success, #22c55e);';
                item.appendChild(indicator);
            }
        }
    });
}

// 监听章节切换，记录阅读进度
document.addEventListener('DOMContentLoaded', function() {
    const navItems = document.querySelectorAll('.teaching-nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            const target = this.dataset.target;
            markSectionRead(target);
            updateReadStatus();
        });
    });

    // 初始化已读状态
    updateReadStatus();
});

// ========================================
// 打印功能（可选）
// ========================================

/**
 * 打印当前章节
 */
function printCurrentSection() {
    const activeSection = document.querySelector('.teaching-section.active');
    if (activeSection) {
        const printContent = activeSection.innerHTML;
        const printWindow = window.open('', '_blank');
        printWindow.document.write(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>AgomSAAF 教学指南</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; padding: 20px; }
                    h2 { color: #333; border-bottom: 2px solid #eee; padding-bottom: 10px; }
                    h4 { color: #555; margin-top: 20px; }
                    p, li { line-height: 1.6; color: #666; }
                    table { width: 100%; border-collapse: collapse; margin: 15px 0; }
                    th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
                    th { background: #f5f5f5; }
                    .info-box, .warning-box, .success-box { padding: 15px; margin: 15px 0; border-left: 4px solid; }
                    .info-box { background: #eff6ff; border-color: #3b82f6; }
                    .warning-box { background: #fff7ed; border-color: #f59e0b; }
                    .success-box { background: #f0fdf4; border-color: #22c55e; }
                </style>
            </head>
            <body>${printContent}</body>
            </html>
        `);
        printWindow.document.close();
        printWindow.print();
    }
}

// 导出打印函数
window.printCurrentSection = printCurrentSection;
