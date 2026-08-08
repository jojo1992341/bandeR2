import { store } from '../core/store.js';
store.subscribe('replicas', () => {
  const el = document.getElementById('replica-list');
  if (el) el.innerHTML = `<pre>${JSON.stringify(store.replicas, null, 2)}</pre>`;
});
store.setReplicas([
  { id: 'r-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2500, confidence_score: 0.94, speaker_id: 'spk-01' }
]);
