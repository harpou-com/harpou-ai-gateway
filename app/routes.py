import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from celery.result import AsyncResult
from app.extensions import celery, limiter # Import de l'instance Celery et du limiteur
from .extensions import _get_key_info_from_request
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
@limiter.exempt
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
    """
    Point d'entrée principal pour les requêtes de chat.
    Gère les flux synchrones (clients API standards) et asynchrones (client WebUI).
    """
    data = request.json
    model_id = data.get("model")
    conversation = data.get("messages")
    stream = data.get("stream", False)

    if not model_id:
        return jsonify({"error": {"message": "Le paramètre 'model' est manquant.", "type": "invalid_request_error"}}), 400
    if not conversation:
        return jsonify({"error": {"message": "Le paramètre 'messages' est manquant.", "type": "invalid_request_error"}}), 400

    # Déterminer le type de flux en fonction de la présence de l'en-tête X-SID.
    # Cet en-tête est ajouté par le Pipe de l'agent WebUI.
    is_async_flow = 'X-SID' in request.headers

    if is_async_flow:
        # --- FLUX ASYNCHRONE (pour le client WebUI) ---
        sid = request.headers.get('X-SID')
        logger.info(f"Flux asynchrone détecté pour SID {sid}. Lancement de la tâche en arrière-plan.")
        # Récupérer les informations de l'utilisateur pour les passer à la tâche
        user_info = _get_key_info_from_request()
        task = orchestrator_task.delay(sid=sid, conversation=conversation, model_id=model_id, user_info=user_info)
        
        response_payload = {
            "id": task.id,
            "message": "Task accepted and is running in the background."
        }
        return jsonify(response_payload), 202
    else:
        # --- FLUX SYNCHRONE (pour les clients API OpenAI standards) ---
        logger.info("Flux synchrone détecté. Traitement de la requête de manière bloquante.")
        
        try:
            # Cette fonction gère l'appel à la tâche, l'attente du résultat,
            # et le formatage de la réponse en un objet ChatCompletion compatible.
            response_obj = llm_connector.get_chat_completion(
                model_name=model_id,
                messages=conversation,
                stream=stream
            )
            # .model_dump() est la méthode Pydantic pour convertir l'objet en dictionnaire
            return jsonify(response_obj.model_dump())
        except Exception as e:
            logger.error(f"Erreur lors du traitement synchrone de la tâche: {e}", exc_info=True)
            return jsonify({"error": {"message": "Une erreur interne est survenue lors du traitement de votre requête.", "type": "internal_server_error"}}), 500
