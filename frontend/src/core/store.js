/**
 * RythmoStore §7.3 — Command pattern pour undo/redo
 * Gère undoStack / redoStack et les commandes métier :
 *  - déplacement (move)
 *  - redimensionnement (resize)
 *  - édition de texte (editText)
 *  - changement de code typographique (typo)
 */

// Helper deep clone (structuredClone si dispo, sinon JSON)
function clone(obj) {
  if (typeof structuredClone === 'function') {
    try { return structuredClone(obj); } catch {}
  }
  return JSON.parse(JSON.stringify(obj));
}

// Command abstraite
class Command {
  constructor(store) {
    this.store = store;
  }
  execute() {}
  undo() {}
}

// Command générique pour mise à jour d'une réplique (utilisée pour move/resize/edit/typo)
class UpdateReplicaCommand extends Command {
  constructor(store, replicaId, oldReplica, newReplica, label = 'update') {
    super(store);
    this.replicaId = replicaId;
    this.oldReplica = clone(oldReplica);
    this.newReplica = clone(newReplica);
    this.label = label;
  }
  execute() {
    const idx = this.store.replicas.findIndex((r) => r.id === this.replicaId);
    if (idx >= 0) {
      this.store.replicas[idx] = clone(this.newReplica);
      this.store._dispatch('replicas');
    }
  }
  undo() {
    const idx = this.store.replicas.findIndex((r) => r.id === this.replicaId);
    if (idx >= 0) {
      this.store.replicas[idx] = clone(this.oldReplica);
      this.store._dispatch('replicas');
    }
  }
}

export class RythmoStore extends EventTarget {
  constructor() {
    super();
    this.currentProject = null;
    this.replicas = [];
    this.playheadMs = 0;
    this.selection = null;
    this.undoStack = [];
    this.redoStack = [];
    this.syncStatus = 'idle';
    // §16.4 — replica locks: { replicaId: { user_id, user_name } }
    this.replicaLocks = {};
    // §16.1 — project lifecycle status
    this.projectStatus = null;  // e.g. 'En_edition', 'Valide', etc.
    this.projectStatusInfo = null;  // { label, is_editable, is_readonly, allowed_transitions }
  }

  setProject(p) {
    this.currentProject = p;
    this._dispatch('project');
  }

  setReplicas(replicas) {
    this.replicas = replicas ? replicas.map((r) => clone(r)) : [];
    // setReplicas est une initialisation, on ne le pousse pas dans l'historique
    // mais on pourrait vouloir vider les piles si c'est un nouveau projet
    this._dispatch('replicas');
  }

  // Exécution d'une commande (pattern Command)
  executeCommand(command) {
    command.execute();
    this.undoStack.push(command);
    this.redoStack = [];
  }

