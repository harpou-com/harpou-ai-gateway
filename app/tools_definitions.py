import logging
from .tools.web_search import search_web
from .tools.web_reader import read_webpage

# Configuration du logger
logger = logging.getLogger(__name__)

# Le "menu" des outils présentés au LLM de décision
# Conforme au format de l'API OpenAI
TOOLS_LIST = [
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Effectue une recherche sur le web pour des informations récentes ou spécifiques.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "La requête de recherche précise. Par exemple: 'dernières nouvelles projet de loi C-63 Canada'"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_webpage",
            "description": "Lit le contenu textuel principal d'une page web à partir de son URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "L'URL complète de la page à lire."
                    }
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "proceed_to_synthesis",
            "description": "Utilise cet outil lorsque la réponse ne nécessite aucune recherche externe ou lecture de page web et peut être formulée directement à partir de l'historique de la conversation et des connaissances générales.",
            "parameters": {
                "type": "object",
                "properties": {}
            }
        }
    }
]

def get_tools_list():
    """Retourne la liste des définitions d'outils."""
    return TOOLS_LIST

def execute_tool(tool_name: str, parameters: dict) -> str:
    """
    Aiguilleur qui appelle la fonction Python correspondante à l'outil choisi.
    """
    logger.info(f"Exécution de la fonction pour l'outil: {tool_name}")
    
    if tool_name == "search_web":
        query = parameters.get("query")
        if not query:
            return "Erreur: La requête de recherche est manquante."
        return search_web(query)
        
    elif tool_name == "read_webpage":
        url = parameters.get("url")
        if not url:
            return "Erreur: L'URL est manquante."
        return read_webpage(url)
        
    # Note: proceed_to_synthesis n'a pas de fonction d'exécution ici car il est géré
    # directement dans la logique de l'orchestrateur.
    
    else:
        logger.warning(f"Tentative d'exécution d'un outil inconnu: {tool_name}")
        return f"Erreur: Outil '{tool_name}' non reconnu."

