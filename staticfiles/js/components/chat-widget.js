/**
 * AgomChatWidget - 可复用的AI聊天窗口组件
 *
 * 支持功能：
 * - 多提供商/模型切换
 * - 会话历史记录
 * - 流式响应（可扩展）
 * - 嵌入式/弹窗式两种显示模式
 *
 * 使用方法：
 *   <div id="chat-container"></div>
 *   <script>
 *     const chat = new AgomChatWidget({
 *       containerId: 'chat-container',
 *       title: 'AI 助手',
 *       defaultProvider: 'openai',
 *       defaultModel: 'gpt-4'
 *     });
 *   </script>
 */

class AgomChatWidget {
    constructor(options = {}) {
        // 配置项
        this.config = {
            containerId: options.containerId || 'chat-container',
            title: options.title || 'AI 助手',
            placeholder: options.placeholder || '请输入您的问题...',
            defaultProvider: options.defaultProvider || null,
            defaultModel: options.defaultModel || null,
            height: options.height || '500px',
            width: options.width || '100%',
            showHeader: options.showHeader !== false,
            showModelSelector: options.showModelSelector !== false,
            showProviderSelector: options.showProviderSelector !== false,
            enableHistory: options.enableHistory !== false,
            maxHistoryLength: options.maxHistoryLength || 50,
            apiBaseUrl: options.apiBaseUrl || '/prompt/api',
            onMessageSent: options.onMessageSent || null,
            onMessageReceived: options.onMessageReceived || null,
            onError: options.onError || null,
        };

        // 内部状态
        this.state = {
            providers: [],
            models: [],
            currentProvider: this.config.defaultProvider,
            currentModel: this.config.defaultModel,
            sessionId: null,
            messages: [],
            isLoading: false,
        };

        // 初始化
        this.container = null;
        this.elements = {};
        this.init();
    }

    /**
     * 初始化组件
     */
    async init() {
        this.container = document.getElementById(this.config.containerId);
        if (!this.container) {
            console.error(`Container with id "${this.config.containerId}" not found`);
            return;
        }

        // 渲染组件结构
        this.render();

        // 加载提供商和模型列表
        await this.loadProviders();

        // 绑定事件
        this.bindEvents();
    }

    /**
     * 渲染组件HTML结构
     */
    render() {
        const html = `
            <div class="agom-chat-widget" style="width: ${this.config.width}; height: ${this.config.height};">
                ${this.config.showHeader ? this._renderHeader() : ''}
                <div class="agom-chat-messages" id="${this.config.containerId}-messages">
                    <div class="agom-chat-welcome">
                        <div class="welcome-icon">🤖</div>
                        <p>你好！我是${this.config.title}，有什么可以帮您的吗？</p>
                    </div>
                </div>
                <div class="agom-chat-input-area">
                    ${this.config.showProviderSelector || this.config.showModelSelector ? this._renderSelectors() : ''}
                    <div class="agom-chat-input-row">
                        <textarea
                            class="agom-chat-input"
                            id="${this.config.containerId}-input"
                            placeholder="${this.config.placeholder}"
                            rows="1"
                        ></textarea>
                        <button class="agom-chat-send-btn" id="${this.config.containerId}-send">
                            <span class="send-icon">➤</span>
                        </button>
                    </div>
                </div>
            </div>
        `;

        this.container.innerHTML = html;
        this._cacheElements();
    }

    /**
     * 渲染头部
     */
    _renderHeader() {
        return `
            <div class="agom-chat-header">
                <div class="header-title">
                    <span class="title-icon">💬</span>
                    <span class="title-text">${this.config.title}</span>
                </div>
                <div class="header-info" id="${this.config.containerId}-header-info"></div>
            </div>
        `;
    }

    /**
     * 渲染选择器（提供商/模型）
     */
    _renderSelectors() {
        return `
            <div class="agom-chat-selectors">
                ${this.config.showProviderSelector ? `
                    <select class="agom-chat-selector" id="${this.config.containerId}-provider">
                        <option value="">加载中...</option>
                    </select>
                ` : ''}
                ${this.config.showModelSelector ? `
                    <select class="agom-chat-selector" id="${this.config.containerId}-model">
                        <option value="">请先选择提供商</option>
                    </select>
                ` : ''}
            </div>
        `;
    }

