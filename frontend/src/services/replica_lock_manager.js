/**
 * ReplicaLockManager §16.4 — Client-side lock management + WebSocket real-time sync.
 *
 * - Maintains a WebSocket connection per project for lock events
 * - Tracks which replicas are locked by which users
 * - Acquires/releases locks automatically on edit start/end
 * - Heartbeats every 10s to keep the lock alive (TTL=30s server-side)
 * - Provides visual lock state for the UI
 */

import { api as defaultApi } from './api.js';

/** @typedef {{ user_id: string, user_name: string }} LockInfo */
/** @typedef {{ [replicaId: string]: LockInfo }} LockMap */

export class ReplicaLockManager {
  /**
   * @param {string} projectId
   * @param {string} userId
   * @param {string} userName
   * @param {typeof defaultApi} [apiInstance]
   */
  constructor(projectId, userId, userName, apiInstance = defaultApi) {
    this.projectId = projectId;
    this.userId = userId;
    this.userName = userName;
    this.api = apiInstance;

    /** @type {LockMap} current lock state: replicaId → { user_id, user_name } */
    this.locks = {};

    /** @type {WebSocket|null} */
    this.ws = null;

    /** @type {number|null} heartbeat interval timer */
    this._heartbeatTimer = null;

    /** @type {Set<string>} replicas locked by current user */
    this._myLocks = new Set();

    /** @type {Set<Function>} subscribers for lock state changes */
    this._subscribers = new Set();

    /** @type {Array<{type:string, data:any}>} events for test inspection */
    this._events = [];
  }

  // ── WebSocket ──────────────────────────────────────────

  /**
   * Opens the WebSocket connection for real-time lock events.
   * @param {string} [wsUrl] — override WebSocket URL (for tests)
   */
  connect(wsUrl) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return;

    const base = wsUrl || this._buildWsUrl();
    this.ws = new WebSocket(base);

    this.ws.onopen = () => {
      this._emit('connected', {});
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this._handleMessage(msg);
      } catch {
        // ignore malformed
      }
    };

    this.ws.onclose = () => {
      this._emit('disconnected', {});
    };

    this.ws.onerror = () => {
      this._emit('error', {});
    };
  }

  disconnect() {
    this._stopHeartbeat();
    // Release all my locks
    for (const replicaId of this._myLocks) {
      this.releaseLock(replicaId).catch(() => {});
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  _buildWsUrl() {
    const proto = typeof location !== 'undefined' && location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = typeof location !== 'undefined' ? location.host : 'localhost:8000';
    return `${proto}//${host}/api/v1/ws/projects/${this.projectId}/replicas`;
  }

  // ── Lock acquisition / release ─────────────────────────

  /**
   * Attempt to acquire an edit lock on a replica.
   * @param {string} replicaId
   * @returns {Promise<{acquired: boolean, lockedBy?: LockInfo}>}
   */
  async acquireLock(replicaId) {
    const result = await this.api.acquireReplicaLock(replicaId, this.userId, this.userName);

    if (result.acquired) {
      this._myLocks.add(replicaId);
      this.locks[replicaId] = { user_id: this.userId, user_name: this.userName };
      this._emit('lock_acquired', { replicaId, userId: this.userId, userName: this.userName });
      this._startHeartbeat();
    } else {
      this.locks[replicaId] = result.locked_by || { user_id: '?', user_name: 'Inconnu' };
      this._emit('lock_denied', { replicaId, lockedBy: result.locked_by });
    }

    this._notifySubscribers();
    return result;
  }

  /**
   * Release an edit lock on a replica.
   * @param {string} replicaId
   * @returns {Promise<boolean>}
   */
  async releaseLock(replicaId) {
    const result = await this.api.releaseReplicaLock(replicaId, this.userId);
    if (result.released) {
      this._myLocks.delete(replicaId);
      delete this.locks[replicaId];
      this._emit('lock_released', { replicaId });
      this._notifySubscribers();
    }
    return result.released;
  }

  /**
   * Send a heartbeat for a specific replica lock.
   * @param {string} replicaId
   */
  async heartbeat(replicaId) {
    return this.api.replicaLockHeartbeat(replicaId, this.userId);
  }

  // ── Queries ────────────────────────────────────────────

  /**
   * Is this replica currently locked by someone?
   * @param {string} replicaId
   * @returns {boolean}
   */
  isLocked(replicaId) {
    return replicaId in this.locks;
  }

  /**
   * Is this replica locked by the current user?
   * @param {string} replicaId
   * @returns {boolean}
   */
  isLockedByMe(replicaId) {
    return this._myLocks.has(replicaId);
  }

  /**
   * Who is editing this replica?
   * @param {string} replicaId
   * @returns {LockInfo|null}
   */
  getLockInfo(replicaId) {
    return this.locks[replicaId] || null;
  }

  /**
   * Returns a descriptive lock message for UI display.
   * @param {string} replicaId
   * @returns {string|null} e.g. "Camille édite cette réplique" or null
   */
  getLockMessage(replicaId) {
    const info = this.locks[replicaId];
    if (!info) return null;
    if (info.user_id === this.userId) return null; // no message for self
    return `${info.user_name} édite cette réplique`;
  }

  // ── Subscription ───────────────────────────────────────

  /**
   * Subscribe to lock state changes.
   * @param {Function} callback — called with (locks: LockMap)
   * @returns {Function} unsubscribe
   */
  subscribe(callback) {
    this._subscribers.add(callback);
    return () => this._subscribers.delete(callback);
  }

  _notifySubscribers() {
    for (const cb of this._subscribers) {
      try { cb({ ...this.locks }); } catch {}
    }
  }

  // ── Internal ───────────────────────────────────────────

  _emit(type, data) {
    this._events.push({ type, data, timestamp: Date.now() });
  }

  _handleMessage(msg) {
    const type = msg.type;

    if (type === 'lock_snapshot') {
      // Initial state on connect
      this.locks = msg.locks || {};
      this._notifySubscribers();
      this._emit('snapshot', msg.locks);
    }
    else if (type === 'replica:lock_acquired') {
      const rid = msg.replica_id;
      this.locks[rid] = { user_id: msg.user_id, user_name: msg.user_name };
      this._notifySubscribers();
      this._emit('lock_acquired', { replicaId: rid, userId: msg.user_id, userName: msg.user_name });
    }
    else if (type === 'replica:lock_released') {
      const rid = msg.replica_id;
      delete this.locks[rid];
      this._myLocks.delete(rid);
      this._notifySubscribers();
      this._emit('lock_released', { replicaId: rid });
    }
    else if (type === 'replica:updated') {
      this._emit('replica_updated', msg);
    }
  }

  _startHeartbeat() {
    if (this._heartbeatTimer) return;
    // Heartbeat every 10s for all my locks
    this._heartbeatTimer = setInterval(() => {
      for (const replicaId of this._myLocks) {
        this.heartbeat(replicaId).catch(() => {});
      }
      // Also send via WebSocket if connected
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        for (const replicaId of this._myLocks) {
          this.ws.send(JSON.stringify({
            type: 'heartbeat',
            replica_id: replicaId,
            user_id: this.userId,
          }));
        }
      }
    }, 10000);
  }

  _stopHeartbeat() {
    if (this._heartbeatTimer) {
      clearInterval(this._heartbeatTimer);
      this._heartbeatTimer = null;
    }
  }
}
