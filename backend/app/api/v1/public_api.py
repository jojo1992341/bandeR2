"""
API publique §25.4 — intégration des ERP de production et plateformes de
gestion de droits.

Authentification par entête ``X-API-Key`` (clé opaque, hachée en base).
Les clés sont limitées à un studio (tenant) et portent des ``scopes``.

Endpoints :
  POST   /api/v1/public/projects                 créer un projet
  GET    /api/v1/public/projects/{id}            consulter un projet
  POST   /api/v1/public/projects/{id}/media      enregistrer un média
  POST   /api/v1/public/projects/{id}/process    déclencher un traitement
  GET    /api/v1/public/jobs/{id}                statut d'un job
  POST   /api/v1/public/projects/{id}/exports    déclencher un export
  GET    /api/v1/public/projects/{id}/exports    lister les exports
  GET    /api/v1/public/exports/{id}             consulter un export
  GET    /api/v1/public/exports/{id}/download    télécharger un export
  GET    /api/v1/public/webhooks                 lister les endpoints webhook
  POST   /api/v1/public/webhooks                 créer un endpoint webhook
  DELETE /api/v1/public/webhooks/{id}            révoquer un endpoint
  GET    /api/v1/public/webhooks/{id}/deliveries journal des livraisons

Gestion des clés (authentifiée par JWT utilisateur admin studio) :
  POST   /api/v1/studios/{id}/api-keys
  GET    /api/v1/studios/{id}/api-keys
  DELETE /api/v1/studios/{id}/api-keys/{key_id}
"""

from __future__ import annotations

import os
import uuid
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import get_current_user_payload, is_risky_role
from app.core.rate_limit import public_api_rate_limit
from app.models import (
    ApiKey,
    Export,
    MediaAsset,
    PipelineJob,
    Project,
    Studio,
    StudioMembership,
    WebhookDelivery,
    WebhookEndpoint,
)
from app.schemas.public_api import (
    ApiKeyCreateIn,
    ApiKeyCreatedOut,
    ApiKeyOut,
    ErrorOut,
    ExportIn,
    ExportOut,
    JobOut,
    ProcessIn,
    ProcessOut,
    PublicMediaIn,
    PublicMediaOut,
    PublicProjectCreateIn,
    PublicProjectOut,
    WebhookDeliveryOut,
    WebhookEndpointIn,
    WebhookEndpointOut,
)
from app.services import public_api_service
from app.services.public_processing_service import (
    create_processing_job,
    run_processing_job,
)

router = APIRouter()

# Durée maximale d'attente de la notification webhook côté tests
WEBHOOK_TIMEOUT = float(os.getenv("PUBLIC_API_WEBHOOK_TIMEOUT", "5.0"))
# Autorise les webhooks vers loopback (tests / environnement de recette)
WEBHOOK_ALLOW_LOOPBACK = os.getenv(
    "PUBLIC_API_WEBHOOK_ALLOW_LOOPBACK", "true"
).lower() in ("1", "true", "yes", "on")


# ─────────────────────────────────────────────────────────────────────────────
# Dépendances d'authentification
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_api_key(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> ApiKey:
    raw = x_api_key
    if not raw and authorization and authorization.lower().startswith("bearer "):
        # Accepter aussi ``Authorization: Bearer <api-key>``
        raw = authorization.split(" ", 1)[1].strip()
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Clé API requise (entête X-API-Key)",
        )
    api_key = public_api_service.get_api_key_by_hash(db, raw)
    if not api_key:
        raise HTTPException(status_code=401, detail="Clé API invalide")
    if not public_api_service.is_api_key_valid(api_key):
        raise HTTPException(status_code=401, detail="Clé API inactive ou expirée")
    public_api_service.touch_api_key_used(db, api_key)
    return api_key


def require_scopes(*scopes: str):
    allowed = set(scopes)

    def _dep(api_key: ApiKey = Depends(_resolve_api_key)) -> ApiKey:
        granted = set(api_key.scopes or [])
        if not allowed.issubset(granted):
            missing = sorted(allowed - granted)
            raise HTTPException(
                status_code=403,
                detail=f"Scopes manquants: {', '.join(missing)}",
            )
        return api_key

    return _dep


