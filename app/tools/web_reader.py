import requests
from bs4 import BeautifulSoup
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

def read_webpage(url: str) -> str | None:
    """
    Récupère et nettoie le contenu textuel d'une page web.

    Args:
        url: L'URL de la page à lire.

    Returns:
        Le contenu textuel nettoyé de la page, ou None si une erreur survient.
    """
    logger.info(f"Tentative de lecture de la page web: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Supprimer les balises inutiles (script, style, nav, footer, etc.)
        for script_or_style in soup(['script', 'style', 'nav', 'footer', 'aside', 'header']):
            script_or_style.decompose()

        # Extraire le texte de manière plus propre
        text = soup.get_text(separator='\n', strip=True)

        if not text:
            logger.warning(f"Le contenu extrait de l'URL {url} est vide.")
            return "" # Succès, mais la page est vide

        logger.info(f"Lecture de l'URL {url} terminée avec succès.")
        return text

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur de requête HTTP lors de la lecture de l'URL {url}: {e}", exc_info=True)
        return None  # Retourne None pour signaler une erreur
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la lecture de l'URL {url}: {e}", exc_info=True)
        return None  # Retourne None pour signaler une erreur
