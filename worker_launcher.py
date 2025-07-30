import eventlet
eventlet.monkey_patch()

# --- Logique d'initialisation pour le worker ---
from app import create_app
from celery_worker import init_celery_with_flask_app

# 1. Créer une instance de l'application Flask pour fournir le contexte.
app = create_app()

# 2. Initialiser Celery avec la configuration et le contexte de l'application Flask.
#    L'objet 'celery' (défini dans celery_worker.py) est maintenant configuré.
init_celery_with_flask_app(app)
# --- Fin de la logique d'initialisation ---

from celery.__main__ import main

if __name__ == '__main__':
    # 3. Exécute la ligne de commande de Celery.
    #    Les arguments (ex: -A celery_worker.celery worker) sont passés par la commande
    #    qui exécute ce script. Celery trouvera l'instance 'celery' déjà configurée.
    main()