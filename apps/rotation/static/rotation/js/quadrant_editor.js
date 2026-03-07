/**
 * RotationQuadrantEditor
 *
 * Manages a multi-tab UI for configuring per-regime asset allocations.
 * All weights are stored internally as decimals (0.0 – 1.0);
 * the UI displays percentages (0 – 100).
 *
 * External dependencies: none (vanilla JS only).
 */

class RotationQuadrantEditor {
  /**
   * @param {string} containerId  - id of the host <div>
   * @param {string} hiddenInputId - id of the hidden <input> that holds the JSON payload
   */
  constructor(containerId = 'quadrantEditorContainer', hiddenInputId = 'regimeAllocationsJson') {
    this._containerId = containerId;
    this._hiddenInputId = hiddenInputId;

    /** @type {Array<{key: string, label: string}>} */
    this._regimes = [];

    /** @type {Array<{code: string, name: string}>} */
    this._assets = [];

    /** @type {Array<{key: string, label: string, allocations: Object<string,number>}>} */
    this._templates = [];

    /**
     * Internal state: { [regimeKey]: { [assetCode]: decimal (0.0-1.0) } }
     * @type {Object<string, Object<string, number>>}
     */
    this._data = {};

    this._activeRegime = null;
    this._initialized = false;
    this._pendingJsonStr = null;
    this._pendingTemplateKey = null;
    this._readyPromise = null;
  }

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------

  /** Initialise: fetch data from API, render UI. */
  async init() {
    if (this._readyPromise) {
      return this._readyPromise;
    }

    this._readyPromise = (async () => {
      try {
        await Promise.all([
          this._fetchRegimes(),
          this._fetchAssets(),
          this._fetchTemplates(),
        ]);
        this._initState();
        this._render();
        this._initialized = true;

        if (this._pendingJsonStr !== null) {
          const pendingJson = this._pendingJsonStr;
          this._pendingJsonStr = null;
          this.loadFromJson(pendingJson);
        }

        if (this._pendingTemplateKey !== null) {
          const pendingTemplateKey = this._pendingTemplateKey;
          this._pendingTemplateKey = null;
          this.applyTemplate(pendingTemplateKey);
        }
      } catch (err) {
        console.error('[RotationQuadrantEditor] init failed:', err);
        this._renderError(err.message);
        throw err;
      }
    })();

    try {
      await this._readyPromise;
    } catch (_) {
      // Error already rendered above.
    }
  }

  ready() {
    return this._readyPromise || Promise.resolve();
  }

  /**
   * Apply a named template to all quadrants.
   * @param {string} templateKey
   */
  applyTemplate(templateKey) {
    if (!this._initialized) {
      this._pendingTemplateKey = templateKey;
      return;
    }
    const tpl = this._templates.find(t => t.key === templateKey);
    if (!tpl) {
      console.warn('[RotationQuadrantEditor] unknown template key:', templateKey);
      return;
    }
    // tpl.allocations is expected to be { regimeKey: { assetCode: decimal } }
    this._regimes.forEach(regime => {
      const regimeAlloc = tpl.allocations[regime.key] || {};
      this._assets.forEach(asset => {
        const val = regimeAlloc[asset.code];
        this._data[regime.key][asset.code] = (typeof val === 'number') ? val : 0;
      });
    });
    this._refreshActiveTab();
    this._syncHiddenInput();
  }

  /**
   * Initialise the editor from a previously-saved JSON string.
   * @param {string} jsonStr  JSON representing { regimeKey: { assetCode: decimal } }
   */
  loadFromJson(jsonStr) {
    if (!jsonStr) return;
    if (!this._initialized) {
      this._pendingJsonStr = jsonStr;
      return;
    }
    let parsed;
    try {
      parsed = JSON.parse(jsonStr);
    } catch (e) {
      console.error('[RotationQuadrantEditor] loadFromJson: invalid JSON', e);
      return;
    }
    this._regimes.forEach(regime => {
      const regimeAlloc = parsed[regime.key] || {};
      this._assets.forEach(asset => {
        const val = regimeAlloc[asset.code];
        this._data[regime.key][asset.code] = (typeof val === 'number') ? val : 0;
      });
    });
    this._refreshActiveTab();
    this._syncHiddenInput();
  }

  /**
   * Return current allocation data.
   * @returns {Object<string, Object<string, number>>} { regimeKey: { assetCode: decimal } }
   */
  getData() {
    // Deep-clone to protect internal state
    return JSON.parse(JSON.stringify(this._data));
  }

  // ---------------------------------------------------------------------------
  // Private – API fetching
  // ---------------------------------------------------------------------------

