import logging

# Configuration du logger
logger = logging.getLogger(__name__)

# Le "menu" des outils présentés au LLM de décision
# Ce format est destiné à être injecté dans un prompt système.
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
    },
]
