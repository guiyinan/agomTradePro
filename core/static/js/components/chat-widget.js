/**
 * AgomChatWidget - Reusable AI Chat Widget Component
 *
 * Features:
 * - Multiple provider/model switching
 * - Session history
 * - Streaming responses (extensible)
 * - Embedded/Popup display modes
 * - Markdown/Mermaid rich rendering
 * - Answer Chain collapsible panels
 * - Suggestion action cards
 *
 * Usage:
 *   <div id="chat-container"></div>
 *   <script src="/static/js/shared/shared-chat-renderer.js"></script>
 *   <script>
 *     const chat = new AgomChatWidget({
 *       containerId: 'chat-container',
 *       title: 'AI Assistant',
 *       defaultProvider: 'openai',
 *       defaultModel: 'gpt-4',
 *       useSharedApi: true
 *     });
 *   </script>
 */

class AgomChatWidget {
    constructor(options = {}) {
        this.config = {
            containerId: options.containerId || 'chat-container',
            title: options.title || 'AI Assistant',
            placeholder: options.placeholder || 'Enter your question...',
            defaultProvider: options.defaultProvider || null,
            defaultModel: options.defaultModel || null,
            height: options.height || '500px',
            width: options.width || '100%',
            showHeader: options.showHeader !== false,
            showModelSelector: options.showModelSelector !== false,
            showProviderSelector: options.showProviderSelector !== false,
            enableHistory: options.enableHistory !== false,
            maxHistoryLength: options.maxHistoryLength || 50,
            apiBaseUrl: options.apiBaseUrl || '/api/prompt',
            useSharedApi: options.useSharedApi !== false,
            showAnswerChain: options.showAnswerChain !== false,
            showSuggestionCard: options.showSuggestionCard !== false,
            onMessageSent: options.onMessageSent || null,
            onMessageReceived: options.onMessageReceived || null,
            onError: options.onError || null,
            onSuggestionExecute: options.onSuggestionExecute || null,
        };

        this.state = {
            providers: [],
            models: [],
            currentProvider: this.config.defaultProvider,
            currentModel: this.config.defaultModel,
            sessionId: null,
            messages: [],
            isLoading: false,
        };

        this.container = null;
        this.elements = {};
        this.renderer = null;
        this.init();
    }

    async init() {
        this.container = document.getElementById(this.config.containerId);
        if (!this.container) {
            console.error(`Container "${this.config.containerId}" not found`);
            return;
        }

        this._initRenderer();
        this.render();
        await this.loadProviders();
        this.bindEvents();
    }

    _initRenderer() {
        if (window.AgomSharedChatRenderer) {
            this.renderer = new window.AgomSharedChatRenderer({
                cssPrefix: 'agom-chat',
                enableMermaid: true,
                enableAnswerChain: this.config.showAnswerChain,
                enableSuggestionCard: this.config.showSuggestionCard,
                onSuggestionExecute: (action, card) => {
                    this._executeSuggestedAction(action);
                },
                onSuggestionCancel: (action, card) => {
                    card.remove();
                },
            });
        } else {
            console.warn('AgomSharedChatRenderer not loaded, using basic rendering');
            this.renderer = null;
        }
    }

