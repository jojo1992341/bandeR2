import { store } from '../core/store.js';
import { initReplicaEditor } from '../components/replica_editor.js';
import { api } from '../services/api.js';
import { AutoSave } from '../services/autosave.js';
import { VersionsPanel } from '../components/versions_panel.js';
import { ExportsPanel } from '../components/exports_panel.js';
import { CommentsPanel } from '../components/comments_panel.js';

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
  let container = document.getElementById('versions-panel');
  if (!container) {
    container = document.createElement('div');
    container.id = 'versions-panel';
    const app = document.getElementById('app');
    if (app) app.appendChild(container);
    else document.body.appendChild(container);
  }
  versionsPanel = new VersionsPanel('versions-panel', projectId);
  versionsPanel.mount();
  if (typeof window !== 'undefined') window.versionsPanel = versionsPanel;
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initVersionsPanel);
} else {
  initVersionsPanel();
}

// Exports PDF §A.2 — panneau d'export
let exportsPanel = null;
function initExportsPanel() {
  let container = document.getElementById('exports-panel');
  if (!container) {
    container = document.createElement('div');
    container.id = 'exports-panel';
    const app = document.getElementById('app');
    if (app) app.appendChild(container);
    else document.body.appendChild(container);
  }
  exportsPanel = new ExportsPanel('exports-panel', projectId);
  exportsPanel.mount();
  if (typeof window !== 'undefined') window.exportsPanel = exportsPanel;
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initExportsPanel);
} else {
  initExportsPanel();
}

// Panneau latéral contextuel §14.2.4 — Fil de commentaires
let commentsPanel = null;
function initCommentsPanel() {
  let container = document.getElementById('comments-panel');
  if (!container) {
    container = document.createElement('div');
    container.id = 'comments-panel';
    container.setAttribute('data-testid', 'comments-panel');
    // Créer une mise en page éditeur avec zone principale + panneau latéral
    const app = document.getElementById('app');
    if (app) {
      // Créer une structure si elle n'existe pas
      let editorLayout = document.getElementById('editor-layout');
      if (!editorLayout) {
        editorLayout = document.createElement('div');
        editorLayout.id = 'editor-layout';
        editorLayout.style.cssText = 'display:grid; grid-template-columns: 2fr 1fr; gap:1rem; margin-top:1rem;';
        // Déplacer la replica-list dans la zone principale
        const replicaList = document.getElementById('replica-list');
        const mainArea = document.createElement('div');
        mainArea.id = 'editor-main';
        if (replicaList) mainArea.appendChild(replicaList);
        const sidePanel = document.createElement('div');
        sidePanel.id = 'editor-side';
        sidePanel.appendChild(container);
        editorLayout.appendChild(mainArea);
        editorLayout.appendChild(sidePanel);
        app.appendChild(editorLayout);
      } else {
        const side = document.getElementById('editor-side') || editorLayout;
        side.appendChild(container);
      }
    } else {
      document.body.appendChild(container);
    }
  }
  commentsPanel = new CommentsPanel('comments-panel', store);
  commentsPanel.mount();
  if (typeof window !== 'undefined') window.commentsPanel = commentsPanel;
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initCommentsPanel);
} else {
  initCommentsPanel();
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
