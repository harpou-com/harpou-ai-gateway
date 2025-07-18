import time
from .extensions import celery, socketio

@celery.task(bind=True)
def long_running_task(self, sid):
    """
    Tâche de démo qui attend 5 secondes, puis envoie une notification
    au client spécifique qui a déclenché la tâche.
    """
    print(f"Début d'une tâche longue pour le client SID: {sid}")
    time.sleep(5)
    print(f"Tâche terminée. Envoi de la notification au SID: {sid}")
    # Utilise self.request.id pour obtenir l'ID de la tâche
    task_id = self.request.id
    socketio.emit('task_result', {
        'status': 'success',
        'message': 'Tâche terminée !',
        'task_id': task_id
    }, room=sid)
    return "Notification envoyée."