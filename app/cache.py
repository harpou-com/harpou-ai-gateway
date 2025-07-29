# app/cache.py

from .extensions import flask_cache

# Clé de cache pour la liste des modèles
MODELS_CACHE_KEY = "llm_models_list"

def get_models_from_cache():
    """
    Récupère le dictionnaire des modèles depuis le cache.
    Retourne un dictionnaire ou un dictionnaire vide s'il n'y a rien.
    """
    return flask_cache.get(MODELS_CACHE_KEY) or {}

def set_models(models):
    """
    Enregistre le dictionnaire des modèles dans le cache.
    `models` est un dictionnaire où la clé est l'ID du modèle et la valeur est l'objet modèle.
    """
    flask_cache.set(MODELS_CACHE_KEY, models)

def get_model_details(model_id):
    """Récupère les détails d'un modèle spécifique depuis le cache."""
    models = get_models_from_cache()
    # La recherche est maintenant une simple consultation de dictionnaire, O(1)
    return models.get(model_id)
