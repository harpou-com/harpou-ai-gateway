# celery_worker.py
"""
Point d'entrée dédié pour les workers et le service beat de Celery.

Ce script assure que le monkey-patching d'eventlet est appliqué avant
toute autre importation, puis il crée une instance de l'application Flask
pour configurer Celery et SocketIO avec le bon contexte.
"""

import eventlet

# IMPORTANT : eventlet.monkey_patch() doit être la toute première instruction exécutée
# pour garantir la compatibilité avec les bibliothèques asynchrones.
eventlet.monkey_patch()

# Importer les éléments nécessaires de l'application APRÈS le patching.
from app import create_app
from app.extensions import celery, socketio
# Importer le module de tâches est nécessaire pour que Celery les découvre.
from app import tasks  # noqa: F401

# 1. Créer une instance de l'application Flask.
#    L'appel à create_app() va charger la configuration et initialiser Celery.
#    On passe init_socketio=False car le worker n'est pas un serveur web.
app = create_app(init_socketio=False)

# 2. Initialiser SocketIO pour le worker.
#    Ceci configure le client SocketIO pour qu'il puisse émettre des événements
#    via la file de messages (Redis), en utilisant la configuration de l'app.
socketio.init_app(app)

# L'instance 'celery' est maintenant configurée et prête à être utilisée
# par la ligne de commande de Celery.
# ex: celery -A celery_worker.celery worker