    render() {
        const html = `
            <div class="agom-chat-widget" style="width: ${this.config.width}; height: ${this.config.height};">
                ${this.config.showHeader ? this._renderHeader() : ''}
                <div class="agom-chat-messages" id="${this.config.containerId}-messages">
                    <div class="agom-chat-welcome">
                        <div class="welcome-icon">🤖</div>
                        <p>Hello! I'm ${this.config.title}. How can I help you?</p>
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

    _renderSelectors() {
        return `
            <div class="agom-chat-selectors">
                ${this.config.showProviderSelector ? `
                    <select class="agom-chat-selector" id="${this.config.containerId}-provider">
                        <option value="">Loading...</option>
                    </select>
                ` : ''}
                ${this.config.showModelSelector ? `
                    <select class="agom-chat-selector" id="${this.config.containerId}-model">
                        <option value="">Select provider first</option>
                    </select>
                ` : ''}
            </div>
        `;
    }

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

    bindEvents() {
        if (this.elements.sendBtn) {
            this.elements.sendBtn.addEventListener('click', () => this.sendMessage());
        }

        if (this.elements.input) {
            this.elements.input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });

            this.elements.input.addEventListener('input', () => {
                this._adjustTextareaHeight();
            });
        }

        if (this.elements.providerSelect) {
            this.elements.providerSelect.addEventListener('change', (e) => {
                this.state.currentProvider = e.target.value;
                this.loadModels(e.target.value);
            });
        }

        if (this.elements.modelSelect) {
            this.elements.modelSelect.addEventListener('change', (e) => {
                this.state.currentModel = e.target.value;
                this._updateHeaderInfo();
            });
        }
    }

    async loadProviders() {
        try {
            const response = await fetch(`${this.config.apiBaseUrl}/chat/providers`);
            const data = await response.json();

            this.state.providers = data.providers || [];

            if (this.elements.providerSelect) {
                if (this.state.providers.length === 0) {
                    this.elements.providerSelect.innerHTML = '<option value="">No providers available</option>';
                } else {
                    this.elements.providerSelect.innerHTML = this.state.providers.map(p =>
                        `<option value="${p.name}">${p.display_label}</option>`
                    ).join('');

                    if (!this.state.currentProvider && data.default_provider) {
                        this.state.currentProvider = data.default_provider;
                        this.elements.providerSelect.value = data.default_provider;
                    } else if (this.state.currentProvider) {
                        this.elements.providerSelect.value = this.state.currentProvider;
                    }

                    this.loadModels(this.state.currentProvider);
                }
            }
        } catch (error) {
            console.error('Failed to load providers:', error);
            this._showError('Failed to load provider list');
        }
    }

    async loadModels(providerName) {
        if (!providerName || !this.elements.modelSelect) return;

        try {
            const response = await fetch(`${this.config.apiBaseUrl}/chat/models?provider=${providerName}`);
            const data = await response.json();

            this.state.models = data.models || [];

            if (this.state.models.length === 0) {
                this.elements.modelSelect.innerHTML = '<option value="">No models available</option>';
            } else {
                this.elements.modelSelect.innerHTML = this.state.models.map(m =>
                    `<option value="${m}">${m}</option>`
                ).join('');

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

    async sendMessage() {
        if (this.state.isLoading) return;

        const message = this.elements.input.value.trim();
        if (!message) return;

        this._addUserMessage(message);
        this.elements.input.value = '';
        this._adjustTextareaHeight();

        this.state.isLoading = true;
        this._showTypingIndicator();

        const requestData = {
            message: message,
            session_id: this.state.sessionId,
            provider_name: this.state.currentProvider,
            model: this.state.currentModel,
            context: {
                history: this.state.messages
            }
        };

        if (this.config.onMessageSent) {
            this.config.onMessageSent(requestData);
        }

        const apiUrl = this.config.useSharedApi ? '/api/chat/web/' : `${this.config.apiBaseUrl}/chat`;

        try {
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCsrfToken()
                },
                body: JSON.stringify(requestData)
            });

            const data = await response.json();

            if (response.ok) {
                this.state.sessionId = data.session_id;

                if (this.renderer) {
                    await this._addAssistantMessageWithRenderer(data);
                } else {
                    this._addAssistantMessageBasic(data);
                }

                if (this.config.enableHistory) {
                    this.state.messages.push(
                        { role: 'user', content: message },
                        { role: 'assistant', content: data.reply }
                    );
                    if (this.state.messages.length > this.config.maxHistoryLength) {
                        this.state.messages = this.state.messages.slice(-this.config.maxHistoryLength);
                    }
                }

                if (this.config.onMessageReceived) {
                    this.config.onMessageReceived(data);
                }
            } else {
                this._showError(data.error || 'Failed to send message');
                if (this.config.onError) {
                    this.config.onError(data);
                }
            }
        } catch (error) {
            console.error('Failed to send message:', error);
            this._showError('Network error, please retry');
            if (this.config.onError) {
                this.config.onError(error);
            }
        } finally {
            this.state.isLoading = false;
            this._hideTypingIndicator();
        }
    }

    _addUserMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'agom-chat-message agom-chat-message-user';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'agom-chat-message-content';
        contentDiv.textContent = content;
        messageDiv.appendChild(contentDiv);

        this._removeWelcome();
        this.elements.messages.appendChild(messageDiv);
        this._scrollToBottom();
    }

    async _addAssistantMessageWithRenderer(data) {
        this._hideTypingIndicator();
        await this.renderer.renderAIMessage(
            this.elements.messages,
            data,
            () => this._scrollToBottom()
        );
    }

    _addAssistantMessageBasic(data) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'agom-chat-message agom-chat-message-assistant';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'agom-chat-message-content';
        contentDiv.innerHTML = this._escapeHtml(data.reply || '').replace(/\n/g, '<br>');
        messageDiv.appendChild(contentDiv);

        const metadata = data.metadata;
        if (metadata) {
            const metaDiv = document.createElement('div');
            metaDiv.className = 'agom-chat-message-metadata';
            const parts = [];
            if (metadata.provider) parts.push(metadata.provider);
            if (metadata.model) parts.push(metadata.model);
            if (metadata.tokens) parts.push(`${metadata.tokens} tokens`);
            metaDiv.innerHTML = `└─ ${parts.join(' | ')}`;
            messageDiv.appendChild(metaDiv);
        }

        this._removeWelcome();
        this.elements.messages.appendChild(messageDiv);
        this._scrollToBottom();
    }

    async _executeSuggestedAction(action) {
        if (this.config.onSuggestionExecute) {
            this.config.onSuggestionExecute(action);
            return;
        }

        this.state.isLoading = true;
        this._showTypingIndicator();

        try {
            const response = await fetch('/api/chat/web/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this._getCsrfToken()
                },
                body: JSON.stringify({
                    message: action.command || action.intent,
                    session_id: this.state.sessionId,
                    provider_name: this.state.currentProvider,
                    model: this.state.currentModel,
                    context: {
                        history: this.state.messages,
                        execute_action: action,
                    }
                })
            });

            const data = await response.json();

            if (response.ok) {
                this.state.sessionId = data.session_id;
                if (this.renderer) {
                    await this._addAssistantMessageWithRenderer(data);
                } else {
                    this._addAssistantMessageBasic(data);
                }
            } else {
                this._showError(data.error || 'Failed to execute action');
            }
        } catch (error) {
            console.error('Failed to execute action:', error);
            this._showError('Network error');
        } finally {
            this.state.isLoading = false;
            this._hideTypingIndicator();
        }
    }

    _removeWelcome() {
        const welcome = this.elements.messages.querySelector('.agom-chat-welcome');
        if (welcome) welcome.remove();
    }

    _showTypingIndicator() {
        if (this.renderer) {
            const indicator = this.renderer.createTypingIndicator();
            indicator.id = `${this.config.containerId}-typing`;
            this._removeWelcome();
            this.elements.messages.appendChild(indicator);
        } else {
            const indicator = document.createElement('div');
            indicator.className = 'agom-chat-message agom-chat-message-assistant agom-chat-typing';
            indicator.id = `${this.config.containerId}-typing`;
            indicator.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
            this._removeWelcome();
            this.elements.messages.appendChild(indicator);
        }
        this._scrollToBottom();
    }

    _hideTypingIndicator() {
        const indicator = document.getElementById(`${this.config.containerId}-typing`);
        if (indicator) indicator.remove();
    }

    _showError(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'agom-chat-error';
        errorDiv.textContent = message;
        this.elements.messages.appendChild(errorDiv);
        this._scrollToBottom();

        setTimeout(() => errorDiv.remove(), 5000);
    }

    _updateHeaderInfo() {
        if (!this.elements.headerInfo) return;

        const provider = this.state.providers.find(p => p.name === this.state.currentProvider);
        const model = this.state.currentModel;

        this.elements.headerInfo.textContent = provider && model
            ? `${provider.name} - ${model}`
            : '';
    }

    _adjustTextareaHeight() {
        const textarea = this.elements.input;
        textarea.style.height = 'auto';
        textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
    }

    _scrollToBottom() {
        this.elements.messages.scrollTop = this.elements.messages.scrollHeight;
    }

    _getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return decodeURIComponent(value);
        }
        return '';
    }

    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    clearHistory() {
        this.state.messages = [];
        this.state.sessionId = null;
        this.elements.messages.innerHTML = `
            <div class="agom-chat-welcome">
                <div class="welcome-icon">🤖</div>
                <p>Hello! I'm ${this.config.title}. How can I help you?</p>
            </div>
        `;
    }

    setSystemPrompt(prompt) {
        this.config.systemPrompt = prompt;
    }

    destroy() {
        if (this.container) {
            this.container.innerHTML = '';
        }
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AgomChatWidget;
} else {
    window.AgomChatWidget = AgomChatWidget;
}
