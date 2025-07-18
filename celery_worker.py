# celery_worker.py
from app import create_app

app = create_app()
celery = app.celery_app

# Import tasks to register them with Celery
from app import tasks