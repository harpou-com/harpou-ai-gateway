import eventlet
# Appliquer le monkey-patching avant l'importation de tout code d'application ou de test.
# C'est crucial pour que les bibliothèques asynchrones comme eventlet, socketio, et celery
# fonctionnent correctement dans l'environnement de test.
eventlet.monkey_patch()

import unittest
import sys
from datetime import datetime

def log_message(message):
    """Affiche un message avec un horodatage pour un meilleur suivi."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

if __name__ == '__main__':
    """
    Découvre et exécute tous les tests unitaires dans le dossier /tests.
    Ce script s'assure que l'environnement est correctement patché pour eventlet
    avant que les tests ne soient exécutés.
    """
    log_message("Début de l'exécution de la suite de tests.")
    # Découvre et exécute les tests avec une sortie plus détaillée.
    loader = unittest.TestLoader()
    suite = loader.discover('tests')
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    log_message("Fin de l'exécution de la suite de tests.")

    # Quitte avec un code d'erreur si des tests ont échoué, pour que le CI/CD puisse le détecter.
    if not result.wasSuccessful():
        log_message("La suite de tests a échoué.")
        sys.exit(1)
    
    log_message("La suite de tests a réussi.")