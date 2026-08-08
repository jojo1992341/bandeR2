/**
 * VersionsPanel §16.1 — Gestion de versions de la bande rythmo
 * Historisation complète, comparaison entre versions, retour arrière
 */

import { api } from '../services/api.js';

export class VersionsPanel {
  constructor(containerId, projectId) {
    this.containerId = containerId;
    this.projectId = projectId;
    this.versions = [];
    this.selected = new Set();
    this.container = null;
  }

  async mount() {
    this.container = document.getElementById(this.containerId);
    if (!this.container) {
      // Créer le conteneur s'il n'existe pas
      this.container = document.createElement('div');
      this.container.id = this.containerId;
      this.container.setAttribute('data-testid', 'versions-panel');
      document.body.appendChild(this.container);
    }
    this.container.setAttribute('data-testid', 'versions-panel');
    await this.refresh();
    this.render();
    return this;
  }

  async refresh() {
    if (!this.projectId) return;
    try {
      const data = await api.listVersions(this.projectId);
      this.versions = data.versions || [];
    } catch (e) {
      console.error('listVersions failed', e);
      this.versions = [];
    }
  }

  render() {
    if (!this.container) return;
    const count = this.versions.length;
    this.container.innerHTML = `
      <style>
        .versions-panel { background: #16182e; border-radius: 8px; padding: 1rem; color: #e8e8ec; font-family: system-ui, sans-serif; }
        .versions-panel h2 { margin: 0 0 0.5rem 0; font-size: 1.1rem; }
        .versions-list { list-style: none; padding: 0; margin: 0; }
        .version-item { display: flex; justify-content: space-between; align-items: center; padding: 0.5rem; border: 1px solid #2a2d3e; border-radius: 4px; margin-bottom: 0.5rem; }
        .version-item.selected { border-color: #e11d48; background: #1f2235; }
        .version-actions button { margin-left: 0.5rem; padding: 0.25rem 0.5rem; border-radius: 4px; border: 1px solid #3f3f46; background: #2a2d3e; color: #e8e8ec; cursor: pointer; }
        .version-actions button:hover { background: #3a3f5c; }
        .version-actions button.restore { background: #e11d48; border-color: #e11d48; }
        .compare-box { margin-top: 1rem; padding: 0.75rem; background: #0b0c15; border-radius: 4px; border: 1px solid #2a2d3e; }
        .diff-added { color: #22c55e; }
        .diff-removed { color: #ef4444; }
        .diff-modified { color: #f59e0b; }
        .create-version { margin-bottom: 0.75rem; }
        .create-version input { background: #0b0c15; border: 1px solid #3f3f46; color: #e8e8ec; padding: 0.35rem; border-radius: 4px; width: 60%; }
        .create-version button { padding: 0.35rem 0.75rem; margin-left: 0.5rem; background: #e11d48; border: none; color: white; border-radius: 4px; cursor: pointer; }
      </style>
      <div class="versions-panel">
        <h2>Versions de la bande rythmo §16.1</h2>
        <div class="create-version" data-testid="create-version-box">
          <input type="text" placeholder="Commentaire de version (optionnel)" data-testid="version-comment-input" />
          <button data-testid="create-version-btn">Créer une version</button>
          <button data-testid="compare-btn" ${this.selected.size === 2 ? '' : 'disabled'}>Comparer sélectionnées</button>
        </div>
        <div data-testid="versions-count">${count} version(s)</div>
        <ul class="versions-list" data-testid="versions-list">
          ${this.versions.map(v => `
            <li class="version-item ${this.selected.has(v.id) ? 'selected' : ''}" data-testid="version-item" data-version-id="${v.id}" data-version-number="${v.version_number}">
              <div>
                <strong>V${v.version_number}</strong>
                <span data-testid="version-comment">${v.comment || '(sans commentaire)'}</span>
                <small style="opacity:0.7; margin-left:0.5rem;">${new Date(v.created_at).toLocaleString('fr-FR')} — ${v.created_by}</small>
                <small style="opacity:0.7; margin-left:0.5rem;" data-testid="replica-count">${v.replica_count || (v.snapshot?.length || 0)} répliques</small>
              </div>
              <div class="version-actions">
                <button data-testid="view-version-btn" data-id="${v.id}">Consulter</button>
                <button data-testid="restore-version-btn" data-id="${v.id}" class="restore">Restaurer</button>
                <label style="margin-left:0.5rem;"><input type="checkbox" data-testid="select-version" data-id="${v.id}" ${this.selected.has(v.id) ? 'checked' : ''} /> Sélection</label>
              </div>
            </li>
          `).join('')}
        </ul>
        <div id="version-detail" data-testid="version-detail"></div>
        <div id="version-compare" data-testid="version-compare"></div>
      </div>
    `;
    this._bind();
  }

