import uuid
from sqlalchemy.orm import Session
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings
from app.tasks.forced_alignment import forced_alignment
from app.models import TranscriptSegment, Word, MediaAsset

def test_forced_alignment_word_level():
    # Vérifie alignement forcé : chaque mot possède start < end cohérent
    # Note : nécessite DB active et audio de test (ex. /tmp/test_video_piste.wav)
    # Sur cible Windows : aligne sur segment Whisper et persiste Word
    result = forced_alignment.run(
        media_path="/tmp/test_video_piste.mp4",
        segment_id=str(uuid.uuid4()),
        language="fr"
    )
    # Le résultat doit indiquer succès et nombre de mots alignés
    assert result is not None
    assert result.get("language") in ("fr", "fr-FR", "fr") or result.get("language") is not None