    /**
     * 缓存DOM元素引用
     */
    _cacheElements() {
        const cid = this.config.containerId;
        this.elements = {
            widget: this.container.querySelector('.agom-chat-widget'),
            messages: document.getElementById(`${cid}-messages`),
            input: document.getElementById(`${cid}-input`),
            sendBtn: document.getElementById(`${cid}-send`),
            providerSelect: document.getElementById(`${cid}-provider`),
            modelSelect: document.getElementById(`${cid}-model`),
            headerInfo: document.getElementById(`${cid}-header-info`),
        };
    }

    /**
     * 绑定事件监听器
     */
    bindEvents() {
        // 发送按钮
        if (this.elements.sendBtn) {
            this.elements.sendBtn.addEventListener('click', () => this.sendMessage());
        }

        // 输入框回车发送
        if (this.elements.input) {
            this.elements.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });

            // 自动调整高度
            this.elements.input.addEventListener('input', () => {
                this._adjustTextareaHeight();
            });
        }

        // 提供商选择
        if (this.elements.providerSelect) {
            this.elements.providerSelect.addEventListener('change', (e) => {
                this.state.currentProvider = e.target.value;
                this.loadModels(e.target.value);
            });
        }

        // 模型选择
        if (this.elements.modelSelect) {
            this.elements.modelSelect.addEventListener('change', (e) => {
                this.state.currentModel = e.target.value;
                this._updateHeaderInfo();
            });
        }
    }

    /**
     * 加载提供商列表
     */
    async loadProviders() {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/chat/providers`);
            const data = await response.json();

            this.state.providers = data.providers || [];

            // 填充提供商选择器
            if (this.elements.providerSelect) {
                if (this.state.providers.length === 0) {
                    this.elements.providerSelect.innerHTML = '<option value="">暂无可用提供商</option>';
                } else {
                    this.elements.providerSelect.innerHTML = this.state.providers.map(p =>
                        `<option value="${p.name}">${p.display_label}</option>`
                    ).join('');

                    // 设置默认提供商
                    if (!this.state.currentProvider && data.default_provider) {
                        this.state.currentProvider = data.default_provider;
                        this.elements.providerSelect.value = data.default_provider;
                    } else if (this.state.currentProvider) {
                        this.elements.providerSelect.value = this.state.currentProvider;
                    }

                    // 加载模型列表
                    this.loadModels(this.state.currentProvider);
                }
            }
        } catch (error) {
            console.error('Failed to load providers:', error);
            this._showError('加载提供商列表失败');
        }
    }

    /**
     * 加载模型列表
     */
    async loadModels(providerName) {
        if (!providerName || !this.elements.modelSelect) return;

        try {
            const response = await fetch(`${this.config.apiBaseUrl}/chat/models?provider=${providerName}`);
            const data = await response.json();

            this.state.models = data.models || [];

            // 填充模型选择器
            if (this.state.models.length === 0) {
                this.elements.modelSelect.innerHTML = '<option value="">无可用模型</option>';
            } else {
                this.elements.modelSelect.innerHTML = this.state.models.map(m =>
                    `<option value="${m}">${m}</option>`
                ).join('');

                // 设置默认模型
                const provider = this.state.providers.find(p => p.name === providerName);
                const defaultModel = provider?.default_model;

                if (this.state.currentModel) {
                    this.elements.modelSelect.value = this.state.currentModel;
                } else if (defaultModel && this.state.models.includes(defaultModel)) {
                    this.state.currentModel = defaultModel;
                    this.elements.modelSelect.value = defaultModel;
                }
            }

            this._updateHeaderInfo();
        } catch (error) {
            console.error('Failed to load models:', error);
        }
    }

    /**
     * 发送消息
     */
    async sendMessage() {
        if (this.state.isLoading) return;

        const message = this.elements.input.value.trim();
        if (!message) return;

        // 添加用户消息到界面
        this._addMessage('user', message);
        this.elements.input.value = '';
        this._adjustTextareaHeight();

        // 显示加载状态
        this.state.isLoading = true;
        this._showTypingIndicator();

        // 构建请求
        const requestData = {
            message: message,
            session_id: this.state.sessionId,
            provider_name: this.state.currentProvider,
            model: this.state.currentModel,
            context: {
                history: this.state.messages
            }
        };

        // 回调
        if (this.config.onMessageSent) {
            this.config.onMessageSent(requestData);
        }

        try {
            const response = await fetch(`${this.config.apiBaseUrl}/chat`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCsrfToken()
                },
                body: JSON.stringify(requestData)
            });

            const data = await response.json();

            if (response.ok) {
                // 保存会话ID
                this.state.sessionId = data.session_id;

                // 添加AI回复到界面
                this._addMessage('assistant', data.reply, data.metadata);

                // 保存到历史
                if (this.config.enableHistory) {
                    this.state.messages.push(
                        { role: 'user', content: message },
                        { role: 'assistant', content: data.reply }
                    );
                    if (this.state.messages.length > this.config.maxHistoryLength) {
                        this.state.messages = this.state.messages.slice(-this.config.maxHistoryLength);
                    }
                }

                // 回调
                if (this.config.onMessageReceived) {
                    this.config.onMessageReceived(data);
                }
            } else {
                this._showError(data.error || '发送失败');
                if (this.config.onError) {
                    this.config.onError(data);
                }
            }
        } catch (error) {
            console.error('Failed to send message:', error);
            this._showError('网络错误，请重试');
            if (this.config.onError) {
                this.config.onError(error);
            }
        } finally {
            this.state.isLoading = false;
            this._hideTypingIndicator();
        }
    }

    /**
     * 添加消息到聊天区域
     */
    _addMessage(role, content, metadata = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `agom-chat-message agom-chat-message-${role}`;

        let metaHtml = '';
        if (metadata) {
            metaHtml = `
                <div class="message-metadata">
                    <span class="metadata-provider">${metadata.provider || ''}</span>
                    <span class="metadata-model">${metadata.model || ''}</span>
                    ${metadata.tokens ? `<span class="metadata-tokens">${metadata.tokens} tokens</span>` : ''}
                </div>
            `;
        }

        messageDiv.innerHTML = `
            <div class="message-content">${this._escapeHtml(content)}</div>
            ${metaHtml}
        `;

        // 移除欢迎消息
        const welcome = this.elements.messages.querySelector('.agom-chat-welcome');
        if (welcome) welcome.remove();

        this.elements.messages.appendChild(messageDiv);
        this._scrollToBottom();
    }

    /**
     * 显示输入指示器
     */
    _showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'agom-chat-message agom-chat-message-assistant agom-chat-typing';
        indicator.id = `${this.config.containerId}-typing`;
        indicator.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
        this.elements.messages.appendChild(indicator);
        this._scrollToBottom();
    }

    /**
     * 隐藏输入指示器
     */
    _hideTypingIndicator() {
        const indicator = document.getElementById(`${this.config.containerId}-typing`);
        if (indicator) indicator.remove();
    }

    /**
     * 显示错误消息
     */
    _showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'agom-chat-error';
        errorDiv.textContent = message;
        this.elements.messages.appendChild(errorDiv);
        this._scrollToBottom();

        setTimeout(() => errorDiv.remove(), 5000);
    }

    /**
     * 更新头部信息
     */
    _updateHeaderInfo() {
        if (!this.elements.headerInfo) return;

        const provider = this.state.providers.find(p => p.name === this.state.currentProvider);
        const model = this.state.currentModel;

        this.elements.headerInfo.textContent = provider && model
            ? `${provider.name} - ${model}`
            : '';
    }

    /**
     * 自动调整文本框高度
     */
    _adjustTextareaHeight() {
        const textarea = this.elements.input;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }

    /**
     * 滚动到底部
     */
    _scrollToBottom() {
        this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
    }

    /**
     * 获取CSRF Token
     */
    _getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return decodeURIComponent(value);
        }
        return '';
    }

    /**
     * HTML转义
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * 清空聊天历史
     */
    clearHistory() {
        this.state.messages = [];
        this.state.sessionId = null;
        this.elements.messages.innerHTML = `
            <div class="agom-chat-welcome">
                <div class="welcome-icon">🤖</div>
                <p>你好！我是${this.config.title}，有什么可以帮您的吗？</p>
            </div>
        `;
    }

    /**
     * 设置系统提示词（用于扩展功能）
     */
    setSystemPrompt(prompt) {
        this.config.systemPrompt = prompt;
    }

    /**
     * 销毁组件
     */
    destroy() {
        if (this.container) {
            this.container.innerHTML = '';
        }
    }
}

// 导出供全局使用
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AgomChatWidget;
}
