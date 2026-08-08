/**
 * Test §14.2 / §16.1 — Cycle de vie d'un projet/bande rythmo.
 *
 * Vérifie :
 *  - Transitions de statut autorisées
 *  - Refus d'édition d'une réplique appartenant à une bande Validée
 *  - Déverrouillage explicite ré-autorise l'édition
 *  - Indicateur visuel de statut readonly
 */

import { describe, it, expect, vi } from 'vitest';
import { RythmoStore } from '../src/core/store.js';
import { handleEditEvent } from '../src/components/replica_editor.js';

// ── Domain logic (pure, no API calls) ─────────────────────────

// Replicate the backend transition graph for frontend validation
const ALLOWED_TRANSITIONS = {
  Cree: ['En_traitement'],
  En_traitement: ['Pret_pour_edition', 'Cree'],
  Pret_pour_edition: ['En_edition', 'Archive'],
  En_edition: ['En_relecture', 'Pret_pour_edition'],
  En_relecture: ['Valide', 'En_edition', 'Pret_pour_edition'],
  Valide: ['Exporte_Livre', 'En_relecture', 'Archive'],
  Exporte_Livre: ['Archive', 'Valide'],
  Archive: ['Exporte_Livre'],
};

const EDITABLE_STATUSES = ['Pret_pour_edition', 'En_edition', 'En_relecture'];

function isTransitionAllowed(fromStatus, toStatus) {
  return (ALLOWED_TRANSITIONS[fromStatus] || []).includes(toStatus);
}

function isEditable(status) {
  return EDITABLE_STATUSES.includes(status);
}

// ── Tests ─────────────────────────────────────────────────────

describe('§16.1 — Project lifecycle: allowed transitions', () => {
  it('allows Cree → En_traitement', () => {
    expect(isTransitionAllowed('Cree', 'En_traitement')).toBe(true);
  });

  it('allows En_traitement → Pret_pour_edition', () => {
    expect(isTransitionAllowed('En_traitement', 'Pret_pour_edition')).toBe(true);
  });

  it('allows Pret_pour_edition → En_edition', () => {
    expect(isTransitionAllowed('Pret_pour_edition', 'En_edition')).toBe(true);
  });

  it('allows En_edition → En_relecture', () => {
    expect(isTransitionAllowed('En_edition', 'En_relecture')).toBe(true);
  });

  it('allows En_relecture → Valide (formal validation)', () => {
    expect(isTransitionAllowed('En_relecture', 'Valide')).toBe(true);
  });

  it('allows Valide → Exporte_Livre', () => {
    expect(isTransitionAllowed('Valide', 'Exporte_Livre')).toBe(true);
  });

  it('allows Exporte_Livre → Archive', () => {
    expect(isTransitionAllowed('Exporte_Livre', 'Archive')).toBe(true);
  });

  it('allows Valide → En_relecture (explicit unlock)', () => {
    expect(isTransitionAllowed('Valide', 'En_relecture')).toBe(true);
  });
});

describe('§16.1 — Project lifecycle: forbidden transitions', () => {
  it('forbids Cree → Valide (skip steps)', () => {
    expect(isTransitionAllowed('Cree', 'Valide')).toBe(false);
  });

  it('forbids Cree → En_edition', () => {
    expect(isTransitionAllowed('Cree', 'En_edition')).toBe(false);
  });

  it('forbids Valide → En_edition (must unlock first)', () => {
    expect(isTransitionAllowed('Valide', 'En_edition')).toBe(false);
  });

  it('forbids Archive → En_edition', () => {
    expect(isTransitionAllowed('Archive', 'En_edition')).toBe(false);
  });

  it('forbids En_traitement → Valide', () => {
    expect(isTransitionAllowed('En_traitement', 'Valide')).toBe(false);
  });

  it('forbids Pret_pour_edition → Valide', () => {
    expect(isTransitionAllowed('Pret_pour_edition', 'Valide')).toBe(false);
  });
});

describe('§16.1 — Editability per status', () => {
  it('editable in Pret_pour_edition', () => {
    expect(isEditable('Pret_pour_edition')).toBe(true);
  });

  it('editable in En_edition', () => {
    expect(isEditable('En_edition')).toBe(true);
  });

  it('editable in En_relecture', () => {
    expect(isEditable('En_relecture')).toBe(true);
  });

  it('NOT editable in Cree', () => {
    expect(isEditable('Cree')).toBe(false);
  });

  it('NOT editable in En_traitement', () => {
    expect(isEditable('En_traitement')).toBe(false);
  });

  it('NOT editable in Valide (locked)', () => {
    expect(isEditable('Valide')).toBe(false);
  });

  it('NOT editable in Exporte_Livre', () => {
    expect(isEditable('Exporte_Livre')).toBe(false);
  });

  it('NOT editable in Archive (readonly)', () => {
    expect(isEditable('Archive')).toBe(false);
  });
});

