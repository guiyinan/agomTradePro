/**
 * AgomSharedChatRenderer - Shared chat rendering utilities
 *
 * Provides reusable rendering functions for AI chat interfaces:
 * - Markdown rendering (with fallback)
 * - Mermaid diagram rendering
 * - Answer chain collapsible panels
 * - Metadata display
 * - Suggestion action cards
 *
 * This module is framework-agnostic and can be used by:
 * - Homepage chat
 * - AgomChatWidget
 * - Terminal (optional refactoring)
 *
 * Usage:
 *   const renderer = new AgomSharedChatRenderer(options);
 *   const container = document.getElementById('messages');
 *   renderer.renderAIMessage(container, response);
 */

class AgomSharedChatRenderer {
    constructor(options = {}) {
        this.options = {
            cssPrefix: options.cssPrefix || 'agom-chat',
            enableMermaid: options.enableMermaid !== false,
            enableAnswerChain: options.enableAnswerChain !== false,
            enableSuggestionCard: options.enableSuggestionCard !== false,
            onSuggestionExecute: options.onSuggestionExecute || null,
            onSuggestionCancel: options.onSuggestionCancel || null,
            ...options,
        };
        this.initializeRichTextLibraries();
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    formatMarkdown(text) {
        const source = this.escapeHtml(text || '');

        if (window.marked?.parse) {
            try {
                return window.marked.parse(source);
            } catch (e) {
                console.warn('Markdown parse error:', e);
            }
        }

        let formatted = source;
        formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            const className = lang ? ` class="language-${lang}"` : '';
            return `<pre class="${this.options.cssPrefix}-code-block"><code${className}>${code}</code></pre>`;
        });
        formatted = formatted.replace(/`([^`]+)`/g, `<code class="${this.options.cssPrefix}-inline-code">$1</code>`);
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        formatted = formatted.replace(/\n/g, '<br>');
        return formatted;
    }

    initializeRichTextLibraries() {
        if (window.marked?.setOptions) {
            window.marked.setOptions({
                gfm: true,
                breaks: true,
            });
        }

        if (window.mermaid?.initialize) {
            window.mermaid.initialize({
                startOnLoad: false,
                securityLevel: 'strict',
                theme: 'default',
            });
        }
    }

    async renderRichContent(container) {
        container.querySelectorAll('pre').forEach((pre) => {
            pre.classList.add(`${this.options.cssPrefix}-code-block`);
        });
        container.querySelectorAll(':not(pre) > code').forEach((code) => {
            code.classList.add(`${this.options.cssPrefix}-inline-code`);
        });

        if (!this.options.enableMermaid || !window.mermaid?.render) {
            return;
        }

        const mermaidBlocks = container.querySelectorAll('pre code.language-mermaid');
        for (const block of mermaidBlocks) {
            const pre = block.closest('pre');
            if (!pre) continue;

            const source = block.textContent || '';
            const wrapper = document.createElement('div');
            wrapper.className = `${this.options.cssPrefix}-mermaid-wrap`;
            wrapper.innerHTML = `
                <div class="${this.options.cssPrefix}-mermaid-label">Mermaid</div>
                <div class="${this.options.cssPrefix}-mermaid-diagram"></div>
            `;

            pre.replaceWith(wrapper);

            try {
                const id = `${this.options.cssPrefix}-mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
                const result = await window.mermaid.render(id, source);
                wrapper.querySelector(`.${this.options.cssPrefix}-mermaid-diagram`).innerHTML = result.svg;
            } catch (error) {
                wrapper.innerHTML = `
                    <div class="${this.options.cssPrefix}-mermaid-label">Mermaid</div>
                    <pre class="${this.options.cssPrefix}-code-block"><code class="language-mermaid">${this.escapeHtml(source)}</code></pre>
                    <div class="${this.options.cssPrefix}-mermaid-error">Diagram render failed: ${this.escapeHtml(error?.message || 'unknown error')}</div>
                `;
            }
        }
    }

    renderAnswerChain(answerChain) {
        if (!this.options.enableAnswerChain) return null;
        if (!answerChain || !Array.isArray(answerChain.steps) || answerChain.steps.length === 0) {
            return null;
        }

        const wrapper = document.createElement('div');
        wrapper.className = `${this.options.cssPrefix}-answer-chain`;

        const toggle = document.createElement('button');
        toggle.type = 'button';
        toggle.className = `${this.options.cssPrefix}-answer-chain-toggle`;
        toggle.textContent = answerChain.label || 'View answer chain';
        toggle.setAttribute('aria-expanded', 'false');

        const panel = document.createElement('div');
        panel.className = `${this.options.cssPrefix}-answer-chain-panel`;
        panel.hidden = true;

        const steps = answerChain.steps.map((step, index) => {
            const details = Array.isArray(step.technical_details) && step.technical_details.length > 0
                ? `<div class="${this.options.cssPrefix}-answer-chain-tech">${step.technical_details.map((item) => `<code>${this.escapeHtml(item)}</code>`).join('')}</div>`
                : '';
            return `
                <div class="${this.options.cssPrefix}-answer-chain-step">
                    <div class="${this.options.cssPrefix}-answer-chain-stepno">${index + 1}</div>
                    <div class="${this.options.cssPrefix}-answer-chain-stepbody">
                        <div class="${this.options.cssPrefix}-answer-chain-title">${this.escapeHtml(step.title || 'Step')}</div>
                        <div class="${this.options.cssPrefix}-answer-chain-summary">${this.escapeHtml(step.summary || '')}</div>
                        <div class="${this.options.cssPrefix}-answer-chain-source">${this.escapeHtml(step.source || '')}</div>
                        ${details}
                    </div>
                </div>
            `;
        }).join('');

        panel.innerHTML = steps;
        toggle.addEventListener('click', () => {
            panel.hidden = !panel.hidden;
            toggle.classList.toggle('expanded', !panel.hidden);
            toggle.setAttribute('aria-expanded', panel.hidden ? 'false' : 'true');
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(panel);
        return wrapper;
    }

    renderMetadata(metadata) {
        if (!metadata) return null;

        const meta = document.createElement('div');
        meta.className = `${this.options.cssPrefix}-message-metadata`;
        
        const parts = [];
        if (metadata.provider) parts.push(metadata.provider);
        if (metadata.model) parts.push(metadata.model);
        if (metadata.tokens) parts.push(`${metadata.tokens} tokens`);
        
        meta.innerHTML = `└─ ${parts.join(' | ')}`;
        return meta;
    }

    renderSuggestionCard(suggestedAction) {
        if (!this.options.enableSuggestionCard || !suggestedAction) return null;

        const card = document.createElement('div');
        card.className = `${this.options.cssPrefix}-suggestion-card`;
        card.dataset.capabilityKey = suggestedAction.capability_key || '';
        card.dataset.intent = suggestedAction.intent || '';
        card.dataset.command = suggestedAction.command || '';

        card.innerHTML = `
            <div class="${this.options.cssPrefix}-suggestion-header">
                <span class="${this.options.cssPrefix}-suggestion-icon">💡</span>
                <span class="${this.options.cssPrefix}-suggestion-label">${this.escapeHtml(suggestedAction.label || 'Suggested Action')}</span>
            </div>
            <div class="${this.options.cssPrefix}-suggestion-desc">${this.escapeHtml(suggestedAction.description || '')}</div>
            <div class="${this.options.cssPrefix}-suggestion-command">
                <code>${this.escapeHtml(suggestedAction.command || '')}</code>
            </div>
            <div class="${this.options.cssPrefix}-suggestion-actions">
                <button type="button" class="${this.options.cssPrefix}-suggestion-btn ${this.options.cssPrefix}-suggestion-execute">
                    Execute
                </button>
                <button type="button" class="${this.options.cssPrefix}-suggestion-btn ${this.options.cssPrefix}-suggestion-cancel">
                    Cancel
                </button>
            </div>
        `;

        const executeBtn = card.querySelector(`.${this.options.cssPrefix}-suggestion-execute`);
        const cancelBtn = card.querySelector(`.${this.options.cssPrefix}-suggestion-cancel`);

        executeBtn.addEventListener('click', () => {
            if (this.options.onSuggestionExecute) {
                this.options.onSuggestionExecute(suggestedAction, card);
            }
        });

        cancelBtn.addEventListener('click', () => {
            if (this.options.onSuggestionCancel) {
                this.options.onSuggestionCancel(suggestedAction, card);
            }
            card.remove();
        });

        return card;
    }

    createTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = `${this.options.cssPrefix}-typing`;
        indicator.innerHTML = `
            <span class="${this.options.cssPrefix}-typing-dot"></span>
            <span class="${this.options.cssPrefix}-typing-dot"></span>
            <span class="${this.options.cssPrefix}-typing-dot"></span>
        `;
        return indicator;
    }

    async renderAIMessage(container, response, scrollToBottom = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `${this.options.cssPrefix}-message ${this.options.cssPrefix}-message-assistant`;

        const contentDiv = document.createElement('div');
        contentDiv.className = `${this.options.cssPrefix}-message-content`;
        contentDiv.innerHTML = this.formatMarkdown(response.reply || '');
        messageDiv.appendChild(contentDiv);

        const metadata = response.metadata || {};
        const metaEl = this.renderMetadata(metadata);
        if (metaEl) {
            messageDiv.appendChild(metaEl);
        }

        if (metadata.answer_chain) {
            const chainEl = this.renderAnswerChain(metadata.answer_chain);
            if (chainEl) {
                messageDiv.appendChild(chainEl);
            }
        }

        if (response.route_confirmation_required && response.suggested_action) {
            const cardEl = this.renderSuggestionCard(response.suggested_action);
            if (cardEl) {
                messageDiv.appendChild(cardEl);
            }
        }

        container.appendChild(messageDiv);

        await this.renderRichContent(contentDiv);

        if (scrollToBottom) {
            scrollToBottom();
        } else if (container.scrollTop !== undefined) {
            container.scrollTop = container.scrollHeight;
        }

        return messageDiv;
    }

    renderUserMessage(container, message, scrollToBottom = null) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `${this.options.cssPrefix}-message ${this.options.cssPrefix}-message-user`;
        
        const contentDiv = document.createElement('div');
        contentDiv.className = `${this.options.cssPrefix}-message-content`;
        contentDiv.textContent = message;
        messageDiv.appendChild(contentDiv);

        container.appendChild(messageDiv);

        if (scrollToBottom) {
            scrollToBottom();
        } else if (container.scrollTop !== undefined) {
            container.scrollTop = container.scrollHeight;
        }

        return messageDiv;
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AgomSharedChatRenderer;
}

window.AgomSharedChatRenderer = AgomSharedChatRenderer;
