"""Point d'entrée dédié pour les workers et le service beat de Celery."""

import eventlet

# IMPORTANT : eventlet.monkey_patch() doit être la toute première instruction exécutée
# pour garantir la compatibilité avec les bibliothèques asynchrones.
eventlet.monkey_patch()

# Importer les éléments nécessaires de l'application APRÈS le patching.
from app import create_app, tasks # noqa: F401

# 1. Créer une instance de l'application Flask.
#    L'appel à create_app() va charger la configuration et initialiser Celery.
app = create_app(init_socketio=False)

# 2. Exposer l'instance Celery configurée pour que la CLI puisse la trouver.
#    L'instance a été configurée lors de l'appel à create_app().
from app.extensions import celery, socketio

# 3. Initialiser SocketIO pour le worker dans le contexte de l'application.
#    Ceci permet aux tâches d'émettre des événements via le message queue.
with app.app_context():
    socketio.init_app(app)

# La CLI Celery peut maintenant être lancée avec :
# pdm run worker -> celery -A celery_worker.celery worker ...
# pdm run beat   -> celery -A celery_worker.celery beat ...
