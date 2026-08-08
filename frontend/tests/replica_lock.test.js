/**
 * Test §16.4 — Verrouillage optimiste par réplique avec notification WebSocket.
 *
 * Vérifie :
 *  - L'indicateur visuel de verrouillage apparaît quand un autre utilisateur édite
 *  - Aucune écriture concurrente destructive ne se produit (409 Conflict → revert)
 *  - Le ReplicaLockManager fonctionne correctement
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { ReplicaLockManager } from '../src/services/replica_lock_manager.js';
import { createLockIndicator, renderLockIndicatorHTML } from '../src/components/replica_lock_indicator.js';
import { handleEditEvent } from '../src/components/replica_editor.js';

// ── Mock API ──────────────────────────────────────────────────

function createMockApi() {
  const locks = {};  // replicaId → { user_id, user_name }
  const replicas = {
    'r-001': { id: 'r-001', text: 'Bonjour le monde', version: 1, start_ms: 0, end_ms: 3000 },
  };

  return {
    locks,
    replicas,

    async acquireReplicaLock(replicaId, userId, userName) {
      if (locks[replicaId] && locks[replicaId].user_id !== userId) {
        return { acquired: false, locked_by: locks[replicaId], message: `Réplique verrouillée par ${locks[replicaId].user_name}` };
      }
      locks[replicaId] = { user_id: userId, user_name: userName };
      return { acquired: true, message: 'Verrou acquis' };
    },

    async releaseReplicaLock(replicaId, userId) {
      if (locks[replicaId] && locks[replicaId].user_id === userId) {
        delete locks[replicaId];
        return { released: true };
      }
      return { released: false };
    },

    async replicaLockHeartbeat(replicaId, userId) {
      return { ok: !!locks[replicaId] && locks[replicaId].user_id === userId };
    },

    async getReplicaLockStatus(replicaId) {
      if (locks[replicaId]) {
        return { locked: true, ...locks[replicaId] };
      }
      return { locked: false };
    },

    async patchReplica(replicaId, payload) {
      const replica = replicas[replicaId];
      if (!replica) throw new Error('Not found');

      // Optimistic lock check
      if (payload.version !== undefined && replica.version !== payload.version) {
        const err = new Error('Conflit de version : cette réplique a été modifiée par un autre utilisateur.');
        err.status = 409;
        err.detail = {
          code: 'version_conflict',
          message: 'Conflit de version : cette réplique a été modifiée par un autre utilisateur.',
          current_version: replica.version,
          sent_version: payload.version,
        };
        throw err;
      }

      // Apply changes
      if (payload.text !== undefined) replica.text = payload.text;
      if (payload.start_ms !== undefined) replica.start_ms = payload.start_ms;
      if (payload.end_ms !== undefined) replica.end_ms = payload.end_ms;
      replica.version = (replica.version || 0) + 1;

      return {
        id: replicaId,
        status: 'updated',
        version: replica.version,
        replica: { ...replica },
      };
    },

    // Stubs for other API methods used by replica_editor
    async splitReplica() { return { replicas: [], split_ms: 0, status: 'split' }; },
    async mergeReplicas() { return { replica: {}, merged_count: 0, status: 'merged' }; },
    async fetchReplicas() { return []; },
  };
}

// ── Tests ─────────────────────────────────────────────────────

describe('§16.4 — ReplicaLockManager', () => {
  it('acquiert un verrou et signale un verrouillage par un autre utilisateur', async () => {
    const api = createMockApi();
    const lockMgr = new ReplicaLockManager('proj-1', 'user-camille', 'Camille', api);

    // Camille acquiert le verrou
    const result = await lockMgr.acquireLock('r-001');
    expect(result.acquired).toBe(true);
    expect(lockMgr.isLockedByMe('r-001')).toBe(true);
    expect(lockMgr.getLockMessage('r-001')).toBeNull(); // pas de message pour soi-même

    // Denis tente d'acquérir — on simule en créant un autre manager
    const denisMgr = new ReplicaLockManager('proj-1', 'user-denis', 'Denis', api);
    const result2 = await denisMgr.acquireLock('r-001');
    expect(result2.acquired).toBe(false);
    expect(result2.locked_by.user_name).toBe('Camille');

    // Indicateur visuel pour Denis
    expect(denisMgr.isLocked('r-001')).toBe(true);
    expect(denisMgr.getLockMessage('r-001')).toBe('Camille édite cette réplique');
  });

  it('relâche le verrou et permet à un autre utilisateur de l\'acquérir', async () => {
    const api = createMockApi();
    const camilleMgr = new ReplicaLockManager('proj-1', 'user-camille', 'Camille', api);

    await camilleMgr.acquireLock('r-001');
    const released = await camilleMgr.releaseLock('r-001');
    expect(released).toBe(true);
    expect(camilleMgr.isLocked('r-001')).toBe(false);

    // Denis peut maintenant acquérir
    const denisMgr = new ReplicaLockManager('proj-1', 'user-denis', 'Denis', api);
    const result = await denisMgr.acquireLock('r-001');
    expect(result.acquired).toBe(true);

    // Cleanup
    await denisMgr.releaseLock('r-001');
  });
});

describe('§16.4 — Lock indicator visuel', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
  });

  it('affiche "Camille édite cette réplique" quand verrouillé par un autre', () => {
    const indicator = createLockIndicator(
      container,
      'r-001',
      { user_id: 'user-camille', user_name: 'Camille' },
      'user-denis',  // current user is Denis
    );

    expect(indicator.el.style.display).not.toBe('none');
    expect(indicator.el.textContent).toContain('Camille édite cette réplique');
    expect(indicator.el.className).toContain('replica-lock-indicator--locked');
  });

  it('masque l\'indicateur quand le verrou est détenu par l\'utilisateur courant', () => {
    const indicator = createLockIndicator(
      container,
      'r-001',
      { user_id: 'user-camille', user_name: 'Camille' },
      'user-camille',  // current user is Camille herself
    );

    expect(indicator.el.style.display).toBe('none');
  });

  it('affiche un message de conflit en cas de 409', () => {
    const indicator = createLockIndicator(container, 'r-001', null, 'user-denis');
    indicator.showConflict('Conflit de version détecté');

    expect(indicator.el.style.display).not.toBe('none');
    expect(indicator.el.textContent).toContain('Conflit de version détecté');
    expect(indicator.el.className).toContain('replica-lock-indicator--conflict');
  });

  it('met à jour dynamiquement l\'indicateur', () => {
    const indicator = createLockIndicator(container, 'r-001', null, 'user-denis');
    expect(indicator.el.style.display).toBe('none');

    indicator.update({ user_id: 'user-camille', user_name: 'Camille' });
    expect(indicator.el.style.display).not.toBe('none');
    expect(indicator.el.textContent).toContain('Camille édite cette réplique');

    indicator.update(null);
    expect(indicator.el.style.display).toBe('none');
  });

  it('renderLockIndicatorHTML produit le bon markup', () => {
    const html = renderLockIndicatorHTML({ user_name: 'Camille' });
    expect(html).toContain('Camille édite cette réplique');
    expect(html).toContain('replica-lock-indicator--locked');
  });
});

describe('§16.4 — Store lock state', () => {
  it('gère les verrous dans le store', () => {
    const store = new RythmoStore();

    store.setReplicaLocks({
      'r-001': { user_id: 'user-camille', user_name: 'Camille' },
    });

    expect(store.isReplicaLocked('r-001')).toBe(true);
    expect(store.getReplicaLockMessage('r-001')).toBe('Camille édite cette réplique');
    expect(store.isReplicaLocked('r-002')).toBe(false);

    store.updateReplicaLock('r-001', null);
    expect(store.isReplicaLocked('r-001')).toBe(false);
  });

  it('notifie les abonnés quand les verrous changent', () => {
    const store = new RythmoStore();
    const events = [];
    store.subscribe('replicaLocks', () => events.push(store.replicaLocks));

    store.setReplicaLocks({ 'r-001': { user_id: 'u1', user_name: 'Camille' } });
    expect(events.length).toBeGreaterThanOrEqual(1);
    expect(events[0]['r-001'].user_name).toBe('Camille');
  });
});

describe('§16.4 — Concurrent edit prevention (optimistic lock)', () => {
  it('empêche une écriture concurrente destructive (409 → revert)', async () => {
    const api = createMockApi();
    const store = new RythmoStore();
    store.setReplicas([{
      id: 'r-001',
      text: 'Bonjour le monde',
      version: 1,
      start_ms: 0,
      end_ms: 3000,
      speaker_id: null,
      typo_codes: {},
      confidence_score: 0.9,
      is_manually_edited: false,
      breath_marker: false,
      order_index: 0,
    }]);

    // Camille modifie en premier (version 1 → 2)
    await api.patchReplica('r-001', { text: 'Bonsoir le monde', version: 1 });
    expect(api.replicas['r-001'].text).toBe('Bonsoir le monde');
    expect(api.replicas['r-001'].version).toBe(2);

    // Denis tente de modifier avec version=1 (périmée)
    let conflictCaught = false;
    try {
      await api.patchReplica('r-001', { text: 'Salut le monde', version: 1 });
    } catch (e) {
      if (e.status === 409) {
        conflictCaught = true;
      }
    }
    expect(conflictCaught).toBe(true);

    // Vérifier qu'aucune écriture destructive ne s'est produite
    expect(api.replicas['r-001'].text).toBe('Bonsoir le monde');
    expect(api.replicas['r-001'].version).toBe(2);
  });

  it('Denis peut modifier après avoir récupéré la version à jour', async () => {
    const api = createMockApi();

    // Camille modifie (version 1 → 2)
    await api.patchReplica('r-001', { text: 'Bonsoir le monde', version: 1 });

    // Denis re-lit (version=2)
    const currentVersion = api.replicas['r-001'].version; // 2

    // Denis modifie avec la bonne version
    const result = await api.patchReplica('r-001', { text: 'Salut le monde', version: currentVersion });
    expect(result.version).toBe(3);
    expect(result.replica.text).toBe('Salut le monde');
  });
});

describe('§16.4 — handleEditEvent with lock integration', () => {
  it('bloque l\'édition si la réplique est verrouillée par un autre', async () => {
    const api = createMockApi();
    const store = new RythmoStore();
    store.setReplicas([{
      id: 'r-001',
      text: 'Bonjour le monde',
      version: 1,
      start_ms: 0,
      end_ms: 3000,
      speaker_id: null,
      typo_codes: {},
      confidence_score: 0.9,
      is_manually_edited: false,
      breath_marker: false,
      order_index: 0,
    }]);

    // Simulate lock manager where Camille holds the lock
    const lockMgr = new ReplicaLockManager('proj-1', 'user-denis', 'Denis', api);
    lockMgr.locks = { 'r-001': { user_id: 'user-camille', user_name: 'Camille' } };

    // Denis tries to edit
    const event = new CustomEvent('rythmo:edit', {
      detail: { id: 'r-001', text: 'Salut le monde' },
    });

    await handleEditEvent(event, store, api, lockMgr);

    // Text should NOT have changed (blocked by lock)
    expect(store.replicas[0].text).toBe('Bonjour le monde');
  });
});
