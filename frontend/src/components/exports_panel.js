/**
 * ExportsPanel — Export PDF calligraphié + SRT/VTT étendu + EBU-STL étendu + Cavena/.rythmo + JSON + Journal qualité §A.2, §17.1, §12.4
 * Génération asynchrone <15s et téléchargement via GET /exports/{id}/download
 * SRT/VTT : texte horodaté, locuteur en commentaire, styles basiques
 * EBU-STL étendu : GSI 1024 + TTI 128*N, 25fps, conforme ETS 300 706 (rétro-ingénierie docs/retro_engineering_cavena_ebu.md)
 * Cavena/.rythmo : structure propriétaire reconstituée (magic, timings, typo_flags, texte) — Annexe A.2
 * Qualité : rapport PDF de synthèse (scores de confiance, zones à faible confiance)
 */

import { api } from '../services/api.js';

export class ExportsPanel {
  constructor(containerId, projectId) {
    this.containerId = containerId;
    this.projectId = projectId;
    this.container = null;
    this.lastExportId = null;
    this.lastFormat = 'pdf';
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
        .export-actions button { padding: 0.5rem 1rem; border-radius: 6px; border: none; background: #e11d48; color: white; cursor: pointer; font-weight: 600; margin-right: 0.5rem; margin-bottom: 0.5rem; }
        .export-actions button:disabled { background: #3f3f46; cursor: not-allowed; }
        .export-actions select { background: #0b0c15; color: #e8e8ec; border: 1px solid #3f3f46; padding: 0.5rem; border-radius: 6px; }
        .export-status { margin-top: 0.75rem; padding: 0.5rem; border-radius: 4px; background: #0b0c15; border: 1px solid #2a2d3e; }
        .export-status.saving { border-color: #3b82f6; }
        .export-status.saved { border-color: #22c55e; }
        .export-status.error { border-color: #ef4444; }
        .export-download a { color: #3b82f6; text-decoration: underline; cursor: pointer; }
      </style>
      <div class="exports-panel">
        <h2>Exports — Annexe A.2</h2>
        <p style="opacity:0.8; font-size:0.85rem;">PDF calligraphié + SRT/VTT étendu + EBU-STL étendu + Cavena/.rythmo + JSON + Journal qualité §12.4. Génération asynchrone &lt;15s §17.1</p>
        <div class="export-actions" data-testid="export-actions">
          <select data-testid="export-format-select">
            <option value="pdf" ${this.lastFormat === 'pdf' ? 'selected' : ''}>PDF calligraphié</option>
            <option value="srt" ${this.lastFormat === 'srt' ? 'selected' : ''}>SRT étendu</option>
            <option value="vtt" ${this.lastFormat === 'vtt' ? 'selected' : ''}>VTT étendu</option>
            <option value="stl" ${this.lastFormat === 'stl' ? 'selected' : ''}>EBU-STL étendu</option>
            <option value="cavena" ${this.lastFormat === 'cavena' ? 'selected' : ''}>Cavena (.cav)</option>
            <option value="rythmo" ${this.lastFormat === 'rythmo' ? 'selected' : ''}>Rythmo (.rythmo)</option>
            <option value="json" ${this.lastFormat === 'json' ? 'selected' : ''}>JSON structuré</option>
            <option value="quality_report" ${this.lastFormat === 'quality_report' ? 'selected' : ''}>Rapport qualité PDF</option>
          </select>
          <button data-testid="export-pdf-btn" ${isGenerating ? 'disabled' : ''}>${isGenerating ? 'Génération en cours…' : 'Exporter'}</button>
          <button data-testid="export-srt-btn" style="background:#3b82f6;" ${isGenerating ? 'disabled' : ''}>SRT</button>
          <button data-testid="export-vtt-btn" style="background:#8b5cf6;" ${isGenerating ? 'disabled' : ''}>VTT</button>
          <button data-testid="export-stl-btn" style="background:#06b6d4;" ${isGenerating ? 'disabled' : ''}>EBU-STL</button>
          <button data-testid="export-cavena-btn" style="background:#6366f1;" ${isGenerating ? 'disabled' : ''}>Cavena</button>
          <button data-testid="export-rythmo-btn" style="background:#14b8a6;" ${isGenerating ? 'disabled' : ''}>Rythmo</button>
          <button data-testid="export-json-btn" style="background:#a3a3a3; color:#0b0c15;" ${isGenerating ? 'disabled' : ''}>JSON</button>
          <button data-testid="export-quality-btn" style="background:#f59e0b; color:#0b0c15;" ${isGenerating ? 'disabled' : ''}>Rapport qualité</button>
          <button data-testid="export-refresh-btn" style="background:#2a2d3e;">Actualiser</button>
        </div>
        <div class="export-status ${status || 'idle'}" data-testid="export-status" data-status="${status || 'idle'}">
          ${status ? `Statut: ${status} (${this.lastFormat})` : 'Aucun export en cours'}
          ${error ? `<div style="color:#ef4444; margin-top:0.25rem;">Erreur: ${error}</div>` : ''}
        </div>
        <div class="export-download" data-testid="export-download" style="margin-top:0.5rem;"></div>
        <div style="margin-top:0.5rem; font-size:0.75rem; opacity:0.7;">Formats: PDF • SRT • VTT • EBU-STL • Cavena • Rythmo • JSON • Rapport qualité • Timecodes SMPTE 25fps • Codes typo inclus • Rétro-ingénierie §4 / Annexe A.2</div>
      </div>
    `;
    this._bind();
  }

  _bind() {
    const btnPdf = this.container.querySelector('[data-testid="export-pdf-btn"]');
    const btnSrt = this.container.querySelector('[data-testid="export-srt-btn"]');
    const btnVtt = this.container.querySelector('[data-testid="export-vtt-btn"]');
    const btnQuality = this.container.querySelector('[data-testid="export-quality-btn"]');
    const refreshBtn = this.container.querySelector('[data-testid="export-refresh-btn"]');
    const select = this.container.querySelector('[data-testid="export-format-select"]');
    if (select) {
      select.addEventListener('change', (e) => {
        this.lastFormat = e.target.value;
      });
    }
    if (btnPdf) {
      btnPdf.addEventListener('click', () => this.createExport(this.lastFormat || 'pdf'));
    }
    if (btnSrt) {
      btnSrt.addEventListener('click', () => this.createExport('srt'));
    }
    if (btnVtt) {
      btnVtt.addEventListener('click', () => this.createExport('vtt'));
    }
    const btnStl = this.container.querySelector('[data-testid="export-stl-btn"]');
    const btnCavena = this.container.querySelector('[data-testid="export-cavena-btn"]');
    const btnRythmo = this.container.querySelector('[data-testid="export-rythmo-btn"]');
    const btnJson = this.container.querySelector('[data-testid="export-json-btn"]');
    if (btnStl) {
      btnStl.addEventListener('click', () => this.createExport('stl'));
    }
    if (btnCavena) {
      btnCavena.addEventListener('click', () => this.createExport('cavena'));
    }
    if (btnRythmo) {
      btnRythmo.addEventListener('click', () => this.createExport('rythmo'));
    }
    if (btnJson) {
      btnJson.addEventListener('click', () => this.createExport('json'));
    }
    if (btnQuality) {
      btnQuality.addEventListener('click', () => this.createExport('quality_report'));
    }
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.checkStatus());
    }
  }

  async createExport(format = null) {
    if (!this.projectId) {
      alert('Projet non défini');
      return;
    }
    const fmt = format || this.lastFormat || 'pdf';
    this.lastFormat = fmt;
    this.render('pending');
    try {
      const result = await api.createExport(this.projectId, fmt);
      this.lastExportId = result.id;
      this.lastFormat = result.format || fmt;
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
        this.lastFormat = data.format || this.lastFormat;
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
      this.lastFormat = data.format || this.lastFormat;
      this.render(data.status);
      if (data.status === 'completed') this.showDownload(data);
    } catch (e) {
      this.render('error', e.message);
    }
  }

  showDownload(exportData) {
    const dlContainer = this.container.querySelector('[data-testid="export-download"]');
    if (!dlContainer) return;
    const fmt = exportData.format || this.lastFormat || 'pdf';
    const ext = fmt.toLowerCase() === 'quality_report' ? 'pdf' : fmt.toLowerCase();
    dlContainer.innerHTML = `
      <a href="/api/v1/exports/${exportData.id}/download" data-testid="download-link" download>Télécharger le ${ext.toUpperCase()}</a>
      <span style="margin-left:0.5rem; opacity:0.7;">(${exportData.id.slice(0,8)}… • ${ext.toUpperCase()})</span>
      <button data-testid="download-btn" style="margin-left:0.5rem; padding:0.25rem 0.5rem; background:#22c55e; border:none; color:white; border-radius:4px; cursor:pointer;">Télécharger</button>
    `;
    const link = dlContainer.querySelector('[data-testid="download-btn"]');
    if (link) {
      link.addEventListener('click', async () => {
        try {
          const blob = await api.downloadExport(exportData.id);
          const url = URL.createObjectURL(blob);
          const a = document.createElement('a');
          a.href = url;
          a.download = `bande_rythmo_${exportData.id}.${ext}`;
          a.click();
          URL.revokeObjectURL(url);
        } catch (e) {
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
