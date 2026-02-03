/**
 * AgomSAAF Floating Widget System
 * 浮动小组件系统 - 提供页面级别的功能介绍和计算逻辑说明
 *
 * @class AgomFloatingWidget
 * @example
 * const widget = new AgomFloatingWidget({
 *     widgetId: 'regime-dashboard',
 *     position: 'bottom-right',
 *     icon: '📊',
 *     title: 'Regime 判定指南',
 *     content: { ... }
 * });
 */

class AgomFloatingWidget {
    /**
     * Create a new floating widget instance
     * @param {Object} options - Widget configuration
     * @param {string} options.widgetId - Unique widget identifier
     * @param {string} [options.position='bottom-right'] - Position: bottom-right, bottom-left, top-right, top-left
     * @param {string} [options.icon='💡'] - Icon emoji for collapsed state
     * @param {string} [options.title='帮助'] - Widget title
     * @param {Object} [options.content=null] - Content configuration object
     * @param {string} [options.width='400px'] - Widget width when expanded
     * @param {string} [options.maxHeight='600px'] - Max height when expanded
     * @param {string} [options.defaultState='collapsed'] - Default state: collapsed or expanded
     * @param {boolean} [options.persistState=true] - Whether to remember state in localStorage
     */
    constructor(options = {}) {
        this.config = {
            widgetId: options.widgetId || 'floating-widget-' + Date.now(),
            position: options.position || 'bottom-right',
            icon: options.icon || '💡',
            title: options.title || '帮助',
            content: options.content || null,
            width: options.width || '400px',
            maxHeight: options.maxHeight || '600px',
            defaultState: options.defaultState || 'collapsed',
            persistState: options.persistState !== false,
            ...options
        };

        this.isExpanded = false;
        this.element = null;
        this.init();
    }

    /**
     * Initialize the widget
     * @private
     */
    init() {
        // Load saved state if persistence is enabled
        if (this.config.persistState) {
            const savedState = this.loadState();
            if (savedState === 'expanded') {
                this.config.defaultState = 'expanded';
            }
        }

        // Create widget DOM
        this.createWidget();

        // Set initial state
        if (this.config.defaultState === 'expanded') {
            this.open(false); // false = don't save state on init
        }

        // Bind event listeners
        this.bindEvents();

        console.log(`[FloatingWidget] Widget "${this.config.widgetId}" initialized`);
    }

    /**
     * Create the widget DOM structure
     * @private
     */
    createWidget() {
        // Create container
        const container = document.createElement('div');
        container.className = `floating-widget position-${this.config.position}`;
        container.id = this.config.widgetId;
        container.setAttribute('role', 'complementary');
        container.setAttribute('aria-label', this.config.title);

        // Create toggle button
        const toggleBtn = document.createElement('button');
        toggleBtn.className = 'widget-toggle';
        toggleBtn.setAttribute('aria-label', this.config.title);
        toggleBtn.setAttribute('aria-expanded', 'false');
        toggleBtn.innerHTML = `
            <span class="default-icon widget-icon">${this.config.icon}</span>
            <span class="close-icon widget-icon">✕</span>
        `;

        // Create content panel
        const contentPanel = document.createElement('div');
        contentPanel.className = 'widget-content';
        contentPanel.style.width = this.config.width;
        contentPanel.style.maxHeight = this.config.maxHeight;

        // Render content if provided
        if (this.config.content) {
            this.renderContent(contentPanel);
        }

        // Assemble widget
        container.appendChild(toggleBtn);
        container.appendChild(contentPanel);

        // Add to DOM
        document.body.appendChild(container);

        this.element = container;
    }

    /**
     * Render widget content from configuration
     * @private
     * @param {HTMLElement} contentPanel - The content panel element
     */
    renderContent(contentPanel) {
        const content = this.config.content;

        // Header
        const header = document.createElement('div');
        header.className = 'widget-header';
        header.innerHTML = `
            <div class="widget-title">
                <span class="widget-title-icon">${this.config.icon}</span>
                <span>${this.config.title}</span>
            </div>
            <div class="widget-actions">
                <button class="widget-action-btn" data-action="minimize" aria-label="最小化">−</button>
            </div>
        `;

        // Body
        const body = document.createElement('div');
        body.className = 'widget-body';

        if (content.sections && content.sections.length > 0) {
            content.sections.forEach(section => {
                const sectionEl = this.renderSection(section);
                body.appendChild(sectionEl);
            });
        } else if (content.html) {
            body.innerHTML = content.html;
        } else {
            body.innerHTML = '<p style="color: var(--color-text-muted);">暂无内容</p>';
        }

        // Footer (actions)
        const footer = document.createElement('div');
        footer.className = 'widget-footer';
        if (content.actions && content.actions.length > 0) {
            const actionsList = document.createElement('div');
            actionsList.className = 'widget-actions-list';
            content.actions.forEach(action => {
                const actionLink = document.createElement('a');
                actionLink.className = 'widget-action-link';
                actionLink.href = 'javascript:void(0)';
                actionLink.innerHTML = action.icon ? `${action.icon} ${action.label}` : action.label;
                actionLink.addEventListener('click', () => {
                    if (action.action && typeof window[action.action] === 'function') {
                        window[action.action]();
                    } else if (action.url) {
                        window.location.href = action.url;
                    } else if (action.onclick) {
                        action.onclick();
                    }
                });
                actionsList.appendChild(actionLink);
            });
            footer.appendChild(actionsList);
        }

        contentPanel.appendChild(header);
        contentPanel.appendChild(body);
        contentPanel.appendChild(footer);
    }

