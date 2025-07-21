# celery_worker.py
import eventlet

# eventlet.monkey_patch() doit être appelé en premier pour s'assurer que toutes
# les bibliothèques standard sont patchées pour le multitâche coopératif.
# C'est crucial pour éviter les problèmes de concurrence comme l'avertissement 'RLock not greened'.
eventlet.monkey_patch()

import os
from app import create_app, tasks
from app.extensions import celery, socketio

# Crée l'application Flask pour obtenir le contexte et la configuration pour Celery et Socket.IO.
# Nous passons init_socketio=False car nous l'initialiserons manuellement pour le worker.
app = create_app(init_socketio=False)

# Initialise Socket.IO pour le worker.
# Le worker agit uniquement comme un client pour la file de messages (ex: Redis)
# afin de pouvoir émettre des événements. Il n'exécute pas de serveur HTTP, donc les options
# spécifiques au serveur comme `cors_allowed_origins` ne sont pas nécessaires ici.
# L'URL `message_queue` nécessaire devrait être récupérée depuis la configuration de l'app
# qui a été définie lors de `create_app`.
socketio.init_app(app)

# L'objet `celery` de `app.extensions` est maintenant exposé pour la CLI Celery.
# Il a été configuré par `celery.init_app(app)` à l'intérieur de `create_app`.
# Le module `tasks` est importé pour que le mécanisme de découverte de Celery les trouve.
