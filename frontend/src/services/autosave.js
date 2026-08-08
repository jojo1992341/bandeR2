/**
 * Auto-save différée §17.3 + cache IndexedDB §7.4
 * - Sauvegarde différée toutes les 3 secondes d'inactivité (debounce 3000ms)
 * - Indicateur syncStatus : idle / saving / saved / error
 * - Cache local IndexedDB pour tolérer micro-coupures réseau
 */

import { debounce } from '../utils/debounce.js';
import { idbCache } from './idb.js';

export class AutoSave {
  /**
   * @param {import('../core/store.js').RythmoStore} store
   * @param {import('./api.js').api} api
   * @param {object} options
   * @param {string} [options.projectId] - identifiant projet pour clé IDB
   * @param {number} [options.debounceMs=3000] - délai inactivité avant save
   * @param {number} [options.savedResetMs=1500] - délai avant retour idle après saved
   * @param {function} [options.onSave] - callback custom pour tests (au lieu de api.patchReplica)
   */
  constructor(store, api, options = {}) {
    this.store = store;
    this.api = api;
    this.projectId = options.projectId || null;
    this.debounceMs = options.debounceMs ?? 3000;
    this.savedResetMs = options.savedResetMs ?? 1500;
    this.onSave = options.onSave || null;

    this.isStarted = false;
    this.saveTimer = null;
    this.savedTimer = null;
    this.pending = false;
    this.retryTimer = null;

    // Debounced flush
    this.debouncedFlush = debounce(() => this.flush(), this.debounceMs);

    this._onReplicasChange = this._onReplicasChange.bind(this);
    this._onOnline = this._onOnline.bind(this);
    this._onOffline = this._onOffline.bind(this);
    this._onProjectChange = this._onProjectChange.bind(this);
  }

