/**
 * SecuritySettingsPanel §15.4 — Panneau de gestion des protections des contenus studio.
 *
 * Permet d'activer ou désactiver par cases à cocher :
 * - Filigrane dynamique pour rôles à risque (invités, clients externes)
 * - Chiffrement au repos (AES-256 S3)
 * - Chiffrement en transit (TLS 1.3 obligatoire & HSTS)
 * - Purge automatique configurable des exports après 30 jours (sauf archivés)
 */

export class SecuritySettingsPanel {
  /**
   * @param {string} containerId - DOM element ID to mount into
   * @param {string} studioId - Studio UUID
   */
  constructor(containerId, studioId) {
    this.containerId = containerId;
    this.studioId = studioId;
    this.settings = {
      watermark_enabled: true,
      encryption_at_rest_enabled: true,
      encryption_in_transit_enabled: true,
      auto_purge_enabled: true,
      retention_days: 30,
    };
  }

  async fetch() {
    const res = await fetch(`/api/v1/studios/${this.studioId}/security`);
    if (!res.ok) throw new Error(`Security fetch failed: ${res.status}`);
    this.settings = await res.json();
    return this.settings;
  }

  async update(patch) {
    const res = await fetch(`/api/v1/studios/${this.studioId}/security`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`Security update failed: ${res.status}`);
    this.settings = await res.json();
    this._render();
    return this.settings;
  }

  async mount() {
    try {
      await this.fetch();
    } catch (e) {
      console.warn('Fallback to default security settings', e);
    }
    this._render();
  }

  _render() {
    const el = document.getElementById(this.containerId);
    if (!el) return;

    el.innerHTML = `
      <div class="security-panel" data-testid="security-panel">
        <h2 class="security-title">Protection des contenus (§15.4)</h2>
        <p class="security-desc">Ces protections peuvent être activées ou désactivées en cochant/décochant une case.</p>

        <div class="security-field">
          <label class="security-label">
            <input type="checkbox" id="chk-watermark" data-testid="chk-watermark"
                   ${this.settings.watermark_enabled ? 'checked' : ''} />
            <span><b>Filigrane dynamique</b> — incrusté sur aperçus vidéo et exports PDF pour les rôles à risque (invités, clients externes)</span>
          </label>
        </div>

        <div class="security-field">
          <label class="security-label">
            <input type="checkbox" id="chk-aes256" data-testid="chk-aes256"
                   ${this.settings.encryption_at_rest_enabled ? 'checked' : ''} />
            <span><b>Chiffrement au repos</b> — AES-256 sur le stockage objet S3</span>
          </label>
        </div>

        <div class="security-field">
          <label class="security-label">
            <input type="checkbox" id="chk-tls13" data-testid="chk-tls13"
                   ${this.settings.encryption_in_transit_enabled ? 'checked' : ''} />
            <span><b>Chiffrement en transit</b> — TLS 1.3 obligatoire & en-tête HSTS sur tous les flux</span>
          </label>
        </div>

        <div class="security-field">
          <label class="security-label">
            <input type="checkbox" id="chk-purge" data-testid="chk-purge"
                   ${this.settings.auto_purge_enabled ? 'checked' : ''} />
            <span><b>Purge automatique des exports</b> — suppression après expiration sauf archivage explicite</span>
          </label>
          ${
            this.settings.auto_purge_enabled
              ? `
            <div class="security-retention">
              <label for="input-retention">Rétention (jours) :</label>
              <input type="number" id="input-retention" data-testid="input-retention"
                     value="${this.settings.retention_days}" min="1" max="365" />
            </div>`
              : ''
          }
        </div>
      </div>
    `;

    const chkWatermark = el.querySelector('#chk-watermark');
    if (chkWatermark) {
      chkWatermark.addEventListener('change', (e) =>
        this.update({ watermark_enabled: e.target.checked })
      );
    }
    const chkAes = el.querySelector('#chk-aes256');
    if (chkAes) {
      chkAes.addEventListener('change', (e) =>
        this.update({ encryption_at_rest_enabled: e.target.checked })
      );
    }
    const chkTls = el.querySelector('#chk-tls13');
    if (chkTls) {
      chkTls.addEventListener('change', (e) =>
        this.update({ encryption_in_transit_enabled: e.target.checked })
      );
    }
    const chkPurge = el.querySelector('#chk-purge');
    if (chkPurge) {
      chkPurge.addEventListener('change', (e) =>
        this.update({ auto_purge_enabled: e.target.checked })
      );
    }
    const inputRet = el.querySelector('#input-retention');
    if (inputRet) {
      inputRet.addEventListener('change', (e) =>
        this.update({ retention_days: parseInt(e.target.value, 10) || 30 })
      );
    }
  }
}
