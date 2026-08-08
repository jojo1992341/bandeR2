import uuid
from typing import List
from sqlalchemy.orm import Session
from app.models import SilenceEvent
from app.ai.silero_vad import SileroVADSilenceDetector
from app.core.logging import logger


class SilenceService:
    def __init__(self, db: Session):
        self.db = db
        self.detector = SileroVADSilenceDetector()

    def detect_and_persist_silences(
        self, media_id: uuid.UUID, audio_path: str
    ) -> List[SilenceEvent]:
        events_data = self.detector.detect_and_classify(audio_path)
        self.db.query(SilenceEvent).filter(
            SilenceEvent.media_id == media_id
        ).delete(synchronize_session=False)

        persisted = []
        for ed in events_data:
            se = SilenceEvent(
                id=uuid.uuid4(),
                media_id=media_id,
                event_type=ed["event_type"],
                start_ms=ed["start_ms"],
                end_ms=ed["end_ms"],
                duration_ms=ed["duration_ms"],
                confidence_score=ed.get("confidence_score", 0.90),
                details=ed.get("details", {}),
            )
            self.db.add(se)
            persisted.append(se)

        self.db.commit()
        for se in persisted:
            self.db.refresh(se)
        return persisted

    def list_by_media(self, media_id: uuid.UUID) -> List[SilenceEvent]:
        return (
            self.db.query(SilenceEvent)
            .filter(SilenceEvent.media_id == media_id)
            .order_by(SilenceEvent.start_ms)
            .all()
        )
