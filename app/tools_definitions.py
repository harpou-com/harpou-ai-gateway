import logging

logger = logging.getLogger(__name__)

# NOTE : La définition des outils a été déplacée vers le fichier `config/tools_config.json`.
# Ce fichier est conservé pour la compatibilité des imports mais ne doit plus être modifié
# pour la configuration des outils. La configuration est maintenant chargée dynamiquement
# au démarrage de l'application.
