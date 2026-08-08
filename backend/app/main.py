from fastapi import FastAPI
from app.api.v1 import auth, users, projects, studios, transcripts, rythmo, exports
from app.core.config import get_settings
from app.core.logging import logger

settings = get_settings()

app = FastAPI(
    title="RythmoAI Backend",
    description="FastAPI backend per CDC RythmoAI v2 §6.2 (Clean Architecture)",
    version="2.0.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(projects.router, prefix="/api/v1/projects", tags=["projects"])
app.include_router(studios.router, prefix="/api/v1/studios", tags=["studios"])
app.include_router(
    transcripts.router, prefix="/api/v1/transcripts", tags=["transcripts"]
)
app.include_router(rythmo.router, prefix="/api/v1/rythmo", tags=["rythmo"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["exports"])
from app.api.v1 import media, pipeline_ws, speakers, replicas
app.include_router(media.router, tags=["media"])
app.include_router(pipeline_ws.router, tags=["pipeline"])
app.include_router(speakers.router, tags=["speakers"])
app.include_router(replicas.router, prefix="/api/v1", tags=["replicas"])
