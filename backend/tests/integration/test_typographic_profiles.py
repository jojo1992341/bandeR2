"""
Test d'intégration pour GET/PATCH /studios/{id}/typographic-profiles §10.2
§2.4 / §16.3 : configuration des codes typographiques et seuils de calibrage
avec plusieurs profils par studio.

Condition d'achèvement : test vérifiant qu'un profil personnalisé créé par un studio
est bien appliqué lors de la génération automatique de bande rythmo pour ce studio.
"""

import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal, engine
from app.core.password import hash_password
from app.core.auth_handler import create_access_token
from app.models import (
    Base,
    Studio,
    Project,
    MediaAsset,
    Replica,
    Word,
    TranscriptSegment,
    PipelineJob,
    TypographicProfile,
    User,
    StudioMembership,
    AuditLog,
    SecurityAlert,
    set_allow_audit_log_purge,
)

client = TestClient(app)

def get_db() -> Session:
    return SessionLocal()

def cleanup_profile_data(studio_name="Studio Typo §2.4"):
    db = get_db()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(AuditLog.user_email.in_(["typo_admin@studio.com", "typo_user@studio.com"])).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(SecurityAlert.user_email.in_(["typo_admin@studio.com", "typo_user@studio.com"])).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)
        studio = db.query(Studio).filter(Studio.name == studio_name).first()
        if studio:
            db.query(TypographicProfile).filter(TypographicProfile.studio_id == studio.id).delete(synchronize_session=False)
            projects = db.query(Project).filter(Project.studio_id == studio.id).all()
            for p in projects:
                for m in db.query(MediaAsset).filter(MediaAsset.project_id == p.id).all():
                    db.query(Word).filter(Word.segment_id.in_(db.query(TranscriptSegment.id).filter(TranscriptSegment.media_id == m.id))).delete(synchronize_session=False)
                    db.query(TranscriptSegment).filter(TranscriptSegment.media_id == m.id).delete(synchronize_session=False)
                    db.query(Replica).filter(Replica.media_id == m.id).delete(synchronize_session=False)
                    db.query(PipelineJob).filter(PipelineJob.project_id == p.id).delete(synchronize_session=False)
                    db.query(MediaAsset).filter(MediaAsset.id == m.id).delete(synchronize_session=False)
                db.query(Project).filter(Project.id == p.id).delete(synchronize_session=False)
            for email in ["typo_admin@studio.com", "typo_user@studio.com"]:
                u = db.query(User).filter(User.email == email).first()
                if u:
                    db.query(StudioMembership).filter(StudioMembership.user_id == u.id).delete(synchronize_session=False)
                    db.delete(u)
            db.delete(studio)
            db.commit()
    finally:
        db.close()

