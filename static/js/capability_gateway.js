(() => {
    const panel = document.getElementById('semanticGovernancePanel');
    if (!panel) return;

    const rowsContainer = document.getElementById('semanticCorrectionRows');
    const resultElement = document.getElementById('semanticGovernanceResult');

    function csrfToken() {
        const name = 'csrftoken=';
        const cookie = document.cookie
            .split(';')
            .map((part) => part.trim())
            .find((part) => part.startsWith(name));
        return cookie ? decodeURIComponent(cookie.slice(name.length)) : '';
    }

    function correctionRow() {
        const template = rowsContainer.querySelector('.semantic-correction-row');
        const row = template.cloneNode(true);
        row.querySelectorAll('input').forEach((input) => {
            input.value = '';
        });
        row.querySelector('[data-field="action"]').value = 'set';
        return row;
    }

    function collectPayload() {
        const corrections = Array.from(
            rowsContainer.querySelectorAll('.semantic-correction-row')
        ).map((row) => {
            const action = row.querySelector('[data-field="action"]').value;
            const correction = {
                capability_key: row.querySelector('[data-field="capability_key"]').value.trim(),
                action,
            };
            const semanticKey = row.querySelector('[data-field="semantic_key"]').value.trim();
            if (action === 'set') correction.semantic_key = semanticKey;
            return correction;
        }).filter((item) => item.capability_key);

        return {
            idempotency_key: document.getElementById('semanticIdempotencyKey').value.trim(),
            reason: document.getElementById('semanticReason').value.trim(),
            corrections,
        };
    }

    async function submit(url) {
        resultElement.textContent = '处理中…';
        const response = await fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken(),
            },
            body: JSON.stringify(collectPayload()),
        });
        const payload = await response.json();
        resultElement.textContent = JSON.stringify(payload, null, 2);
        if (!response.ok) {
            throw new Error(payload.error || '语义治理请求失败');
        }
        return payload;
    }

    document.getElementById('addSemanticCorrection').addEventListener('click', () => {
        rowsContainer.appendChild(correctionRow());
    });

    rowsContainer.addEventListener('click', (event) => {
        const button = event.target.closest('[data-remove-correction]');
        if (!button) return;
        const rows = rowsContainer.querySelectorAll('.semantic-correction-row');
        if (rows.length === 1) {
            rows[0].querySelectorAll('input').forEach((input) => {
                input.value = '';
            });
            return;
        }
        button.closest('.semantic-correction-row').remove();
    });

    rowsContainer.addEventListener('change', (event) => {
        if (event.target.dataset.field !== 'action') return;
        const semanticInput = event.target
            .closest('.semantic-correction-row')
            .querySelector('[data-field="semantic_key"]');
        semanticInput.disabled = event.target.value === 'remove';
        if (semanticInput.disabled) semanticInput.value = '';
    });

    document.getElementById('previewSemanticCorrections').addEventListener('click', async () => {
        try {
            await submit(panel.dataset.previewUrl);
        } catch (error) {
            if (window.showToast) window.showToast(error.message, 'warning');
        }
    });

    document.getElementById('applySemanticCorrections').addEventListener('click', async () => {
        if (!window.confirm('确认应用已预览的语义键修正？')) return;
        try {
            await submit(panel.dataset.applyUrl);
            if (window.showToast) window.showToast('语义键修正已应用', 'success');
        } catch (error) {
            if (window.showToast) window.showToast(error.message, 'warning');
        }
    });
})();
