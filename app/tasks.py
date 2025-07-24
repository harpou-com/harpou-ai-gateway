"""
Catalogue d'outils disponibles pour l'API et logique de décision LLM.
Ce module définit les tâches Celery asynchrones de l'application,
la logique de décision de l'IA et les outils associés.
"""
# 1. Imports
# Standard library
import json

# Third-party libraries
import requests
from celery import chain
from flask import current_app
from celery.utils.log import get_task_logger

# Local application imports
from .extensions import celery, socketio
from .llm_connector import get_chat_completion, get_llm_completion

# 2. Constantes et Configuration
logger = get_task_logger(__name__)

AVAILABLE_TOOLS = [
    {
        "name": "search_web",
        "description": (
            "Outil permettant d'effectuer des recherches sur internet afin d'obtenir des informations récentes "
            "(par exemple : météo, actualités, résultats sportifs, etc.)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "La requête de recherche à envoyer sur le web."
                }
            },
            "required": ["query"]
        }
    }
]

# 3. Fonctions de logique métier (Helpers)
def get_llm_decision(user_question):
    """
    Appelle le LLM pour déterminer si une question nécessite un outil ou une réponse directe.
    """
    logger.info(f"Demande de décision au LLM pour : {user_question!r}")

    system_prompt = f"""
Vous êtes un orchestrateur intelligent. Votre tâche est d'analyser la question de l'utilisateur et de décider de la meilleure action.
Actions possibles : `call_tool` ou `respond`.

Outils disponibles :
{json.dumps(AVAILABLE_TOOLS, indent=2)}

Répondez avec un objet JSON structuré comme suit :
- Pour un outil : {{"action": "call_tool", "tool_name": "search_web", "parameters": {{"query": "requête de recherche"}}}}
- Pour une réponse directe : {{"action": "respond", "message": "Votre réponse directe ici."}}
"""
    
    full_prompt = f"{system_prompt}\n\nQuestion utilisateur : \"{user_question}\"\n\nVotre réponse JSON :"

    try:
        # On appelle le LLM en mode JSON pour garantir une sortie structurée
        llm_response_str = get_llm_completion(full_prompt, json_mode=True)
        decision = json.loads(llm_response_str)
        logger.info(f"Décision du LLM reçue : {decision}")
        return decision
    except Exception as e:
        logger.error(f"Échec de l'obtention ou de l'analyse de la décision du LLM : {e}")
        # Réponse de secours en cas d'erreur
        return {"action": "respond", "message": "Je rencontre une difficulté pour traiter votre demande."}

# 4. Tâches Celery
@celery.task(bind=True)
def orchestrator_task(self, user_question, sid):
    """
    Tâche Celery qui orchestre la décision de l'IA et lance le flux de travail approprié.
    """
    logger.info(f"Démarrage pour SID {sid} avec la question: '{user_question}'")
    # Utilise la nouvelle fonction qui appelle le vrai LLM
    decision = get_llm_decision(user_question)
    logger.info(f"Décision IA pour SID {sid} : {decision}")

    if decision.get('action') == 'call_tool':
        tool_name = decision.get("tool_name")
        if tool_name == "search_web":
            query = decision.get("parameters", {}).get("query")
            if query:
                logger.info(f"Création d'une chaîne de tâches pour SID {sid}: search_web -> synthesis")
                # Crée une chaîne: le résultat de search_web_task est passé à synthesis_task
                workflow = chain(
                    search_web_task.s(query=query),
                    synthesis_task.s(original_question=user_question, sid=sid)
                )
                workflow.delay()
            else:
                logger.error(f"Paramètre 'query' manquant pour l'outil 'search_web' pour SID {sid}")
                # TODO: Notifier l'utilisateur de l'erreur
        else:
            logger.warning(f"Outil non reconnu '{tool_name}' demandé pour SID {sid}")
            # TODO: Notifier l'utilisateur de l'erreur
    else:
        # L'action est 'respond' ou une erreur de décision.
        # On envoie la réponse directement sans passer par la tâche de synthèse.
        final_answer = decision.get('message', "Je ne suis pas sûr de savoir comment répondre. Pourriez-vous reformuler ?")
        logger.info(f"Envoi de la réponse directe au client SID {sid}")
        
        # L'événement 'task_result' est écouté par le client HTML
        socketio.emit('task_result', {'status': 'final_answer', 'message': final_answer}, room=sid)

    return "Orchestration initiée."

