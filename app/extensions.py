# app/extensions.py

from celery import Celery
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask import request, g, current_app
from flask_caching import Cache # <--- AJOUT POUR LE CACHE

def _get_key_info_from_request():
    """
    Helper function to extract API key info from the current request.
    It memoizes the result in `g` to avoid redundant lookups within the same request.
    """
    # Check if we've already done the lookup for this request
    if hasattr(g, 'api_key_info'):
        return g.api_key_info

    # Perform the lookup
    provided_key = None
    auth_header = request.headers.get('Authorization')
    if auth_header and auth_header.startswith('Bearer '):
        provided_key = auth_header.split(' ', 1)[1]

    valid_users_dict = current_app.config.get('USERS_DICT', {})
    
    # If no keys are configured at all, treat as public access.
    if not valid_users_dict:
        g.api_key_info = {"username": "public_access"}
        return g.api_key_info

    key_info = valid_users_dict.get(provided_key)
    if key_info:
        g.api_key_info = key_info
    else:
        # Invalid or no key provided
        g.api_key_info = {"username": "invalid_key"}
    
    return g.api_key_info

def rate_limit_identifier():
    """
    Identifies a request by the API key's owner for rate-limiting.
    Falls back to the remote IP address if the key is invalid or absent.
    Using the owner is more secure than using the key itself.
    """
    key_info = _get_key_info_from_request()
    if key_info.get("username") not in ["public_access", "invalid_key"]:
        return key_info["username"]
    return get_remote_address()

def get_rate_limit_from_key():
    """
    Returns the rate limit specific to the API key, or the default limit.
    This is now reliable because _get_key_info_from_request is called first.
    """
    key_info = _get_key_info_from_request()
    limit = key_info.get('rate_limit')
    # Si la limite est explicitement "unlimited", on ne retourne aucune limite.
    if limit == "unlimited":
        return None
    # Sinon, on retourne la limite de la clé ou la limite par défaut.
    return limit or current_app.config.get("RATELIMIT_DEFAULT")

# Initialisation de Celery. L'instance est définie ici pour être partagée par toute l'application.
celery = Celery(__name__, include=['app.tasks'])

# Initialisation de SocketIO
socketio = SocketIO(async_mode='eventlet')

# Initialisation du Cache # <--- AJOUT POUR LE CACHE
flask_cache = Cache()

# Initialisation de Flask-Limiter.
limiter = Limiter(
    key_func=rate_limit_identifier,
    # La limite par défaut est maintenant une fonction dynamique
    default_limits=[get_rate_limit_from_key]
)
