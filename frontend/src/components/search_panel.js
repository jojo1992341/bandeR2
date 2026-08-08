/**
 * SearchPanel §16.1 — Recherche full-text dans les transcriptions d'un studio
 * Utilise l'API GET /studios/{id}/search (PostgreSQL French tsvector + fallback SQLite LIKE)
 * Option Meilisearch/OpenSearch documentée si volume > 10k répliques (non activée par défaut)
 */

import { api } from '../services/api.js';

export class SearchPanel {
  constructor(containerId, studioId) {
    this.containerId = containerId;
    this.studioId = studioId;
    this.container = null;
    this.lastQuery = '';
    this.lastResult = null;
    this.debounceTimer = null;
  }

  mount() {
    this.container = document.getElementById(this.containerId);
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = this.containerId;
      this.container.setAttribute('data-testid', 'search-panel');
      const app = document.getElementById('app');
      if (app) app.appendChild(this.container);
      else document.body.appendChild(this.container);
    }
    this.render();
    return this;
  }

  render() {
    if (!this.container) return;
    this.container.innerHTML = `
      <div class="search-panel" data-testid="search-panel">
        <h3>Recherche full-text §16.1</h3>
        <p style="opacity:0.7; font-size:0.8rem;">PostgreSQL French full-text (GIN) avec fallback SQLite LIKE — Meilisearch/OpenSearch optionnel si volume &gt; 10k</p>
        <input type="text" placeholder="Rechercher dans les transcriptions..." data-testid="search-input" style="width:100%; padding:0.5rem; border-radius:6px; border:1px solid #3f3f46; background:#0b0c15; color:#e8e8ec;" />
        <div data-testid="search-latency" style="font-size:0.75rem; opacity:0.6; margin-top:0.25rem;"></div>
        <div data-testid="search-results" style="margin-top:0.5rem;"></div>
        <div data-testid="search-projects" style="margin-top:0.5rem;"></div>
      </div>
    `;
    const input = this.container.querySelector('[data-testid="search-input"]');
    if (input) {
      input.addEventListener('input', (e) => this._onInput(e.target.value));
    }
  }

  async _onInput(query) {
    this.lastQuery = query.trim();
    if (this.lastQuery.length < 2) {
      this._clearResults();
      return;
    }
    clearTimeout(this.debounceTimer);
    this.debounceTimer = setTimeout(async () => {
      const start = performance.now();
      try {
        const result = await api.searchStudio(this.studioId, this.lastQuery, { limit: 10 });
        const latency = Math.round(performance.now() - start);
        // Utiliser la latence serveur si disponible, sinon la latence mesurée
        const serverLatency = result.latency_ms || result.took_ms || latency;
        this.lastResult = result;
        this._renderResults(result, serverLatency);
      } catch (e) {
        this._renderError(e);
      }
    }, 300);
  }

  _renderResults(result, measuredLatency) {
    const latencyEl = this.container.querySelector('[data-testid="search-latency"]');
    const resultsEl = this.container.querySelector('[data-testid="search-results"]');
    const projectsEl = this.container.querySelector('[data-testid="search-projects"]');
    if (latencyEl) {
      latencyEl.textContent = `Trouvé ${result.total_replicas} répliques, ${result.total_projects} projets en ${result.latency_ms}ms (mesuré ${measuredLatency}ms, moteur ${result.engine})`;
      latencyEl.setAttribute('data-latency', result.latency_ms);
      latencyEl.setAttribute('data-engine', result.engine);
    }
    if (resultsEl) {
      if (result.replicas.length === 0) {
        resultsEl.innerHTML = '<div style="opacity:0.6;">Aucune réplique trouvée</div>';
      } else {
        resultsEl.innerHTML = result.replicas.map(r => `
          <div data-testid="search-replica" data-replica-id="${r.id}" data-project-id="${r.project_id}" style="padding:0.5rem; border:1px solid #2a2d3e; border-radius:4px; margin-bottom:0.25rem;">
            <div style="font-weight:600;">${r.project_title} — ${r.text.slice(0,60)}</div>
            <div style="font-size:0.8rem; opacity:0.8;">${r.highlighted}</div>
            <div style="font-size:0.7rem; opacity:0.6;">${r.start_ms}→${r.end_ms} — ${r.speaker_id || '—'}</div>
          </div>
        `).join('');
      }
    }
    if (projectsEl) {
      if (result.projects.length === 0) {
        projectsEl.innerHTML = '';
      } else {
        projectsEl.innerHTML = '<h4>Projets pertinents</h4>' + result.projects.map(p => `
          <div data-testid="search-project" data-project-id="${p.id}" style="padding:0.25rem; border-left:2px solid #e11d48; margin-bottom:0.25rem;">
            ${p.title} (${p.total_matches} matches)
          </div>
        `).join('');
      }
    }
  }

  _clearResults() {
    const latencyEl = this.container.querySelector('[data-testid="search-latency"]');
    const resultsEl = this.container.querySelector('[data-testid="search-results"]');
    const projectsEl = this.container.querySelector('[data-testid="search-projects"]');
    if (latencyEl) latencyEl.textContent = '';
    if (resultsEl) resultsEl.innerHTML = '';
    if (projectsEl) projectsEl.innerHTML = '';
  }

  _renderError(e) {
    const resultsEl = this.container.querySelector('[data-testid="search-results"]');
    if (resultsEl) resultsEl.innerHTML = `<div style="color:#ef4444;">Erreur: ${e.message}</div>`;
  }

  // Pour tests : recherche directe sans debounce
  async search(query) {
    const result = await api.searchStudio(this.studioId, query, { limit: 10 });
    this.lastResult = result;
    this._renderResults(result, result.latency_ms);
    return result;
  }
}

if (!customElements.get('search-panel')) {
  try {
    customElements.define('search-panel', class extends HTMLElement {
      connectedCallback() {
        const studioId = this.getAttribute('studio-id');
        this.panel = new SearchPanel(this.id || 'search-panel-host', studioId);
        this.panel.container = this;
        this.panel.render();
      }
    });
  } catch {}
}
