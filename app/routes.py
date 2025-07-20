from flask import Blueprint, request, jsonify
from .tasks import search_web_task, long_running_task

bp = Blueprint('main', __name__)




# Nouvelle route /chat qui simule la décision d'un LLM et retourne une réponse structurée
@bp.route('/chat', methods=['POST'])
def chat():
    """
    Point d'entrée API pour traiter une question utilisateur via LLM ou outil.
    """
    data = request.get_json(force=True)
    user_question = data.get('question') if data else None
    if not user_question:
        return jsonify({'error': "Le champ 'question' est requis."}), 400

    decision = decide_llm_action(user_question)

    # Structure de la réponse selon l'action décidée
    if decision.get("action") == "call_tool":
        response = {
            "type": "tool_call",
            "tool_name": decision.get("tool_name"),
            "parameters": decision.get("parameters")
        }
    else:
        response = {
            "type": "direct_response",
            "message": decision.get("message")
        }
    return jsonify(response), 200

@bp.route('/')
def index():
    return "AI Gateway is running!"

@bp.route('/trigger-task', methods=['POST'])
def trigger_task():
    """
    Déclenche la tâche Celery en lui passant le SID du body JSON.
    """
    data = request.get_json(force=True)
    sid = data.get('sid') if data else None
    print(f"[DEBUG] SID reçu du client : {sid}")
    task = long_running_task.delay(sid)
    print(f"Tâche {task.id} lancée pour le client SID: {sid}")
    return jsonify({'message': f'Tâche {task.id} démarrée !'}), 202

