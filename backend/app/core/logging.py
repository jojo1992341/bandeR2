"""
Logging structuré avec `request_id` de corrélation (CDC §10.1).

Un filtre injecte `request_id` (depuis le contexte de requête) dans chaque
enregistrement, et le format inclut `[req=<request_id>]`. Ainsi, le même
identifiant apparaît dans les logs que dans la réponse d'erreur uniformisée.
"""

import logging
import sys

from app.core.request_context import get_request_id


class RequestIdFilter(logging.Filter):
    """Injecte `request_id` dans chaque record de log."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id() or "-"
        return True


_FORMAT = "%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s: %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=_FORMAT,
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Le filtre doit être appliqué au handler racine pour couvrir tous les loggers.
for _h in logging.getLogger().handlers:
    _h.addFilter(RequestIdFilter())

logger = logging.getLogger("rythmoai")
