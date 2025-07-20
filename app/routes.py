from flask import Blueprint, request, jsonify
from .tasks import search_web_task, long_running_task

bp = Blueprint('main', __name__)

# Nouvelle route pour lancer la recherche web asynchrone et notifier le client via WebSocket
@bp.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(force=True)
    user_query = data.get('query')
    client_sid = data.get('sid')
    if not user_query or not client_sid:
        return jsonify({'error': 'Paramètres query et sid requis.'}), 400
    print(f"[chat] Lancement de la tâche pour user_query='{user_query}' et client_sid='{client_sid}'")
    search_web_task.delay(user_query, client_sid)
    return jsonify({'message': f"Recherche lancée pour : {user_query}", 'sid': client_sid}), 202

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

