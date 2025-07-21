
import os
from flask import Flask
from dotenv import load_dotenv
from .extensions import celery, socketio
from flask_cors import CORS

# Charger les variables d'environnement dès le début
load_dotenv()

def create_app(config_object=None, init_socketio=True):
    """
    Application Factory : initialise Flask, Celery, SocketIO, Blueprints et événements.
    - init_socketio : True pour serveur web, False pour worker Celery
    """

    app = Flask(__name__)
    # Active CORS pour toutes les routes HTTP (fetch cross-origin)
    CORS(app, origins="*")

    # Configuration depuis les variables d'environnement
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY'),
        # Configuration Celery avec les clés en minuscules (recommandé pour Celery 5+)
        broker_url=os.environ.get('CELERY_BROKER_URL'),
        result_backend=os.environ.get('CELERY_RESULT_BACKEND'),
    )

    # Initialiser Celery
    init_celery(app)

    # Initialiser SocketIO (uniquement pour le serveur web)
    if init_socketio:
        socketio.init_app(
            app, 
            cors_allowed_origins="*" # Autorise toutes les origines
        )

    # Enregistrer les Blueprints
    from . import routes
    app.register_blueprint(routes.bp)

    # Enregistrer les gestionnaires d'événements SocketIO
    if init_socketio:
        from . import events  # noqa: F401 (force l'import pour enregistrer les handlers)

    return app

def init_celery(app: Flask):
    """Initialise et configure l'instance Celery avec le contexte Flask."""
    celery.conf.update(app.config)

    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
