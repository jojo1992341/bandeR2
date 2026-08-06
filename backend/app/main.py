from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import router as api_v1_router
from app.core.middleware import SecurityHeadersMiddleware, TimingMiddleware

app = FastAPI(
    title="RythmoAI API",
    description="API pour la génération et édition de bandes rythmo",
    version="0.2.0-mvp"
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TimingMiddleware)

app.include_router(api_v1_router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "rythmoai-api", "version": "0.2.0-mvp"}

@app.get("/")
async def root():
    return {"message": "RythmoAI API - MVP Ready", "docs": "/docs"}
