import { store } from '../core/store.js';
import { initReplicaEditor } from '../components/replica_editor.js';
import { api } from '../services/api.js';

// Initialiser les raccourcis d'édition §14.4 (Ctrl+Maj+S / Ctrl+Maj+F)
initReplicaEditor(store, api);

store.subscribe('replicas', () => {
  const el = document.getElementById('replica-list');
  if (el) el.innerHTML = `<pre>${JSON.stringify(store.replicas, null, 2)}</pre>`;
});
store.setReplicas([
  { id: 'r-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2500, confidence_score: 0.94, speaker_id: 'spk-01' }
]);

// Exposer store pour debugging et tests manuels
if (typeof window !== 'undefined') window.store = store;
