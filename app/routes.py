import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from celery.result import AsyncResult
import time
import json
import uuid

from .auth import require_api_key
from .cache import get_models_from_cache
from . import llm_connector
from .tasks import orchestrator_task

# Configuration du logger
logger = logging.getLogger(__name__)

# Création du Blueprint
bp = Blueprint('api', __name__)

def generate_openai_stream_chunk(id, model, content):
    """Génère un chunk de réponse au format streaming OpenAI."""
    chunk = {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant", "content": content},
                "finish_reason": None
            }
        ]
    }
    return f"data: {json.dumps(chunk)}\n\n"

def generate_final_openai_stream_chunk(id, model):
    """Génère le chunk final de la réponse streamée."""
    chunk = {
        "id": id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop"
            }
        ]
    }
    return f"data: {json.dumps(chunk)}\n\n"


@bp.route('/v1/models', methods=['GET'])
@require_api_key
def get_models():
    """Retourne la liste des modèles disponibles depuis le cache."""
    logger.info("Service de la liste des modèles depuis le cache.")
    models_dict = get_models_from_cache()
    # Le cache retourne un dictionnaire de modèles. On extrait les valeurs pour la liste.
    model_list = list(models_dict.values())
    # Formatage de la réponse pour être compatible avec l'API OpenAI
    formatted_models = {
        "object": "list",
        "data": model_list
    }
    return jsonify(formatted_models)


@bp.route('/v1/chat/completions', methods=['POST'])
@require_api_key
def chat_completions():
    """Point d'entrée principal pour les requêtes de chat."""
    data = request.json
    model_id = data.get("model")
    conversation = data.get("messages")
    stream = data.get("stream", False)

    # Validation des paramètres essentiels
    if not model_id:
        return jsonify({"error": {"message": "Le paramètre 'model' est manquant.", "type": "invalid_request_error"}}), 400
    if not conversation:
        return jsonify({"error": {"message": "Le paramètre 'messages' est manquant.", "type": "invalid_request_error"}}), 400

    request_id = f"chatcmpl-{uuid.uuid4()}"

    if stream:
        # Si le client demande un stream, on lance la tâche en arrière-plan
        # et on retourne immédiatement un stream qui sera rempli plus tard.
        # Pour l'instant, nous allons exécuter la tâche de manière synchrone
        # puis streamer la réponse finale mot par mot.
        
        sid = str(uuid.uuid4())
        logger.info(f"Requête de stream reçue. Lancement synchrone de l'orchestrateur pour SID {sid}.")
        
        # Exécution synchrone de la tâche. L'erreur 'NameError' est corrigée car 'conversation' est maintenant défini.
        task_result = orchestrator_task(sid=sid, conversation=conversation, model_id=model_id)
        
        def generate():
            # Simuler un stream mot par mot depuis la réponse finale
            words = task_result.split()
            for word in words:
                yield generate_openai_stream_chunk(request_id, model_id, f" {word}")
                time.sleep(0.05) # Simule le délai de génération
            yield generate_final_openai_stream_chunk(request_id, model_id)
        
        logger.info("Début du streaming de la réponse finale simulée.")
        return Response(stream_with_context(generate()), content_type='text/event-stream')

    else:
        # Si la requête n'est pas streamée, on attend le résultat complet.
        sid = str(uuid.uuid4())
        logger.info(f"Requête synchrone reçue. Lancement de l'orchestrateur pour SID {sid}.")
        
        task = orchestrator_task.delay(sid=sid, conversation=conversation, model_id=model_id)
        
        try:
            # Attendre le résultat de la tâche avec un timeout
            final_response_content = task.get(timeout=300)
            logger.info(f"Réponse complète reçue de l'orchestrateur pour SID {sid}.")

            # Construire la réponse complète au format OpenAI
            response_payload = {
                "id": request_id,
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model_id,
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": final_response_content,
                    },
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": 0, # TODO: Calculer le nombre de tokens
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
            }
            return jsonify(response_payload)

        except Exception as e:
            logger.error(f"Erreur lors de la récupération du résultat de la tâche Celery pour SID {sid}: {e}", exc_info=True)
            return jsonify({"error": "Une erreur interne est survenue lors du traitement de votre requête."}), 500
