from unittest.mock import MagicMock
from app.services.rythmo_score_service import compute_aggregate_score

def test_compute_aggregate_score_synthetic():
    # Jeu synthétique : transcription haut, alignement parfait, diarisation cohérente (1 locuteur)
    db = MagicMock()
    segment_mock = MagicMock()
    segment_mock.confidence_score = 0.92
    db.query.return_value.filter.return_value.first.return_value = segment_mock
    word_mock = MagicMock()
    word_mock.confidence_score = 0.95
    word_mock.speaker_id = "spk-01"
    db.query.return_value.filter.return_value.all.return_value = [word_mock, word_mock]

    score = compute_aggregate_score("rep-01", db)
    # Pondération : 0.92*0.5 + 1.0*0.3 + 0.9*0.2 = 0.46 + 0.30 + 0.18 = 0.94
    assert 0.90 <= score <= 1.0, f"Score agrégé attendu ~0.94, obtenu {score}"
    assert score == round(score, 3), "Score doit être arrondi à 3 décimales"
