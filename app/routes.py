from flask import Blueprint, jsonify
from .tasks import long_running_task
from . import socketio

bp = Blueprint('main', __name__)

@bp.route('/trigger-task', methods=['POST'])
def trigger_task():
    """
    Déclenche la tâche Celery 'long_running_task'.
    """
    task = long_running_task.delay()
    return jsonify({'task_id': task.id}), 202  # 202 Accepted


@socketio.on('connect')
def test_connect():
    """
    Gestionnaire d'événement pour la connexion d'un client.
    """
    print("Client connecté")