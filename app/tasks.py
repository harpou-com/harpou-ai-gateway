import logging
from celery import Celery
from app.extensions import socketio
from app import llm_connector, tools_definitions
import openai

# Configuration du logger
logger = logging.getLogger(__name__)

# Initialisation de Celery
celery = Celery(__name__, broker='redis://redis:6379/0', backend='redis://redis:6379/0')

# Mise à jour de la configuration de Celery
celery.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json']
)

def _make_decision(sid, conversation, backend, model):
    """
    Étape 1: Le LLM prend une décision sur l'outil à utiliser.
    Cette fonction est maintenant plus robuste et gère les modèles ne supportant pas les outils.
    """
    logger.info("Étape 1: Prise de décision par le LLM.")
    
    # Récupère les définitions d'outils disponibles
    tools = tools_definitions.get_tools()

    # Prépare une copie de la conversation pour la prise de décision
    decision_conversation = conversation.copy()

    try:
        # Tente d'exécuter la requête avec les outils
        response = llm_connector._execute_llm_request(
            conversation=decision_conversation,
            backend=backend,
            model=model,
            tools=tools,
            tool_choice="auto", # Demande au modèle de choisir
            temperature=0, # Température basse pour une décision fiable
        )
        
        # Retourne le message de décision du LLM
        return response.choices[0].message

    except openai.BadRequestError as e:
        # Gère spécifiquement l'erreur si le modèle ne supporte pas les outils
        if "does not support tools" in str(e).lower():
            logger.warning(f"Le modèle '{model}' sur le backend '{backend}' ne supporte pas les outils. Passage en mode conversationnel simple.")
            return None  # Retourne None pour indiquer qu'aucune décision d'outil n'a pu être prise
        else:
            # Pour les autres erreurs "Bad Request", les logger et les relancer
            logger.error(f"Erreur BadRequest lors de la prise de décision: {e}")
            raise
    except Exception as e:
        # Gère les autres erreurs inattendues
        logger.error(f"Erreur inattendue lors de la prise de décision: {e}")
        raise

def _create_synthesis(sid, conversation, backend, model):
    """
    Étape 3: Synthèse de la réponse finale.
    Cette fonction ne doit pas envoyer de paramètres d'outils.
    """
    logger.info("Étape 3: Synthèse de la réponse finale.")
    
    try:
        # Exécute la requête de synthèse sans les paramètres 'tools' ou 'tool_choice'
        response = llm_connector._execute_llm_request(
            conversation=conversation,
            backend=backend,
            model=model,
            stream=True # Activer le streaming pour la réponse finale
        )
        
        final_content = ""
        # Itère sur la réponse en streaming
        for chunk in response:
            content = chunk.choices[0].delta.content
            if content:
                final_content += content
                # Émet chaque fragment au client via WebSocket
                socketio.emit('final_response_chunk', {'sid': sid, 'content': content}, room=sid)
        
        logger.info("Synthèse terminée avec succès.")
        return final_content

    except Exception as e:
        logger.error(f"Erreur lors de la synthèse de la réponse: {e}")
        error_message = "Désolé, une erreur est survenue lors de la génération de la réponse."
        socketio.emit('final_response_chunk', {'sid': sid, 'content': error_message}, room=sid)
        return error_message


@celery.task(name="app.tasks.orchestrator_task")
def orchestrator_task(sid, conversation, backend, model):
    """
    Tâche principale d'orchestration qui gère le flux de la requête.
    """
    logger.info(f"Orchestrateur démarré pour SID {sid}.")
    
    # Étape 1: Prise de décision
    decision_message = _make_decision(sid, conversation, backend, model)

    # Étape 2: Exécution de l'outil si une décision a été prise
    if decision_message and decision_message.tool_calls:
        logger.info(f"Décision: Utiliser l'outil '{decision_message.tool_calls[0].function.name}'.")
        # Ici, vous ajouteriez la logique pour appeler l'outil (non implémenté dans ce correctif)
        # Pour l'instant, nous passons directement à la synthèse
        pass

    # Étape 3: Synthèse de la réponse finale
    # Si aucune décision n'a été prise ou si l'outil a été exécuté, on synthétise la réponse.
    final_response = _create_synthesis(sid, conversation, backend, model)
    
    logger.info(f"Orchestrateur terminé pour SID {sid}.")
    socketio.emit('task_complete', {'sid': sid}, room=sid)
    return final_response


@celery.task(name="app.tasks.refresh_models_cache_task")
def refresh_models_cache_task():
    """
    Tâche périodique pour rafraîchir le cache des modèles.
    """
    from app.services import get_model_service
    logger.info("Exécution de la tâche de rafraîchissement du cache des modèles.")
    model_service = get_model_service()
    count = model_service.refresh_models_cache()
    logger.info(f"Tâche de rafraîchissement terminée. {count} modèles ont été trouvés et mis en cache.")
