/**
 * Learning Progress Tracker - Phase 2
 * 功能：学习进度追踪、统计、成就系统
 */

// 章节配置
const sections = [
    { id: 'basics', name: '宏观经济基础', icon: '📊', order: 1 },
    { id: 'regime', name: 'Regime 判定', icon: '🎯', order: 2 },
    { id: 'policy', name: 'Policy 档位', icon: '📰', order: 3 },
    { id: 'allocation', name: '资产配置', icon: '💼', order: 4 },
    { id: 'cases', name: '历史案例', icon: '📖', order: 5 }
];

// 子主题配置（每个章节的手风琴项）
const sectionTopics = {
    'basics': ['pmi', 'cpi', 'cycle', 'momentum'],
    'regime': ['quadrant', 'momentum_vs_level', 'confidence', 'calculator'],
    'policy': ['levels', 'events', 'rules', 'simulator'],
    'allocation': ['matrix', 'assets', 'risk_control'],
    'cases': ['case2020', 'case2022', 'case2023']
};

// 成就配置
const achievements = [
    {
        id: 'first_read',
        name: '初学者',
        description: '完成第一个章节',
        icon: '🎓',
        condition: (progress) => progress.completedSections >= 1
    },
    {
        id: 'basics_master',
        name: '基础专家',
        description: '完成宏观经济基础章节',
        icon: '📚',
        condition: (progress) => progress.completedTopics.basics >= 4
    },
    {
        id: 'regime_master',
        name: 'Regime 大师',
        description: '完成 Regime 判定章节',
        icon: '🎯',
        condition: (progress) => progress.completedTopics.regime >= 4
    },
    {
        id: 'calculator_user',
        name: '实践者',
        description: '使用 Regime 计算器',
        icon: '🧮',
        condition: (progress) => progress.calculatorUsed >= 1
    },
    {
        id: 'simulator_user',
        name: '模拟专家',
        description: '使用 Policy 模拟器',
        icon: '🎮',
        condition: (progress) => progress.simulatorUsed >= 1
    },
    {
        id: 'case_studies',
        name: '历史研究员',
        description: '阅读3个历史案例',
        icon: '📜',
        condition: (progress) => progress.completedTopics.cases >= 3
    },
    {
        id: 'half_complete',
        name: '进度过半',
        description: '完成50%的学习内容',
        icon: '📈',
        condition: (progress) => progress.totalProgress >= 50
    },
    {
        id: 'full_master',
        name: '全能专家',
        description: '完成所有学习内容',
        icon: '🏆',
        condition: (progress) => progress.totalProgress >= 100
    }
];

/**
 * 获取学习进度
 */
function getLearningProgress() {
    try {
        const saved = localStorage.getItem('teaching_learning_progress');
        if (saved) {
            return JSON.parse(saved);
        }
    } catch (e) {
        console.warn('Failed to load progress:', e);
    }

    // 默认进度
    return {
        completedSections: [],
        completedTopics: {
            basics: 0,
            regime: 0,
            policy: 0,
            allocation: 0,
            cases: 0
        },
        calculatorUsed: 0,
        simulatorUsed: 0,
        casesRead: [],
        totalTime: 0,
        lastAccessTime: null,
        totalProgress: 0
    };
}

/**
 * 保存学习进度
 */
function saveLearningProgress(progress) {
    try {
        progress.lastAccessTime = new Date().toISOString();
        progress.totalProgress = calculateTotalProgress(progress);
        localStorage.setItem('teaching_learning_progress', JSON.stringify(progress));
        updateProgressDisplay();
    } catch (e) {
        console.warn('Failed to save progress:', e);
    }
}

/**
 * 计算总进度百分比
 */
function calculateTotalProgress(progress) {
    let totalTopics = 0;
    let completedTopics = 0;

    Object.entries(sectionTopics).forEach(([section, topics]) => {
        totalTopics += topics.length;
        completedTopics += progress.completedTopics[section] || 0;
    });

    return totalTopics > 0 ? Math.round((completedTopics / totalTopics) * 100) : 0;
}

/**
 * 标记主题为已读
 */
