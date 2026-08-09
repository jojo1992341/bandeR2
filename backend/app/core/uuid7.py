"""
Génération d'UUID v7 (RFC 9562) — clés primaires ordonnées temporellement (§9.5 CDC).

Un UUID v7 est constitué de :
- 48 bits de timestamp Unix (ms) en tête → l'ordre lexicographique des UUID
  correspond à l'ordre chronologique de création (avantage majeur pour
  l'indexation B-Tree par rapport aux UUID v4 aléatoires) ;
- 12 bits aléatoires (rand_a) ;
- 2 bits de variante (0b10) ;
- 62 bits aléatoires (rand_b).

Monotonicité intra-milliseconde garantie par un compteur process-local protégé
par un verrou : deux UUID générés durant la même ms sont produits dans l'ordre
croissant (incrémentation de rand_b), de sorte que la propriété d'ordre
temporel tient même sans granularité temporelle supérieure.

Compatibilité : les UUID v4 existants (données déjà présentes) cohabitent sans
problème avec les nouveaux UUID v7 — seul le bit de version diffère.
"""

from __future__ import annotations

import secrets
import threading
import time
from uuid import UUID

_LOCK = threading.Lock()
_last_ts_ms: int = 0
_last_rand_a: int = 0
_last_rand_b: int = 0

_VERSION_7 = 7
_VARIANT = 0b10


def uuid7(timestamp_ms: int | None = None) -> UUID:
    """
    Génère un UUID v7 (RFC 9562), monotone au sein du processus.

    Args:
        timestamp_ms: timestamp Unix en millisecondes ; si None, utilise l'heure
            courante. Permet de générer des UUID à des instants arbitraires
            (utile pour les tests d'ordre temporel).

    Returns:
        Un objet `uuid.UUID` de version 7, ordonné temporellement.
    """
    global _last_ts_ms, _last_rand_a, _last_rand_b

    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)

    ts = timestamp_ms & ((1 << 48) - 1)

    with _LOCK:
        if timestamp_ms > _last_ts_ms:
            _last_ts_ms = timestamp_ms
            _last_rand_a = secrets.randbits(12)
            _last_rand_b = secrets.randbits(62)
        else:
            # Même ms (ou skew d'horloge) : incrémenter pour préserver l'ordre.
            _last_ts_ms = timestamp_ms
            _last_rand_b = (_last_rand_b + 1) & ((1 << 62) - 1)
            if _last_rand_b == 0:
                _last_rand_a = (_last_rand_a + 1) & ((1 << 12) - 1)
        rand_a = _last_rand_a
        rand_b = _last_rand_b

    uuid_int = (
        (ts << 80)
        | (_VERSION_7 << 76)
        | (rand_a << 64)
        | (_VARIANT << 62)
        | rand_b
    )
    return UUID(int=uuid_int)
