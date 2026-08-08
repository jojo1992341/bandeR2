/**
 * ReplicaLockIndicator §16.4 — Visual indicator showing who is editing a replica.
 *
 * Renders:
 *  - "🔒 Camille édite cette réplique" (amber, pulsating) when locked by another user
 *  - Nothing when not locked or locked by current user
 *  - Conflict message when a version conflict was detected
 *
 * Usage:
 *   const indicator = createLockIndicator(container, replicaId, lockInfo);
 *   indicator.update(newLockInfo);
 *   indicator.showConflict(message);
 *   indicator.destroy();
 */

const LOCK_ICON_SVG = `<svg class="replica-lock-indicator__icon" viewBox="0 0 16 16" fill="currentColor"><path d="M8 1a3 3 0 0 0-3 3v2H4a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-1V4a3 3 0 0 0-3-3zm2 5V4a2 2 0 1 0-4 0v2h4z"/></svg>`;

/**
 * Creates and attaches a lock indicator element to a container.
 *
 * @param {HTMLElement} container
 * @param {string} replicaId
 * @param {{ user_id: string, user_name: string }|null} lockInfo
 * @param {string} [currentUserId] — if lock is held by current user, don't show
 * @returns {{ el: HTMLElement, update: Function, showConflict: Function, destroy: Function }}
 */
export function createLockIndicator(container, replicaId, lockInfo, currentUserId = null) {
  const el = document.createElement('div');
  el.className = 'replica-lock-indicator';
  el.setAttribute('data-replica-id', replicaId);
  el.style.display = 'none';

  container.appendChild(el);

  function update(newLockInfo) {
    if (!newLockInfo || (currentUserId && newLockInfo.user_id === currentUserId)) {
      el.style.display = 'none';
      el.className = 'replica-lock-indicator';
      return;
    }

    el.style.display = 'inline-flex';
    el.className = 'replica-lock-indicator replica-lock-indicator--locked';
    el.innerHTML = `${LOCK_ICON_SVG}<span class="replica-lock-indicator__text">${newLockInfo.user_name} édite cette réplique</span>`;
  }

  function showConflict(message = 'Conflit de version détecté') {
    el.style.display = 'inline-flex';
    el.className = 'replica-lock-indicator replica-lock-indicator--conflict';
    el.innerHTML = `<span class="replica-lock-indicator__text">⚠ ${message}</span>`;
  }

  function destroy() {
    el.remove();
  }

  // Initial render
  update(lockInfo);

  return { el, update, showConflict, destroy };
}

/**
 * Renders lock indicator markup as an HTML string (for SSR / innerHTML).
 *
 * @param {{ user_name: string }} lockInfo
 * @returns {string}
 */
export function renderLockIndicatorHTML(lockInfo) {
  if (!lockInfo) return '';
  return `<span class="replica-lock-indicator replica-lock-indicator--locked">${LOCK_ICON_SVG}<span class="replica-lock-indicator__text">${lockInfo.user_name} édite cette réplique</span></span>`;
}
