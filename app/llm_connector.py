# app/llm_connector.py
import openai
import json
import base64
import requests
import mimetypes
import copy
import time
from flask import current_app


def _get_backend_config(backend_name):
    """
    Récupère la configuration d'un backend spécifique par son nom.
    """
    backends = current_app.config.get('llm_backends', [])
    for backend in backends:
        if backend.get('name') == backend_name:
            return backend
    return None

# --- Nouvelle fonction utilitaire pour l'encodage d'images ---
def _encode_image_url(url):
    """
    Télécharge une image depuis une URL et l'encode en Base64 Data URI.
    """
    try:
        headers = {'User-Agent': 'Harpou-AI-Gateway/1.0'}
        response = requests.get(url, stream=True, timeout=10, headers=headers)
        response.raise_for_status()

        # Deviner le type MIME à partir de l'URL ou des en-têtes de la réponse
        content_type = response.headers.get('Content-Type')
        if not content_type or 'image' not in content_type:
            mime_type, _ = mimetypes.guess_type(url)
        else:
            mime_type = content_type

        if not mime_type:
            mime_type = 'application/octet-stream' # Fallback

        image_data = response.content
        base64_image = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{base64_image}"
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Impossible de récupérer l'image depuis l'URL {url}: {e}")
        return None

def list_models_from_backend(backend_config):
    """
    Interroge un backend pour obtenir la liste des modèles disponibles.
    Gère les backends de type 'openai' et 'ollama' via leur API compatible OpenAI.

    Args:
        backend_config (dict): La configuration du backend à interroger.

    Returns:
        list: Une liste d'objets de modèle (compatibles Pydantic/OpenAI) ou une liste vide en cas d'erreur.
    """
    backend_name = backend_config.get('name')
    backend_type = backend_config.get('type')
    base_url = backend_config.get('base_url')

    if not base_url:
        current_app.logger.error(f"URL de base non configurée pour le backend '{backend_name}'.")
        return []

    # Assurer la compatibilité avec l'API OpenAI d'Ollama qui se trouve sur /v1
    if 'ollama' in backend_type and base_url and not base_url.endswith('/v1'):
        base_url = f"{base_url.rstrip('/')}/v1"

    # Le client OpenAI requiert une clé API, même si le backend ne l'utilise pas (ex: Ollama).
    api_key = backend_config.get('api_key', 'not-needed')

    if 'openai' in backend_type and not backend_config.get('api_key'):
        current_app.logger.error(f"Clé API manquante pour le backend '{backend_name}' de type '{backend_type}'.")
        return []

    try:
        client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=5.0)
        models_response = client.models.list()
        model_list = models_response.data
        current_app.logger.info(f"{len(model_list)} modèles trouvés pour le backend '{backend_name}'.")
        return model_list

    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        current_app.logger.warning(f"Impossible de joindre le backend '{backend_name}' à '{base_url}': {e}")
    except openai.APIStatusError as e:
        current_app.logger.error(f"Erreur API du backend '{backend_name}' ({base_url}). Statut: {e.status_code}")
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue pour '{backend_name}': {e}", exc_info=True)

    return []

# --- Fonction principale du connecteur ---

def get_llm_completion(prompt, json_mode=False):
    """
    Wrapper simple pour get_chat_completion pour les cas d'utilisation non-chat.
    Appelle le backend LLM primaire pour obtenir une complétion.
    """
    # Utilise le backend primaire par défaut
    primary_backend_name = current_app.config.get('primary_backend_name')
    if not primary_backend_name:
        raise ValueError("Aucun backend LLM primaire n'est configuré.")

    backend_config = _get_backend_config(primary_backend_name)
    if not backend_config:
        raise ValueError(f"Backend primaire '{primary_backend_name}' non trouvé dans la configuration.")

    model_name = backend_config.get('default_model')
    if not model_name:
        raise ValueError(f"Aucun modèle par défaut n'est configuré pour le backend '{primary_backend_name}'.")

    messages = [{"role": "user", "content": prompt}]

    response = get_chat_completion(
        model_name=model_name,
        messages=messages,
        stream=False,
        json_mode=json_mode,
        backend_name=primary_backend_name
    )

    if response.choices and response.choices[0].message and response.choices[0].message.content:
        return response.choices[0].message.content
    return ""

