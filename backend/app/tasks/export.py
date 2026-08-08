from .audio_extraction import celery_app


@celery_app.task
def export_project(project_id: int):
    return {"file": f"/exports/{project_id}.mp4"}
