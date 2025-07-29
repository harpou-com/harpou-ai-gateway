import eventlet
# Appliquer le monkey-patching tout au début, avant l'importation de tout autre module.
# C'est essentiel pour qu'eventlet fonctionne correctement avec Celery.
eventlet.monkey_patch()

# --- Logique d'initialisation pour le service Beat ---
from app import create_app
from celery_worker import init_celery_with_flask_app

# 1. Créer une instance de l'application Flask pour fournir le contexte et la configuration.
#    init_socketio=False est important car le service Beat ne gère pas les requêtes web.
app = create_app(init_socketio=False)

# 2. Initialiser Celery avec la configuration et le contexte de l'application Flask.
#    Ceci configure le broker, le backend, et surtout le `beat_schedule`.
init_celery_with_flask_app(app)
# --- Fin de la logique d'initialisation ---

from celery.__main__ import main

if __name__ == '__main__':
    # 3. Exécute la ligne de commande de Celery.
    #    Les arguments (ex: -A celery_worker.celery beat) sont passés par la commande
    #    qui exécute ce script. Celery trouvera l'instance 'celery' déjà configurée.
    main()