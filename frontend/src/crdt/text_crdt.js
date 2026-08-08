/**
 * TextCRDT §16.4 — CRDT pour édition collaborative caractère par caractère
 * Compatible avec le backend Python (RGA / Logoot-like)
 * 
 * Évaluation §16.4 : CRDT vs OT vs Verrouillage optimiste
 * - Verrouillage optimiste : simple, mais 409 Conflict en cas de concurrence
 * - OT : nécessite serveur central, transformation complexe
 * - CRDT : décentralisé, commutatif, idéal pour volume élevé
 * 
 * Choix : RGA/Logoot-like avec position pos=[int] et tie-breaker siteId
 */

function hashSite(siteId) {
  let hash = 0;
  for (let i = 0; i < siteId.length; i++) {
    hash = ((hash << 5) - hash) + siteId.charCodeAt(i);
    hash = hash & hash; // Convert to 32bit
  }
  return Math.abs(hash) % 1000;
}

export class TextCRDT {
  constructor(siteId = 'default', initialText = '') {
    this.siteId = siteId;
    this.counter = 0;
    this.versionVector = { [siteId]: 0 };
    this.characters = [];
    // Initialiser avec le texte initial
    for (let i = 0; i < initialText.length; i++) {
      this.characters.push({
        char: initialText[i],
        id: { site: 'init', counter: i },
        pos: [i],
        visible: true,
      });
    }
    this._sort();
  }

  _sort() {
    this.characters.sort((a, b) => {
      // Comparer pos lexicographiquement
      const len = Math.min(a.pos.length, b.pos.length);
      for (let i = 0; i < len; i++) {
        if (a.pos[i] !== b.pos[i]) return a.pos[i] - b.pos[i];
      }
      if (a.pos.length !== b.pos.length) return a.pos.length - b.pos.length;
      // Tie-breaker siteId puis counter
      if (a.id.site !== b.id.site) return a.id.site.localeCompare(b.id.site);
      return a.id.counter - b.id.counter;
    });
  }

  _nextId() {
    this.counter += 1;
    this.versionVector[this.siteId] = this.counter;
    return { site: this.siteId, counter: this.counter };
  }

  _generatePosBetween(leftPos, rightPos, siteId = null) {
    const site = siteId || this.siteId;
    const siteHash = hashSite(site);
    if (!leftPos && !rightPos) return [siteHash];
    if (!leftPos) return [rightPos[0] - 1, siteHash];
    if (!rightPos) return [leftPos[0] + 1, siteHash];
    if (leftPos[0] + 1 < rightPos[0]) {
      return [Math.floor((leftPos[0] + rightPos[0]) / 2), siteHash];
    } else {
      return [...leftPos, siteHash];
    }
  }

  _findVisibleIndex(logicalPos) {
    let visibleCount = 0;
    for (let i = 0; i < this.characters.length; i++) {
      if (this.characters[i].visible) {
        if (visibleCount === logicalPos) return i;
        visibleCount++;
      }
    }
    return this.characters.length;
  }

  insert(logicalPos, char, siteId = null, counter = null, pos = null) {
    const site = siteId || this.siteId;
    let cid;
    if (counter !== null) {
      cid = { site, counter };
      this.versionVector[site] = Math.max(this.versionVector[site] || 0, counter);
      if (site === this.siteId) this.counter = Math.max(this.counter, counter);
    } else {
      if (site === this.siteId) {
        cid = this._nextId();
      } else {
        this.counter += 1;
        cid = { site, counter: this.counter };
        this.versionVector[site] = Math.max(this.versionVector[site] || 0, cid.counter);
      }
    }

    if (!pos) {
      const visible = this.characters.filter(c => c.visible);
      let leftPos = null, rightPos = null;
      if (logicalPos > 0 && logicalPos <= visible.length) {
        leftPos = visible[logicalPos - 1].pos;
      }
      if (logicalPos < visible.length) {
        rightPos = visible[logicalPos].pos;
      }
      pos = this._generatePosBetween(leftPos, rightPos, site);
    }

    const newChar = { char, id: cid, pos, visible: true };
    this.characters.push(newChar);
    this._sort();
    return newChar;
  }

  delete(logicalPos, siteId = null, counter = null) {
    const site = siteId || this.siteId;
    const visible = this.characters.filter(c => c.visible);
    if (logicalPos < 0 || logicalPos >= visible.length) return null;
    const target = visible[logicalPos];
    target.visible = false;
    if (site === this.siteId) {
      this._nextId();
    } else if (counter !== null) {
      this.versionVector[site] = Math.max(this.versionVector[site] || 0, counter);
    }
    return target;
  }

  getText() {
    return this.characters.filter(c => c.visible).map(c => c.char).join('');
  }

  getState() {
    return {
      characters: JSON.parse(JSON.stringify(this.characters)),
      versionVector: { ...this.versionVector },
      text: this.getText(),
    };
  }

  setState(state) {
    this.characters = JSON.parse(JSON.stringify(state.characters || []));
    this.versionVector = { ...(state.versionVector || {}) };
    this.counter = this.versionVector[this.siteId] || 0;
    this._sort();
  }

  merge(other) {
    const existing = new Set(this.characters.map(c => `${c.id.site}:${c.id.counter}`));
    for (const c of other.characters) {
      const key = `${c.id.site}:${c.id.counter}`;
      if (!existing.has(key)) {
        this.characters.push(JSON.parse(JSON.stringify(c)));
        existing.add(key);
      } else {
        // Conflit de visibilité : delete l'emporte
        const local = this.characters.find(x => `${x.id.site}:${x.id.counter}` === key);
        if (local && !c.visible) local.visible = false;
      }
    }
    for (const [site, counter] of Object.entries(other.versionVector || {})) {
      this.versionVector[site] = Math.max(this.versionVector[site] || 0, counter);
    }
    this._sort();
  }

  // Pour tests de convergence : appliquer une liste d'opérations dans n'importe quel ordre
  applyOperations(ops) {
    for (const op of ops) {
      if (op.op_type === 'insert') {
        this.insert(op.position, op.char, op.site_id, op.counter, op.pos_id);
      } else if (op.op_type === 'delete') {
        this.delete(op.position, op.site_id, op.counter);
      }
    }
  }
}

// Helper pour créer une instance depuis l'état backend
export function crdtFromState(state, siteId) {
  const crdt = new TextCRDT(siteId || 'default', '');
  if (state) crdt.setState(state);
  return crdt;
}