def get_chat_completion(model_name, messages, stream=False, json_mode=False, backend_name=None, tools=None, tool_choice=None, tried_backends=None):
    """
    Effectue une requête de complétion de chat vers un backend LLM spécifique
    en utilisant une interface compatible avec l'API OpenAI.

    Args:
        model_name (str): Le nom du modèle à utiliser.
        messages (list): La liste des messages de la conversation, au format OpenAI.
        stream (bool): Indique si la réponse doit être un flux (stream).
        json_mode (bool): Si True, demande une réponse au format JSON.
        backend_name (str, optional): Le nom du backend à utiliser. Si None, utilise le primaire.
        tools (list, optional): Une liste d'outils que le modèle peut appeler.
        tool_choice (str or dict, optional): Contrôle quel outil est appelé par le modèle.
        tried_backends (set, optional): Un ensemble de noms de backends déjà essayés pour cette requête (utilisé pour le failover).

    Returns:
        La réponse de l'API, qui peut être un objet de complétion ou un itérateur
        de chunks si stream=True.

    Raises:
        ValueError: Si la configuration du backend est manquante ou non supportée.
        openai.APIError: Si l'appel à l'API échoue.
    """
    config = current_app.config
    
    # Initialiser l'ensemble des backends essayés pour le failover
    if tried_backends is None:
        tried_backends = set()
    
    # 1. Déterminer le backend à utiliser
    if not backend_name:
        backend_name = config.get('primary_backend_name')
        if not backend_name:
            raise ValueError("Aucun backend LLM primaire n'est configuré.")
    
    # Marquer ce backend comme "essayé" pour la logique de failover
    tried_backends.add(backend_name)

    # 2. Récupérer la configuration du backend
    backend_config = _get_backend_config(backend_name)
    if not backend_config:
        raise ValueError(f"Backend '{backend_name}' non trouvé dans la configuration.")

    # 3. Traiter les messages pour la multimodalité (encodage d'images pour Ollama)
    # On travaille sur une copie pour ne pas altérer l'objet original
    processed_messages = copy.deepcopy(messages)
    is_multimodal_request = False

    for message in processed_messages:
        if isinstance(message.get('content'), list):
            for part in message['content']:
                if part.get('type') == 'image_url':
                    image_url_obj = part.get('image_url', {})
                    url = image_url_obj.get('url')
                    # On encode uniquement les URL web, pas les données déjà en Base64
                    if url and url.startswith(('http://', 'https://')):
                        is_multimodal_request = True
                        current_app.logger.info(f"Encodage de l'image depuis l'URL : {url}")
                        base64_uri = _encode_image_url(url)
                        if base64_uri:
                            image_url_obj['url'] = base64_uri
                        else:
                            current_app.logger.warning(f"Échec de l'encodage de l'image {url}, elle ne sera pas envoyée au LLM.")

    if is_multimodal_request and json_mode:
        current_app.logger.warning("Le mode JSON est désactivé pour les requêtes multimodales car il est souvent non supporté.")
        json_mode = False

    backend_type = backend_config.get('type')
    base_url = backend_config.get('base_url')
    api_key = backend_config.get('api_key') # Peut être None

    # 3. Préparer les détails de la connexion
    if 'ollama' in backend_type and base_url:
        # Assurer la compatibilité avec l'API OpenAI d'Ollama qui se trouve sur /v1
        if not base_url.endswith('/v1'):
            base_url = f"{base_url.rstrip('/')}/v1"
        # Le client OpenAI requiert une clé, même si Ollama ne l'utilise pas.
        api_key = api_key or "ollama"

    if not base_url:
        raise ValueError(f"L'URL de base pour le backend '{backend_name}' n'est pas configurée.")

    if 'openai' in backend_type and not api_key:
        raise ValueError(f"La clé API pour le backend '{backend_name}' de type '{backend_type}' est requise.")

    # Le client OpenAI gère api_key=None, mais nous mettons une valeur par défaut pour la clarté.
    api_key = api_key or "not-needed"

    try: # Bloc principal pour la tentative de connexion et l'appel API
        client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key,
        )

        params = {"model": model_name, "messages": processed_messages, "stream": stream}
        if json_mode:
            # Pour la compatibilité avec OpenAI, on utilise response_format
            params["response_format"] = {"type": "json_object"}

        if tools:
            params["tools"] = tools
        if tool_choice:
            params["tool_choice"] = tool_choice

        response = client.chat.completions.create(**params)

        # Gérer la spécificité de certains backends (comme Ollama) qui peuvent renvoyer
        # une chaîne JSON au lieu d'un objet lorsque le mode JSON est activé et que le streaming est désactivé.
        if not stream and json_mode:
            content_to_parse = None
            try:
                # Vérifier si la réponse a le contenu attendu
                if response.choices and response.choices[0].message and response.choices[0].message.content:
                    content_to_parse = response.choices[0].message.content
                    # Si le contenu est une chaîne, on tente de l'analyser comme du JSON pour normaliser la réponse.
                    if isinstance(content_to_parse, str):
                        current_app.logger.debug("Tentative de normalisation de la réponse JSON du backend.")
                        response.choices[0].message.content = json.loads(content_to_parse)
            except (json.JSONDecodeError, IndexError, AttributeError) as e:
                current_app.logger.error(
                    f"Échec de la normalisation de la réponse JSON du backend. "
                    f"La réponse n'est peut-être pas un JSON valide ou a une structure inattendue. Erreur: {e}\n"
                    f"Contenu brut: {content_to_parse}"
                )
                # On ne lève pas d'exception, on retourne la réponse brute pour que l'appelant puisse la gérer.

        return response
    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        current_app.logger.warning(f"Le backend '{backend_name}' a échoué : {e}. Tentative de basculement (failover).")

        # --- LOGIQUE DE BASCULEMENT (FAILOVER) ---
        ha_strategy = config.get('high_availability_strategy')
        if ha_strategy != 'failover':
            # Si la stratégie n'est pas le failover, on ne fait rien et on relance l'erreur.
            raise e

        all_backends = config.get('llm_backends', [])
        
        # Trouver le prochain backend disponible qui n'a pas encore été essayé
        next_backend_to_try = None
        for backend in all_backends:
            if backend.get('name') not in tried_backends:
                next_backend_to_try = backend
                break
        
        if next_backend_to_try:
            next_backend_name = next_backend_to_try.get('name')
            current_app.logger.info(f"Basculement vers le prochain backend disponible : '{next_backend_name}'.")
            
            # Appel récursif avec le nouveau backend et la liste des backends déjà essayés
            return get_chat_completion(
                model_name=model_name, messages=messages, stream=stream, json_mode=json_mode,
                backend_name=next_backend_name, tools=tools, tool_choice=tool_choice,
                tried_backends=tried_backends # Passer l'ensemble mis à jour
            )
        else:
            # Si tous les backends ont été essayés et ont échoué
            current_app.logger.error("Tous les backends configurés ont échoué. Impossible de traiter la requête.")
            raise e # Relancer la dernière exception de connexion

    except openai.APIError as e:
        current_app.logger.error(f"Erreur d'API lors de l'appel à '{backend_type}': {e}")
        raise