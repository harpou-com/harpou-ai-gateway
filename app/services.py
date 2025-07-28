# app/services.py
"""
Ce module contient la logique métier principale de l'application,
séparée des routes et des tâches de fond.
"""
import time
from flask import current_app
from .llm_connector import list_models_from_backend
from .cache import set_models

def refresh_and_cache_models():
    """
    Récupère les modèles de tous les backends, met à jour le cache en mémoire,
    et retourne la liste des modèles.
    """
    current_app.logger.info("Début du rafraîchissement de la liste des modèles...")
    llm_backends = current_app.config.get('llm_backends', [])
    exposed_models = []

    for backend in llm_backends:
        backend_name = backend.get('name')
        if not backend_name:
            current_app.logger.warning("Un backend sans nom a été trouvé dans la configuration, il sera ignoré.")
            continue

        if backend.get('llm_auto_load'):
            current_app.logger.info(f"Découverte des modèles pour le backend '{backend_name}'.")
            backend_models = list_models_from_backend(backend)
            for model in backend_models:
                model_dict = model.model_dump()
                model_dict['id'] = f"{backend_name}/{model.id}"
                exposed_models.append(model_dict)
        else:
            current_app.logger.info(f"Exposition manuelle du backend '{backend_name}' comme un modèle unique.")
            exposed_models.append({
                "id": backend_name, "object": "model",
                "created": int(time.time()), "owned_by": "gateway"
            })
    
    set_models(exposed_models)
    current_app.logger.info(f"Cache des modèles mis à jour avec {len(exposed_models)} modèles.")
    return exposed_models