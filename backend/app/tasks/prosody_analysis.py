from celery import Celery

celery_app = Celery('rythmoai', broker='redis://localhost:6379/0')

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def prosody_analysis(self, media_path: str = ''):
    return {'task': 'prosody_analysis', 'status': 'ok'}

@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def analyze_prosody(self, media_path: str = ''):
    return {'task': 'analyze_prosody', 'status': 'ok'}
