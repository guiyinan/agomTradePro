/**
 * AgomSAAF Terminal - CLI Interface Controller
 * 
 * A bash-style terminal interface for AI chat and system commands.
 * Supports command history, auto-completion, interactive parameters, and real-time AI responses.
 */

class AgomTerminal {
    constructor() {
        // State
        this.commandHistory = [];
        this.historyIndex = -1;
        this.providers = [];
        this.models = [];
        this.currentProvider = null;
        this.currentModel = null;
        this.sessionId = null;
        this.messageCount = 0;
        this.tokenCount = 0;
        this.isLoading = false;
        this.maxInputChars = 12000;
        this.largePasteThreshold = 1200;
        
        // Save original prompt (username@agomSAAF:~$)
        this.originalPrompt = document.getElementById('terminal-prompt')?.textContent || 'guest@agomSAAF:~$';
        
        // Dynamic commands (loaded from backend)
        this.dynamicCommands = {};
        this.commandCategories = [];

        // DOM Elements
        this.elements = {
            input: document.getElementById('terminal-input'),
            output: document.getElementById('terminal-output'),
            body: document.getElementById('terminal-body'),
            providerSelect: document.getElementById('provider-select'),
            modelSelect: document.getElementById('model-select'),
            providerBadge: document.getElementById('terminal-provider'),
            modelBadge: document.getElementById('terminal-model'),
            sessionId: document.getElementById('session-id'),
            messageCount: document.getElementById('message-count'),
            tokenCount: document.getElementById('token-count'),
            sidebar: document.getElementById('terminal-sidebar'),
            sidebarToggle: document.getElementById('sidebar-toggle'),
            inputStatus: document.getElementById('terminal-input-status'),
            inputCount: document.getElementById('terminal-input-count'),
        };

        // Built-in commands (always available)
        this.builtinCommands = {
            'help': this.cmdHelp.bind(this),
            'clear': this.cmdClear.bind(this),
            'history': this.cmdHistory.bind(this),
            'status': this.cmdStatus.bind(this),
            'regime': this.cmdRegime.bind(this),
            'version': this.cmdVersion.bind(this),
            'export': this.cmdExport.bind(this),
            'commands': this.cmdListCommands.bind(this),
        };

        // Interactive parameter collection state
        this.pendingCommand = null;
        this.pendingParams = {};
        this.paramIndex = 0;

        // Governance state
        this.terminalMode = 'confirm_each';
        this.terminalState = 'normal'; // normal | pending_params | pending_confirmation | pending_route_confirmation
        this.pendingConfirmation = null; // {name, params, token, details}
        this.pendingRouteSuggestion = null; // {command, intent, prompt}
        this.userCapabilities = null;

        // Initialize
        this.init();
    }

    /**
     * Initialize the terminal
     */
    async init() {
        this.bindEvents();
        this.initializeRichTextRenderer();
        await Promise.all([
            this.loadProviders(),
            this.loadDynamicCommands(),
            this.loadCapabilities(),
        ]);
        this.updateSessionInfo();
        this.autoResizeInput();
        this.updateInputState();
        this.focusInput();

        console.log('AgomSAAF Terminal initialized. Type "/help" for commands.');
    }

    /**
     * Load dynamic commands from backend
     */
    async loadDynamicCommands() {
        try {
            const response = await fetch('/api/terminal/commands/available/');
            const data = await response.json();
            
            if (data.success && data.commands) {
                this.dynamicCommands = {};
                data.commands.forEach(cmd => {
                    this.dynamicCommands[cmd.name] = cmd;
                });
                this.commandCategories = data.categories || [];
                
                // Update sidebar with dynamic commands
                this.updateSidebarCommands();
            }
        } catch (error) {
            console.error('Failed to load dynamic commands:', error);
        }
    }

    /**
     * Update sidebar with dynamic commands
     */
    updateSidebarCommands() {
        const quickCommands = document.querySelector('.quick-commands');
        if (!quickCommands) return;

        // Keep existing quick-cmd-btn elements but add dynamic ones
        const existingBtns = quickCommands.querySelectorAll('.quick-cmd-btn');
        const existingCmds = new Set(Array.from(existingBtns).map(b => b.dataset.cmd));

        // Add new dynamic commands
        Object.entries(this.dynamicCommands).forEach(([name, cmd]) => {
            if (!existingCmds.has(name)) {
                const btn = document.createElement('button');
                btn.className = 'quick-cmd-btn';
                btn.dataset.cmd = name;
                
                const iconMap = {
                    'prompt': '🤖',
                    'api': '📡',
                    'builtin': '⚡'
                };

                const riskBadge = cmd.risk_level && cmd.risk_level !== 'read'
                    ? `<span class="risk-badge risk-${cmd.risk_level}" style="font-size:9px;margin-left:4px;padding:1px 4px;border-radius:3px;background:${cmd.risk_level === 'admin' ? '#dc3545' : cmd.risk_level === 'write_high' ? '#fd7e14' : '#ffc107'};color:#000;">${cmd.risk_level}</span>`
                    : '';

                btn.innerHTML = `
                    <span class="quick-cmd-icon">${iconMap[cmd.type] || '▶'}</span>
                    <span>${cmd.display_name || name}${riskBadge}</span>
                `;
                
                btn.addEventListener('click', () => {
                    this.executeCommand(name);
                });
                
                quickCommands.appendChild(btn);
            }
        });
    }

