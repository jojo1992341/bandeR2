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
    return ['replica-id', 'text', 'start-ms', 'end-ms', 'speaker-id'];
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (oldVal !== newVal) this.render();
  }

  render() {
    const id = this.getAttribute('replica-id') || 'r-01';
    const text = this.getAttribute('text') || '';
    const startMs = parseInt(this.getAttribute('start-ms') || '0', 10);
    const endMs = parseInt(this.getAttribute('end-ms') || '1000', 10);
    const speakerId = this.getAttribute('speaker-id') || '';
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; position: relative; user-select: none; }
        .track { background: #2a2d3e; border: 2px solid #e11d48; border-radius: 4px; padding: 0.5rem 0.75rem; cursor: grab; }
        .handle { position: absolute; top: 0; bottom: 0; width: 6px; background: #ff9800; cursor: ew-resize; }
        .handle.left { left: 0; }
        .handle.right { right: 0; }
        .track:hover { border-color: #ff9800; }
        .edit-box { position: absolute; top: -8px; left: 10px; background: #1a1c2e; border: 1px solid #e11d48; border-radius: 4px; padding: 0.25rem; z-index: 10; }
      </style>
      <div class="track" draggable="true" data-id="${id}" data-start="${startMs}" data-end="${endMs}">
        <div class="handle left" data-edge="left"></div>
        <div class="text">${text}</div>
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
      const input = document.createElement('input');
      input.value = txt.innerText;
      input.className = 'edit-box';
      input.style.position = 'absolute';
      input.style.top = '0';
      input.style.left = '0';
      input.style.width = '100%';
      txt.replaceWith(input);
      input.focus();
      input.addEventListener('blur', () => {
        txt.innerText = input.value;
        input.replaceWith(txt);
        this.isEditing = false;
        // Déclencher mise à jour store + PATCH
        if (window.store && typeof window.store.setReplicas === 'function') {
          const updated = window.store.replicas.map(r => r.id === track.dataset.id ? { ...r, text: input.value } : r);
          window.store.setReplicas(updated);
        }
        this.dispatchEvent(new CustomEvent('rythmo:edit', { detail: { id: track.dataset.id, text: input.value }, bubbles: true }));
      });
    });

    track.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      const menu = document.createElement('div');
      menu.innerHTML = `<button onclick="this.closest('rythmo-track').dispatchEvent(new CustomEvent('rythmo:typo', {bubbles:true, detail:{code:'italic'}}))">Italique</button>`;
      menu.style.position = 'absolute';
      menu.style.zIndex = 100;
      track.appendChild(menu);
      setTimeout(() => menu.remove(), 2000);
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
