# celery_worker.py
from app import create_app
import os

# Crée l'application Flask pour que Celery puisse utiliser sa configuration.
app = create_app(init_socketio=False)

# Initialiser socketio pour la communication Redis/pubsub (pas de serveur HTTP)
from app.extensions import socketio
socketio.init_app(
    app,
    message_queue=os.environ.get('REDIS_URL'),
    cors_allowed_origins="*"
)

# Cette ligne est cruciale : elle force l'importation de app/tasks.py
# pour que Celery découvre et enregistre les tâches définies avec @celery.task
from app import tasks

# Expose l'objet celery pour la CLI Celery
from app.extensions import celery
