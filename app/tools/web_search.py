import requests
import logging
from typing import List, Dict, Any

# Configuration du logger
logger = logging.getLogger(__name__)

# TODO: Externaliser cette URL dans la configuration globale
SEARXNG_URL = "http://searxng:8080" # Assurez-vous que c'est accessible depuis votre worker Celery

def search_web(query: str, num_results: int = 5) -> List[Dict[str, Any]]:
    """
    Effectue une recherche web via SearXNG et retourne une liste de résultats structurés.

    Args:
        query: La requête de recherche.
        num_results: Le nombre de résultats à retourner.

    Returns:
        Une liste de dictionnaires, chaque dictionnaire représentant un résultat.
        Retourne une liste vide en cas d'erreur ou si aucun résultat n'est trouvé.
    """
    logger.info(f"Début de la recherche web pour: '{query}'")
    try:
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10  # Toujours mettre un timeout pour les requêtes réseau
        )
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP

        data = response.json()
        results = data.get("results", [])

        if not results:
            logger.warning(f"Aucun résultat trouvé pour la requête: '{query}'")
            return []

        # Préparer une liste de résultats propres et structurés
        clean_results = [
            {"title": r.get("title"), "url": r.get("url"), "content": r.get("content")}
            for r in results[:num_results]
        ]

        logger.info(f"{len(clean_results)} résultats traités pour '{query}'.")
        return clean_results

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion à SearXNG pour la requête '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la recherche web pour '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