def _load_project_for_key(
    db: Session, project_id: uuid.UUID, api_key: ApiKey
) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project or project.studio_id != api_key.studio_id:
        raise HTTPException(status_code=404, detail="Projet non trouvé")
    return project


def _load_media_for_project(
    db: Session, project: Project, media_id: uuid.UUID
) -> MediaAsset:
    media = (
        db.query(MediaAsset)
        .filter(MediaAsset.id == media_id, MediaAsset.project_id == project.id)
        .first()
    )
    if not media:
        raise HTTPException(status_code=404, detail="Média non trouvé")
    return media


# ─────────────────────────────────────────────────────────────────────────────
# Gestion des clés API (JWT utilisateur admin)
# ─────────────────────────────────────────────────────────────────────────────
def _require_studio_admin(db: Session, studio_id: uuid.UUID, payload: dict) -> None:
    user_id = uuid.UUID(payload.get("sub"))
    membership = (
        db.query(StudioMembership)
        .filter(
            StudioMembership.studio_id == studio_id,
            StudioMembership.user_id == user_id,
        )
        .first()
    )
    role = (membership.role if membership else payload.get("role", "")).lower()
    if role not in ("owner", "admin", "chef_de_projet"):
        raise HTTPException(
            status_code=403, detail="Rôle administrateur de studio requis"
        )


