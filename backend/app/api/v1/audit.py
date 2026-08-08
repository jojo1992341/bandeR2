import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.rbac import get_optional_user_payload
from app.models import AuditLog, SecurityAlert

router = APIRouter()


@router.get("/audit-logs", response_model=List[dict])
@router.get("/api/v1/audit-logs", response_model=List[dict])
def list_audit_logs(
    studio_id: Optional[uuid.UUID] = Query(None),
    user_id: Optional[uuid.UUID] = Query(None),
    user_email: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    query = db.query(AuditLog)
    if studio_id:
        query = query.filter(AuditLog.studio_id == studio_id)
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if user_email:
        query = query.filter(AuditLog.user_email == user_email)
    if action:
        query = query.filter(AuditLog.action == action)

    logs = (
        query.order_by(AuditLog.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "user_id": str(log.user_id) if log.user_id else None,
            "user_email": log.user_email,
            "studio_id": str(log.studio_id) if log.studio_id else None,
            "ip_address": log.ip_address,
            "country_code": log.country_code,
            "details": log.details or {},
            "created_at": (
                log.created_at.isoformat() if log.created_at else None
            ),
        }
        for log in logs
    ]


@router.get("/security-alerts", response_model=List[dict])
@router.get("/api/v1/security-alerts", response_model=List[dict])
def list_security_alerts(
    studio_id: Optional[uuid.UUID] = Query(None),
    user_email: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    is_resolved: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    query = db.query(SecurityAlert)
    if studio_id:
        query = query.filter(SecurityAlert.studio_id == studio_id)
    if user_email:
        query = query.filter(SecurityAlert.user_email == user_email)
    if alert_type:
        query = query.filter(SecurityAlert.alert_type == alert_type)
    if is_resolved is not None:
        query = query.filter(SecurityAlert.is_resolved == is_resolved)

    alerts = (
        query.order_by(SecurityAlert.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(alert.id),
            "alert_type": alert.alert_type,
            "user_id": str(alert.user_id) if alert.user_id else None,
            "user_email": alert.user_email,
            "studio_id": str(alert.studio_id) if alert.studio_id else None,
            "severity": alert.severity,
            "details": alert.details or {},
            "is_resolved": alert.is_resolved,
            "created_at": (
                alert.created_at.isoformat() if alert.created_at else None
            ),
        }
        for alert in alerts
    ]


@router.post("/security-alerts/{alert_id}/resolve", response_model=dict)
@router.post("/api/v1/security-alerts/{alert_id}/resolve", response_model=dict)
def resolve_security_alert(
    alert_id: uuid.UUID,
    db: Session = Depends(get_db),
    payload: Optional[dict] = Depends(get_optional_user_payload),
):
    alert = (
        db.query(SecurityAlert).filter(SecurityAlert.id == alert_id).first()
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.is_resolved = True
    db.commit()
    db.refresh(alert)
    return {
        "id": str(alert.id),
        "status": "resolved",
        "is_resolved": True,
        "message": "Security alert resolved successfully",
    }
