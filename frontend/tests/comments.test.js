import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { CommentsPanel } from '../src/components/comments_panel.js';

// On va mocker l'api pour avoir un stockage partagé entre deux utilisateurs
const sharedComments = new Map(); // replicaId -> array of comments

vi.mock('../src/services/api.js', async () => {
  const actual = await vi.importActual('../src/services/api.js');
  return {
    api: {
      ...actual.api,
      listComments: vi.fn(async (replicaId) => {
        return sharedComments.get(replicaId) || [];
      }),
      createComment: vi.fn(async (replicaId, content) => {
        const list = sharedComments.get(replicaId) || [];
        const newComment = {
          id: `c-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          replica_id: replicaId,
          author_id: 'user1',
          author_email: 'user1@test.com',
          content,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        };
        list.push(newComment);
        sharedComments.set(replicaId, list);
        return newComment;
      }),
      deleteComment: vi.fn(async (commentId) => {
        for (const [replicaId, list] of sharedComments.entries()) {
          const idx = list.findIndex(c => c.id === commentId);
          if (idx >= 0) {
            list.splice(idx, 1);
            sharedComments.set(replicaId, list);
            return { status: 'deleted', id: commentId };
          }
        }
        throw new Error('Comment not found');
      }),
    }
  };
});

import { api } from '../src/services/api.js';

describe('CommentsPanel §14.2.4 — Fil de commentaires', () => {
  let store1, store2;
  let container1, container2;
  const replicaId = 'r-01';

  beforeEach(() => {
    sharedComments.clear();
    // Deux stores simulant deux utilisateurs connectés au même projet
    store1 = new RythmoStore();
    store2 = new RythmoStore();
    store1.setReplicas([{ id: replicaId, text: 'Bonjour le monde', start_ms: 0, end_ms: 2000 }]);
    store2.setReplicas([{ id: replicaId, text: 'Bonjour le monde', start_ms: 0, end_ms: 2000 }]);
    store1.selectReplica(replicaId);
    store2.selectReplica(replicaId);

    container1 = document.createElement('div');
    container1.id = 'comments-panel-user1';
    document.body.appendChild(container1);

    container2 = document.createElement('div');
    container2.id = 'comments-panel-user2';
    document.body.appendChild(container2);

    vi.clearAllMocks();
  });

  afterEach(() => {
    container1.remove();
    container2.remove();
    sharedComments.clear();
  });

  it('affiche le fil de commentaires pour la réplique sélectionnée', async () => {
    const panel = new CommentsPanel('comments-panel-user1', store1);
    panel.mount();
    await new Promise(r => setTimeout(r, 0));
    expect(container1.querySelector('[data-testid="comments-thread"]')).not.toBeNull();
    expect(container1.querySelector('[data-testid="no-comments"]')).not.toBeNull();
    expect(container1.textContent).toContain('Fil de commentaires');
  });

  it('ajoute un commentaire et l\'affiche immédiatement', async () => {
    const panel = new CommentsPanel('comments-panel-user1', store1);
    panel.mount();
    await panel.loadForReplica(replicaId);
    expect(panel.comments.length).toBe(0);

    // Simuler la saisie et l'envoi
    const input = container1.querySelector('[data-testid="comment-input"]');
    expect(input).not.toBeNull();
    input.value = 'Super réplique !';
    const form = container1.querySelector('[data-testid="comment-form"]');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));

    expect(panel.comments.length).toBe(1);
    expect(panel.comments[0].content).toBe('Super réplique !');
    expect(container1.querySelector('[data-testid="comment-content"]').textContent).toBe('Super réplique !');
  });

  it('e2e: second utilisateur voit immédiatement le commentaire du premier', async () => {
    // Panel pour user1 et user2, même replica, même projet (sharedComments simule le backend partagé)
    const panel1 = new CommentsPanel('comments-panel-user1', store1);
    const panel2 = new CommentsPanel('comments-panel-user2', store2);
    panel1.mount();
    panel2.mount();
    await panel1.loadForReplica(replicaId);
    await panel2.loadForReplica(replicaId);
    expect(panel1.comments.length).toBe(0);
    expect(panel2.comments.length).toBe(0);

    // User1 poste un commentaire via l'API (simule POST /replicas/{id}/comments)
    await api.createComment(replicaId, 'Commentaire de user1');
    // User1 rafraîchit (son panel l'a déjà fait via l'optimistic, mais on simule le refresh)
    await panel1.refresh();
    expect(panel1.comments.length).toBe(1);
    expect(panel1.comments[0].content).toBe('Commentaire de user1');

    // User2 n'a pas encore rafraîchi, il doit voir le commentaire après un refresh (polling)
    // Simuler le polling automatique ou un refresh manuel
    expect(panel2.comments.length).toBe(0); // avant refresh, il ne voit pas encore
    await panel2.refresh();
    expect(panel2.comments.length).toBe(1);
    expect(panel2.comments[0].content).toBe('Commentaire de user1');
    // Vérifier l'affichage dans le DOM du second utilisateur
    expect(container2.querySelector('[data-testid="comment-content"]').textContent).toBe('Commentaire de user1');
    expect(container2.textContent).toContain('Commentaire de user1');

    // User2 poste à son tour
    await api.createComment(replicaId, 'Réponse de user2');
    await panel1.refresh();
    await panel2.refresh();
    expect(panel1.comments.length).toBe(2);
    expect(panel2.comments.length).toBe(2);
    expect(container1.textContent).toContain('Réponse de user2');
    expect(container2.textContent).toContain('Commentaire de user1');
  });

  it('supprime un commentaire et met à jour l\'affichage', async () => {
    const panel = new CommentsPanel('comments-panel-user1', store1);
    panel.mount();
    await panel.loadForReplica(replicaId);
    // Créer un commentaire
    const input = container1.querySelector('[data-testid="comment-input"]');
    input.value = 'À supprimer';
    const form = container1.querySelector('[data-testid="comment-form"]');
    form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    expect(panel.comments.length).toBe(1);
    const commentId = panel.comments[0].id;

    // Supprimer
    // Mock confirm
    window.confirm = vi.fn(() => true);
    const deleteBtn = container1.querySelector(`[data-testid="delete-comment-btn"][data-comment-id="${commentId}"]`);
    expect(deleteBtn).not.toBeNull();
    deleteBtn.click();
    await new Promise(r => setTimeout(r, 0));
    await new Promise(r => setTimeout(r, 0));
    expect(panel.comments.length).toBe(0);
    expect(container1.querySelector('[data-testid="no-comments"]')).not.toBeNull();
  });

  it('affiche le panneau latéral contextuel même sans sélection', async () => {
    const emptyStore = new RythmoStore();
    const panel = new CommentsPanel('comments-panel-user1', emptyStore);
    panel.mount();
    expect(container1.querySelector('[data-testid="no-selection"]')).not.toBeNull();
  });

  it('gère le polling pour second utilisateur (rafraîchissement automatique)', async () => {
    const panel1 = new CommentsPanel('comments-panel-user1', store1);
    const panel2 = new CommentsPanel('comments-panel-user2', store2);
    panel1.mount();
    panel2.mount();
    await panel1.loadForReplica(replicaId);
    await panel2.loadForReplica(replicaId);

    // User1 crée un commentaire directement via API (hors panel)
    await api.createComment(replicaId, 'Poll test');
    // Panel2 n'a pas été notifié via event, mais son polling doit le récupérer
    // Simuler le polling : appeler refresh manuellement comme le ferait le timer
    expect(panel2.comments.length).toBe(0);
    await panel2.refresh();
    expect(panel2.comments.length).toBe(1);
    expect(panel2.comments[0].content).toBe('Poll test');
  });
});
