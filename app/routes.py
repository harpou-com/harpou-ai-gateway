"""
Définition des routes pour l'API de l'application Gateway AI.
Cette partie du code gère les requêtes entrantes et les traite en fonction de leur contenu.
"""
# 1. Imports
import json
import logging
import time
import uuid
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context
from celery.result import AsyncResult
from celery.utils.log import get_task_logger
from .extensions import socketio, limiter, celery
from .tasks import orchestrator_task
from .llm_connector import _execute_llm_request
from .cache import get_models
from .auth import require_api_key

# 2. Constantes et Configuration
logger = get_task_logger(__name__)

bp = Blueprint('main', __name__)

@bp.route('/')
def index():
    """Route de base pour vérifier que le service est en ligne."""
    return "AI Gateway is running!"

@bp.route('/chat', methods=['POST'])
def chat():
    """
    Point d'entrée API qui lance la tâche d'orchestration de manière asynchrone.
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    user_question = data.get('question')
    sid = data.get('sid')
    
    if not user_question or not sid:
        return jsonify({'error': "Les champs 'question' et 'sid' sont requis."}), 400

    task = orchestrator_task.delay(user_question, sid)

    return jsonify({
        "status": "accepted",
        "task_id": task.id,
        "message": "La question a été transmise à l'orchestrateur IA pour traitement."
    }), 202

@bp.route('/v1/models', methods=['GET'])
@require_api_key
@limiter.limit("60/minute") # Applique une limite de 60 requêtes par minute
def list_models():
    """
    Découverte des modèles. Retourne une liste de tous les modèles disponibles
    depuis le cache, au format compatible OpenAI.
    Le cache est rafraîchi périodiquement par une tâche de fond.
    """
    cached_models = get_models()
    if not cached_models:
        # Forcer un refresh immédiat si le cache est vide
        from .services import refresh_and_cache_models
        cached_models = refresh_and_cache_models()
        current_app.logger.info("Cache vide, rafraîchissement forcé côté gateway.")
    current_app.logger.info(f"Service de la liste des modèles depuis le cache ({len(cached_models)} modèles).")

    # Formater la réponse finale pour être compatible avec l'API OpenAI
    return jsonify({"object": "list", "data": cached_models})

@bp.route('/v1/chat/completions', methods=['POST'])
@require_api_key
@limiter.limit("120 per minute") # Applique une limite de 120 requêtes par minute
def chat_completions():
    """
    Point d'entrée pour la compatibilité avec l'API OpenAI (ex: Open WebUI).
    - Si un SID est fourni (mode asynchrone via WebSocket), lance la tâche et retourne
      un flux SSE initial pour éviter les timeouts. La réponse finale arrive par WebSocket.
    - Sinon (mode synchrone), la logique de streaming complète sera implémentée.
    """
    # --- Journalisation d'audit (Début) ---
    audit_logger = logging.getLogger('audit')
    request_id = f"req_{uuid.uuid4()}"
    request_timestamp = time.time()

    # Cloner les en-têtes pour pouvoir les sérialiser en JSON
    headers_for_log = {k: v for k, v in request.headers.items()}

    # 1. Parser le corps de la requête JSON (et le garder pour l'audit)
    payload = request.get_json()
    
    # Log de la requête initiale
    audit_logger.info(json.dumps({"request_id": request_id, "timestamp": request_timestamp, "type": "request", "payload": payload, "headers": headers_for_log}))

    if not payload:
        return jsonify({"error": {"message": "Corps de la requête invalide (doit être du JSON).", "type": "invalid_request_error"}}), 400

    # 2. Extraire les données essentielles
    messages = payload.get('messages')
    model_name = payload.get('model')
    tools = payload.get('tools')
    tool_choice = payload.get('tool_choice')

    if not isinstance(messages, list) or not messages:
        return jsonify({"error": {"message": "Le champ 'messages' est requis et doit être une liste non vide.", "type": "invalid_request_error"}}), 400

    last_message = messages[-1]
    if not isinstance(last_message, dict) or 'content' not in last_message:
        return jsonify({"error": {"message": "Le dernier élément de 'messages' doit être un objet avec une clé 'content'.", "type": "invalid_request_error"}}), 400

    user_question = last_message['content']

    # 3. Récupérer l'identifiant de session (sid) depuis les en-têtes HTTP
    sid = request.headers.get('X-SID')

    # 4. Implémenter la Logique de Routage Intelligente (NOUVEAU FLUX)
    # L'orchestrateur est déclenché UNIQUEMENT si le modèle est un agent.
    # Les requêtes avec "tools" pour des modèles standards sont gérées comme des appels OpenAI classiques.
    is_agentic_request = model_name and model_name.startswith("harpou-agent/")
    if is_agentic_request:
        # On a besoin d'un SID pour le mode agent/asynchrone
        if not sid:
            return jsonify({"error": {"message": "L'en-tête 'X-SID' est requis pour les requêtes agentiques.", "type": "invalid_request_error"}}), 400
        current_app.logger.info(f"Lancement d'une requête agentique pour le modèle '{model_name}' avec SID '{sid}'.")

        # Retirer le préfixe de l'agent pour obtenir le vrai nom du modèle
        agent_prefix = current_app.config.get("AGENT_MODEL_PREFIX", "harpou-agent/")
        actual_model_name = model_name.replace(agent_prefix, "", 1)

        task = orchestrator_task.delay(messages=messages, sid=sid, model_name=actual_model_name)

        # Retourner une réponse HTTP 202 Accepted formatée comme une réponse OpenAI
        response_payload = {
            "id": task.id,
            "object": "task.accepted",
            "created": int(time.time()),
            "model": model_name,
            "choices": [{
                "index": 0,
                "delta": {"role": "assistant", "content": "Tâche agentique lancée..."},
                "finish_reason": None
            }]
        }
        return jsonify(response_payload), 202
    else:
        # SINON (modèle standard, flux synchrone/streaming direct)
        stream = payload.get('stream', False)

        # --- Logique de routage (SIMPLIFIÉE) ---
        # La logique de routage est maintenant entièrement gérée par get_chat_completion.
        # On passe simplement le nom du modèle tel que reçu. Si model_name est None,
        # get_chat_completion utilisera le backend primaire par défaut.
        # model_to_use = model_name

        # Si aucun modèle n'est spécifié par le client, on doit lever une erreur claire
        # car la spec OpenAI requiert un nom de modèle.
        if not model_name:
            return jsonify({"error": {"message": "Le champ 'model' est requis dans le corps de la requête.", "type": "invalid_request_error"}}), 400

        if stream:
            # SI stream est true :
            def generate_stream_response():
                # --- Pour la journalisation d'audit ---
                response_parts = []
                final_finish_reason = None
                final_response_for_log = None
                status_code = 200

                try:
                    response_stream = _execute_llm_request(
                        model_name=model_name, messages=messages, stream=True,
                        tools=tools, tool_choice=tool_choice
                    )
                    for chunk in response_stream:
                        # Accumuler les parties pour le log final
                        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                            response_parts.append(chunk.choices[0].delta.content)
                        if chunk.choices and chunk.choices[0].finish_reason:
                            final_finish_reason = chunk.choices[0].finish_reason
                        
                        # Le chunk de la librairie OpenAI est un objet Pydantic, on le convertit en JSON pour le SSE
                        yield f"data: {chunk.model_dump_json()}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    status_code = 500
                    current_app.logger.error(f"Erreur lors du streaming de la réponse LLM: {e}", exc_info=True)
                    error_payload = {"error": {"message": str(e), "type": "api_error"}}
                    final_response_for_log = error_payload # Log this error
                    yield f"data: {json.dumps(error_payload)}\n\n"
                    yield "data: [DONE]\n\n"
                finally:
                    # --- Journalisation d'audit (Réponse streamée) ---
                    # Construire la réponse finale uniquement si elle n'a pas déjà été définie par une erreur
                    if final_response_for_log is None:
                        final_content = "".join(response_parts)
                        final_response_for_log = {
                            "id": f"chatcmpl-stream-{request_id}",
                            "object": "chat.completion",
                            "model": model_name,
                            "choices": [{
                                "index": 0,
                                "message": {"role": "assistant", "content": final_content},
                                "finish_reason": final_finish_reason
                            }]
                        }
                    
                    audit_logger.info(json.dumps({
                        "request_id": request_id,
                        "timestamp": time.time(),
                        "type": "response",
                        "response": final_response_for_log,
                        "status_code": status_code
                    }))
            return Response(stream_with_context(generate_stream_response()), mimetype='text/event-stream')
        else:
            # SINON (stream est false ou absent, réponse JSON complète)
            # C'est ici que nous lançons la tâche agentique et retournons un ID de tâche.
            
            # Générer un SID si aucun n'est fourni (pour les clients non-websocket)
            if not sid:
                sid = str(uuid.uuid4())
                current_app.logger.info(f"Génération d'un SID ({sid}) pour une requête API synchrone.")

            task = orchestrator_task.delay(messages=messages, sid=sid, model_name=model_name)

            # On retourne une réponse qui indique que la tâche est acceptée et fournit un moyen de la suivre.
            return jsonify({
                "task_id": task.id,
                "status_endpoint": f"/v1/tasks/status/{task.id}",
                "message": "La tâche a été acceptée et est en cours de traitement. Veuillez sonder l'endpoint de statut pour le résultat."
            }), 202
            
            """
            try:
                response_obj = _execute_llm_request(
                    model_name=model_name, messages=messages, stream=False,
                    tools=tools, tool_choice=tool_choice
                )
                # Le connecteur retourne un objet Pydantic compatible OpenAI.
                # La méthode .to_json() le sérialise directement au format attendu.
                response_for_log = json.loads(response_obj.to_json())
                audit_logger.info(json.dumps({
                    "request_id": request_id, 
                    "timestamp": time.time(), 
                    "type": "response", 
                    "response": response_for_log,
                    "status_code": 200
                }))
                return Response(response_obj.to_json(), mimetype='application/json', status=200)
            except Exception as e:
                current_app.logger.error(f"Erreur lors de la récupération de la complétion LLM: {e}", exc_info=True)
                error_response = {"error": {"message": str(e), "type": "api_error"}}
                audit_logger.info(json.dumps({
                    "request_id": request_id,
                    "timestamp": time.time(),
                    "type": "response",
                    "response": error_response,
                    "status_code": 500
                }))
                return jsonify(error_response), 500
            """

@bp.route('/v1/tasks/status/<task_id>', methods=['GET'])
@require_api_key
@limiter.limit("120 per minute")
def get_task_status(task_id):
    """
    Sonde le statut d'une tâche Celery asynchrone.
    Cet endpoint est utilisé par les clients pour suivre la progression
    des tâches de longue durée, comme les requêtes agentiques.
    """
    task = AsyncResult(task_id, app=celery)

    if task.state in ['PENDING', 'STARTED']:
        # PENDING peut aussi signifier que le task_id est inconnu du backend de résultats.
        # C'est un comportement normal de Celery.
        response = {"task_id": task_id, "status": "in_progress", "message": "Tâche en cours de traitement..."}
        return jsonify(response)
    
    if task.state == 'SUCCESS':
        # Utiliser un timeout court sur .get() est une bonne pratique, même si le statut est SUCCESS.
        response = {"task_id": task_id, "status": "completed", "result": task.get(timeout=1)}
        return jsonify(response)

    if task.state in ['FAILURE', 'REVOKED']:
        response = {"task_id": task_id, "status": "failed", "error": str(task.info)}
        return jsonify(response), 500

    # Cas pour un état inattendu
    return jsonify({"task_id": task_id, "status": task.state})