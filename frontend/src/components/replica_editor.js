import { store as defaultStore } from '../core/store.js';
import { api as defaultApi } from '../services/api.js';

/**
 * ReplicaEditor — éditeur de bande rythmo avec raccourcis §14.4 et codes typo §2.4
 * - Ctrl+Maj+S : Scinder la réplique sélectionnée au point de lecture
 * - Ctrl+Maj+F : Fusionner avec la réplique suivante
 * - Clic droit : menu codes typographiques (crochets, italique, majuscules, parenthèses)
 * - Undo/Redo : Ctrl+Z / Ctrl+Y (pattern Command §7.3)
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
  const key = (event.key || '').toLowerCase();
  const isCtrl = event.ctrlKey || event.metaKey; // meta pour Mac

  // §14.4 — Undo / Redo (Ctrl+Z / Ctrl+Y, et Ctrl+Maj+Z comme alias redo)
  if (isCtrl && !event.shiftKey && key === 'z') {
    if (typeof event.preventDefault === 'function') event.preventDefault();
    storeInstance.undo();
    return 'undo';
  }
  if (isCtrl && (key === 'y' || (event.shiftKey && key === 'z'))) {
    if (typeof event.preventDefault === 'function') event.preventDefault();
    storeInstance.redo();
    return 'redo';
  }

  const isCtrlShift = event.ctrlKey && event.shiftKey;
  if (!isCtrlShift) return;

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

  // Mise à jour via Command pattern (undoable) — remplacement exact du typo_codes
  const updatedTypo = result?.typo_codes || result?.replica?.typo_codes || newTypo;
  const current = storeInstance.replicas.find((r) => r.id === replicaId)?.typo_codes || {};
  if (JSON.stringify(current) !== JSON.stringify(updatedTypo)) {
    // Utiliser updateReplica pour un remplacement exact (pas de merge) afin que la suppression d'un code soit bien prise en compte
    // Si le store a une méthode updateTypoCodes qui merge, on l'évite ici pour ne pas réintroduire l'ancien code supprimé
    if (typeof storeInstance.updateReplica === 'function') {
      storeInstance.updateReplica(replicaId, { typo_codes: updatedTypo });
    } else if (typeof storeInstance.updateTypoCodes === 'function') {
      // Fallback : forcer le remplacement en vidant d'abord
      storeInstance.updateTypoCodes(replicaId, updatedTypo);
    }
  }

  // Mettre à jour l'élément DOM rythmo-track si présent
  if (typeof document !== 'undefined') {
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
  if (typeof event.preventDefault === 'function') event.preventDefault();
  return applyTypoCode(replicaId, code, value, storeInstance, apiInstance);
}

/**
 * Gère l'édition de texte via double-clic §7.3 + §16.4 (optimistic lock)
 */
export async function handleEditEvent(event, storeInstance = defaultStore, apiInstance = defaultApi, lockManager = null) {
  const detail = event.detail || {};
  const id = detail.id;
  const text = detail.text;
  if (!id || text === undefined) return;
  // Command pattern + API
  const replica = storeInstance.replicas.find(r => r.id === id);
  if (!replica) return;
  if (replica.text === text) return;

  // §16.4 — Acquire lock before editing
  if (lockManager && !lockManager.isLockedByMe(id)) {
    if (lockManager.isLocked(id)) {
      // Someone else is editing — show indicator, don't proceed
      const msg = lockManager.getLockMessage(id);
      if (typeof console !== 'undefined') console.warn('Replica locked:', msg);
      storeInstance.updateReplicaLock(id, lockManager.getLockInfo(id));
      return;
    }
    try {
      const result = await lockManager.acquireLock(id);
      if (!result.acquired) {
        // Lock denied — another user holds it
        storeInstance.updateReplicaLock(id, result.locked_by);
        return;
      }
    } catch (e) {
      // Lock acquisition failed — proceed without lock (graceful degradation)
      if (typeof console !== 'undefined') console.warn('Lock acquisition failed, proceeding without lock:', e);
    }
  }

  // Optimistic via store (undoable)
  storeInstance.editReplicaText(id, text);
  // Persist with version for optimistic lock §16.4
  try {
    const payload = { text };
    if (replica.version !== undefined) payload.version = replica.version;
    await apiInstance.patchReplica(id, payload);
  } catch (e) {
    // §16.4 — Handle 409 Conflict (version mismatch)
    if (e.status === 409) {
      // Revert optimistic update
      storeInstance.undo();
      // Emit event for UI to show conflict message
      if (typeof document !== 'undefined') {
        document.dispatchEvent(new CustomEvent('replica:conflict', {
          detail: { replicaId: id, message: e.message, serverDetail: e.detail },
        }));
      }
      return;
    }
    // Other errors — keep optimistic (could revert but we keep it)
    console.error('patch text failed', e);
  }
  // Mettre à jour DOM
  if (typeof document !== 'undefined') {
    document.querySelectorAll('rythmo-track').forEach(el => {
      if (el.getAttribute('replica-id') === id) el.setAttribute('text', text);
    });
  }
}

