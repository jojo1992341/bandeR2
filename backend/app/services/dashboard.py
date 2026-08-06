from typing import Dict, Any
from datetime import datetime, timedelta

def get_studio_dashboard(studio_id: int, period_days: int = 30) -> Dict[str, Any]:
    """
    G-3.4 — Advanced studio dashboard metrics.
    """
    # Placeholder data (would come from Celery job results + DB in real impl)
    return {
        "studio_id": studio_id,
        "period_days": period_days,
        "total_projects": 47,
        "minutes_processed": 1240,
        "avg_processing_time_min": 7.8,
        "ia_minutes_consumed": 892,
        "quota_remaining_minutes": 2108,
        "active_users": 12,
        "exports_count": 31,
        "most_used_profile": "France TF1 2026",
        "generated_at": datetime.now().isoformat()
    }
