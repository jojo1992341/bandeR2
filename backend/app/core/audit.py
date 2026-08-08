import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy.orm import Session
from app.models import (
    AuditLog,
    SecurityAlert,
    AuditLogImmutableError,
    set_allow_audit_log_purge,
)
from app.core.logging import logger


def get_client_ip(request=None) -> str:
    if not request:
        return "127.0.0.1"
    return (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or getattr(request.client, "host", "127.0.0.1")
        or "127.0.0.1"
    )


def get_client_country(request=None) -> str:
    if not request:
        return "FR"
    return (
        request.headers.get("x-country-code")
        or request.headers.get("x-user-country")
        or request.headers.get("x-geo-country")
        or request.headers.get("cf-ipcountry")
        or "FR"
    ).upper()


def record_audit_log(
    db: Session,
    action: str,
    user_id: Optional[uuid.UUID] = None,
    user_email: Optional[str] = None,
    studio_id: Optional[uuid.UUID] = None,
    ip_address: Optional[str] = None,
    country_code: Optional[str] = None,
    details: Optional[dict] = None,
    request=None,
) -> Optional[AuditLog]:
    """
    Enregistre de manière append-only une action sensible dans le journal AuditLog (§15.5).
    """
    if request:
        if not ip_address:
            ip_address = get_client_ip(request)
        if not country_code:
            country_code = get_client_country(request)
    try:
        log_entry = AuditLog(
            id=uuid.uuid4(),
            action=action,
            user_id=user_id,
            user_email=user_email,
            studio_id=studio_id,
            ip_address=ip_address or "127.0.0.1",
            country_code=country_code or "FR",
            details=details or {},
            created_at=datetime.now(timezone.utc),
        )
        db.add(log_entry)
        db.commit()
        db.refresh(log_entry)
        return log_entry
    except Exception as e:
        logger.error(f"Audit Log recording error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return None


def check_login_anomalies(
    db: Session,
    user_id: Optional[uuid.UUID],
    user_email: Optional[str],
    country_code: str,
    ip_address: str,
):
    """
    Détecte automatiquement les anomalies de connexion (§15.5) :
    - Connexions depuis des géolocalisations inhabituelles
    """
    if not user_id and not user_email:
        return
    try:
        query = db.query(AuditLog).filter(AuditLog.action == "login")
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        elif user_email:
            query = query.filter(AuditLog.user_email == user_email)

        prev_logs = query.all()
        known_countries = {
            log.country_code
            for log in prev_logs
            if log.country_code and log.country_code.strip()
        }

        if (
            known_countries
            and country_code
            and country_code not in known_countries
        ):
            alert = SecurityAlert(
                id=uuid.uuid4(),
                alert_type="unusual_geolocation",
                user_id=user_id,
                user_email=user_email,
                severity="warning",
                details={
                    "message": f"Connexion depuis une géolocalisation inhabituelle ({country_code})",
                    "known_countries": list(known_countries),
                    "detected_country": country_code,
                    "ip_address": ip_address,
                },
                created_at=datetime.now(timezone.utc),
            )
            db.add(alert)
            db.commit()
            record_audit_log(
                db,
                "security_alert",
                user_id=user_id,
                user_email=user_email,
                ip_address=ip_address,
                country_code=country_code,
                details={
                    "alert_type": "unusual_geolocation",
                    "detected_country": country_code,
                    "known_countries": list(known_countries),
                },
            )
    except Exception as e:
        logger.error(f"Anomaly check geolocation error: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def check_brute_force_anomalies(
    db: Session, user_email: str, ip_address: str, country_code: str
):
    """
    Détecte automatiquement les tentatives de force brute (§15.5) :
    - >= 3 échecs de connexion en 10 minutes
    """
    if not user_email:
        return
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        failed_count = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "login_failed",
                AuditLog.user_email == user_email,
                AuditLog.created_at >= cutoff,
            )
            .count()
        )
        if failed_count >= 3:
            alert = SecurityAlert(
                id=uuid.uuid4(),
                alert_type="brute_force",
                user_email=user_email,
                severity="critical",
                details={
                    "message": f"Tentatives de force brute détectées ({failed_count} échecs en 10 min)",
                    "failed_count": failed_count,
                    "time_window_minutes": 10,
                },
                created_at=datetime.now(timezone.utc),
            )
            db.add(alert)
            db.commit()
            record_audit_log(
                db,
                "security_alert",
                user_email=user_email,
                ip_address=ip_address,
                country_code=country_code,
                details={
                    "alert_type": "brute_force",
                    "failed_count": failed_count,
                },
            )
    except Exception as e:
        logger.error(f"Anomaly check brute force error: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def check_download_anomalies(
    db: Session,
    user_id: Optional[uuid.UUID],
    user_email: Optional[str],
    studio_id: Optional[uuid.UUID] = None,
):
    """
    Détecte automatiquement les comportements anormaux (§15.5) :
    - Téléchargements massifs (>= 5 téléchargements d'exports/médias en 10 minutes)
    """
    if not user_id and not user_email:
        return
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        query = db.query(AuditLog).filter(
            AuditLog.action.in_(
                [
                    "export_download",
                    "media_download",
                    "download",
                ]
            ),
            AuditLog.created_at >= cutoff,
        )
        if user_id:
            query = query.filter(AuditLog.user_id == user_id)
        elif user_email:
            query = query.filter(AuditLog.user_email == user_email)

        count = query.count()
        if count >= 5:
            alert = SecurityAlert(
                id=uuid.uuid4(),
                alert_type="massive_downloads",
                user_id=user_id,
                user_email=user_email,
                studio_id=studio_id,
                severity="critical",
                details={
                    "message": f"Comportement anormal : téléchargements massifs détectés ({count} téléchargements en 10 min)",
                    "download_count": count,
                    "time_window_minutes": 10,
                },
                created_at=datetime.now(timezone.utc),
            )
            db.add(alert)
            db.commit()
            record_audit_log(
                db,
                "security_alert",
                user_id=user_id,
                user_email=user_email,
                studio_id=studio_id,
                details={
                    "alert_type": "massive_downloads",
                    "download_count": count,
                },
            )
    except Exception as e:
        logger.error(f"Anomaly check massive downloads error: {e}")
        try:
            db.rollback()
        except Exception:
            pass
