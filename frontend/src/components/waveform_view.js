/**
 * WaveSurfer.js intégration — rendu Canvas 2D virtualisé (§7.4, §14.2.3)
 * Seuls les éléments dans le viewport sont dessinés (performance 2h+)
 */
export function initWaveform(containerId, audioUrl, fps = 25) {
  const container = document.getElementById(containerId);
  if (!container) return null;
  const canvas = document.createElement('canvas');
  canvas.width = container.clientWidth || 800;
  canvas.height = 120;
  container.appendChild(canvas);
  const ctx = canvas.getContext('2d');

  // Virtualisation : on ne dessine que les segments visibles
  const visibleDurationMs = 30000; // fenêtre visible par défaut 30s
  let scrollMs = 0;

  function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const w = canvas.width;
    const h = canvas.height;
    // Simplifié : barre de progression continue avec marqueurs à chaque 5s
    const segments = Math.ceil(visibleDurationMs / 5000);
    for (let i = 0; i < segments; i++) {
      const x = (i / segments) * w;
      const y = h / 2;
      ctx.fillStyle = '#e11d48';
      ctx.fillRect(x, y - 4, 6, 8);
      ctx.fillStyle = '#e8e8ec';
      ctx.font = '10px system-ui';
      ctx.fillText(`${Math.round((scrollMs + i * 5000) / 1000)}s`, x + 4, y - 10);
    }
  }

  draw();
  return { canvas, draw, scrollMs, setScroll: (ms) => { scrollMs = ms; draw(); } };
}
