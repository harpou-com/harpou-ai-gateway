import requests
import json
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

# TODO: Externaliser cette URL dans la configuration globale
SEARXNG_URL = "http://searxng:8080"

def search_web(query: str) -> str:
    """
    Effectue une recherche web en utilisant une instance SearXNG et retourne les résultats formatés.
    """
    logger.info(f"Début de la recherche web pour: '{query}'")
    try:
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"}
        )
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP
        
        data = response.json()
        
        # Formater les résultats pour la synthèse par le LLM
        formatted_results = []
        for result in data.get("results", [])[:5]: # Limite aux 5 premiers résultats
            formatted_results.append(
                f"- Titre: {result.get('title', 'N/A')}\n"
                f"  URL: {result.get('url', 'N/A')}\n"
                f"  Extrait: {result.get('content', 'N/A')}\n"
            )
            
        if not formatted_results:
            logger.warning(f"Aucun résultat trouvé pour la requête: '{query}'")
            return "Aucun résultat de recherche trouvé."
            
        logger.info(f"{len(formatted_results)} résultats trouvés pour '{query}'.")
        return "\n".join(formatted_results)

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion à SearXNG: {e}", exc_info=True)
        return f"Erreur: Impossible de se connecter au service de recherche web. Détails: {e}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la recherche web: {e}", exc_info=True)
        return f"Erreur inattendue lors de la recherche. Détails: {e}"
