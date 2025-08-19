import logging
import json
import os
import copy
from typing import Optional, List, Dict, Any
import urllib.parse
import requests
from bs4 import BeautifulSoup
from flask import current_app
from eventlet.greenpool import GreenPool
from app.extensions import socketio, celery
from app.llm_connector import get_llm_completion, _execute_llm_request, _get_backend_config
from app.services import refresh_and_cache_models 

# Configuration du logger
logger = logging.getLogger(__name__)

def get_llm_decision(user_question: str, model_name: str):
    """
    Appelle le LLM pour déterminer si une question nécessite un outil ou une réponse directe,
    en utilisant la liste d'outils chargée depuis la configuration de l'application.
    """
    logger.info(f"Demande de décision au LLM pour : {user_question!r}")
    available_tools = current_app.config.get('AVAILABLE_TOOLS', [])

    # Générer dynamiquement les exemples de sortie JSON pour chaque outil
    tool_examples = []
    for tool in available_tools:
        tool_name = tool.get("name")
        params = tool.get("parameters", {}).get("properties", {})
        example_params = {p_name: f"valeur pour {p_name}" for p_name in params}
        example_json = {"action": "call_tool", "tool_name": tool_name, "parameters": example_params}
        tool_examples.append(f"- Pour utiliser l'outil '{tool_name}': {json.dumps(example_json)}")

    tool_examples.append('- Pour une réponse directe : {"action": "respond_directly"}')
    examples_str = "\n".join(tool_examples)

    system_prompt = f"""
Vous êtes un orchestrateur intelligent. Votre unique tâche est d'analyser la question de l'utilisateur fournie ci-dessous et de décider de la meilleure action à entreprendre.
Ne tenez pas compte d'un éventuel historique de conversation, basez votre décision uniquement sur la question explicite.
Actions possibles : `call_tool` ou `respond_directly`.

Outils disponibles :
{json.dumps(available_tools, indent=2)}

Règle impérative : Vous DEVEZ choisir un nom d'outil EXACTEMENT comme il apparaît dans la liste "Outils disponibles". N'inventez PAS de nouveaux noms d'outils. Si aucun outil ne correspond parfaitement, choisissez le plus pertinent ou répondez directement.

Répondez avec un objet JSON structuré comme l'un des exemples suivants :
{examples_str}
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

def _execute_tool(tool_name: str, parameters: dict, user_question: str) -> str:
    """
    Exécute un outil en fonction de sa configuration (type, détails d'exécution).
    """
    logger.info(f"Tentative d'exécution de l'outil '{tool_name}' avec les paramètres : {parameters}")

    # 1. Retrouver la configuration complète de l'outil
    available_tools = current_app.config.get('AVAILABLE_TOOLS', [])
    tool_config = next((tool for tool in available_tools if tool.get('name') == tool_name), None)

    if not tool_config:
        error_msg = f"Erreur: La configuration pour l'outil '{tool_name}' est introuvable."
        logger.error(error_msg)
        return error_msg

    tool_type = tool_config.get("type")

    # 2. Exécuter l'outil en fonction de son type
    try:
        if tool_type == "internal_function":
            # Logique pour les fonctions internes (tâches Celery)
            if tool_name == "search_web":
                query = parameters.get("query", "")
                logger.info(f"Orchestrateur : appel de la fonction interne 'search_web' avec la requête : {query}")
                search_results = search_web_task(query=query)
                if isinstance(search_results, list) and search_results:
                    top_result_url = search_results[0].get('url')
                    logger.info(f"Orchestrateur : appel de 'read_webpage' sur le premier résultat : {top_result_url}")
                    scraped_content = read_webpage_task(url=top_result_url)
                    final_context = f"Contenu détaillé de la page principale ({top_result_url}):\n{scraped_content}\n\n"
                    final_context += "--- AUTRES RÉSULTATS DE RECHERCHE ---\n"
                    final_context += _format_results_as_context(search_results[1:5])
                    return final_context
                else:
                    return "La recherche n'a retourné aucun résultat."
            elif tool_name == "read_webpage":
                url = parameters.get("url", "")
                logger.info(f"Orchestrateur : appel direct de la fonction interne 'read_webpage' sur l'URL : {url}")
                return read_webpage_task(url=url)
            else:
                error_msg = f"Fonction interne non implémentée: '{tool_name}'"
                logger.warning(error_msg)
                return error_msg

        elif tool_type == "api_call":
            # Nouvelle logique pour les appels API
            details = tool_config.get("execution_details")
            if not details:
                return f"Erreur: 'execution_details' manquant pour l'outil API '{tool_name}'."

            method = details.get("method", "GET").upper()
            # Gère les secrets via les variables d'environnement (ex: $API_KEY)
            headers = {k: os.path.expandvars(str(v)) for k, v in details.get("headers", {}).items()}
            
            url_template = details.get("url_template", details.get("url", ""))
            if "url_template" in details:
                # URL-encode les paramètres pour gérer les espaces et caractères spéciaux de manière sécurisée.
                encoded_params = {k: urllib.parse.quote(str(v)) for k, v in parameters.items()}
                url = url_template.format(**encoded_params)
            else:
                url = details.get("url", "") # Fallback si aucun template n'est fourni

            logger.info(f"Appel API: {method} {url}")
            response = requests.request(method, url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.text

        elif tool_type == "web_scraper":
            logger.info(f"Exécution de l'outil de type 'web_scraper': '{tool_name}'")
            details = tool_config.get("execution_details")
            if not details or "base_url_template" not in details or "scrape_targets" not in details:
                return f"Erreur: 'execution_details' mal configuré pour l'outil scraper '{tool_name}'. Attendu: 'base_url_template' et 'scrape_targets'."

            encoded_params = {k: urllib.parse.quote(str(v)) for k, v in parameters.items()}
            base_url = details["base_url_template"].format(**encoded_params)
            targets = details.get("scrape_targets", [])

            pool = GreenPool()

            def scrape_target(target):
                target_name = target.get("name", "Cible sans nom")
                full_url = base_url + target.get("url_suffix", "")
                logger.info(f"Scraping de la cible '{target_name}' à l'URL : {full_url}")
                
                try:
                    headers = {'User-Agent': 'Harpou-AI-Gateway-Scraper/1.0'}
                    page_response = requests.get(full_url, timeout=20, headers=headers)
                    page_response.raise_for_status()
                    soup = BeautifulSoup(page_response.content, 'html.parser')
                    
                    target_data = [f"--- {target_name} ---"]
                    for item_to_scrape in target.get("selectors", []):
                        element = soup.select_one(item_to_scrape['selector'])
                        if element:
                            value = element.get_text(strip=True, separator=' ')
                            target_data.append(f"- {item_to_scrape['name']}: {value}")
                        else:
                            target_data.append(f"- {item_to_scrape['name']}: Non trouvé")
                    return "\n".join(target_data)
                except Exception as e:
                    logger.error(f"Échec du scraping pour la cible '{target_name}' ({full_url}): {e}")
                    return f"--- {target_name} ---\nErreur lors de la récupération des données."

            # Lancer les tâches de scraping en parallèle et collecter les résultats
            scraped_results = list(pool.imap(scrape_target, targets))
            scraped_results_str = "\n\n".join(scraped_results)

            # --- Logique d'enrichissement pour la météo ---
            # Si l'outil principal (le scraper) ne suffit pas, on lance une recherche web.
            if tool_name == "get_detailed_weather": # Ce nom doit correspondre à celui dans tools_config.json
                supplementary_context = ""
                # Mots-clés que MétéoMédia pourrait ne pas fournir de manière structurée
                keywords_to_check = ["insecte", "moustique", "pollen", "qualité de l'air", "uv", "humidex"]
                
                keywords_found = [kw for kw in keywords_to_check if kw in user_question.lower()]
                if keywords_found:
                    logger.info(f"La question météo contient des mots-clés spécifiques ({keywords_found}). Lancement d'une recherche web pour enrichir les données.")
                    
                    city = parameters.get("city", "la ville")
                    state = parameters.get("state", "")
                    search_terms = ", ".join(keywords_found)
                    supplementary_query = f"prévisions {search_terms} pour {city} {state}"
                    
                    search_results = search_web_task(query=supplementary_query)
                    if search_results:
                        supplementary_context = "\n\n--- Informations complémentaires (recherche web) ---\n"
                        supplementary_context += _format_results_as_context(search_results[:3]) # Limiter à 3 résultats pour la concision
                return f"{scraped_results_str}{supplementary_context}"
            return scraped_results_str

        else:
            error_msg = f"Erreur: Type d'outil non supporté '{tool_type}' pour l'outil '{tool_name}'."
            logger.error(error_msg)
            return error_msg

    except Exception as e:
        logger.error(f"Erreur lors de l'exécution de l'outil '{tool_name}': {e}", exc_info=True)
        return f"Erreur lors de l'exécution de l'outil : {e}"

def _format_results_as_context(results: List[Dict[str, Any]]) -> str:
    """Formate une liste de résultats de recherche en une chaîne de contexte pour le LLM."""
    context = ""
    # Limiter aux 5 premiers résultats pour ne pas surcharger le contexte
    for result in results[:5]:
        context += f"Titre: {result.get('title', 'N/A')}\n"
        context += f"URL: {result.get('url', 'N/A')}\n"
        context += f"Extrait: {result.get('content', 'N/A')}\n---\n"
    return context

@celery.task(name="app.tasks.orchestrator_task")
def orchestrator_task(sid: str, conversation: List[Dict[str, Any]], model_id: str, user_info: Optional[Dict[str, Any]] = None):
    """
    Tâche Celery qui orchestre la décision de l'IA et lance le flux de travail approprié.
    Le résultat de cette tâche est la réponse finale, la rendant compatible avec le polling HTTP.
    """
    try:
        # Déterminer le modèle à utiliser pour le routage.
        # Si ROUTING_BACKEND_NAME est défini, on utilise le modèle par défaut de ce backend.
        # Sinon, on se rabat sur le modèle choisi par l'utilisateur.
        routing_backend_name = current_app.config.get("ROUTING_BACKEND_NAME")
        routing_model_id = model_id  # Fallback par défaut sur le modèle de l'utilisateur

        if routing_backend_name:
            routing_backend_config = _get_backend_config(routing_backend_name)
            if routing_backend_config and routing_backend_config.get('default_model'):
                # On construit un ID de modèle qui inclut le backend pour un routage explicite.
                # Ex: "ollama_router/RoutingLLM/Mistral-7B-Instruct-v0.3:latest"
                # Cela garantit que le bon backend est appelé avec son modèle par défaut.
                default_model = routing_backend_config.get('default_model')
                routing_model_id = f"{routing_backend_name}/{default_model}"
                logger.info(f"Utilisation du backend de routage '{routing_backend_name}' avec le modèle '{default_model}'.")
            else:
                logger.warning(f"ROUTING_BACKEND_NAME '{routing_backend_name}' est configuré mais le backend ou son modèle par défaut est introuvable. Utilisation du modèle de l'utilisateur pour le routage.")
        else:
            logger.warning("ROUTING_BACKEND_NAME n'est pas configuré, utilisation du modèle de l'utilisateur pour le routage.")

        # Extraire la question la plus récente de l'historique des messages pour la prise de décision.
        user_question = ""
        if conversation and isinstance(conversation, list) and conversation[-1].get("role") == "user":
            user_question = conversation[-1].get("content", "")

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
                    model_name=model_id,
                    json_mode=False
                )
                return llm_fallback if llm_fallback else fallback_prompt
            except Exception as e:
                logger.error(f"Erreur lors de la génération du fallback LLM : {e}")
                return fallback_prompt

        # --- Étape de Décision ---
        # Les requêtes internes de Open WebUI pour les titres, tags, etc., commencent par "### Task:".
        # Celles-ci ne doivent pas passer par la logique d'outils mais être traitées directement.
        if user_question.strip().startswith("### Task:"):
            logger.info(f"Requête interne de l'UI détectée pour SID {sid}. Contournement de la logique d'outils.")
            # On force la décision à "répondre directement" pour sauter l'exécution d'outil.
            decision = {"action": "respond_directly"}
        else:
            # Pour les requêtes utilisateur standard, on appelle le LLM de routage.
            decision = get_llm_decision(user_question, model_name=routing_model_id)

        # --- Étape de Validation et Normalisation de la Décision ---
        # On ajoute une couche de validation pour se prémunir contre les "hallucinations"
        # du LLM de routage, qui peut parfois retourner des outils inexistants ou omettre des paramètres.
        if decision.get("action") == "call_tool":
            tool_name_from_llm = decision.get("tool_name") or decision.get("outil")
            # On vérifie si les paramètres sont présents, même s'ils sont vides.
            parameters_from_llm = decision.get("parameters") if "parameters" in decision else decision.get("paramètres")
            
            available_tools_names = {tool['name'] for tool in current_app.config.get('AVAILABLE_TOOLS', [])}

            # On vérifie que l'outil demandé existe ET que le champ des paramètres est bien présent.
            if tool_name_from_llm not in available_tools_names or parameters_from_llm is None:
                log_message = (
                    f"Le LLM de routage a fourni une décision invalide. "
                    f"Outil: '{tool_name_from_llm}', Paramètres: {parameters_from_llm}. "
                    f"Forçage de la réponse directe."
                )
                logger.warning(log_message)
                # On écrase la décision invalide du LLM.
                decision = {"action": "respond_directly"}
            else:
                # Normaliser les clés pour le reste du code au cas où le LLM a utilisé 'outil' ou 'paramètres'.
                decision['tool_name'] = tool_name_from_llm
                decision['parameters'] = parameters_from_llm

        # --- Étape d'Exécution de l'Action ---
        tool_name = decision.get("tool_name")
        parameters = decision.get("parameters", {})
        logger.info(f"SID {sid}: Action décidée - Outil: {tool_name}, Décision: {decision}")

        tool_results = ""
        synthesis_messages = copy.deepcopy(conversation)
        
        if decision.get("action") == "call_tool" and tool_name:
            try:
                tool_results = _execute_tool(tool_name, parameters, user_question=user_question)
                logger.debug(f"Résultat brut de l'outil '{tool_name}':\n---\n{tool_results}\n---")
            except Exception as e:
                logger.error(f"Erreur inattendue lors de l'appel à _execute_tool pour '{tool_name}' pour SID {sid}: {e}", exc_info=True)
                tool_results = f"Erreur critique lors de l'exécution de l'outil : {e}"

        # --- Étape de Synthèse Finale ---
        logger.info(f"Début de la synthèse finale pour SID {sid}.")

        # Préparer les messages pour le LLM de synthèse en injectant le contexte si nécessaire
        if tool_results:
            system_prompt = f"""Vous êtes un assistant de synthèse. Votre rôle est de répondre à la question de l'utilisateur EN VOUS BASANT UNIQUEMENT sur les "Informations de recherche" fournies ci-dessous.
Règle impérative : NE PAS inventer d'informations ou de valeurs qui ne sont pas présentes dans le contexte. Si une information demandée par l'utilisateur (par exemple, le risque d'insectes) n'est pas explicitement listée dans les "Informations de recherche", vous DEVEZ indiquer qu'elle n'a pas pu être trouvée.
Formatez la réponse de manière claire et lisible.

Informations de recherche:\n---\n{tool_results}\n---"""
            if synthesis_messages and synthesis_messages[0].get("role") == "system":
                synthesis_messages[0]["content"] = system_prompt
            else:
                synthesis_messages.insert(0, {"role": "system", "content": system_prompt})
        elif not synthesis_messages or synthesis_messages[0].get("role") != "system":
            # Injecter le persona de l'utilisateur s'il est défini
            if user_info and (persona := user_info.get("persona")):
                system_prompt = persona
                logger.info(f"Persona de l'utilisateur '{user_info.get('username')}' injecté dans le prompt.")
            else:
                system_prompt = "Vous êtes un assistant IA généraliste et serviable."
            synthesis_messages.insert(0, {"role": "system", "content": system_prompt})
        elif user_info and (persona := user_info.get("persona")):
            synthesis_messages[0]["content"] = f"{persona}\n\n{synthesis_messages[0]['content']}"
            logger.info(f"Persona de l'utilisateur '{user_info.get('username')}' injecté dans le prompt système existant.")
            system_prompt = "Vous êtes un assistant IA généraliste et serviable."
            synthesis_messages.insert(0, {"role": "system", "content": system_prompt})

        # La valeur retournée ici est le résultat de la tâche Celery,
        # qui sera récupéré par l'endpoint de polling HTTP.
        try:
            logger.info(f"Appel final au LLM pour synthèse pour SID {sid}.")
            response_obj = _execute_llm_request(
                model_name=model_id,
                messages=synthesis_messages,
                stream=False
            )
            final_answer = response_obj.choices[0].message.content
            logger.info(f"Réponse finale synthétisée pour SID {sid}: '{final_answer[:100]}...'")

            # --- Sécurité finale : Ne jamais retourner une réponse vide ---
            if not final_answer or not final_answer.strip():
                logger.warning(f"Le LLM de synthèse a retourné une réponse vide pour SID {sid}. Envoi d'un message d'erreur à l'utilisateur.")
                final_answer = "Désolé, je n'ai pas pu générer de réponse pour votre demande. Veuillez essayer de reformuler votre question."

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
                    model_name=model_id,
                    json_mode=False
                )
                return llm_fallback if llm_fallback else fallback_msg
            except Exception as e2:
                logger.error(f"Erreur lors de la génération du fallback LLM synthèse : {e2}")
                return fallback_msg
    except Exception as e:
        logger.error(f"Erreur inattendue dans orchestrator_task pour SID {sid}: {e}", exc_info=True)
        return "Désolé, une erreur est survenue lors du traitement de votre demande."

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

@celery.task()
def search_web_task(query: str) -> list:
    """
    Effectue une recherche web pour la requête donnée et retourne les résultats.
    """
    logger.info(f"Début de la recherche pour : '{query}'")
    searxng_url = current_app.config.get('SEARXNG_BASE_URL')

    if not searxng_url:
        logger.error("L'URL de SearXNG n'est pas configurée (SEARXNG_BASE_URL).")
        return []
    
    try:
        search_url = f"{searxng_url}/search?q={query}&format=json"
        response = requests.get(search_url, timeout=10)
        response.raise_for_status()
        return response.json().get("results", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion à SearXNG : {e}")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Erreur de décodage de la réponse JSON de SearXNG : {e}")
        return []

@celery.task()
def read_webpage_task(url: str) -> str:
    """
    Scrape le contenu textuel d'une page web à partir de son URL.
    """
    if not url or not url.startswith(('http://', 'https://')):
        return f"Erreur: URL invalide fournie : '{url}'"

    logger.info(f"Début du scraping pour l'URL : {url}")
    try:
        headers = {'User-Agent': 'Harpou-AI-Gateway-Scraper/1.0'}
        page_response = requests.get(url, timeout=15, headers=headers)
        page_response.raise_for_status()

        soup = BeautifulSoup(page_response.content, 'html.parser')
        for script_or_style in soup(["script", "style", "nav", "footer", "header", "aside"]):
            script_or_style.decompose()

        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        full_text = '\n'.join(chunk for chunk in chunks if chunk)

        return full_text[:8000]
    except requests.exceptions.RequestException as e:
        error_message = f"Erreur lors de la lecture de l'URL {url}: {e}"
        logger.error(error_message)
        return error_message