function markTopicRead(sectionId, topicId) {
    const progress = getLearningProgress();
    progress.completedTopics[sectionId] = Math.min(
        progress.completedTopics[sectionId] + 1,
        sectionTopics[sectionId]?.length || 0
    );

    // 检查章节是否完成
    const sectionTopicsCount = sectionTopics[sectionId]?.length || 0;
    if (progress.completedTopics[sectionId] >= sectionTopicsCount) {
        if (!progress.completedSections.includes(sectionId)) {
            progress.completedSections.push(sectionId);
        }
    }

    saveLearningProgress(progress);
    checkAchievements(progress);
}

/**
 * 标记章节已访问
 */
function markSectionVisited(sectionId) {
    const progress = getLearningProgress();
    if (!progress.visitedSections) {
        progress.visitedSections = [];
    }
    if (!progress.visitedSections.includes(sectionId)) {
        progress.visitedSections.push(sectionId);
        saveLearningProgress(progress);
    }
}

/**
 * 记录计算器使用
 */
function recordCalculatorUse() {
    const progress = getLearningProgress();
    progress.calculatorUsed = (progress.calculatorUsed || 0) + 1;
    saveLearningProgress(progress);
    checkAchievements(progress);
}

/**
 * 记录模拟器使用
 */
function recordSimulatorUse() {
    const progress = getLearningProgress();
    progress.simulatorUsed = (progress.simulatorUsed || 0) + 1;
    saveLearningProgress(progress);
    checkAchievements(progress);
}

/**
 * 记录案例阅读
 */
function recordCaseRead(caseId) {
    const progress = getLearningProgress();
    if (!progress.casesRead) {
        progress.casesRead = [];
    }
    if (!progress.casesRead.includes(caseId)) {
        progress.casesRead.push(caseId);
        // 更新cases章节的进度
        progress.completedTopics.cases = Math.min(
            (progress.completedTopics.cases || 0) + 1,
            sectionTopics.cases?.length || 0
        );
        saveLearningProgress(progress);
        checkAchievements(progress);
    }
}

/**
 * 检查成就解锁
 */
function checkAchievements(progress) {
    const unlocked = getUnlockedAchievements();

    achievements.forEach(achievement => {
        if (!unlocked.includes(achievement.id) && achievement.condition(progress)) {
            unlockAchievement(achievement);
        }
    });
}

/**
 * 获取已解锁的成就
 */
function getUnlockedAchievements() {
    try {
        return JSON.parse(localStorage.getItem('teaching_achievements') || '[]');
    } catch (e) {
        return [];
    }
}

/**
 * 解锁成就
 */
function unlockAchievement(achievement) {
    const unlocked = getUnlockedAchievements();
    unlocked.push(achievement.id);
    localStorage.setItem('teaching_achievements', JSON.stringify(unlocked));

    // 成就通知已禁用，不再弹出
    // showAchievementNotification(achievement);
}

/**
 * 显示成就通知
 */
function showAchievementNotification(achievement) {
    const notification = document.createElement('div');
    notification.className = 'achievement-notification';
    notification.innerHTML = `
        <div class="achievement-content">
            <div class="achievement-icon">${achievement.icon}</div>
            <div class="achievement-text">
                <div class="achievement-title">成就解锁！</div>
                <div class="achievement-name">${achievement.name}</div>
                <div class="achievement-desc">${achievement.description}</div>
            </div>
            <button class="achievement-close" onclick="this.parentElement.parentElement.remove()">×</button>
        </div>
    `;

    document.body.appendChild(notification);

    setTimeout(() => notification.classList.add('show'), 10);

    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 4000);
}

/**
 * 渲染进度条
 */
function renderProgressBar() {
    const progress = getLearningProgress();
    const container = document.getElementById('progressBarContainer');
    if (!container) return;

    container.innerHTML = `
        <div class="learning-progress-bar">
            <div class="progress-header">
                <span class="progress-label">学习进度</span>
                <span class="progress-percentage">${progress.totalProgress}%</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill" style="width: ${progress.totalProgress}%"></div>
            </div>
            <div class="progress-stats">
                <span>已完成 ${progress.completedSections.length} / ${sections.length} 章节</span>
            </div>
        </div>
    `;
}

/**
 * 渲染章节进度列表
 */
