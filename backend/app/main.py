from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.api.v1 import (
    auth,
    users,
    projects,
    studios,
    transcripts,
    rythmo,
    exports,
    media,
    pipeline_ws,
    speakers,
    replicas,
    comments,
    replica_lock_ws,
    project_lifecycle,
    dashboard,
    audit,
    backups,
    silences,
    speech_rate,
    emotions,
    typographic_profiles,
    lip_sync,
    search,
    feedback,
    words,
    sso,
    crdt,
    public_api,
    preferences,
    organization,
    teams,
    tasks,
)
from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

app = FastAPI(
    title="RythmoAI Backend",
    description="FastAPI backend per CDC RythmoAI v2 §6.2 (Clean Architecture) & §15.4-15.5 Security/Audit",
    version="2.0.0",
)


@app.middleware("http")
async def security_transport_headers(request: Request, call_next):
    # Support TLS 1.3 obligatoire & HSTS activé (§15.4) & OWASP Security Headers (§15.7)
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = (
        "max-age=31536000; includeSubDomains; preload"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; frame-ancestors 'none';"
    )
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    ssl_proto = (
        request.headers.get("x-ssl-protocol")
        or request.headers.get("x-forwarded-ssl-version")
        or ""
    )
    if ssl_proto and "TLSv1.3" not in ssl_proto and "TLSv1.2" in ssl_proto:
        return JSONResponse(
            status_code=426,
            content={"detail": "TLS 1.3 obligatoire en transit (§15.4)"},
        )
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth-api"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(studios.router, prefix="/api/v1/studios", tags=["studios"])
app.include_router(studios.router, prefix="/studios", tags=["studios-alt"])
app.include_router(
    transcripts.router, prefix="/api/v1/transcripts", tags=["transcripts"]
)
app.include_router(rythmo.router, prefix="/api/v1", tags=["rythmo"])
app.include_router(exports.router, prefix="/api/v1", tags=["exports"])
app.include_router(exports.router, tags=["exports-alt"])
app.include_router(media.router, tags=["media"])
app.include_router(media.router, prefix="/api/v1", tags=["media-api"])
app.include_router(pipeline_ws.router, tags=["pipeline"])
app.include_router(speakers.router, tags=["speakers"])
app.include_router(speakers.router, prefix="/api/v1", tags=["speakers-api"])
app.include_router(replicas.router, prefix="/api/v1", tags=["replicas"])
app.include_router(replica_lock_ws.router, prefix="/api/v1", tags=["replica-locks"])
app.include_router(
    project_lifecycle.router, prefix="/api/v1", tags=["project-lifecycle"]
)
app.include_router(dashboard.router, prefix="/api/v1", tags=["dashboard"])
app.include_router(comments.router, prefix="/api/v1", tags=["comments"])
app.include_router(audit.router, tags=["audit"])
app.include_router(backups.router, tags=["backups"])
app.include_router(silences.router, tags=["silences"])
app.include_router(speech_rate.router, tags=["speech-rate"])
app.include_router(emotions.router, tags=["emotions"])
app.include_router(typographic_profiles.router, tags=["typographic-profiles"])
app.include_router(lip_sync.router, tags=["lip-sync"])
app.include_router(search.router, prefix="/api/v1", tags=["search"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(sso.router, prefix="/api/v1", tags=["sso"])
app.include_router(sso.router, tags=["sso-alt"])
app.include_router(crdt.router, prefix="/api/v1", tags=["crdt"])
app.include_router(crdt.router, tags=["crdt-alt"])
app.include_router(words.router, prefix="/api/v1", tags=["words"])
app.include_router(words.router, tags=["words-alt"])
# §25.4 — API publique (intégrations ERP/plateformes de droits) + webhooks
app.include_router(public_api.router, prefix="/api/v1", tags=["public-api"])
app.include_router(public_api.router, tags=["public-api-alt"])

# §16.1–§16.3 — Préférences, organisation de projets, équipes, tâches & activité
app.include_router(preferences.router, prefix="/api/v1/users", tags=["preferences"])
app.include_router(organization.router, prefix="/api/v1", tags=["organization"])
app.include_router(teams.router, prefix="/api/v1", tags=["teams"])
app.include_router(tasks.router, prefix="/api/v1", tags=["tasks-activity"])
