import os
from flask import Flask
from flask_socketio import SocketIO
from celery import Celery, Task

# --- Configuration via Variables d'Environnement ---
# Les variables d'environnement sont lues au démarrage.
# On fournit des valeurs par défaut pour faciliter le développement local.

# URL de Redis utilisée par Celery et SocketIO.
# Dans un environnement conteneurisé (Docker), vous utiliseriez le nom du service,
# par exemple 'redis://redis:6379/0'.
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Clé secrète pour Flask, essentielle pour la sécurité des sessions.
FLASK_SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'une-cle-secrete-pour-le-developpement')


# --- Initialisation des Extensions ---

# 1. Flask-SocketIO
# L'argument `message_queue` est crucial si vous utilisez plusieurs workers (ex: Gunicorn).
# Il permet aux différents processus de communiquer entre eux via Redis.
socketio = SocketIO(message_queue=REDIS_URL)

# 2. Celery
# On configure Celery pour utiliser Redis comme "broker" (file d'attente des tâches)
# et comme "backend" (stockage des résultats des tâches).
celery = Celery(__name__, broker=REDIS_URL, backend=REDIS_URL)


# --- Factory de l'application ---

def create_app(debug=False):
    """
    Crée et configure une instance de l'application Flask.
    Ce patron de conception (Application Factory) est une bonne pratique.
    """
    app = Flask(__name__)
    app.debug = debug
    app.config['SECRET_KEY'] = FLASK_SECRET_KEY

    # 3. Liaison de Celery avec le contexte de l'application Flask
    # Cette étape garantit que les tâches Celery s'exécutent avec le contexte
    # de l'application Flask actif. Ainsi, les tâches peuvent accéder à `current_app`,
    # aux configurations, aux extensions, etc.
    class ContextTask(Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask

    # 4. Initialisation de SocketIO avec l'application
    socketio.init_app(app)

    # 5. Importer et enregistrer les Blueprints, événements et tâches
    # On importe ici pour éviter les dépendances circulaires.
    from . import routes, events, tasks
    app.register_blueprint(routes.bp)
    
    # Attacher l'instance Celery configurée à l'application
    app.celery_app = celery

    return app