    /**
     * Render a single section
     * @private
     * @param {Object} section - Section configuration
     * @returns {HTMLElement}
     */
    renderSection(section) {
        const sectionEl = document.createElement('div');
        sectionEl.className = 'widget-section';

        const title = document.createElement('div');
        title.className = 'section-title';
        title.textContent = section.title;
        sectionEl.appendChild(title);

        if (section.type === 'accordion' && section.items) {
            // Render as accordion
            const accordion = document.createElement('div');
            accordion.className = 'widget-accordion accordion';

            section.items.forEach((item, index) => {
                const accordionItem = document.createElement('div');
                accordionItem.className = 'accordion-item';

                const header = document.createElement('button');
                header.className = 'accordion-header';
                header.innerHTML = `
                    <span class="accordion-title">${item.title}</span>
                    <span class="accordion-icon">▼</span>
                `;
                header.addEventListener('click', () => this.toggleAccordion(accordionItem));

                const content = document.createElement('div');
                content.className = 'accordion-content';
                const body = document.createElement('div');
                body.className = 'accordion-body';
                body.innerHTML = item.content;
                content.appendChild(body);

                accordionItem.appendChild(header);
                accordionItem.appendChild(content);
                accordion.appendChild(accordionItem);
            });

            sectionEl.appendChild(accordion);
        } else {
            // Render as regular content
            const content = document.createElement('div');
            content.className = 'section-content';
            content.innerHTML = section.content || '';
            sectionEl.appendChild(content);
        }

        return sectionEl;
    }

    /**
     * Toggle accordion item
     * @private
     * @param {HTMLElement} item - The accordion item element
     */
    toggleAccordion(item) {
        const isOpen = item.classList.contains('open');

        // Close all other accordions in the same widget (optional)
        const accordion = item.closest('.accordion');
        if (accordion) {
            const siblings = accordion.querySelectorAll('.accordion-item.open');
            siblings.forEach(sibling => {
                if (sibling !== item) {
                    sibling.classList.remove('open');
                }
            });
        }

        // Toggle current item
        item.classList.toggle('open', !isOpen);
    }

