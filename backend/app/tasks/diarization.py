from .audio_extraction import celery_app


@celery_app.task
def diarize_task(audio_path: str):
    return {"speakers": []}
