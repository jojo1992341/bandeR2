/**
 * RythmoTrack — Web Component pour l'affichage d'une réplique avec codes typographiques métier §2.4 et §9.4
 * Codes supportés (stockés dans typo_codes JSONB) :
 *  - crochets : [ entrée / sortie ]
 *  - italique : voix off / téléphone (italic)
 *  - majuscules : cris (MAJUSCULES)
 *  - parentheses : indications de jeu (parenthèses)
 */

export function formatReplicaText(text, typoCodes = {}) {
  if (!typoCodes || typeof typoCodes !== 'object') return text;
  let out = text || '';
  const normalized = {};
  // Normaliser les clés (aliases)
  for (const [k, v] of Object.entries(typoCodes)) {
    const key = String(k).toLowerCase();
    let canon = key;
    if (['brackets', 'bracket_in', 'bracket_out'].includes(key)) canon = 'crochets';
    else if (['italic', 'voix_off', 'off'].includes(key)) canon = 'italique';
    else if (['uppercase', 'cri', 'caps'].includes(key)) canon = 'majuscules';
    else if (['parentheses_jeu', 'indication_jeu', 'jeu'].includes(key)) canon = 'parentheses';
    normalized[canon] = v;
  }
  // Appliquer MAJUSCULES d'abord (transformation texte)
  if (normalized.majuscules) {
    out = out.toUpperCase();
  }
  // Parentheses ensuite
  if (normalized.parentheses) {
    out = `(${out})`;
  }
  // Crochets en dernier (enveloppe externe)
  if (normalized.crochets) {
    out = `[ ${out} ]`;
  }
  return out;
}

export function getTypoStyles(typoCodes = {}) {
  const styles = [];
  const normalized = {};
  for (const [k, v] of Object.entries(typoCodes || {})) {
    const key = String(k).toLowerCase();
    let canon = key;
    if (['brackets', 'bracket_in', 'bracket_out'].includes(key)) canon = 'crochets';
    else if (['italic', 'voix_off', 'off'].includes(key)) canon = 'italique';
    else if (['uppercase', 'cri', 'caps'].includes(key)) canon = 'majuscules';
    else if (['parentheses_jeu', 'indication_jeu', 'jeu'].includes(key)) canon = 'parentheses';
    normalized[canon] = v;
  }
  if (normalized.italique) styles.push('font-style: italic');
  if (normalized.majuscules) styles.push('text-transform: uppercase');
  return styles.join('; ');
}

export const TYPO_LABELS = {
  crochets: 'Crochets [ ]',
  italique: 'Italique (voix off)',
  majuscules: 'MAJUSCULES (cris)',
  parentheses: 'Parenthèses (jeu)',
};

export function renderSpeechRateBadge(speechRate, alert) {
  if (!speechRate || speechRate <= 0) return '';
  if (alert && alert.is_alert) {
    const isFast = alert.alert_type === 'too_fast';
    const colorClass = isFast
      ? 'speech-rate-badge--fast'
      : 'speech-rate-badge--slow';
    const icon = isFast ? '⚡' : '🐢';
    return `<span class="speech-rate-badge ${colorClass}" title="${
      alert.alert_message || ''
    }">${icon} ${speechRate} syll/s (ALERTE)</span>`;
  }
  return `<span class="speech-rate-badge speech-rate-badge--normal">${speechRate} syll/s</span>`;
}

