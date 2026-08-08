/**
 * AuditLogPanel §15.5 — Panneau du journal d'audit append-only et des alertes de sécurité.
 *
 * Affiche :
 * - Journal d'audit append-only horodaté des actions sensibles (connexions, exports, partages, etc.)
 * - Alertes automatiques sur comportements anormaux (téléchargements massifs, géolocalisation inhabituelle, force brute)
 * - Bouton de résolution / acquittement d'une alerte
 */

export class AuditLogPanel {
  /**
   * @param {string} containerId - DOM element ID to mount into
   * @param {string} studioId - Studio UUID
   */
  constructor(containerId, studioId) {
    this.containerId = containerId;
    this.studioId = studioId;
    this.auditLogs = [];
    this.securityAlerts = [];
  }

  async fetch() {
    const [resLogs, resAlerts] = await Promise.all([
      fetch(`/api/v1/audit-logs?limit=50`),
      fetch(`/api/v1/security-alerts?limit=20`),
    ]);
    if (!resLogs.ok) throw new Error(`AuditLogs fetch failed: ${resLogs.status}`);
    if (!resAlerts.ok) throw new Error(`SecurityAlerts fetch failed: ${resAlerts.status}`);
    this.auditLogs = await resLogs.json();
    this.securityAlerts = await resAlerts.json();
    return { auditLogs: this.auditLogs, securityAlerts: this.securityAlerts };
  }

  async resolveAlert(alertId) {
    const res = await fetch(`/api/v1/security-alerts/${alertId}/resolve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    if (!res.ok) throw new Error(`Alert resolve failed: ${res.status}`);
    await this.fetch();
    this._render();
  }

  async mount() {
    try {
      await this.fetch();
    } catch (e) {
      console.warn('Could not load audit logs or alerts', e);
    }
    this._render();
  }

  _render() {
    const el = document.getElementById(this.containerId);
    if (!el) return;

    const unresolvedAlerts = this.securityAlerts.filter((a) => !a.is_resolved);

    el.innerHTML = `
      <div class="audit-panel" data-testid="audit-panel">
        <div class="audit-header">
          <h2 class="audit-title">Journal d'audit & Alertes de sécurité (§15.5)</h2>
          <span class="audit-badge">Append-only / Immuable</span>
        </div>

        ${
          unresolvedAlerts.length > 0
            ? `
          <div class="security-alerts-section" data-testid="security-alerts">
            <h3 class="alerts-title">⚠️ Alertes de sécurité actives (${unresolvedAlerts.length})</h3>
            <table class="alerts-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Type d'alerte</th>
                  <th>Sévérité</th>
                  <th>Utilisateur</th>
                  <th>Détails</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                ${unresolvedAlerts
                  .map(
                    (a) => `
                  <tr class="alert-row alert-row--${a.severity}" data-alert-id="${a.id}">
                    <td>${a.created_at ? new Date(a.created_at).toLocaleString('fr-FR') : '—'}</td>
                    <td><b>${a.alert_type}</b></td>
                    <td><span class="severity-badge severity-${a.severity}">${a.severity.toUpperCase()}</span></td>
                    <td>${a.user_email || '—'}</td>
                    <td>${a.details?.message || JSON.stringify(a.details)}</td>
                    <td>
                      <button class="btn-resolve-alert" data-alert-id="${a.id}">Résoudre</button>
                    </td>
                  </tr>
                `
                  )
                  .join('')}
              </tbody>
            </table>
          </div>
        `
            : '<div class="alerts-empty" data-testid="alerts-empty">Aucune alerte de sécurité active.</div>'
        }

        <div class="audit-logs-section" data-testid="audit-logs">
          <h3 class="logs-title">Journal des actions sensibles (append-only)</h3>
          <table class="audit-table">
            <thead>
              <tr>
                <th>Horodatage</th>
                <th>Action</th>
                <th>Utilisateur</th>
                <th>IP / Pays</th>
                <th>Détails</th>
              </tr>
            </thead>
            <tbody>
              ${
                this.auditLogs.length > 0
                  ? this.auditLogs
                      .map(
                        (log) => `
                    <tr class="audit-row" data-log-id="${log.id}">
                      <td>${log.created_at ? new Date(log.created_at).toLocaleString('fr-FR') : '—'}</td>
                      <td><span class="audit-action badge-${log.action}">${log.action}</span></td>
                      <td>${log.user_email || '—'}</td>
                      <td>${log.ip_address || '—'} (${log.country_code || 'FR'})</td>
                      <td><code>${JSON.stringify(log.details)}</code></td>
                    </tr>
                  `
                      )
                      .join('')
                  : '<tr><td colspan="5">Aucune action sensible enregistrée.</td></tr>'
              }
            </tbody>
          </table>
        </div>
      </div>
    `;

    el.querySelectorAll('.btn-resolve-alert').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const id = e.currentTarget.dataset.alertId;
        if (id) this.resolveAlert(id);
      });
    });
  }
}
