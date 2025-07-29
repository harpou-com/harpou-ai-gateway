import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio # SocketIO est initialisé dans create_app
from celery_worker import init_celery_with_flask_app # Import de la fonction d'initialisation

app = create_app()

# Initialiser Celery avec le contexte de l'application Flask.
init_celery_with_flask_app(app)

if __name__ == "__main__":
    # Utiliser le reloader de socketio en mode debug, il est plus stable que celui de Flask.
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=True)