function renderSectionProgress() {
    const progress = getLearningProgress();
    const container = document.getElementById('sectionProgressContainer');
    if (!container) return;

    container.innerHTML = `
        <div class="section-progress-list">
            ${sections.map(section => {
                const topicsCount = sectionTopics[section.id]?.length || 0;
                const completedCount = progress.completedTopics[section.id] || 0;
                const isCompleted = progress.completedSections.includes(section.id);
                const progressPercent = topicsCount > 0 ? Math.round((completedCount / topicsCount) * 100) : 0;

                return `
                    <div class="section-progress-item ${isCompleted ? 'completed' : ''}">
                        <div class="section-progress-header">
                            <span class="section-icon">${section.icon}</span>
                            <span class="section-name">${section.name}</span>
                            <span class="section-status">${isCompleted ? '✓ 已完成' : `${progressPercent}%`}</span>
                        </div>
                        <div class="section-progress-track">
                            <div class="section-progress-fill" style="width: ${progressPercent}%"></div>
                        </div>
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

/**
 * 渲染成就展示
 */
function renderAchievements() {
    const unlocked = getUnlockedAchievements();
    const container = document.getElementById('achievementsContainer');
    if (!container) return;

    container.innerHTML = `
        <div class="achievements-grid">
            ${achievements.map(achievement => {
                const isUnlocked = unlocked.includes(achievement.id);
                return `
                    <div class="achievement-card ${isUnlocked ? 'unlocked' : 'locked'}" title="${achievement.description}">
                        <div class="achievement-icon">${isUnlocked ? achievement.icon : '🔒'}</div>
                        <div class="achievement-name">${achievement.name}</div>
                        ${isUnlocked ? '<div class="achievement-badge">已解锁</div>' : ''}
                    </div>
                `;
            }).join('')}
        </div>
    `;
}

/**
 * 渲染学习统计
 */
function renderLearningStats() {
    const progress = getLearningProgress();
    const container = document.getElementById('learningStatsContainer');
    if (!container) return;

    // 计算学习时长（简化处理）
    const learningDays = progress.lastAccessTime
        ? Math.ceil((new Date() - new Date(progress.lastAccessTime)) / (1000 * 60 * 60 * 24))
        : 0;

    container.innerHTML = `
        <div class="learning-stats">
            <div class="stat-item">
                <div class="stat-value">${progress.totalProgress}%</div>
                <div class="stat-label">总进度</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${progress.completedSections.length}/${sections.length}</div>
                <div class="stat-label">完成章节</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${progress.calculatorUsed + progress.simulatorUsed}</div>
                <div class="stat-label">互动次数</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">${getUnlockedAchievements().length}</div>
                <div class="stat-label">解锁成就</div>
            </div>
        </div>
    `;
}

/**
 * 更新进度显示
 */
function updateProgressDisplay() {
    renderProgressBar();
    renderSectionProgress();
    renderAchievements();
    renderLearningStats();
}

/**
 * 渲染完整的学习进度面板
 */
function renderLearningProgressPanel() {
    const container = document.getElementById('learningProgressPanel');
    if (!container) return;

    container.innerHTML = `
        <div class="learning-progress-panel">
            <div class="panel-header">
                <h3>📊 学习进度</h3>
                <button class="reset-btn" onclick="resetLearningProgress()" title="重置进度">重置</button>
            </div>

            <div id="progressBarContainer"></div>
            <div id="learningStatsContainer"></div>

            <div class="panel-section">
                <h4>章节进度</h4>
                <div id="sectionProgressContainer"></div>
            </div>

            <div class="panel-section">
                <h4>🏆 成就</h4>
                <div id="achievementsContainer"></div>
            </div>
        </div>
    `;

    updateProgressDisplay();
}

/**
 * 重置学习进度
 */
function resetLearningProgress() {
    if (confirm('确定要重置所有学习进度吗？此操作不可撤销。')) {
        localStorage.removeItem('teaching_learning_progress');
        localStorage.removeItem('teaching_achievements');
        updateProgressDisplay();
        alert('学习进度已重置');
    }
}

/**
 * 导出学习进度
 */
function exportLearningProgress() {
    const progress = getLearningProgress();
    const achievements = getUnlockedAchievements();

    const exportData = {
        progress: progress,
        achievements: achievements,
        exportDate: new Date().toISOString()
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `agomsaaf-learning-progress-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
}

/**
 * 导入学习进度
 */
function importLearningProgress(file) {
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const data = JSON.parse(e.target.result);
            if (data.progress) {
                localStorage.setItem('teaching_learning_progress', JSON.stringify(data.progress));
            }
            if (data.achievements) {
                localStorage.setItem('teaching_achievements', JSON.stringify(data.achievements));
            }
            updateProgressDisplay();
            alert('学习进度导入成功！');
        } catch (error) {
            alert('导入失败：文件格式错误');
        }
    };
    reader.readAsText(file);
}

/**
 * 初始化手风琴阅读追踪
 */
function initAccordionTracking() {
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                const target = mutation.target;
                if (target.classList.contains('accordion-item') && target.classList.contains('open')) {
                    // 找到所属章节
                    const section = target.closest('.teaching-section');
                    if (section) {
                        const sectionId = section.id.replace('section-', '');
                        // 生成一个主题ID（简化处理）
                        const topicIndex = Array.from(target.parentElement.children).indexOf(target);
                        markTopicRead(sectionId, topicIndex);
                    }
                }
            }
        });
    });

    // 监听所有手风琴项
    setTimeout(() => {
        document.querySelectorAll('.accordion-item').forEach(item => {
            observer.observe(item, { attributes: true });
        });
    }, 1000);
}

/**
 * 导出全局函数
 */
window.markTopicRead = markTopicRead;
window.markSectionVisited = markSectionVisited;
window.recordCalculatorUse = recordCalculatorUse;
window.recordSimulatorUse = recordSimulatorUse;
window.recordCaseRead = recordCaseRead;
window.renderLearningProgressPanel = renderLearningProgressPanel;
window.resetLearningProgress = resetLearningProgress;
window.exportLearningProgress = exportLearningProgress;
window.importLearningProgress = importLearningProgress;

/**
 * 初始化
 */
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(() => {
        initAccordionTracking();
        renderLearningProgressPanel();
    }, 700);

    // 监听章节切换，记录访问
    const navItems = document.querySelectorAll('.teaching-nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', function() {
            const target = this.dataset.target;
            markSectionVisited(target);
        });
    });
});

/**
 * 添加样式
 */
(function() {
    const style = document.createElement('style');
    style.textContent = `
        /* 学习进度面板 */
        .learning-progress-panel {
            padding: 20px;
            background: var(--color-surface, #f8fafc);
            border-radius: var(--radius-md, 10px);
            margin: 20px 0;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .panel-header h3 {
            margin: 0;
            font-size: 18px;
            color: var(--color-text-primary, #0f172a);
        }

        .reset-btn {
            padding: 6px 12px;
        background: white;
        border: 1px solid var(--color-border, #e2e8f0);
        border-radius: var(--radius-sm, 6px);
        font-size: 12px;
        cursor: pointer;
        transition: all 0.2s ease;
    }

    .reset-btn:hover {
        background: #fee2e2;
        border-color: #ef4444;
        color: #ef4444;
    }

    /* 进度条 */
    .learning-progress-bar {
        margin-bottom: 24px;
    }

    .progress-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 8px;
    }

    .progress-label {
        font-size: 14px;
        font-weight: 600;
        color: var(--color-text-secondary, #475569);
    }

    .progress-percentage {
        font-size: 16px;
        font-weight: 700;
        color: var(--color-primary, #3366cc);
    }

    .progress-track {
        height: 12px;
        background: white;
        border-radius: 6px;
        overflow: hidden;
        border: 1px solid var(--color-border, #e2e8f0);
    }

    .progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #3366cc, #22c55e);
        border-radius: 6px;
        transition: width 0.5s ease;
    }

    .progress-stats {
        font-size: 12px;
        color: var(--color-text-muted, #94a3b8);
        margin-top: 4px;
    }

    /* 学习统计 */
    .learning-stats {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 16px;
        margin-bottom: 24px;
    }

    .stat-item {
        text-align: center;
        padding: 16px;
        background: white;
        border-radius: var(--radius-md, 10px);
        border: 1px solid var(--color-border, #e2e8f0);
    }

    .stat-value {
        font-size: 24px;
        font-weight: 700;
        color: var(--color-primary, #3366cc);
        margin-bottom: 4px;
    }

    .stat-label {
        font-size: 12px;
        color: var(--color-text-muted, #94a3b8);
    }

    /* 章节进度列表 */
    .section-progress-list {
        display: flex;
        flex-direction: column;
        gap: 12px;
    }

    .section-progress-item {
        padding: 12px;
        background: white;
        border-radius: var(--radius-sm, 6px);
        border: 1px solid var(--color-border, #e2e8f0);
    }

    .section-progress-item.completed {
        border-color: #22c55e;
        background: #dcfce7;
    }

    .section-progress-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 8px;
    }

    .section-icon {
        font-size: 20px;
    }

    .section-name {
        flex: 1;
        font-weight: 600;
        font-size: 14px;
        color: var(--color-text-primary, #0f172a);
    }

    .section-status {
        font-size: 12px;
        color: var(--color-text-muted, #94a3b8);
    }

    .section-progress-item.completed .section-status {
        color: #166534;
        font-weight: 600;
    }

    .section-progress-track {
        height: 6px;
        background: var(--color-surface, #f8fafc);
        border-radius: 3px;
        overflow: hidden;
    }

    .section-progress-fill {
        height: 100%;
        background: linear-gradient(90deg, #3366cc, #22c55e);
        border-radius: 3px;
        transition: width 0.3s ease;
    }

    /* 成就网格 */
    .achievements-grid {
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
        gap: 12px;
    }

    .achievement-card {
        padding: 16px;
        background: white;
        border-radius: var(--radius-sm, 6px);
        border: 1px solid var(--color-border, #e2e8f0);
        text-align: center;
        position: relative;
        transition: all 0.2s ease;
    }

    .achievement-card.locked {
        opacity: 0.5;
    }

    .achievement-card.unlocked {
        border-color: #f59e0b;
        background: linear-gradient(135deg, #fffbeb, #fef3c7);
    }

    .achievement-card:hover {
        transform: translateY(-2px);
        box-shadow: var(--shadow-sm, 0 1px 3px rgba(0, 0, 0, 0.08));
    }

    .achievement-icon {
        font-size: 32px;
        margin-bottom: 8px;
    }

    .achievement-name {
        font-size: 13px;
        font-weight: 600;
        color: var(--color-text-primary, #0f172a);
    }

    .achievement-badge {
        position: absolute;
        top: 8px;
        right: 8px;
        padding: 2px 6px;
        background: #f59e0b;
        color: white;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 600;
    }

    /* 成就通知 */
    .achievement-notification {
        position: fixed;
        top: 80px;
        right: 20px;
        z-index: 10002;
        opacity: 0;
        transform: translateX(100%);
        transition: all 0.3s ease;
    }

    .achievement-notification.show {
        opacity: 1;
        transform: translateX(0);
    }

    .achievement-content {
        background: linear-gradient(135deg, #fef3c7, #fde68a);
        border-radius: var(--radius-md, 10px);
        box-shadow: var(--shadow-lg, 0 8px 24px rgba(0, 0, 0, 0.12));
        padding: 16px 20px;
        min-width: 320px;
        display: flex;
        align-items: center;
        gap: 12px;
        position: relative;
        border: 2px solid #f59e0b;
    }

    .achievement-icon {
        font-size: 36px;
    }

    .achievement-text {
        flex: 1;
    }

    .achievement-title {
        font-size: 12px;
        color: #92400e;
        margin-bottom: 2px;
    }

    .achievement-name {
        font-size: 16px;
        font-weight: 700;
        color: #78350f;
        margin-bottom: 2px;
    }

    .achievement-desc {
        font-size: 12px;
        color: #92400e;
    }

    .achievement-close {
        width: 24px;
        height: 24px;
        border: none;
        background: rgba(120, 53, 15, 0.1);
        border-radius: 50%;
        cursor: pointer;
        font-size: 16px;
        color: #92400e;
    }

    .panel-section {
        margin-top: 24px;
    }

    .panel-section h4 {
        margin: 0 0 12px 0;
        font-size: 14px;
        color: var(--color-text-secondary, #475569);
    }

    /* 响应式 */
    @media (max-width: 768px) {
        .learning-stats {
            grid-template-columns: repeat(2, 1fr);
        }

        .achievements-grid {
            grid-template-columns: repeat(2, 1fr);
        }

        .achievement-notification {
            right: 10px;
            left: 10px;
        }

        .achievement-content {
            min-width: auto;
        }
    }
    `;
    document.head.appendChild(style);
})();