  // Méthode générique pour update (utilisée par les 4 types)
  updateReplica(id, updates) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    const newReplica = clone({ ...oldReplica, ...updates });
    // Pour typo_codes, merge si updates contient typo_codes partiel
    if (updates.typo_codes && typeof updates.typo_codes === 'object') {
      // Si l'appel vient de applyTypoCode, il a déjà mergé, mais on garde le comportement
      // On s'assure que newReplica.typo_codes est bien le résultat attendu
      newReplica.typo_codes = clone(updates.typo_codes);
    }
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'update');
    this.executeCommand(cmd);
  }

  // === Commandes métier §7.3 ===

  // Déplacement : change start_ms et end_ms en préservant la durée (ou avec delta)
  moveReplica(id, newStartMs, newEndMs) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    let newStart, newEnd;
    if (typeof newEndMs === 'number') {
      newStart = newStartMs;
      newEnd = newEndMs;
    } else if (typeof newStartMs === 'number') {
      // Si un seul paramètre est donné, on considère que c'est le delta
      const delta = newStartMs;
      newStart = oldReplica.start_ms + delta;
      newEnd = oldReplica.end_ms + delta;
    } else {
      return;
    }
    const newReplica = clone({ ...oldReplica, start_ms: newStart, end_ms: newEnd });
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'move');
    this.executeCommand(cmd);
  }

  // Alias pour déplacement avec delta
  moveReplicaByDelta(id, deltaMs) {
    return this.moveReplica(id, deltaMs);
  }

  // Redimensionnement : change start_ms et/ou end_ms (un ou deux bords)
  resizeReplica(id, newStartMs, newEndMs) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    const newReplica = clone(oldReplica);
    if (typeof newStartMs === 'number') newReplica.start_ms = newStartMs;
    if (typeof newEndMs === 'number') newReplica.end_ms = newEndMs;
    // Validation simple : start < end
    if (newReplica.start_ms >= newReplica.end_ms) return;
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'resize');
    this.executeCommand(cmd);
  }

  // Variante avec edge : resizeReplicaByEdge(id, edge, newMs)
  resizeReplicaByEdge(id, edge, newMs) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const old = this.replicas[idx];
    if (edge === 'left' || edge === 'start') {
      return this.resizeReplica(id, newMs, old.end_ms);
    } else if (edge === 'right' || edge === 'end') {
      return this.resizeReplica(id, old.start_ms, newMs);
    }
  }

  // Édition de texte
  editReplicaText(id, newText) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    const newReplica = clone({ ...oldReplica, text: newText });
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'editText');
    this.executeCommand(cmd);
  }

  // Alias pour compatibilité
  updateText(id, newText) {
    return this.editReplicaText(id, newText);
  }

  // Changement de code typographique §2.4
  updateTypoCodes(id, newTypoCodes) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    const existing = oldReplica.typo_codes || {};
    // Normaliser les clés vers canonique et merger avec l'existant (préserve les autres codes)
    const canonicalMap = {
      brackets: 'crochets', bracket_in: 'crochets', bracket_out: 'crochets',
      crochets: 'crochets',
      italic: 'italique', italique: 'italique', voix_off: 'italique', off: 'italique',
      uppercase: 'majuscules', majuscules: 'majuscules', cri: 'majuscules', caps: 'majuscules',
      parentheses: 'parentheses', parentheses_jeu: 'parentheses', indication_jeu: 'parentheses', jeu: 'parentheses',
    };
    const normalized = {};
    for (const [k, v] of Object.entries(newTypoCodes || {})) {
      const canon = canonicalMap[k.toLowerCase()] || k.toLowerCase();
      normalized[canon] = v;
    }
    // Merge : si une clé vaut false/null, on la supprime
    const merged = clone(existing);
    for (const [k, v] of Object.entries(normalized)) {
      if (v === false || v === null || v === undefined) {
        delete merged[k];
      } else {
        merged[k] = v;
      }
    }
    // Si l'appel fournit un objet vide, on vide (clear)
    const finalTypo = Object.keys(newTypoCodes || {}).length === 0 ? {} : merged;
    const newReplica = clone({ ...oldReplica, typo_codes: finalTypo });
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'typo');
    this.executeCommand(cmd);
  }

  // Toggle d'un seul code typo
  toggleTypoCode(id, code, value) {
    const idx = this.replicas.findIndex((r) => r.id === id);
    if (idx < 0) return;
    const oldReplica = clone(this.replicas[idx]);
    const existing = oldReplica.typo_codes || {};
    const newTypo = clone(existing);
    const canonicalMap = {
      brackets: 'crochets', bracket_in: 'crochets', bracket_out: 'crochets',
      crochets: 'crochets',
      italic: 'italique', italique: 'italique', voix_off: 'italique', off: 'italique',
      uppercase: 'majuscules', majuscules: 'majuscules', cri: 'majuscules', caps: 'majuscules',
      parentheses: 'parentheses', parentheses_jeu: 'parentheses', indication_jeu: 'parentheses', jeu: 'parentheses',
    };
    const canon = canonicalMap[code.toLowerCase()] || code.toLowerCase();
    if (value === undefined) value = !newTypo[canon];
    if (value) newTypo[canon] = true;
    else delete newTypo[canon];
    const newReplica = clone({ ...oldReplica, typo_codes: newTypo });
    const cmd = new UpdateReplicaCommand(this, id, oldReplica, newReplica, 'typo');
    this.executeCommand(cmd);
  }

  // Méthodes historiques pour compatibilité
  changeTypoCode(id, code, value) {
    return this.toggleTypoCode(id, code, value);
  }

  setPlayhead(ms) {
    this.playheadMs = ms;
    this._dispatch('playhead');
  }

  selectReplica(replicaId) {
    this.selection = replicaId;
    this._dispatch('selection');
  }

  undo() {
    if (this.undoStack.length === 0) return;
    const cmd = this.undoStack.pop();
    if (cmd && typeof cmd.undo === 'function') {
      cmd.undo();
      this.redoStack.push(cmd);
      // _dispatch déjà fait dans cmd.undo(), mais on assure un dispatch global
      this._dispatch('replicas');
    } else {
      // Fallback pour ancien format (réplique snapshot)
      const prev = cmd;
      const idx = this.replicas.findIndex((r) => r.id === prev.id);
      if (idx >= 0) {
        this.redoStack.push(clone(this.replicas[idx]));
        this.replicas[idx] = clone(prev);
        this._dispatch('replicas');
      }
    }
  }

  redo() {
    if (this.redoStack.length === 0) return;
    const cmd = this.redoStack.pop();
    if (cmd && typeof cmd.execute === 'function') {
      // Pour redo, on ré-exécute la commande
      // UpdateReplicaCommand.execute() va ré-appliquer newReplica
      cmd.execute();
      this.undoStack.push(cmd);
      this._dispatch('replicas');
    } else {
      // Fallback ancien format
      const next = cmd;
      const idx = this.replicas.findIndex((r) => r.id === next.id);
      if (idx >= 0) {
        this.undoStack.push(clone(this.replicas[idx]));
        this.replicas[idx] = clone(next);
        this._dispatch('replicas');
      }
    }
  }

  // Alias pour raccourci Ctrl+Y (redo) vs Ctrl+Shift+Z
  redoStackSize() { return this.redoStack.length; }
  undoStackSize() { return this.undoStack.length; }
  canUndo() { return this.undoStack.length > 0; }
  canRedo() { return this.redoStack.length > 0; }

  clearHistory() {
    this.undoStack = [];
    this.redoStack = [];
  }

  setSyncStatus(status) {
    this.syncStatus = status;
    this._dispatch('syncStatus');
  }

  // §16.4 — Replica lock state management
  setReplicaLocks(locks) {
    this.replicaLocks = locks || {};
    this._dispatch('replicaLocks');
  }

  updateReplicaLock(replicaId, lockInfo) {
    if (lockInfo) {
      this.replicaLocks = { ...this.replicaLocks, [replicaId]: lockInfo };
    } else {
      const next = { ...this.replicaLocks };
      delete next[replicaId];
      this.replicaLocks = next;
    }
    this._dispatch('replicaLocks');
  }

  isReplicaLocked(replicaId) {
    return replicaId in this.replicaLocks;
  }

  getReplicaLockMessage(replicaId) {
    const info = this.replicaLocks[replicaId];
    if (!info) return null;
    return `${info.user_name} édite cette réplique`;
  }

  // §16.1 — Project lifecycle status management
  setProjectStatus(status, info = null) {
    this.projectStatus = status;
    this.projectStatusInfo = info;
    this._dispatch('projectStatus');
  }

  isProjectEditable() {
    if (this.projectStatusInfo && typeof this.projectStatusInfo.is_editable === 'boolean') {
      return this.projectStatusInfo.is_editable;
    }
    // Default: editable if no status set or unknown
    return this.projectStatus === null;
  }

  isProjectReadonly() {
    if (this.projectStatusInfo && typeof this.projectStatusInfo.is_readonly === 'boolean') {
      return this.projectStatusInfo.is_readonly;
    }
    return false;
  }

  getProjectStatusLabel() {
    if (this.projectStatusInfo && this.projectStatusInfo.label) {
      return this.projectStatusInfo.label;
    }
    return this.projectStatus || '';
  }

  getProjectAllowedTransitions() {
    if (this.projectStatusInfo && Array.isArray(this.projectStatusInfo.allowed_transitions)) {
      return this.projectStatusInfo.allowed_transitions;
    }
    return [];
  }

  _dispatch(type) {
    this.dispatchEvent(new CustomEvent(type, { detail: this }));
  }

  subscribe(type, handler) {
    this.addEventListener(type, handler);
  }
}

export const store = new RythmoStore();

// Exposer les classes pour tests avancés si besoin
export { Command, UpdateReplicaCommand };
