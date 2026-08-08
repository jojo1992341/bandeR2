import { describe, it, expect, beforeEach, vi } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { renderTypographicProfiles, loadTypographicProfiles, createTypographicProfile, patchTypographicProfiles } from '../src/components/typographic_profiles_panel.js';
import { api } from '../src/services/api.js';

describe('TypographicProfilesPanel §2.4 / §10.2 / §16.3', () => {
  let store;
  beforeEach(() => {
    store = new RythmoStore();
  });

  it('rend une liste vide correctement', () => {
    const html = renderTypographicProfiles(store);
    expect(html).toContain('Aucun profil');
  });

  it('rend les profils avec codes et seuils', () => {
    store.setTypographicProfiles([
      { id: 'p1', name: 'Netflix FR', codes: { crochets: true, majuscules: true }, thresholds: { silence_ms: 200, max_duration_ms: 8000 }, is_default: true, description: 'Profil Netflix' },
      { id: 'p2', name: 'TF1', codes: { italique: true }, thresholds: { silence_ms: 600 }, is_default: false },
    ]);
    const html = renderTypographicProfiles(store);
    expect(html).toContain('Netflix FR');
    expect(html).toContain('TF1');
    expect(html).toContain('crochets');
    expect(html).toContain('majuscules');
    expect(html).toContain('silence_ms=200');
    expect(html).toContain('Défaut');
    expect(html).toContain('Profil Netflix');
  });

  it('charge les profils depuis l\'API et met à jour le store', async () => {
    const mockData = {
      studio_id: 'studio-1',
      count: 1,
      profiles: [{ id: 'p1', name: 'Default', codes: { crochets: true }, thresholds: { silence_ms: 500 }, is_default: true }],
      default_profile: { id: 'p1', name: 'Default', codes: { crochets: true }, thresholds: { silence_ms: 500 }, is_default: true }
    };
    const spy = vi.spyOn(api, 'getTypographicProfiles').mockResolvedValue(mockData);
    const result = await loadTypographicProfiles('studio-1', store, api);
    expect(spy).toHaveBeenCalledWith('studio-1');
    expect(store.getTypographicProfiles()).toHaveLength(1);
    expect(store.getTypographicProfiles()[0].name).toBe('Default');
    expect(store.getCurrentTypographicProfile().name).toBe('Default');
    spy.mockRestore();
  });

  it('crée un profil et recharge la liste', async () => {
    const created = { id: 'p2', name: 'Arte', codes: { parentheses: true }, thresholds: { silence_ms: 400 }, is_default: false };
    const spyCreate = vi.spyOn(api, 'createTypographicProfile').mockResolvedValue(created);
    const spyGet = vi.spyOn(api, 'getTypographicProfiles').mockResolvedValue({
      studio_id: 'studio-1',
      count: 2,
      profiles: [
        { id: 'p1', name: 'Default', codes: {}, thresholds: {}, is_default: true },
        created
      ]
    });
    const result = await createTypographicProfile('studio-1', { name: 'Arte', codes: { parentheses: true } }, store, api);
    expect(spyCreate).toHaveBeenCalledWith('studio-1', { name: 'Arte', codes: { parentheses: true } });
    expect(result.name).toBe('Arte');
    expect(store.getTypographicProfiles()).toHaveLength(2);
    spyCreate.mockRestore();
    spyGet.mockRestore();
  });

  it('patch bulk plusieurs profils (§16.3 plusieurs profils par studio)', async () => {
    const spyPatch = vi.spyOn(api, 'patchTypographicProfiles').mockResolvedValue({
      studio_id: 'studio-1',
      count: 2,
      profiles: [
        { id: 'p1', name: 'Netflix FR', codes: { majuscules: true }, thresholds: { silence_ms: 250 }, is_default: true },
        { id: 'p2', name: 'Arte', codes: { parentheses: true }, thresholds: { silence_ms: 400 }, is_default: false }
      ]
    });
    const spyGet = vi.spyOn(api, 'getTypographicProfiles').mockResolvedValue({
      studio_id: 'studio-1',
      count: 2,
      profiles: [
        { id: 'p1', name: 'Netflix FR', codes: { majuscules: true }, thresholds: { silence_ms: 250 }, is_default: true },
        { id: 'p2', name: 'Arte', codes: { parentheses: true }, thresholds: { silence_ms: 400 }, is_default: false }
      ]
    });
    await patchTypographicProfiles('studio-1', { profiles: [{ name: 'Netflix FR', codes: { majuscules: true } }, { name: 'Arte', codes: { parentheses: true } }] }, store, api);
    expect(spyPatch).toHaveBeenCalled();
    expect(store.getTypographicProfiles()).toHaveLength(2);
    spyPatch.mockRestore();
    spyGet.mockRestore();
  });

  it('gère le store current profile', () => {
    store.setTypographicProfiles([
      { id: 'p1', name: 'A', codes: {}, thresholds: {}, is_default: false },
      { id: 'p2', name: 'B', codes: {}, thresholds: {}, is_default: true },
    ]);
    expect(store.getCurrentTypographicProfile().name).toBe('B');
    expect(store.getTypographicProfileById('p1').name).toBe('A');
    store.setCurrentTypographicProfile({ id: 'p1', name: 'A' });
    expect(store.getCurrentTypographicProfile().id).toBe('p1');
  });
});