    /**
     * Bind event listeners
     */
    bindEvents() {
        // Main input handling
        this.elements.input.addEventListener('keydown', (e) => this.handleKeyDown(e));
        this.elements.input.addEventListener('input', () => {
            this.autoResizeInput();
            this.updateInputState();
        });
        this.elements.input.addEventListener('paste', (e) => this.handlePaste(e));

        // Provider/Model selection
        this.elements.providerSelect.addEventListener('change', (e) => this.onProviderChange(e));
        this.elements.modelSelect.addEventListener('change', (e) => this.onModelChange(e));

        // Sidebar toggle
        this.elements.sidebarToggle.addEventListener('click', () => this.toggleSidebar());

        // Quick commands
        document.querySelectorAll('.quick-cmd-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.cmd;
                this.executeCommand(cmd);
            });
        });

        // Terminal mode selector
        const modeSelect = document.getElementById('terminal-mode-select');
        if (modeSelect) {
            modeSelect.addEventListener('change', (e) => this.setMode(e.target.value));
        }

        // Click anywhere to focus input
        this.elements.body.addEventListener('click', () => this.focusInput());

        // Tab completion
        this.elements.input.addEventListener('keydown', (e) => {
            if (e.key === 'Tab') {
                e.preventDefault();
                this.handleTabCompletion();
            }
        });
    }

    /**
     * Handle key down events
     */
    handleKeyDown(e) {
        switch (e.key) {
            case 'Enter':
                if (!e.shiftKey) {
                    e.preventDefault();
                    this.submitCommand();
                }
                break;
            case 'ArrowUp':
                if (this.canNavigateHistory(-1)) {
                    e.preventDefault();
                    this.navigateHistory(-1);
                }
                break;
            case 'ArrowDown':
                if (this.canNavigateHistory(1)) {
                    e.preventDefault();
                    this.navigateHistory(1);
                }
                break;
            case 'Escape':
                this.elements.input.value = '';
                this.autoResizeInput();
                this.updateInputState();
                break;
            case 'l':
                if (e.ctrlKey) {
                    e.preventDefault();
                    this.cmdClear();
                }
                break;
        }
    }

    /**
     * Handle tab completion
     */
    handleTabCompletion() {
        const input = this.elements.input.value;
        
        // Only complete commands that start with /
        if (!input.startsWith('/')) {
            return;
        }
        
        const withoutSlash = input.slice(1);
        const parts = withoutSlash.split(' ');
        const lastPart = parts[parts.length - 1];

        // Complete command names (after the /)
        if (parts.length === 1) {
            // Combine built-in and dynamic commands
            const allCommands = [
                ...Object.keys(this.builtinCommands),
                ...Object.keys(this.dynamicCommands)
            ];
            
            const matches = allCommands.filter(cmd => 
                cmd.startsWith(lastPart)
            );
            
            if (matches.length === 1) {
                this.elements.input.value = '/' + matches[0] + ' ';
            } else if (matches.length > 1) {
                // Show all matches
                const grouped = {};
                matches.forEach(m => {
                    const isBuiltin = this.builtinCommands[m];
                    const isDynamic = this.dynamicCommands[m];
                    const type = isBuiltin ? 'builtin' : (isDynamic?.type || 'unknown');
                    if (!grouped[type]) grouped[type] = [];
                    grouped[type].push('/' + m);
                });
                
                let output = '';
                Object.entries(grouped).forEach(([type, cmds]) => {
                    output += `<span style="color: var(--terminal-text-dim);">[${type}]</span> ${cmds.join('  ')}\n`;
                });
                this.printOutput(output, 'info');
            }
        }
    }

    /**
     * Navigate command history
     */
    navigateHistory(direction) {
        if (this.commandHistory.length === 0) return;

        this.historyIndex += direction;

        if (this.historyIndex < 0) {
            this.historyIndex = 0;
        } else if (this.historyIndex >= this.commandHistory.length) {
            this.historyIndex = this.commandHistory.length;
            this.elements.input.value = '';
            return;
        }

        this.elements.input.value = this.commandHistory[this.historyIndex];
        this.autoResizeInput();
        this.updateInputState();
    }

    /**
     * Submit command
     */
    submitCommand() {
        const input = this.normalizeInput(this.elements.input.value).trim();
        if (!input) return;

        // Check if we're in confirmation mode
        if (this.terminalState === 'pending_confirmation' || this.terminalState === 'pending_route_confirmation') {
            this.elements.input.value = '';
            this.autoResizeInput();
            this.updateInputState();
            this.printCommand(input);
            const answer = input.toLowerCase();
            if (answer === 'y' || answer === 'yes') {
                if (this.terminalState === 'pending_route_confirmation') {
                    this.confirmRouteSuggestion();
                } else {
                    this.confirmExecution();
                }
            } else {
                if (this.terminalState === 'pending_route_confirmation') {
                    this.cancelRouteSuggestion();
                } else {
                    this.cancelConfirmation();
                }
            }
            return;
        }

        // Check if we're in parameter collection mode
        if (this.pendingCommand) {
            this.collectParameter(input);
            return;
        }

        // Add to history
        this.commandHistory.push(input);
        this.historyIndex = this.commandHistory.length;

        // Print command
        this.printCommand(input);

        // Clear input
        this.elements.input.value = '';
        this.autoResizeInput();
        this.updateInputState();

        // Execute
        this.executeCommand(input);
    }

    /**
     * Execute a command
     * CLI-style: commands start with /, plain text defaults to chat
     */
    async executeCommand(input) {
        // If input is a string, parse it
        let cmd, args;
        if (typeof input === 'string') {
            // Check if it starts with / (command mode)
            if (input.startsWith('/')) {
                // Remove the / prefix and parse
                const withoutSlash = input.slice(1);
                const parts = withoutSlash.split(/\s+/);
                cmd = parts[0].toLowerCase();
                args = parts.slice(1);
            } else {
                // No / prefix - treat as chat message
                await this.cmdChat([input]);
                return;
            }
        } else {
            // Direct command name (from button clicks, etc.)
            cmd = input.toLowerCase();
            args = [];
        }

        // Check if it's a built-in command
        if (this.builtinCommands[cmd]) {
            await this.builtinCommands[cmd](args);
            return;
        }

        // Check if it's a dynamic command
        if (this.dynamicCommands[cmd]) {
            await this.executeDynamicCommand(cmd, args);
            return;
        }

        // Unknown command
        this.printError(`Unknown command: /${cmd}. Type /help for available commands.`);
    }

    /**
     * Execute a dynamic command (from backend configuration)
     */
    async executeDynamicCommand(cmdName, providedArgs = []) {
        const cmdConfig = this.dynamicCommands[cmdName];
        if (!cmdConfig) {
            this.printError(`Unknown command: ${cmdName}`);
            return;
        }

        // Parse provided arguments into params
        const params = {};
        const paramDefs = cmdConfig.parameters || [];

        // Map positional args to parameter names
        providedArgs.forEach((arg, index) => {
            if (index < paramDefs.length) {
                params[paramDefs[index].name] = arg;
            }
        });

        // Check for missing required parameters
        const missingParams = paramDefs.filter(p => 
            p.required && params[p.name] === undefined
        );

        if (missingParams.length > 0) {
            // Start interactive parameter collection
            this.startParameterCollection(cmdName, cmdConfig, params, missingParams);
            return;
        }

        // Execute with collected params
        await this.runDynamicCommand(cmdName, params);
    }

    /**
     * Start interactive parameter collection
     */
    startParameterCollection(cmdName, cmdConfig, existingParams, missingParams) {
        this.pendingCommand = {
            name: cmdName,
            config: cmdConfig,
            params: existingParams,
            missingParams: missingParams
        };
        this.paramIndex = 0;

        this.printInfo(`Command: ${cmdConfig.display_name || cmdName}`);
        this.printOutput(`<span style="color: var(--terminal-text-dim);">${cmdConfig.description || ''}</span>`);
        
        // Start collecting first missing parameter
        this.promptForNextParameter();
    }

    /**
     * Prompt for the next missing parameter
     */
    promptForNextParameter() {
        if (!this.pendingCommand || this.paramIndex >= this.pendingCommand.missingParams.length) {
            return;
        }

        const param = this.pendingCommand.missingParams[this.paramIndex];
        const required = param.required ? '*' : '';
        const defaultVal = param.default !== undefined ? ` [${param.default}]` : '';
        
        let prompt = `  ${param.prompt || param.name}${required}${defaultVal}: `;
        
        if (param.type === 'select' && param.options) {
            prompt += `\n  Options: ${param.options.join(', ')}\n  > `;
        }

        this.printOutput(`<span class="terminal-prompt" style="color: var(--terminal-yellow);">?</span> ${prompt}`);
        
        // Update prompt indicator
        this.updatePromptIndicator(`${param.name}`);
    }

    /**
     * Collect a parameter value from user input
     */
    async collectParameter(input) {
        const param = this.pendingCommand.missingParams[this.paramIndex];
        let value = input.trim();

        // Use default if empty
        if (!value && param.default !== undefined) {
            value = param.default;
        }

        // Validate select type
        if (param.type === 'select' && param.options) {
            if (!param.options.includes(value)) {
                this.printWarning(`Invalid option. Choose from: ${param.options.join(', ')}`);
                this.promptForNextParameter();
                return;
            }
        }

        // Convert types
        if (param.type === 'number' || param.type === 'integer') {
            value = parseFloat(value);
            if (isNaN(value)) {
                this.printWarning('Please enter a valid number');
                this.promptForNextParameter();
                return;
            }
        } else if (param.type === 'boolean') {
            value = value.toLowerCase() === 'true' || value === '1' || value === 'yes';
        }

        // Store the value
        this.pendingCommand.params[param.name] = value;
        this.paramIndex++;

        // Check if more parameters needed
        if (this.paramIndex < this.pendingCommand.missingParams.length) {
            this.promptForNextParameter();
        } else {
            // All parameters collected, execute command
            const cmdName = this.pendingCommand.name;
            const params = this.pendingCommand.params;
            
            // Reset state
            this.pendingCommand = null;
            this.paramIndex = 0;
            this.updatePromptIndicator();

            // Execute
            await this.runDynamicCommand(cmdName, params);
        }
    }

    /**
     * Run a dynamic command with parameters
     */
    async runDynamicCommand(cmdName, params) {
        this.showTypingIndicator();
        this.isLoading = true;

        try {
            const response = await fetch('/api/terminal/commands/execute_by_name/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    name: cmdName,
                    params: params,
                    session_id: this.sessionId,
                    mode: this.terminalMode,
                })
            });

            const data = await response.json();
            this.hideTypingIndicator();

            // Handle confirmation required
            if (data.confirmation_required && data.confirmation_token) {
                this.handleConfirmationResponse(data, cmdName, params);
                return;
            }

            if (data.success) {
                this.printOutput(data.output || 'Command executed successfully');

                if (data.metadata) {
                    this.messageCount++;
                    if (data.metadata.tokens) {
                        this.tokenCount += data.metadata.tokens;
                    }
                    if (data.metadata.session_id) {
                        this.sessionId = data.metadata.session_id;
                    }
                    this.updateSessionInfo();
                }
            } else {
                // Check if we need to collect more parameters
                if (data.missing_params && data.missing_params.length > 0) {
                    this.printWarning(`Missing parameters: ${data.missing_params.join(', ')}`);
                } else {
                    this.printError(data.error || 'Command execution failed');
                }
            }
        } catch (error) {
            this.hideTypingIndicator();
            this.printError(`Network error: ${error.message}`);
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Handle confirmation response from server
     */
    handleConfirmationResponse(data, cmdName, params) {
        this.terminalState = 'pending_confirmation';
        this.pendingConfirmation = {
            name: cmdName,
            params: params,
            token: data.confirmation_token,
            details: data,
        };

        const riskLevel = data.risk_level || 'unknown';
        const prompt = data.confirmation_prompt || '';

        this.printOutput(`
<div style="padding: 8px 0; border: 1px solid var(--terminal-yellow); border-radius: 4px; padding: 12px; margin: 4px 0;">
<strong style="color: var(--terminal-yellow);">Confirmation required</strong>

  <span style="color: var(--terminal-text-dim);">Command:</span>    ${this.escapeHtml(cmdName)}
  <span style="color: var(--terminal-text-dim);">Risk Level:</span> <span style="color: ${riskLevel === 'admin' ? 'var(--terminal-red)' : riskLevel === 'write_high' ? '#fd7e14' : 'var(--terminal-yellow)'};">${riskLevel}</span>
  <span style="color: var(--terminal-text-dim);">Parameters:</span> ${this.escapeHtml(JSON.stringify(params))}
  <span style="color: var(--terminal-text-dim);">Mode:</span>       ${this.terminalMode}

  Type <span class="terminal-cmd">Y</span> to confirm, <span class="terminal-cmd">N</span> to cancel:
</div>`, 'warning');

        // Update prompt to confirm>
        this.updatePromptIndicator('confirm');
        this.updateInputState();
    }

    /**
     * Confirm pending execution
     */
    async confirmExecution() {
        if (!this.pendingConfirmation) return;

        const { name, params, token } = this.pendingConfirmation;

        // Reset state
        this.terminalState = 'normal';
        const confirmation = this.pendingConfirmation;
        this.pendingConfirmation = null;
        this.updatePromptIndicator();
        this.updateInputState();

        this.showTypingIndicator();
        this.isLoading = true;

        try {
            const response = await fetch('/api/terminal/commands/confirm_execute/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    name: confirmation.name,
                    params: confirmation.params,
                    confirmation_token: confirmation.token,
                    session_id: this.sessionId,
                    mode: this.terminalMode,
                })
            });

            const data = await response.json();
            this.hideTypingIndicator();

            if (data.success) {
                this.printSuccess('Command confirmed and executed');
                this.printOutput(data.output || '');
                if (data.metadata) {
                    this.messageCount++;
                    this.updateSessionInfo();
                }
            } else {
                this.printError(data.error || 'Confirmed execution failed');
            }
        } catch (error) {
            this.hideTypingIndicator();
            this.printError(`Network error: ${error.message}`);
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Cancel pending confirmation
     */
    cancelConfirmation() {
        this.terminalState = 'normal';
        this.pendingConfirmation = null;
        this.updatePromptIndicator();
        this.updateInputState();
        this.printInfo('Command cancelled');
    }

    /**
     * Handle mid-confidence route suggestion from terminal chat router.
     */
    handleRouteSuggestion(data) {
        this.terminalState = 'pending_route_confirmation';
        this.pendingRouteSuggestion = {
            command: data.suggested_command,
            intent: data.suggested_intent,
            prompt: data.suggestion_prompt,
        };

        this.printOutput(`
<div style="padding: 8px 0; border: 1px solid var(--terminal-yellow); border-radius: 4px; padding: 12px; margin: 4px 0;">
<strong style="color: var(--terminal-yellow);">Route confirmation required</strong>

  <span style="color: var(--terminal-text-dim);">Suggested command:</span> ${this.escapeHtml(data.suggested_command || '')}
  <span style="color: var(--terminal-text-dim);">Detected intent:</span>   ${this.escapeHtml(data.suggested_intent || 'unknown')}

  Type <span class="terminal-cmd">Y</span> to execute, <span class="terminal-cmd">N</span> to cancel:
</div>`, 'warning');

        this.updatePromptIndicator('confirm');
        this.updateInputState();
    }

    /**
     * Execute suggested builtin command after user confirms.
     */
    async confirmRouteSuggestion() {
        if (!this.pendingRouteSuggestion) return;

        const suggestion = this.pendingRouteSuggestion;
        this.terminalState = 'normal';
        this.pendingRouteSuggestion = null;
        this.updatePromptIndicator();
        this.updateInputState();

        const commandName = (suggestion.command || '').replace(/^\//, '').toLowerCase();
        if (commandName && this.builtinCommands[commandName]) {
            this.printInfo(`Executing suggested command: /${commandName}`);
            await this.builtinCommands[commandName]([]);
            return;
        }

        this.printError(`Suggested command is unavailable: ${suggestion.command || 'unknown'}`);
    }

    /**
     * Cancel route suggestion confirmation.
     */
    cancelRouteSuggestion() {
        this.terminalState = 'normal';
        this.pendingRouteSuggestion = null;
        this.updatePromptIndicator();
        this.updateInputState();
        this.printInfo('Suggested command cancelled');
    }

    /**
     * Load terminal capabilities from server
     */
    async loadCapabilities() {
        try {
            const response = await fetch('/api/terminal/commands/capabilities/');
            const data = await response.json();

            if (data.success) {
                this.userCapabilities = data;

                // Lock mode if needed
                if (data.available_modes && data.available_modes.length === 1) {
                    this.terminalMode = data.available_modes[0];
                }

                // Update mode selector if present
                this.updateModeSelector();
            }
        } catch (error) {
            console.error('Failed to load capabilities:', error);
        }
    }

    /**
     * Set terminal mode
     */
    setMode(mode) {
        if (this.userCapabilities && this.userCapabilities.available_modes) {
            if (!this.userCapabilities.available_modes.includes(mode)) {
                this.printError(`Mode "${mode}" is not available. Available: ${this.userCapabilities.available_modes.join(', ')}`);
                return;
            }
        }
        this.terminalMode = mode;
        this.updateModeSelector();
        this.printSuccess(`Terminal mode set to: ${mode}`);
    }

    /**
     * Update mode selector UI
     */
    updateModeSelector() {
        const modeSelect = document.getElementById('terminal-mode-select');
        const modeStatus = document.getElementById('mode-status');
        if (!modeSelect) return;

        modeSelect.value = this.terminalMode;

        // Disable unavailable options
        if (this.userCapabilities && this.userCapabilities.available_modes) {
            Array.from(modeSelect.options).forEach(opt => {
                opt.disabled = !this.userCapabilities.available_modes.includes(opt.value);
            });
        }

        if (modeStatus) {
            if (this.userCapabilities && this.userCapabilities.reason_if_locked) {
                modeStatus.textContent = this.userCapabilities.reason_if_locked;
                modeStatus.style.color = 'var(--terminal-yellow)';
            } else {
                modeStatus.textContent = '';
            }
        }
    }

    /**
     * Update prompt indicator
     */
    updatePromptIndicator(paramName = null) {
        const promptEl = document.getElementById('terminal-prompt');
        if (promptEl) {
            if (paramName) {
                promptEl.textContent = `${paramName}>`;
                promptEl.style.color = 'var(--terminal-yellow)';
            } else {
                promptEl.textContent = this.originalPrompt;
                promptEl.style.color = '';
            }
        }
    }

    /**
     * List available commands
     */
    cmdListCommands() {
        let output = '<div style="padding: 8px 0;">';
        output += '<strong style="color: var(--terminal-cyan);">Available Commands</strong>\n\n';
        
        // Built-in commands
        output += '<span style="color: var(--terminal-yellow);">Built-in:</span>\n';
        Object.keys(this.builtinCommands).forEach(cmd => {
            output += `  /${cmd.padEnd(14)} \n`;
        });
        
        // Dynamic commands by category
        if (Object.keys(this.dynamicCommands).length > 0) {
            const byCategory = {};
            Object.entries(this.dynamicCommands).forEach(([name, cmd]) => {
                const cat = cmd.category || 'general';
                if (!byCategory[cat]) byCategory[cat] = [];
                byCategory[cat].push({name, ...cmd});
            });
            
            Object.entries(byCategory).forEach(([cat, cmds]) => {
                output += `\n<span style="color: var(--terminal-yellow);">${cat}:</span>\n`;
                cmds.forEach(cmd => {
                    const typeIcon = cmd.type === 'prompt' ? '🤖' : (cmd.type === 'api' ? '📡' : '⚡');
                    output += `  ${typeIcon} /${(cmd.name).padEnd(14)} - ${cmd.display_name || cmd.description || ''}\n`;
                });
            });
        }
        
        output += '\n<span style="color: var(--terminal-text-dim);">Tip: Type without / prefix to chat with AI</span>';
        output += '</div>';
        this.printOutput(output);
    }

    /**
     * Print command line
     */
    printCommand(cmd) {
        const line = document.createElement('div');
        line.className = 'terminal-output-line command';
        line.innerHTML = `<span class="terminal-prompt">${this.originalPrompt}</span><span class="terminal-cmd">${this.escapeHtml(cmd)}</span>`;
        this.elements.output.appendChild(line);
        this.scrollToBottom();
    }

    /**
     * Print output
     */
    printOutput(text, type = 'default') {
        const line = document.createElement('div');
        line.className = `terminal-output-line ${type}`;
        line.innerHTML = text;
        this.elements.output.appendChild(line);
        this.scrollToBottom();
        return line;
    }

    /**
     * Print AI response with styling
     */
    printAIResponse(text, metadata = null) {
        const container = document.createElement('div');
        container.className = 'terminal-output-line ai-response';
        
        // Format the response
        const formattedText = this.formatAIResponse(text);
        container.innerHTML = formattedText;

        if (metadata) {
            const meta = document.createElement('div');
            meta.className = 'terminal-output-line';
            meta.style.cssText = 'color: var(--terminal-text-dim); font-size: 11px; margin-top: 4px; padding-left: 16px;';
            meta.innerHTML = `└─ ${metadata.provider || 'AI'} | ${metadata.model || 'unknown'}${metadata.tokens ? ` | ${metadata.tokens} tokens` : ''}`;
            container.appendChild(meta);
        }

        this.elements.output.appendChild(container);
        this.scrollToBottom();
        this.renderRichContent(container);
    }

    /**
     * Format AI response with syntax highlighting
     */
    formatAIResponse(text) {
        const source = this.escapeHtml(text || '');

        if (window.marked?.parse) {
            return window.marked.parse(source);
        }

        let formatted = source;
        formatted = formatted.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
            const className = lang ? ` class="language-${lang}"` : '';
            return `<pre class="terminal-code-block"><code${className}>${code}</code></pre>`;
        });
        formatted = formatted.replace(/`([^`]+)`/g, '<code class="terminal-inline-code">$1</code>');
        formatted = formatted.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        formatted = formatted.replace(/\*([^*]+)\*/g, '<em>$1</em>');
        formatted = formatted.replace(/\n/g, '<br>');
        return formatted;
    }

    /**
     * Show typing indicator
     */
    showTypingIndicator() {
        const indicator = document.createElement('div');
        indicator.className = 'terminal-typing';
        indicator.id = 'typing-indicator';
        indicator.innerHTML = `
            <span class="terminal-typing-dot"></span>
            <span class="terminal-typing-dot"></span>
            <span class="terminal-typing-dot"></span>
        `;
        this.elements.output.appendChild(indicator);
        this.scrollToBottom();
    }

    /**
     * Hide typing indicator
     */
    hideTypingIndicator() {
        const indicator = document.getElementById('typing-indicator');
        if (indicator) indicator.remove();
    }

    /**
     * Print error
     */
    printError(text) {
        this.printOutput(`❌ Error: ${text}`, 'error');
    }

    /**
     * Print success
     */
    printSuccess(text) {
        this.printOutput(`✓ ${text}`, 'success');
    }

    /**
     * Print info
     */
    printInfo(text) {
        this.printOutput(`ℹ ${text}`, 'info');
    }

    /**
     * Print warning
     */
    printWarning(text) {
        this.printOutput(`⚠ ${text}`, 'warning');
    }

    /**
     * Clear terminal
     */
    cmdClear() {
        this.elements.output.innerHTML = '';
        this.printInfo('Terminal cleared. Type "/help" for commands.');
    }

    /**
     * Help command
     */
    cmdHelp() {
        let helpText = `
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-cyan);">Built-in Commands:</strong>

  <span class="terminal-cmd">/help</span>              Show this help message
  <span class="terminal-cmd">/clear</span>             Clear the terminal screen
  <span class="terminal-cmd">/history</span>           Show command history
  <span class="terminal-cmd">/status</span>            Show live system readiness
  <span class="terminal-cmd">/regime</span>            Show current market regime
  <span class="terminal-cmd">/commands</span>          List all available commands
  <span class="terminal-cmd">/version</span>           Show system version
  <span class="terminal-cmd">/export</span>            Export chat history`;
        
        // Add dynamic commands by category
        if (Object.keys(this.dynamicCommands).length > 0) {
            const byCategory = {};
            Object.entries(this.dynamicCommands).forEach(([name, cmd]) => {
                const cat = cmd.category || 'general';
                if (!byCategory[cat]) byCategory[cat] = [];
                byCategory[cat].push({name, ...cmd});
            });
            
            Object.entries(byCategory).forEach(([cat, cmds]) => {
                helpText += `\n\n<strong style="color: var(--terminal-cyan);">${cat}:</strong>`;
                cmds.forEach(cmd => {
                    const typeIcon = cmd.type === 'prompt' ? '🤖' : (cmd.type === 'api' ? '📡' : '⚡');
                    helpText += `\n  ${typeIcon} <span class="terminal-cmd">/${cmd.name}</span>`;
                    if (cmd.display_name && cmd.display_name !== cmd.name) {
                        helpText += ` - ${cmd.display_name}`;
                    }
                });
            });
        }
        
        helpText += `