  _bind() {
    const createBtn = this.container.querySelector('[data-testid="create-version-btn"]');
    const commentInput = this.container.querySelector('[data-testid="version-comment-input"]');
    const compareBtn = this.container.querySelector('[data-testid="compare-btn"]');

    if (createBtn) {
      createBtn.addEventListener('click', async () => {
        const comment = commentInput ? commentInput.value : null;
        try {
          await api.createVersion(this.projectId, comment);
          await this.refresh();
          this.render();
          window.dispatchEvent(new CustomEvent('versions:created', { detail: { projectId: this.projectId }}));
        } catch (e) {
          alert('Création version échouée: ' + e.message);
        }
      });
    }

    if (compareBtn) {
      compareBtn.addEventListener('click', async () => {
        if (this.selected.size !== 2) {
          alert('Sélectionnez exactement 2 versions à comparer');
          return;
        }
        const [fromId, toId] = Array.from(this.selected);
        try {
          const result = await api.compareVersions(this.projectId, fromId, toId);
          this.showCompare(result);
        } catch (e) {
          alert('Comparaison échouée: ' + e.message);
        }
      });
    }

    this.container.querySelectorAll('[data-testid="view-version-btn"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        try {
          const v = await api.getVersion(this.projectId, id);
          this.showDetail(v);
        } catch (e) {
          alert('Consultation échouée: ' + e.message);
        }
      });
    });

    this.container.querySelectorAll('[data-testid="restore-version-btn"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!confirm(`Restaurer la version ${id} ? L'état actuel sera remplacé.`)) return;
        try {
          const result = await api.restoreVersion(this.projectId, id);
          // Mettre à jour le store si disponible
          if (window.store && result.replicas) {
            window.store.setReplicas(result.replicas);
          }
          window.dispatchEvent(new CustomEvent('versions:restored', { detail: { projectId: this.projectId, versionId: id }}));
          alert(`Version restaurée : ${result.replica_count} répliques`);
          await this.refresh();
          this.render();
        } catch (e) {
          alert('Restauration échouée: ' + e.message);
        }
      });
    });

    this.container.querySelectorAll('[data-testid="select-version"]').forEach(cb => {
      cb.addEventListener('change', () => {
        const id = cb.getAttribute('data-id');
        if (cb.checked) {
          if (this.selected.size >= 2) {
            // Limiter à 2
            cb.checked = false;
            alert('Maximum 2 versions pour comparaison');
            return;
          }
          this.selected.add(id);
        } else {
          this.selected.delete(id);
        }
        this.render();
      });
    });
  }

  showDetail(version) {
    const detailEl = this.container.querySelector('#version-detail');
    if (!detailEl) return;
    const snapshot = version.snapshot || [];
    detailEl.innerHTML = `
      <div class="compare-box" data-testid="detail-box">
        <h3>Détail V${version.version_number} — ${version.comment || ''}</h3>
        <div>${snapshot.length} répliques</div>
        <pre style="max-height:300px; overflow:auto; background:#0b0c15; padding:0.5rem; border-radius:4px;">${JSON.stringify(snapshot, null, 2)}</pre>
        <button data-testid="close-detail">Fermer</button>
      </div>
    `;
    detailEl.querySelector('[data-testid="close-detail"]')?.addEventListener('click', () => { detailEl.innerHTML = ''; });
  }

  showCompare(result) {
    const compareEl = this.container.querySelector('#version-compare');
    if (!compareEl) return;
    const { from, to, added, removed, modified, summary } = result;
    compareEl.innerHTML = `
      <div class="compare-box" data-testid="compare-box">
        <h3>Comparaison V${from.version_number} → V${to.version_number}</h3>
        <div data-testid="compare-summary">+${summary.added_count} ajoutées, -${summary.removed_count} supprimées, ~${summary.modified_count} modifiées</div>
        ${added.length ? `<div class="diff-added" data-testid="diff-added"><strong>Ajoutées:</strong> <pre>${JSON.stringify(added, null, 2)}</pre></div>` : ''}
        ${removed.length ? `<div class="diff-removed" data-testid="diff-removed"><strong>Supprimées:</strong> <pre>${JSON.stringify(removed, null, 2)}</pre></div>` : ''}
        ${modified.length ? `<div class="diff-modified" data-testid="diff-modified"><strong>Modifiées:</strong> <pre>${JSON.stringify(modified, null, 2)}</pre></div>` : ''}
        ${!added.length && !removed.length && !modified.length ? '<div>Aucune différence</div>' : ''}
        <button data-testid="close-compare">Fermer</button>
      </div>
    `;
    compareEl.querySelector('[data-testid="close-compare"]')?.addEventListener('click', () => { compareEl.innerHTML = ''; });
  }

  setProjectId(projectId) {
    this.projectId = projectId;
    this.refresh().then(() => this.render());
  }
}

// Web Component wrapper (optionnel)
export class RythmoVersionsPanel extends HTMLElement {
  connectedCallback() {
    const projectId = this.getAttribute('project-id');
    this.panel = new VersionsPanel(this.id || 'versions-panel-host', projectId);
    // Si l'élément a un id, on l'utilise, sinon on crée un conteneur interne
    if (!this.id) {
      this.id = 'versions-panel-' + Math.random().toString(36).slice(2, 7);
      this.panel.containerId = this.id;
    }
    this.panel.projectId = projectId;
    this.panel.container = this;
    this.panel.refresh().then(() => this.panel.render());
  }
  setProjectId(id) {
    if (this.panel) this.panel.setProjectId(id);
  }
}

if (!customElements.get('rythmo-versions')) {
  customElements.define('rythmo-versions', RythmoVersionsPanel);
}
