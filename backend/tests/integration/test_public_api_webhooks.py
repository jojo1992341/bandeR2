"""
Tests §25.4 — API publique et webhooks.

Condition d'achèvement du goal :
  « un client externe de test peut, via un token API dédié, déclencher un
   traitement et recevoir une notification webhook à sa complétion. »

On lance un serveur HTTP local jouant le rôle du système tiers (ERP /
plateforme de droits), on crée un projet + média, on déclenche le traitement
via l'API publique et on vérifie qu'un webhook signé ``pipeline.completed``
est bien reçu.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, engine
from app.main import app
from app.models import (
    ApiKey,
    Base,
    Project,
    Studio,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.services import public_api_service

client = TestClient(app)


# ─────────────────────────────────────────────────────────────────────────────
# Serveur webhook tiers (simule un ERP / une plateforme de droits)
# ─────────────────────────────────────────────────────────────────────────────
class _WebhookRecorder(BaseHTTPRequestHandler):
    received: List[Dict[str, Any]] = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        record = {
            "path": self.path,
            "headers": {k: v for k, v in self.headers.items()},
            "body": body,
            "json": json.loads(body.decode("utf-8")) if body else {},
        }
        type(self).received.append(record)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *args, **kwargs):  # silencieux dans les tests
        pass


class _WebhookServer:
    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), _WebhookRecorder)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/webhook"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def _make_wav(path: str, duration: float = 2.0, sr: int = 16000) -> None:
    t = np.linspace(0, duration, int(sr * duration), endpoint=False).astype(np.float32)
    audio = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    pcm = (audio * 32767).astype("<i2").tobytes()
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm)


@pytest.fixture()
def studio_and_api_key(monkeypatch, tmp_path):
    # S'assurer que les nouvelles tables existent sur le schéma de test
    Base.metadata.create_all(bind=engine)

    monkeypatch.setenv("DATABASE_URL", os.getenv("DATABASE_URL", "sqlite:///:memory:"))
    monkeypatch.setenv("PUBLIC_API_WEBHOOK_ALLOW_LOOPBACK", "true")

    db = SessionLocal()
    try:
        studio = Studio(id=uuid.uuid4(), name="Studio ERP", plan="enterprise")
        db.add(studio)
        db.commit()
        db.refresh(studio)

        api_key_row, plaintext = public_api_service.create_api_key(
            db,
            studio_id=studio.id,
            name="Clé ERP production",
            scopes=[
                "project:read",
                "project:write",
                "export:write",
                "webhook:write",
            ],
            created_by="test@rythmoai.test",
        )
        yield studio, api_key_row, plaintext
    finally:
        db.close()


def _wait_for(predicate, timeout: float = 15.0, interval: float = 0.2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────
def test_external_client_triggers_processing_and_receives_webhook(
    studio_and_api_key, tmp_path
):
    studio, api_key_row, plaintext = studio_and_api_key
    auth = {"X-API-Key": plaintext}

    # 1) Le client externe crée un projet via l'API publique
    resp = client.post(
        "/api/v1/public/projects",
        headers=auth,
        json={
            "title": "Projet intégré ERP",
            "source_lang": "fr",
            "target_lang": "fr",
        },
    )
    assert resp.status_code == 201, resp.text
    project = resp.json()
    assert project["studio_id"] == str(studio.id)
    project_id = project["id"]

    # 2) Il enregistre un média (WAV local, pas de ffmpeg requis)
    wav_path = str(tmp_path / "media.wav")
    _make_wav(wav_path)
    resp = client.post(
        f"/api/v1/public/projects/{project_id}/media",
        headers=auth,
        json={"storage_path": wav_path, "duration_seconds": 2.0, "codec": "pcm_s16le"},
    )
    assert resp.status_code == 201, resp.text
    media = resp.json()
    assert media["status"] == "confirmed"

    # 3) Il enregistre son endpoint webhook — le serveur local simule l'ERP
    with _WebhookServer() as server:
        _WebhookRecorder.received.clear()
        resp = client.post(
            "/api/v1/public/webhooks",
            headers=auth,
            json={
                "url": server.url,
                "events": ["pipeline.completed", "pipeline.failed", "export.completed"],
                "description": "ERP production",
            },
        )
        assert resp.status_code == 201, resp.text
        webhook = resp.json()
        endpoint_id = webhook["id"]
        assert webhook["is_active"] is True

        # 4) Il déclenche le traitement + export automatique
        resp = client.post(
            f"/api/v1/public/projects/{project_id}/process",
            headers=auth,
            json={
                "media_id": media["id"],
                "auto_export": True,
                "export_format": "srt",
            },
        )
        assert resp.status_code == 202, resp.text
        job = resp.json()
        assert job["status"] in ("pending", "processing")
        job_id = job["job_id"]

        # 5) Le webhook pipeline.completed doit arriver au serveur tiers
        assert _wait_for(
            lambda: any(
                r["json"].get("event") == "pipeline.completed"
                for r in _WebhookRecorder.received
            )
        ), "Aucun webhook pipeline.completed reçu"

        completed = next(
            r
            for r in _WebhookRecorder.received
            if r["json"].get("event") == "pipeline.completed"
        )
        headers = completed["headers"]
        assert "X-RythmoAI-Signature" in headers
        assert headers["X-RythmoAI-Signature"].startswith("sha256=")
        assert "X-RythmoAI-Timestamp" in headers
        assert headers["X-RythmoAI-Event"] == "pipeline.completed"

        data = completed["json"]["data"]
        assert data["project_id"] == project_id
        assert data["status"] == "completed"
        assert data["auto_export"] is not None
        assert data["auto_export"]["format"] == "srt"

        # La signature est vérifiable avec le secret de l'endpoint
        db = SessionLocal()
        try:
            endpoint = (
                db.query(WebhookEndpoint)
                .filter(WebhookEndpoint.id == uuid.UUID(endpoint_id))
                .first()
            )
            assert endpoint is not None
            ok = public_api_service.verify_signature(
                endpoint.secret,
                completed["body"],
                headers["X-RythmoAI-Timestamp"],
                headers["X-RythmoAI-Signature"],
            )
            assert ok, "La signature HMAC du webhook est invalide"
        finally:
            db.close()

    # 6) Le job est bien terminal côté API
    resp = client.get(f"/api/v1/public/jobs/{job_id}", headers=auth)
    assert resp.status_code == 200, resp.text
    job_state = resp.json()
    assert job_state["status"] == "completed"
    assert job_state["progress_percent"] == 100

    # 7) L'export automatique est listable et disponible
    resp = client.get(f"/api/v1/public/projects/{project_id}/exports", headers=auth)
    assert resp.status_code == 200
    exports = resp.json()
    assert len(exports) >= 1
    srt_export = next(e for e in exports if e["format"] == "srt")
    assert srt_export["status"] == "completed"


def test_api_key_rejected_without_valid_credentials(studio_and_api_key):
    # Sans clé → 401
    resp = client.get("/api/v1/public/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 401

    # Clé invalide → 401
    resp = client.get(
        "/api/v1/public/projects/00000000-0000-0000-0000-000000000000",
        headers={"X-API-Key": "ryth_invalid_key_value"},
    )
    assert resp.status_code == 401


def test_api_key_scope_enforcement(studio_and_api_key):
    studio, _, _ = studio_and_api_key
    db = SessionLocal()
    try:
        _, readonly_key = public_api_service.create_api_key(
            db,
            studio_id=studio.id,
            name="Clé lecture seule",
            scopes=["project:read"],
        )
    finally:
        db.close()

    # Une clé sans project:write ne peut pas créer de projet
    resp = client.post(
        "/api/v1/public/projects",
        headers={"X-API-Key": readonly_key},
        json={"title": "Tentative interdite"},
    )
    assert resp.status_code == 403
    assert "Scopes manquants" in resp.json()["detail"]


def test_webhook_url_rejects_private_metadata_ips(studio_and_api_key):
    _, _, plaintext = studio_and_api_key
    # L'IP link-local AWS/GCP metadata doit être rejetée (anti-SSRF §15.7)
    resp = client.post(
        "/api/v1/public/webhooks",
        headers={"X-API-Key": plaintext},
        json={
            "url": "http://169.254.169.254/latest/meta-data",
            "events": ["pipeline.completed"],
        },
    )
    assert resp.status_code == 422
    assert (
        "interdite" in resp.json()["detail"].lower()
        or "résolution" in resp.json()["detail"].lower()
    )


def test_webhook_delivery_recorded_in_database(studio_and_api_key):
    studio, _, plaintext = studio_and_api_key
    with _WebhookServer() as server:
        _WebhookRecorder.received.clear()
        create_resp = client.post(
            "/api/v1/public/webhooks",
            headers={"X-API-Key": plaintext},
            json={"url": server.url, "events": ["pipeline.completed"]},
        )
        assert create_resp.status_code == 201
        endpoint_id = create_resp.json()["id"]

        # Émission synchrone directe via le service
        db = SessionLocal()
        try:
            deliveries = public_api_service.dispatch_event(
                db,
                studio.id,
                "pipeline.completed",
                {"hello": "world"},
                timeout=3.0,
            )
            assert len(deliveries) == 1
            assert deliveries[0].status == "delivered"
            assert deliveries[0].response_status_code == 200
            assert deliveries[0].attempts == 1
        finally:
            db.close()

    # L'endpoint liste ses livraisons (même serveur arrêté, elles sont en base)
    resp = client.get(
        f"/api/v1/public/webhooks/{endpoint_id}/deliveries",
        headers={"X-API-Key": plaintext},
    )
    assert resp.status_code == 200
    deliveries = resp.json()
    assert any(
        d["event"] == "pipeline.completed" and d["status"] == "delivered"
        for d in deliveries
    )


def test_failed_pipeline_sends_failure_webhook(
    studio_and_api_key, tmp_path, monkeypatch
):
    # Le pipeline de base est défensif (fallbacks). On force une erreur réelle
    # sur l'étape de transcription pour vérifier la notification d'échec.
    from app.tasks import pipeline as pipeline_mod

    class _ExplodingTask:
        def run(self, *args, **kwargs):
            raise RuntimeError("Échec simulé de transcription")

    monkeypatch.setattr(pipeline_mod, "transcribe_audio", _ExplodingTask())

    studio, _, plaintext = studio_and_api_key
    auth = {"X-API-Key": plaintext}

    project_resp = client.post(
        "/api/v1/public/projects",
        headers=auth,
        json={"title": "Projet échouant"},
    )
    project_id = project_resp.json()["id"]

    wav_path = str(tmp_path / "broken.wav")
    _make_wav(wav_path)
    media_resp = client.post(
        f"/api/v1/public/projects/{project_id}/media",
        headers=auth,
        json={"storage_path": wav_path},
    )
    media_id = media_resp.json()["id"]

    with _WebhookServer() as server:
        _WebhookRecorder.received.clear()
        client.post(
            "/api/v1/public/webhooks",
            headers=auth,
            json={"url": server.url, "events": ["pipeline.failed"]},
        )
        client.post(
            f"/api/v1/public/projects/{project_id}/process",
            headers=auth,
            json={"media_id": media_id},
        )
        assert _wait_for(
            lambda: any(
                r["json"].get("event") == "pipeline.failed"
                for r in _WebhookRecorder.received
            ),
            timeout=20.0,
        )
        failed = next(
            r
            for r in _WebhookRecorder.received
            if r["json"].get("event") == "pipeline.failed"
        )
        assert failed["json"]["data"]["status"] == "failed"