<strong style="color: var(--terminal-cyan);">Chat Mode:</strong>
  Just type your message and press Enter to chat with AI.
  No command prefix needed - plain text is sent as chat.

<strong style="color: var(--terminal-cyan);">Shortcuts:</strong>
  <span class="terminal-key">Tab</span>               Auto-complete command (after /)
  <span class="terminal-key">↑/↓</span>               Navigate command history
  <span class="terminal-key">Ctrl+L</span>            Clear screen
  <span class="terminal-key">Esc</span>               Clear input line

<strong style="color: var(--terminal-cyan);">Examples:</strong>
  <span class="terminal-cmd">/help</span>              → Show help
  <span class="terminal-cmd">/status</span>            → Show live system readiness
  <span class="terminal-cmd">Hello, how are you?</span> → Chat with AI
  <span class="terminal-cmd">目前系统是什么状态</span>  → Routed to /status
  <span class="terminal-cmd">/regime</span>           → Get current market regime
</div>`;
        this.printOutput(helpText);
    }

    /**
     * Status command
     */
    async cmdStatus() {
        this.printInfo('Fetching system status...');
        
        try {
            const response = await fetch('/api/ready/');
            const data = await response.json();
            const checks = data.checks || {};
            const overallStatus = data.status || (response.ok ? 'ok' : 'error');

            const statusColor = overallStatus === 'ok'
                ? 'var(--terminal-green)'
                : 'var(--terminal-red)';

            const renderCheck = (name, result) => {
                const checkStatus = result?.status || 'unknown';
                const colorMap = {
                    ok: 'var(--terminal-green)',
                    warning: 'var(--terminal-yellow)',
                    skipped: 'var(--terminal-blue)',
                    error: 'var(--terminal-red)',
                    unknown: 'var(--terminal-text-dim)',
                };
                const detail = result?.error
                    || result?.reason
                    || (result?.workers ? `${result.workers} workers` : '')
                    || (result?.empty_tables ? `empty: ${result.empty_tables.join(', ')}` : '')
                    || '';

                return `
  ${name.padEnd(14)} <span style="color: ${colorMap[checkStatus] || colorMap.unknown};">${checkStatus}</span>${detail ? ` <span style="color: var(--terminal-text-dim);">(${this.escapeHtml(detail)})</span>` : ''}`;
            };

            this.printOutput(`
