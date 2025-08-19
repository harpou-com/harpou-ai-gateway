import logging
from flask import jsonify, g
from functools import wraps
from .extensions import _get_key_info_from_request

logger = logging.getLogger(__name__)

def _initialize_users(app):
    """
    Charge les utilisateurs depuis la configuration et les prépare pour une recherche rapide.
    """
    users = app.config.get('users', [])
    # Crée un dictionnaire pour des recherches en O(1)
    # La clé est la clé API, la valeur est l'objet utilisateur complet.
    app.config['USERS_DICT'] = {user_info['key']: user_info for user_info in users if 'key' in user_info}
    logger.info(f"{len(app.config['USERS_DICT'])} utilisateur(s) chargé(s).")

def require_api_key(f):
    """
    Décorateur pour protéger un endpoint et exiger une clé API valide.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # La logique de vérification est centralisée dans _get_key_info_from_request
        key_info = _get_key_info_from_request()
        
        # Si l'username est 'invalid_key', cela signifie que la clé fournie
        # n'a pas été trouvée dans notre dictionnaire d'utilisateurs.
        if key_info.get("username") == "invalid_key":
             return jsonify({"error": {"message": "Clé API invalide ou manquante.", "type": "authentication_error"}}), 401
        
        return f(*args, **kwargs)
    return decorated_function