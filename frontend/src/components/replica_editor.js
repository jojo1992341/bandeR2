import { store as defaultStore } from '../core/store.js';
import { api as defaultApi } from '../services/api.js';

/**
 * ReplicaEditor — éditeur de bande rythmo avec raccourcis §14.4
 * - Ctrl+Maj+S : Scinder la réplique sélectionnée au point de lecture
 * - Ctrl+Maj+F : Fusionner avec la réplique suivante
 */

export const ReplicaEditor = {
  render: () => '<div>Éditeur de réplique</div>',
};

/**
 * Gère un événement clavier pour les raccourcis d'édition.
 * Exposée pour testabilité (vitest e2e).
 * @param {KeyboardEvent} event
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 * @returns {Promise<any>|undefined} - promesse de l'action ou undefined si ignoré
 */
export function handleKeyDown(event, storeInstance = defaultStore, apiInstance = defaultApi) {
  const isCtrlShift = event.ctrlKey && event.shiftKey;
  if (!isCtrlShift) return;

  const key = (event.key || '').toLowerCase();

  // Ctrl+Maj+S : Scinder
  if (key === 's') {
    if (typeof event.preventDefault === 'function') event.preventDefault();
    const sel = storeInstance.selection;
    if (!sel) return;
    const replica = storeInstance.replicas.find((r) => r.id === sel);
    if (!replica) return;

    // Déterminer split_ms : playhead si à l'intérieur, sinon milieu
    let splitMs = storeInstance.playheadMs;
    if (typeof splitMs !== 'number' || splitMs <= replica.start_ms || splitMs >= replica.end_ms) {
      splitMs = Math.floor((replica.start_ms + replica.end_ms) / 2);
    }

    // Appel backend et mise à jour optimistic du store à la réponse
    const p = apiInstance.splitReplica(replica.id, splitMs).then((result) => {
      // La réponse attendue : { replicas: [r1, r2], split_ms }
      if (result && Array.isArray(result.replicas) && result.replicas.length === 2) {
        const idx = storeInstance.replicas.findIndex((r) => r.id === replica.id);
        if (idx >= 0) {
          // Remplacer l'original par les deux nouvelles
          const nextReplicas = [...storeInstance.replicas];
          nextReplicas.splice(idx, 1, result.replicas[0], result.replicas[1]);
          // Re-tri par order_index puis start_ms pour cohérence
          nextReplicas.sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0) || a.start_ms - b.start_ms);
          storeInstance.setReplicas(nextReplicas);
          // Sélectionner la première moitié après scission (UX)
          storeInstance.selectReplica(result.replicas[0].id);
        }
      }
      return result;
    });
    return p;
  }

  // Ctrl+Maj+F : Fusionner
  if (key === 'f') {
    if (typeof event.preventDefault === 'function') event.preventDefault();
    const sel = storeInstance.selection;
    if (!sel) return;
    // Répliques triées par order_index / start_ms (ordre d'affichage)
    const sorted = [...storeInstance.replicas].sort(
      (a, b) => (a.order_index ?? 0) - (b.order_index ?? 0) || a.start_ms - b.start_ms
    );
    const idx = sorted.findIndex((r) => r.id === sel);
    if (idx === -1 || idx >= sorted.length - 1) return;
    const next = sorted[idx + 1];
    const replicaIds = [sorted[idx].id, next.id];

    const p = apiInstance.mergeReplicas(replicaIds).then((result) => {
      if (result && result.replica) {
        const merged = result.replica;
        // Retirer les deux originales et insérer la fusionnée
        const idsToRemove = new Set(replicaIds);
        const remaining = storeInstance.replicas.filter((r) => !idsToRemove.has(r.id));
        // Insérer au bon index (celui du premier)
        const insertIdx = Math.min(
          storeInstance.replicas.findIndex((r) => r.id === replicaIds[0]),
          remaining.length
        );
        const nextReplicas = [...remaining];
        // Insérer à l'endroit de la première réplique
        const originalIdx = storeInstance.replicas.findIndex((r) => r.id === replicaIds[0]);
        if (originalIdx >= 0) {
          nextReplicas.splice(originalIdx, 0, merged);
        } else {
          nextReplicas.push(merged);
        }
        nextReplicas.sort((a, b) => (a.order_index ?? 0) - (b.order_index ?? 0) || a.start_ms - b.start_ms);
        storeInstance.setReplicas(nextReplicas);
        storeInstance.selectReplica(merged.id);
      }
      return result;
    });
    return p;
  }
}

/**
 * Initialise l'écoute des raccourcis sur le document.
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 * @returns {{destroy: () => void, handleKeyDown: Function}}
 */
export function initReplicaEditor(storeInstance = defaultStore, apiInstance = defaultApi) {
  const listener = (e) => handleKeyDown(e, storeInstance, apiInstance);
  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('keydown', listener);
  }
  return {
    handleKeyDown: listener,
    destroy() {
      if (typeof document !== 'undefined' && document.removeEventListener) {
        document.removeEventListener('keydown', listener);
      }
    },
  };
}

// Auto-init côté navigateur (pas en environnement de test où l'on veut contrôler)
if (typeof window !== 'undefined' && typeof document !== 'undefined' && window.store) {
  // Si un store global existe, on s'y attache automatiquement
  try {
    // Ne pas auto-init en mode test (vitest)
    if (!globalThis.__VITEST__ && !window.__VITEST__) {
      initReplicaEditor(defaultStore, defaultApi);
    }
  } catch (_) {
    // ignore
  }
} else if (typeof document !== 'undefined' && !globalThis.__VITEST__) {
  // Tenter auto-init même sans window.store (usage direct)
  try {
    if (typeof window !== 'undefined' && !window.__VITEST__) {
      // Attendre DOM ready pour éviter double binding en tests
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initReplicaEditor(defaultStore, defaultApi), { once: true });
      } else {
        // Ne pas auto-bind immédiatement pour laisser les tests mock document
      }
    }
  } catch (_) {}
}
