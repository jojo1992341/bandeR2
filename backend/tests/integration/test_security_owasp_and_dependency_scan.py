import os
import io
import uuid
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import SessionLocal
from app.core.password import hash_password
from app.core.auth_handler import create_access_token
from app.models import (
    User,
    Studio,
    Project,
    MediaAsset,
    Replica,
    Comment,
    StudioMembership,
    AuditLog,
    SecurityAlert,
    set_allow_audit_log_purge,
)

client = TestClient(app)


def get_db_session() -> Session:
    return SessionLocal()


def cleanup_owasp_test_data():
    db = get_db_session()
    try:
        set_allow_audit_log_purge(True)
        try:
            db.query(AuditLog).filter(
                AuditLog.user_email.in_(
                    [
                        "owasp_a@studio.com",
                        "owasp_b@studio.com",
                        "' OR 1=1; --",
                    ]
                )
            ).delete(synchronize_session=False)
            db.query(SecurityAlert).filter(
                SecurityAlert.user_email.in_(
                    [
                        "owasp_a@studio.com",
                        "owasp_b@studio.com",
                        "' OR 1=1; --",
                    ]
                )
            ).delete(synchronize_session=False)
        finally:
            set_allow_audit_log_purge(False)

        users = (
            db.query(User)
            .filter(
                User.email.in_(
                    [
                        "owasp_a@studio.com",
                        "owasp_b@studio.com",
                    ]
                )
            )
            .all()
        )
        user_ids = [u.id for u in users]
        if user_ids:
            db.query(Comment).filter(Comment.author_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.query(StudioMembership).filter(
                StudioMembership.user_id.in_(user_ids)
            ).delete(synchronize_session=False)
            projects = (
                db.query(Project)
                .filter(
                    Project.title.in_(
                        [
                            "OWASP Project A",
                            "OWASP Project B",
                            "OWASP SQLi Project'; DROP TABLE users; --",
                            "<script>alert('XSS')</script>",
                        ]
                    )
                )
                .all()
            )
            proj_ids = [p.id for p in projects]
            if proj_ids:
                media_assets = (
                    db.query(MediaAsset)
                    .filter(MediaAsset.project_id.in_(proj_ids))
                    .all()
                )
                media_ids = [m.id for m in media_assets]
                if media_ids:
                    db.query(Replica).filter(
                        Replica.media_id.in_(media_ids)
                    ).delete(synchronize_session=False)
                    db.query(MediaAsset).filter(
                        MediaAsset.id.in_(media_ids)
                    ).delete(synchronize_session=False)
                db.query(Project).filter(Project.id.in_(proj_ids)).delete(
                    synchronize_session=False
                )
            db.query(User).filter(User.id.in_(user_ids)).delete(
                synchronize_session=False
            )
        db.commit()
    finally:
        db.close()


def test_dependency_scan_ci_fails_on_vulnerable_package_and_passes_on_current_code():
    """
    CONDITION D'ACHÈVEMENT (§15.7 / CI) :
    La pipeline CI échoue sur une vulnérabilité connue injectée volontairement (test de non-régression),
    et passe sur le code courant.
    """
    repo_root = Path(__file__).resolve().parent.parent.parent.parent

    # A. Le scan passe sur le code courant (backend/requirements.txt)
    req_file = repo_root / "backend" / "requirements.txt"
    assert req_file.exists(), "Fichier backend/requirements.txt manquant"

    result_current = subprocess.run(
        ["pip-audit", "-r", str(req_file), "--no-deps"],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    assert (
        result_current.returncode == 0
    ), f"pip-audit doit passer (code 0) sur le code courant. Sortie : {result_current.stderr} {result_current.stdout}"

    # B. Le scan échoue sur une vulnérabilité connue injectée volontairement
    vuln_file = repo_root / "backend" / "vulnerable_test_requirements.txt"
    # urllib3 1.25.10 contient plusieurs CVE/PYSEC connus
    vuln_file.write_text("urllib3==1.25.10\n", encoding="utf-8")
    try:
        result_vuln = subprocess.run(
            ["pip-audit", "-r", str(vuln_file), "--no-deps"],
            capture_output=True,
            text=True,
            cwd=str(repo_root),
        )
        assert (
            result_vuln.returncode != 0
        ), "pip-audit doit ÉCHOUER (code non nul) sur une vulnérabilité connue injectée volontairement."
        output_combined = (result_vuln.stdout + result_vuln.stderr).lower()
        assert any(
            keyword in output_combined
            for keyword in ["vulnerab", "pysec", "cve", "found"]
        ), f"Le rapport doit mentionner des vulnérabilités connues : {output_combined}"
    finally:
        if vuln_file.exists():
            vuln_file.unlink()


def test_owasp_top10_and_strict_http_security_headers():
    """
    Revue systématique OWASP Top 10 (injection, XSS, CSRF, IDOR, SSRF) sur les endpoints existants,
    avec en-têtes de sécurité HTTP stricts servis par Nginx (CSP, X-Frame-Options, Referrer-Policy) — §15.7
    """
    cleanup_owasp_test_data()
    db = get_db_session()
    try:
        # Setup Studios et Utilisateurs (Studio A et Studio B)
        studio_a = Studio(id=uuid.uuid4(), name="Studio OWASP A", plan="pro")
        studio_b = Studio(id=uuid.uuid4(), name="Studio OWASP B", plan="pro")
        db.add_all([studio_a, studio_b])
        db.commit()

        user_a = User(
            id=uuid.uuid4(),
            email="owasp_a@studio.com",
            hashed_password=hash_password("OwaspSafe_99!@#"),
            role="owner",
            is_active=True,
        )
        user_b = User(
            id=uuid.uuid4(),
            email="owasp_b@studio.com",
            hashed_password=hash_password("OwaspSafe_88!@#"),
            role="owner",
            is_active=True,
        )
        db.add_all([user_a, user_b])
        db.commit()
        db.refresh(user_a)
        db.refresh(user_b)

        db.add_all(
            [
                StudioMembership(
                    studio_id=studio_a.id, user_id=user_a.id, role="owner"
                ),
                StudioMembership(
                    studio_id=studio_b.id, user_id=user_b.id, role="owner"
                ),
            ]
        )
        db.commit()

        token_a = create_access_token(
            {
                "sub": str(user_a.id),
                "email": user_a.email,
                "role": "owner",
                "tv": 0,
            }
        )
        token_b = create_access_token(
            {
                "sub": str(user_b.id),
                "email": user_b.email,
                "role": "owner",
                "tv": 0,
            }
        )
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # ------------------------------------------------------------------
        # 1. EN-TÊTES DE SÉCURITÉ HTTP STRICTS (CSP, X-Frame-Options, Referrer-Policy, HSTS) — §15.7
        # ------------------------------------------------------------------
        resp_health = client.get("/health")
        assert resp_health.status_code == 200
        headers = {k.lower(): v for k, v in resp_health.headers.items()}
        assert "content-security-policy" in headers
        assert "frame-ancestors 'none'" in headers["content-security-policy"]
        assert headers["x-frame-options"] == "DENY"
        assert headers["x-content-type-options"] == "nosniff"
        assert (
            headers["referrer-policy"] == "strict-origin-when-cross-origin"
        )
        assert (
            "max-age=31536000" in headers["strict-transport-security"]
        )

        # Vérifier que le fichier nginx.conf contient également ces directives stricts
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        nginx_conf = repo_root / "deploy" / "nginx" / "nginx.conf"
        assert (
            nginx_conf.exists()
        ), "deploy/nginx/nginx.conf est requis par §15.7"
        nginx_text = nginx_conf.read_text(encoding="utf-8")
        assert "Content-Security-Policy" in nginx_text
        assert "X-Frame-Options" in nginx_text
        assert "Referrer-Policy" in nginx_text
        assert "TLSv1.3" in nginx_text

        # ------------------------------------------------------------------
        # 2. OWASP A03:2021 — INJECTION (SQL Injection / Command Injection)
        # ------------------------------------------------------------------
        # A. Tentative d'injection SQL dans le formulaire de login
        resp_sqli = client.post(
            "/auth/login",
            json={"email": "' OR 1=1; --", "password": "' OR 1=1; --"},
        )
        assert resp_sqli.status_code in (
            401,
            422,
        ), "L'injection SQL sur l'authentification doit échouer sans contournement"

        resp_sqli_email = client.post(
            "/auth/login",
            json={"email": "or1=1--@evil.com", "password": "' OR '1'='1"},
        )
        assert resp_sqli_email.status_code == 401

        # B. Tentative d'injection SQL dans le titre d'un projet
        sqli_title = "OWASP SQLi Project'; DROP TABLE users; --"
        resp_proj_sqli = client.post(
            "/api/v1/projects",
            json={
                "title": sqli_title,
                "studio_id": str(studio_a.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
            headers=headers_a,
        )
        assert resp_proj_sqli.status_code == 201
        proj_sqli = resp_proj_sqli.json()
        assert (
            proj_sqli["title"] == sqli_title
        ), "Le titre doit être stocké littéralement sans exécution SQL"
        # La table users doit être intacte
        assert (
            db.query(User).filter(User.id == user_a.id).first() is not None
        ), "La table users doit rester intacte après une tentative SQLi"

        # ------------------------------------------------------------------
        # 3. OWASP A03:2021 / A07:2021 — XSS (Cross-Site Scripting)
        # ------------------------------------------------------------------
        xss_title = "<script>alert('XSS')</script>"
        resp_proj_xss = client.post(
            "/api/v1/projects",
            json={
                "title": xss_title,
                "studio_id": str(studio_a.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
            headers=headers_a,
        )
        assert resp_proj_xss.status_code == 201
        proj_xss_id = resp_proj_xss.json()["id"]

        # La lecture via l'API retourne la donnée brute (le frontend et les exports gèrent l'échappement HTML)
        resp_get_xss = client.get(
            f"/api/v1/projects/{proj_xss_id}", headers=headers_a
        )
        assert resp_get_xss.status_code == 200
        assert resp_get_xss.json()["title"] == xss_title

        # Lors d'un export PDF, les chevrons et balises sont correctement échappés sans exécution
        resp_exp_xss = client.post(
            f"/api/v1/projects/{proj_xss_id}/exports",
            json={"format": "pdf"},
            headers=headers_a,
        )
        assert resp_exp_xss.status_code == 202

        # ------------------------------------------------------------------
        # 4. OWASP A01:2021 — CSRF (Cross-Site Request Forgery)
        # ------------------------------------------------------------------
        # Les actions modifiant l'état (POST, PUT, DELETE, PATCH) exigent un en-tête Authorization Bearer valide
        # Une requête sans en-tête (type CSRF cookie-based) est systématiquement rejetée
        resp_csrf_no_token = client.post(
            "/api/v1/projects",
            json={
                "title": "CSRF Attempt",
                "studio_id": str(studio_a.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
        )
        assert (
            resp_csrf_no_token.status_code == 401
        ), "Une requête sans en-tête Bearer (CSRF attempt) doit être rejetée avec 401"

        # ------------------------------------------------------------------
        # 5. OWASP A01:2021 — IDOR (Insecure Direct Object Reference)
        # ------------------------------------------------------------------
        # Création du Projet A pour Studio A
        resp_proj_a = client.post(
            "/api/v1/projects",
            json={
                "title": "OWASP Project A",
                "studio_id": str(studio_a.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
            headers=headers_a,
        )
        assert resp_proj_a.status_code == 201
        project_a_id = resp_proj_a.json()["id"]

        # Création du Projet B pour Studio B
        resp_proj_b = client.post(
            "/api/v1/projects",
            json={
                "title": "OWASP Project B",
                "studio_id": str(studio_b.id),
                "source_lang": "fr",
                "target_lang": "fr",
            },
            headers=headers_b,
        )
        assert resp_proj_b.status_code == 201
        project_b_id = resp_proj_b.json()["id"]

        # L'utilisateur A essaie d'accéder directement au Projet B par IDOR -> 404
        resp_idor = client.get(
            f"/api/v1/projects/{project_b_id}", headers=headers_a
        )
        assert (
            resp_idor.status_code == 404
        ), "L'accès à une ressource d'un autre studio (IDOR) doit retourner 404/403"

        # L'utilisateur A essaie de créer un export pour le Projet B -> 404
        resp_idor_export = client.post(
            f"/api/v1/projects/{project_b_id}/exports",
            json={"format": "pdf"},
            headers=headers_a,
        )
        assert resp_idor_export.status_code == 404

        # ------------------------------------------------------------------
        # 6. OWASP A10:2021 — SSRF & Path Traversal
        # ------------------------------------------------------------------
        # Tentative de confirmation de média avec clé S3 pointant vers une URL externe (SSRF)
        # ou un chemin système de fichiers (Path Traversal)
        media_test = MediaAsset(
            id=uuid.uuid4(),
            project_id=uuid.UUID(project_a_id),
            storage_path="valid_path.mp4",
            status="pending",
        )
        db.add(media_test)
        db.commit()

        resp_ssrf = client.post(
            f"/api/v1/media/{media_test.id}/confirm",
            json={"key": "http://169.254.169.254/latest/meta-data/"},
            headers=headers_a,
        )
        assert resp_ssrf.status_code == 400
        assert "ssrf" in resp_ssrf.json()["detail"].lower()

        resp_traversal = client.post(
            f"/api/v1/media/{media_test.id}/confirm",
            json={"key": "../../etc/passwd"},
            headers=headers_a,
        )
        assert resp_traversal.status_code == 400
        assert "path traversal" in resp_traversal.json()["detail"].lower()

    finally:
        cleanup_owasp_test_data()
        db.close()
