import eventlet
eventlet.monkey_patch()
import logging

from celery.signals import after_setup_logger
from app import create_app, configure_logging
from celery_worker import init_celery_with_flask_app

# 1. Créer une instance de l'application Flask pour fournir le contexte.
app = create_app()

# --- Configuration de la journalisation pour le worker Celery ---
# On s'assure que le worker Celery utilise la même configuration de logging que l'app Flask.
@after_setup_logger.connect
def setup_celery_worker_logging(logger, **kwargs):
    """Ce signal est émis après que le logger du worker a été configuré."""
    # On appelle notre fonction de configuration personnalisée pour surcharger les logs par défaut de Celery.
    # Cela garantit que les logs du worker (y compris les logs des tâches) suivent les règles
    # définies dans app/__init__.py (niveau, format, rotation de fichiers, etc.).
    configure_logging(app)

    # --- Réduction de la verbosité de Celery ---
    # On force les loggers internes de Celery à un niveau supérieur (INFO)
    # pour éviter le flot de messages DEBUG (ex: "Timer wake-up!").
    logging.getLogger('celery').setLevel(logging.INFO)

    logger.info("Configuration de la journalisation de Flask appliquée au worker Celery.")

# 2. Initialiser Celery avec la configuration et le contexte de l'application Flask.
#    L'objet 'celery' (défini dans celery_worker.py) est maintenant configuré.
init_celery_with_flask_app(app)
# --- Fin de la logique d'initialisation ---

from celery.__main__ import main

if __name__ == '__main__':
    # 3. Exécute la ligne de commande de Celery.
    #    Les arguments (ex: -A celery_worker.celery worker) sont passés par la commande
    #    qui exécute ce script. Celery trouvera l'instance 'celery' déjà configurée.
    main()