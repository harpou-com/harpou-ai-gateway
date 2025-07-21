import eventlet

# Appliquer le monkey-patching tout au début, avant l'importation de tout autre module.
# C'est essentiel pour qu'eventlet fonctionne correctement avec Celery et d'autres bibliothèques
# qui utilisent des I/O (réseau, etc.) ou du threading.
eventlet.monkey_patch()

from celery.__main__ import main

if __name__ == '__main__':
    # Exécute la ligne de commande de Celery.
    # Les arguments sont passés depuis la commande qui lance ce script.
    # Par exemple: python worker_launcher.py -A celery_worker.celery worker --loglevel=info
    main()