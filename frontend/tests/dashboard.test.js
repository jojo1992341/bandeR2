/**
 * Test §14.2.1 — Dashboard : vue synthétique des projets.
 *
 * Vérifie :
 *  - L'affichage des indicateurs studio (total, volume, quota)
 *  - Le filtrage par statut
 *  - Le rendu du projet avec statut et pipeline
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { Dashboard } from '../src/pages/dashboard.js';

// ── Mock data ────────────────────────────────────────────────

function getMockData() {
  return {
    studio_id: 'studio-001',
    studio_name: 'Studio RythmoAI',
    studio_plan: 'pro',
    projects: [
      {
        id: 'p-01', title: 'Projet Alpha', status: 'Cree',
        status_label: 'Créé', is_editable: false,
        updated_at: new Date(Date.now() - 5 * 86400000).toISOString(),
        pipeline: null,
      },
      {
        id: 'p-02', title: 'Projet Beta', status: 'En_traitement',
        status_label: 'En traitement', is_editable: false,
        updated_at: new Date(Date.now() - 4 * 86400000).toISOString(),
        pipeline: { status: 'processing', progress_percent: 64, current_step: 'diarisation' },
      },
      {
        id: 'p-03', title: 'Projet Gamma', status: 'En_edition',
        status_label: 'En édition', is_editable: true,
        updated_at: new Date(Date.now() - 3 * 86400000).toISOString(),
        pipeline: { status: 'completed', progress_percent: 100, current_step: 'export' },
      },
      {
        id: 'p-04', title: 'Projet Delta', status: 'En_relecture',
        status_label: 'En relecture', is_editable: true,
        updated_at: new Date(Date.now() - 2 * 86400000).toISOString(),
        pipeline: { status: 'completed', progress_percent: 100, current_step: 'export' },
      },
      {
        id: 'p-05', title: 'Projet Epsilon', status: 'Valide',
        status_label: 'Validé', is_editable: false,
        updated_at: new Date(Date.now() - 86400000).toISOString(),
        pipeline: { status: 'completed', progress_percent: 100, current_step: 'export' },
      },
      {
        id: 'p-06', title: 'Projet Zeta', status: 'Archive',
        status_label: 'Archivé', is_editable: false,
        updated_at: new Date(Date.now() - 0.5 * 86400000).toISOString(),
        pipeline: null,
      },
    ],
    indicators: {
      total_projects: 6,
      status_distribution: [
        { status: 'Cree', label: 'Créé', count: 1 },
        { status: 'En_traitement', label: 'En traitement', count: 1 },
        { status: 'En_edition', label: 'En édition', count: 1 },
        { status: 'En_relecture', label: 'En relecture', count: 1 },
        { status: 'Valide', label: 'Validé', count: 1 },
        { status: 'Archive', label: 'Archivé', count: 1 },
      ],
      volume_month: 4,
      avg_processing_seconds: 420,
      quota: {
        limit_minutes: 600,
        used_minutes: 180,
        remaining_minutes: 420,
        percent_used: 30.0,
      },
    },
    filters: [
      { value: 'Cree', label: 'Créé' },
      { value: 'En_traitement', label: 'En traitement' },
      { value: 'Pret_pour_edition', label: 'Prêt pour édition' },
      { value: 'En_edition', label: 'En édition' },
      { value: 'En_relecture', label: 'En relecture' },
      { value: 'Valide', label: 'Validé' },
      { value: 'Exporte_Livre', label: 'Exporté / Livré' },
      { value: 'Archive', label: 'Archivé' },
    ],
  };
}

// ── Tests ─────────────────────────────────────────────────────

describe('§14.2.1 — Dashboard indicators', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'dash-container';
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
  });

  it('renders all 6 projects with correct statuses', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const rows = container.querySelectorAll('[data-testid="project-row"]');
    expect(rows.length).toBe(6);

    const statuses = Array.from(rows).map(r => r.dataset.status);
    expect(statuses).toContain('Cree');
    expect(statuses).toContain('En_traitement');
    expect(statuses).toContain('En_edition');
    expect(statuses).toContain('En_relecture');
    expect(statuses).toContain('Valide');
    expect(statuses).toContain('Archive');
  });

  it('renders total projects indicator', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const indicator = container.querySelector('[data-testid="indicator-total"]');
    expect(indicator).toBeTruthy();
    expect(indicator.textContent).toContain('6');
  });

  it('renders volume indicator', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const indicator = container.querySelector('[data-testid="indicator-volume"]');
    expect(indicator).toBeTruthy();
    expect(indicator.textContent).toContain('4');
  });

  it('renders quota indicator with remaining minutes', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const indicator = container.querySelector('[data-testid="indicator-quota"]');
    expect(indicator).toBeTruthy();
    expect(indicator.textContent).toContain('420min');
  });

  it('renders quota usage bar', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const bar = container.querySelector('[data-testid="quota-bar"]');
    expect(bar).toBeTruthy();
    const fill = bar.querySelector('.dash-quota-fill');
    expect(fill).toBeTruthy();
    expect(fill.style.width).toBe('30%');
  });
});

describe('§14.2.1 — Dashboard filters', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'dash-container';
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
  });

  it('renders filter buttons for all statuses', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const filterArea = container.querySelector('[data-testid="dash-filters"]');
    expect(filterArea).toBeTruthy();

    // "Tous" button + 8 status filters
    const buttons = filterArea.querySelectorAll('.dash-filter-btn');
    expect(buttons.length).toBe(9);
  });

  it('clicking a filter reduces visible projects', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    // Initially all 6 visible
    let rows = container.querySelectorAll('[data-testid="project-row"]');
    expect(rows.length).toBe(6);

    // Click "Valide" filter
    const valideBtn = container.querySelector('[data-testid="filter-Valide"]');
    expect(valideBtn).toBeTruthy();
    valideBtn.click();

    // Now only 1 project visible
    rows = container.querySelectorAll('[data-testid="project-row"]');
    expect(rows.length).toBe(1);
    expect(rows[0].dataset.status).toBe('Valide');
  });

  it('clicking "Tous" resets the filter', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    // Filter first
    const valideBtn = container.querySelector('[data-testid="filter-Valide"]');
    valideBtn.click();
    let rows = container.querySelectorAll('[data-testid="project-row"]');
    expect(rows.length).toBe(1);

    // Click "Tous"
    const tousBtn = container.querySelector('.dash-filter-btn[data-status=""]');
    tousBtn.click();

    rows = container.querySelectorAll('[data-testid="project-row"]');
    expect(rows.length).toBe(6);
  });
});

describe('§14.2.1 — Dashboard pipeline progress', () => {
  let container;

  beforeEach(() => {
    container = document.createElement('div');
    container.id = 'dash-container';
    document.body.appendChild(container);
  });

  afterEach(() => {
    container.remove();
  });

  it('shows pipeline progress bar for in-progress project', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const rows = container.querySelectorAll('[data-testid="project-row"]');
    const processingRow = Array.from(rows).find(r => r.dataset.status === 'En_traitement');
    expect(processingRow).toBeTruthy();

    const bar = processingRow.querySelector('.dash-pipeline-bar');
    expect(bar).toBeTruthy();
  });

  it('shows "Terminé" for completed pipeline', async () => {
    const data = getMockData();
    const dash = new Dashboard('dash-container', 'studio-001');
    dash.fetch = vi.fn().mockResolvedValue(data);
    await dash.mount();

    const rows = container.querySelectorAll('[data-testid="project-row"]');
    const editionRow = Array.from(rows).find(r => r.dataset.status === 'En_edition');
    expect(editionRow).toBeTruthy();

    const done = editionRow.querySelector('.dash-pipeline-done');
    expect(done).toBeTruthy();
    expect(done.textContent).toContain('Terminé');
  });
});
