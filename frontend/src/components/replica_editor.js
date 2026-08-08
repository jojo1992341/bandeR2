import { store as defaultStore } from '../core/store.js';
import { api as defaultApi } from '../services/api.js';

/**
 * ReplicaEditor — éditeur de bande rythmo avec raccourcis §14.4 et codes typo §2.4
 * - Ctrl+Maj+S : Scinder la réplique sélectionnée au point de lecture
 * - Ctrl+Maj+F : Fusionner avec la réplique suivante
 * - Clic droit : menu codes typographiques (crochets, italique, majuscules, parenthèses)
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
 * Applique un code typographique via clic droit §2.4
 * @param {string} replicaId
 * @param {string} code - crochets|italique|majuscules|parentheses (alias acceptés)
 * @param {boolean} value - active/désactive
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 * @returns {Promise<any>}
 */
export async function applyTypoCode(replicaId, code, value, storeInstance = defaultStore, apiInstance = defaultApi) {
  const replica = storeInstance.replicas.find((r) => r.id === replicaId);
  if (!replica) throw new Error(`Réplique ${replicaId} non trouvée dans le store`);

  // Normaliser le code (comme backend)
  const canonicalMap = {
    brackets: 'crochets', bracket_in: 'crochets', bracket_out: 'crochets',
    crochets: 'crochets',
    italic: 'italique', italique: 'italique', voix_off: 'italique', off: 'italique',
    uppercase: 'majuscules', majuscules: 'majuscules', cri: 'majuscules', caps: 'majuscules',
    parentheses: 'parentheses', parentheses_jeu: 'parentheses', indication_jeu: 'parentheses', jeu: 'parentheses',
  };
  const canon = canonicalMap[code.toLowerCase()] || code.toLowerCase();

  // Construire le nouveau typo_codes en merge
  const existing = replica.typo_codes || {};
  const newTypo = { ...existing };
  if (value) {
    newTypo[canon] = true;
  } else {
    delete newTypo[canon];
  }

  // Appel API PATCH
  const result = await apiInstance.patchReplica(replicaId, { typo_codes: newTypo });

  // Mise à jour optimistic du store (utilise la réponse si disponible, sinon newTypo)
  const updatedTypo = result?.typo_codes || result?.replica?.typo_codes || newTypo;
  storeInstance.updateReplica(replicaId, { typo_codes: updatedTypo });

  // Mettre à jour l'élément DOM rythmo-track si présent
  if (typeof document !== 'undefined') {
    const trackEl = document.querySelector(`rythmo-track[replica-id="${replicaId}"]`);
    if (trackEl) {
      trackEl.setAttribute('typo-codes', JSON.stringify(updatedTypo));
    }
    // Aussi mettre à jour tous les tracks correspondants (shadow DOM)
    document.querySelectorAll('rythmo-track').forEach((el) => {
      if (el.getAttribute('replica-id') === replicaId) {
        el.setAttribute('typo-codes', JSON.stringify(updatedTypo));
      }
    });
  }

  return result;
}

/**
 * Gère l'événement custom `rythmo:typo` émis par rythmo-track lors d'un clic droit
 * @param {CustomEvent} event - detail: {id, code, value, typoCodes}
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 */
export function handleTypoEvent(event, storeInstance = defaultStore, apiInstance = defaultApi) {
  const detail = event.detail || {};
  const replicaId = detail.id;
  const code = detail.code;
  const value = detail.value !== undefined ? detail.value : true;
  if (!replicaId || !code) return;
  // Empêcher la propagation si déjà géré
  if (typeof event.preventDefault === 'function') event.preventDefault();
  return applyTypoCode(replicaId, code, value, storeInstance, apiInstance);
}

/**
 * Initialise l'écoute des raccourcis et des événements typo sur le document.
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 * @returns {{destroy: () => void, handleKeyDown: Function, handleTypo: Function}}
 */
export function initReplicaEditor(storeInstance = defaultStore, apiInstance = defaultApi) {
  const keyListener = (e) => handleKeyDown(e, storeInstance, apiInstance);
  const typoListener = (e) => handleTypoEvent(e, storeInstance, apiInstance);

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('keydown', keyListener);
    document.addEventListener('rythmo:typo', typoListener);
  }
  return {
    handleKeyDown: keyListener,
    handleTypo: typoListener,
    destroy() {
      if (typeof document !== 'undefined' && document.removeEventListener) {
        document.removeEventListener('keydown', keyListener);
        document.removeEventListener('rythmo:typo', typoListener);
      }
    },
  };
}

// Auto-init côté navigateur (pas en environnement de test où l'on veut contrôler)
if (typeof window !== 'undefined' && typeof document !== 'undefined' && window.store) {
  try {
    if (!globalThis.__VITEST__ && !window.__VITEST__) {
      initReplicaEditor(defaultStore, defaultApi);
    }
  } catch (_) {}
} else if (typeof document !== 'undefined' && !globalThis.__VITEST__) {
  try {
    if (typeof window !== 'undefined' && !window.__VITEST__) {
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => initReplicaEditor(defaultStore, defaultApi), { once: true });
      }
    }
  } catch (_) {}
}