<div style="padding: 8px 0;">
<strong style="color: ${statusColor};">System Readiness: ${this.escapeHtml(overallStatus.toUpperCase())}</strong>

  API Liveness:   <span style="color: var(--terminal-green);">ok</span>
${renderCheck('Database:', checks.database)}
${renderCheck('Redis:', checks.redis)}
${renderCheck('Celery:', checks.celery)}
${renderCheck('Critical Data:', checks.critical_data)}
  Provider:       <span style="color: var(--terminal-cyan);">${this.currentProvider || 'Not selected'}</span>
  Model:          <span style="color: var(--terminal-cyan);">${this.currentModel || 'Not selected'}</span>
  Session ID:     <span style="color: var(--terminal-text-dim);">${this.sessionId || 'New session'}</span>
  Messages:       <span style="color: var(--terminal-yellow);">${this.messageCount}</span>
  Tokens Used:    <span style="color: var(--terminal-purple);">${this.tokenCount}</span>
  Timestamp:      <span style="color: var(--terminal-text-dim);">${this.escapeHtml(data.timestamp || '-')}</span>
</div>`);
        } catch (error) {
            this.printError('Failed to fetch system status');
        }
    }

    /**
     * Regime command
     */
    async cmdRegime() {
        this.printInfo('Fetching current regime...');
        
        try {
            const response = await fetch('/api/regime/current/');
            const data = await response.json();
            
            // Handle both response formats
            const regimeData = data.data || data;
            const regime = regimeData.dominant_regime || regimeData.regime || 'Unknown';
            const confidence = regimeData.confidence;
            
            const regimeColors = {
                'Recovery': 'var(--terminal-green)',
                'Overheat': 'var(--terminal-red)',
                'Stagflation': 'var(--terminal-yellow)',
                'Deflation': 'var(--terminal-blue)',
            };
            
            const color = regimeColors[regime] || 'var(--terminal-text)';
            
            this.printOutput(`
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-cyan);">Current Market Regime</strong>

  Regime:         <span style="color: ${color}; font-weight: bold;">${regime}</span>
  Confidence:     <span style="color: var(--terminal-cyan);">${confidence ? (confidence * 100).toFixed(1) + '%' : 'N/A'}</span>
  Source:         <span style="color: var(--terminal-text-dim);">${regimeData.source || 'N/A'}</span>
  Observed:       <span style="color: var(--terminal-text-dim);">${regimeData.observed_at || 'N/A'}</span>
