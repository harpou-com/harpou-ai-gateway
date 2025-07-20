from flask import Blueprint, request, jsonify
from .tasks import search_web_task, long_running_task, orchestrator_task

bp = Blueprint('main', __name__)




# Nouvelle route /chat qui simule la décision d'un LLM et retourne une réponse structurée
@bp.route('/chat', methods=['POST'])
def chat():
    """
    Point d'entrée API pour traiter une question utilisateur via LLM ou outil.
    """
    data = request.get_json(force=True)
    user_question = data.get('question') if data else None
    sid = data.get('sid') if data else None
    if not user_question or not sid:
        return jsonify({'error': "Les champs 'question' et 'sid' sont requis."}), 400

    # Lancement asynchrone de la tâche d'orchestration
    task = orchestrator_task.delay(user_question, sid)

    response = {
        "status": "accepted",
        "task_id": task.id,
        "message": "La question a été transmise à l'orchestrateur IA pour traitement."
    }
    return jsonify(response), 202

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

