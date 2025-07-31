import requests
import logging
from typing import List, Dict, Any
from .web_reader import read_webpage

# Configuration du logger
logger = logging.getLogger(__name__)

# TODO: Externaliser cette URL dans la configuration globale
SEARXNG_URL = "http://searxng:8080" # Assurez-vous que c'est accessible depuis votre worker Celery

def search_web(query: str, num_to_read: int = 5, num_extra: int = 5) -> List[Dict[str, Any]]:
    """
    Effectue une recherche web, lit le contenu des premiers résultats,
    et retourne une liste combinée de résultats enrichis et standards.

    Args:
        query: La requête de recherche.
        num_to_read: Le nombre de pages à lire entièrement.
        num_extra: Le nombre de résultats supplémentaires à retourner sans lecture.

    Returns:
        Une liste de dictionnaires. Les premiers `num_to_read` résultats
        contiennent une clé 'page_content' avec le contenu de la page.
        Les suivants sont des résultats de recherche standards.
        Retourne une liste vide en cas d'erreur ou si aucun résultat n'est trouvé.
    """
    total_results_needed = num_to_read + num_extra
    logger.info(f"Début de la recherche web enrichie pour: '{query}', demandant jusqu'à {total_results_needed} résultats.")
    try:
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10  # Toujours mettre un timeout pour les requêtes réseau
        )
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP

        data = response.json()
        all_results = data.get("results", [])

        if not all_results:
            logger.warning(f"Aucun résultat trouvé pour la requête: '{query}'")
            return []

        # Séparer les résultats à lire de ceux à retourner tels quels
        results_to_read = all_results[:num_to_read]
        other_results = all_results[num_to_read:total_results_needed]
        
        final_results = []

        # 1. Traiter les résultats à lire
        logger.info(f"Lecture du contenu de {len(results_to_read)} page(s)...")
        for r in results_to_read:
            page_content = read_webpage(r.get("url")) # Appel à l'outil de lecture
            final_results.append({
                "title": r.get("title"), "url": r.get("url"),
                "content": r.get("content"), "page_content": page_content
            })

        # 2. Ajouter les résultats supplémentaires
        for r in other_results:
            final_results.append({
                "title": r.get("title"), "url": r.get("url"),
                "content": r.get("content"), "page_content": None
            })

        logger.info(f"Recherche et lecture terminées. {len(final_results)} résultats au total retournés pour '{query}'.")
        return final_results

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion à SearXNG pour la requête '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la recherche web pour '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
