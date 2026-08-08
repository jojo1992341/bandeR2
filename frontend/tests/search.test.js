/**
 * Test §16.1 — Recherche full-text et Dashboard enrichi
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { SearchPanel } from '../src/components/search_panel.js';
import { Dashboard } from '../src/pages/dashboard.js';
import { api } from '../src/services/api.js';

describe('§16.1 — Recherche full-text', () => {
  let container;
  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'search-container';
    document.body.appendChild(container);
    vi.clearAllMocks();
  });
  afterEach(() => {
    container.remove();
    vi.restoreAllMocks();
  });

  it('affiche les résultats de recherche avec highlight et latence', async () => {
    const mockResult = {
      query: 'banane',
      studio_id: 'studio-1',
      projects: [{ id: 'p1', title: 'Projet Banane', total_matches: 2 }],
      replicas: [
        { id: 'r1', project_id: 'p1', project_title: 'Projet Banane', text: 'Bonjour la banane', highlighted: 'Bonjour la <mark>banane</mark>', start_ms: 0, end_ms: 1000, speaker_id: null },
        { id: 'r2', project_id: 'p1', project_title: 'Projet Banane', text: 'Une autre banane', highlighted: 'Une autre <mark>banane</mark>', start_ms: 2000, end_ms: 3000, speaker_id: null },
      ],
      transcripts: [],
      total_projects: 1,
      total_replicas: 2,
      total_transcripts: 0,
      latency_ms: 42,
      engine: 'postgres',
    };
    vi.spyOn(api, 'searchStudio').mockResolvedValue(mockResult);

    const panel = new SearchPanel('search-container', 'studio-1');
    panel.mount();
    const result = await panel.search('banane');

    expect(api.searchStudio).toHaveBeenCalledWith('studio-1', 'banane', { limit: 10 });
    expect(result.total_projects).toBe(1);
    expect(result.latency_ms).toBe(42);
    expect(result.latency_ms).toBeLessThan(500);

    const latencyEl = container.querySelector('[data-testid="search-latency"]');
    expect(latencyEl).toBeTruthy();
    expect(latencyEl.textContent).toContain('42ms');
    expect(latencyEl.textContent).toContain('postgres');

    const replicas = container.querySelectorAll('[data-testid="search-replica"]');
    expect(replicas.length).toBe(2);
    expect(replicas[0].innerHTML).toContain('<mark>banane</mark>');

    const projects = container.querySelectorAll('[data-testid="search-project"]');
    expect(projects.length).toBe(1);
  });

  it('affiche un message si aucun résultat', async () => {
    vi.spyOn(api, 'searchStudio').mockResolvedValue({
      query: 'xyz', studio_id: 'studio-1', projects: [], replicas: [], transcripts: [], total_projects: 0, total_replicas: 0, total_transcripts: 0, latency_ms: 15, engine: 'sqlite'
    });
    const panel = new SearchPanel('search-container', 'studio-1');
    panel.mount();
    await panel.search('xyz');
    const resultsEl = container.querySelector('[data-testid="search-results"]');
    expect(resultsEl.textContent).toContain('Aucune');
  });

  it('respecte la latence acceptable (<500ms)', async () => {
    const mockResult = {
      query: 'test', studio_id: 'studio-1', projects: [], replicas: [], transcripts: [], total_projects: 0, total_replicas: 0, total_transcripts: 0, latency_ms: 123, engine: 'sqlite'
    };
    vi.spyOn(api, 'searchStudio').mockImplementation(async () => {
      // Simuler un délai
      await new Promise(r => setTimeout(r, 10));
      return mockResult;
    });
    const panel = new SearchPanel('search-container', 'studio-1');
    panel.mount();
    const start = performance.now();
    const result = await panel.search('test');
    const elapsed = performance.now() - start;
    expect(result.latency_ms).toBeLessThan(500);
    expect(elapsed).toBeLessThan(500);
  });
});

describe('§16.1 — Dashboard enrichi US-053', () => {
  let container;
  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'dash-enriched';
    document.body.appendChild(container);
  });
  afterEach(() => {
    container.remove();
  });

  it('affiche les indicateurs enrichis (répliques, speakers, durée, confiance, stockage)', async () => {
    const mockData = {
      studio_id: 'studio-1',
      studio_name: 'Studio Test',
      studio_plan: 'pro',
      projects: [
        {
          id: 'p1', title: 'Projet 1', status: 'En_edition', status_label: 'En édition', is_editable: true,
          updated_at: new Date().toISOString(), pipeline: null,
          stats: { replica_count: 5, speaker_count: 2, word_count: 100, transcript_segment_count: 5, avg_confidence: 0.9, total_duration_seconds: 120, storage_mb: 50, total_duration_hours: 0.03 },
          replica_count: 5, speaker_count: 2, avg_confidence: 0.9, duration_seconds: 120
        }
      ],
      indicators: {
        total_projects: 1,
        status_distribution: [{ status: 'En_edition', label: 'En édition', count: 1 }],
        volume_month: 1,
        avg_processing_seconds: 60,
        quota: { limit_minutes: 600, used_minutes: 100, remaining_minutes: 500, percent_used: 16.7 },
        total_replicas: 5,
        total_speakers: 2,
        total_duration_seconds: 120,
        total_duration_hours: 0.03,
        total_storage_mb: 50,
        total_words: 100,
        total_transcripts: 5,
        avg_confidence_global: 0.9,
        top_projects: [{ id: 'p1', title: 'Projet 1', updated_at: new Date().toISOString(), status: 'En_edition' }]
      },
      filters: [{ value: 'En_edition', label: 'En édition' }]
    };
    const dash = new Dashboard('dash-enriched', 'studio-1');
    dash.fetch = vi.fn().mockResolvedValue(mockData);
    await dash.mount();

    // Vérifier les nouveaux indicateurs
    expect(container.querySelector('[data-testid="indicator-replicas"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="indicator-replicas"]').textContent).toContain('5');
    expect(container.querySelector('[data-testid="indicator-speakers"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="indicator-duration"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="indicator-confidence"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="indicator-storage"]')).toBeTruthy();

    // Vérifier les colonnes enrichies par projet
    expect(container.querySelector('[data-testid="cell-replicas"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="cell-replicas"]').textContent).toContain('5');
    expect(container.querySelector('[data-testid="cell-speakers"]').textContent).toContain('2');
    expect(container.querySelector('[data-testid="cell-confidence"]')).toBeTruthy();
  });

  it('affiche la barre de recherche full-text', async () => {
    const mockData = {
      studio_id: 'studio-1', studio_name: 'Studio', studio_plan: 'pro',
      projects: [], indicators: { total_projects: 0, status_distribution: [], volume_month: 0, avg_processing_seconds: null, quota: { limit_minutes: 600, used_minutes: 0, remaining_minutes: 600, percent_used: 0 }, total_replicas: 0, total_speakers: 0, total_duration_seconds: 0, total_storage_mb: 0, avg_confidence_global: null, top_projects: [] }, filters: []
    };
    const dash = new Dashboard('dash-enriched', 'studio-1');
    dash.fetch = vi.fn().mockResolvedValue(mockData);
    await dash.mount();
    expect(container.querySelector('[data-testid="dash-search"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="search-input"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="search-input"]').placeholder).toContain('Rechercher');
  });
});
