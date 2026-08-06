"""
G-3.7 — V1.5 Recette (M10)
"""
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_v1_5_features():
    # Feature flag
    from app.api.v1.feature_flags import flags
    assert "lip_sync_enabled" in flags
    
    # Dashboard
    from app.services.dashboard import get_studio_dashboard
    dash = get_studio_dashboard(1)
    assert dash["total_projects"] > 0
    
    # Search
    from app.services.search import full_text_search
    results = full_text_search(1, "bonjour")
    assert isinstance(results, list)
    
    # Feedback
    from app.services.feedback_loop import log_correction
    result = log_correction(1, "word", "bonour", "bonjour", 1, consent_given=True)
    assert result["logged"] is True
    
    print("✅ Phase 3 (V1.5) features validated")
