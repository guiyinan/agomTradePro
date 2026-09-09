import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
test('Classic policy row actions follow the event state in the all-events tab', () => {
    const body = { innerHTML: '' };
    const context = vm.createContext({ document: { addEventListener() {}, getElementById() { return body; } }, console });
    vm.runInContext(readFileSync(new URL('../../../static/js/policy-workbench.js', import.meta.url), 'utf8'), context);
    for (const [audit_status, gate_effective, expected] of [['pending_review', false, 'approve'], ['manual_approved', true, 'rollback'], ['rejected', false, 'detail']]) {
        context.items = [{ id: 1, title: 'Policy', event_date: '2026-09-08', event_type: 'policy', level: 'P1', gate_level: 'L1', ai_confidence: null, audit_status, gate_effective }];
        vm.runInContext('renderEvents(items)', context);
        assert.ok(body.innerHTML.includes(`data-action="${expected}"`));
        if (expected !== 'approve') assert.ok(!body.innerHTML.includes('data-action="approve"'));
        if (expected !== 'rollback') assert.ok(!body.innerHTML.includes('data-action="rollback"'));
    }
});
