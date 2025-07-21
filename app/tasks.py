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
from celery.utils.log import get_task_logger

# Local application imports
from .extensions import celery, socketio

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
SEARXNG_BASE_URL = "https://searxng.harpou.com"

# 3. Fonctions de logique métier (Helpers)
def decide_llm_action(user_question):
    """
    Simule la décision d'un LLM pour déterminer si une question utilisateur nécessite l'appel d'un outil
    (par exemple, une recherche web) ou une réponse directe.
    """
    logger.info(f"Question reçue pour décision : {user_question!r}")
    keywords = ["météo", "actualités", "qui est", "nouveautés", "recherche"]
    if any(kw.lower() in user_question.lower() for kw in keywords):
        decision = {
            "action": "call_tool",
            "tool_name": "search_web",
            "parameters": {"query": user_question}
        }
        logger.info(f"Décision : appel de l'outil 'search_web' avec paramètres {decision['parameters']}")
        return decision
    else:
        decision = {
            "action": "respond",
            "message": f"Je n'ai pas besoin d'outils pour répondre à cela. Voici une réponse directe à '{user_question}'."
        }
        logger.info("Décision : réponse directe.")
        return decision

# 4. Tâches Celery
@celery.task(bind=True)
def orchestrator_task(self, user_question, sid):
    """
    Tâche Celery qui orchestre la décision de l'IA et lance le flux de travail approprié.
    """
    logger.info(f"Démarrage pour SID {sid} avec la question: '{user_question}'")
    decision = decide_llm_action(user_question)
    logger.info(f"Décision IA pour SID {sid} : {decision}")

    if decision['action'] == 'call_tool':
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
        # Réponse directe, on appelle directement la synthèse
        logger.info(f"Appel direct de synthesis_task pour une réponse directe pour SID {sid}")
        synthesis_task.delay(
            task_results=decision.get('message', '...'), 
            original_question=user_question, 
            sid=sid
        )

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
    
    try:
        search_url = f"{SEARXNG_BASE_URL}/search?q={query}&format=json"
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
    Tâche Celery qui synthétise une réponse finale et la notifie au client.
    """
    logger.info(f"Démarrage de la synthèse pour SID {sid}")
    final_answer = f"Basé sur ma recherche concernant '{original_question}', voici un résumé : {task_results}"
    logger.info(f"Réponse finale générée pour SID {sid}")
    
    # Envoi du message via WebSocket
    logger.info(f"Envoi de la réponse finale au client SID {sid}")
    # L'événement 'task_result' est écouté par le client HTML
    socketio.emit('task_result', {'status': 'final_answer', 'message': final_answer}, room=sid)
    
    return final_answer