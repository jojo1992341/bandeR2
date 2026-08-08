import uuid
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.core.password import hash_password
from app.models import (
    User,
    Studio,
    Project,
    MediaAsset,
    Replica,
    Export,
    AuditLog,
    SecurityAlert,
    AuditLogImmutableError,
    set_allow_audit_log_purge,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_test_audit_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(
                AuditLog.user_email.in_(
                    [
                        "audit_admin@studio.com",
                        "audit_user@studio.com",
                        "brute_target@studio.com",
                    ]
                )
            ).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(
                SecurityAlert.user_email.in_(
                    [
                        "audit_admin@studio.com",
                        "audit_user@studio.com",
                        "brute_target@studio.com",
                    ]
                )
            ).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)

        db.query(Export).filter(
            Export.created_by.in_(
                [
                    "audit_admin@studio.com",
                    "audit_user@studio.com",
                    "brute_target@studio.com",
                ]
            )
        ).delete(synchronize_session=False)
        from app.models import StudioInvitation, StudioMembership

        db.query(StudioInvitation).filter(
            StudioInvitation.email == "invited_audit@studio.com"
        ).delete(synchronize_session=False)
        users = (
            db.query(User)
            .filter(
                User.email.in_(
                    [
                        "audit_admin@studio.com",
                        "audit_user@studio.com",
                        "brute_target@studio.com",
                        "invited_audit@studio.com",
                    ]
                )
            )
            .all()
        )
        user_ids = [u.id for u in users]
        if user_ids:
            db.query(StudioMembership).filter(
                StudioMembership.user_id.in_(user_ids)
            ).delete(synchronize_session=False)
        db.query(User).filter(User.id.in_(user_ids)).delete(
            synchronize_session=False
        )
        db.commit()
    finally:
        db.close()


