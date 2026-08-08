/**
 * ExportsPanel — Export PDF calligraphié §A.2, §17.1
 * Génération asynchrone <15s et téléchargement via GET /exports/{id}/download
 */

import { api } from '../services/api.js';

export class ExportsPanel {
  constructor(containerId, projectId) {
    this.containerId = containerId;
    this.projectId = projectId;
    this.container = null;
    this.lastExportId = null;
    this.pollTimer = null;
  }

  mount() {
    this.container = document.getElementById(this.containerId);
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = this.containerId;
      this.container.setAttribute('data-testid', 'exports-panel');
      const app = document.getElementById('app');
      if (app) app.appendChild(this.container);
      else document.body.appendChild(this.container);
    }
    this.container.setAttribute('data-testid', 'exports-panel');
    this.render();
    return this;
  }

  render(status = null, error = null) {
    if (!this.container) return;
    const isGenerating = status === 'pending' || status === 'processing';
    this.container.innerHTML = `
      <style>
        .exports-panel { background: #16182e; border-radius: 8px; padding: 1rem; color: #e8e8ec; font-family: system-ui, sans-serif; margin-top: 1rem; }
        .exports-panel h2 { margin: 0 0 0.5rem 0; font-size: 1.1rem; }
        .export-actions button { padding: 0.5rem 1rem; border-radius: 6px; border: none; background: #e11d48; color: white; cursor: pointer; font-weight: 600; }
        .export-actions button:disabled { background: #3f3f46; cursor: not-allowed; }
        .export-status { margin-top: 0.75rem; padding: 0.5rem; border-radius: 4px; background: #0b0c15; border: 1px solid #2a2d3e; }
        .export-status.saving { border-color: #3b82f6; }
        .export-status.saved { border-color: #22c55e; }
        .export-status.error { border-color: #ef4444; }
        .export-download a { color: #3b82f6; text-decoration: underline; cursor: pointer; }
      </style>
      <div class="exports-panel">
        <h2>Export PDF calligraphié — Annexe A.2</h2>
        <p style="opacity:0.8; font-size:0.85rem;">Mise en page de la bande avec codes typographiques et timecodes de référence. Génération asynchrone &lt;15s §17.1</p>
        <div class="export-actions" data-testid="export-actions">
          <button data-testid="export-pdf-btn" ${isGenerating ? 'disabled' : ''}>${isGenerating ? 'Génération en cours…' : 'Exporter en PDF'}</button>
          <button data-testid="export-refresh-btn" style="background:#2a2d3e; margin-left:0.5rem;">Actualiser</button>
        </div>
        <div class="export-status ${status || 'idle'}" data-testid="export-status" data-status="${status || 'idle'}">
          ${status ? `Statut: ${status}` : 'Aucun export en cours'}
          ${error ? `<div style="color:#ef4444; margin-top:0.25rem;">Erreur: ${error}</div>` : ''}
        </div>
        <div class="export-download" data-testid="export-download" style="margin-top:0.5rem;"></div>
        <div style="margin-top:0.5rem; font-size:0.75rem; opacity:0.7;">Format: PDF calligraphié • Timecodes SMPTE 25fps • Codes typo inclus</div>
      </div>
    `;
    this._bind();
  }

  _bind() {
    const btn = this.container.querySelector('[data-testid="export-pdf-btn"]');
    const refreshBtn = this.container.querySelector('[data-testid="export-refresh-btn"]');
    if (btn) {
      btn.addEventListener('click', () => this.createExport());
    }
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.checkStatus());
    }
  }

  async createExport() {
    if (!this.projectId) {
      alert('Projet non défini');
      return;
    }
    this.render('pending');
    try {
      const result = await api.createExport(this.projectId, 'pdf');
      this.lastExportId = result.id;
      this.render('processing');
      this.pollStatus();
    } catch (e) {
      this.render('error', e.message);
    }
  }

  async pollStatus() {
    if (!this.lastExportId) return;
    if (this.pollTimer) clearTimeout(this.pollTimer);
    const check = async () => {
      try {
        const data = await api.getExport(this.lastExportId);
        const status = data.status;
        this.render(status);
        if (status === 'pending' || status === 'processing') {
          this.pollTimer = setTimeout(check, 500);
        } else if (status === 'completed') {
          this.showDownload(data);
        } else if (status === 'failed') {
          this.render('error', data.error_message);
        }
      } catch (e) {
        this.render('error', e.message);
      }
    };
    check();
  }

  async checkStatus() {
    if (!this.lastExportId) {
      this.render(null);
      return;
    }
    try {
      const data = await api.getExport(this.lastExportId);
      this.render(data.status);
      if (data.status === 'completed') this.showDownload(data);
    } catch (e) {
      this.render('error', e.message);
    }
  }

  showDownload(exportData) {
    const dlContainer = this.container.querySelector('[data-testid="export-download"]');
    if (!dlContainer) return;
    dlContainer.innerHTML = `
      <a href="/api/v1/exports/${exportData.id}/download" data-testid="download-link" download>Télécharger le PDF</a>
      <span style="margin-left:0.5rem; opacity:0.7;">(${exportData.id.slice(0,8)}…)</span>
      <button data-testid="download-btn" style="margin-left:0.5rem; padding:0.25rem 0.5rem; background:#22c55e; border:none; color:white; border-radius:4px; cursor:pointer;">Télécharger</button>
    `;
    const link = dlContainer.querySelector('[data-testid="download-btn"]');
    if (link) {
      link.addEventListener('click', async () => {
        try {
          // Utiliser l'API pour déclencher le téléchargement
          const blob = await api.downloadExport(exportData.id);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `bande_rythmo_${exportData.id}.pdf`;
          a.click();
          URL.revokeObjectURL(url);
        } catch (e) {
          // Fallback : navigation directe
          window.location.href = `/api/v1/exports/${exportData.id}/download`;
        }
      });
    }
  }

  setProjectId(projectId) {
    this.projectId = projectId;
    this.render();
  }
}

export class RythmoExportsPanel extends HTMLElement {
  connectedCallback() {
    const projectId = this.getAttribute('project-id');
    this.panel = new ExportsPanel(this.id || 'exports-panel-host', projectId);
    if (!this.id) {
      this.id = 'exports-panel-' + Math.random().toString(36).slice(2, 7);
      this.panel.containerId = this.id;
    }
    this.panel.projectId = projectId;
    this.panel.container = this;
    this.panel.render();
  }
  setProjectId(id) {
    if (this.panel) this.panel.setProjectId(id);
  }
}

if (!customElements.get('rythmo-exports')) {
  customElements.define('rythmo-exports', RythmoExportsPanel);
}
