from celery import Celery; celery_app = Celery('rythmoai', broker='redis://localhost:6379/0'); @celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def generate_rythmo(self, media_path: str = ''): return {'task':'generate_rythmo','status':'ok'}
