export const api = {
  async fetchReplicas(projectId) {
    return fetch(`/api/v1/projects/${projectId}/replicas`).then((r) => r.json());
  },

  /**
   * Scinde une réplique au temps donné.
   * POST /api/v1/replicas/{id}/split  §10.2
   */
  async splitReplica(replicaId, splitMs) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/split`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ split_ms: splitMs }),
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`split failed ${res.status}: ${err}`);
    }
    return res.json();
  },

  /**
   * Fusionne plusieurs répliques.
   * POST /api/v1/replicas/merge  §10.2
   */
  async mergeReplicas(replicaIds) {
    const res = await fetch(`/api/v1/replicas/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ replica_ids: replicaIds }),
    });
    if (!res.ok) {
      const err = await res.text();
      throw new Error(`merge failed ${res.status}: ${err}`);
    }
    return res.json();
  },

  async patchReplica(replicaId, payload) {
    const res = await fetch(`/api/v1/replicas/${replicaId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (res.status === 409) {
      // §16.4 — optimistic lock conflict
      const err = await res.json().catch(() => ({}));
      const conflictErr = new Error(err.detail?.message || 'Conflit de version');
      conflictErr.status = 409;
      conflictErr.detail = err.detail;
      throw conflictErr;
    }
    if (!res.ok) throw new Error(`patch failed ${res.status}`);
    return res.json();
  },

  // ==================== Replica Locks §16.4 ====================

  async acquireReplicaLock(replicaId, userId, userName) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/lock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, user_name: userName }),
    });
    if (!res.ok) throw new Error(`acquire lock failed ${res.status}`);
    return res.json();
  },

  async releaseReplicaLock(replicaId, userId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/lock?user_id=${encodeURIComponent(userId)}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`release lock failed ${res.status}`);
    return res.json();
  },

  async replicaLockHeartbeat(replicaId, userId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/heartbeat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    if (!res.ok) throw new Error(`heartbeat failed ${res.status}`);
    return res.json();
  },

  async getReplicaLockStatus(replicaId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/lock`);
    if (!res.ok) throw new Error(`get lock status failed ${res.status}`);
    return res.json();
  },

  // ==================== Versions RythmoBand §16.1 ====================

  async createVersion(projectId, comment = null) {
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ comment }),
    });
    if (!res.ok) throw new Error(`createVersion failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async listVersions(projectId) {
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/versions`);
    if (!res.ok) throw new Error(`listVersions failed ${res.status}`);
    return res.json();
  },

  async getVersion(projectId, versionId) {
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/versions/${versionId}`);
    if (!res.ok) throw new Error(`getVersion failed ${res.status}`);
    return res.json();
  },

  async compareVersions(projectId, fromId, toId) {
    const params = new URLSearchParams();
    if (fromId) params.set('from', fromId);
    if (toId) params.set('to', toId);
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/versions/compare?${params.toString()}`);
    if (!res.ok) throw new Error(`compare failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async restoreVersion(projectId, versionId) {
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/versions/${versionId}/restore`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error(`restore failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  // ==================== Exports PDF §A.2, §17.1 ====================

  async createExport(projectId, format = 'pdf') {
    const res = await fetch(`/api/v1/projects/${projectId}/exports`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format }),
    });
    if (!res.ok) throw new Error(`createExport failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async getExport(exportId) {
    const res = await fetch(`/api/v1/exports/${exportId}`);
    if (!res.ok) throw new Error(`getExport failed ${res.status}`);
    return res.json();
  },

  async downloadExport(exportId) {
    const res = await fetch(`/api/v1/exports/${exportId}/download`);
    if (!res.ok) throw new Error(`downloadExport failed ${res.status}`);
    return res.blob();
  },

  // ==================== Comments §10.2, §14.2.4 ====================

  async listComments(replicaId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/comments`);
    if (!res.ok) throw new Error(`listComments failed ${res.status}`);
    return res.json();
  },

  async createComment(replicaId, content) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/comments`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });
    if (!res.ok) throw new Error(`createComment failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async deleteComment(commentId) {
    const res = await fetch(`/api/v1/comments/${commentId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error(`deleteComment failed ${res.status}`);
    return res.json();
  },
};
