
import os
from flask import Flask
from dotenv import load_dotenv

# Importer les extensions
from .extensions import celery, socketio

# Charger les variables d'environnement depuis le fichier .env
# C'est une bonne pratique de le faire au début.
load_dotenv()


def create_app(config_object=None, init_socketio=True):
    """
    Application factory, voir : http://flask.pocoo.org/docs/patterns/appfactories/
    Le paramètre init_socketio permet de désactiver l'initialisation de SocketIO (utile pour Celery).
    """
    app = Flask(__name__)

    # Configuration depuis les variables d'environnement
    app.config.from_mapping(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY'),
        CELERY_BROKER_URL=os.environ.get('CELERY_BROKER_URL'),
        CELERY_RESULT_BACKEND=os.environ.get('CELERY_RESULT_BACKEND'),
    )

    # Initialiser Celery
    init_celery(app)

    # Initialiser SocketIO avec l'app Flask (sauf pour les workers Celery)
    if init_socketio:
        socketio.init_app(app, async_mode="eventlet")

    # Enregistrer les routes (Blueprints)
    # L'importation est faite ici pour éviter les dépendances circulaires
    with app.app_context():
        from . import routes
        # Si vous utilisez des Blueprints, enregistrez-les ici.
        # Exemple: app.register_blueprint(routes.bp)

    return app

def init_celery(app: Flask):
    """Initialise et configure l'instance Celery."""
    celery.conf.update(
        broker_url=app.config["CELERY_BROKER_URL"],
        result_backend=app.config["CELERY_RESULT_BACKEND"],
    )

    # Crée une sous-classe de Task qui intègre le contexte de l'application Flask.
    # Cela garantit que les tâches Celery s'exécutent avec le contexte de l'application
    # (accès à app.config, etc.)
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return self.run(*args, **kwargs)

    celery.Task = ContextTask
