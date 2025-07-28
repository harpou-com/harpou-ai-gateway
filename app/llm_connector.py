# app/llm_connector.py
import openai
import json
import base64
import requests
import mimetypes
import copy
import time
from typing import Dict, Optional, List, Any, Iterator
import uuid

# Third-party libraries
from flask import current_app
from openai.types.chat import ChatCompletion
from openai.types.chat.chat_completion import Choice, ChatCompletionMessage

def _get_backend_config(backend_name: str) -> Optional[Dict[str, Any]]:
    """
    Récupère la configuration d'un backend spécifique par son nom.
    """
    backends: List[Dict[str, Any]] = current_app.config.get('llm_backends', [])
    for backend in backends:
        if backend.get('name') == backend_name:
            return backend
    return None

def _create_openai_client(backend_config: Dict[str, Any]) -> openai.OpenAI:
    """
    Crée et configure un client OpenAI basé sur la configuration du backend.
    Gère la normalisation de l'URL pour Ollama et les clés API factices.
    """
    backend_name = backend_config.get('name')
    backend_type = backend_config.get('type')
    base_url = backend_config.get('base_url')
    api_key = backend_config.get('api_key')

    if not base_url:
        raise ValueError(f"URL de base non configurée pour le backend '{backend_name}'.")

    # Assurer la compatibilité avec l'API OpenAI d'Ollama qui se trouve sur /v1
    if 'ollama' in str(backend_type) and not base_url.endswith('/v1'):
        base_url = f"{base_url.rstrip('/')}/v1"

    # Le client OpenAI v1+ requiert une clé API, même si le backend ne l'utilise pas.
    # On fournit une valeur factice si aucune n'est définie.
    if api_key is None:
        api_key = "NA"

    # Récupérer le timeout : priorité au backend, puis au global, puis au défaut.
    default_timeout = current_app.config.get('LLM_BACKEND_TIMEOUT', 300.0)
    backend_timeout = backend_config.get('timeout', default_timeout)
    current_app.logger.debug(f"Configuration du client OpenAI pour '{backend_name}' avec un timeout de {backend_timeout}s.")

    return openai.OpenAI(
        base_url=base_url,
        api_key=api_key,
        timeout=float(backend_timeout) # S'assurer que la valeur est un float
    )

# --- Nouvelle fonction utilitaire pour l'encodage d'images ---
def _encode_image_url(url: str) -> Optional[str]:
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

def list_models_from_backend(backend_config: Dict[str, Any]) -> List[Any]:
    """
    Interroge un backend pour obtenir la liste des modèles disponibles.
    Gère les backends de type 'openai' et 'ollama' via leur API compatible OpenAI.

    Args:
        backend_config (dict): La configuration du backend à interroger.

    Returns:
        list: Une liste d'objets de modèle (compatibles Pydantic/OpenAI) ou une liste vide en cas d'erreur.
    """
    backend_name = backend_config.get('name')
    
    try:
        client = _create_openai_client(backend_config)
        models_response = client.models.list()
        model_list = models_response.data
        current_app.logger.info(f"{len(model_list)} modèles trouvés pour le backend '{backend_name}'.")
        return model_list

    except (openai.APIConnectionError, openai.APITimeoutError) as e:
        current_app.logger.warning(f"Impossible de joindre le backend '{backend_name}': {e}")
    except openai.APIStatusError as e:
        current_app.logger.error(f"Erreur API du backend '{backend_name}'. Statut: {e.status_code}, Réponse: {e.response.text}")
    except ValueError as e:
        current_app.logger.error(f"Erreur de configuration pour le backend '{backend_name}': {e}")
    except Exception as e:
        current_app.logger.error(f"Erreur inattendue pour '{backend_name}': {e}", exc_info=True)

    return []

# --- Fonction principale du connecteur ---

def get_llm_completion(prompt: str, model_name: str, json_mode: bool = False) -> str:
    """
    Wrapper simple pour get_chat_completion pour les cas d'utilisation non-chat.
    Appelle le LLM spécifié pour obtenir une complétion.
    """
    messages = [{"role": "user", "content": prompt}]

    # La logique de routage est entièrement gérée par get_chat_completion
    response = _execute_llm_request(
        model_name=model_name,
        messages=messages,
        stream=False,
        json_mode=json_mode
    )

    if response and response.choices and response.choices[0].message and response.choices[0].message.content:
        return response.choices[0].message.content
    return ""

