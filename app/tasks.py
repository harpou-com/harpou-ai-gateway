"""
Catalogue d'outils disponibles pour l'API et logique de décision LLM.
Ce module définit les tâches Celery asynchrones de l'application,
la logique de décision de l'IA et les outils associés.
"""
# 1. Imports
# Standard library
import json
from bs4 import BeautifulSoup
import copy
import uuid
import time
from typing import Optional, List, Dict, Any

# Third-party libraries
import requests
from celery import chain
from flask import Response, current_app, jsonify, request
from celery.utils.log import get_task_logger

# Local application imports
from .extensions import celery, socketio
from .llm_connector import _execute_llm_request, get_llm_completion
from .services import refresh_and_cache_models

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
    }},
    {
    "name": "read_webpage",
    "description": "Permet de lire et d'extraire le contenu textuel principal d'une page web à partir de son URL. Utile pour obtenir des détails, résumer un article, ou analyser le contenu d'un lien spécifique.",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "L'URL complète de la page web à lire."
            }
        },
            "required": ["url"]
        }
    }
]

# 3. Fonctions de logique métier (Helpers)
def get_llm_decision(user_question: str, model_name: str):
    """
    Appelle le LLM pour déterminer si une question nécessite un outil ou une réponse directe.
    """
    logger.info(f"Demande de décision au LLM pour : {user_question!r}")

    system_prompt = f"""
Vous êtes un orchestrateur intelligent. Votre tâche est d'analyser la question de l'utilisateur et de décider de la meilleure action.
Actions possibles : `call_tool` ou `respond_directly`.

Outils disponibles :
{json.dumps(AVAILABLE_TOOLS, indent=2)}

Répondez avec un objet JSON structuré comme suit :
- Pour un outil : {{"action": "call_tool", "tool_name": "search_web", "parameters": {{"query": "requête de recherche"}}}}
- Pour une réponse directe : {{"action": "respond_directly"}}
"""
    
    full_prompt = f"{system_prompt}\n\nQuestion utilisateur : \"{user_question}\"\n\nVotre réponse JSON :"

    try:
        # On appelle le LLM en mode JSON pour garantir une sortie structurée
        llm_response = get_llm_completion(full_prompt, model_name=model_name, json_mode=True)
        
        if isinstance(llm_response, str):
            decision = json.loads(llm_response)
        elif isinstance(llm_response, dict):
            decision = llm_response
        else:
            raise TypeError(f"Type de réponse inattendu du LLM : {type(llm_response)}")
        logger.info(f"Décision du LLM reçue : {decision}")
        return decision
    except Exception as e:
        logger.error(f"Échec de l'obtention ou de l'analyse de la décision du LLM : {e}", exc_info=True)
        # Il est crucial de relancer l'exception pour que la tâche Celery soit marquée comme FAILED.
        raise

def _format_results_as_context(results: List[Dict[str, Any]]) -> str:
    """Formate une liste de résultats de recherche en une chaîne de contexte pour le LLM."""
    context = ""
    # Limiter aux 5 premiers résultats pour ne pas surcharger le contexte
    for result in results[:5]:
        context += f"Titre: {result.get('title', 'N/A')}\n"
        context += f"URL: {result.get('url', 'N/A')}\n"
        context += f"Extrait: {result.get('content', 'N/A')}\n---\n"
    return context

# 4. Tâches Celery
@celery.task(name="app.tasks.refresh_models_cache_task")
def refresh_models_cache_task():
    """
    Tâche Celery périodique pour rafraîchir le cache des modèles.
    """
    logger.info("Lancement de la tâche de rafraîchissement du cache des modèles.")
    try:
        refresh_and_cache_models()
        logger.info("Tâche de rafraîchissement du cache des modèles terminée avec succès.")
    except Exception as e:
        logger.error(f"Erreur lors de la tâche de rafraîchissement du cache des modèles: {e}", exc_info=True)

