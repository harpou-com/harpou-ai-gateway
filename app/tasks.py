import logging
from . import llm_connector
from .tools_definitions import get_tools_list, execute_tool
from . import services
import json

# Configuration du logger
logger = logging.getLogger(__name__)

# Initialisation de Celery
from .extensions import celery  # Import Celery instance


@celery.task(name='app.tasks.refresh_models_cache_task')
def refresh_models_cache_task():
    """
    Tâche périodique pour rafraîchir la liste des modèles disponibles depuis les backends.
    """
    logger.info("Exécution de la tâche de rafraîchissement du cache des modèles.")
    try:
        services.refresh_and_cache_models()
    except Exception as e:
        logger.error(f"Erreur lors de l'exécution de la tâche de rafraîchissement du cache: {e}", exc_info=True)


def _make_decision(model_id: str, messages: list) -> dict:
    """
    Première étape : Appelle le LLM pour décider quel outil utiliser.
    """
    logger.info("Étape 1: Prise de décision par le LLM.")
    
    tools = get_tools_list()
    
    # Appel au LLM avec la liste des outils
    try:
        # On utilise la fonction interne _execute_llm_request pour un appel direct au backend,
        # car les fonctions publiques de llm_connector sont conçues pour le flux de l'agent.
        response = llm_connector._execute_llm_request(
            model_name=model_id,
            messages=messages,
            tools=tools,
            tool_choice="auto"
        )
        
        # Extraire la décision d'appel d'outil
        tool_calls = response.choices[0].message.tool_calls
        if tool_calls:
            logger.info(f"Décision reçue: Appeler l'outil {tool_calls[0].function.name}.")
            return json.loads(tool_calls[0].function.arguments)
        else:
            logger.info("Décision reçue: Aucune action d'outil, passage direct à la synthèse.")
            return {"action": "proceed_to_synthesis", "parameters": {}}

    except Exception as e:
        logger.error(f"Erreur lors de la prise de décision: {e}", exc_info=True)
        # En cas d'erreur, on passe à la synthèse avec un message d'erreur.
        return {"action": "error", "parameters": {"details": str(e)}}


def _make_synthesis(model_id: str, original_messages: list, tool_result: str) -> str:
    """
    Troisième étape : Synthétise une réponse finale en se basant sur la conversation et le résultat de l'outil.
    """
    logger.info("Étape 3: Synthèse de la réponse finale.")

    # Création d'un nouveau prompt pour le LLM de synthèse
    synthesis_prompt = f"""
    Contexte de la conversation originale:
    {json.dumps(original_messages, indent=2)}

    Résultat de l'outil exécuté:
    {tool_result}

    Tâche: En te basant sur la conversation et le résultat de l'outil, rédige une réponse finale et complète à la dernière question de l'utilisateur.
    Réponds directement à l'utilisateur. Ne mentionne pas que tu as utilisé un outil.
    """
    
    synthesis_messages = [{"role": "user", "content": synthesis_prompt}]

    try:
        response = llm_connector._execute_llm_request(
            model_name=model_id,
            messages=synthesis_messages
        )
        final_response = response.choices[0].message.content
        logger.info("Synthèse terminée avec succès.")
        return final_response
    except Exception as e:
        logger.error(f"Erreur lors de la synthèse: {e}", exc_info=True)
        return "Je suis désolé, une erreur est survenue lors de la finalisation de ma réponse."


@celery.task
def orchestrator_task(sid: str, model_id: str, messages: list) -> str:
    """
    Tâche Celery principale qui orchestre le flux de décision, exécution et synthèse.
    """
    logger.info(f"Orchestrateur démarré pour SID {sid}.")
    
    # 1. Prise de décision
    decision = _make_decision(model_id, messages)
    
    tool_name = decision.get("action", "proceed_to_synthesis")
    parameters = decision.get("parameters", {})
    
    # 2. Exécution de l'outil (si nécessaire)
    tool_result = ""
    if tool_name != "proceed_to_synthesis" and tool_name != "error":
        logger.info(f"Étape 2: Exécution de l'outil '{tool_name}'.")
        tool_result = execute_tool(tool_name, parameters)
    elif tool_name == "error":
        tool_result = f"Une erreur est survenue lors de la prise de décision: {parameters.get('details')}"
    else:
        logger.info("Étape 2: Aucune exécution d'outil nécessaire.")
        tool_result = "Aucun outil n'a été utilisé. La réponse est basée sur la connaissance générale."
        
    # 3. Synthèse
    final_response = _make_synthesis(model_id, messages, tool_result)
    
    logger.info(f"Orchestrateur terminé pour SID {sid}.")
    return final_response
