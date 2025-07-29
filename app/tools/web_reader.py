import requests
from bs4 import BeautifulSoup
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

def read_webpage(url: str) -> str:
    """
    Récupère et nettoie le contenu textuel d'une page web.
    """
    logger.info(f"Lecture de la page web: {url}")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        # Utilisation de BeautifulSoup pour parser le HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # Supprimer les balises de script et de style
        for script_or_style in soup(['script', 'style']):
            script_or_style.decompose()

        # Extraire le texte et nettoyer les espaces
        text = soup.get_text()
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        cleaned_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        logger.info(f"Lecture de l'URL {url} terminée avec succès.")
        return cleaned_text if cleaned_text else "Le contenu de la page est vide ou n'a pas pu être lu."

    except requests.exceptions.RequestException as e:
        logger.error(f"Erreur lors de la requête vers l'URL {url}: {e}", exc_info=True)
        return f"Erreur: Impossible d'accéder à l'URL. Détails: {e}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la lecture de l'URL {url}: {e}", exc_info=True)
        return f"Erreur inattendue lors de la lecture de la page. Détails: {e}"