</div>`);
        } catch (error) {
            this.printError('Failed to fetch regime data');
        }
    }

    /**
     * Signals command
     */
    async cmdSignals() {
        this.printInfo('Fetching active signals...');
        
        try {
            const response = await fetch('/api/signal/signals/');
            const data = await response.json();
            const signals = data.results || data.signals || data.items || [];
            
            if (signals.length === 0) {
                this.printInfo('No active signals found');
                return;
            }
            
            let table = `
<table class="terminal-table">
  <thead>
    <tr>
      <th>Signal</th>
      <th>Type</th>
      <th>Status</th>
      <th>Confidence</th>
    </tr>
  </thead>
  <tbody>`;
            
            signals.slice(0, 10).forEach(signal => {
                table += `
    <tr>
      <td>${signal.name || signal.signal_id || '-'}</td>
      <td>${signal.signal_type || signal.type || '-'}</td>
      <td>${signal.status || '-'}</td>
      <td>${signal.confidence ? (signal.confidence * 100).toFixed(0) + '%' : '-'}</td>
    </tr>`;
            });
            
            table += `
  </tbody>
</table>`;
            
            this.printOutput(table);
        } catch (error) {
            this.printError('Failed to fetch signals');
        }
    }

    /**
     * Quota command
     */
    async cmdQuota() {
        this.printInfo('Fetching decision quota...');
        
        try {
            const response = await fetch('/api/decision-rhythm/quotas/by-period/?period=WEEKLY');
            const data = await response.json();
            
            // Handle response format
            const quota = data.data || data;
            const maxDecisions = quota.max_decisions || 10;
            const usedDecisions = quota.used_decisions || 0;
            const remaining = quota.remaining_decisions || (maxDecisions - usedDecisions);
            
            const percent = maxDecisions > 0 
                ? Math.round((usedDecisions / maxDecisions) * 100) 
                : 0;
            
            let barColor = 'var(--terminal-green)';
            if (percent >= 80) barColor = 'var(--terminal-red)';
            else if (percent >= 60) barColor = 'var(--terminal-yellow)';
            
            this.printOutput(`
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-cyan);">Decision Quota Status</strong>

  Period:         ${quota.period || 'WEEKLY'}
  Used:           ${usedDecisions} / ${maxDecisions}
  Remaining:      ${remaining}
  
  <div class="terminal-progress" style="margin-top: 8px;">
    <div class="terminal-progress-bar" style="width: ${percent}%; background: ${barColor};"></div>
  </div>
  <span style="color: var(--terminal-text-dim); font-size: 11px;">${percent}% used</span>
