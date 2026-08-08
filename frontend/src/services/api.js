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
    if (!res.ok) throw new Error(`patch failed ${res.status}`);
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
};