def get_chat_completion(
    model_name: str,
    messages: List[Dict[str, Any]],
    stream: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> ChatCompletion:
    """
    Point d'entrée unifié pour toutes les requêtes de chat conformes à l'API OpenAI.
    Lance le pipeline de l'agent (orchestration, outils, synthèse) et retourne
    une réponse synchrone compatible avec l'API OpenAI.

    Note: Le streaming n'est pas supporté via ce chemin car le pipeline de l'agent
    communique via WebSockets, ce qui est incompatible avec une réponse HTTP streamée.
    """
    # Importation locale pour éviter une dépendance circulaire (llm_connector -> tasks -> llm_connector)
    from app import tasks

    if stream:
        current_app.logger.warning(
            "Le streaming n'est pas supporté pour les appels API qui passent par le pipeline de l'agent. "
            "La requête sera traitée de manière synchrone."
        )

    # Générer un ID de session unique pour cette transaction stateless.
    sid = str(uuid.uuid4())
    current_app.logger.info(f"Lancement du pipeline de l'agent pour la requête API (SID: {sid}).")

    # Lancer la tâche d'orchestration et attendre son résultat final (appel bloquant).
    # On passe la liste complète des messages pour préserver l'historique de la conversation.
    async_result = tasks.orchestrator_task.delay(messages=messages, sid=sid, model_name=model_name)
    final_answer_str = async_result.get(propagate=True)

    # Construire un objet de réponse ChatCompletion standard.
    return ChatCompletion(
        id=f"chatcmpl-{uuid.uuid4()}",
        choices=[Choice(
            index=0,
            message=ChatCompletionMessage(role="assistant", content=final_answer_str),
            finish_reason="stop"
        )],
        created=int(time.time()),
        model=model_name,
        object="chat.completion",
    )

def _execute_llm_request(
    model_name: str, 
    messages: List[Dict[str, Any]], 
    stream: bool = False, 
    json_mode: bool = False, 
    backend_name: Optional[str] = None, 
    tools: Optional[List[Dict[str, Any]]] = None, 
    tool_choice: Optional[Any] = None, 
    tried_backends: Optional[set] = None
) -> Optional[Iterator[Any]]:
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
        Un objet de complétion ou un itérateur
        de chunks si stream=True.

    Raises:
        ValueError: Si la configuration du backend est manquante ou non supportée.
        openai.APIError: Si l'appel à l'API échoue.
    """
    config = current_app.config
    
    # Initialiser l'ensemble des backends essayés pour le failover
    if tried_backends is None:
        tried_backends = set()
    
    # 1. Déterminer le backend et le nom du modèle à utiliser (logique de routage centralisée)
    final_backend_name = backend_name
    final_model_name = model_name

    if '/' in model_name:
        # Le nom du modèle contient un routage explicite (ex: "default/llama3")
        # Cela a la priorité sur le paramètre `backend_name`.
        backend_from_model, model_id_part = model_name.split('/', 1)
        final_backend_name = backend_from_model
        final_model_name = model_id_part
        current_app.logger.debug(f"Routage explicite détecté dans le nom du modèle. Backend: '{final_backend_name}', Modèle: '{final_model_name}'.")

    if not final_backend_name:
        # Si aucun backend n'a été déterminé (ni via le nom du modèle, ni en paramètre),
        # on utilise le backend primaire de la configuration.
        final_backend_name = config.get('primary_backend_name')
        if not final_backend_name:
            raise ValueError("Aucun backend LLM n'a pu être déterminé. Spécifiez-le dans le nom du modèle (ex: 'backend/model') ou configurez un backend primaire.")

    # Marquer ce backend comme "essayé" pour la logique de failover
    tried_backends.add(final_backend_name)

    # 2. Récupérer la configuration du backend
    backend_config = _get_backend_config(final_backend_name)
    if not backend_config:
        # Si le backend spécifié n'existe pas, on ne peut pas continuer.
        # C'est une erreur de configuration ou une mauvaise requête.
        raise ValueError(f"Backend '{final_backend_name}' non trouvé dans la configuration.")

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

    try: # Bloc principal pour la tentative de connexion et l'appel API
        client = _create_openai_client(backend_config)

        # IMPORTANT: Utiliser le nom du modèle nettoyé (final_model_name) pour l'appel API.
        current_app.logger.info(f"Appel au backend '{final_backend_name}' avec le modèle '{final_model_name}'.")
        params = {"model": final_model_name, "messages": processed_messages, "stream": stream}

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
        current_app.logger.warning(f"Le backend '{final_backend_name}' a échoué : {e}. Tentative de basculement (failover).")

        # --- LOGIQUE DE BASCULEMENT (FAILOVER) ---
        ha_strategy = config.get('high_availability_strategy')
        if ha_strategy != 'failover':
            # Si la stratégie n'est pas le failover, on ne fait rien et on relance l'erreur.
            raise e

        all_backends = config.get('llm_backends', [])
        
        next_backend_to_try = next((b for b in all_backends if b.get('name') not in tried_backends), None)
        
        if next_backend_to_try:
            next_backend_name = next_backend_to_try.get('name')
            current_app.logger.info(f"Basculement vers le prochain backend disponible : '{next_backend_name}'.")
            
            # Appel récursif avec le nouveau backend et la liste des backends déjà essayés
            return _execute_llm_request( # Correction: appel récursif à soi-même pour le failover
                model_name=model_name, messages=messages, stream=stream, json_mode=json_mode,
                backend_name=next_backend_name, tools=tools, tool_choice=tool_choice,
                tried_backends=tried_backends
            )
        else:
            # Si tous les backends ont été essayés et ont échoué
            current_app.logger.error("Tous les backends configurés ont échoué. Impossible de traiter la requête.")
            raise e # Relancer la dernière exception de connexion

    except openai.APIError as e:
        current_app.logger.error(f"Erreur d'API lors de l'appel à '{backend_config.get('type')}': {e}")
        raise