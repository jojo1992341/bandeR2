/**
 * CommentsPanel §14.2.4 — Fil de commentaires dans le panneau latéral contextuel
 * Affiche le fil de commentaires attaché à la réplique sélectionnée,
 * permet d'ajouter/supprimer, et se met à jour pour tous les utilisateurs du projet (polling).
 */

import { api } from '../services/api.js';

export class CommentsPanel {
  constructor(containerId, store) {
    this.containerId = containerId;
    this.store = store;
    this.container = null;
    this.currentReplicaId = null;
    this.comments = [];
    this.pollTimer = null;
    this.isMounted = false;
  }

  mount() {
    this.container = document.getElementById(this.containerId);
    if (!this.container) {
      this.container = document.createElement('div');
      this.container.id = this.containerId;
      this.container.setAttribute('data-testid', 'comments-panel');
      // Insérer dans le panneau latéral contextuel - on cherche un conteneur latéral ou on crée à côté de replica-list
      const app = document.getElementById('app');
      const target = document.getElementById('replica-list')?.parentElement || app || document.body;
      target.appendChild(this.container);
    }
    this.container.setAttribute('data-testid', 'comments-panel');
    this.container.classList.add('comments-panel-container');
    this.isMounted = true;

    // Écouter la sélection de réplique
    if (this.store) {
      this.store.subscribe('selection', (e) => {
        const selected = e.detail.selection || this.store.selection;
        if (selected) {
          this.loadForReplica(selected);
        } else {
          this.currentReplicaId = null;
          this.comments = [];
          this.render();
        }
      });
      // Charger initial si déjà une sélection
      if (this.store.selection) {
        this.loadForReplica(this.store.selection);
      }
    }

    // Écouter l'événement custom pour rafraîchissement immédiat (autre utilisateur local)
    if (typeof window !== 'undefined') {
      window.addEventListener('comments:created', (e) => {
        if (e.detail && e.detail.replica_id === this.currentReplicaId) {
          this.refresh();
        }
      });
      window.addEventListener('comments:deleted', (e) => {
        if (e.detail && e.detail.replica_id === this.currentReplicaId) {
          this.refresh();
        }
      });
    }

    // Polling pour l'affichage immédiat pour un second utilisateur (toutes les 2s)
    this.startPolling();

    this.render();
    return this;
  }

  unmount() {
    this.isMounted = false;
    if (this.pollTimer) clearInterval(this.pollTimer);
    if (this.container) {
      // Ne pas supprimer le container, juste vider
    }
  }

  startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => {
      if (this.currentReplicaId) {
        this.refresh(false); // silent refresh
      }
    }, 2000);
  }

  async loadForReplica(replicaId) {
    this.currentReplicaId = replicaId;
    await this.refresh();
  }

  async refresh(showLoading = true) {
    if (!this.currentReplicaId) {
      this.comments = [];
      this.render();
      return;
    }
    if (showLoading) {
      // Optionnel: afficher un état de chargement
    }
    try {
      const data = await api.listComments(this.currentReplicaId);
      // L'API retourne une liste directe ou un objet avec commentaires
      this.comments = Array.isArray(data) ? data : (data.comments || []);
      this.render();
    } catch (e) {
      console.error('Failed to load comments', e);
      // Ne pas vider les commentaires en cas d'erreur réseau, garder l'existant
    }
  }

  render() {
    if (!this.container || !this.isMounted) return;

    const replicaId = this.currentReplicaId;
    const hasSelection = !!replicaId;
    const commentsHtml = this.comments.map(c => `
      <div class="comment-item" data-testid="comment-item" data-comment-id="${c.id}">
        <div class="comment-header">
          <span class="comment-author" data-testid="comment-author">${c.author_email || c.author_id || 'Anonyme'}</span>
          <span class="comment-date" style="opacity:0.6; font-size:0.75rem;">${c.created_at ? new Date(c.created_at).toLocaleString('fr-FR') : ''}</span>
        </div>
        <div class="comment-content" data-testid="comment-content">${this._escapeHtml(c.content)}</div>
        <button class="comment-delete" data-testid="delete-comment-btn" data-comment-id="${c.id}" style="font-size:0.7rem; opacity:0.7; background:none; border:none; color:#e11d48; cursor:pointer;">Supprimer</button>
      </div>
    `).join('');

    const emptyHtml = hasSelection && this.comments.length === 0
      ? `<div data-testid="no-comments" style="opacity:0.6; font-style:italic; padding:0.5rem;">Aucun commentaire pour cette réplique.</div>`
      : '';

    const noSelectionHtml = !hasSelection
      ? `<div data-testid="no-selection" style="opacity:0.6; padding:0.5rem;">Sélectionnez une réplique pour voir ses commentaires.</div>`
      : '';

    this.container.innerHTML = `
      <style>
        .comments-panel { background: #1a1c2e; border-radius: 8px; padding: 1rem; color: #e8e8ec; font-family: system-ui, sans-serif; border: 1px solid #2a2d3e; margin-top: 1rem; }
        .comments-panel h3 { margin: 0 0 0.75rem 0; font-size: 1rem; color: #e11d48; }
        .comment-item { background: #0b0c15; border: 1px solid #2a2d3e; border-radius: 6px; padding: 0.75rem; margin-bottom: 0.5rem; }
        .comment-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem; font-size: 0.8rem; font-weight: 600; }
        .comment-content { font-size: 0.9rem; line-height: 1.3; white-space: pre-wrap; word-break: break-word; }
        .comment-form { display: flex; gap: 0.5rem; margin-top: 0.75rem; }
        .comment-form textarea { flex: 1; background: #0b0c15; border: 1px solid #3f3f46; color: #e8e8ec; padding: 0.5rem; border-radius: 4px; resize: vertical; min-height: 60px; font-family: inherit; }
        .comment-form button { padding: 0.5rem 1rem; background: #e11d48; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; align-self: flex-end; }
        .comment-form button:disabled { background: #3f3f46; cursor: not-allowed; }
      </style>
      <div class="comments-panel" data-testid="comments-thread">
        <h3 data-testid="comments-title">Fil de commentaires ${hasSelection ? `— Réplique ${replicaId ? replicaId.slice(0,8) : ''}` : ''}</h3>
        ${noSelectionHtml}
        ${hasSelection ? `<div data-testid="comments-list">${emptyHtml}${commentsHtml}</div>` : ''}
        ${hasSelection ? `
          <form class="comment-form" data-testid="comment-form">
            <textarea data-testid="comment-input" placeholder="Ajouter un commentaire..." rows="2"></textarea>
            <button type="submit" data-testid="submit-comment-btn">Envoyer</button>
          </form>
        ` : ''}
        <div style="margin-top:0.5rem; font-size:0.7rem; opacity:0.5;" data-testid="comments-count">${this.comments.length} commentaire(s)</div>
      </div>
    `;

    this._bind();
  }

  _escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }

  _bind() {
    const form = this.container.querySelector('[data-testid="comment-form"]');
    if (form) {
      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const input = this.container.querySelector('[data-testid="comment-input"]');
        const content = input ? input.value.trim() : '';
        if (!content || !this.currentReplicaId) return;
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        try {
          const newComment = await api.createComment(this.currentReplicaId, content);
          // Ajout optimiste + événement pour notifier les autres panneaux (même projet, second utilisateur local)
          this.comments.push(newComment);
          this.render();
          if (input) input.value = '';
          // Notifier globalement pour que d'autres instances (second utilisateur simulé) puissent rafraîchir
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('comments:created', { detail: { replica_id: this.currentReplicaId, comment: newComment }}));
          }
          // Rafraîchir depuis le serveur pour s'assurer de la cohérence
          await this.refresh();
        } catch (err) {
          console.error('Failed to create comment', err);
          alert('Erreur lors de la création du commentaire: ' + (err.message || 'unknown'));
        } finally {
          if (btn) btn.disabled = false;
        }
      });
    }

    this.container.querySelectorAll('[data-testid="delete-comment-btn"]').forEach(btn => {
      btn.addEventListener('click', async () => {
        const commentId = btn.getAttribute('data-comment-id');
        if (!commentId) return;
        if (!confirm('Supprimer ce commentaire ?')) return;
        try {
          await api.deleteComment(commentId);
          this.comments = this.comments.filter(c => c.id !== commentId);
          this.render();
          if (typeof window !== 'undefined') {
            window.dispatchEvent(new CustomEvent('comments:deleted', { detail: { replica_id: this.currentReplicaId, comment_id: commentId }}));
          }
          await this.refresh();
        } catch (err) {
          console.error('Failed to delete comment', err);
          alert('Erreur lors de la suppression');
        }
      });
    });
  }

  // Pour tests : simulation d'un second utilisateur qui rafraîchit
  async forceRefresh() {
    await this.refresh();
  }
}

export class RythmoCommentsPanel extends HTMLElement {
  connectedCallback() {
    const replicaId = this.getAttribute('replica-id');
    // On récupère le store global si disponible
    const store = (typeof window !== 'undefined' && window.store) ? window.store : null;
    this.panel = new CommentsPanel(this.id || 'comments-panel-host', store);
    if (!this.id) {
      this.id = 'comments-panel-' + Math.random().toString(36).slice(2, 7);
      this.panel.containerId = this.id;
    }
    this.panel.container = this;
    if (replicaId) {
      this.panel.currentReplicaId = replicaId;
    }
    this.panel.isMounted = true;
    this.panel.render();
    if (replicaId) {
      this.panel.loadForReplica(replicaId);
    }
    // Écouter la sélection du store si disponible
    if (store) {
      store.subscribe('selection', (e) => {
        const sel = e.detail.selection || store.selection;
        if (sel) this.panel.loadForReplica(sel);
      });
    }
  }
}

if (!customElements.get('rythmo-comments')) {
  customElements.define('rythmo-comments', RythmoCommentsPanel);
}