def test_get_patch_typographic_profiles_and_generation_applies_custom_profile():
    """
    Condition d'achèvement : un profil personnalisé créé par un studio
    est bien appliqué lors de la génération automatique de bande rythmo.
    """
    cleanup_profile_data()
    Base.metadata.create_all(bind=engine)
    db = get_db()
    try:
        # Setup studio + admin
        studio = Studio(id=uuid.uuid4(), name="Studio Typo §2.4", plan="pro")
        db.add(studio); db.commit(); db.refresh(studio)

        admin = User(id=uuid.uuid4(), email="typo_admin@studio.com", hashed_password=hash_password("TypoAdmin_99!@#"), role="owner", is_active=True)
        user = User(id=uuid.uuid4(), email="typo_user@studio.com", hashed_password=hash_password("TypoUser_99!@#"), role="adaptateur", is_active=True)
        db.add_all([admin, user]); db.commit(); db.refresh(admin); db.refresh(user)
        db.add(StudioMembership(studio_id=studio.id, user_id=admin.id, role="owner"))
        db.add(StudioMembership(studio_id=studio.id, user_id=user.id, role="adaptateur"))
        db.commit()

        token_admin = create_access_token({"sub": str(admin.id), "email": admin.email, "role": "owner"})
        token_user = create_access_token({"sub": str(user.id), "email": user.email, "role": "adaptateur"})
        headers_admin = {"Authorization": f"Bearer {token_admin}"}
        headers_user = {"Authorization": f"Bearer {token_user}"}

        # 1. GET initial -> vide
        resp = client.get(f"/api/v1/studios/{studio.id}/typographic-profiles", headers=headers_admin)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["count"] == 0
        assert data["profiles"] == []

        # 2. PATCH collection pour créer un profil personnalisé (admin)
        #    Ce profil a des codes distinctifs et des seuils custom
        custom_profile_payload = {
            "name": "Netflix FR",
            "description": "Profil Netflix avec seuils serrés",
            "codes": {"crochets": True, "majuscules": True, "italique": False, "parentheses": False},
            "thresholds": {"silence_ms": 200, "max_duration_ms": 8000, "syllable_rate_min": 4.5, "syllable_rate_max": 6.5},
            "is_default": True
        }
        resp = client.patch(f"/api/v1/studios/{studio.id}/typographic-profiles", json=custom_profile_payload, headers=headers_admin)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] in ("created", "created_default", "updated")
        # Vérifier GET après création
        resp = client.get(f"/api/v1/studios/{studio.id}/typographic-profiles", headers=headers_admin)
        assert resp.status_code == 200
        profiles = resp.json()["profiles"]
        assert len(profiles) == 1
        prof = profiles[0]
        assert prof["name"] == "Netflix FR"
        assert prof["codes"]["crochets"] is True
        assert prof["codes"]["majuscules"] is True
        # italique False -> non présent ou False
        assert prof["codes"].get("italique") is None or prof["codes"].get("italique") is False
        assert prof["thresholds"]["silence_ms"] == 200
        assert prof["thresholds"]["max_duration_ms"] == 8000
        assert prof["is_default"] is True
        profile_id = prof["id"]

        # 3. POST création d'un second profil (plusieurs profils par studio §16.3)
        second_payload = {
            "name": "TF1 Jeunesse",
            "codes": {"italique": True, "parentheses": True},
            "thresholds": {"silence_ms": 600, "max_duration_ms": 12000},
            "is_default": False
        }
        resp = client.post(f"/api/v1/studios/{studio.id}/typographic-profiles", json=second_payload, headers=headers_admin)
        assert resp.status_code == 201, resp.text
        assert resp.json()["name"] == "TF1 Jeunesse"
        resp = client.get(f"/api/v1/studios/{studio.id}/typographic-profiles", headers=headers_admin)
        assert resp.json()["count"] == 2
        assert len(resp.json()["profiles"]) == 2
        # Vérifier que le défaut est toujours Netflix FR
        default = resp.json()["default_profile"]
        assert default["name"] == "Netflix FR"

        # 4. PATCH bulk avec liste de profils (mise à jour + création)
        bulk_payload = {
            "profiles": [
                {"name": "Netflix FR", "codes": {"crochets": True, "majuscules": True, "italique": True}, "thresholds": {"silence_ms": 250}},
                {"name": "Arte", "codes": {"parentheses": True}, "thresholds": {"silence_ms": 400}}
            ]
        }
        resp = client.patch(f"/api/v1/studios/{studio.id}/typographic-profiles", json=bulk_payload, headers=headers_admin)
        assert resp.status_code == 200
        # Maintenant on doit avoir 3 profils (Netflix FR mis à jour, TF1 intact, Arte nouveau)
        resp = client.get(f"/api/v1/studios/{studio.id}/typographic-profiles", headers=headers_admin)
        assert resp.json()["count"] == 3
        names = {p["name"] for p in resp.json()["profiles"]}
        assert names == {"Netflix FR", "TF1 Jeunesse", "Arte"}
        # Vérifier que Netflix FR a bien été mis à jour (italique True, silence 250)
        netflix = next(p for p in resp.json()["profiles"] if p["name"] == "Netflix FR")
        assert netflix["codes"]["italique"] is True
        assert netflix["thresholds"]["silence_ms"] == 250

        # 5. PATCH individuel par profile_id
        arte_id = next(p["id"] for p in resp.json()["profiles"] if p["name"] == "Arte")
        resp = client.patch(f"/api/v1/studios/{studio.id}/typographic-profiles/{arte_id}", json={"codes": {"crochets": True, "majuscules": False}, "thresholds": {"max_duration_ms": 9000}}, headers=headers_admin)
        assert resp.status_code == 200
        assert resp.json()["codes"]["crochets"] is True

        # 6. Vérifier que non-admin ne peut pas PATCH (403)
        resp = client.patch(f"/api/v1/studios/{studio.id}/typographic-profiles", json={"name": "Hack", "codes": {}}, headers=headers_user)
        assert resp.status_code == 403, "Adaptateur ne doit pas pouvoir configurer les profils typographiques"

        # 7. Condition d'achèvement : profil personnalisé appliqué lors de génération rythmo
        #    Créer un projet + média + mots avec un gap qui distingue les seuils
        project = Project(id=uuid.uuid4(), studio_id=studio.id, title="Projet Profil Test", source_lang="fr", target_lang="fr", status="Pret_pour_edition")
        db.add(project); db.commit(); db.refresh(project)
        media = MediaAsset(id=uuid.uuid4(), project_id=project.id, storage_path="/tmp/test_profile.mp4", status="confirmed")
        db.add(media); db.commit(); db.refresh(media)
        # PipelineJob prêt
        job = PipelineJob(id=uuid.uuid4(), project_id=project.id, status="Prêt pour édition", progress_percent=100, current_step="done")
        db.add(job); db.commit()
        # Transcript avec mots : gap de 300ms entre "monde" et "Au"
        # Avec silence_ms 250 (Netflix FR) -> split, avec 400 (Arte) ou 500 défaut -> pas de split
        seg = TranscriptSegment(id=uuid.uuid4(), media_id=media.id, text="Bonjour le monde Au revoir", start_ms=0, end_ms=4000, language="fr", confidence_score=0.95)
        db.add(seg); db.commit(); db.refresh(seg)
        words_data = [
            ("Bonjour", 0, 500),
            ("le", 600, 700),
            ("monde", 800, 1200),
            # gap 400ms (1200->1600)
            ("Au", 1600, 1700),
            ("revoir", 1800, 2100),
        ]
        for w_text, s, e in words_data:
            db.add(Word(id=uuid.uuid4(), segment_id=seg.id, text=w_text, start_ms=s, end_ms=e, language="fr", confidence_score=0.9))
        db.commit()

        # Mettre à jour Netflix FR pour avoir un profil distinctif : silence 200, codes majuscules+crochets
        # On va le rendre default avec silence 200 pour le test de génération par défaut
        db2 = get_db()
        try:
            from app.models import TypographicProfile as TP
            netflix_prof = db2.query(TP).filter(TP.studio_id == studio.id, TP.name == "Netflix FR").first()
            netflix_prof.thresholds = {"silence_ms": 200, "max_duration_ms": 8000}
            netflix_prof.codes = {"crochets": True, "majuscules": True}
            netflix_prof.is_default = True
            db2.commit()
            # S'assurer que Arte est non-default
            arte_prof = db2.query(TP).filter(TP.id == uuid.UUID(arte_id)).first()
            arte_prof.is_default = False
            db2.commit()
        finally:
            db2.close()

        # Générer sans préciser de profile_id -> doit utiliser le défaut (Netflix FR, silence 200)
        resp = client.post(f"/api/v1/projects/{project.id}/rythmo/generate", json={"media_id": str(media.id)}, headers=headers_admin)
        assert resp.status_code == 200, resp.text
        gen_data = resp.json()
        assert gen_data["replica_count"] >= 2, f"Avec silence 200, gap 400 doit splitter en 2 répliques, trouvé {gen_data['replica_count']}"
        # Vérifier que les répliques ont bien les codes du profil Netflix FR
        replicas = db.query(Replica).filter(Replica.media_id == media.id).order_by(Replica.order_index).all()
        assert len(replicas) >= 2
        for r in replicas:
            assert r.typo_codes.get("crochets") is True, f"Réplique {r.id} doit avoir crochets du profil"
            assert r.typo_codes.get("majuscules") is True, f"Réplique {r.id} doit avoir majuscules du profil"
        # Vérifier que la réponse inclut le profil utilisé
        assert gen_data["typographic_profile"]["name"] == "Netflix FR"
        assert gen_data["typographic_profile"]["thresholds"]["silence_ms"] == 200

        # Nettoyer les répliques pour tester avec l'autre profil (Arte, silence 400 -> gap 400 ne doit PAS splitter ? gap == seuil non >)
        # gap 400 avec silence 400 -> gap > silence ? non (400 >400 false) donc 1 seule réplique
        # On supprime d'abord
        db.query(Replica).filter(Replica.media_id == media.id).delete(synchronize_session=False)
        db.commit()
        # Régénérer en passant explicitement le profil Arte
        resp = client.post(f"/api/v1/projects/{project.id}/rythmo/generate", json={"media_id": str(media.id), "typographic_profile_id": arte_id}, headers=headers_admin)
        assert resp.status_code == 200, resp.text
        gen_data2 = resp.json()
        # Arte a silence 400, gap 400 -> pas de split (car condition gap > silence_ms)
        # Donc 1 seule réplique attendue avec Arte
        # Mais Arte a aussi été patché à max_duration 9000, toujours 1
        replicas2 = db.query(Replica).filter(Replica.media_id == media.id).order_by(Replica.order_index).all()
        print(f"Arte replicas {len(replicas2)}")
        assert len(replicas2) == 1, f"Avec Arte silence 400, gap 400 ne doit pas splitter, attendu 1 réplique, trouvé {len(replicas2)}"
        # Vérifier codes Arte : crochets True, majuscules False -> majuscules absent
        for r in replicas2:
            assert r.typo_codes.get("crochets") is True
            assert r.typo_codes.get("majuscules") is None or r.typo_codes.get("majuscules") is False
            # Arte avait aussi parenthèses initialement mais après patch il a crochets + ??? Vérifier au moins crochets présent
        assert gen_data2["typographic_profile"]["name"] == "Arte"

        # 8. Test que thresholds max_duration_ms est aussi appliqué
        # Créer un nouveau média avec une réplique très longue (durée > max_duration)
        # Nettoyer d'abord
        db.query(Replica).filter(Replica.media_id == media.id).delete(synchronize_session=False)
        db.query(Word).filter(Word.segment_id == seg.id).delete(synchronize_session=False)
        db.query(TranscriptSegment).filter(TranscriptSegment.id == seg.id).delete(synchronize_session=False)
        db.commit()
        seg2 = TranscriptSegment(id=uuid.uuid4(), media_id=media.id, text="Mot " * 50, start_ms=0, end_ms=20000, language="fr", confidence_score=0.9)
        db.add(seg2); db.commit(); db.refresh(seg2)
        # Créer des mots espacés de 100ms sur 20 secondes
        for i in range(50):
            db.add(Word(id=uuid.uuid4(), segment_id=seg2.id, text=f"mot{i}", start_ms=i*400, end_ms=i*400+300, language="fr", confidence_score=0.9))
        db.commit()
        # Mettre Arte max_duration à 5000, Netflix à 8000, on va tester avec un profil à 5000
        # Créer un profil CustomShort
        resp = client.post(f"/api/v1/studios/{studio.id}/typographic-profiles", json={"name": "ShortCalib", "thresholds": {"silence_ms": 500, "max_duration_ms": 5000}, "codes": {"parentheses": True}}, headers=headers_admin)
        assert resp.status_code == 201
        short_id = resp.json()["id"]
        db.query(Replica).filter(Replica.media_id == media.id).delete(synchronize_session=False)
        db.commit()
        resp = client.post(f"/api/v1/projects/{project.id}/rythmo/generate", json={"media_id": str(media.id), "typographic_profile_id": short_id}, headers=headers_admin)
        assert resp.status_code == 200
        replicas_short = db.query(Replica).filter(Replica.media_id == media.id).order_by(Replica.order_index).all()
        # Avec max_duration 5000, sur 20s on doit avoir au moins 3-4 répliques
        assert len(replicas_short) >= 3, f"Avec max_duration 5000 sur 20s, attendu >=3 répliques, trouvé {len(replicas_short)}"
        for r in replicas_short:
            assert r.typo_codes.get("parentheses") is True

        # 9. Vérifier 404 sur studio inexistant
        fake_studio = uuid.uuid4()
        resp = client.get(f"/api/v1/studios/{fake_studio}/typographic-profiles", headers=headers_admin)
        assert resp.status_code == 404

        # 10. Vérifier 404 sur profil inexistant
        resp = client.get(f"/api/v1/studios/{studio.id}/typographic-profiles/{uuid.uuid4()}", headers=headers_admin)
        assert resp.status_code == 404

    finally:
        db.close()
        cleanup_profile_data()

