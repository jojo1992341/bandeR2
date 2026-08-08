import { describe, it, expect } from 'vitest';
import { renderSpeechRateBadge } from '../src/components/rythmo_track.js';

describe("Calcul et affichage du débit d'élocution §12.3", () => {
  it('affiche un badge normal dans la plage standard 5-7 syll/s', () => {
    const html = renderSpeechRateBadge(6.5, {
      is_alert: false,
      alert_type: 'normal',
    });
    expect(html).toContain('speech-rate-badge--normal');
    expect(html).toContain('6.5 syll/s');
    expect(html).not.toContain('ALERTE');
  });

  it("affiche un badge d'alerte lorsque le seuil est dépassé (>7 syll/s en FR standard)", () => {
    const html = renderSpeechRateBadge(10.0, {
      is_alert: true,
      alert_type: 'too_fast',
      alert_message: "Débit d'élocution trop élevé",
    });
    expect(html).toContain('speech-rate-badge--fast');
    expect(html).toContain('ALERTE');
    expect(html).toContain('⚡');
    expect(html).toContain("Débit d'élocution trop élevé");
  });
});
