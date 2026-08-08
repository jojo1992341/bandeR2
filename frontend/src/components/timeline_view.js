/**
 * TimelineView (§17.3) — Rendu Canvas virtualisé pour la timeline de bande rythmo.
 *
 * Principes de performance §17.3 :
 * - Rendu Canvas virtualisé : seuls les éléments (répliques, marqueurs temporels) visibles
 *   dans le viewport temporel [scrollMs, scrollMs + visibleDurationMs / zoomLevel] sont dessinés.
 * - Recalcul incrémental au scroll/zoom uniquement : un flag de dirty-check (isDirty) et
 *   la mise en cache des frontières du viewport (lastScrollMs, lastZoomLevel, lastViewportWidth)
 *   évitent tout recalcul ou redessin superflu si la vue n'a pas changé.
 * - Debounce/throttle pour les interactions haute fréquence.
 */

export class TimelineView {
  /**
   * @param {string} containerId - ID de l'élément conteneur dans le DOM
   * @param {object} options
   */
  constructor(containerId, options = {}) {
    this.containerId = containerId;
    this.fps = options.fps || 25;
    this.visibleDurationMs = options.visibleDurationMs || 30000;
    this.scrollMs = options.scrollMs || 0;
    this.zoomLevel = options.zoomLevel || 1.0;
    this.replicas = [];

    this.isDirty = true;
    this.lastScrollMs = null;
    this.lastZoomLevel = null;
    this.lastWidth = 0;
    this.lastHeight = 0;
    this.lastVisibleCount = 0;
    this.lastRenderDurationMs = 0;

    this.canvas = null;
    this.ctx = null;
  }

  /**
   * Charge un jeu de données de répliques (ex. vidéo de 20 min).
   * @param {Array} replicas
   */
  setReplicas(replicas = []) {
    this.replicas = replicas.slice().sort((a, b) => a.start_ms - b.start_ms);
    this.isDirty = true;
    this.draw();
  }

  /**
   * Action au défilement temporel (scroll). Recalcule uniquement au changement.
   * @param {number} ms
   */
  scroll(ms) {
    const clamped = Math.max(0, ms);
    if (this.scrollMs === clamped && !this.isDirty) return false;
    this.scrollMs = clamped;
    this.isDirty = true;
    this.draw();
    return true;
  }

  /**
   * Action au zoom sur la timeline. Recalcule uniquement au changement.
   * @param {number} level
   */
  zoom(level) {
    const clamped = Math.max(0.2, Math.min(5.0, level));
    if (this.zoomLevel === clamped && !this.isDirty) return false;
    this.zoomLevel = clamped;
    this.isDirty = true;
    this.draw();
    return true;
  }

  invalidate() {
    this.isDirty = true;
    this.draw();
  }

  /**
   * Filtre virtualisé : retourne uniquement les répliques visibles dans le viewport [startMs, endMs].
   * @param {number} startMs
   * @param {number} endMs
   * @returns {Array}
   */
  getVisibleReplicas(startMs, endMs) {
    const visible = [];
    for (let i = 0; i < this.replicas.length; i++) {
      const r = this.replicas[i];
      if (r.end_ms < startMs) continue;
      if (r.start_ms > endMs) break;
      visible.push(r);
    }
    return visible;
  }

  mount() {
    const container = document.getElementById(this.containerId);
    if (!container) return;

    this.canvas = document.createElement('canvas');
    this.canvas.width = container.clientWidth || 800;
    this.canvas.height = container.clientHeight || 160;
    container.innerHTML = '';
    container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.isDirty = true;
    this.draw();
  }

  /**
   * Rendu Canvas virtualisé avec recalcul incrémental (§17.3).
   * @returns {object} Métriques de rendu (visibleCount, durationMs, skipped)
   */
  draw() {
    if (
      !this.isDirty &&
      this.lastScrollMs === this.scrollMs &&
      this.lastZoomLevel === this.zoomLevel
    ) {
      if (this.canvas) {
        if (
          this.canvas.width === this.lastWidth &&
          this.canvas.height === this.lastHeight
        ) {
          return {
            skipped: true,
            visibleCount: this.lastVisibleCount,
            durationMs: 0,
          };
        }
      } else {
        return { skipped: true, visibleCount: 0, durationMs: 0 };
      }
    }

    const t0 =
      typeof performance !== 'undefined' && performance.now
        ? performance.now()
        : Date.now();

    const w = this.canvas ? this.canvas.width : 800;
    const h = this.canvas ? this.canvas.height : 160;

    const windowDurationMs = this.visibleDurationMs / this.zoomLevel;
    const startMs = this.scrollMs;
    const endMs = startMs + windowDurationMs;

    const visibleReplicas = this.getVisibleReplicas(startMs, endMs);
    this.lastVisibleCount = visibleReplicas.length;

    if (this.ctx) {
      const ctx = this.ctx;
      ctx.clearRect(0, 0, w, h);

      ctx.fillStyle = '#1e1e2e';
      ctx.fillRect(0, 0, w, h);

      ctx.strokeStyle = '#3f3f46';
      ctx.lineWidth = 1;
      const stepMs = Math.max(1000, 5000 / this.zoomLevel);
      const firstTickMs = Math.floor(startMs / stepMs) * stepMs;
      for (let tick = firstTickMs; tick <= endMs; tick += stepMs) {
        const x = ((tick - startMs) / windowDurationMs) * w;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, 15);
        ctx.stroke();

        ctx.fillStyle = '#9ca3af';
        ctx.font = '10px system-ui, -apple-system, sans-serif';
        const secs = Math.round(tick / 1000);
        ctx.fillText(`${secs}s`, x + 2, 12);
      }

      for (let i = 0; i < visibleReplicas.length; i++) {
        const r = visibleReplicas[i];
        const rx0 = Math.max(0, ((r.start_ms - startMs) / windowDurationMs) * w);
        const rx1 = Math.min(w, ((r.end_ms - startMs) / windowDurationMs) * w);
        const rw = Math.max(4, rx1 - rx0);
        const ry = 30 + (i % 3) * 36;
        const rh = 30;

        ctx.fillStyle = '#e11d48';
        ctx.fillRect(rx0, ry, rw, rh);
        ctx.strokeStyle = '#ffa8c5';
        ctx.strokeRect(rx0, ry, rw, rh);

        if (rw > 20 && r.text) {
          ctx.fillStyle = '#ffffff';
          ctx.font = '12px system-ui, -apple-system, sans-serif';
          ctx.save();
          ctx.beginPath();
          ctx.rect(rx0 + 4, ry, rw - 8, rh);
          ctx.clip();
          ctx.fillText(r.text, rx0 + 6, ry + 19);
          ctx.restore();
        }
      }

      ctx.strokeStyle = '#facc15';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, 0);
      ctx.lineTo(0, h);
      ctx.stroke();
    }

    const t1 =
      typeof performance !== 'undefined' && performance.now
        ? performance.now()
        : Date.now();

    this.lastScrollMs = this.scrollMs;
    this.lastZoomLevel = this.zoomLevel;
    this.lastWidth = w;
    this.lastHeight = h;
    this.isDirty = false;
    this.lastRenderDurationMs = t1 - t0;

    return {
      skipped: false,
      visibleCount: this.lastVisibleCount,
      durationMs: this.lastRenderDurationMs,
      totalReplicas: this.replicas.length,
    };
  }
}
