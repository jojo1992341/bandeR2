/**
 * Test de convergence CRDT §16.4
 * Vérifie que deux éditions concurrentes sur la même réplique convergent sans perte
 */

import { describe, it, expect } from 'vitest';
import { TextCRDT } from '../src/crdt/text_crdt.js';

describe('CRDT Text — Convergence §16.4', () => {
  it('converge pour deux inserts concurrents à la même position', () => {
    const siteA = new TextCRDT('site-A', 'Hello');
    const siteB = new TextCRDT('site-B', 'Hello');

    expect(siteA.getText()).toBe('Hello');
    expect(siteB.getText()).toBe('Hello');

    // Site A insère X à pos 2 -> HeXllo
    const opA = siteA.insert(2, 'X');
    expect(siteA.getText()).toBe('HeXllo');

    // Site B insère Y à pos 2 sur l'état initial -> HeYllo
    const opB = siteB.insert(2, 'Y');
    expect(siteB.getText()).toBe('HeYllo');

    // Synchronisation : A reçoit B, B reçoit A
    siteA.insert(2, 'Y', 'site-B', opB.id.counter, opB.pos);
    siteB.insert(2, 'X', 'site-A', opA.id.counter, opA.pos);

    const textA = siteA.getText();
    const textB = siteB.getText();

    expect(textA).toBe(textB);
    expect(textA).toContain('X');
    expect(textA).toContain('Y');
    expect(textA.length).toBe('Hello'.length + 2);
    expect(['HeXYllo', 'HeYXllo'].includes(textA)).toBe(true);
  });

  it('converge pour delete + insert concurrents', () => {
    const siteA = new TextCRDT('site-A', 'Hello');
    const siteB = new TextCRDT('site-B', 'Hello');

    // A supprime 'e' à pos 1 -> Hllo
    siteA.delete(1);
    expect(siteA.getText()).toBe('Hllo');

    // B insère X à pos 2 -> HeXllo
    siteB.insert(2, 'X');
    expect(siteB.getText()).toBe('HeXllo');

    // Merge
    const stateA = siteA.getState();
    const stateB = siteB.getState();

    const mergedA = new TextCRDT('site-A', '');
    mergedA.setState(stateA);
    mergedA.merge(siteB);

    const mergedB = new TextCRDT('site-B', '');
    mergedB.setState(stateB);
    mergedB.merge(siteA);

    expect(mergedA.getText()).toBe(mergedB.getText());
    expect(mergedA.getText()).toContain('X');
    expect(mergedA.getText()).not.toContain('e');
  });

  it('converge quel que soit l\'ordre d\'application (commutativité)', () => {
    const opA = { pos: [1, 430], site: 'site-A', counter: 1, char: 'X' };
    const opB = { pos: [1, 293], site: 'site-B', counter: 1, char: 'Y' };

    // Ordre A puis B
    const crdt1 = new TextCRDT('site-A', 'Hello');
    crdt1.insert(2, 'X', 'site-A', 1, opA.pos);
    crdt1.insert(2, 'Y', 'site-B', 1, opB.pos);
    const text1 = crdt1.getText();

    // Ordre B puis A
    const crdt2 = new TextCRDT('site-B', 'Hello');
    crdt2.insert(2, 'Y', 'site-B', 1, opB.pos);
    crdt2.insert(2, 'X', 'site-A', 1, opA.pos);
    const text2 = crdt2.getText();

    expect(text1).toBe(text2);
    expect(text1).toBe('HeYXllo'); // Y avant X car site-B hash < site-A
  });

  it('préserve l\'ordre déterministe via siteId tie-breaker', () => {
    const crdt = new TextCRDT('site-A', 'Hello');
    // Deux inserts concurrents au même endroit, génèrent des pos différentes
    const opA = crdt.insert(2, 'X', 'site-A');
    // Simuler un autre site qui insère aussi à 2 mais avec un site différent
    const crdt2 = new TextCRDT('site-B', 'Hello');
    const opB = crdt2.insert(2, 'Y', 'site-B');

    // Les pos doivent être différentes mais toutes entre [1] et [2]
    expect(opA.pos).not.toEqual(opB.pos);
    // Le tri doit être déterministe
    const sorted = [opA, opB].sort((a, b) => {
      const len = Math.min(a.pos.length, b.pos.length);
      for (let i = 0; i < len; i++) if (a.pos[i] !== b.pos[i]) return a.pos[i] - b.pos[i];
      if (a.pos.length !== b.pos.length) return a.pos.length - b.pos.length;
      return a.id.site.localeCompare(b.id.site);
    });
    expect(sorted[0].char).toBe('Y'); // site-B hash 293 < site-A 430
    expect(sorted[1].char).toBe('X');
  });
});

describe('CRDT vs Verrouillage Optimiste', () => {
  it('montre que le verrouillage optimiste perd des données en cas de concurrence', () => {
    // Simuler deux PATCH avec même version
    let replica = { text: 'Hello', version: 1 };
    const patchA = { text: 'HeXllo', version: 1 };
    const patchB = { text: 'HeYllo', version: 1 };

    // Sans CRDT, le second PATCH avec version stale échoue en 409, ou écrase le premier
    // Ici on simule le fait que le second écrase le premier (perte de X)
    let state = { ...replica };
    // A applique
    if (patchA.version === state.version) {
      state = { text: patchA.text, version: 2 };
    }
    // B applique avec version stale 1 -> en vrai 409, mais si on force, il écrase
    if (true) { // force sans vérification
      state = { text: patchB.text, version: 3 }; // B écrase A, X perdu
    }
    expect(state.text).toBe('HeYllo');
    expect(state.text).not.toContain('X'); // Perte !

    // Avec CRDT, les deux sont préservés
    const crdt = new TextCRDT('site-A', 'Hello');
    crdt.insert(2, 'X', 'site-A');
    crdt.insert(2, 'Y', 'site-B');
    expect(crdt.getText()).toContain('X');
    expect(crdt.getText()).toContain('Y');
  });
});