@celery.task(bind=True)
def orchestrator_task(self, messages: List[Dict[str, Any]], sid: str, model_name: str):
    """
    Tâche Celery qui orchestre la décision de l'IA et lance le flux de travail approprié.
    Le résultat de cette tâche est la réponse finale, la rendant compatible avec le polling HTTP.
    """
    try:
        # Extraire la question la plus récente de l'historique des messages pour la prise de décision.
        user_question = ""
        if messages and isinstance(messages, list) and messages[-1].get("role") == "user":
            user_question = messages[-1].get("content", "")

        if not user_question or not isinstance(user_question, str):
            logger.error(f"Impossible d'extraire une question utilisateur valide des messages pour SID {sid}.")
            # Fallback LLM pour message utilisateur en cas d'erreur
            admin_email = current_app.config.get("SYSTEM_ADMIN_EMAIL", "admin@harpou.ai")
            fallback_prompt = (
                "Je rencontre une difficulté technique pour traiter votre demande. "
                f"Veuillez contacter l'administrateur système à l'adresse {admin_email}."
            )
            try:
                # On tente de demander au LLM de reformuler le message d'excuse
                llm_fallback = get_llm_completion(
                    f"Formule un message d'excuse poli à transmettre à l'utilisateur en cas de panne technique. "
                    f"Indique qu'il peut contacter l'administrateur à {admin_email}.",
                    model_name=model_name,
                    json_mode=False
                )
                return llm_fallback if llm_fallback else fallback_prompt
            except Exception as e:
                logger.error(f"Erreur lors de la génération du fallback LLM : {e}")
                return fallback_prompt

        # 2. Prise de décision : Appeler le LLM pour savoir s'il faut utiliser un outil ou répondre directement
        decision = get_llm_decision(user_question, model_name=model_name)

        # 3. Exécution de l'action décidée
        tool_name = decision.get("tool_name")
        logger.info(f"SID {sid}: Action décidée - Outil: {tool_name}, Décision: {decision}")

        tool_results = ""
        synthesis_messages = copy.deepcopy(messages)
        if decision.get("action") == "call_tool" and tool_name in ["search_web", "read_webpage"]:
            try:
                if tool_name == "search_web":
                    query = decision.get("parameters", {}).get("query", "")
                    logger.info(f"Orchestrateur : appel de l'outil 'search_web' avec la requête : {query}")
                    search_results = search_web_task(query=query)
                    if isinstance(search_results, list) and search_results:
                        top_result_url = search_results[0].get('url')
                        logger.info(f"Orchestrateur : appel de 'read_webpage' sur le premier résultat : {top_result_url}")
                        scraped_content = read_webpage_task(url=top_result_url)
                        final_context = f"Contenu détaillé de la page principale ({top_result_url}):\n{scraped_content}\n\n"
                        final_context += "--- AUTRES RÉSULTATS DE RECHERCHE ---\n"
                        final_context += _format_results_as_context(search_results[1:5])
                        tool_results = final_context
                    else:
                        tool_results = "La recherche n'a retourné aucun résultat."
                elif tool_name == "read_webpage":
                    url = decision.get("parameters", {}).get("url", "")
                    logger.info(f"Orchestrateur : appel direct de 'read_webpage' sur l'URL : {url}")
                    tool_results = read_webpage_task(url=url)
                else:
                    logger.warning(f"Outil non reconnu '{tool_name}' demandé pour SID {sid}")
                    tool_results = f"Erreur: L'outil '{tool_name}' n'est pas reconnu."
            except Exception as e:
                logger.error(f"Erreur lors de l'exécution de l'outil '{tool_name}' pour SID {sid}: {e}", exc_info=True)
                tool_results = f"Erreur lors de l'exécution de l'outil : {e}"

        # --- Étape de Synthèse Finale ---
        logger.info(f"Début de la synthèse finale pour SID {sid}.")

        # Préparer les messages pour le LLM de synthèse en injectant le contexte si nécessaire
        if tool_results:
            system_prompt = f"""Vous êtes un assistant de synthèse. Utilisez les informations de recherche suivantes pour répondre à la dernière question de l'utilisateur.
Citez vos sources en utilisant les URL fournies pour chaque information que vous utilisez, en format Markdown comme ceci : [Texte du lien](URL).
Ne mentionnez que les liens pertinents pour la réponse.

Informations de recherche:\n---\n{tool_results}\n---"""
            if synthesis_messages and synthesis_messages[0].get("role") == "system":
                synthesis_messages[0]["content"] = system_prompt
            else:
                synthesis_messages.insert(0, {"role": "system", "content": system_prompt})
        elif not synthesis_messages or synthesis_messages[0].get("role") != "system":
            system_prompt = "Vous êtes un assistant IA généraliste et serviable."
            synthesis_messages.insert(0, {"role": "system", "content": system_prompt})

        # La valeur retournée ici est le résultat de la tâche Celery,
        # qui sera récupéré par l'endpoint de polling HTTP.
        try:
            logger.info(f"Appel final au LLM pour synthèse pour SID {sid}.")
            response_obj = _execute_llm_request(
                model_name=model_name,
                messages=synthesis_messages,
                stream=False
            )
            final_answer = response_obj.choices[0].message.content
            logger.info(f"Réponse finale synthétisée pour SID {sid}: '{final_answer[:100]}...'")
            return final_answer
        except Exception as e:
            logger.error(f"Échec de la synthèse finale pour SID {sid}: {e}", exc_info=True)
            admin_email = current_app.config.get("SYSTEM_ADMIN_EMAIL", "admin@harpou.ai")
            fallback_msg = (
                "Je rencontre une difficulté technique pour générer la réponse finale. "
                f"Veuillez contacter l'administrateur système à l'adresse {admin_email}."
            )
            try:
                llm_fallback = get_llm_completion(
                    f"Formule un message d'excuse poli à transmettre à l'utilisateur en cas de panne technique. "
                    f"Indique qu'il peut contacter l'administrateur à {admin_email}.",
                    model_name=model_name,
                    json_mode=False
                )
                return llm_fallback if llm_fallback else fallback_msg
            except Exception as e2:
                logger.error(f"Erreur lors de la génération du fallback LLM synthèse : {e2}")
                return fallback_msg
    except Exception as e:
        logger.error(f"Erreur inattendue dans orchestrator_task pour SID {sid}: {e}", exc_info=True)
        return "Désolé, une erreur est survenue lors du traitement de votre demande."

