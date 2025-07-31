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

@bp.route('/v1/tasks/status/<task_id>', methods=['GET'])
@require_api_key
def get_task_status(task_id):
    """
    Sonde le statut d'une tâche Celery. C'est l'endpoint que le Pipe va appeler.
    """
    # Utiliser l'instance celery de l'application pour créer l'objet de résultat
    task = AsyncResult(task_id, app=celery)
    
    if task.state == 'PENDING' or task.state == 'STARTED':
        response = {'status': 'in_progress'}
    elif task.state == 'SUCCESS':
        response = {'status': 'completed', 'result': task.result}
    elif task.state == 'FAILURE':
        # Renvoyer une information d'erreur propre
        response = {'status': 'failed', 'error': str(task.info)}
    else:
        response = {'status': 'unknown', 'state': task.state}
        
    logger.debug(f"Polling pour la tâche {task_id}: Statut {response.get('status')}")
    return jsonify(response)


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

    # Le Pipe agentique attend un comportement asynchrone.
    # Nous lançons la tâche et retournons immédiatement un ID de tâche.
    sid = str(uuid.uuid4())
    logger.info(f"Requête agentique reçue. Lancement de la tâche en arrière-plan pour SID {sid}.")
    
    task = orchestrator_task.delay(sid=sid, conversation=conversation, model_id=model_id)
    
    # C'est la réponse que le Pipe attend pour commencer le polling.
    response_payload = {
        "id": task.id,
        "message": "Task accepted and is running in the background."
    }
    
    # On retourne un statut 202 Accepted pour indiquer que la requête est acceptée
    # mais pas encore terminée.
    return jsonify(response_payload), 202
