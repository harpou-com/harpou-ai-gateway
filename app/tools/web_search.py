import requests
import logging
from typing import List, Dict, Any
from .web_reader import read_webpage
from concurrent.futures import ThreadPoolExecutor, as_completed

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
    logger.info(f"Début de la recherche web enrichie pour: '{query}', demandant {total_results_needed} résultats.")
    try:
        response = requests.get(
            f"{SEARXNG_URL}/search",
            params={"q": query, "format": "json"},
            timeout=10  # Toujours mettre un timeout pour les requêtes réseau
        )
        response.raise_for_status()  # Lève une exception pour les codes d'erreur HTTP

        data = response.json()
        all_search_results = data.get("results", [])

        if not all_search_results:
            logger.warning(f"Aucun résultat trouvé pour la requête: '{query}'")
            return []

        # Séparer les résultats à lire de ceux à retourner tels quels
        results_to_process = all_search_results[:total_results_needed]
        final_results = [{"title": r.get("title"), "url": r.get("url"), "content": r.get("content"), "page_content": None} for r in results_to_process]
        
        # 1. Traiter les résultats à lire en parallèle
        urls_to_read = [r.get("url") for r in results_to_process[:num_to_read] if r.get("url")]
        logger.info(f"Lecture parallèle du contenu de {len(urls_to_read)} page(s)...")

        # Créer un mapping URL -> index pour retrouver la place du résultat
        url_to_index = {r['url']: i for i, r in enumerate(final_results) if i < num_to_read and r.get('url')}

        with ThreadPoolExecutor(max_workers=5) as executor:
            # Soumettre les tâches de lecture et garder une référence vers l'URL
            future_to_url = {executor.submit(read_webpage, url): url for url in urls_to_read}
            
            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    page_content = future.result()
                    # Placer le contenu lu dans le bon dictionnaire de la liste finale
                    if url in url_to_index:
                        index = url_to_index[url]
                        final_results[index]['page_content'] = page_content
                except Exception as exc:
                    logger.error(f"Erreur lors de la lecture de l'URL {url} dans le thread: {exc}")

        logger.info(f"Recherche et lecture terminées. {len(final_results)} résultats au total retournés pour '{query}'.")
        return final_results

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de connexion à SearXNG pour la requête '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la recherche web pour '{query}': {e}", exc_info=True)
        return []  # Retourne une liste vide pour signaler l'échec
