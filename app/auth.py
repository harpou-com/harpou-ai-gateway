"""
Gestion de l'authentification pour l'API Gateway.
"""
from functools import wraps
from flask import request, jsonify, current_app, g

def require_api_key(f):
    """
    Un décorateur pour protéger les routes qui nécessitent une clé API.
    Il vérifie la présence d'un en-tête 'Authorization: Bearer <VOTRE_CLÉ>'.
    Il attache également les informations de la clé à `g.api_key_info`.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 1. Récupérer la liste des clés API valides depuis la configuration
        # La configuration attend une liste d'objets, ex: [{"key": "sk-...", "owner": "user1"}]
        valid_keys_config = current_app.config.get('api_keys', [])
        
        # Si aucune clé n'est configurée dans le fichier config.json, l'accès est public.
        # C'est un comportement par défaut pour faciliter le démarrage.
        # Pour sécuriser, il suffit d'ajouter au moins une clé dans la configuration.
        if not valid_keys_config:
            current_app.logger.warning("Aucune clé API n'est configurée ('api_keys' est vide ou absent dans la config). L'accès à l'API est public.")
            g.api_key_info = {"owner": "public"} # Pour la journalisation/limitation
            return f(*args, **kwargs)

        # 2. Récupérer la clé fournie par le client
        provided_key = None
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            provided_key = auth_header.split(' ', 1)[1]

        # 3. Vérifier si la clé est valide et récupérer ses informations
        key_info = None
        if provided_key:
            for item in valid_keys_config:
                if item.get('key') == provided_key:
                    key_info = item
                    break
        
        if key_info:
            g.api_key_info = key_info # Attacher les infos de la clé au contexte de la requête
            return f(*args, **kwargs) # La clé est valide, on continue
        else:
            # Clé manquante ou invalide
            current_app.logger.warning(f"Tentative d'accès non autorisé. Clé fournie: {'oui' if provided_key else 'non'}.")
            error_payload = {"error": {"message": "Clé API incorrecte fournie. Vous devez fournir une clé API valide dans l'en-tête 'Authorization: Bearer <KEY>'.", "type": "invalid_request_error", "code": "invalid_api_key"}}
            return jsonify(error_payload), 401
            
    return decorated_function