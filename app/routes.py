# app/routes.py
import json
import time
import uuid

from flask import Blueprint, jsonify, request, current_app, Response, stream_with_context
from .tasks import orchestrator_task

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

@bp.route('/v1/chat/completions', methods=['POST'])
def chat_completions():
    """
    Point d'entrée pour la compatibilité avec l'API OpenAI (ex: Open WebUI).
    - Si un SID est fourni (mode asynchrone via WebSocket), lance la tâche et retourne
      un flux SSE initial pour éviter les timeouts. La réponse finale arrive par WebSocket.
    - Sinon (mode synchrone), la logique de streaming complète sera implémentée.
    """
    # 1. Parser le corps de la requête JSON
    payload = request.get_json()
    if not payload:
        return jsonify({"error": {"message": "Corps de la requête invalide (doit être du JSON).", "type": "invalid_request_error"}}), 400

    # 2. Récupérer la question de l'utilisateur depuis le tableau 'messages'
    messages = payload.get('messages')
    if not isinstance(messages, list) or not messages:
        return jsonify({"error": {"message": "Le champ 'messages' est requis et doit être une liste non vide.", "type": "invalid_request_error"}}), 400

    last_message = messages[-1]
    if not isinstance(last_message, dict) or 'content' not in last_message:
        return jsonify({"error": {"message": "Le dernier élément de 'messages' doit être un objet avec une clé 'content'.", "type": "invalid_request_error"}}), 400
    
    user_question = last_message['content']

    # 3. Récupérer l'identifiant de session (sid) depuis les en-têtes HTTP
    # Ce SID est utilisé par notre architecture asynchrone pour renvoyer la réponse via WebSocket.
    # Pour les clients standards OpenAI, cet en-tête ne sera pas présent.
    sid = request.headers.get('X-SID')

    # 4. Journaliser et lancer la tâche si SID est présent
    current_app.logger.info(
        f"Requête de complétion de chat reçue. SID: '{sid or 'Non fourni'}', "
        f"Question: '{user_question[:80]}...'"
    )

    if sid:
        # Lancer la tâche asynchrone. La réponse sera envoyée via WebSocket.
        task = orchestrator_task.delay(user_question, sid)
        current_app.logger.info(f"Tâche d'orchestration {task.id} lancée pour le SID {sid}.")

        def generate_sse_handshake():
            """
            Génère un flux SSE initial pour satisfaire les clients comme Open WebUI.
            Ceci évite les timeouts en fournissant une réponse immédiate en streaming.
            La réponse réelle sera envoyée via la connexion WebSocket existante.
            """
            try:
                # 1. Envoyer un premier chunk pour établir la connexion et le rôle.
                initial_chunk = {
                    "id": f"chatcmpl-{uuid.uuid4()}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": current_app.config.get('DEFAULT_LLM_MODEL', 'harpou-ai-gateway'),
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": ""},
                        "finish_reason": None
                    }]
                }
                yield f"data: {json.dumps(initial_chunk)}\n\n"
                current_app.logger.info(f"Handshake SSE envoyé pour SID {sid}. En attente de la réponse via WebSocket.")

                # 2. Envoyer immédiatement le signal [DONE] pour fermer ce flux HTTP.
                yield "data: [DONE]\n\n"
            except GeneratorExit:
                current_app.logger.warning(f"Le client s'est déconnecté du flux SSE pour SID {sid}.")

        # Retourner une réponse en streaming avec le handshake.
        return Response(stream_with_context(generate_sse_handshake()), mimetype='text/event-stream')
    else:
        # Cas où aucun SID n'est fourni. La gestion synchrone sera implémentée plus tard.
        # Pour l'instant, on retourne une erreur claire.
        return jsonify({"error": {"message": "L'en-tête 'X-SID' est requis pour utiliser ce point d'entrée en mode asynchrone.", "type": "invalid_request_error"}}), 400