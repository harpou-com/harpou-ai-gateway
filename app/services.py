# app/services.py
"""
Ce module contient la logique métier principale de l'application,
séparée des routes et des tâches de fond.
"""
import time
import socket
import os
from urllib.parse import urljoin
from pydantic import BaseModel, Field
from flask import current_app
from openai import APIError
from .llm_connector import list_models_from_backend
from .cache import set_models

class GatewayBackendModel(BaseModel):
    """Représente un backend exposé comme un modèle unique, compatible API OpenAI."""
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "gateway"

def refresh_and_cache_models():
    """
    Récupère les modèles de tous les backends, met à jour le cache en mémoire,
    et retourne la liste des modèles.
    """
    current_app.logger.info("Début du rafraîchissement de la liste des modèles...")
    llm_backends = current_app.config.get('llm_backends', [])
    exposed_models = {} # Utiliser un dictionnaire pour un accès rapide par ID

    for backend in llm_backends:
        current_app.logger.debug(f"Backend brut: {backend}")
        backend_name = backend.get('name')
        if not backend_name:
            current_app.logger.warning("Un backend sans nom a été trouvé dans la configuration, il sera ignoré.")
            continue

        if backend.get('llm_auto_load'):
            current_app.logger.info(f"Découverte des modèles pour le backend '{backend_name}'.")
            try:
                backend_models = list_models_from_backend(backend)
                for model in backend_models:
                    model_dict = model.model_dump()
                    composite_id = f"{backend_name}/{model.id}"
                    model_dict['id'] = composite_id # S'assurer que l'ID composite est dans l'objet
                    exposed_models[composite_id] = model_dict
            except APIError as e:
                current_app.logger.error(f"Impossible de récupérer les modèles pour le backend '{backend_name}': {e}")
                # On continue avec les autres backends au lieu de planter.
            except Exception as e:
                current_app.logger.error(f"Une erreur inattendue est survenue lors de la récupération des modèles pour le backend '{backend_name}': {e}")
        else:
            default_model_name = backend.get('default_model')
            if not default_model_name:
                current_app.logger.warning(
                    f"Backend '{backend_name}' a 'llm_auto_load: false' mais pas de 'default_model' configuré. Il sera ignoré."
                )
                continue
            
            current_app.logger.info(f"Exposition manuelle du backend '{backend_name}' via son modèle par défaut '{default_model_name}'.")
            # On crée un ID de modèle qui inclut le nom du backend pour le routage.
            manual_model_id = f"{backend_name}/{default_model_name}"
            manual_model = GatewayBackendModel(id=manual_model_id).model_dump()
            exposed_models[manual_model_id] = manual_model
    
    set_models(exposed_models)
    current_app.logger.info(f"Cache des modèles mis à jour avec {len(exposed_models)} modèles.")
    current_app.logger.info(f"Service exécutant la requête : {os.environ.get('HOSTNAME')}")
    return exposed_models
