import { store } from '../core/store.js';
import { initReplicaEditor } from '../components/replica_editor.js';
import { api } from '../services/api.js';
import { AutoSave } from '../services/autosave.js';
import { VersionsPanel } from '../components/versions_panel.js';

// Initialiser les raccourcis d'édition §14.4 (Ctrl+Maj+S / Ctrl+Maj+F) + undo/redo
initReplicaEditor(store, api);

// Auto-save différée §17.3 + cache IndexedDB §7.4
const autosave = new AutoSave(store, api, {
  debounceMs: 3000,
  savedResetMs: 1500,
  projectId: store.currentProject?.id || 'default',
});
autosave.start();

// Versions §16.1 — panneau d'historisation
const projectId = store.currentProject?.id || '00000000-0000-0000-0000-000000000001';
let versionsPanel = null;
function initVersionsPanel() {
  // Créer conteneur s'il n'existe pas
  let container = document.getElementById('versions-panel');
  if (!container) {
    container = document.createElement('div');
    container.id = 'versions-panel';
    // Insérer après replica-list
    const app = document.getElementById('app');
    if (app) app.appendChild(container);
    else document.body.appendChild(container);
  }
  versionsPanel = new VersionsPanel('versions-panel', projectId);
  versionsPanel.mount();
  // Exposer pour tests e2e
  if (typeof window !== 'undefined') window.versionsPanel = versionsPanel;
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initVersionsPanel);
} else {
  initVersionsPanel();
}

// Exposer pour debug / tests e2e
if (typeof window !== 'undefined') {
  window.store = store;
  window.autosave = autosave;
  window.api = api;
}

// Indicateur syncStatus idle/saving/saved/error (§17.3)
function updateSyncIndicator(status) {
  let el = document.getElementById('sync-status');
  if (!el) {
    el = document.createElement('div');
    el.id = 'sync-status';
    el.setAttribute('data-testid', 'sync-status');
    el.style.cssText = 'position:fixed;top:0.5rem;right:0.5rem;padding:0.25rem 0.5rem;border-radius:4px;font-size:0.75rem;background:#1a1c2e;color:#e8e8ec;border:1px solid #3f3f46;z-index:9999;';
    document.body.appendChild(el);
  }
  const labels = {
    idle: '—',
    saving: 'Enregistrement…',
    saved: '✓ Enregistré',
    error: '⚠ Hors ligne – en cache',
  };
  el.textContent = labels[status] || status;
  el.setAttribute('data-status', status);
  if (status === 'saving') el.style.borderColor = '#3b82f6';
  else if (status === 'saved') el.style.borderColor = '#22c55e';
  else if (status === 'error') el.style.borderColor = '#ef4444';
  else el.style.borderColor = '#3f3f46';
}

store.subscribe('syncStatus', (e) => {
  updateSyncIndicator(e.detail.syncStatus);
});
updateSyncIndicator(store.syncStatus);

store.subscribe('replicas', () => {
  const el = document.getElementById('replica-list');
  if (el) el.innerHTML = `<pre>${JSON.stringify(store.replicas, null, 2)}</pre>`;
});
// Projet fictif par défaut pour la démo / tests
store.setProject({ id: projectId, title: 'Projet Démo', studio_id: '00000000-0000-0000-0000-000000000002' });
store.setReplicas([
  { id: 'r-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2500, confidence_score: 0.94, speaker_id: 'spk-01' }
]);
