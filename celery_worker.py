# celery_worker.py
import eventlet # DOIT ÊTRE LA PREMIÈRE IMPORTATION SI UTILISATION DU MONKEY PATCHING
eventlet.monkey_patch()

from app.extensions import celery # Importer l'instance Celery partagée
from celery.signals import beat_init
import os
import logging

logger = logging.getLogger(__name__)

# Fonction pour initialiser l'application Celery avec le contexte de l'application Flask.
# Cette fonction doit être appelée par l'application web Flask (run.py)
# et par le lanceur de worker Celery (worker_launcher.py),
# PAS globalement par celery_worker.py lui-même.
def init_celery_with_flask_app(app):
    """
    Initialise l'application Celery avec le contexte de l'application Flask.
    Ceci doit être appelé par l'application web Flask (run.py)
    et par le lanceur de worker Celery (worker_launcher.py).
    """
    # Mettre à jour la configuration de l'instance Celery partagée à partir de la config Flask
    celery.conf.update(app.config) # Met à jour la configuration Celery à partir de la config Flask
    # Empêcher Celery de détourner la configuration du logger racine pour éviter les logs dupliqués.
    celery.conf.worker_hijack_root_logger = False

    # --- Validation de la configuration ---
    # S'assurer qu'un broker est bien configuré pour éviter que Celery ne se rabatte
    # sur son broker par défaut (AMQP) en silence.
    if not celery.conf.broker_url:
        raise ValueError("Le broker Celery n'est pas configuré. Veuillez définir REDIS_URL ou CELERY_BROKER_URL.")

    # --- Configuration de Celery Beat pour les tâches périodiques ---
    update_interval_minutes = int(app.config.get('llm_cache_update_interval_minutes', 5))
    app.logger.info(f"Configuration de la tâche de rafraîchissement du cache des modèles toutes les {update_interval_minutes} minutes.")
    
    celery.conf.beat_schedule = {
        'refresh-models-every-x-minutes': {
            'task': 'app.tasks.refresh_models_cache_task',
            'schedule': update_interval_minutes * 60.0,  # en secondes
        },
    }

    @beat_init.connect(weak=False)
    def on_beat_init(sender, **kwargs):
        # Utiliser le logger du module pour une meilleure cohérence avec le reste de l'application.
        logger.info("Celery Beat a démarré. Lancement de la tâche de rafraîchissement initial du cache.")
        sender.app.send_task('app.tasks.refresh_models_cache_task')

    TaskBase = celery.Task
    class ContextTask(TaskBase):
        abstract = True
        def __call__(self, *args, **kwargs):
            with app.app_context():
                return TaskBase.__call__(self, *args, **kwargs)
    celery.Task = ContextTask
    return celery

# IMPORTANT: Ne pas appeler create_app() ou init_celery_with_flask_app() globalement ici.
# Celery Beat et les Workers Celery doivent pouvoir importer 'celery' sans
# initialiser l'application web Flask complète.
# Le contexte de l'application Flask est géré par la `ContextTask` pour l'exécution des tâches individuelles.
