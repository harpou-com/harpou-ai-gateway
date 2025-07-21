from celery import Celery
from flask_socketio import SocketIO

# On initialise Celery ici, mais sans configuration.
# La configuration sera chargée depuis l'application Flask plus tard.
celery = Celery(__name__)
socketio = SocketIO(async_mode='eventlet', message_queue='redis://redis:6379/0')
