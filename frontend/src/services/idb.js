/**
 * IndexedDB cache pour l'état d'édition §7.4, §17.3
 * Stocke les réplicas et le projet courant pour tolérer les micro-coupures réseau.
 * Fallback vers localStorage / mémoire si IndexedDB indisponible (jsdom, tests).
 */

const DB_NAME = 'rythmoai-cache';
const STORE_NAME = 'edits';
const DB_VERSION = 1;

// Fallback mémoire pour tests / environnements sans IndexedDB
const memoryFallback = new Map();

function hasIndexedDB() {
  try {
    return typeof indexedDB !== 'undefined' && indexedDB !== null && typeof indexedDB.open === 'function';
  } catch {
    return false;
  }
}

function hasLocalStorage() {
  try {
    return typeof localStorage !== 'undefined' && localStorage !== null;
  } catch {
    return false;
  }
}

function openDB() {
  return new Promise((resolve, reject) => {
    if (!hasIndexedDB()) {
      reject(new Error('IndexedDB not available'));
      return;
    }
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME);
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function idbPut(key, value) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const req = store.put(value, key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
    tx.onerror = () => reject(tx.error);
  });
}

async function idbGet(key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readonly');
    const store = tx.objectStore(STORE_NAME);
    const req = store.get(key);
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}

async function idbDelete(key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, 'readwrite');
    const store = tx.objectStore(STORE_NAME);
    const req = store.delete(key);
    req.onsuccess = () => resolve();
    req.onerror = () => reject(req.error);
    tx.oncomplete = () => db.close();
  });
}

// Clé générique pour l'état d'édition
function makeKey(projectId) {
  return projectId ? `replicas:${projectId}` : 'replicas:default';
}

export const idbCache = {
  async save(projectId, replicas) {
    const key = makeKey(projectId);
    const payload = {
      replicas: JSON.parse(JSON.stringify(replicas)),
      timestamp: Date.now(),
    };
    // Essayer IndexedDB d'abord
    if (hasIndexedDB()) {
      try {
        await idbPut(key, payload);
        return;
      } catch (e) {
        // fallback
      }
    }
    // Fallback localStorage
    if (hasLocalStorage()) {
      try {
        localStorage.setItem(`rythmo:${key}`, JSON.stringify(payload));
        return;
      } catch {}
    }
    // Fallback mémoire
    memoryFallback.set(key, payload);
  },

  async load(projectId) {
    const key = makeKey(projectId);
    if (hasIndexedDB()) {
      try {
        const res = await idbGet(key);
        if (res) return res;
      } catch {}
    }
    if (hasLocalStorage()) {
      try {
        const raw = localStorage.getItem(`rythmo:${key}`);
        if (raw) return JSON.parse(raw);
      } catch {}
    }
    if (memoryFallback.has(key)) {
      return memoryFallback.get(key);
    }
    return null;
  },

  async clear(projectId) {
    const key = makeKey(projectId);
    if (hasIndexedDB()) {
      try { await idbDelete(key); } catch {}
    }
    if (hasLocalStorage()) {
      try { localStorage.removeItem(`rythmo:${key}`); } catch {}
    }
    memoryFallback.delete(key);
  },

  // Pour tests : vérifier si une entrée existe
  async has(projectId) {
    const data = await this.load(projectId);
    return !!data;
  },

  // Pour tests : vider tout
  async clearAll() {
    if (hasIndexedDB()) {
      try {
        const db = await openDB();
        const tx = db.transaction(STORE_NAME, 'readwrite');
        tx.objectStore(STORE_NAME).clear();
        await new Promise((res, rej) => {
          tx.oncomplete = () => { db.close(); res(); };
          tx.onerror = () => rej(tx.error);
        });
      } catch {}
    }
    if (hasLocalStorage()) {
      try {
        Object.keys(localStorage).forEach(k => {
          if (k.startsWith('rythmo:replicas:')) localStorage.removeItem(k);
        });
      } catch {}
    }
    memoryFallback.clear();
  },

  // Exposer le fallback pour tests
  _memory: memoryFallback,
  _hasIDB: hasIndexedDB,
};