</div>`);
        } catch (error) {
            this.printError('Failed to fetch quota data');
        }
    }

    /**
     * Provider command
     */
    async cmdProvider(args) {
        if (args.length === 0) {
            // Show current provider and available options
            let text = `
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-cyan);">AI Providers</strong>

  Current:        <span style="color: var(--terminal-green);">${this.currentProvider || 'Not selected'}</span>
  
  Available:`;
            
            this.providers.forEach(p => {
                const marker = p.name === this.currentProvider ? '→' : ' ';
                text += `\n    ${marker} ${p.name} (${p.display_label})`;
            });
            
            text += `
  
  Usage: <span class="terminal-cmd">provider &lt;name&gt;</span> to switch
</div>`;
            
            this.printOutput(text);
        } else {
            // Set provider
            const providerName = args[0];
            const provider = this.providers.find(p => p.name === providerName);
            
            if (provider) {
                this.currentProvider = providerName;
                this.elements.providerSelect.value = providerName;
                await this.loadModels(providerName);
                this.updateBadges();
                this.printSuccess(`Provider switched to: ${providerName}`);
            } else {
                this.printError(`Unknown provider: ${providerName}`);
            }
        }
    }

    /**
     * Model command
     */
    cmdModel(args) {
        if (args.length === 0) {
            // Show current model and available options
            let text = `
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-cyan);">AI Models</strong>

  Provider:       ${this.currentProvider || 'Not selected'}
  Current Model:  <span style="color: var(--terminal-green);">${this.currentModel || 'Not selected'}</span>
  
  Available:`;
            
            this.models.forEach(m => {
                const marker = m === this.currentModel ? '→' : ' ';
                text += `\n    ${marker} ${m}`;
            });
            
            text += `
  
  Usage: <span class="terminal-cmd">model &lt;name&gt;</span> to switch
