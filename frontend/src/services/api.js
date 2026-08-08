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

  // ==================== Project Lifecycle §16.1 ====================

  async getProjectStatus(projectId) {
    const res = await fetch(`/api/v1/projects/${projectId}/status`);
    if (!res.ok) throw new Error(`getProjectStatus failed ${res.status}`);
    return res.json();
  },

  async transitionProjectStatus(projectId, status, { comment, userId, userRole } = {}) {
    const res = await fetch(`/api/v1/projects/${projectId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, comment, user_id: userId, user_role: userRole }),
    });
    if (res.status === 403) {
      const err = await res.json().catch(() => ({}));
      const forbiddenErr = new Error(err.detail?.message || 'Transition interdite');
      forbiddenErr.status = 403;
      forbiddenErr.detail = err.detail;
      throw forbiddenErr;
    }
    if (!res.ok) throw new Error(`transitionProjectStatus failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async validateProject(projectId, { userId, userRole, comment } = {}) {
    const res = await fetch(`/api/v1/projects/${projectId}/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, user_role: userRole, comment }),
    });
    if (res.status === 403) {
      const err = await res.json().catch(() => ({}));
      const forbiddenErr = new Error(err.detail?.message || 'Validation interdite');
      forbiddenErr.status = 403;
      forbiddenErr.detail = err.detail;
      throw forbiddenErr;
    }
    if (!res.ok) throw new Error(`validateProject failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async unlockProject(projectId, { userId, userRole, comment } = {}) {
    const res = await fetch(`/api/v1/projects/${projectId}/unlock`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, user_role: userRole, comment }),
    });
    if (!res.ok) throw new Error(`unlockProject failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async listProjectStatuses() {
    const res = await fetch(`/api/v1/projects/statuses`);
    if (!res.ok) throw new Error(`listProjectStatuses failed ${res.status}`);
    return res.json();
  },

  // ==================== Dashboard §14.2.1 ====================

  async getStudioDashboard(studioId) {
    const res = await fetch(`/api/v1/studios/${studioId}/dashboard`);
    if (!res.ok) throw new Error(`getStudioDashboard failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async listStudioProjects(studioId, { status, statuses, page, perPage } = {}) {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (statuses) params.set('statuses', statuses);
    if (page) params.set('page', String(page));
    if (perPage) params.set('per_page', String(perPage));
    const res = await fetch(`/api/v1/studios/${studioId}/projects?${params.toString()}`);
    if (!res.ok) throw new Error(`listStudioProjects failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  // ==================== Emotions & Intentions §8.2.5 ====================

  async getReplicaEmotionTags(replicaId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/emotion-tags`);
    if (!res.ok) throw new Error(`getReplicaEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async detectReplicaEmotionTags(replicaId) {
    const res = await fetch(`/api/v1/replicas/${replicaId}/emotion-tags/detect`, { method: 'POST' });
    if (!res.ok) throw new Error(`detectReplicaEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async getMediaEmotionTags(mediaId) {
    const res = await fetch(`/api/v1/media/${mediaId}/emotion-tags`);
    if (!res.ok) throw new Error(`getMediaEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async detectMediaEmotionTags(mediaId) {
    const res = await fetch(`/api/v1/media/${mediaId}/emotion-tags/detect`, { method: 'POST' });
    if (!res.ok) throw new Error(`detectMediaEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async getProjectEmotionTags(projectId) {
    const res = await fetch(`/api/v1/projects/${projectId}/emotion-tags`);
    if (!res.ok) throw new Error(`getProjectEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async detectProjectEmotionTags(projectId) {
    const res = await fetch(`/api/v1/projects/${projectId}/emotion-tags/detect`, { method: 'POST' });
    if (!res.ok) throw new Error(`detectProjectEmotionTags failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async getReplicasWithEmotions(projectId) {
    const res = await fetch(`/api/v1/projects/${projectId}/replicas/with-emotions`);
    if (!res.ok) throw new Error(`getReplicasWithEmotions failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  // ==================== Typographic Profiles §2.4 / §10.2 / §16.3 ====================

  async getTypographicProfiles(studioId) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles`);
    if (!res.ok) throw new Error(`getTypographicProfiles failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async createTypographicProfile(studioId, profile) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(profile),
    });
    if (!res.ok) throw new Error(`createTypographicProfile failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async patchTypographicProfiles(studioId, patch) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`patchTypographicProfiles failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async getTypographicProfile(studioId, profileId) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles/${profileId}`);
    if (!res.ok) throw new Error(`getTypographicProfile failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async patchTypographicProfile(studioId, profileId, patch) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles/${profileId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`patchTypographicProfile failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async deleteTypographicProfile(studioId, profileId) {
    const res = await fetch(`/api/v1/studios/${studioId}/typographic-profiles/${profileId}`, { method: 'DELETE' });
    if (!res.ok) throw new Error(`deleteTypographicProfile failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async generateRythmo(projectId, mediaId, typographicProfileId = null) {
    const body = { media_id: mediaId };
    if (typographicProfileId) body.typographic_profile_id = typographicProfileId;
    const res = await fetch(`/api/v1/projects/${projectId}/rythmo/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`generateRythmo failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  // ==================== Search §16.1 ====================

  async searchStudio(studioId, query, { limit = 20, offset = 0, includeReplicas = true, includeTranscripts = true } = {}) {
    const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset), include_replicas: String(includeReplicas), include_transcripts: String(includeTranscripts) });
    const res = await fetch(`/api/v1/studios/${studioId}/search?${params.toString()}`);
    if (!res.ok) throw new Error(`searchStudio failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  async searchStudioSuggest(studioId, query, limit = 5) {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    const res = await fetch(`/api/v1/studios/${studioId}/search/suggest?${params.toString()}`);
    if (!res.ok) throw new Error(`searchStudioSuggest failed ${res.status}: ${await res.text()}`);
    return res.json();
  },

  // Dashboard enrichi §16.1 US-053
  async getStudioDashboardEnriched(studioId) {
    const res = await fetch(`/api/v1/studios/${studioId}/dashboard`);
    if (!res.ok) throw new Error(`getStudioDashboardEnriched failed ${res.status}: ${await res.text()}`);
    return res.json();
  },
};
