"""
Catalogue d'outils disponibles pour l'API et logique de décision LLM.
"""

# Chaque outil est défini comme un dictionnaire pour faciliter l'extension et la maintenance.
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

def decide_llm_action(user_question):
    """
    Simule la décision d'un LLM pour déterminer si une question utilisateur nécessite l'appel d'un outil
    (par exemple, une recherche web) ou une réponse directe.

    Args:
        user_question (str): La question posée par l'utilisateur.

    Returns:
        dict: Un dictionnaire décrivant l'action à entreprendre.
            - Si une recherche web est suggérée, retourne :
                {
                    "action": "call_tool",
                    "tool_name": "search_web",
                    "parameters": {"query": user_question}
                }
            - Sinon, retourne :
                {
                    "action": "respond",
                    "message": "Réponse directe simulée."
                }
    """
    print(f"[decide_llm_action] Question reçue : {user_question!r}")
    keywords = ["météo", "actualités", "qui est"]
    if any(kw.lower() in user_question.lower() for kw in keywords):
        decision = {
            "action": "call_tool",
            "tool_name": "search_web",
            "parameters": {"query": user_question}
        }
        print(f"[decide_llm_action] Décision : appel de l'outil 'search_web' avec paramètres {decision['parameters']}")
        return decision
    else:
        decision = {
            "action": "respond",
            "message": "Réponse directe simulée."
        }
        print(f"[decide_llm_action] Décision : réponse directe.")
        return decision
import requests
import json
from .extensions import celery, socketio
@celery.task(bind=True)
def search_web_task(self, user_query, sid):
    """
    Tâche Celery qui effectue une recherche web puis notifie le client via WebSocket (SocketIO).
    """
    SEARXNG_BASE_URL = "https://searxng.harpou.com"
    print(f"[search_web_task] Début de la recherche pour : {user_query} (SID: {sid})")
    payload = {
        'status': 'success',
        'query': user_query,
        'results': [],
        'error': None
    }
    try:
        response = requests.get(f"{SEARXNG_BASE_URL}/search?q={user_query}&format=json", timeout=10)
        response.raise_for_status()
        search_data = response.json()
        results = search_data.get("results", [])[:5]
        for idx, res in enumerate(results, 1):
            payload['results'].append({
                'rank': idx,
                'title': res.get("title", ""),
                'content': res.get("content", ""),
                'url': res.get("url", "")
            })
        if not payload['results']:
            payload['status'] = 'empty'
            payload['error'] = 'Aucun résultat trouvé.'
            print("[search_web_task] Aucun résultat trouvé.")
        else:
            print(f"[search_web_task] Recherche terminée avec succès pour {user_query}.")
    except requests.exceptions.RequestException as e:
        payload['status'] = 'error'
        payload['error'] = f"Erreur lors de la requête SearXNG : {e}"
        print(f"[search_web_task] Erreur de requête : {e}")
    except json.JSONDecodeError as e:
        payload['status'] = 'error'
        payload['error'] = f"Erreur de décodage JSON : {e}"
        print(f"[search_web_task] Erreur de décodage JSON : {e}")

    # Notifie le client via WebSocket (SocketIO)
    socketio.emit('task_result', payload, room=sid)
    return None

import time

@celery.task(bind=True)
def long_running_task(self, sid):
    """
    Tâche de démo qui attend 5 secondes, puis envoie une notification
    au client spécifique qui a déclenché la tâche.
    """
    print(f"Début d'une tâche longue pour le client SID: {sid}")
    time.sleep(5)
    print(f"Tâche terminée. Envoi de la notification au SID: {sid}")
    # Utilise self.request.id pour obtenir l'ID de la tâche
    task_id = self.request.id
    socketio.emit('task_result', {
        'status': 'success',
        'message': 'Tâche terminée !',
        'task_id': task_id
    }, room=sid)
    return "Notification envoyée."