</div>`;
            
            this.printOutput(text);
        } else {
            // Set model
            const modelName = args[0];
            if (this.models.includes(modelName)) {
                this.currentModel = modelName;
                this.elements.modelSelect.value = modelName;
                this.updateBadges();
                this.printSuccess(`Model switched to: ${modelName}`);
            } else {
                this.printError(`Unknown model: ${modelName}`);
            }
        }
    }

    /**
     * History command
     */
    cmdHistory() {
        if (this.commandHistory.length === 0) {
            this.printInfo('No command history');
            return;
        }
        
        let text = '<div style="padding: 8px 0;"><strong style="color: var(--terminal-cyan);">Command History</strong>\n\n';
        
        this.commandHistory.forEach((cmd, i) => {
            text += `  ${(i + 1).toString().padStart(3)}  ${this.escapeHtml(cmd)}\n`;
        });
        
        text += '</div>';
        this.printOutput(text);
    }

    /**
     * Version command
     */
    cmdVersion() {
        this.printOutput(`
<div style="padding: 8px 0;">
<strong style="color: var(--terminal-green);">AgomSAAF Terminal</strong>

  Version:        2.0.0
  Build:          2024.03
  Framework:      Django + Alpine.js
  UI Style:       CLI Terminal Emulator
  
  © 2024 AgomSAAF Team
