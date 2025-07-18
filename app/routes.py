from flask import Blueprint, jsonify, request
from .tasks import long_running_task

bp = Blueprint('main', __name__)

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

