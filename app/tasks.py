import logging
import json
import os
import copy
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from typing import Optional, List, Dict, Any
import urllib.parse
import unicodedata
import requests
from bs4 import BeautifulSoup
from flask import current_app
from eventlet.greenpool import GreenPool
from app.extensions import socketio, celery
from app.llm_connector import get_llm_completion, _execute_llm_request, _get_backend_config
from app.services import refresh_and_cache_models 

# Configuration du logger
logger = logging.getLogger(__name__)

def _get_prompt_from_file(filename: str) -> Optional[str]:
    """Lit un prompt depuis un fichier dans le dossier config/prompts."""
    if not filename:
        return None
    try:
        # Le chemin racine du projet est un niveau au-dessus du répertoire de l'application
        project_root = os.path.abspath(os.path.join(current_app.root_path, os.pardir))
        prompt_path = os.path.join(project_root, 'config', 'prompts', filename)
        
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            logger.warning(f"Le fichier de prompt '{filename}' est configuré mais n'a pas été trouvé à l'emplacement : {prompt_path}")
            return None
    except Exception as e:
        logger.error(f"Erreur lors de la lecture du fichier de prompt '{filename}': {e}")
        return None

def _normalize_string(s: str) -> str:
    """Retire les accents et autres diacritiques d'une chaîne de caractères."""
    if not isinstance(s, str):
        return str(s)
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

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

    # Charger le template du prompt de routage depuis un fichier
    routing_prompt_file = current_app.config.get("routing_prompt_file", "default_routing.txt")
    system_prompt_template = _get_prompt_from_file(routing_prompt_file)

    if not system_prompt_template:
        # Fallback vers un prompt hardcodé si le fichier est manquant ou vide
        logger.error("Le template du prompt de routage est manquant ou vide. Utilisation d'un prompt par défaut.")
        system_prompt_template = """Vous êtes un orchestrateur. Choisissez une action: `call_tool` ou `respond_directly`. Outils: {available_tools}. Répondez en JSON comme dans ces exemples: {examples_str}."""

    # Remplir les placeholders dans le template
    system_prompt = system_prompt_template.format(
        available_tools=json.dumps(available_tools, indent=2),
        examples_str=examples_str
    )
    
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
                
                # Récupérer les paramètres configurables depuis tools_config.json, avec des valeurs par défaut.
                details = tool_config.get("execution_details", {})
                pages_to_read = details.get("pages_to_read", 1)
                excerpts_to_show = details.get("excerpts_to_show", 4)
                
                search_results = search_web_task(query=query)
                if not isinstance(search_results, list) or not search_results:
                    return "La recherche n'a retourné aucun résultat."

                # --- Lecture en parallèle des pages principales ---
                urls_to_read = [res.get('url') for res in search_results[:pages_to_read] if res.get('url')]
                final_context = ""
                
                if urls_to_read:
                    logger.info(f"Lecture en parallèle de {len(urls_to_read)} page(s) web...")
                    pool = GreenPool()
                    read_contents = list(pool.imap(read_webpage_task, urls_to_read))
                    
                    final_context += "--- CONTENU DES PAGES PRINCIPALES ---\n"
                    for i, content in enumerate(read_contents):
                        final_context += f"Source {i+1}: {urls_to_read[i]}\nContenu:\n{content}\n---\n"
                
                # --- Ajout des extraits des pages suivantes ---
                excerpt_results = search_results[pages_to_read : pages_to_read + excerpts_to_show]
                if excerpt_results:
                    final_context += "\n--- AUTRES RÉSULTATS DE RECHERCHE (EXTRAITS) ---\n"
                    final_context += _format_results_as_context(excerpt_results)
                    
                return final_context
            elif tool_name == "read_webpage":
                urls = parameters.get("url", [])
                if isinstance(urls, str):
                    # Si une seule URL est fournie, on la traite comme une liste d'un seul élément.
                    urls = [urls]
                
                if not urls:
                    return "Erreur: Aucune URL n'a été fournie."

                logger.info(f"Orchestrateur : appel de la fonction interne 'read_webpage' sur {len(urls)} URL(s).")
                
                pool = GreenPool()
                read_contents = list(pool.imap(read_webpage_task, urls))
                
                final_context = ""
                for i, content in enumerate(read_contents):
                    final_context += f"--- Contenu de l'URL {i+1}: {urls[i]} ---\n{content}\n\n"
                
                return final_context.strip()
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

        elif tool_type == "search_and_read_webpage":
            logger.info(f"Exécution de l'outil de type 'search_and_read_webpage': '{tool_name}'")
            details = tool_config.get("execution_details")
            if not details or "query_template" not in details:
                return f"Erreur: 'execution_details' mal configuré pour l'outil '{tool_name}'. Attendu: 'query_template'."

            query = details["query_template"].format(**parameters)
            pages_to_read = details.get("pages_to_read", 1)

            logger.info(f"Recherche générée pour '{tool_name}': {query}")
            search_results = search_web_task(query=query)
            if not isinstance(search_results, list) or not search_results:
                return "La recherche n'a retourné aucun résultat."

            urls_to_read = [res.get('url') for res in search_results[:pages_to_read] if res.get('url')]

            if not urls_to_read:
                return "La recherche n'a retourné aucune URL à lire."

            logger.info(f"Lecture en parallèle de {len(urls_to_read)} page(s) web...")
            pool = GreenPool()
            read_contents = list(pool.imap(read_webpage_task, urls_to_read))

            search_and_read_context = ""
            for i, content in enumerate(read_contents):
                search_and_read_context += f"--- Contenu de l\'URL {i+1}: {urls_to_read[i]} ---\n{content}\n\n"

            # --- Logique d'enrichissement pour la météo ---
            if tool_name == "get_detailed_weather":
                supplementary_context = ""
                keywords_to_check = ["insecte", "moustique", "pollen", "qualité de l'air", "uv", "humidex"]

                keywords_found = [kw for kw in keywords_to_check if kw in user_question.lower()]
                if keywords_found:
                    logger.info(f"La question météo contient des mots-clés spécifiques ({keywords_found}). Lancement d'une recherche web pour enrichir les données.")

                    location = parameters.get("location", "l'endroit demandé")
                    search_terms = ", ".join(keywords_found)
                    supplementary_query = f"prévision {search_terms} pour {location}"

                    supplementary_search_results = search_web_task(query=supplementary_query)
                    if supplementary_search_results:
                        supplementary_context = "\n\n--- Informations complémentaires (recherche web) ---\n"
                        supplementary_context += _format_results_as_context(supplementary_search_results[:3])
                return f"{search_and_read_context}{supplementary_context}"

            return search_and_read_context.strip()

        elif tool_type == "url_from_template":
            logger.info(f"Exécution de l'outil de type 'url_from_template': '{tool_name}'")
            details = tool_config.get("execution_details")
            if not details or "query_template" not in details:
                return f"Erreur: 'execution_details' mal configuré pour l'outil '{tool_name}'. Attendu: 'query_template'."

            # Récupérer le template et injecter les variables de configuration globales
            template_string = details["query_template"]
            if '{SEARXNG_BASE_URL}' in template_string:
                searxng_url = current_app.config.get('SEARXNG_BASE_URL', '')
                template_string = template_string.replace('{SEARXNG_BASE_URL}', searxng_url)

            # Formater l'URL avec les paramètres spécifiques à l'outil
            url_to_read = template_string.format(**parameters)

            # Appeler directement la fonction de lecture de page web
            logger.info(f"Lecture directe de l'URL générée : {url_to_read}")
            result = read_webpage_task(url_to_read)

            # Formater la sortie pour être cohérente avec les autres outils
            return f"--- Contenu de l'URL 1: {url_to_read} ---\n{result}\n\n"

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

        # 1. Définir le contexte temporel pour le LLM.
        time_context = ""
        try:
            # Le fuseau horaire pourrait être rendu configurable ou lié à l'utilisateur.
            tz = ZoneInfo("America/Montreal")
            current_time_str = datetime.now(tz).strftime('%Y-%m-%d %H:%M:%S %Z')
            time_context = f"Contexte temporel : La date et l'heure actuelles sont {current_time_str}."
        except (ZoneInfoNotFoundError, ImportError):
            logger.warning("Le module 'zoneinfo' ou le fuseau horaire n'est pas disponible. Utilisation de l'heure UTC.")
            current_time_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
            time_context = f"Contexte temporel : La date et l'heure actuelles sont {current_time_str}."
        except Exception as e:
            logger.error(f"Erreur lors de la récupération de la date/heure : {e}")
            # Ne pas bloquer l'exécution si la date échoue.

        # 2. Déterminer le prompt système de base.
        base_system_prompt = ""
        if tool_results:
            # Si un outil a été utilisé, le prompt se concentre sur la synthèse des résultats.
            base_system_prompt = f"""Vous êtes un assistant de synthèse. Votre rôle est de répondre à la question de l'utilisateur EN VOUS BASANT UNIQUEMENT sur les "Informations de recherche" fournies ci-dessous.
Règle impérative : NE PAS inventer d'informations ou de valeurs qui ne sont pas présentes dans le contexte. Si une information demandée par l'utilisateur (par exemple, le risque d'insectes) n'est pas explicitement listée dans les "Informations de recherche", vous DEVEZ indiquer qu'elle n'a pas pu être trouvée.
Formatez la réponse de manière claire et lisible.

Informations de recherche:\n---\n{tool_results}\n---"""
        else:
            # Si aucune information externe n'est fournie, on utilise le persona de l'utilisateur ou un prompt par défaut.
            persona_prompt = None
            if user_info and (persona_file := user_info.get("persona_prompt_file")):
                persona_prompt = _get_prompt_from_file(persona_file)
                if persona_prompt:
                    logger.info(f"Persona de l'utilisateur '{user_info.get('username')}' injecté depuis le fichier '{persona_file}'.")
            
            base_system_prompt = persona_prompt or "Vous êtes un assistant IA généraliste et serviable."

        # 3. Construire le prompt système final en combinant le temps et le contenu.
        final_system_prompt = f"{time_context}\n\n{base_system_prompt}".strip()

        # 4. Injecter ou mettre à jour le prompt système dans la conversation.
        if synthesis_messages and synthesis_messages[0].get("role") == "system":
            synthesis_messages[0]["content"] = final_system_prompt
        else:
            synthesis_messages.insert(0, {"role": "system", "content": final_system_prompt})

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