@celery.task(bind=True)
def search_web_task(self, query):
    """
    Effectue une recherche web pour la requête donnée et retourne les résultats
    sous forme d'une chaîne de caractères formatée pour un LLM.

    Args:
        query (str): La requête de recherche à envoyer sur le web.

    Returns:
        str: Une chaîne de caractères contenant les résultats ou un message d'erreur.
    """
    logger.info(f"Début de la recherche pour : '{query}'")
    searxng_url = current_app.config.get('SEARXNG_BASE_URL')

    if not searxng_url:
        error_message = "L'URL de SearXNG n'est pas configurée (SEARXNG_BASE_URL)."
        logger.error(error_message)
        return error_message
    
    try:
        search_url = f"{searxng_url}/search?q={query}&format=json"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()  # Lève une exception pour les erreurs HTTP

        search_data = response.json()
        results = search_data.get("results", [])

        if not results:
            logger.warning("Aucun résultat trouvé.")
            return "Aucun résultat trouvé pour la recherche."

        # Formater les 5 premiers résultats pour le LLM
        context = ""
        for result in results[:5]:
            context += f"Titre: {result.get('title', 'N/A')}\n"
            context += f"Extrait: {result.get('content', 'N/A')}\n---\n"
        
        logger.info(f"Recherche terminée avec succès pour '{query}'.")
        return context

    except requests.exceptions.RequestException as e:
        error_message = f"Erreur de connexion à SearXNG : {e}"
        logger.error(f"{error_message}")
        return error_message
    except json.JSONDecodeError as e:
        error_message = f"Erreur de décodage de la réponse JSON de SearXNG : {e}"
        logger.error(f"{error_message}")
        return error_message

@celery.task(bind=True)
def synthesis_task(self, task_results, original_question, sid):
    """
    Tâche Celery qui utilise le LLM pour synthétiser une réponse finale et la notifie au client,
    avec un streaming jeton par jeton.
    """
    logger.info(f"Démarrage de la synthèse en streaming pour SID {sid} avec la question '{original_question}'")

    # 1. Préparer les messages pour le LLM au format chat
    system_prompt = "Vous êtes un assistant de synthèse. Votre rôle est de fournir une réponse concise et utile à la question de l'utilisateur en vous basant sur les informations de recherche fournies."
    user_prompt = f"""
Informations de recherche :
---
{task_results}
---
À partir de ces informations, répondez à la question suivante : "{original_question}"
"""
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    final_answer_parts = []
    try:
        # 2. Déterminer le modèle à utiliser
        primary_backend_name = current_app.config.get('primary_backend_name')
        if not primary_backend_name:
            raise ValueError("Aucun backend LLM primaire n'est configuré.")

        backends = current_app.config.get('llm_backends', [])
        backend_config = next((b for b in backends if b.get('name') == primary_backend_name), None)

        if not backend_config:
            raise ValueError(f"Configuration du backend primaire '{primary_backend_name}' non trouvée.")

        model_name = backend_config.get('default_model')
        if not model_name:
            raise ValueError(f"Aucun modèle par défaut configuré pour le backend '{primary_backend_name}'.")

        # 3. Appeler get_chat_completion en mode streaming
        logger.info(f"Appel de get_chat_completion en mode stream avec le modèle '{model_name}'.")
        stream = get_chat_completion(
            model_name=model_name,
            messages=messages,
            stream=True, # Activer le streaming
            backend_name=primary_backend_name
        )
        
        # 4. Itérer sur le flux et envoyer les jetons via WebSocket
        for chunk in stream:
            token = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
            if token:
                socketio.emit('task_result', {'status': 'streaming_update', 'token': token}, room=sid)
                final_answer_parts.append(token)

        final_answer = "".join(final_answer_parts)
        if not final_answer:
            raise ValueError("La réponse du LLM en streaming était vide.")
        
        logger.info(f"Réponse finale streamée générée par le LLM pour SID {sid}: '{final_answer[:100]}...'")
        
        # 5. Envoyer un message final pour indiquer la fin du flux
        socketio.emit('task_result', {'status': 'final_answer', 'message': final_answer}, room=sid)

    except Exception as e:
        logger.error(f"Échec de la synthèse par le LLM en streaming : {e}", exc_info=True)
        final_answer = f"J'ai trouvé des informations, mais j'ai eu du mal à les résumer. Voici les données brutes : {task_results}"
        socketio.emit('task_result', {'status': 'error', 'message': final_answer}, room=sid)
    
    return final_answer