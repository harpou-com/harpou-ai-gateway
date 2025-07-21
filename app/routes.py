# app/routes.py

from flask import Blueprint, jsonify, request
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