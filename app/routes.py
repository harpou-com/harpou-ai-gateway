
from flask import Blueprint, jsonify
from .tasks import long_running_task

bp = Blueprint('main', __name__)


@bp.route('/trigger-task', methods=['POST'])
def trigger_task():
    """
    Déclenche la tâche Celery 'long_running_task'.
    """
    task = long_running_task.delay()
    return jsonify({'task_id': task.id}), 202  # 202 Accepted

