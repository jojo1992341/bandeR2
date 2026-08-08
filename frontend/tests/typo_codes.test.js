import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { applyTypoCode, handleTypoEvent } from '../src/components/replica_editor.js';
import { formatReplicaText, getTypoStyles } from '../src/components/rythmo_track.js';

// Charger le web component
import '../src/components/rythmo_track.js';

describe('Codes typographiques métier §2.4 / §9.4', () => {
  describe('formatReplicaText helper', () => {
    it('applique crochets [ ]', () => {
      expect(formatReplicaText('Bonjour', { crochets: true })).toBe('[ Bonjour ]');
      expect(formatReplicaText('Bonjour', { brackets: true })).toBe('[ Bonjour ]');
    });
    it('applique italique (même texte, style séparé)', () => {
      // italique ne change pas le texte brut, seulement le style
      expect(formatReplicaText('Bonjour', { italique: true })).toBe('Bonjour');
      expect(formatReplicaText('Bonjour', { italic: true })).toBe('Bonjour');
      expect(getTypoStyles({ italique: true })).toContain('italic');
    });
    it('applique MAJUSCULES', () => {
      expect(formatReplicaText('Bonjour le monde', { majuscules: true })).toBe('BONJOUR LE MONDE');
      expect(formatReplicaText('cri', { uppercase: true })).toBe('CRI');
      expect(getTypoStyles({ majuscules: true })).toContain('uppercase');
    });
    it('applique parentheses', () => {
      expect(formatReplicaText('chuchote', { parentheses: true })).toBe('(chuchote)');
    });
    it('combine plusieurs codes', () => {
      const t = formatReplicaText('Alerte', { crochets: true, majuscules: true });
      expect(t).toBe('[ ALERTE ]');
      const t2 = formatReplicaText('off', { parentheses: true, italique: true });
      expect(t2).toBe('(off)');
      expect(getTypoStyles({ italique: true, majuscules: true })).toContain('italic');
    });
  });

  describe('RythmoTrack rendu visuel', () => {
    let el;
    beforeEach(() => {
      el = document.createElement('rythmo-track');
      document.body.appendChild(el);
    });
    afterEach(() => {
      el.remove();
    });

    it('rend le texte brut sans typo', () => {
      el.setAttribute('replica-id', 'r-01');
      el.setAttribute('text', 'Bonjour');
      el.setAttribute('typo-codes', JSON.stringify({}));
      const textEl = el.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.textContent).toBe('Bonjour');
      expect(textEl.className).not.toContain('typo-italique');
    });

    it('reflète visuellement italique (voix off)', () => {
      el.setAttribute('replica-id', 'r-02');
      el.setAttribute('text', 'Allo');
      el.setAttribute('typo-codes', JSON.stringify({ italique: true }));
      const textEl = el.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.className).toContain('typo-italique');
      expect(textEl.style.fontStyle).toBe('italic');
    });

    it('reflète visuellement crochets [ ]', () => {
      el.setAttribute('text', 'Entre');
      el.setAttribute('typo-codes', JSON.stringify({ crochets: true }));
      const textEl = el.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.textContent).toBe('[ Entre ]');
      expect(textEl.className).toContain('typo-crochets');
    });

    it('reflète visuellement majuscules (cris)', () => {
      el.setAttribute('text', 'au secours');
      el.setAttribute('typo-codes', JSON.stringify({ majuscules: true }));
      const textEl = el.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.textContent).toBe('AU SECOURS');
      expect(textEl.className).toContain('typo-majuscules');
    });

    it('reflète visuellement parentheses (jeu)', () => {
      el.setAttribute('text', 'en riant');
      el.setAttribute('typo-codes', JSON.stringify({ parentheses: true }));
      const textEl = el.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.textContent).toBe('(en riant)');
      expect(textEl.className).toContain('typo-parentheses');
    });

    it('affiche le menu clic droit avec les 4 codes métier', () => {
      el.setAttribute('replica-id', 'r-99');
      el.setAttribute('text', 'Test');
      el.setAttribute('typo-codes', JSON.stringify({ italique: true }));
      const track = el.shadowRoot.querySelector('.track');
      // Simuler clic droit
      const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true });
      track.dispatchEvent(event);
      const menu = el.shadowRoot.querySelector('[data-testid="typo-menu"]');
      expect(menu).not.toBeNull();
      expect(menu.querySelector('[data-code="crochets"]')).not.toBeNull();
      expect(menu.querySelector('[data-code="italique"]')).not.toBeNull();
      expect(menu.querySelector('[data-code="majuscules"]')).not.toBeNull();
      expect(menu.querySelector('[data-code="parentheses"]')).not.toBeNull();
      // Italique doit être actif
      const italicBtn = menu.querySelector('[data-code="italique"]');
      expect(italicBtn.classList.contains('active')).toBe(true);
    });
  });

  describe('applyTypoCode via API + store', () => {
    let store;
    let apiMock;

    beforeEach(() => {
      store = new RythmoStore();
      store.setReplicas([
        { id: 'r-01', media_id: 'm-01', text: 'Bonjour', start_ms: 0, end_ms: 1000, order_index: 0, typo_codes: {} },
      ]);
      apiMock = {
        patchReplica: vi.fn().mockImplementation((id, payload) => {
          // Simuler la réponse backend normalisée
          const typo = payload.typo_codes;
          return Promise.resolve({ id, status: 'updated', typo_codes: typo, replica: { id, typo_codes: typo } });
        }),
        splitReplica: vi.fn(),
        mergeReplicas: vi.fn(),
      };
    });

    it('met à jour typo_codes côté API et store', async () => {
      const res = await applyTypoCode('r-01', 'italique', true, store, apiMock);
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-01', { typo_codes: { italique: true } });
      expect(store.replicas[0].typo_codes).toEqual({ italique: true });
      expect(res.typo_codes).toEqual({ italique: true });
    });

    it('merge les codes existants (pas d\'écrasement)', async () => {
      store.replicas[0].typo_codes = { crochets: true };
      await applyTypoCode('r-01', 'majuscules', true, store, apiMock);
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-01', { typo_codes: { crochets: true, majuscules: true } });
      expect(store.replicas[0].typo_codes).toEqual({ crochets: true, majuscules: true });
    });

    it('désactive un code (toggle off)', async () => {
      store.replicas[0].typo_codes = { italique: true, crochets: true };
      await applyTypoCode('r-01', 'italique', false, store, apiMock);
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-01', { typo_codes: { crochets: true } });
      expect(store.replicas[0].typo_codes).toEqual({ crochets: true });
      expect(store.replicas[0].typo_codes).not.toHaveProperty('italique');
    });

    it('normalise les alias (brackets -> crochets, uppercase -> majuscules)', async () => {
      await applyTypoCode('r-01', 'brackets', true, store, apiMock);
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-01', expect.objectContaining({ typo_codes: { crochets: true } }));
      await applyTypoCode('r-01', 'uppercase', true, store, apiMock);
      // Le second appel doit merger avec crochets déjà présent dans store
      expect(store.replicas[0].typo_codes).toHaveProperty('majuscules');
    });

    it('met à jour le DOM rythmo-track après patch', async () => {
      const track = document.createElement('rythmo-track');
      track.setAttribute('replica-id', 'r-01');
      track.setAttribute('text', 'Bonjour');
      track.setAttribute('typo-codes', JSON.stringify({}));
      document.body.appendChild(track);

      await applyTypoCode('r-01', 'italique', true, store, apiMock);
      // Le track doit avoir été mis à jour
      expect(track.getAttribute('typo-codes')).toContain('italique');
      const textEl = track.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.className).toContain('typo-italique');

      track.remove();
    });
  });

  describe('handleTypoEvent (clic droit) e2e', () => {
    let store;
    let apiMock;

    beforeEach(() => {
      store = new RythmoStore();
      store.setReplicas([
        { id: 'r-42', media_id: 'm-01', text: 'Test', start_ms: 0, end_ms: 1000, order_index: 0, typo_codes: {} },
      ]);
      apiMock = {
        patchReplica: vi.fn().mockResolvedValue({ id: 'r-42', status: 'updated', typo_codes: { crochets: true } }),
        splitReplica: vi.fn(),
        mergeReplicas: vi.fn(),
      };
    });

    it('déclenché via événement rythmo:typo (clic droit menu)', async () => {
      const event = new CustomEvent('rythmo:typo', {
        detail: { id: 'r-42', code: 'crochets', value: true },
        bubbles: true,
      });
      const p = handleTypoEvent(event, store, apiMock);
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-42', { typo_codes: { crochets: true } });
      await p;
      expect(store.replicas[0].typo_codes).toEqual({ crochets: true });
    });

    it('initReplicaEditor écoute rythmo:typo sur document', async () => {
      const { initReplicaEditor } = await import('../src/components/replica_editor.js');
      const editor = initReplicaEditor(store, apiMock);
      const ev = new CustomEvent('rythmo:typo', { detail: { id: 'r-42', code: 'parentheses', value: true } });
      document.dispatchEvent(ev);
      await new Promise((r) => setTimeout(r, 0));
      expect(apiMock.patchReplica).toHaveBeenCalled();
      editor.destroy();
    });

    it('clic droit réel sur rythmo-track déclenche le flow complet (e2e visuel)', async () => {
      // Créer un track réel et simuler le menu
      const track = document.createElement('rythmo-track');
      track.setAttribute('replica-id', 'r-42');
      track.setAttribute('text', 'Au secours');
      track.setAttribute('typo-codes', JSON.stringify({}));
      document.body.appendChild(track);
      store.setReplicas([
        { id: 'r-42', media_id: 'm-01', text: 'Au secours', start_ms: 0, end_ms: 1000, order_index: 0, typo_codes: {} },
      ]);

      // Attacher l'éditeur qui écoute les events
      const { initReplicaEditor: init } = await import('../src/components/replica_editor.js');
      const ed = init(store, apiMock);
      // Patch pour que le mock renvoie la bonne valeur majuscules
      apiMock.patchReplica.mockResolvedValueOnce({ id: 'r-42', typo_codes: { majuscules: true }, status: 'updated' });

      // Simuler contextmenu pour ouvrir le menu
      const trackDiv = track.shadowRoot.querySelector('.track');
      trackDiv.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }));
      const menu = track.shadowRoot.querySelector('[data-testid="typo-menu"]');
      expect(menu).not.toBeNull();
      const btn = menu.querySelector('[data-code="majuscules"]');
      expect(btn).not.toBeNull();
      // Cliquer sur MAJUSCULES
      btn.click();
      await new Promise((r) => setTimeout(r, 0));
      expect(apiMock.patchReplica).toHaveBeenCalledWith('r-42', expect.objectContaining({ typo_codes: expect.objectContaining({ majuscules: true }) }));
      // Vérifier le store a été mis à jour
      expect(store.replicas[0].typo_codes).toHaveProperty('majuscules');
      // Vérifier le rendu visuel majuscules (texte en uppercase)
      // Le track a été mis à jour via applyTypoCode qui setAttribute
      expect(track.getAttribute('typo-codes')).toContain('majuscules');
      const textEl = track.shadowRoot.querySelector('[data-testid="replica-text"]');
      expect(textEl.textContent).toBe('AU SECOURS');

      ed.destroy();
      track.remove();
    });
  });
});