@celery.task(bind=True)
def search_web_task(self, query):
    """
    Effectue une recherche web pour la requête donnée et retourne les résultats
    sous forme d'une chaîne de caractères formatée pour un LLM.

Args:
    query (str): La requête de recherche à envoyer sur le web.

Returns:
    list: Une liste de dictionnaires contenant les résultats, ou une liste vide.
    """
    logger.info(f"Début de la recherche pour : '{query}'")
    searxng_url = current_app.config.get('SEARXNG_BASE_URL')

    if not searxng_url:
        error_message = "L'URL de SearXNG n'est pas configurée (SEARXNG_BASE_URL)."
        logger.error(error_message)
        return []
    
    try:
        search_url = f"{searxng_url}/search?q={query}&format=json"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()  # Lève une exception pour les erreurs HTTP

        return response.json().get("results", [])

    except requests.exceptions.RequestException as e:
        error_message = f"Erreur de connexion à SearXNG : {e}"
        logger.error(f"{error_message}")
        return []
    except json.JSONDecodeError as e:
        error_message = f"Erreur de décodage de la réponse JSON de SearXNG : {e}"
        logger.error(f"{error_message}")
        return []

@celery.task(bind=True)
def read_webpage_task(self, url: str) -> str:
    """
    Scrape le contenu textuel d'une page web à partir de son URL.

    Args:
        url (str): L'URL de la page à lire.

    Returns:
        str: Le contenu textuel nettoyé de la page, ou un message d'erreur.
    """
    if not url or not url.startswith(('http://', 'https://')):
        return f"Erreur: URL invalide fournie : '{url}'"

    logger.info(f"Début du scraping pour l'URL : {url}")
    try:
        headers = {'User-Agent': 'Harpou-AI-Gateway-Scraper/1.0'}
        page_response = requests.get(url, timeout=15, headers=headers)
        page_response.raise_for_status()

        # Utiliser BeautifulSoup pour parser le HTML et extraire le texte
        soup = BeautifulSoup(page_response.content, 'html.parser')

        # Supprimer les balises de script et de style qui n'apportent pas de contexte
        for script_or_style in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script_or_style.decompose()

        # Obtenir le texte et le nettoyer pour une meilleure lisibilité
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        full_text = '\n'.join(chunk for chunk in chunks if chunk)

        # Limiter la taille pour ne pas surcharger le contexte du LLM (8000 caractères)
        scraped_content = full_text[:8000]
        logger.info(f"Scraping de {url} terminé avec succès.")
        return scraped_content

    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la lecture de l'URL {url}: {e}"
        logger.error(error_message)
        return error_message

