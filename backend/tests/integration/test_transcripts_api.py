"""
Tests des APIs Transcript (CDC §10.2) — G-014.

Couvre : lecture paginée, correction segment/mot, retrouver les modifications,
historique, validation, pagination et permissions (anti-IDOR).

Harnais auto-contenu (SQLite synchrone + surcharge de `get_db`).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth_handler import create_access_token
from app.core.database import get_db
from app.core.password import hash_password
from app.main import app
from app.models import (
    Base,
    MediaAsset,
    Project,
    Studio,
    StudioMembership,
    TranscriptSegment,
    User,
    Word,
)


# ------------------------------------------------------------------
# Harnais
# ------------------------------------------------------------------
_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
Base.metadata.create_all(bind=_engine)
_TestingSessionLocal = sessionmaker(
    bind=_engine, autocommit=False, autoflush=False, expire_on_commit=False
)


def _override_get_db():
    db = _TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _isolate_get_db():
    saved = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


client = TestClient(app)


def _db():
    return _TestingSessionLocal()


def _clean():
    db = _db()
    try:
        for m in (Word, TranscriptSegment, MediaAsset, Project, StudioMembership, User, Studio):
            db.query(m).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


def _make_tenant(name: str):
    db = _db()
    try:
        studio_id = uuid.uuid4()
        user_id = uuid.uuid4()
        db.add(Studio(id=studio_id, name=name, plan="pro"))
        db.add(
            User(
                id=user_id,
                email=f"u_{name}@x.com",
                hashed_password=hash_password("Pass123!"),
                role="adaptateur",
                is_active=True,
            )
        )
        db.add(
            StudioMembership(
                id=uuid.uuid4(), studio_id=studio_id, user_id=user_id, role="adaptateur"
            )
        )
        db.commit()
        token = create_access_token(
            {"sub": str(user_id), "email": f"u_{name}@x.com", "role": "adaptateur", "tv": 0}
        )
        return {
            "studio_id": studio_id,
            "user_id": user_id,
            "headers": {"Authorization": f"Bearer {token}"},
        }
    finally:
        db.close()


def _seed_transcript(studio_id, n_segments=3, words_per_seg=2):
    """Crée projet + média + segments + mots directement en DB."""
    db = _db()
    try:
        project = Project(
            id=uuid.uuid4(), studio_id=studio_id, title="P", status="Pret_pour_edition"
        )
        db.add(project)
        db.flush()
        media = MediaAsset(
            id=uuid.uuid4(), project_id=project.id, storage_path="m.mp4", status="confirmed"
        )
        db.add(media)
        db.flush()
        segments = []
        for i in range(n_segments):
            seg = TranscriptSegment(
                id=uuid.uuid4(),
                media_id=media.id,
                text=f"segment {i}",
                start_ms=i * 1000,
                end_ms=i * 1000 + 900,
                language="fr",
            )
            db.add(seg)
            db.flush()
            for j in range(words_per_seg):
                db.add(
                    Word(
                        id=uuid.uuid4(),
                        segment_id=seg.id,
                        text=f"mot{i}-{j}",
                        start_ms=seg.start_ms + j * 100,
                        end_ms=seg.start_ms + j * 100 + 90,
                        language="fr",
                    )
                )
            segments.append(seg)
        db.commit()
        return {
            "project_id": project.id,
            "media_id": media.id,
            "segment_ids": [s.id for s in segments],
        }
    finally:
        db.close()


# ============================================================
# Lecture paginée
# ============================================================
class TestRead:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.data = _seed_transcript(self.a["studio_id"], n_segments=5, words_per_seg=2)

    def test_get_transcript_segments_with_words(self):
        r = client.get(
            f"/api/v1/projects/{self.data['project_id']}/transcript",
            headers=self.a["headers"],
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 5
        assert len(body["segments"]) == 5
        # Chaque segment contient ses mots
        for seg in body["segments"]:
            assert len(seg["words"]) == 2
            assert seg["is_manually_edited"] is False

    def test_pagination(self):
        r = client.get(
            f"/api/v1/projects/{self.data['project_id']}/transcript?page=1&page_size=2",
            headers=self.a["headers"],
        )
        body = r.json()
        assert body["total"] == 5
        assert len(body["segments"]) == 2
        r2 = client.get(
            f"/api/v1/projects/{self.data['project_id']}/transcript?page=3&page_size=2",
            headers=self.a["headers"],
        )
        assert len(r2.json()["segments"]) == 1  # 5 = 2+2+1


# ============================================================
# Correction + historique
# ============================================================
class TestCorrection:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.data = _seed_transcript(self.a["studio_id"], n_segments=2, words_per_seg=1)

    def test_patch_segment_text_and_history(self):
        sid = self.data["segment_ids"][0]
        r = client.patch(
            f"/api/v1/transcript/segments/{sid}",
            headers=self.a["headers"],
            json={"text": "corrigé", "end_ms": 1500},
        )
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "corrigé"
        assert r.json()["is_manually_edited"] is True
        # Historique
        h = client.get(
            f"/api/v1/transcript/segments/{sid}/history", headers=self.a["headers"]
        )
        assert h.status_code == 200
        fields = {e["field"] for e in h.json()}
        assert {"text", "end_ms"}.issubset(fields)

    def test_patch_word_and_history(self):
        db = _db()
        try:
            word_id = (
                db.query(Word)
                .filter(Word.segment_id == self.data["segment_ids"][0])
                .first()
                .id
            )
        finally:
            db.close()
        r = client.patch(
            f"/api/v1/transcript/words/{word_id}",
            headers=self.a["headers"],
            json={"text": "mot corrigé", "start_ms": 10, "end_ms": 80},
        )
        assert r.status_code == 200, r.text
        assert r.json()["text"] == "mot corrigé"
        assert r.json()["is_manually_edited"] is True
        h = client.get(
            f"/api/v1/transcript/words/{word_id}/history", headers=self.a["headers"]
        )
        assert {"text", "start_ms", "end_ms"}.issubset(
            {e["field"] for e in h.json()}
        )

    def test_validation_start_end(self):
        sid = self.data["segment_ids"][0]
        r = client.patch(
            f"/api/v1/transcript/segments/{sid}",
            headers=self.a["headers"],
            json={"start_ms": 500, "end_ms": 500},
        )
        assert r.status_code == 422


# ============================================================
# Flux de bout en bout (condition d'achèvement)
# ============================================================
class TestEndToEndFlow:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.data = _seed_transcript(self.a["studio_id"], n_segments=4, words_per_seg=1)

    def test_load_correct_find_modifications_and_history(self):
        h = self.a["headers"]
        pid = self.data["project_id"]
        seg0 = self.data["segment_ids"][0]

        # 1) Chargement initial : aucun segment édité
        r = client.get(f"/api/v1/projects/{pid}/transcript?edited_only=true", headers=h)
        assert r.json()["total"] == 0

        # 2) Correction d'un segment
        client.patch(
            f"/api/v1/transcript/segments/{seg0}",
            headers=h,
            json={"text": "segment corrigé"},
        )

        # 3) Retrouver les modifications : edited_only renvoie le segment corrigé
        r = client.get(f"/api/v1/projects/{pid}/transcript?edited_only=true", headers=h)
        body = r.json()
        assert body["total"] == 1
        assert body["segments"][0]["id"] == str(seg0)
        assert body["segments"][0]["is_manually_edited"] is True

        # 4) Historique du segment
        hist = client.get(
            f"/api/v1/transcript/segments/{seg0}/history", headers=h
        )
        assert hist.status_code == 200
        assert any(e["field"] == "text" for e in hist.json())
        assert hist.json()[0]["new_value"] == "segment corrigé"

        # 5) La relecture du segment reflète la correction
        seg = client.get(f"/api/v1/transcript/segments/{seg0}", headers=h)
        assert seg.json()["text"] == "segment corrigé"


# ============================================================
# Permissions (anti-IDOR)
# ============================================================
class TestPermissions:
    def setup_method(self):
        _clean()
        self.a = _make_tenant("A")
        self.b = _make_tenant("B")
        self.data = _seed_transcript(self.a["studio_id"], n_segments=1, words_per_seg=1)

    def test_unauthenticated(self):
        assert (
            client.get(
                f"/api/v1/projects/{self.data['project_id']}/transcript"
            ).status_code
            == 401
        )

    def test_cross_studio_project_transcript(self):
        r = client.get(
            f"/api/v1/projects/{self.data['project_id']}/transcript",
            headers=self.b["headers"],
        )
        assert r.status_code == 404

    def test_cross_studio_patch_segment(self):
        sid = self.data["segment_ids"][0]
        r = client.patch(
            f"/api/v1/transcript/segments/{sid}",
            headers=self.b["headers"],
            json={"text": "hack"},
        )
        assert r.status_code == 404
        # Le segment est inchangé
        db = _db()
        try:
            assert (
                db.query(TranscriptSegment).filter(TranscriptSegment.id == sid).first().text
                == "segment 0"
            )
        finally:
            db.close()

    def test_cross_studio_word(self):
        db = _db()
        try:
            word_id = (
                db.query(Word)
                .filter(Word.segment_id == self.data["segment_ids"][0])
                .first()
                .id
            )
        finally:
            db.close()
        r = client.patch(
            f"/api/v1/transcript/words/{word_id}",
            headers=self.b["headers"],
            json={"text": "hack"},
        )
        assert r.status_code == 404
        h = client.get(
            f"/api/v1/transcript/words/{word_id}/history", headers=self.b["headers"]
        )
        assert h.status_code == 404

    def test_cross_studio_history(self):
        sid = self.data["segment_ids"][0]
        assert (
            client.get(
                f"/api/v1/transcript/segments/{sid}/history", headers=self.b["headers"]
            ).status_code
            == 404
        )
