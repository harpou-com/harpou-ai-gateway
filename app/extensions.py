from celery import Celery
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import request, g, current_app

def rate_limit_identifier():
    """
    Identifie une requête soit par sa clé API, soit par son adresse IP.
    La clé API est prioritaire pour la limitation de débit.
    """
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        # Utilise la clé API comme identifiant pour le rate limiting
        return auth_header.split(' ', 1)[1]
    # Si pas de clé, utilise l'adresse IP comme fallback
    return get_remote_address()

def get_rate_limit_from_key():
    """
    Retourne la limite de taux spécifique à la clé API, ou la limite par défaut.
    """
    # g.api_key_info est défini par le décorateur @require_api_key
    if hasattr(g, 'api_key_info') and g.api_key_info.get('rate_limit'):
        return g.api_key_info['rate_limit']
    # Sinon, retourne la limite par défaut de l'application
    return current_app.config.get("RATELIMIT_DEFAULT")

# On initialise Celery ici, mais sans configuration.
# La configuration sera chargée depuis l'application Flask plus tard.
celery = Celery(__name__)
# On initialise SocketIO ici, mais sans configuration.
# La configuration (async_mode, message_queue, etc.) sera appliquée
# via socketio.init_app() dans la factory de l'application.
socketio = SocketIO(async_mode='eventlet')

# Initialisation de Flask-Limiter.
# La stratégie de clé est personnalisée pour utiliser la clé API si elle est présente,
# Les limites réelles sont chargées depuis la configuration de l'application.
limiter = Limiter(
    key_func=rate_limit_identifier,
    # La limite par défaut est maintenant une fonction dynamique
    default_limits=[get_rate_limit_from_key]
)
