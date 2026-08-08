import { store as defaultStore } from '../core/store.js';
import { api as defaultApi } from '../services/api.js';

/**
 * TypographicProfilesPanel §2.4 / §10.2 / §16.3
 * Gestion des profils typographiques par studio (codes + seuils de calibrage)
 * Plusieurs profils possibles par studio (ex: un par diffuseur/client)
 */

export function renderTypographicProfiles(storeInstance = defaultStore) {
  const profiles = storeInstance.getTypographicProfiles ? storeInstance.getTypographicProfiles() : (storeInstance.typographicProfiles || []);
  if (!profiles || profiles.length === 0) {
    return '<div class="typo-profiles empty" data-testid="typo-profiles-empty">Aucun profil typographique</div>';
  }
  const rows = profiles.map(p => `
    <div class="typo-profile" data-testid="typo-profile" data-profile-id="${p.id}" data-is-default="${p.is_default}">
      <h4>${p.name} ${p.is_default ? '<span class="badge default">Défaut</span>' : ''}</h4>
      <div class="typo-codes" data-testid="typo-codes">Codes: ${Object.entries(p.codes || {}).filter(([,v])=>v).map(([k])=>k).join(', ') || 'aucun'}</div>
      <div class="typo-thresholds" data-testid="typo-thresholds">Seuils: ${Object.entries(p.thresholds || {}).map(([k,v])=>`${k}=${v}`).join(', ')}</div>
      ${p.description ? `<div class="typo-desc">${p.description}</div>` : ''}
    </div>
  `).join('');
  return `<div class="typo-profiles" data-testid="typo-profiles">${rows}</div>`;
}

export const TypographicProfilesPanel = {
  render: (storeInstance = defaultStore) => renderTypographicProfiles(storeInstance),
};

export async function loadTypographicProfiles(studioId, storeInstance = defaultStore, apiInstance = defaultApi) {
  try {
    const data = await apiInstance.getTypographicProfiles(studioId);
    const profiles = data.profiles || [];
    if (storeInstance.setTypographicProfiles) {
      storeInstance.setTypographicProfiles(profiles);
    } else {
      storeInstance.typographicProfiles = profiles;
    }
    return data;
  } catch (e) {
    console.warn('loadTypographicProfiles failed', e);
    return { profiles: [] };
  }
}

export async function createTypographicProfile(studioId, profile, storeInstance = defaultStore, apiInstance = defaultApi) {
  const created = await apiInstance.createTypographicProfile(studioId, profile);
  // Recharger la liste
  await loadTypographicProfiles(studioId, storeInstance, apiInstance);
  return created;
}

export async function patchTypographicProfiles(studioId, patch, storeInstance = defaultStore, apiInstance = defaultApi) {
  const result = await apiInstance.patchTypographicProfiles(studioId, patch);
  await loadTypographicProfiles(studioId, storeInstance, apiInstance);
  return result;
}

export async function patchTypographicProfile(studioId, profileId, patch, storeInstance = defaultStore, apiInstance = defaultApi) {
  const updated = await apiInstance.patchTypographicProfile(studioId, profileId, patch);
  await loadTypographicProfiles(studioId, storeInstance, apiInstance);
  return updated;
}
