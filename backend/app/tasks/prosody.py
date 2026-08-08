from .audio_extraction import celery_app


@celery_app.task
def analyze_prosody(audio_path: str):
    return {"pitch": 0}
