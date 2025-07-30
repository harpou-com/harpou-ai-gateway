import logging
import json

from app.extensions import socketio, celery
from app import llm_connector, tools_definitions
import openai

# Configuration du logger
logger = logging.getLogger(__name__)

def _make_decision(sid, conversation, model_id):
    """
    Étape 1: Le LLM prend une décision sur l'outil à utiliser.
    Cette fonction est maintenant plus robuste et gère les modèles ne supportant pas les outils.
    """
    logger.info("Étape 1: Prise de décision par le LLM.")
    
    tools = tools_definitions.get_tools_list()
    decision_conversation = conversation.copy()

    try:

        response = llm_connector._execute_llm_request(
            messages=decision_conversation,
            model_name=model_id,
            tools=tools,
            tool_choice="auto"
        )
        return response.choices[0].message
    except openai.BadRequestError as e:
        if "does not support tools" in str(e).lower():
            logger.warning(f"Le modèle '{model_id}' ne supporte pas les outils. Passage en mode conversationnel simple.")
            return None
        else:
            logger.error(f"Erreur BadRequest lors de la prise de décision: {e}")
            raise
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la prise de décision: {e}")
        raise

def _create_synthesis(sid, conversation, model_id):
    """
    Étape 3: Synthèse de la réponse finale.
    Cette fonction ne doit pas envoyer de paramètres d'outils.
    """
    logger.info("Étape 3: Synthèse de la réponse finale.")
    
    try:
        response = llm_connector._execute_llm_request(
            messages=conversation,
            model_name=model_id,
            stream=True
        )
        
        final_content = ""
        for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                final_content += content
                socketio.emit('final_response_chunk', {'sid': sid, 'content': content}, room=sid)
        
        logger.info("Synthèse terminée avec succès.")
        return final_content
    except Exception as e:
        logger.error(f"Erreur lors de la synthèse de la réponse: {e}")
        error_message = "Désolé, une erreur est survenue lors de la génération de la réponse."
        socketio.emit('final_response_chunk', {'sid': sid, 'content': error_message}, room=sid)
        return error_message

@celery.task(name="app.tasks.orchestrator_task")
def orchestrator_task(sid, conversation, model_id):
    """
    Tâche principale d'orchestration qui gère le flux de la requête.
    """
    logger.info(f"Orchestrateur démarré pour SID {sid}.")
    
    # On travaille sur une copie pour ne pas modifier l'historique original
    # de manière inattendue pour d'autres branches de logique.
    current_conversation = conversation.copy()
    
    decision_message = _make_decision(sid, current_conversation, model_id)

    if decision_message and decision_message.tool_calls:
        tool_call = decision_message.tool_calls[0]
        tool_name = tool_call.function.name
        logger.info(f"Décision: Utiliser l'outil '{tool_name}'.")

        if tool_name != "proceed_to_synthesis":
            # 1. Ajouter la décision du LLM (l'appel d'outil) à l'historique
            # C'est une étape standard pour que le LLM ait le contexte de sa propre décision.
            current_conversation.append(decision_message.model_dump())

            # 2. Exécuter l'outil
            tool_parameters = json.loads(tool_call.function.arguments)
            tool_result = tools_definitions.execute_tool(tool_name, tool_parameters)

            # 3. Ajouter le résultat de l'outil à l'historique
            current_conversation.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": tool_name,
                "content": tool_result,
            })
            logger.info(f"Résultat de l'outil '{tool_name}': {str(tool_result)[:200]}...")
        else:
            logger.info("L'outil 'proceed_to_synthesis' a été choisi. Passage direct à la synthèse.")
            # Pas besoin d'ajouter quoi que ce soit à la conversation pour cet outil.

    # La synthèse est appelée avec la conversation potentiellement enrichie par l'outil.
    final_response = _create_synthesis(sid, current_conversation, model_id)
    
    logger.info(f"Orchestrateur terminé pour SID {sid}.")
    socketio.emit('task_complete', {'sid': sid}, room=sid)
    return final_response

@celery.task(name="app.tasks.refresh_models_cache_task")
def refresh_models_cache_task():
    """
    Tâche périodique pour rafraîchir le cache des modèles.
    """
    # Rétablissement de la logique originale qui fonctionnait, avec l'importation à l'intérieur de la tâche
    # pour éviter les dépendances circulaires potentielles.
    try:
        from app.services import refresh_and_cache_models
        logger.info("Exécution de la tâche de rafraîchissement du cache des modèles.")
        model_service = refresh_and_cache_models()
        count = (len(model_service))
        logger.info(f"Tâche de rafraîchissement terminée. {count} modèles ont été trouvés et mis en cache.")
    except ImportError:
        logger.exception("Impossible d'importer refresh_and_cache_model depuis app.services. Vérifiez le nom et l'emplacement du service.")
    except Exception as e:
        logger.exception(f"Une erreur est survenue lors du rafraîchissement du cache des modèles: {e}")