def test_audit_log_immutable_and_automatic_alerting():
    cleanup_test_audit_data()
    db = get_db_session()
    try:
        # 1. Setup : Studio, Admin et Utilisateur
        studio = Studio(id=uuid.uuid4(), name="Audit Studio", plan="pro")
        db.add(studio)
        db.commit()
        db.refresh(studio)

        admin_user = User(
            id=uuid.uuid4(),
            email="audit_admin@studio.com",
            hashed_password=hash_password("AuditSafe_Admin_99!@#"),
            role="owner",
            is_active=True,
        )
        normal_user = User(
            id=uuid.uuid4(),
            email="audit_user@studio.com",
            hashed_password=hash_password("AuditSafe_User_88!@#"),
            role="adaptateur",
            is_active=True,
        )
        db.add_all([admin_user, normal_user])
        db.commit()
        db.refresh(admin_user)
        db.refresh(normal_user)

        from app.models import StudioMembership

        db.add_all(
            [
                StudioMembership(
                    studio_id=studio.id, user_id=admin_user.id, role="owner"
                ),
                StudioMembership(
                    studio_id=studio.id,
                    user_id=normal_user.id,
                    role="adaptateur",
                ),
            ]
        )
        db.commit()

        # ------------------------------------------------------------------
        # A. ACTION SENSIBLE 1 : CONNEXIONS (avec horodatage)
        # ------------------------------------------------------------------
        resp_login = client.post(
            "/auth/login",
            json={
                "email": "audit_admin@studio.com",
                "password": "AuditSafe_Admin_99!@#",
            },
            headers={"x-country-code": "FR", "x-forwarded-for": "10.0.0.1"},
        )
        assert resp_login.status_code == 200
        token_admin = resp_login.json()["access_token"]
        headers_admin = {"Authorization": f"Bearer {token_admin}"}

        # Vérifier dans AuditLog qu'une entrée "login" a été générée
        login_log = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "login",
                AuditLog.user_email == "audit_admin@studio.com",
            )
            .first()
        )
        assert (
            login_log is not None
        ), "Une entrée AuditLog 'login' doit systématiquement être créée."
        assert login_log.ip_address == "10.0.0.1"
        assert login_log.country_code == "FR"
        assert login_log.created_at is not None

        # ------------------------------------------------------------------
        # CONDITION D'ACHÈVEMENT :
        # Test vérifiant qu'une tentative de modification d'une entrée
        # existante échoue (AuditLog est immuable / append-only)
        # ------------------------------------------------------------------
        log_id = login_log.id

        # 1. Tentative d'UPDATE d'une entrée existante via l'instance ORM -> ECHEC
        with pytest.raises((RuntimeError, AuditLogImmutableError)) as exc_info:
            login_log.action = "hacked_action"
            db.commit()
        assert "append-only" in str(exc_info.value).lower()
        db.rollback()

        # 2. Tentative d'UPDATE en masse via ORM update -> ECHEC
        with pytest.raises((RuntimeError, AuditLogImmutableError)) as exc_info2:
            db.query(AuditLog).filter(AuditLog.id == log_id).update(
                {"details": {"hacked": True}}
            )
        assert "append-only" in str(exc_info2.value).lower()
        db.rollback()

        # 3. Tentative de DELETE d'une entrée existante via ORM delete -> ECHEC
        with pytest.raises((RuntimeError, AuditLogImmutableError)) as exc_info3:
            db.query(AuditLog).filter(AuditLog.id == log_id).delete(
                synchronize_session=False
            )
        assert "append-only" in str(exc_info3.value).lower()
        db.rollback()

        # Vérifier en base que l'entrée est restée strictement intacte
        intact_log = (
            db.query(AuditLog).filter(AuditLog.id == log_id).first()
        )
        assert intact_log is not None
        assert intact_log.action == "login"
        assert intact_log.details.get("hacked") is None

        # ------------------------------------------------------------------
        # B. ACTIONS SENSIBLES 2 à 4 : PARTAGES, CHANGEMENTS DE DROITS, EXPORTS
        # ------------------------------------------------------------------
        # B1. Partage (invitation dans le studio)
        resp_invite = client.post(
            f"/api/v1/studios/{studio.id}/users/invite",
            json={"email": "invited_audit@studio.com", "role": "invité"},
            headers=headers_admin,
        )
        assert resp_invite.status_code == 201

        invite_log = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "studio_invite",
                AuditLog.studio_id == studio.id,
            )
            .first()
        )
        assert (
            invite_log is not None
        ), "Une entrée AuditLog 'studio_invite' doit systématiquement être créée."
        assert (
            invite_log.details.get("invited_email")
            == "invited_audit@studio.com"
        )

        # B2. Changement de droits (modification du rôle de normal_user)
        resp_role = client.put(
            f"/api/v1/studios/{studio.id}/users/{normal_user.id}",
            json={"role": "chef_de_projet"},
            headers=headers_admin,
        )
        assert resp_role.status_code == 200

        role_log = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "role_change",
                AuditLog.studio_id == studio.id,
            )
            .first()
        )
        assert (
            role_log is not None
        ), "Une entrée AuditLog 'role_change' doit systématiquement être créée."
        assert role_log.details.get("old_role") == "adaptateur"
        assert role_log.details.get("new_role") == "chef_de_projet"

        # B3. Création et téléchargement d'un export
        project = Project(
            id=uuid.uuid4(),
            studio_id=studio.id,
            title="Audit Project",
            source_lang="fr",
            target_lang="fr",
            status="draft",
        )
        db.add(project)
        db.commit()

        resp_export = client.post(
            f"/api/v1/projects/{project.id}/exports",
            json={"format": "pdf"},
            headers=headers_admin,
        )
        assert resp_export.status_code == 202
        export_id = resp_export.json()["id"]

        export_create_log = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "export_create",
                AuditLog.studio_id == studio.id,
            )
            .first()
        )
        assert (
            export_create_log is not None
        ), "Une entrée AuditLog 'export_create' doit systématiquement être créée."

        # Téléchargement de l'export
        resp_dl = client.get(
            f"/api/v1/exports/{export_id}/download", headers=headers_admin
        )
        assert resp_dl.status_code == 200

        export_dl_log = (
            db.query(AuditLog)
            .filter(AuditLog.action == "export_download")
            .first()
        )
        assert (
            export_dl_log is not None
        ), "Une entrée AuditLog 'export_download' doit systématiquement être créée."

        # Vérifier via l'API /api/v1/audit-logs que le journal complet est consultable
        resp_list_logs = client.get("/api/v1/audit-logs", headers=headers_admin)
        assert resp_list_logs.status_code == 200
        all_logs = resp_list_logs.json()
        actions_found = {item["action"] for item in all_logs}
        for expected_act in [
            "login",
            "studio_invite",
            "role_change",
            "export_create",
            "export_download",
        ]:
            assert expected_act in actions_found

        # ------------------------------------------------------------------
        # C. ALERTING AUTOMATIQUE SUR COMPORTEMENTS ANORMAUX (§15.5)
        # ------------------------------------------------------------------
        # C1. Alerte Géolocalisation inhabituelle :
        # audit_admin s'est connecté depuis "FR". S'il se connecte depuis un autre pays -> alerte
        resp_unusual_geo = client.post(
            "/auth/login",
            json={
                "email": "audit_admin@studio.com",
                "password": "AuditSafe_Admin_99!@#",
            },
            headers={"x-country-code": "RU", "x-forwarded-for": "80.80.80.80"},
        )
        assert resp_unusual_geo.status_code == 200

        geo_alert = (
            db.query(SecurityAlert)
            .filter(
                SecurityAlert.alert_type == "unusual_geolocation",
                SecurityAlert.user_email == "audit_admin@studio.com",
            )
            .first()
        )
        assert (
            geo_alert is not None
        ), "Une alerte de géolocalisation inhabituelle doit être automatiquement générée."
        assert geo_alert.details.get("detected_country") == "RU"
        assert "FR" in geo_alert.details.get("known_countries", [])

        # C2. Alerte Téléchargements massifs :
        # Répéter >= 5 téléchargements en peu de temps
        for _ in range(5):
            client.get(
                f"/api/v1/exports/{export_id}/download", headers=headers_admin
            )

        dl_alert = (
            db.query(SecurityAlert)
            .filter(SecurityAlert.alert_type == "massive_downloads")
            .first()
        )
        assert (
            dl_alert is not None
        ), "Une alerte 'massive_downloads' doit être automatiquement générée dès >= 5 téléchargements en 10 minutes."
        assert dl_alert.severity == "critical"

        # C3. Alerte Tentatives de force brute :
        # Répéter >= 3 échecs de connexion pour un compte
        for _ in range(3):
            client.post(
                "/auth/login",
                json={
                    "email": "brute_target@studio.com",
                    "password": "WrongPasswordHere",
                },
            )

        brute_alert = (
            db.query(SecurityAlert)
            .filter(
                SecurityAlert.alert_type == "brute_force",
                SecurityAlert.user_email == "brute_target@studio.com",
            )
            .first()
        )
        assert (
            brute_alert is not None
        ), "Une alerte 'brute_force' doit être automatiquement générée dès >= 3 échecs en 10 minutes."
        assert brute_alert.severity == "critical"

        # Vérifier la consultation et la résolution des alertes via l'API
        resp_list_alerts = client.get(
            "/api/v1/security-alerts", headers=headers_admin
        )
        assert resp_list_alerts.status_code == 200
        alert_types_found = {a["alert_type"] for a in resp_list_alerts.json()}
        assert "unusual_geolocation" in alert_types_found
        assert "massive_downloads" in alert_types_found
        assert "brute_force" in alert_types_found

        # Résoudre une alerte
        alert_id_to_resolve = geo_alert.id
        resp_resolve = client.post(
            f"/api/v1/security-alerts/{alert_id_to_resolve}/resolve",
            headers=headers_admin,
        )
        assert resp_resolve.status_code == 200
        assert resp_resolve.json()["is_resolved"] is True

    finally:
        cleanup_test_audit_data()
        db.close()
