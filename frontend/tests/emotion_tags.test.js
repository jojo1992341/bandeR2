import { describe, it, expect, beforeEach, vi } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { renderEmotionTags, EmotionTagsPanel, loadEmotionTags } from '../src/components/emotion_tags_panel.js';
import { api } from '../src/services/api.js';

describe('EmotionTagsPanel §8.2.5 — double analyse acoustique + NLP FR', () => {
  let store;

  beforeEach(() => {
    store = new RythmoStore();
  });

  it('affiche les EmotionTag à titre indicatif sans modifier le texte — seulement codes typo suggérés', () => {
    const replicaId = 'rep-1';
    // Simuler des tags produits par le pipeline
    const tags = [
      {
        id: 'tag1',
        replica_id: replicaId,
        tag_type: 'emotion',
        label: 'colere',
        score: 0.88,
        source: 'audio',
        suggested_typo_codes: { majuscules: true },
        details: { emotion: { label: 'colere' }, intention: { label: 'ordre' } },
      },
      {
        id: 'tag2',
        replica_id: replicaId,
        tag_type: 'intention',
        label: 'ordre',
        score: 0.9,
        source: 'texte',
        suggested_typo_codes: { majuscules: true },
        details: { emotion: { label: 'colere' }, intention: { label: 'ordre' } },
      },
    ];
    store.setEmotionTags(replicaId, tags);
    // Ajouter une réplique avec texte original
    store.setReplicas([{ id: replicaId, text: 'ARRÊTE TOUT DE SUITE !', typo_codes: {}, start_ms: 0, end_ms: 2000 }]);

    const html = renderEmotionTags(replicaId, store);
    // Doit contenir les labels émotion / intention
    expect(html).toContain('Colère');
    expect(html).toContain('Ordre');
    // Sources distinctes : audio vs texte
    expect(html).toContain('audio');
    expect(html).toContain('texte');
    // Codes suggérés présents — mais pas appliqués au typo_codes de la réplique
    expect(html).toContain('MAJ suggérées');
    expect(html).toContain('indicatif');
    expect(html).toContain('jamais modifié automatiquement');
    // Le texte original doit rester inchangé dans le store
    expect(store.replicas[0].text).toBe('ARRÊTE TOUT DE SUITE !');
    expect(store.replicas[0].typo_codes).toEqual({});
    // Les suggestions sont accessibles via le store mais ne sont pas dans typo_codes
    expect(store.getSuggestedTypoCodes(replicaId)).toEqual({ majuscules: true });
  });

  it('gère les différents cas de suggestions (hésitation → parenthèses, voix off → italique, question surprise → crochets)', () => {
    const cases = [
      { text: 'euh... je ne sais pas', tags: [{ tag_type: 'emotion', label: 'neutre', score: 0.6, source: 'audio', suggested_typo_codes: { parentheses: true } }, { tag_type: 'intention', label: 'hesitation', score: 0.88, source: 'texte', suggested_typo_codes: { parentheses: true } }], expected: 'Parenthèses' },
      { text: 'voix off au téléphone', tags: [{ tag_type: 'emotion', label: 'neutre', score: 0.65, source: 'audio', suggested_typo_codes: { italique: true } }, { tag_type: 'intention', label: 'affirmation', score: 0.75, source: 'texte', suggested_typo_codes: { italique: true } }], expected: 'Italique' },
      { text: 'Bonjour, comment vas-tu ?', tags: [{ tag_type: 'emotion', label: 'surprise', score: 0.76, source: 'audio', suggested_typo_codes: { crochets: true } }, { tag_type: 'intention', label: 'question', score: 0.95, source: 'texte', suggested_typo_codes: { crochets: true } }], expected: 'Crochets' },
    ];
    for (const c of cases) {
      const rid = `rep-${c.text.slice(0, 5)}`;
      store.setEmotionTags(rid, c.tags);
      const html = renderEmotionTags(rid, store);
      expect(html).toContain(c.expected);
    }
  });

  it('affiche un message vide si aucun tag et ne modifie jamais le texte', () => {
    const rid = 'rep-empty';
    store.setReplicas([{ id: rid, text: 'Texte à conserver', typo_codes: {} }]);
    const html = renderEmotionTags(rid, store);
    expect(html).toContain('Aucune analyse');
    expect(store.replicas[0].text).toBe('Texte à conserver');
  });

  it('charge les EmotionTag depuis l\'API et met à jour le store sans altérer le texte', async () => {
    const rid = 'rep-api';
    store.setReplicas([{ id: rid, text: 'Au secours !', typo_codes: {} }]);
    const mockTags = [
      { id: '1', replica_id: rid, tag_type: 'emotion', label: 'peur', score: 0.86, source: 'audio', suggested_typo_codes: { majuscules: true }, details: {} },
      { id: '2', replica_id: rid, tag_type: 'intention', label: 'exclamation', score: 0.92, source: 'texte', suggested_typo_codes: { majuscules: true }, details: {} },
    ];
    const spy = vi.spyOn(api, 'getReplicaEmotionTags').mockResolvedValue(mockTags);
    const result = await loadEmotionTags(rid, store, api);
    expect(spy).toHaveBeenCalledWith(rid);
    expect(result).toEqual(mockTags);
    expect(store.getEmotionTags(rid)).toEqual(mockTags);
    // Texte toujours inchangé
    expect(store.replicas[0].text).toBe('Au secours !');
    expect(store.replicas[0].typo_codes).toEqual({});
    spy.mockRestore();
  });

  it('les EmotionTag sont indicatifs : seul typo_codes suggéré, pas d\'écriture automatique', () => {
    const rid = 'rep-indicatif';
    const tags = [
      { tag_type: 'emotion', label: 'colere', score: 0.9, source: 'audio', suggested_typo_codes: { majuscules: true } },
      { tag_type: 'intention', label: 'ordre', score: 0.9, source: 'texte', suggested_typo_codes: { majuscules: true } },
    ];
    store.setEmotionTags(rid, tags);
    store.setReplicas([{ id: rid, text: 'texte original', typo_codes: {} }]);
    renderEmotionTags(rid, store);
    // Même après rendu, le store ne modifie pas typo_codes
    expect(store.replicas[0].typo_codes).toEqual({});
    // L'utilisateur doit appliquer manuellement via applyTypoCode s'il le souhaite — pas automatique
    expect(store.getSuggestedTypoCodes(rid)).toHaveProperty('majuscules', true);
  });
});
