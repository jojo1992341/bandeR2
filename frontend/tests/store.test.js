import { describe, it, expect } from 'vitest';
import { RythmoStore } from '../src/core/store.js';

describe('Store §7.3', () => {
  it('notifie abonnés lors d\'une mutation de replicas', () => {
    const store = new RythmoStore();
    const events = [];
    store.subscribe('replicas', (e) => events.push(e.detail.replicas));
    store.setReplicas([{ id: 'r-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, speaker_id: 'spk-01', confidence_score: 0.92 }]);
    expect(events.length).toBeGreaterThanOrEqual(1);
    expect(events[0][0].id).toBe('r-01');
  });
});
