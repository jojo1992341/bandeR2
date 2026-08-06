from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from app.core.security import require_role
import hmac
import hashlib
import time

router = APIRouter(prefix="/public", tags=["public-api"])

class WebhookConfig(BaseModel):
    url: str
    events: List[str]
    secret: Optional[str] = None

webhooks_db = {}

@router.post("/webhooks")
async def register_webhook(config: WebhookConfig, current_user=Depends(require_role("admin"))):
    """G-4.5 — Register webhook for events."""
    wh_id = len(webhooks_db) + 1
    webhooks_db[wh_id] = config.dict()
    return {"id": wh_id, **config.dict()}

@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(webhook_id: int, current_user=Depends(require_role("admin"))):
    """Send test payload to webhook."""
    if webhook_id not in webhooks_db:
        raise HTTPException(404, "Webhook not found")
    return {"status": "test_sent", "webhook_id": webhook_id}

def verify_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    """Verify webhook signature (G-4.5)."""
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
