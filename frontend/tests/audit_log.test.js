import { describe, it, expect, beforeEach } from 'vitest';
import { AuditLogPanel } from '../src/components/audit_log_panel.js';

describe('AuditLogPanel §15.5', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="audit-container"></div>';
  });

  it('affiche les alertes et les actions sensibles du journal append-only', async () => {
    const panel = new AuditLogPanel('audit-container', 'studio-1');
    panel.auditLogs = [
      {
        id: 'log-1',
        action: 'login',
        user_email: 'test@studio.com',
        ip_address: '1.2.3.4',
        country_code: 'FR',
        details: { mfa_used: true },
      },
    ];
    panel.securityAlerts = [
      {
        id: 'alt-1',
        alert_type: 'unusual_geolocation',
        severity: 'warning',
        user_email: 'test@studio.com',
        details: { message: 'Alerte géo' },
        is_resolved: false,
      },
    ];
    panel._render();

    const el = document.getElementById('audit-container');
    expect(el.querySelector('.alert-row')).not.toBeNull();
    expect(el.querySelector('.audit-row')).not.toBeNull();
  });
});
