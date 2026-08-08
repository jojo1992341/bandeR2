import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { handleKeyDown, initReplicaEditor } from '../src/components/replica_editor.js';

/**
 * E2E-like test pour §14.4 : raccourcis Ctrl+Maj+S (scinder) / Ctrl+Maj+F (fusionner)
 * Vérifie le déclenchement via événement clavier.
 */

describe('Raccourcis éditeur §14.4', () => {
  let store;
  let apiMock;

  beforeEach(() => {
    store = new RythmoStore();
    apiMock = {
      splitReplica: vi.fn().mockResolvedValue({
        replicas: [
          { id: 'r-01-a', media_id: 'm-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, order_index: 0, confidence_score: 0.9, is_manually_edited: true },
          { id: 'r-01-b', media_id: 'm-01', text: 'le monde', start_ms: 1000, end_ms: 2000, order_index: 1, confidence_score: 0.9, is_manually_edited: true },
        ],
        split_ms: 1000,
        status: 'split',
      }),
      mergeReplicas: vi.fn().mockResolvedValue({
        replica: { id: 'r-merged', media_id: 'm-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2000, order_index: 0, confidence_score: 0.9, is_manually_edited: true },
        merged_count: 2,
        status: 'merged',
      }),
    };
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('Ctrl+Maj+S déclenche scission via handleKeyDown', async () => {
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2000, order_index: 0 },
    ]);
    store.selectReplica('r-01');
    store.setPlayhead(1000);

    const event = {
      ctrlKey: true,
      shiftKey: true,
      key: 'S',
      preventDefault: vi.fn(),
    };

    const promise = handleKeyDown(event, store, apiMock);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(apiMock.splitReplica).toHaveBeenCalledTimes(1);
    expect(apiMock.splitReplica).toHaveBeenCalledWith('r-01', 1000);

    await promise;

    // Après scission, le store doit contenir 2 répliques
    expect(store.replicas.length).toBe(2);
    expect(store.replicas[0].id).toBe('r-01-a');
    expect(store.replicas[1].id).toBe('r-01-b');
    // Timing cohérent
    expect(store.replicas[0].end_ms).toBe(1000);
    expect(store.replicas[1].start_ms).toBe(1000);
    expect(store.replicas[0].start_ms).toBe(0);
    expect(store.replicas[1].end_ms).toBe(2000);
  });

  it('Ctrl+Maj+S utilise milieu si playhead hors intervalle', async () => {
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Hello world', start_ms: 1000, end_ms: 3000, order_index: 0 },
    ]);
    store.selectReplica('r-01');
    store.setPlayhead(5000); // hors intervalle

    const event = { ctrlKey: true, shiftKey: true, key: 's', preventDefault: vi.fn() };
    const p = handleKeyDown(event, store, apiMock);
    expect(apiMock.splitReplica).toHaveBeenCalledWith('r-01', 2000); // milieu 1000+3000/2
    await p;
    expect(store.replicas.length).toBe(2);
  });

  it('Ctrl+Maj+F déclenche fusion via handleKeyDown', async () => {
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, order_index: 0 },
      { id: 'r-02', media_id: 'm-01', text: 'le monde', start_ms: 1000, end_ms: 2000, order_index: 1 },
      { id: 'r-03', media_id: 'm-01', text: 'du doublage', start_ms: 2000, end_ms: 3000, order_index: 2 },
    ]);
    store.selectReplica('r-01');
    store.setPlayhead(500);

    const event = {
      ctrlKey: true,
      shiftKey: true,
      key: 'F',
      preventDefault: vi.fn(),
    };

    const promise = handleKeyDown(event, store, apiMock);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(apiMock.mergeReplicas).toHaveBeenCalledTimes(1);
    expect(apiMock.mergeReplicas).toHaveBeenCalledWith(['r-01', 'r-02']);

    await promise;

    // Après fusion, une seule réplique fusionnée + r-03 = 2 au total
    expect(store.replicas.length).toBe(2);
    const merged = store.replicas.find((r) => r.id === 'r-merged');
    expect(merged).toBeDefined();
    expect(merged.start_ms).toBe(0);
    expect(merged.end_ms).toBe(2000);
  });

  it('Ctrl+Maj+F ne déclenche rien si pas de sélection ou pas de suivante', () => {
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, order_index: 0 },
    ]);
    store.selectReplica('r-01');
    const event = { ctrlKey: true, shiftKey: true, key: 'F', preventDefault: vi.fn() };
    const res = handleKeyDown(event, store, apiMock);
    expect(apiMock.mergeReplicas).not.toHaveBeenCalled();
    expect(res).toBeUndefined();

    // Aucune sélection
    store.selectReplica(null);
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, order_index: 0 },
      { id: 'r-02', media_id: 'm-01', text: 'le monde', start_ms: 1000, end_ms: 2000, order_index: 1 },
    ]);
    handleKeyDown(event, store, apiMock);
    expect(apiMock.mergeReplicas).not.toHaveBeenCalled();
  });

  it('initReplicaEditor enregistre le listener et réagit au keydown DOM', async () => {
    store.setReplicas([
      { id: 'r-01', media_id: 'm-01', text: 'Bonjour le monde', start_ms: 0, end_ms: 2000, order_index: 0 },
    ]);
    store.selectReplica('r-01');
    store.setPlayhead(1000);

    const editor = initReplicaEditor(store, apiMock);

    const event = new KeyboardEvent('keydown', { key: 'S', ctrlKey: true, shiftKey: true, bubbles: true });
    document.dispatchEvent(event);

    // Attendre microtask pour la promesse
    await new Promise((r) => setTimeout(r, 0));
    // Le mock doit avoir été appelé via le listener DOM
    expect(apiMock.splitReplica).toHaveBeenCalled();

    editor.destroy();
    vi.clearAllMocks();

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'S', ctrlKey: true, shiftKey: true, bubbles: true }));
    await new Promise((r) => setTimeout(r, 0));
    expect(apiMock.splitReplica).not.toHaveBeenCalled();
  });

  it('ignore les combinaisons sans Ctrl+Shift', () => {
    store.setReplicas([{ id: 'r-01', media_id: 'm-01', text: 'test', start_ms: 0, end_ms: 1000, order_index: 0 }]);
    store.selectReplica('r-01');
    const event = { ctrlKey: true, shiftKey: false, key: 'S', preventDefault: vi.fn() };
    handleKeyDown(event, store, apiMock);
    expect(apiMock.splitReplica).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();

    const event2 = { ctrlKey: false, shiftKey: true, key: 'F', preventDefault: vi.fn() };
    handleKeyDown(event2, store, apiMock);
    expect(apiMock.mergeReplicas).not.toHaveBeenCalled();
  });
});
