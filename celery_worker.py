from dotenv import load_dotenv

# Charger les variables d'environnement avant toute autre importation
# pour s'assurer que create_app() les voit.
load_dotenv()

from app import create_app
from app.extensions import celery

# Crée l'application Flask pour que Celery puisse utiliser sa configuration, sans initialiser SocketIO
app = create_app(init_socketio=False)
app.app_context().push()
