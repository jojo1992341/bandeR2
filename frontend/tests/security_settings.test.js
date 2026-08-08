import { describe, it, expect, vi, beforeEach } from 'vitest';
import { SecuritySettingsPanel } from '../src/components/security_settings_panel.js';

describe('SecuritySettingsPanel §15.4', () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="sec-container"></div>';
  });

  it('affiche les cases à cocher de protection des contenus', async () => {
    const panel = new SecuritySettingsPanel('sec-container', 'studio-1');
    panel.settings = {
      watermark_enabled: true,
      encryption_at_rest_enabled: true,
      encryption_in_transit_enabled: true,
      auto_purge_enabled: true,
      retention_days: 30,
    };
    panel._render();

    const el = document.getElementById('sec-container');
    expect(el.querySelector('#chk-watermark').checked).toBe(true);
    expect(el.querySelector('#chk-aes256').checked).toBe(true);
    expect(el.querySelector('#chk-tls13').checked).toBe(true);
    expect(el.querySelector('#chk-purge').checked).toBe(true);
  });
});
