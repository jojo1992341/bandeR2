import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { handleKeyDown } from '../src/components/replica_editor.js';

describe('Store Command pattern undo/redo §7.3 + raccourcis §14.4', () => {
  let store;
  const initialReplica = {
    id: 'r-01',
    media_id: 'm-01',
    text: 'Bonjour le monde',
    start_ms: 1000,
    end_ms: 3000,
    order_index: 0,
    speaker_id: 'spk-01',
    typo_codes: {},
    confidence_score: 0.92,
  };

  beforeEach(() => {
    store = new RythmoStore();
    store.setReplicas([initialReplica]);
    store.clearHistory?.();
    // s'assurer que l'historique est vide après setReplicas initial
    store.clearHistory();
  });

  it('déplacement (move) → undo → redo restaure exactement l\'état', () => {
    const before = JSON.parse(JSON.stringify(store.replicas[0]));
    // Déplacement : de 1000-3000 à 1500-3500 (delta +500)
    store.moveReplica('r-01', 1500, 3500);
    const afterMove = store.replicas[0];
    expect(afterMove.start_ms).toBe(1500);
    expect(afterMove.end_ms).toBe(3500);
    expect(store.undoStack.length).toBe(1);
    expect(store.redoStack.length).toBe(0);

    // Undo doit restaurer exactement l'état initial
    store.undo();
    const afterUndo = store.replicas[0];
    expect(afterUndo.start_ms).toBe(before.start_ms);
    expect(afterUndo.end_ms).toBe(before.end_ms);
    expect(afterUndo.text).toBe(before.text);
    expect(store.undoStack.length).toBe(0);
    expect(store.redoStack.length).toBe(1);

    // Redo doit restaurer exactement l'état après move
    store.redo();
    const afterRedo = store.replicas[0];
    expect(afterRedo.start_ms).toBe(1500);
    expect(afterRedo.end_ms).toBe(3500);
    expect(afterRedo).toEqual(afterMove);
    expect(store.undoStack.length).toBe(1);
    expect(store.redoStack.length).toBe(0);
  });

  it('redimensionnement (resize) → undo → redo', () => {
    const before = JSON.parse(JSON.stringify(store.replicas[0]));
    // Resize : étendre la fin de 3000 à 4000
    store.resizeReplica('r-01', 1000, 4000);
    expect(store.replicas[0].start_ms).toBe(1000);
    expect(store.replicas[0].end_ms).toBe(4000);

    store.undo();
    expect(store.replicas[0].start_ms).toBe(before.start_ms);
    expect(store.replicas[0].end_ms).toBe(before.end_ms);

    store.redo();
    expect(store.replicas[0].end_ms).toBe(4000);
  });

  it('redimensionnement par bord (resize edge) → undo → redo', () => {
    store.resizeReplicaByEdge('r-01', 'right', 5000);
    expect(store.replicas[0].end_ms).toBe(5000);
    store.undo();
    expect(store.replicas[0].end_ms).toBe(3000);
    store.redo();
    expect(store.replicas[0].end_ms).toBe(5000);
  });

  it('édition de texte → undo → redo', () => {
    const beforeText = store.replicas[0].text;
    store.editReplicaText('r-01', 'Hello world');
    expect(store.replicas[0].text).toBe('Hello world');
    expect(store.undoStack.length).toBe(1);

    store.undo();
    expect(store.replicas[0].text).toBe(beforeText);

    store.redo();
    expect(store.replicas[0].text).toBe('Hello world');
  });

  it('changement de code typo → undo → redo', () => {
    const beforeTypo = JSON.parse(JSON.stringify(store.replicas[0].typo_codes));
    expect(beforeTypo).toEqual({});

    store.updateTypoCodes('r-01', { italique: true });
    expect(store.replicas[0].typo_codes).toEqual({ italique: true });

    // Ajout d'un second code doit merger mais être une commande distincte
    store.updateTypoCodes('r-01', { crochets: true, italique: true });
    expect(store.replicas[0].typo_codes).toEqual({ italique: true, crochets: true });

    // Undo du dernier changement (crochets)
    store.undo();
    expect(store.replicas[0].typo_codes).toEqual({ italique: true });

    // Undo du premier (italique)
    store.undo();
    expect(store.replicas[0].typo_codes).toEqual({});

    // Redo deux fois doit restaurer l'état final
    store.redo();
    expect(store.replicas[0].typo_codes).toEqual({ italique: true });
    store.redo();
    expect(store.replicas[0].typo_codes).toEqual({ italique: true, crochets: true });
  });

  it('toggleTypoCode → undo → redo', () => {
    store.toggleTypoCode('r-01', 'majuscules', true);
    expect(store.replicas[0].typo_codes.majuscules).toBe(true);
    store.undo();
    expect(store.replicas[0].typo_codes.majuscules).toBeUndefined();
    store.redo();
    expect(store.replicas[0].typo_codes.majuscules).toBe(true);
  });

  it('séquence complète : déplacement → resize → edit → typo → undo×4 → redo×4 restaure exactement', () => {
    const initial = JSON.parse(JSON.stringify(store.replicas[0]));

    // 1. Déplacement
    store.moveReplica('r-01', 1200, 3200);
    const s1 = JSON.parse(JSON.stringify(store.replicas[0]));
    expect(s1.start_ms).toBe(1200);

    // 2. Redimensionnement
    store.resizeReplica('r-01', 1200, 4000);
    const s2 = JSON.parse(JSON.stringify(store.replicas[0]));
    expect(s2.end_ms).toBe(4000);

    // 3. Édition texte
    store.editReplicaText('r-01', 'Texte modifié');
    const s3 = JSON.parse(JSON.stringify(store.replicas[0]));
    expect(s3.text).toBe('Texte modifié');

    // 4. Typo
    store.updateTypoCodes('r-01', { parentheses: true });
    const s4 = JSON.parse(JSON.stringify(store.replicas[0]));
    expect(s4.typo_codes.parentheses).toBe(true);
    expect(store.undoStack.length).toBe(4);

    // Undo pas à pas
    store.undo(); // undo typo
    expect(store.replicas[0]).toEqual(s3);
    store.undo(); // undo edit
    expect(store.replicas[0]).toEqual(s2);
    store.undo(); // undo resize
    expect(store.replicas[0]).toEqual(s1);
    store.undo(); // undo move
    expect(store.replicas[0]).toEqual(initial);
    expect(store.undoStack.length).toBe(0);
    expect(store.redoStack.length).toBe(4);

    // Redo pas à pas
    store.redo();
    expect(store.replicas[0]).toEqual(s1);
    store.redo();
    expect(store.replicas[0]).toEqual(s2);
    store.redo();
    expect(store.replicas[0]).toEqual(s3);
    store.redo();
    expect(store.replicas[0]).toEqual(s4);
    expect(store.redoStack.length).toBe(0);
  });

  it('nouvelle action après undo vide la pile redo', () => {
    store.editReplicaText('r-01', 'v1');
    store.editReplicaText('r-01', 'v2');
    expect(store.undoStack.length).toBe(2);
    store.undo();
    expect(store.redoStack.length).toBe(1);
    // Nouvelle action doit vider redo
    store.editReplicaText('r-01', 'v3');
    expect(store.redoStack.length).toBe(0);
    expect(store.replicas[0].text).toBe('v3');
    // Redo ne doit rien faire
    store.redo();
    expect(store.replicas[0].text).toBe('v3');
  });

  it('raccourcis clavier Ctrl+Z / Ctrl+Y déclenchent undo/redo §14.4', () => {
    store.editReplicaText('r-01', 'après edit');
    expect(store.replicas[0].text).toBe('après edit');

    // Ctrl+Z → undo
    const eventUndo = { ctrlKey: true, metaKey: false, shiftKey: false, key: 'z', preventDefault: vi.fn() };
    const r1 = handleKeyDown(eventUndo, store, { splitReplica: vi.fn(), mergeReplicas: vi.fn() });
    expect(eventUndo.preventDefault).toHaveBeenCalled();
    expect(r1).toBe('undo');
    expect(store.replicas[0].text).toBe('Bonjour le monde');

    // Ctrl+Y → redo
    const eventRedo = { ctrlKey: true, shiftKey: false, key: 'y', preventDefault: vi.fn() };
    const r2 = handleKeyDown(eventRedo, store, { splitReplica: vi.fn(), mergeReplicas: vi.fn() });
    expect(eventRedo.preventDefault).toHaveBeenCalled();
    expect(r2).toBe('redo');
    expect(store.replicas[0].text).toBe('après edit');
  });

  it('Ctrl+Maj+Z est alias de redo (comme Ctrl+Y)', () => {
    store.editReplicaText('r-01', 'v1');
    store.undo();
    expect(store.replicas[0].text).toBe('Bonjour le monde');
    const event = { ctrlKey: true, shiftKey: true, key: 'z', preventDefault: vi.fn() };
    handleKeyDown(event, store, { splitReplica: vi.fn(), mergeReplicas: vi.fn() });
    expect(store.replicas[0].text).toBe('v1');
  });

  it('updateReplica générique est aussi undoable (compatibilité)', () => {
    const before = JSON.parse(JSON.stringify(store.replicas[0]));
    store.updateReplica('r-01', { text: 'generic', start_ms: 2000 });
    expect(store.replicas[0].text).toBe('generic');
    expect(store.replicas[0].start_ms).toBe(2000);
    store.undo();
    expect(store.replicas[0]).toEqual(before);
    store.redo();
    expect(store.replicas[0].text).toBe('generic');
  });

  it('undo sans historique ne fait rien', () => {
    const snapshot = JSON.parse(JSON.stringify(store.replicas));
    store.undo();
    store.undo();
    expect(store.replicas).toEqual(snapshot);
    store.redo();
    expect(store.replicas).toEqual(snapshot);
  });

  it('couvre les 4 types via le pattern Command (vérifie les labels)', () => {
    store.moveReplica('r-01', 0, 2000);
    expect(store.undoStack[store.undoStack.length - 1].label).toBe('move');
    store.clearHistory();
    store.resizeReplica('r-01', 0, 2500);
    expect(store.undoStack[store.undoStack.length - 1].label).toBe('resize');
    store.clearHistory();
    store.editReplicaText('r-01', 'new');
    expect(store.undoStack[store.undoStack.length - 1].label).toBe('editText');
    store.clearHistory();
    store.updateTypoCodes('r-01', { italique: true });
    expect(store.undoStack[store.undoStack.length - 1].label).toBe('typo');
  });
});
