import { describe, it, expect, beforeEach } from 'vitest';
import { TimelineView } from '../src/components/timeline_view.js';

describe('TimelineView §17.3 Performance (recalcul incrémental au scroll/zoom uniquement)', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="timeline-container"></div>';
  });

  it('ne dessine que les répliques visibles dans le viewport virtuel (vidéo de 20 min)', () => {
    const timeline = new TimelineView('timeline-container', {
      visibleDurationMs: 30000,
    });
    // Génération de 600 répliques de 2 secondes sur 20 minutes (1 200 000 ms)
    const replicas = [];
    for (let i = 0; i < 600; i++) {
      const start = i * 2000;
      replicas.push({
        id: `rep-${i}`,
        start_ms: start,
        end_ms: start + 1800,
        text: `Réplique #${i} du projet`,
      });
    }
    timeline.setReplicas(replicas);

    const metrics = timeline.draw();
    expect(metrics.skipped).toBe(false);
    expect(metrics.totalReplicas).toBe(600);
    // Dans 30 secondes [0, 30000], seules ~15 répliques sont visibles et dessinées
    expect(metrics.visibleCount).toBeLessThan(30);
    expect(metrics.visibleCount).toBeGreaterThan(0);
  });

  it('évite tout recalcul ou redessin si ni scroll ni zoom ne changent', () => {
    const timeline = new TimelineView('timeline-container');
    timeline.setReplicas([
      { id: '1', start_ms: 0, end_ms: 1000, text: 'Test 1' },
      { id: '2', start_ms: 2000, end_ms: 3000, text: 'Test 2' },
    ]);

    // Premier dessin initial
    const m1 = timeline.draw();
    expect(m1.skipped).toBe(false);

    // Deuxième dessin immédiat sans changement -> ignoré (recalcul incrémental)
    const m2 = timeline.draw();
    expect(m2.skipped).toBe(true);
    expect(m2.durationMs).toBe(0);

    // Changement de scroll -> provoque un recalcul incrémental
    const didScroll = timeline.scroll(5000);
    expect(didScroll).toBe(true);
    expect(timeline.isDirty).toBe(false);

    // Re-scroll à la même position -> aucun recalcul
    const didScrollAgain = timeline.scroll(5000);
    expect(didScrollAgain).toBe(false);
  });

  it("affiche les événements de silence classifiés comme points d'appui visuels (§8.2.4, §9.2)", () => {
    const timeline = new TimelineView('timeline-container');
    const silences = [
      { id: 's-1', event_type: 'respiration_audible', start_ms: 1000, end_ms: 1250 },
      { id: 's-2', event_type: 'pause_syntaxique', start_ms: 3000, end_ms: 3450 },
      { id: 's-3', event_type: 'hesitation', start_ms: 5000, end_ms: 5150 },
      { id: 's-4', event_type: 'coupe_technique', start_ms: 8000, end_ms: 8400 },
    ];
    timeline.setSilenceEvents(silences);
    expect(timeline.silences.length).toBe(4);
    const m = timeline.draw();
    expect(m.skipped).toBe(false);
  });
});