def test_typographic_profile_isolation_between_studios():
    """Vérifie l'isolation multi-tenant des profils"""
    cleanup_profile_data(studio_name="Studio A Iso")
    cleanup_profile_data(studio_name="Studio B Iso")
    Base.metadata.create_all(bind=engine)
    db = get_db()
    try:
        studio_a = Studio(id=uuid.uuid4(), name="Studio A Iso", plan="pro")
        studio_b = Studio(id=uuid.uuid4(), name="Studio B Iso", plan="pro")
        db.add_all([studio_a, studio_b]); db.commit(); db.refresh(studio_a); db.refresh(studio_b)
        admin_a = User(id=uuid.uuid4(), email="typo_admin@studio.com", hashed_password=hash_password("pass"), role="owner", is_active=True)
        db.add(admin_a); db.commit(); db.refresh(admin_a)
        db.add(StudioMembership(studio_id=studio_a.id, user_id=admin_a.id, role="owner"))
        db.add(StudioMembership(studio_id=studio_b.id, user_id=admin_a.id, role="owner"))
        db.commit()
        token = create_access_token({"sub": str(admin_a.id), "email": admin_a.email, "role": "owner"})
        headers = {"Authorization": f"Bearer {token}"}

        # Créer profil pour A
        resp = client.post(f"/api/v1/studios/{studio_a.id}/typographic-profiles", json={"name": "Profil A", "codes": {"crochets": True}}, headers=headers)
        assert resp.status_code == 201
        # Créer profil pour B avec même nom (doit être autorisé, unique par studio seulement)
        resp = client.post(f"/api/v1/studios/{studio_b.id}/typographic-profiles", json={"name": "Profil A", "codes": {"majuscules": True}}, headers=headers)
        assert resp.status_code == 201
        # Vérifier isolation
        resp_a = client.get(f"/api/v1/studios/{studio_a.id}/typographic-profiles", headers=headers)
        resp_b = client.get(f"/api/v1/studios/{studio_b.id}/typographic-profiles", headers=headers)
        assert resp_a.json()["count"] == 1
        assert resp_b.json()["count"] == 1
        assert resp_a.json()["profiles"][0]["codes"].get("crochets") is True
        assert resp_b.json()["profiles"][0]["codes"].get("majuscules") is True
    finally:
        db.close()
        cleanup_profile_data(studio_name="Studio A Iso")
        cleanup_profile_data(studio_name="Studio B Iso")
