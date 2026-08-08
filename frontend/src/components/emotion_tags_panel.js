import { store as defaultStore } from '../core/store.js';
import { api as defaultApi } from '../services/api.js';

/**
 * EmotionTagsPanel — Affichage indicatif des EmotionTag §8.2.5
 * Double analyse acoustique (wav2vec2) + textuelle (NLP FR)
 * → émotion perçue + intention, stockés en EmotionTag,
 *   affichés à titre indicatif sans jamais modifier automatiquement le texte.
 *   Seuls les codes typographiques sont suggérés (ex: majuscules pour cri, italique pour voix off).
 */

const EMOTION_LABELS_FR = {
  neutre: 'Neutre',
  joie: 'Joie',
  colere: 'Colère',
  tristesse: 'Tristesse',
  peur: 'Peur',
  surprise: 'Surprise',
};

const INTENTION_LABELS_FR = {
  affirmation: 'Affirmation',
  question: 'Question',
  ordre: 'Ordre',
  hesitation: 'Hésitation',
  exclamation: 'Exclamation',
};

const EMOTION_COLORS = {
  neutre: '#6b7280',
  joie: '#f59e0b',
  colere: '#ef4444',
  tristesse: '#3b82f6',
  peur: '#8b5cf6',
  surprise: '#ec4899',
};

const INTENTION_COLORS = {
  affirmation: '#10b981',
  question: '#06b6d4',
  ordre: '#f97316',
  hesitation: '#a3a3a3',
  exclamation: '#e11d48',
};

function formatScore(score) {
  return `${Math.round((score || 0) * 100)}%`;
}

function suggestionBadge(suggested) {
  if (!suggested || Object.keys(suggested).length === 0) return '';
  const map = {
    majuscules: 'MAJ suggérées',
    italique: 'Italique suggéré',
    parenthèses: 'Parenthèses suggérées',
    parentheses: 'Parenthèses suggérées',
    crochets: 'Crochets suggérés',
  };
  return Object.entries(suggested)
    .filter(([, v]) => v)
    .map(([k]) => `<span class="suggestion-badge" data-code="${k}">${map[k] || k}</span>`)
    .join(' ');
}

export function renderEmotionTags(replicaId, storeInstance = defaultStore) {
  const tags = storeInstance.getEmotionTags ? storeInstance.getEmotionTags(replicaId) : (storeInstance.emotionTags?.[replicaId] || []);
  if (!tags || tags.length === 0) {
    return '<div class="emotion-tags empty" data-testid="emotion-tags-empty">Aucune analyse émotionnelle disponible</div>';
  }
  const emotionTag = tags.find(t => t.tag_type === 'emotion') || tags[0];
  const intentionTag = tags.find(t => t.tag_type === 'intention') || tags[1];

  const emotionLabel = EMOTION_LABELS_FR[emotionTag?.label] || emotionTag?.label || '—';
  const intentionLabel = INTENTION_LABELS_FR[intentionTag?.label] || intentionTag?.label || '—';

  const emotionColor = EMOTION_COLORS[emotionTag?.label] || '#6b7280';
  const intentionColor = INTENTION_COLORS[intentionTag?.label] || '#6b7280';

  const suggested = storeInstance.getSuggestedTypoCodes
    ? storeInstance.getSuggestedTypoCodes(replicaId)
    : (emotionTag?.suggested_typo_codes || {});

  // Ne jamais afficher le texte modifié — on vérifie que le tag ne contient pas de texte altéré
  return `
    <div class="emotion-tags" data-testid="emotion-tags" data-replica-id="${replicaId}">
      <div class="emotion-row">
        <span class="tag emotion" style="background:${emotionColor}" data-testid="emotion-label" data-source="${emotionTag?.source || 'audio'}">
          Émotion: ${emotionLabel} <small>${formatScore(emotionTag?.score)}</small>
          <small class="source">(${emotionTag?.source || 'audio'})</small>
        </span>
        <span class="tag intention" style="background:${intentionColor}" data-testid="intention-label" data-source="${intentionTag?.source || 'texte'}">
          Intention: ${intentionLabel} <small>${formatScore(intentionTag?.score)}</small>
          <small class="source">(${intentionTag?.source || 'texte'})</small>
        </span>
      </div>
      ${Object.keys(suggested).length > 0 ? `<div class="suggested-typo" data-testid="suggested-typo">Codes suggérés (indicatif) : ${suggestionBadge(suggested)}</div>` : '<div class="suggested-typo empty" data-testid="suggested-typo-empty">Aucun code suggéré</div>'}
      <div class="emotion-hint" data-testid="emotion-hint">Affichage indicatif — le texte n'est jamais modifié automatiquement</div>
    </div>
  `;
}

export const EmotionTagsPanel = {
  render: (replicaId, storeInstance = defaultStore) => renderEmotionTags(replicaId, storeInstance),
};

// Chargement asynchrone des tags pour une réplique et mise à jour du store
export async function loadEmotionTags(replicaId, storeInstance = defaultStore, apiInstance = defaultApi) {
  try {
    const tags = await apiInstance.getReplicaEmotionTags(replicaId);
    if (storeInstance.setEmotionTags) {
      storeInstance.setEmotionTags(replicaId, tags);
    } else {
      storeInstance.emotionTags = storeInstance.emotionTags || {};
      storeInstance.emotionTags[replicaId] = tags;
    }
    return tags;
  } catch (e) {
    console.warn('loadEmotionTags failed', e);
    return [];
  }
}

export async function detectAndLoadEmotionTags(replicaId, storeInstance = defaultStore, apiInstance = defaultApi) {
  try {
    const tags = await apiInstance.detectReplicaEmotionTags(replicaId);
    if (storeInstance.setEmotionTags) {
      storeInstance.setEmotionTags(replicaId, tags);
    }
    return tags;
  } catch (e) {
    console.warn('detectAndLoadEmotionTags failed', e);
    return [];
  }
}

// Pour média / projet
export async function loadMediaEmotionTags(mediaId, storeInstance = defaultStore, apiInstance = defaultApi) {
  const tags = await apiInstance.getMediaEmotionTags(mediaId);
  // Grouper par replica
  const grouped = {};
  for (const t of tags) {
    const rid = t.replica_id;
    if (!grouped[rid]) grouped[rid] = [];
    grouped[rid].push(t);
  }
  for (const [rid, list] of Object.entries(grouped)) {
    if (storeInstance.setEmotionTags) storeInstance.setEmotionTags(rid, list);
  }
  return grouped;
}

export async function loadProjectEmotionTags(projectId, storeInstance = defaultStore, apiInstance = defaultApi) {
  const replicasWithEmotions = await apiInstance.getReplicasWithEmotions(projectId);
  for (const r of replicasWithEmotions) {
    if (storeInstance.setEmotionTags) {
      storeInstance.setEmotionTags(r.id, r.emotion_tags || []);
    }
  }
  return replicasWithEmotions;
}