</div>`);
    }

    /**
     * Export command
     */
    cmdExport() {
        const history = this.elements.output.innerText;
        const blob = new Blob([history], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `terminal-export-${Date.now()}.txt`;
        a.click();
        URL.revokeObjectURL(url);
        this.printSuccess('Chat history exported');
    }

    /**
     * Chat command - send message to AI
     */
    async cmdChat(args) {
        if (args.length === 0) {
            this.printInfo('Usage: chat <message>');
            return;
        }

        const message = args.join(' ');
        
        // Show loading
        this.isLoading = true;
        this.showTypingIndicator();

        try {
            const response = await fetch('/api/terminal/chat/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({
                    message: message,
                    session_id: this.sessionId,
                    provider_name: this.currentProvider,
                    model: this.currentModel,
                    context: {}
                })
            });

            const data = await response.json();

            this.hideTypingIndicator();

            if (response.ok) {
                this.sessionId = data.session_id;
                this.messageCount += 2;
                if (data.metadata?.tokens) {
                    this.tokenCount += data.metadata.tokens;
                }

                if (data.route_confirmation_required) {
                    this.handleRouteSuggestion(data);
                }
                this.printAIResponse(data.reply, data.metadata);
                this.updateSessionInfo();
            } else {
                this.printError(data.error || 'Failed to get AI response');
            }
        } catch (error) {
            this.hideTypingIndicator();
            this.printError(`Network error: ${error.message}`);
        } finally {
            this.isLoading = false;
        }
    }

    /**
     * Load providers from API
     */
    async loadProviders() {
        try {
            const response = await fetch('/api/prompt/chat/providers');
            const data = await response.json();
            
            this.providers = data.providers || [];
            
            // Update select
            if (this.providers.length > 0) {
                this.elements.providerSelect.innerHTML = this.providers.map(p => 
                    `<option value="${p.name}">${p.display_label}</option>`
                ).join('');
                
                // Set default
                if (data.default_provider) {
                    this.currentProvider = data.default_provider;
                    this.elements.providerSelect.value = data.default_provider;
                } else {
                    this.currentProvider = this.providers[0].name;
                }
                
                await this.loadModels(this.currentProvider);
            } else {
                this.elements.providerSelect.innerHTML = '<option value="">No providers available</option>';
            }
            
            this.updateBadges();
        } catch (error) {
            console.error('Failed to load providers:', error);
            this.elements.providerSelect.innerHTML = '<option value="">Failed to load</option>';
        }
    }

    /**
     * Load models for a provider
     */
    async loadModels(providerName) {
        if (!providerName) return;
        
        try {
            const response = await fetch(`/api/prompt/chat/models?provider=${providerName}`);
            const data = await response.json();
            
            this.models = data.models || [];
            
            if (this.models.length > 0) {
                this.elements.modelSelect.innerHTML = this.models.map(m => 
                    `<option value="${m}">${m}</option>`
                ).join('');
                
                // Set default model
                const provider = this.providers.find(p => p.name === providerName);
                if (provider?.default_model && this.models.includes(provider.default_model)) {
                    this.currentModel = provider.default_model;
                    this.elements.modelSelect.value = provider.default_model;
                } else {
                    this.currentModel = this.models[0];
                }
            } else {
                this.elements.modelSelect.innerHTML = '<option value="">No models available</option>';
                this.currentModel = null;
            }
            
            this.updateBadges();
        } catch (error) {
            console.error('Failed to load models:', error);
        }
    }

    /**
     * Handle provider change from select
     */
    async onProviderChange(e) {
        this.currentProvider = e.target.value;
        await this.loadModels(this.currentProvider);
        this.updateBadges();
    }

    /**
     * Handle model change from select
     */
    onModelChange(e) {
        this.currentModel = e.target.value;
        this.updateBadges();
    }

    /**
     * Update badge displays
     */
    updateBadges() {
        this.elements.providerBadge.textContent = this.currentProvider || 'none';
        this.elements.modelBadge.textContent = this.currentModel || 'none';
    }

    /**
     * Update session info display
     */
    updateSessionInfo() {
        if (this.sessionId) {
            this.elements.sessionId.textContent = this.sessionId.substring(0, 8) + '...';
        }
        this.elements.messageCount.textContent = this.messageCount;
        this.elements.tokenCount.textContent = this.tokenCount;
    }

    /**
     * Toggle sidebar
     */
    toggleSidebar() {
        this.elements.sidebar.classList.toggle('collapsed');
        this.elements.sidebarToggle.textContent = 
            this.elements.sidebar.classList.contains('collapsed') ? '▶' : '◀';
    }

    /**
     * Focus input
     */
    focusInput() {
        this.elements.input.focus();
    }

    /**
     * Initialize markdown and mermaid renderers
     */
    initializeRichTextRenderer() {
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
                theme: 'dark',
            });
        }
    }

    /**
     * Adjust textarea height to its content.
     */
    autoResizeInput() {
        const input = this.elements.input;
        if (!input) return;
        input.style.height = 'auto';
        input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
    }

    /**
     * Track current input size and state.
     */
    updateInputState(message = null, level = 'info') {
        const value = this.elements.input.value || '';
        const count = value.length;
        const ratio = count / this.maxInputChars;

        if (this.elements.inputCount) {
            this.elements.inputCount.textContent = `${count}/${this.maxInputChars}`;
            this.elements.inputCount.classList.toggle('warning', ratio >= 0.8 && ratio < 1);
            this.elements.inputCount.classList.toggle('danger', ratio >= 1);
        }

        if (message !== null) {
            this.setInputStatus(message, level);
            return;
        }

        if (ratio >= 1) {
            this.setInputStatus(`Input capped at ${this.maxInputChars} characters`, 'danger');
        } else if (ratio >= 0.8) {
            this.setInputStatus('Large input detected. Review before sending.', 'warning');
        } else if (this.terminalState === 'pending_confirmation') {
            this.setInputStatus('Confirmation mode: type Y to continue or N to cancel.', 'warning');
        } else if (this.terminalState === 'pending_route_confirmation') {
            this.setInputStatus('Route suggestion: type Y to execute suggested command or N to cancel.', 'warning');
        } else {
            this.setInputStatus('', 'info');
        }
    }

    /**
     * Show inline input status.
     */
    setInputStatus(text, level = 'info') {
        if (!this.elements.inputStatus) return;
        this.elements.inputStatus.textContent = text || 'Enter to send, Shift+Enter for newline';
        this.elements.inputStatus.classList.remove('warning', 'danger');
        if (level === 'warning' || level === 'danger') {
            this.elements.inputStatus.classList.add(level);
        }
    }

    /**
     * Trim input to the supported size.
     */
    normalizeInput(raw, source = 'input') {
        const value = raw || '';
        if (value.length <= this.maxInputChars) {
            return value;
        }

        const trimmed = value.slice(0, this.maxInputChars);
        const message = source === 'paste'
            ? `Pasted content was truncated to ${this.maxInputChars} characters`
            : `Input was truncated to ${this.maxInputChars} characters`;
        this.setInputStatus(message, 'warning');
        return trimmed;
    }

    /**
     * Keep large pasted content usable without breaking the input.
     */
    handlePaste(e) {
        const pastedText = e.clipboardData?.getData('text') || '';
        if (!pastedText) return;

        window.requestAnimationFrame(() => {
            const normalized = this.normalizeInput(this.elements.input.value, 'paste');
            if (normalized !== this.elements.input.value) {
                this.elements.input.value = normalized;
            }

            this.autoResizeInput();
            if (pastedText.length >= this.largePasteThreshold) {
                this.updateInputState('Large paste captured. Multi-line input enabled for review.', 'warning');
            } else {
                this.updateInputState();
            }
        });
    }

    /**
     * Only use history navigation when the caret is at a safe edge.
     */
    canNavigateHistory(direction) {
        const input = this.elements.input;
        const value = input.value || '';
        if (!value.includes('\n')) {
            return true;
        }

        const caret = input.selectionStart ?? value.length;
        if (direction < 0) {
            return caret === 0;
        }
        return caret === value.length;
    }

    /**
     * Render Mermaid diagrams after markdown conversion.
     */
    async renderRichContent(container) {
        container.querySelectorAll('pre').forEach((pre) => {
            pre.classList.add('terminal-code-block');
        });
        container.querySelectorAll(':not(pre) > code').forEach((code) => {
            code.classList.add('terminal-inline-code');
        });

        if (!window.mermaid?.render) {
            return;
        }

        const mermaidBlocks = container.querySelectorAll('pre code.language-mermaid');
        for (const block of mermaidBlocks) {
            const pre = block.closest('pre');
            if (!pre) continue;

            const source = block.textContent || '';
            const wrapper = document.createElement('div');
            wrapper.className = 'terminal-mermaid-wrap';
            wrapper.innerHTML = `
                <div class="terminal-mermaid-label">Mermaid</div>
                <div class="terminal-mermaid-diagram"></div>
            `;

            pre.replaceWith(wrapper);

            try {
                const id = `terminal-mermaid-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
                const result = await window.mermaid.render(id, source);
                wrapper.querySelector('.terminal-mermaid-diagram').innerHTML = result.svg;
            } catch (error) {
                wrapper.innerHTML = `
                    <div class="terminal-mermaid-label">Mermaid</div>
                    <pre class="terminal-code-block"><code class="language-mermaid">${this.escapeHtml(source)}</code></pre>
                    <div class="terminal-mermaid-error">Diagram render failed: ${this.escapeHtml(error?.message || 'unknown error')}</div>
                `;
            }
        }

        this.scrollToBottom();
    }

    /**
     * Scroll to bottom
     */
    scrollToBottom() {
        this.elements.body.scrollTop = this.elements.body.scrollHeight;
    }

    /**
     * Get CSRF token
     */
    getCsrfToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') return decodeURIComponent(value);
        }
        return '';
    }

    /**
     * Escape HTML
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize terminal when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.terminal = new AgomTerminal();
});