@celery.task(bind=True)
def synthesis_task(self, task_results: Optional[str], messages: List[Dict[str, Any]], sid: str, model_name: str):
    """
    Tâche Celery qui utilise le LLM pour synthétiser une réponse finale et la notifie au client,
    avec un streaming jeton par jeton.
    Gère deux cas : la synthèse à partir de résultats d'outils et la réponse directe,
    tout en préservant l'historique de la conversation.
    """
    logger.info(f"Démarrage de la synthèse en streaming pour SID {sid}.")

    # On travaille sur une copie pour ne pas modifier l'historique original
    final_llm_messages = copy.deepcopy(messages)

    # 1. Préparer les messages pour le LLM en injectant le contexte si nécessaire
    if task_results:
        # Cas 1: Un outil a été utilisé. On injecte les résultats dans un prompt système.
        system_prompt = f"""Vous êtes un assistant de synthèse. Utilisez les informations de recherche suivantes pour répondre à la dernière question de l'utilisateur dans le contexte de la conversation.
\nInformations de recherche:\n---\n{task_results}\n---"""
        
        # Remplacer ou insérer le prompt système
        if final_llm_messages and final_llm_messages[0].get("role") == "system":
            final_llm_messages[0]["content"] = system_prompt
        else:
            final_llm_messages.insert(0, {"role": "system", "content": system_prompt})
    else:
        # Cas 2: Réponse directe. On s'assure qu'un prompt système générique existe.
        logger.info(f"Synthèse en mode réponse directe pour SID {sid}.")
        if not final_llm_messages or final_llm_messages[0].get("role") != "system":
            system_prompt = "Vous êtes un assistant IA généraliste et serviable."
            final_llm_messages.insert(0, {"role": "system", "content": system_prompt})

    final_answer_parts = []
    try:
        # 2. Appeler _execute_llm_request en mode streaming avec le modèle spécifié
        logger.info(f"Appel de _execute_llm_request en mode stream avec le modèle '{model_name}'.")
        stream = _execute_llm_request(
            model_name=model_name,
            messages=final_llm_messages, # Utiliser les messages préparés
            stream=True, # Activer le streaming
        )
        
        # 3. Itérer sur le flux et envoyer les jetons via WebSocket
        for chunk in stream:
            token = chunk.choices[0].delta.content if chunk.choices and chunk.choices[0].delta else None
            if token:
                socketio.emit('task_result', {'status': 'streaming_update', 'token': token}, room=sid)
                final_answer_parts.append(token)

        final_answer = "".join(final_answer_parts)
        if not final_answer:
            raise ValueError("La réponse du LLM en streaming était vide.")
        
        logger.info(f"Réponse finale streamée générée par le LLM pour SID {sid}: '{final_answer[:100]}...'")
        
        # 4. Envoyer un message final pour indiquer la fin du flux
        socketio.emit('task_result', {'status': 'final_answer', 'message': final_answer}, room=sid)

    except Exception as e:
        logger.error(f"Échec de la synthèse par le LLM en streaming : {e}", exc_info=True)
        admin_email = current_app.config.get("SYSTEM_ADMIN_EMAIL", "admin@harpou.ai")
        error_msg = (
            "Je rencontre une difficulté technique pour générer la réponse finale. "
            f"Veuillez contacter l'administrateur système à l'adresse {admin_email}."
        )
        try:
            llm_fallback = get_llm_completion(
                f"Formule un message d'excuse poli à transmettre à l'utilisateur en cas de panne technique. "
                f"Indique qu'il peut contacter l'administrateur à {admin_email}.",
                model_name=model_name,
                json_mode=False
            )
            socketio.emit('task_result', {'status': 'error', 'message': llm_fallback}, room=sid)
            return llm_fallback if llm_fallback else error_msg
        except Exception as e2:
            logger.error(f"Erreur lors de la génération du fallback LLM synthèse streaming : {e2}")
            socketio.emit('task_result', {'status': 'error', 'message': error_msg}, room=sid)
            return error_msg
    return final_answer