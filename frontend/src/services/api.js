export const api = {
  async fetchReplicas(projectId) {
    return fetch(`/api/v1/projects/${projectId}/replicas`).then((r) => r.json());
  },

  /**
   * Scinde une réplique au temps donné.
   * POST /api/v1/replicas/{id}/split  §10.2
   * @param {string} replicaId - UUID de la réplique
   * @param {number} splitMs - temps de coupe en ms
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
   * @param {string[]} replicaIds - liste d'UUIDs
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

  // Raccourci pour réutilisation dans l'éditeur
  async patchReplica(replicaId, payload) {
    const res = await fetch(`/api/v1/replicas/${replicaId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`patch failed ${res.status}`);
    return res.json();
  },
};
