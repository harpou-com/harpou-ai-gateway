from celery import Celery
from flask_socketio import SocketIO

# On initialise Celery ici, mais sans configuration.
# La configuration sera chargée depuis l'application Flask plus tard.
celery = Celery(__name__)
# On initialise SocketIO ici, mais sans configuration.
# La configuration (async_mode, message_queue, etc.) sera appliquée
# via socketio.init_app() dans la factory de l'application.
socketio = SocketIO(async_mode='eventlet')