/**
 * Gère le redimensionnement / déplacement via handles §7.3
 */
export async function handleResizeEvent(event, storeInstance = defaultStore, apiInstance = defaultApi) {
  const detail = event.detail || {};
  const id = detail.id;
  const startMs = detail.startMs;
  const endMs = detail.endMs;
  if (!id || (startMs === undefined && endMs === undefined)) return;
  const replica = storeInstance.replicas.find(r => r.id === id);
  if (!replica) return;
  const oldStart = replica.start_ms;
  const oldEnd = replica.end_ms;
  const newStart = startMs !== undefined ? startMs : oldStart;
  const newEnd = endMs !== undefined ? endMs : oldEnd;
  if (oldStart === newStart && oldEnd === newEnd) return;

  const isMove = (newStart !== oldStart && newEnd !== oldEnd && (newEnd - newStart) === (oldEnd - oldStart));
  const isResize = !isMove;

  // Déterminer si c'est un déplacement (delta) ou redimensionnement
  if (isMove) {
    storeInstance.moveReplica(id, newStart, newEnd);
  } else {
    storeInstance.resizeReplica(id, newStart, newEnd);
  }

  try {
    await apiInstance.patchReplica(id, { start_ms: newStart, end_ms: newEnd });
  } catch (e) {
    console.error('patch resize/move failed', e);
  }

  if (typeof document !== 'undefined') {
    document.querySelectorAll('rythmo-track').forEach(el => {
      if (el.getAttribute('replica-id') === id) {
        if (newStart !== undefined) el.setAttribute('start-ms', String(newStart));
        if (newEnd !== undefined) el.setAttribute('end-ms', String(newEnd));
      }
    });
  }
}

/**
 * Initialise l'écoute des raccourcis et des événements métier sur le document.
 * @param {import('../core/store.js').RythmoStore} storeInstance
 * @param {typeof defaultApi} apiInstance
 * @returns {{destroy: () => void, handleKeyDown: Function, handleTypo: Function}}
 */
export function initReplicaEditor(storeInstance = defaultStore, apiInstance = defaultApi) {
  const keyListener = (e) => handleKeyDown(e, storeInstance, apiInstance);
  const typoListener = (e) => handleTypoEvent(e, storeInstance, apiInstance);
  const editListener = (e) => handleEditEvent(e, storeInstance, apiInstance);
  const resizeListener = (e) => handleResizeEvent(e, storeInstance, apiInstance);

  if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('keydown', keyListener);
    document.addEventListener('rythmo:typo', typoListener);
    document.addEventListener('rythmo:edit', editListener);
    document.addEventListener('rythmo:resize', resizeListener);
  }
  // Flag pour que rythmo_track sache que l'éditeur est responsable de la sync
  if (typeof window !== 'undefined') window._rythmoEditorInitialized = true;

  // Sync DOM tracks lors d'undo/redo ou de toute mutation du store
  let syncHandler = null;
  if (typeof storeInstance.subscribe === 'function') {
    syncHandler = () => {
      if (typeof document === 'undefined') return;
      storeInstance.replicas.forEach((r) => {
        document.querySelectorAll(`rythmo-track[replica-id="${r.id}"]`).forEach((el) => {
          if (el.getAttribute('text') !== r.text) el.setAttribute('text', r.text);
          if (el.getAttribute('start-ms') !== String(r.start_ms)) el.setAttribute('start-ms', String(r.start_ms));
          if (el.getAttribute('end-ms') !== String(r.end_ms)) el.setAttribute('end-ms', String(r.end_ms));
          const currentTypo = el.getAttribute('typo-codes') || '{}';
          const newTypo = JSON.stringify(r.typo_codes || {});
          if (currentTypo !== newTypo) el.setAttribute('typo-codes', newTypo);
        });
      });
    };
    storeInstance.subscribe('replicas', syncHandler);
  }

  return {
    handleKeyDown: keyListener,
    handleTypo: typoListener,
    handleEdit: editListener,
    handleResize: resizeListener,
    destroy() {
      if (typeof document !== 'undefined' && document.removeEventListener) {
        document.removeEventListener('keydown', keyListener);
        document.removeEventListener('rythmo:typo', typoListener);
        document.removeEventListener('rythmo:edit', editListener);
        document.removeEventListener('rythmo:resize', resizeListener);
      }
      if (syncHandler && typeof storeInstance.removeEventListener === 'function') {
        // EventTarget n'a pas de unsubscribe simple, on laisse le handler
      }
      if (typeof window !== 'undefined') window._rythmoEditorInitialized = false;
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
