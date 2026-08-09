"""
Schéma d'erreur commun et handlers d'exceptions uniformisés (CDC §10.1).

Toutes les erreurs API renvoient :
    { "code": ..., "message": ..., "details": ..., "request_id": ... }

- `code` : code machine lisible (not_found, forbidden, validation_error, ...).
- `message` : message humain.
- `details` : contexte optionnel (erreurs de validation, payload structuré).
- `request_id` : identifiant de corrélation (également dans l'en-tête
  `X-Request-ID` et les logs structurés).

Les exceptions internes (500) sont journalisées avec leur trace (et le
request_id) côté serveur mais **jamais** renvoyées au client : la réponse ne
contient qu'un message générique afin de ne pas divulguer d'information
sensible (secret, stacktrace).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.request_context import get_request_id

logger = logging.getLogger("rythmoai")

# Mapping code HTTP -> code machine.
STATUS_CODE_MAP = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


def code_for_status(status_code: int) -> str:
    return STATUS_CODE_MAP.get(status_code, f"error_{status_code}")


def _request_id(request: Request) -> str:
    """
    Récupère le request_id de corrélation. `request.state.request_id` (positionné
    par le middleware de corrélation) est la source la plus fiable : il persiste
    sur l'objet requête même à travers le chemin d'exception/TaskGroup où la
    `ContextVar` peut être perdue.
    """
    return (
        getattr(request.state, "request_id", None)
        or get_request_id()
        or "-"
    )


def error_body(
    code: str, message: str, details: Any, request_id: Optional[str]
) -> dict:
    return {
        "code": code,
        "message": message,
        "details": details,
        "request_id": request_id or "-",
    }


def _json(status_code: int, body: dict, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"X-Request-ID": request_id},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handler uniforme pour HTTPException (FastAPI + Starlette)."""
    request_id = _request_id(request)
    detail = exc.detail
    if isinstance(detail, dict):
        # Certaines routes lèvent detail={"code":..., "message":..., ...}
        code = detail.get("code") or code_for_status(exc.status_code)
        message = detail.get("message") or detail.get("detail") or "Erreur"
        extra = {k: v for k, v in detail.items() if k not in ("code", "message", "detail")}
        extra = extra or None
    else:
        code = code_for_status(exc.status_code)
        message = str(detail) if detail not in (None, "") else "Erreur"
        extra = None
    body = error_body(code, message, extra, request_id)
    # Champ `detail` conservé pour rétrocompatibilité (anciens clients/tests) ;
    # le contrat canonique reste {code, message, details, request_id}.
    body["detail"] = detail
    # Préserver les en-têtes de la réponse (ex. Retry-After sur 429).
    headers = {"X-Request-ID": request_id}
    if getattr(exc, "headers", None):
        headers.update(exc.headers)
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handler pour les erreurs de validation Pydantic (422)."""
    request_id = _request_id(request)
    return _json(
        422,
        error_body(
            "validation_error",
            "Erreur de validation des données",
            exc.errors(),
            request_id,
        ),
        request_id,
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    """
    Handler de dernier recours : journalise la trace (avec request_id) côté
    serveur et renvoie une réponse générique sans divulguer le détail interne.
    """
    request_id = _request_id(request)
    logger.exception(
        "Erreur interne non gérée [%s] %s %s: %s",
        request_id,
        request.method,
        request.url.path,
        exc,
    )
    return _json(
        500,
        error_body(
            "internal_error",
            "Une erreur interne est survenue. Contactez le support avec ce request_id.",
            None,
            request_id,
        ),
        request_id,
    )
