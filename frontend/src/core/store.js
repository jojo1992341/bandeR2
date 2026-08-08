export class RythmoStore extends EventTarget {
  constructor() {
    super();
    this.currentProject = null;
    this.replicas = [];
    this.playheadMs = 0;
    this.selection = null;
    this.undoStack = [];
    this.redoStack = [];
    this.syncStatus = "idle";
  }

  setProject(p) {
    this.currentProject = p;
    this._dispatch("project");
  }

  setReplicas(replicas) {
    this.replicas = replicas || [];
    this._dispatch("replicas");
  }

  updateReplica(id, updates) {
    const idx = this.replicas.findIndex(r => r.id === id);
    if (idx >= 0) {
      this.undoStack.push({ ...this.replicas[idx] });
      this.replicas[idx] = { ...this.replicas[idx], ...updates };
      this.redoStack = [];
      this._dispatch("replicas");
    }
  }

  setPlayhead(ms) {
    this.playheadMs = ms;
    this._dispatch("playhead");
  }

  selectReplica(replicaId) {
    this.selection = replicaId;
    this._dispatch("selection");
  }

  undo() {
    if (this.undoStack.length === 0) return;
    const prev = this.undoStack.pop();
    const idx = this.replicas.findIndex(r => r.id === prev.id);
    if (idx >= 0) {
      this.redoStack.push({ ...this.replicas[idx] });
      this.replicas[idx] = prev;
      this._dispatch("replicas");
    }
  }

  redo() {
    if (this.redoStack.length === 0) return;
    const next = this.redoStack.pop();
    const idx = this.replicas.findIndex(r => r.id === next.id);
    if (idx >= 0) {
      this.undoStack.push({ ...this.replicas[idx] });
      this.replicas[idx] = next;
      this._dispatch("replicas");
    }
  }

  setSyncStatus(status) {
    this.syncStatus = status;
    this._dispatch("syncStatus");
  }

  _dispatch(type) {
    this.dispatchEvent(new CustomEvent(type, { detail: this }));
  }

  subscribe(type, handler) {
    this.addEventListener(type, handler);
  }
}

export const store = new RythmoStore();