  async _fetchRegimes() {
    const resp = await fetch('/api/rotation/regimes/');
    if (!resp.ok) throw new Error(`Regimes API error ${resp.status}`);
    const json = await resp.json();
    // Support both { results: [...] } (DRF pagination) and plain array
    const list = Array.isArray(json) ? json : (json.results || []);
    this._regimes = list.map(item => {
      if (typeof item === 'string') {
        return { key: item, label: item };
      }
      const key = item.key || item.id || item.name || String(item.pk);
      return {
        key: key,
        label: item.label || item.name || key,
      };
    });
  }

  async _fetchAssets() {
    const resp = await fetch('/api/rotation/asset-classes/?is_active=true');
    if (!resp.ok) throw new Error(`Asset classes API error ${resp.status}`);
    const json = await resp.json();
    const list = Array.isArray(json) ? json : (json.results || []);
    this._assets = list.map(item => ({
      code: item.code || item.id || String(item.pk),
      name: item.name || item.code,
    }));
  }

  async _fetchTemplates() {
    const resp = await fetch('/api/rotation/templates/');
    if (!resp.ok) throw new Error(`Templates API error ${resp.status}`);
    const json = await resp.json();
    const list = Array.isArray(json) ? json : (json.results || []);
    this._templates = list.map(item => ({
      key: item.key || item.id || String(item.pk),
      label: item.label || item.name || item.key,
      allocations: item.allocations || item.regime_allocations || {},
    }));
  }

  // ---------------------------------------------------------------------------
  // Private – state
  // ---------------------------------------------------------------------------

  _initState() {
    this._regimes.forEach(regime => {
      if (!this._data[regime.key]) {
        this._data[regime.key] = {};
      }
      this._assets.forEach(asset => {
        if (typeof this._data[regime.key][asset.code] !== 'number') {
          this._data[regime.key][asset.code] = 0;
        }
      });
    });
    if (this._regimes.length > 0 && !this._activeRegime) {
      this._activeRegime = this._regimes[0].key;
    }
  }

  // ---------------------------------------------------------------------------
  // Private – rendering
  // ---------------------------------------------------------------------------

  _container() {
    return document.getElementById(this._containerId);
  }

  _render() {
    const container = this._container();
    if (!container) return;

    container.innerHTML = '';
    container.classList.add('qe-editor');

    // Template toolbar (only if templates exist)
    if (this._templates.length > 0) {
      container.appendChild(this._buildTemplateBar());
    }

    // Tab bar
    container.appendChild(this._buildTabBar());

    // Tab panels
    const panelWrapper = document.createElement('div');
    panelWrapper.className = 'qe-panels';
    this._regimes.forEach(regime => {
      panelWrapper.appendChild(this._buildPanel(regime));
    });
    container.appendChild(panelWrapper);

    this._updateTabVisibility();
  }

  _buildTemplateBar() {
    const bar = document.createElement('div');
    bar.className = 'qe-template-bar';

    const label = document.createElement('span');
    label.className = 'qe-template-label';
    label.textContent = '快速模板：';
    bar.appendChild(label);

    this._templates.forEach(tpl => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'qe-template-btn';
      btn.textContent = tpl.label;
      btn.addEventListener('click', () => this.applyTemplate(tpl.key));
      bar.appendChild(btn);
    });