class RythmoTrack extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this.render();
    this.dragStartX = 0;
    this.dragStartMs = 0;
    this.resizeEdge = null;
    this.isEditing = false;
  }

  static get observedAttributes() {
    return ['replica-id', 'text', 'start-ms', 'end-ms', 'speaker-id', 'typo-codes'];
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (oldVal !== newVal) this.render();
  }

  getTypoCodes() {
    const raw = this.getAttribute('typo-codes');
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch {
      return {};
    }
  }

  render() {
    const id = this.getAttribute('replica-id') || 'r-01';
    const rawText = this.getAttribute('text') || '';
    const startMs = parseInt(this.getAttribute('start-ms') || '0', 10);
    const endMs = parseInt(this.getAttribute('end-ms') || '1000', 10);
    const speakerId = this.getAttribute('speaker-id') || '';
    const typoCodes = this.getTypoCodes();
    const displayText = formatReplicaText(rawText, typoCodes);
    const typoStyles = getTypoStyles(typoCodes);
    // Classes pour tests visuels
    const classes = ['text'];
    if (typoCodes.crochets || typoCodes.brackets) classes.push('typo-crochets');
    if (typoCodes.italique || typoCodes.italic || typoCodes.voix_off) classes.push('typo-italique');
    if (typoCodes.majuscules || typoCodes.uppercase) classes.push('typo-majuscules');
    if (typoCodes.parentheses) classes.push('typo-parentheses');
    // Data attribute pour tests e2e facile
    const typoCodesAttr = JSON.stringify(typoCodes);

    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; position: relative; user-select: none; }
        .track { background: #2a2d3e; border: 2px solid #e11d48; border-radius: 4px; padding: 0.5rem 0.75rem; cursor: grab; }
        .handle { position: absolute; top: 0; bottom: 0; width: 6px; background: #ff9800; cursor: ew-resize; }
        .handle.left { left: 0; }
        .handle.right { right: 0; }
        .track:hover { border-color: #ff9800; }
        .edit-box { position: absolute; top: -8px; left: 10px; background: #1a1c2e; border: 1px solid #e11d48; border-radius: 4px; padding: 0.25rem; z-index: 10; }
        .text.typo-italique { font-style: italic; color: #93c5fd; }
        .text.typo-majuscules { text-transform: uppercase; font-weight: 700; letter-spacing: 0.05em; }
        .text.typo-crochets { border-left: 2px solid #facc15; border-right: 2px solid #facc15; padding: 0 0.25rem; }
        .text.typo-parentheses { opacity: 0.9; font-style: italic; }
        .typo-menu { position: absolute; top: 100%; left: 0; background: #1a1c2e; border: 1px solid #3f3f46; border-radius: 6px; padding: 0.5rem; z-index: 100; min-width: 220px; box-shadow: 0 4px 12px rgba(0,0,0,0.4); }
        .typo-menu button { display: flex; align-items: center; justify-content: space-between; width: 100%; background: transparent; border: none; color: #e8e8ec; padding: 0.35rem 0.5rem; cursor: pointer; border-radius: 4px; font-size: 0.85rem; }
        .typo-menu button:hover { background: #2a2d3e; }
        .typo-menu button.active { background: #e11d48; color: white; }
        .typo-menu .check { margin-left: 0.5rem; }
      </style>
      <div class="track" draggable="true" data-id="${id}" data-start="${startMs}" data-end="${endMs}" data-typo='${typoCodesAttr.replace(/'/g, "&#39;")}'>
        <div class="handle left" data-edge="left"></div>
        <div class="${classes.join(' ')}" style="${typoStyles}" data-testid="replica-text">${displayText}</div>
        <div class="handle right" data-edge="right"></div>
      </div>
    `;
    this._bind();
  }

  _bind() {
    const track = this.shadowRoot.querySelector('.track');
    const handles = this.shadowRoot.querySelectorAll('.handle');
    if (!track) return;

    // Glisser déplacement
    track.addEventListener('dragstart', (e) => {
      this.dragStartMs = parseInt(track.dataset.start, 10);
      e.dataTransfer.setData('text/plain', JSON.stringify({ id: track.dataset.id, startMs: this.dragStartMs }));
      e.dataTransfer.effectAllowed = 'move';
    });

    track.addEventListener('dblclick', () => {
      this.isEditing = true;
      const txt = track.querySelector('.text');
      const raw = this.getAttribute('text') || '';
      const input = document.createElement('input');
      input.value = raw;
      input.className = 'edit-box';
      input.style.position = 'absolute';
      input.style.top = '0';
      input.style.left = '0';
      input.style.width = '100%';
      txt.replaceWith(input);
      input.focus();
      input.addEventListener('blur', () => {
        txt.innerText = formatReplicaText(input.value, this.getTypoCodes());
        input.replaceWith(txt);
        this.isEditing = false;
        // Dispatch pour que replica_editor gère via Command pattern (undoable) + API
        this.dispatchEvent(new CustomEvent('rythmo:edit', { detail: { id: track.dataset.id, text: input.value }, bubbles: true, composed: true }));
        // Fallback si replica_editor n'est pas initialisé : mise à jour directe via store.editReplicaText si dispo
        if (window.store && typeof window.store.editReplicaText === 'function' && !window._rythmoEditorInitialized) {
          window.store.editReplicaText(track.dataset.id, input.value);
        } else if (window.store && typeof window.store.setReplicas === 'function' && !window._rythmoEditorInitialized) {
          const updated = window.store.replicas.map(r => r.id === track.dataset.id ? { ...r, text: input.value } : r);
          window.store.setReplicas(updated);
        }
      });
      // Ctrl+Enter to validate
      input.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'Enter') input.blur();
      });
    });

    track.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      // Supprimer menu existant
      const existing = this.shadowRoot.querySelector('.typo-menu');
      if (existing) existing.remove();
      const typoCodes = this.getTypoCodes();
      const menu = document.createElement('div');
      menu.className = 'typo-menu';
      menu.setAttribute('data-testid', 'typo-menu');

      const codes = [
        { key: 'crochets', label: TYPO_LABELS.crochets },
        { key: 'italique', label: TYPO_LABELS.italique },
        { key: 'majuscules', label: TYPO_LABELS.majuscules },
        { key: 'parentheses', label: TYPO_LABELS.parentheses },
      ];
      codes.forEach(({ key, label }) => {
        const btn = document.createElement('button');
        btn.setAttribute('data-code', key);
        btn.setAttribute('data-testid', `typo-${key}`);
        const isActive = !!typoCodes[key];
        if (isActive) btn.classList.add('active');
        btn.innerHTML = `${label} <span class="check">${isActive ? '✓' : ''}</span>`;
        btn.addEventListener('click', (ev) => {
          ev.stopPropagation();
          const newValue = !typoCodes[key];
          // Dispatch event pour que l'éditeur (replica_editor) fasse le PATCH API
          this.dispatchEvent(new CustomEvent('rythmo:typo', {
            bubbles: true,
            composed: true,
            detail: { id: track.dataset.id, code: key, value: newValue, typoCodes: { ...typoCodes, [key]: newValue } }
          }));
          // Mise à jour visuelle immédiate (optimistic)
          const newCodes = { ...typoCodes, [key]: newValue };
          // Si désactivé, on pourrait supprimer la clé, mais on garde false pour traçabilité
          if (!newValue) delete newCodes[key];
          this.setAttribute('typo-codes', JSON.stringify(newCodes));
          menu.remove();
        });
        menu.appendChild(btn);
      });

      // Bouton fermer
      const closeBtn = document.createElement('button');
      closeBtn.textContent = 'Fermer';
      closeBtn.style.fontSize = '0.75rem';
      closeBtn.style.opacity = '0.7';
      closeBtn.addEventListener('click', () => menu.remove());
      menu.appendChild(closeBtn);

      track.appendChild(menu);
      // Auto-remove après 5s
      setTimeout(() => { if (menu.parentNode) menu.remove(); }, 5000);
      // Fermer au clic ailleurs
      const onClickOutside = (ev) => {
        if (!menu.contains(ev.target) && ev.target !== track) {
          menu.remove();
          document.removeEventListener('click', onClickOutside);
        }
      };
      setTimeout(() => document.addEventListener('click', onClickOutside), 100);
    });

    handles.forEach(h => {
      h.addEventListener('mousedown', (e) => {
        this.resizeEdge = h.dataset.edge;
        this.dragStartX = e.clientX;
        this.dragStartMs = parseInt(track.dataset.start, 10);
        document.body.style.cursor = 'ew-resize';
      });
    });
    document.addEventListener('mousemove', (e) => {
      if (!this.resizeEdge) return;
      const delta = e.clientX - this.dragStartX;
      const ratio = delta / 200; // simplifié
      const newMs = Math.max(0, Math.round(this.dragStartMs + ratio * 5000));
      const oldStart = parseInt(track.dataset.start, 10);
      const oldEnd = parseInt(track.dataset.end, 10);
      if (this.resizeEdge === 'left') {
        track.dataset.start = String(Math.min(newMs, oldEnd - 100));
      } else {
        track.dataset.end = String(Math.max(newMs, oldStart + 100));
      }
      this.dispatchEvent(new CustomEvent('rythmo:resize', { detail: { id: track.dataset.id, startMs: parseInt(track.dataset.start,10), endMs: parseInt(track.dataset.end,10) }, bubbles: true }));
    });
    document.addEventListener('mouseup', () => {
      this.resizeEdge = null;
      document.body.style.cursor = '';
    });
  }
}

customElements.define('rythmo-track', RythmoTrack);
