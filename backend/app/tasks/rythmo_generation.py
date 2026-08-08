from .audio_extraction import celery_app


@celery_app.task
def generate_rythmo(transcript_id: int):
    return {"status": "done"}