    return bar;
  }

  _buildTabBar() {
    const tabBar = document.createElement('div');
    tabBar.className = 'qe-tab-bar';

    this._regimes.forEach(regime => {
      const tab = document.createElement('button');
      tab.type = 'button';
      tab.className = 'qe-tab';
      tab.dataset.regimeKey = regime.key;
      tab.textContent = regime.label;
      tab.addEventListener('click', () => this._switchTab(regime.key));
      tabBar.appendChild(tab);
    });

    return tabBar;
  }

  _buildPanel(regime) {
    const panel = document.createElement('div');
    panel.className = 'qe-panel';
    panel.dataset.regimeKey = regime.key;

    // Asset rows
    const assetList = document.createElement('div');
    assetList.className = 'qe-asset-list';

    this._assets.forEach(asset => {
      assetList.appendChild(this._buildAssetRow(regime.key, asset));
    });

    panel.appendChild(assetList);

    // Weight summary bar
    panel.appendChild(this._buildSummaryBar(regime.key));

    return panel;
  }

  _buildAssetRow(regimeKey, asset) {
    const row = document.createElement('div');
    row.className = 'qe-asset-row';
    row.dataset.regimeKey = regimeKey;
    row.dataset.assetCode = asset.code;

    // Label
    const label = document.createElement('label');
    label.className = 'qe-asset-label';
    label.textContent = asset.name;
    label.title = asset.code;
    row.appendChild(label);

    // Slider
    const slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'qe-slider';
    slider.min = 0;
    slider.max = 100;
    slider.step = 1;
    slider.value = this._toPercent(this._data[regimeKey][asset.code]);
    row.appendChild(slider);

    // Number input
    const numInput = document.createElement('input');
    numInput.type = 'number';
    numInput.className = 'qe-num-input';
    numInput.min = 0;
    numInput.max = 100;
    numInput.step = 1;
    numInput.value = this._toPercent(this._data[regimeKey][asset.code]);
    row.appendChild(numInput);

    // Percent sign
    const pct = document.createElement('span');
    pct.className = 'qe-pct-sign';
    pct.textContent = '%';
    row.appendChild(pct);

    // Bidirectional binding
    slider.addEventListener('input', () => {
      const v = this._clamp(parseInt(slider.value, 10), 0, 100);
      numInput.value = v;
      this._setWeight(regimeKey, asset.code, v);
    });

    numInput.addEventListener('input', () => {
      const raw = parseFloat(numInput.value);
      const v = isNaN(raw) ? 0 : this._clamp(Math.round(raw), 0, 100);
      slider.value = v;
      this._setWeight(regimeKey, asset.code, v);
    });

    numInput.addEventListener('blur', () => {
      // Normalise display on blur
      numInput.value = this._toPercent(this._data[regimeKey][asset.code]);
    });

    return row;
  }

  _buildSummaryBar(regimeKey) {
    const bar = document.createElement('div');
    bar.className = 'qe-summary-bar';
    bar.dataset.regimeKey = regimeKey;
    // Content filled by _updateSummaryBar
    this._updateSummaryBar(regimeKey, bar);
    return bar;
  }

  // ---------------------------------------------------------------------------
  // Private – interaction helpers
  // ---------------------------------------------------------------------------

  _switchTab(regimeKey) {
    this._activeRegime = regimeKey;
    this._updateTabVisibility();
  }

  _updateTabVisibility() {
    const container = this._container();
    if (!container) return;

    // Tabs
    container.querySelectorAll('.qe-tab').forEach(tab => {
      const isActive = tab.dataset.regimeKey === this._activeRegime;
      tab.classList.toggle('qe-tab--active', isActive);
    });

    // Panels
    container.querySelectorAll('.qe-panel').forEach(panel => {
      const isActive = panel.dataset.regimeKey === this._activeRegime;
      panel.classList.toggle('qe-panel--visible', isActive);
    });
  }

  _setWeight(regimeKey, assetCode, percentValue) {
    this._data[regimeKey][assetCode] = percentValue / 100;
    this._updateSummaryBarInDom(regimeKey);
    this._syncHiddenInput();
  }

  _refreshActiveTab() {
    const container = this._container();
    if (!container) return;

    this._regimes.forEach(regime => {
      this._assets.forEach(asset => {
        const row = container.querySelector(
          `.qe-asset-row[data-regime-key="${regime.key}"][data-asset-code="${asset.code}"]`
        );
        if (!row) return;
        const pct = this._toPercent(this._data[regime.key][asset.code]);
        const slider = row.querySelector('.qe-slider');
        const numInput = row.querySelector('.qe-num-input');
        if (slider) slider.value = pct;
        if (numInput) numInput.value = pct;
      });
      this._updateSummaryBarInDom(regime.key);
    });
  }

  _updateSummaryBarInDom(regimeKey) {
    const container = this._container();
    if (!container) return;
    const bar = container.querySelector(`.qe-summary-bar[data-regime-key="${regimeKey}"]`);
    if (bar) this._updateSummaryBar(regimeKey, bar);
  }

  _updateSummaryBar(regimeKey, barEl) {
    const total = this._sumPercent(regimeKey);
    const isValid = Math.abs(total - 100) < 0.01;
    barEl.classList.toggle('qe-summary--valid', isValid);
    barEl.classList.toggle('qe-summary--invalid', !isValid);
    barEl.textContent = isValid
      ? `✓ 总计：100%`
      : `✗ 总计：${total.toFixed(1)}%（应为 100%）`;
  }

  _syncHiddenInput() {
    const el = document.getElementById(this._hiddenInputId);
    if (el) el.value = JSON.stringify(this._data);
  }

  // ---------------------------------------------------------------------------
  // Private – utilities
  // ---------------------------------------------------------------------------

  /** Convert decimal to integer percentage. */
  _toPercent(decimal) {
    return Math.round((decimal || 0) * 100);
  }

  /** Sum weights for a regime as integer percentage. */
  _sumPercent(regimeKey) {
    const alloc = this._data[regimeKey] || {};
    return Object.values(alloc).reduce((acc, v) => acc + (v || 0) * 100, 0);
  }

  _clamp(value, min, max) {
    return Math.min(Math.max(value, min), max);
  }

  _renderError(message) {
    const container = this._container();
    if (!container) return;
    container.innerHTML = `<div class="qe-error">初始化失败：${message}</div>`;
  }
}
