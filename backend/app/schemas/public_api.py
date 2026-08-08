"""Schémas Pydantic de l'API publique §25.4."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class PublicProjectCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    source_lang: str = Field(default="fr", max_length=10)
    target_lang: str = Field(default="fr", max_length=10)


class PublicProjectOut(BaseModel):
    id: str
    title: str
    source_lang: Optional[str] = None
    target_lang: Optional[str] = None
    status: str
    studio_id: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PublicMediaIn(BaseModel):
    storage_path: str = Field(..., min_length=1, max_length=2000)
    duration_seconds: Optional[float] = None
    codec: Optional[str] = None
    fps: Optional[int] = None
    resolution: Optional[str] = None


class PublicMediaOut(BaseModel):
    id: str
    project_id: str
    storage_path: str
    status: Optional[str] = None
    duration_seconds: Optional[float] = None


class ProcessIn(BaseModel):
    """Corps de déclenchement d'un traitement via l'API publique."""

    media_id: Optional[str] = None
    webhook_url: Optional[HttpUrl] = Field(
        default=None,
        description="URL à notifier à la complétion (en plus des endpoints enregistrés).",
    )
    webhook_events: List[str] = Field(
        default_factory=lambda: ["pipeline.completed", "pipeline.failed"]
    )
    auto_export: bool = Field(
        default=False,
        description="Génère automatiquement un export à la complétion.",
    )
    export_format: str = Field(default="srt")
    source_separation: bool = Field(
        default=False,
        description="Active la séparation dialogue/musique/effets §12.1.",
    )
    options: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("export_format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        allowed = {
            "pdf",
            "srt",
            "vtt",
            "stl",
            "cavena",
            "rythmo",
            "json",
            "quality_report",
        }
        if v.lower() not in allowed:
            raise ValueError(f"Format non supporté: {v}")
        return v.lower()


class ProcessOut(BaseModel):
    job_id: str
    project_id: str
    media_id: str
    status: str
    progress_percent: int
    current_step: str


class JobOut(BaseModel):
    id: str
    project_id: str
    status: str
    progress_percent: int
    current_step: str
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ApiKeyCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: List[str] = Field(
        default_factory=lambda: ["project:read", "project:write", "export:write"]
    )


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    scopes: List[str]
    is_active: bool
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ApiKeyCreatedOut(ApiKeyOut):
    """Contient la clé en clair, renvoyée une seule fois à la création."""

    api_key: str


class WebhookEndpointIn(BaseModel):
    url: HttpUrl
    events: List[str]
    description: Optional[str] = None

    @field_validator("events")
    @classmethod
    def _validate_events(cls, v: List[str]) -> List[str]:
        allowed = {"pipeline.completed", "pipeline.failed", "export.completed", "*"}
        bad = [e for e in v if e not in allowed]
        if bad:
            raise ValueError(f"Événements non supportés: {', '.join(bad)}")
        if not v:
            raise ValueError("Au moins un événement est requis")
        return v


class WebhookEndpointOut(BaseModel):
    id: str
    url: str
    events: List[str]
    description: Optional[str] = None
    is_active: bool
    created_at: Optional[datetime] = None


class WebhookDeliveryOut(BaseModel):
    id: str
    event: str
    status: str
    attempts: int
    response_status_code: Optional[int] = None
    error: Optional[str] = None
    delivered_at: Optional[datetime] = None
    next_retry_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ExportIn(BaseModel):
    format: str = Field(default="srt")

    @field_validator("format")
    @classmethod
    def _validate_format(cls, v: str) -> str:
        allowed = {
            "pdf",
            "srt",
            "vtt",
            "stl",
            "cavena",
            "rythmo",
            "json",
            "quality_report",
        }
        if v.lower() not in allowed:
            raise ValueError(f"Format non supporté: {v}")
        return v.lower()


class ExportOut(BaseModel):
    id: str
    project_id: str
    format: str
    status: str
    is_watermarked: bool = False
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    download_url: Optional[str] = None


class ErrorOut(BaseModel):
    detail: str
    code: Optional[str] = None
