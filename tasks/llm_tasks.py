from celery import shared_task
from flask import current_app
import time

# --- ATTENTION : Hypothèses sur votre code ---
# J'ai supposé que vous pouviez accéder à votre client Redis et à votre
# gestionnaire de modèles LLM de cette manière.
# Adaptez les chemins d'importation à la structure de votre projet.
from ..app_redis import app_redis
from ..llm.manager import llm_manager
from .update_llm_models_cache import update_llm_models_cache  # Ajout de l'import manquant
# ---------------------------------------------

# Clé Redis pour stocker le timestamp de la dernière mise à jour réussie.
LAST_MODEL_REFRESH_KEY = "llm:last_refresh_timestamp"


@shared_task(name="tasks.orchestrate_model_refresh")
def orchestrate_model_refresh():
    """
    Tâche d'orchestration qui s'exécute toutes les 30 secondes.
    Force le rafraîchissement du cache des modèles tant que le nombre de modèles est à 0,
    indépendamment de la configuration ou des variables d'environnement.
    """
    # J'ai supposé que votre manager a une méthode pour obtenir le nombre de modèles.
    # Adaptez `get_model_count()` si le nom de la méthode est différent.
    if llm_manager.get_model_count() == 0:
        current_app.logger.warning(
            "Aucun modèle LLM n'est chargé. "
            "Déclenchement forcé du rafraîchissement du cache."
        )
        update_llm_models_cache.delay()
        # Enregistrement du timestamp : permet de tracer les tentatives de rafraîchissement forcé
        app_redis.set(LAST_MODEL_REFRESH_KEY, int(time.time()))
        return

    current_app.logger.info("Des modèles LLM sont chargés. Aucune action d'orchestration nécessaire.")
    # TODO: Ajouter ici la logique de rafraîchissement périodique selon la config/variable d'environnement si besoin.
    return