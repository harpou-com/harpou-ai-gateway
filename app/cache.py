# app/cache.py
"""
Module de cache en mémoire simple pour stocker la liste des modèles.
"""
from threading import Lock

# Le cache est une simple liste en mémoire.
# L'utilisation d'un verrou garantit la sécurité des threads lors des lectures/écritures.
_model_list_cache = []
_cache_lock = Lock()

def get_models():
    """Récupère la liste des modèles depuis le cache."""
    with _cache_lock:
        # Retourne une copie pour éviter les modifications accidentelles de l'extérieur.
        return list(_model_list_cache)

def set_models(models: list):
    """Met à jour la liste des modèles dans le cache."""
    global _model_list_cache
    with _cache_lock:
        _model_list_cache = models