    /**
     * Bind event listeners
     * @private
     */
    bindEvents() {
        // Toggle button click
        const toggleBtn = this.element.querySelector('.widget-toggle');
        toggleBtn.addEventListener('click', () => this.toggle());

        // Minimize button click
        const minimizeBtn = this.element.querySelector('[data-action="minimize"]');
        if (minimizeBtn) {
            minimizeBtn.addEventListener('click', () => this.close());
        }

        // ESC key to close
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isExpanded) {
                this.close();
            }
        });

        // Click outside to close
        document.addEventListener('click', (e) => {
            if (this.isExpanded && !this.element.contains(e.target)) {
                this.close();
            }
        });
    }

    /**
     * Open (expand) the widget
     * @param {boolean} [saveState=true] - Whether to save the state
     */
    open(saveState = true) {
        if (this.isExpanded) return;

        this.isExpanded = true;
        this.element.classList.add('expanded');

        // Update ARIA attribute
        const toggleBtn = this.element.querySelector('.widget-toggle');
        if (toggleBtn) {
            toggleBtn.setAttribute('aria-expanded', 'true');
        }

        // Prevent body scroll when widget is expanded on mobile
        if (window.innerWidth <= 768) {
            document.body.style.overflow = 'hidden';
        }

        // Save state if enabled
        if (saveState && this.config.persistState) {
            this.saveState('expanded');
        }

        // Dispatch custom event
        this.element.dispatchEvent(new CustomEvent('widget:opened', {
            detail: { widgetId: this.config.widgetId }
        }));
    }

    /**
     * Close (collapse) the widget
     * @param {boolean} [saveState=true] - Whether to save the state
     */
    close(saveState = true) {
        if (!this.isExpanded) return;

        this.isExpanded = false;
        this.element.classList.remove('expanded');

        // Update ARIA attribute
        const toggleBtn = this.element.querySelector('.widget-toggle');
        if (toggleBtn) {
            toggleBtn.setAttribute('aria-expanded', 'false');
        }

        // Restore body scroll
        document.body.style.overflow = '';

        // Save state if enabled
        if (saveState && this.config.persistState) {
            this.saveState('collapsed');
        }

        // Dispatch custom event
        this.element.dispatchEvent(new CustomEvent('widget:closed', {
            detail: { widgetId: this.config.widgetId }
        }));
    }

    /**
     * Toggle widget open/close state
     */
    toggle() {
        if (this.isExpanded) {
            this.close();
        } else {
            this.open();
        }
    }

    /**
     * Save widget state to localStorage
     * @private
     * @param {string} state - 'expanded' or 'collapsed'
     */
    saveState(state) {
        try {
            const key = `floating-widget-state-${this.config.widgetId}`;
            localStorage.setItem(key, state);
        } catch (e) {
            console.warn('[FloatingWidget] Failed to save state:', e);
        }
    }

    /**
     * Load widget state from localStorage
     * @private
     * @returns {string|null} - 'expanded', 'collapsed', or null
     */
    loadState() {
        try {
            const key = `floating-widget-state-${this.config.widgetId}`;
            return localStorage.getItem(key);
        } catch (e) {
            console.warn('[FloatingWidget] Failed to load state:', e);
            return null;
        }
    }

    /**
     * Clear saved state from localStorage
     */
    clearState() {
        try {
            const key = `floating-widget-state-${this.config.widgetId}`;
            localStorage.removeItem(key);
        } catch (e) {
            console.warn('[FloatingWidget] Failed to clear state:', e);
        }
    }

    /**
     * Update widget content
     * @param {Object} content - New content configuration
     */
    updateContent(content) {
        this.config.content = content;
        const contentPanel = this.element.querySelector('.widget-content');
        if (contentPanel) {
            contentPanel.innerHTML = '';
            this.renderContent(contentPanel);
        }
    }

    /**
     * Destroy the widget and clean up
     */
    destroy() {
        if (this.element) {
            this.element.remove();
        }
        this.clearState();
        this.isExpanded = false;
        console.log(`[FloatingWidget] Widget "${this.config.widgetId}" destroyed`);
    }
}

// ========================================
// Global Widget Registry
// ========================================

/**
 * Global registry for all floating widgets
 * @private
 */
const _widgetRegistry = new Map();

/**
 * Initialize a floating widget from configuration
 * @param {Object} config - Widget configuration
 * @returns {AgomFloatingWidget} - The widget instance
 */
function initFloatingWidget(config) {
    // Destroy existing widget with same ID if exists
    if (_widgetRegistry.has(config.widgetId)) {
        _widgetRegistry.get(config.widgetId).destroy();
    }

    // Create new widget
    const widget = new AgomFloatingWidget(config);
    _widgetRegistry.set(config.widgetId, widget);

    return widget;
}

/**
 * Get a widget instance by ID
 * @param {string} widgetId - Widget identifier
 * @returns {AgomFloatingWidget|undefined}
 */
function getFloatingWidget(widgetId) {
    return _widgetRegistry.get(widgetId);
}

/**
 * Destroy a widget by ID
 * @param {string} widgetId - Widget identifier
 */
function destroyFloatingWidget(widgetId) {
    if (_widgetRegistry.has(widgetId)) {
        _widgetRegistry.get(widgetId).destroy();
        _widgetRegistry.delete(widgetId);
    }
}

/**
 * Destroy all widgets
 */
function destroyAllFloatingWidgets() {
    _widgetRegistry.forEach(widget => widget.destroy());
    _widgetRegistry.clear();
}

// ========================================
// Auto-initialization from window.floatingWidgetConfig
// ========================================

/**
 * Auto-initialize widget when DOM is ready
 * @private
 */
function _autoInitWidgets() {
    if (window.floatingWidgetConfig) {
        const widget = initFloatingWidget(window.floatingWidgetConfig);
        console.log('[FloatingWidget] Auto-initialized widget:', widget.config.widgetId);
    }
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _autoInitWidgets);
} else {
    _autoInitWidgets();
}

// ========================================
// Export to global scope
// ========================================

window.AgomFloatingWidget = AgomFloatingWidget;
window.initFloatingWidget = initFloatingWidget;
window.getFloatingWidget = getFloatingWidget;
window.destroyFloatingWidget = destroyFloatingWidget;
window.destroyAllFloatingWidgets = destroyAllFloatingWidgets;

// Export for ES6 modules (if used in module context)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        AgomFloatingWidget,
        initFloatingWidget,
        getFloatingWidget,
        destroyFloatingWidget,
        destroyAllFloatingWidgets
    };
}
