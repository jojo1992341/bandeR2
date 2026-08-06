"""
G-4.7 — V2 Recette (M15)
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_v2_enterprise_features():
    # SSO
    from app.api.v1.sso import router as sso_router
    assert any("sso" in str(r.path) for r in sso_router.routes)
    
    # Teams
    from app.api.v1.teams import router as teams_router
    assert any("teams" in str(r.path) for r in teams_router.routes)
    
    # CRDT
    from app.services.crdt import CRDTReplica
    crdt = CRDTReplica(1, "Bonjour")
    crdt.apply_insert(7, " tout", "user1")
    assert "Bonjour tout" in crdt.text
    
    # Source separation
    from app.tasks.source_separation import separate_audio_sources
    result = separate_audio_sources.delay(1, "/tmp/test.wav").get()
    assert "dialogue_path" in result
    
    # Public API
    from app.api.v1.public_api import router as public_router
    assert any("webhooks" in str(r.path) for r in public_router.routes)
    
    # Mobile
    from app.api.v1.mobile import router as mobile_router
    assert any("mobile" in str(r.path) for r in mobile_router.routes)
    
    print("✅ Phase 4 (V2) Enterprise features validated")
