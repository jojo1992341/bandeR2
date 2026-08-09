"""
Tests du contrat OpenAPI 3.1 (CDC §10.5) — G-018.

Vérifie :
- ``docs/openapi.json`` correspond exactement au live (aucune dérive) ;
- l'artefact passe la validation OpenAPI 3.1 (``openapi-spec-validator``) ;
- les parcours principaux sont présents dans le contrat ;
- le schéma d'erreur uniforme est respecté à l'exécution.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# openapi-spec-validator est optionnel (skip si absent)
openapi_validate = pytest.importorskip("openapi_spec_validator").validate

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]  # backend/tests/unit/ -> repo root
ARTIFACT = REPO_ROOT / "docs" / "openapi.json"


def _load_artifact() -> dict:
    assert ARTIFACT.exists(), (
        f"Artefact OpenAPI manquant: {ARTIFACT}. "
        f"Régénérer avec: PYTHONPATH=backend python3 backend/scripts/generate_openapi.py"
    )
    return json.loads(ARTIFACT.read_text(encoding="utf-8"))


# ------------------------------------------------------------------
# 1. L'artefact correspond au live (aucune dérive de contrat)
# ------------------------------------------------------------------
def test_artifact_matches_live_app():
    """Le JSON committé doit être identique à l'OpenAPI généré par l'app."""
    artifact = _load_artifact()
    live = app.openapi()
    assert artifact == live, (
        "Dérive de contrat OpenAPI détectée : docs/openapi.json ne correspond pas "
        "à l'application. Régénérer avec: "
        "PYTHONPATH=backend python3 backend/scripts/generate_openapi.py"
    )


# ------------------------------------------------------------------
# 2. Validation OpenAPI 3.1
# ------------------------------------------------------------------
def test_artifact_validates_openapi_3_1():
    artifact = _load_artifact()
    openapi_validate(artifact)  # lève si invalide
    assert artifact["openapi"].startswith("3.1"), (
        f"Version OpenAPI attendue 3.1.x, trouvée: {artifact['openapi']}"
    )


# ------------------------------------------------------------------
# 3. Parcours principaux présents dans le contrat
# ------------------------------------------------------------------
EXPECTED_PATHS = {
    ("/auth/login", "post"),
    ("/auth/register", "post"),
    ("/api/v1/users/me", "get"),
    ("/api/v1/users/me", "patch"),
    ("/api/v1/users/me", "delete"),
    ("/api/v1/users", "get"),
    ("/api/v1/users/{user_id}", "get"),
    ("/api/v1/users/{user_id}/status", "patch"),
    ("/api/v1/projects", "get"),
    ("/api/v1/projects", "post"),
    ("/api/v1/projects/{project_id}", "get"),
    ("/api/v1/projects/{project_id}", "patch"),
    ("/api/v1/projects/{project_id}", "delete"),
    ("/api/v1/projects/{project_id}/activity", "get"),
    ("/api/v1/projects/{project_id}/transcript", "get"),
    ("/api/v1/transcript/segments/{segment_id}", "patch"),
    ("/api/v1/transcript/words/{word_id}", "patch"),
    ("/api/v1/users/me/preferences", "get"),
    ("/api/v1/users/me/preferences", "put"),
    ("/api/v1/studios/{studio_id}/users", "get"),
    ("/api/v1/studios/{studio_id}/teams", "get"),
    ("/api/v1/studios/{studio_id}/teams", "post"),
    ("/api/v1/studios/{studio_id}/folders", "get"),
    ("/api/v1/studios/{studio_id}/tags", "get"),
    ("/api/v1/studios/{studio_id}/tasks", "get"),
    ("/health", "get"),
}


def test_key_endpoints_present():
    artifact = _load_artifact()
    actual = set()
    for path, methods in artifact["paths"].items():
        for method in methods:
            actual.add((path, method))
    missing = EXPECTED_PATHS - actual
    assert not missing, f"Endpoints attendus manquants du contrat: {missing}"


def test_no_duplicate_operation_ids():
    artifact = _load_artifact()
    from collections import Counter

    op_ids = []
    for path, methods in artifact["paths"].items():
        for method, info in methods.items():
            if isinstance(info, dict) and "operationId" in info:
                op_ids.append(info["operationId"])
    dupes = {k: v for k, v in Counter(op_ids).items() if v > 1}
    assert not dupes, f"Operation IDs en doublon (casse les générateurs clients): {dupes}"


# ------------------------------------------------------------------
# 4. Schéma d'erreur uniforme vérifié à l'exécution
# ------------------------------------------------------------------
def test_error_schema_contract():
    """Le contrat d'erreur {code, message, details, request_id} est respecté."""
    client = TestClient(app, raise_server_exceptions=False)
    # 401 sans auth
    r = client.get("/api/v1/users/me")
    assert r.status_code == 401
    body = r.json()
    for field in ("code", "message", "details", "request_id"):
        assert field in body, f"Champ d'erreur manquant: {field}"
    assert body["code"] == "unauthorized"
    assert r.headers.get("X-Request-ID") == body["request_id"]

    # 422 validation
    r2 = client.post("/auth/register", json={"email": "bad"})
    assert r2.status_code == 422
    body2 = r2.json()
    assert body2["code"] == "validation_error"
    assert isinstance(body2["details"], list)