@router.post(
    "/studios/{studio_id}/api-keys",
    response_model=ApiKeyCreatedOut,
    status_code=201,
    tags=["public-api-keys"],
)
def create_api_key_endpoint(
    studio_id: uuid.UUID,
    data: ApiKeyCreateIn,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    _require_studio_admin(db, studio_id, payload)
    if not db.query(Studio).filter(Studio.id == studio_id).first():
        raise HTTPException(status_code=404, detail="Studio non trouvé")
    api_key, plaintext = public_api_service.create_api_key(
        db,
        studio_id=studio_id,
        name=data.name,
        scopes=data.scopes,
        created_by=payload.get("email") or payload.get("sub"),
    )
    return _api_key_out(api_key, plaintext)


@router.get(
    "/studios/{studio_id}/api-keys",
    response_model=List[ApiKeyOut],
    tags=["public-api-keys"],
)
def list_api_keys(
    studio_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    _require_studio_admin(db, studio_id, payload)
    rows = (
        db.query(ApiKey)
        .filter(ApiKey.studio_id == studio_id)
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [_api_key_out(k) for k in rows]


@router.delete(
    "/studios/{studio_id}/api-keys/{key_id}",
    status_code=204,
    tags=["public-api-keys"],
)
def revoke_api_key(
    studio_id: uuid.UUID,
    key_id: uuid.UUID,
    payload: dict = Depends(get_current_user_payload),
    db: Session = Depends(get_db),
):
    _require_studio_admin(db, studio_id, payload)
    row = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.studio_id == studio_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Clé API non trouvée")
    row.is_active = False
    db.commit()
    return None


def _api_key_out(api_key: ApiKey, plaintext: Optional[str] = None) -> dict:
    data = {
        "id": str(api_key.id),
        "name": api_key.name,
        "key_prefix": api_key.key_prefix,
        "scopes": list(api_key.scopes or []),
        "is_active": bool(api_key.is_active),
        "last_used_at": api_key.last_used_at,
        "expires_at": api_key.expires_at,
        "created_at": api_key.created_at,
    }
    if plaintext is not None:
        data["api_key"] = plaintext
    return data


# ─────────────────────────────────────────────────────────────────────────────
# Projets & médias
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/public/projects",
    response_model=PublicProjectOut,
    status_code=201,
    tags=["public-api"],
    responses={401: {"model": ErrorOut}, 403: {"model": ErrorOut}},
)
def public_create_project(
    data: PublicProjectCreateIn,
    api_key: ApiKey = Depends(require_scopes("project:write")),
    db: Session = Depends(get_db),
):
    project = Project(
        id=uuid.uuid4(),
        studio_id=api_key.studio_id,
        title=data.title,
        source_lang=data.source_lang,
        target_lang=data.target_lang,
        status="Cree",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_out(project)


@router.get(
    "/public/projects/{project_id}",
    response_model=PublicProjectOut,
    tags=["public-api"],
)
def public_get_project(
    project_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("project:read")),
    db: Session = Depends(get_db),
):
    project = _load_project_for_key(db, project_id, api_key)
    return _project_out(project)


@router.post(
    "/public/projects/{project_id}/media",
    response_model=PublicMediaOut,
    status_code=201,
    tags=["public-api"],
)
def public_register_media(
    project_id: uuid.UUID,
    data: PublicMediaIn,
    api_key: ApiKey = Depends(require_scopes("project:write")),
    db: Session = Depends(get_db),
):
    project = _load_project_for_key(db, project_id, api_key)
    media = MediaAsset(
        id=uuid.uuid4(),
        project_id=project.id,
        storage_path=data.storage_path,
        duration_seconds=data.duration_seconds,
        codec=data.codec,
        fps=data.fps,
        resolution=data.resolution,
        status="confirmed",
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return PublicMediaOut(
        id=str(media.id),
        project_id=str(project.id),
        storage_path=media.storage_path,
        status=media.status,
        duration_seconds=media.duration_seconds,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Traitement & jobs
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/public/projects/{project_id}/process",
    response_model=ProcessOut,
    status_code=202,
    tags=["public-api"],
)
def public_process_project(
    project_id: uuid.UUID,
    data: ProcessIn,
    background_tasks: BackgroundTasks,
    request: Request,
    api_key: ApiKey = Depends(require_scopes("project:write")),
    db: Session = Depends(get_db),
):
    project = _load_project_for_key(db, project_id, api_key)
    media_id = uuid.UUID(data.media_id) if data.media_id else None
    media = _resolve_media_or_404(db, project, media_id)

    # Enregistrer un endpoint webhook fourni à la volée (usage ERP simple)
    if data.webhook_url:
        try:
            public_api_service.create_webhook_endpoint(
                db,
                studio_id=project.studio_id,
                url=str(data.webhook_url),
                events=data.webhook_events or ["pipeline.completed", "pipeline.failed"],
                api_key_id=api_key.id,
                description="Endpoint enregistré via /process",
                allow_loopback=WEBHOOK_ALLOW_LOOPBACK,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    options = dict(data.options or {})
    if data.source_separation:
        options["enable_source_separation"] = True
        options.setdefault("source_separation_backend", "spectral")
    options["auto_export"] = bool(data.auto_export)
    if data.auto_export:
        options["export_format"] = data.export_format

    job = create_processing_job(
        db,
        project_id=project.id,
        media_id=media.id,
        options=options,
        triggered_by=f"api_key:{api_key.key_prefix}",
    )

    # Lancer la chaîne en tâche de fond (la complétion déclenche le webhook)
    background_tasks.add_task(
        run_processing_job, str(job.id), str(project.id), str(media.id), options
    )
    return ProcessOut(
        job_id=str(job.id),
        project_id=str(project.id),
        media_id=str(media.id),
        status=job.status,
        progress_percent=job.progress_percent,
        current_step=job.current_step,
    )


def _resolve_media_or_404(
    db: Session, project: Project, media_id: Optional[uuid.UUID]
) -> MediaAsset:
    query = db.query(MediaAsset).filter(MediaAsset.project_id == project.id)
    if media_id:
        media = query.filter(MediaAsset.id == media_id).first()
    else:
        media = query.order_by(MediaAsset.created_at.desc()).first()
    if not media:
        raise HTTPException(
            status_code=422,
            detail="Aucun média confirmé disponible pour ce projet",
        )
    return media


@router.get("/public/jobs/{job_id}", response_model=JobOut, tags=["public-api"])
def public_get_job(
    job_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("project:read")),
    db: Session = Depends(get_db),
    _rl=Depends(public_api_rate_limit),
):
    job = db.query(PipelineJob).filter(PipelineJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")
    project = db.query(Project).filter(Project.id == job.project_id).first()
    if not project or project.studio_id != api_key.studio_id:
        raise HTTPException(status_code=404, detail="Job non trouvé")
    return _job_out(job)


def _job_out(job: PipelineJob) -> dict:
    return {
        "id": str(job.id),
        "project_id": str(job.project_id),
        "status": job.status,
        "progress_percent": job.progress_percent or 0,
        "current_step": job.current_step,
        "error_message": getattr(job, "error_message", None),
        "started_at": getattr(job, "started_at", None),
        "completed_at": getattr(job, "completed_at", None),
        "updated_at": job.updated_at,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Exports
# ─────────────────────────────────────────────────────────────────────────────
@router.post(
    "/public/projects/{project_id}/exports",
    response_model=ExportOut,
    status_code=202,
    tags=["public-api"],
)
def public_create_export(
    project_id: uuid.UUID,
    data: ExportIn,
    background_tasks: BackgroundTasks,
    api_key: ApiKey = Depends(require_scopes("export:write")),
    db: Session = Depends(get_db),
):
    project = _load_project_for_key(db, project_id, api_key)
    export = Export(
        id=uuid.uuid4(),
        project_id=project.id,
        format=data.format,
        status="pending",
        created_by=f"api_key:{api_key.key_prefix}",
        creator_role="client_externe",
        is_watermarked=is_risky_role("client_externe"),
    )
    db.add(export)
    db.commit()
    db.refresh(export)

    from app.api.v1 import exports as exports_module

    background_tasks.add_task(
        exports_module._generate_export_task, str(export.id), str(project.id)
    )
    # À la complétion, un webhook export.completed sera émis par le worker si
    # l'intégration s'est abonnée (on émet également ici après génération).
    return _export_out(export)


@router.get(
    "/public/projects/{project_id}/exports",
    response_model=List[ExportOut],
    tags=["public-api"],
)
def public_list_exports(
    project_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("project:read", "export:write")),
    db: Session = Depends(get_db),
):
    project = _load_project_for_key(db, project_id, api_key)
    rows = (
        db.query(Export)
        .filter(Export.project_id == project.id)
        .order_by(Export.created_at.desc())
        .all()
    )
    return [_export_out(e) for e in rows]


@router.get(
    "/public/exports/{export_id}", response_model=ExportOut, tags=["public-api"]
)
def public_get_export(
    export_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("project:read")),
    db: Session = Depends(get_db),
):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    project = db.query(Project).filter(Project.id == export.project_id).first()
    if not project or project.studio_id != api_key.studio_id:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    return _export_out(export)


@router.get("/public/exports/{export_id}/download", tags=["public-api"])
def public_download_export(
    export_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("project:read")),
    db: Session = Depends(get_db),
):
    export = db.query(Export).filter(Export.id == export_id).first()
    if not export:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    project = db.query(Project).filter(Project.id == export.project_id).first()
    if not project or project.studio_id != api_key.studio_id:
        raise HTTPException(status_code=404, detail="Export non trouvé")
    if export.status != "completed" or not export.file_path:
        raise HTTPException(
            status_code=409, detail=f"Export non prêt (statut: {export.status})"
        )
    if not os.path.exists(export.file_path):
        raise HTTPException(status_code=410, detail="Fichier d'export expiré")
    media_type = _mime_for_format(export.format)
    return FileResponse(
        export.file_path,
        media_type=media_type,
        filename=f"rythmoai_{export.id}.{_extension_for_format(export.format)}",
    )


def _export_out(export: Export) -> dict:
    return {
        "id": str(export.id),
        "project_id": str(export.project_id),
        "format": export.format,
        "status": export.status,
        "is_watermarked": bool(export.is_watermarked),
        "created_at": export.created_at,
        "completed_at": export.updated_at if export.status == "completed" else None,
        "download_url": (
            f"/api/v1/public/exports/{export.id}/download"
            if export.status == "completed"
            else None
        ),
    }


def _mime_for_format(fmt: str) -> str:
    return {
        "pdf": "application/pdf",
        "srt": "application/x-subrip",
        "vtt": "text/vtt",
        "stl": "application/octet-stream",
        "cavena": "application/octet-stream",
        "rythmo": "application/octet-stream",
        "json": "application/json",
    }.get(fmt, "application/octet-stream")


def _extension_for_format(fmt: str) -> str:
    return {
        "pdf": "pdf",
        "srt": "srt",
        "vtt": "vtt",
        "stl": "stl",
        "cavena": "cav",
        "rythmo": "rythmo",
        "json": "json",
    }.get(fmt, fmt)


# ─────────────────────────────────────────────────────────────────────────────
# Webhooks
# ─────────────────────────────────────────────────────────────────────────────
@router.get(
    "/public/webhooks",
    response_model=List[WebhookEndpointOut],
    tags=["public-webhooks"],
)
def list_webhooks(
    api_key: ApiKey = Depends(require_scopes("webhook:write", "project:read")),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(WebhookEndpoint)
        .filter(WebhookEndpoint.studio_id == api_key.studio_id)
        .order_by(WebhookEndpoint.created_at.desc())
        .all()
    )
    return [_webhook_out(w) for w in rows]


@router.post(
    "/public/webhooks",
    response_model=WebhookEndpointOut,
    status_code=201,
    tags=["public-webhooks"],
)
def create_webhook(
    data: WebhookEndpointIn,
    api_key: ApiKey = Depends(require_scopes("webhook:write")),
    db: Session = Depends(get_db),
):
    try:
        endpoint = public_api_service.create_webhook_endpoint(
            db,
            studio_id=api_key.studio_id,
            url=str(data.url),
            events=data.events,
            api_key_id=api_key.id,
            description=data.description,
            allow_loopback=WEBHOOK_ALLOW_LOOPBACK,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _webhook_out(endpoint)


@router.delete(
    "/public/webhooks/{endpoint_id}", status_code=204, tags=["public-webhooks"]
)
def delete_webhook(
    endpoint_id: uuid.UUID,
    api_key: ApiKey = Depends(require_scopes("webhook:write")),
    db: Session = Depends(get_db),
):
    endpoint = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.studio_id == api_key.studio_id,
        )
        .first()
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint non trouvé")
    db.delete(endpoint)
    db.commit()
    return None


@router.get(
    "/public/webhooks/{endpoint_id}/deliveries",
    response_model=List[WebhookDeliveryOut],
    tags=["public-webhooks"],
)
def list_deliveries(
    endpoint_id: uuid.UUID,
    limit: int = Query(default=50, ge=1, le=200),
    api_key: ApiKey = Depends(require_scopes("webhook:write", "project:read")),
    db: Session = Depends(get_db),
):
    endpoint = (
        db.query(WebhookEndpoint)
        .filter(
            WebhookEndpoint.id == endpoint_id,
            WebhookEndpoint.studio_id == api_key.studio_id,
        )
        .first()
    )
    if not endpoint:
        raise HTTPException(status_code=404, detail="Endpoint non trouvé")
    rows = (
        db.query(WebhookDelivery)
        .filter(WebhookDelivery.endpoint_id == endpoint.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        WebhookDeliveryOut(
            id=str(d.id),
            event=d.event,
            status=d.status,
            attempts=d.attempts or 0,
            response_status_code=d.response_status_code,
            error=d.error,
            delivered_at=d.delivered_at,
            next_retry_at=d.next_retry_at,
            created_at=d.created_at,
        )
        for d in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Sérialiseurs
# ─────────────────────────────────────────────────────────────────────────────
def _project_out(project: Project) -> PublicProjectOut:
    return PublicProjectOut(
        id=str(project.id),
        title=project.title,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        status=project.status,
        studio_id=str(project.studio_id),
        created_at=project.created_at,
    )


def _webhook_out(endpoint: WebhookEndpoint) -> WebhookEndpointOut:
    return WebhookEndpointOut(
        id=str(endpoint.id),
        url=endpoint.url,
        events=list(endpoint.events or []),
        description=endpoint.description,
        is_active=bool(endpoint.is_active),
        created_at=endpoint.created_at,
    )