describe('§16.1 — Store project status integration', () => {
  it('tracks project status and editability', () => {
    const store = new RythmoStore();

    // Set to Valide
    store.setProjectStatus('Valide', {
      label: 'Validé',
      is_editable: false,
      is_readonly: false,
      allowed_transitions: ['Exporte_Livre', 'En_relecture', 'Archive'],
    });

    expect(store.projectStatus).toBe('Valide');
    expect(store.isProjectEditable()).toBe(false);
    expect(store.getProjectStatusLabel()).toBe('Validé');
    expect(store.getProjectAllowedTransitions()).toContain('En_relecture');
  });

  it('tracks editability in En_edition', () => {
    const store = new RythmoStore();
    store.setProjectStatus('En_edition', {
      label: 'En édition',
      is_editable: true,
      is_readonly: false,
      allowed_transitions: ['En_relecture', 'Pret_pour_edition'],
    });

    expect(store.isProjectEditable()).toBe(true);
  });

  it('notifies subscribers on status change', () => {
    const store = new RythmoStore();
    const events = [];
    store.subscribe('projectStatus', () => events.push(store.projectStatus));

    store.setProjectStatus('Valide', { label: 'Validé', is_editable: false, is_readonly: false });
    expect(events.length).toBeGreaterThanOrEqual(1);
    expect(events[0]).toBe('Valide');
  });
});

describe('§16.1 — handleEditEvent respects project readonly status', () => {
  it('blocks editing when project is Valide', async () => {
    const store = new RythmoStore();
    store.setReplicas([{
      id: 'r-001', text: 'Bonjour', version: 1,
      start_ms: 0, end_ms: 3000, speaker_id: null,
      typo_codes: {}, confidence_score: 0.9,
      is_manually_edited: false, breath_marker: false, order_index: 0,
    }]);
    // Set project to Valide (readonly for editing)
    store.setProjectStatus('Valide', {
      label: 'Validé',
      is_editable: false,
      is_readonly: false,
      allowed_transitions: ['Exporte_Livre', 'En_relecture'],
    });

    const api = { patchReplica: vi.fn().mockResolvedValue({ status: 'updated' }) };

    const event = new CustomEvent('rythmo:edit', {
      detail: { id: 'r-001', text: 'Tentative interdite' },
    });

    await handleEditEvent(event, store, api);

    // Text should NOT have changed (blocked by project status)
    expect(store.replicas[0].text).toBe('Bonjour');
    // API should not have been called
    expect(api.patchReplica).not.toHaveBeenCalled();
  });

  it('allows editing when project is En_edition', async () => {
    const store = new RythmoStore();
    store.setReplicas([{
      id: 'r-001', text: 'Bonjour', version: 1,
      start_ms: 0, end_ms: 3000, speaker_id: null,
      typo_codes: {}, confidence_score: 0.9,
      is_manually_edited: false, breath_marker: false, order_index: 0,
    }]);
    store.setProjectStatus('En_edition', {
      label: 'En édition',
      is_editable: true,
      is_readonly: false,
      allowed_transitions: ['En_relecture', 'Pret_pour_edition'],
    });

    const api = { patchReplica: vi.fn().mockResolvedValue({ id: 'r-001', status: 'updated', version: 2, replica: { text: 'Bonsoir' } }) };

    const event = new CustomEvent('rythmo:edit', {
      detail: { id: 'r-001', text: 'Bonsoir' },
    });

    await handleEditEvent(event, store, api);

    // Text should have changed (allowed)
    expect(store.replicas[0].text).toBe('Bonsoir');
  });

  it('allows editing after explicit unlock from Valide', async () => {
    const store = new RythmoStore();
    store.setReplicas([{
      id: 'r-001', text: 'Bonjour', version: 1,
      start_ms: 0, end_ms: 3000, speaker_id: null,
      typo_codes: {}, confidence_score: 0.9,
      is_manually_edited: false, breath_marker: false, order_index: 0,
    }]);

    // Project is Valide — editing blocked
    store.setProjectStatus('Valide', {
      label: 'Validé',
      is_editable: false,
      is_readonly: false,
      allowed_transitions: ['Exporte_Livre', 'En_relecture'],
    });

    const api = { patchReplica: vi.fn().mockResolvedValue({ id: 'r-001', status: 'updated', version: 2, replica: { text: 'Bonsoir' } }) };

    // Attempt edit → blocked
    const event1 = new CustomEvent('rythmo:edit', { detail: { id: 'r-001', text: 'Blocked' } });
    await handleEditEvent(event1, store, api);
    expect(store.replicas[0].text).toBe('Bonjour');

    // Explicit unlock: Valide → En_relecture
    store.setProjectStatus('En_relecture', {
      label: 'En relecture',
      is_editable: true,
      is_readonly: false,
      allowed_transitions: ['Valide', 'En_edition', 'Pret_pour_edition'],
    });

    // Now editing is allowed
    const event2 = new CustomEvent('rythmo:edit', { detail: { id: 'r-001', text: 'Bonsoir' } });
    await handleEditEvent(event2, store, api);
    expect(store.replicas[0].text).toBe('Bonsoir');
  });
});