  async start() {
    if (this.isStarted) return;
    this.isStarted = true;

    // Restaurer depuis IDB si disponible (tolérance après reload)
    try {
      const cached = await idbCache.load(this.projectId);
      if (cached && Array.isArray(cached.replicas) && cached.replicas.length > 0) {
        // Ne pas écraser si le store a déjà des données plus récentes ? On restaure seulement si store vide
        if (!this.store.replicas || this.store.replicas.length === 0) {
          this.store.setReplicas(cached.replicas);
        }
      }
    } catch {}

    this.store.subscribe('replicas', this._onReplicasChange);
    this.store.subscribe('project', this._onProjectChange);
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this._onOnline);
      window.addEventListener('offline', this._onOffline);
    }
    // Mettre à jour le projectId si déjà présent
    this._onProjectChange();
    // État initial
    this.store.setSyncStatus('idle');
  }

  stop() {
    if (!this.isStarted) return;
    this.isStarted = false;
    if (typeof this.store.removeEventListener === 'function') {
      // EventTarget n'a pas de off simple pour notre subscribe custom, on laisse
    }
    // On ne peut pas unsubscribe facilement avec EventTarget, on garde le listener mais on ignore via flag
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this._onOnline);
      window.removeEventListener('offline', this._onOffline);
    }
    if (this.saveTimer) clearTimeout(this.saveTimer);
    if (this.savedTimer) clearTimeout(this.savedTimer);
    if (this.retryTimer) clearTimeout(this.retryTimer);
  }

  _onReplicasChange() {
    if (!this.isStarted) return;
    // Sauvegarde immédiate en IDB pour ne rien perdre (micro-coupure)
    this._saveToIDB().catch(() => {});

    // Si on était en erreur, on reste en error jusqu'au prochain flush réussi
    // Sinon on reste idle jusqu'au flush
    if (this.store.syncStatus !== 'saving' && this.store.syncStatus !== 'error') {
      this.store.setSyncStatus('idle');
    }
    this.pending = true;
    // Relancer le debounce
    this.debouncedFlush();
  }

  async _saveToIDB() {
    try {
      await idbCache.save(this.projectId, this.store.replicas);
    } catch {}
  }

  async flush() {
    if (!this.pending) return;
    // Ne pas flusher si offline et qu'on veut attendre le retour réseau
    // Mais on a déjà sauvé en IDB, donc on peut tenter quand même et gérer l'erreur
    this.pending = false;
    this.store.setSyncStatus('saving');
    try {
      await this._saveToServer();
      // Succès
      this.store.setSyncStatus('saved');
      // Optionnel : nettoyer le cache après succès ? On garde pour reload, mais on peut aussi le laisser
      // On programme un retour à idle
      if (this.savedTimer) clearTimeout(this.savedTimer);
      this.savedTimer = setTimeout(() => {
        if (this.store.syncStatus === 'saved') {
          this.store.setSyncStatus('idle');
        }
      }, this.savedResetMs);
    } catch (e) {
      // Échec réseau → error, on garde en IDB pour retry
      this.store.setSyncStatus('error');
      // On re-marque comme pending pour retry
      this.pending = true;
      // Retry automatique quand online ou après délai
      if (this.retryTimer) clearTimeout(this.retryTimer);
      this.retryTimer = setTimeout(() => {
        if (this.pending) this.flush();
      }, 5000);
    }
  }

  async _saveToServer() {
    if (this.onSave) {
      // Pour tests : callback custom
      return this.onSave(this.store.replicas);
    }
    // Par défaut : patch chaque réplique via API
    // On utilise api.patchReplica si dispo, sinon fetch direct
    const replicas = this.store.replicas;
    if (!replicas || replicas.length === 0) return;

    // Si on a un projectId, on pourrait faire un bulk, mais on fait individuel
    const promises = replicas.map((r) => {
      if (this.api && typeof this.api.patchReplica === 'function') {
        return this.api.patchReplica(r.id, {
          text: r.text,
          start_ms: r.start_ms,
          end_ms: r.end_ms,
          typo_codes: r.typo_codes,
          speaker_id: r.speaker_id,
        }).catch((e) => {
          // Propager l'erreur pour que flush la considère comme échec
          throw e;
        });
      } else {
        // Fallback fetch
        return fetch(`/api/v1/replicas/${r.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: r.text,
            start_ms: r.start_ms,
            end_ms: r.end_ms,
            typo_codes: r.typo_codes,
          }),
        }).then((res) => {
          if (!res.ok) throw new Error(`save failed ${res.status}`);
          return res.json();
        });
      }
    });

    // On attend toutes les sauvegardes ; si une échoue, on considère l'ensemble en erreur
    const results = await Promise.allSettled(promises);
    const hasError = results.some((r) => r.status === 'rejected');
    if (hasError) {
      const firstError = results.find((r) => r.status === 'rejected');
      throw firstError.reason;
    }
    return results;
  }

  _onOnline() {
    // Réseau revenu → retry immédiat si on était en erreur/pending
    if (this.store.syncStatus === 'error' || this.pending) {
      // Petit délai pour laisser le réseau se stabiliser
      setTimeout(() => this.flush(), 200);
    }
  }

  _onProjectChange() {
    const newId = this.store.currentProject?.id || null;
    if (newId && newId !== this.projectId) {
      this.projectId = newId;
    }
  }

  _onOffline() {
    // Passage offline → on reste en error si on avait des pending, mais on garde IDB
    if (this.pending) {
      this.store.setSyncStatus('error');
    }
  }

  // Méthodes utilitaires pour tests

  /** Force un flush immédiat (sans debounce) */
  async forceFlush() {
    // Annuler le debounce en attente
    // Le debounce original n'expose pas cancel, on fait juste un flush direct
    return this.flush();
  }

  /** Vérifie si des données sont en cache IDB */
  async hasCached() {
    return idbCache.has(this.projectId);
  }

  async clearCache() {
    return idbCache.clear(this.projectId);
  }
}

// Helper pour créer et démarrer rapidement
export function createAutoSave(store, api, options) {
  const auto = new AutoSave(store, api, options);
  auto.start();
  return auto;
}
