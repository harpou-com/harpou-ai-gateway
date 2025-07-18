import time
from . import celery

@celery.task
def long_running_task():
    """
    Une tâche de démonstration qui attend 5 secondes et retourne un message.
    """
    # Cette sortie apparaîtra dans la console du worker Celery
    print("Début d'une tâche longue (5 secondes)...")
    time.sleep(5)
    print("Tâche terminée.")
    return "La tâche s'est terminée avec succès après 5 secondes."