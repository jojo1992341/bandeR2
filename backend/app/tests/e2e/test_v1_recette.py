"""
G-2.11 — V1 Recette (M7)
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_v1_features():
    """Quick smoke test for Phase 2 features."""
    
    # VAD
    from app.tasks.vad import detect_breathing_and_pauses
    result = detect_breathing_and_pauses.delay(1, "/tmp/test.wav").get()
    assert "events" in result
    
    # Speech rate
    from app.services.speech_rate import calculate_speech_rate
    rate = calculate_speech_rate({"text": "Bonjour tout le monde", "start_ms": 0, "end_ms": 3000})
    assert rate["syll_per_sec"] > 0
    
    # Emotion
    from app.services.emotion import detect_emotion_and_intention
    emo = detect_emotion_and_intention({"text": "C'est génial !"})
    assert emo["emotion"] in ["joie", "neutre"]
    
    print("✅ Phase 2 (V1) features smoke test passed")
