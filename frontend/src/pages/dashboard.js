/**
 * Dashboard §14.2.1 — Vue synthétique des projets du studio.
 *
 * Affiche :
 *  - Indicateurs studio (temps moyen, volume, quota)
 *  - Liste des projets avec statut, avancement pipeline, dernière modification
 *  - Filtres par statut
 */

import { api } from '../services/api.js';

/** Status label map for display */
const STATUS_LABELS = {
  Cree: 'Créé',
  En_traitement: 'En traitement',
  Pret_pour_edition: 'Prêt pour édition',
  En_edition: 'En édition',
  En_relecture: 'En relecture',
  Valide: 'Validé',
  Exporte_Livre: 'Exporté / Livré',
  Archive: 'Archivé',
};

/**
 * Format seconds into human-readable duration.
 */
function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  return m > 0 ? `${h}h${m}` : `${h}h`;
}

/**
 * Format ISO date string into relative or short date.
 */
function formatDate(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  const now = new Date();
  const diffMs = now - d;
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return 'À l\'instant';
  if (diffMin < 60) return `Il y a ${diffMin} min`;
  const diffH = Math.floor(diffMin / 60);
  if (diffH < 24) return `Il y a ${diffH}h`;
  const diffD = Math.floor(diffH / 24);
  if (diffD < 30) return `Il y a ${diffD}j`;
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

/**
 * Render pipeline progress bar HTML.
 */
function renderPipelineProgress(pipeline) {
  if (!pipeline) return '<span class="dash-pipeline-idle">—</span>';
  const pct = pipeline.progress_percent || 0;
  if (pipeline.status === 'completed') {
    return '<span class="dash-pipeline-done">✓ Terminé</span>';
  }
  if (pipeline.status === 'failed') {
    return '<span class="dash-pipeline-failed">✗ Échoué</span>';
  }
  const step = pipeline.current_step || '';
  return `
    <div class="dash-pipeline-bar">
      <div class="dash-pipeline-fill" style="width:${pct}%"></div>
      <span class="dash-pipeline-label">${step} ${pct}%</span>
    </div>`;
}

/**
 * Render status badge.
 */
function renderStatusBadge(status) {
  const label = STATUS_LABELS[status] || status;
  return `<span class="project-status-badge project-status-badge--${status}">${label}</span>`;
}

/**
 * Dashboard class — creates and manages the dashboard UI.
 */
export class Dashboard {
  /**
   * @param {string} containerId - DOM element ID to mount into
   * @param {string} studioId - Studio UUID
   */
  constructor(containerId, studioId) {
    this.containerId = containerId;
    this.studioId = studioId;
    this.data = null;
    this.activeFilters = new Set();
    this._onFilterClick = this._onFilterClick.bind(this);
  }

  async fetch() {
    const res = await fetch(`/api/v1/studios/${this.studioId}/dashboard`);
    if (!res.ok) throw new Error(`Dashboard fetch failed: ${res.status}`);
    this.data = await res.json();
    return this.data;
  }

  async mount() {
    try {
      this.data = await this.fetch();
    } catch (e) {
      this._renderError(e);
      return;
    }
    this._render();
  }

  refresh() {
    return this.mount();
  }

  // ── Rendering ──────────────────────────────────────────

  _render() {
    const el = document.getElementById(this.containerId);
    if (!el) return;

    const { studio_name, studio_plan, projects, indicators, filters } = this.data;

    el.innerHTML = `
      <div class="dash-header">
        <h1 class="dash-title">${studio_name}</h1>
        <span class="dash-plan">${studio_plan || 'free'}</span>
      </div>

      <div class="dash-indicators" data-testid="dash-indicators">
        ${this._renderIndicators(indicators)}
      </div>

      <div class="dash-filters" data-testid="dash-filters">
        <span class="dash-filters-label">Filtrer par statut :</span>
        <button class="dash-filter-btn ${this.activeFilters.size === 0 ? 'active' : ''}" data-status="">Tous</button>
        ${filters.map(f => `
          <button class="dash-filter-btn ${this.activeFilters.has(f.value) ? 'active' : ''}"
                  data-status="${f.value}" data-testid="filter-${f.value}">
            ${f.label}
            <span class="dash-filter-count">${indicators.status_distribution.find(s => s.status === f.value)?.count || 0}</span>
          </button>
        `).join('')}
      </div>

      <div class="dash-projects" data-testid="dash-projects">
        ${this._renderProjects(projects)}
      </div>
    `;

    // Bind filter clicks
    el.querySelectorAll('.dash-filter-btn').forEach(btn => {
      btn.addEventListener('click', this._onFilterClick);
    });
  }

  _renderIndicators(ind) {
    const quotaWarn = ind.quota.percent_used >= 80 ? 'dash-quota-warn' : '';
    const quotaCritical = ind.quota.percent_used >= 95 ? 'dash-quota-critical' : '';
    return `
      <div class="dash-indicator" data-testid="indicator-total">
        <span class="dash-indicator-value">${ind.total_projects}</span>
        <span class="dash-indicator-label">Projets</span>
      </div>
      <div class="dash-indicator" data-testid="indicator-volume">
        <span class="dash-indicator-value">${ind.volume_month}</span>
        <span class="dash-indicator-label">Traités (30j)</span>
      </div>
      <div class="dash-indicator" data-testid="indicator-avg-time">
        <span class="dash-indicator-value">${formatDuration(ind.avg_processing_seconds)}</span>
        <span class="dash-indicator-label">Temps moy. pipeline</span>
      </div>
      <div class="dash-indicator ${quotaWarn} ${quotaCritical}" data-testid="indicator-quota">
        <span class="dash-indicator-value">${ind.quota.remaining_minutes}min</span>
        <span class="dash-indicator-label">Quota IA restant</span>
        <span class="dash-quota-bar" data-testid="quota-bar">
          <span class="dash-quota-fill" style="width:${Math.min(100, ind.quota.percent_used)}%"></span>
        </span>
        <span class="dash-quota-text">${ind.quota.percent_used}% utilisé</span>
      </div>
    `;
  }

  _renderProjects(projects) {
    const filtered = this.activeFilters.size > 0
      ? projects.filter(p => this.activeFilters.has(p.status))
      : projects;

    if (filtered.length === 0) {
      return '<div class="dash-empty">Aucun projet ne correspond au filtre.</div>';
    }

    return `
      <table class="dash-table" data-testid="dash-table">
        <thead>
          <tr>
            <th>Projet</th>
            <th>Statut</th>
            <th>Pipeline</th>
            <th>Dernière modif</th>
          </tr>
        </thead>
        <tbody>
          ${filtered.map(p => `
            <tr class="dash-row" data-project-id="${p.id}" data-status="${p.status}" data-testid="project-row">
              <td class="dash-cell-title">${p.title}</td>
              <td class="dash-cell-status">${renderStatusBadge(p.status)}</td>
              <td class="dash-cell-pipeline">${renderPipelineProgress(p.pipeline)}</td>
              <td class="dash-cell-date">${formatDate(p.updated_at)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  }

  _renderError(e) {
    const el = document.getElementById(this.containerId);
    if (!el) return;
    el.innerHTML = `<div class="dash-error">Erreur de chargement : ${e.message}</div>`;
  }

  _onFilterClick(e) {
    const btn = e.currentTarget;
    const status = btn.dataset.status;

    if (!status) {
      // "Tous" — clear all filters
      this.activeFilters.clear();
    } else if (this.activeFilters.has(status)) {
      this.activeFilters.delete(status);
    } else {
      this.activeFilters.add(status);
    }

    this._render();
  }
}

/**
 * Pure function version for SSR / test rendering.
 */
export function renderDashboardHTML(data, activeFilters = new Set()) {
  const dash = new Dashboard('_ssr', data.studio_id);
  dash.data = data;
  dash.activeFilters = activeFilters;
  const temp = document.createElement('div');
  temp.id = '_ssr';
  document.body.appendChild(temp);
  dash._render();
  const html = temp.innerHTML;
  temp.remove();
  return html;
}
