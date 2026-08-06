from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.core.security import require_role
from app.services.feedback_loop import log_correction

router = APIRouter(prefix="/feedback", tags=["feedback"])

class CorrectionLog(BaseModel):
    replica_id: int
    correction_type: str
    original: str
    corrected: str
    consent: bool = False

@router.post("/corrections")
async def log_manual_correction(
    correction: CorrectionLog,
    current_user=Depends(require_role("adaptateur"))
):
    """G-3.6 — Log correction for continuous improvement (consent required)."""
    result = log_correction(
        correction.replica_id,
        correction.correction_type,
        correction.original,
        correction.corrected,
        studio_id=1,
        consent_given=correction.consent
    )
    return result
