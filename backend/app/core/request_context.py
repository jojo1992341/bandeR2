"""
Contexte de corrélation des requêtes (CDC §10.1).

`request_id` est propagé via une `ContextVar` afin d'être :
- ajouté aux logs structurés (filtre de logging) ;
- inclus dans le corps des erreurs uniformisées `{code, message, details, request_id}` ;
- renvoyé dans l'en-tête de réponse `X-Request-ID`.

La propagation par `ContextVar` garantit la bonne valeur même à travers le
threadpool des routes synchrones FastAPI.
"""

from __future__ import annotations

import contextvars
import uuid

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def new_request_id() -> str:
    return uuid.uuid4().hex


def get_request_id() -> str | None:
    return request_id_var.get()


def set_request_id(request_id: str) -> contextvars.Token:
    return request_id_var.set(request_id)


def reset_request_id(token: contextvars.Token) -> None:
    request_id_var.reset(token)
