
import os
import json
import logging
from logging.handlers import TimedRotatingFileHandler
from flask import Flask
from dotenv import load_dotenv
from .extensions import socketio, limiter, flask_cache
from flask_cors import CORS

# Charger les variables d'environnement, sauf en mode test pour éviter les I/O bloquantes sur le filesystem.
if os.environ.get("APP_ENV") != "testing":
    load_dotenv()

def configure_logging(app):
    """
    Configure la journalisation avec rotation de fichiers pour l'application.
    Cette fonction est conçue pour être robuste contre les erreurs de configuration.
    """
    # Le chemin racine du projet est un niveau au-dessus du répertoire de l'application
    project_root = os.path.abspath(os.path.join(app.root_path, os.pardir))
    log_dir = os.path.join(project_root, 'logs')
    
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError as e:
        # Si la création du dossier échoue, on logue sur la console et on arrête.
        # Le logger par défaut de Flask (stderr) prendra le relais.
        print(f"AVERTISSEMENT: Impossible de créer le dossier de logs {log_dir}. Erreur: {e}")
        return

    # Récupérer les paramètres de journalisation de manière sécurisée
    log_level_str = app.config.get('LOG_LEVEL', 'INFO').upper()
    log_level = getattr(logging, log_level_str, logging.INFO)
    
    default_rotation_days = 7
    invalid_rotation_value = None
    try:
        rotation_days = int(app.config.get('LOG_ROTATION_DAYS', default_rotation_days))
    except (ValueError, TypeError):
        invalid_rotation_value = app.config.get('LOG_ROTATION_DAYS')
        rotation_days = default_rotation_days

    # Configurer le handler pour la rotation des fichiers
    log_file = os.path.join(log_dir, 'app.log')
    file_handler = TimedRotatingFileHandler(log_file, when='midnight', backupCount=rotation_days, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)

    # Appliquer cette configuration au logger racine
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.setLevel(log_level)

    if invalid_rotation_value is not None:
        root_logger.warning(
            f"Valeur invalide '{invalid_rotation_value}' pour LOG_ROTATION_DAYS. "
            f"Utilisation de la valeur par défaut : {default_rotation_days} jours."
        )

def configure_audit_logging(app):
    """
    Configure la journalisation d'audit dans un fichier séparé 'audit.log'.
    Cette journalisation est destinée à enregistrer les requêtes et réponses
    sous forme structurée (JSON) pour une analyse ultérieure.
    """
    log_dir = os.path.join(os.path.abspath(os.path.join(app.root_path, os.pardir)), 'logs')
    if not os.path.exists(log_dir):
        # configure_logging a déjà dû afficher un avertissement si la création a échoué.
        return

    # Le logger d'audit n'a pas de format complexe, car on logguera directement du JSON.
    audit_formatter = logging.Formatter('%(message)s')
    
    # Utiliser la même configuration de rotation que les logs principaux.
    rotation_days = int(app.config.get('LOG_ROTATION_DAYS', 7))

    audit_log_file = os.path.join(log_dir, 'audit.log')
    audit_handler = TimedRotatingFileHandler(audit_log_file, when='midnight', backupCount=rotation_days, encoding='utf-8')
    audit_handler.setFormatter(audit_formatter)

    audit_logger = logging.getLogger('audit')
    audit_logger.setLevel(logging.INFO)
    audit_logger.addHandler(audit_handler)
    audit_logger.propagate = False # Empêche les logs d'audit de remonter au logger racine.

def create_app(config_object=None, init_socketio=True):
    """
    Application Factory : initialise Flask, Celery, SocketIO, Blueprints et événements.
    - init_socketio : True pour serveur web, False pour worker Celery
    """

    app = Flask(__name__)
    # Active CORS pour toutes les routes HTTP (fetch cross-origin)
    CORS(app, origins="*")

    # --- Logique de chargement de la configuration ---
    # Priorité : 1. Secret Docker > 2. Variables d'environnement > 3. config.json > 4. Valeurs par défaut

    # 4. Définir les valeurs par défaut pour un environnement de développement robuste.
    # On commence avec un dictionnaire de configuration vide qui sera rempli par couches successives.
    config = {}

    # 2. Logique de surcharge par variables d'environnement
    app.logger.info("Vérification des variables d'environnement pour surcharger la configuration...")
    
    # Scénario 1: Surcharge simplifiée pour un backend unique
    is_single_backend_mode = False
    if (backend_type := os.environ.get('LLM_BACKEND_TYPE')) and \
       (base_url := os.environ.get('LLM_BASE_URL')) and \
       (default_model := os.environ.get('LLM_DEFAULT_MODEL')):
        
        is_single_backend_mode = True
        app.logger.info("Mode de configuration 'backend unique' détecté via les variables d'environnement.")
        app.logger.info(" -> Surcharge de 'llm_backends', 'primary_backend_name' et 'high_availability_strategy'.")
        
        single_backend = {
            "name": "default",
            "type": backend_type,
            "base_url": base_url,
            "default_model": default_model,
            "api_key": os.environ.get('LLM_API_KEY'),
            "llm_auto_load": os.environ.get('LLM_AUTO_LOAD', 'false').lower() in ('true', '1', 't')
        }
        config['llm_backends'] = [single_backend]
        config['primary_backend_name'] = "default"
        config['high_availability_strategy'] = "none"

    # Scénario 2: Surcharge individuelle des autres paramètres
    # Mappage des variables d'environnement aux clés de configuration
    env_to_config_map = {
        'FLASK_SECRET_KEY': 'FLASK_SECRET_KEY',
        'CELERY_BROKER_URL': 'CELERY_BROKER_URL',
        'CELERY_RESULT_BACKEND': 'CELERY_RESULT_BACKEND',
        'SEARXNG_BASE_URL': 'SEARXNG_BASE_URL',
        'LOG_LEVEL': 'LOG_LEVEL',
        'LOG_ROTATION_DAYS': 'LOG_ROTATION_DAYS',
        'PRIMARY_BACKEND_NAME': 'primary_backend_name',
        'HIGH_AVAILABILITY_STRATEGY': 'high_availability_strategy',
        'RATELIMIT_DEFAULT': 'RATELIMIT_DEFAULT',
        'RATELIMIT_STORAGE_URI': 'RATELIMIT_STORAGE_URI',
        'LLM_CACHE_MIN_UPDATE': 'llm_cache_update_interval_minutes',
        'LLM_BACKEND_TIMEOUT': 'LLM_BACKEND_TIMEOUT',
        'SYSTEM_ADMIN_EMAIL': 'SYSTEM_ADMIN_EMAIL',
    }

    for env_key, config_key in env_to_config_map.items():
        # Ne pas surcharger les paramètres HA si le mode backend unique est actif
        if is_single_backend_mode and config_key in ['primary_backend_name', 'high_availability_strategy']:
            continue

        if (env_value := os.environ.get(env_key)) is not None:
            if config.get(config_key) != env_value:
                app.logger.info(f"  -> Surcharge de '{config_key}' avec la variable d'environnement '{env_key}'.")
            config[config_key] = env_value

    # Logique de surcharge spécifique pour REDIS_URL (a la priorité la plus haute pour l'infra)
    if redis_url_from_env := os.environ.get('REDIS_URL'):
        app.logger.info(f"La variable d'environnement REDIS_URL est définie. Elle configure tous les services Redis.")
        config['CELERY_BROKER_URL'] = redis_url_from_env
        config['CELERY_RESULT_BACKEND'] = redis_url_from_env
        config['CACHE_REDIS_URL'] = redis_url_from_env
        config['RATELIMIT_STORAGE_URI'] = redis_url_from_env
        config['CACHE_TYPE'] = 'RedisCache'
    elif not config.get('CELERY_BROKER_URL'):
        # Si, après toutes les surcharges, aucune URL Redis n'est définie, on passe en mode dégradé.
        app.logger.warning("Aucune URL Redis n'est configurée (ni via REDIS_URL, ni via config.json).")
        app.logger.warning("Le cache, le rate-limiter et Celery ne fonctionneront pas avec Redis.")
        config['CACHE_TYPE'] = 'SimpleCache'
        config.setdefault('RATELIMIT_STORAGE_URI', 'memory://')


    
    # Scénario 3: Surcharge de la configuration des clés API
    # Priorité 1: Clé unique simple via API_KEY
    if api_key_value := os.environ.get('API_KEY'):
        app.logger.info("Mode de configuration 'clé API unique' détecté via la variable d'environnement 'API_KEY'.")

        # Vérifier si la variable contient un chemin de fichier (comme un secret Docker)
        if os.path.exists(api_key_value):
            app.logger.info(f" -> La variable API_KEY pointe vers un fichier. Lecture de '{api_key_value}'.")
            with open(api_key_value) as key_file:
                api_key_value = key_file.read().strip()
        else:
            app.logger.info(" -> La variable API_KEY est utilisée directement comme clé.")

        rate_limit = os.environ.get('API_KEY_RATE_LIMIT', '100/hour')
        app.logger.info(f" -> Clé unique configurée avec un rate_limit de '{rate_limit}'.")
        config['api_keys'] = [
            {"key": api_key_value, "owner": "default_user", "rate_limit": rate_limit}
        ]
    # Priorité 2: Configuration multi-clés via API_KEYS_JSON
    elif api_keys_json_str := os.environ.get('API_KEYS_JSON'):
        app.logger.info("Tentative de surcharge de 'api_keys' avec la variable d'environnement 'API_KEYS_JSON'.")
        try:
            api_keys_from_env = json.loads(api_keys_json_str)
            if isinstance(api_keys_from_env, list):
                config['api_keys'] = api_keys_from_env
        except json.JSONDecodeError:
            app.logger.error("La variable d'environnement 'API_KEYS_JSON' contient un JSON invalide.")
    # Si aucune variable d'environnement n'est définie, la configuration de config.json est utilisée.
    
    # 3. Gérer la clé secrète avec la plus haute priorité (Docker Secrets)
    secret_key_source = "non définie"
    secret_key_value = config.get('FLASK_SECRET_KEY') # Valeur de base (json/env)

    if secret_path := os.environ.get('FLASK_SECRET_KEY_FILE'):
        app.logger.info(f"Tentative de chargement de la clé secrète depuis le fichier : {secret_path}")
        if os.path.exists(secret_path):
            with open(secret_path) as secret_file:
                secret_key_value = secret_file.read().strip()
            secret_key_source = f"fichier secret ({os.path.basename(secret_path)})"
        else:
            app.logger.warning(f"Le fichier secret '{secret_path}' n'a pas été trouvé.")
    elif secret_key_value:
        secret_key_source = "config.json ou variable d'environnement"

    # 4. Appliquer la configuration finale
    config['SECRET_KEY'] = secret_key_value # Clé Flask
    
    # Utiliser update() pour charger toutes les clés, y compris celles en minuscules.
    app.config.update(config)

    # Mapper les clés de configuration vers les clés attendues par Celery/SocketIO
    if broker_url := app.config.get('CELERY_BROKER_URL'):
        app.config['broker_url'] = broker_url
        app.config['message_queue'] = broker_url
    if result_backend := app.config.get('CELERY_RESULT_BACKEND'):
        app.config['result_backend'] = result_backend

    # --- Configuration de la journalisation (AVANT de logger la config) ---
    configure_logging(app)
    configure_audit_logging(app)

    # --- Journalisation de la configuration finale ---
    app.logger.info("="*50)
    app.logger.info("Configuration finale de l'AI Gateway chargée :")
    app.logger.info(f"  - Flask Secret Key: {'Définie' if app.config.get('SECRET_KEY') else 'Non définie'} (source: {secret_key_source})")
    app.logger.info(f"  - Cache Type: {app.config.get('CACHE_TYPE')}")
    app.logger.info(f"  - Celery Broker URL: {app.config.get('CELERY_BROKER_URL')}")
    app.logger.info(f"  - Celery Result Backend: {app.config.get('CELERY_RESULT_BACKEND')}")
    app.logger.info(f"  - SearXNG Base URL: {app.config.get('SEARXNG_BASE_URL')}")
    app.logger.info(f"  - Log Level: {app.config.get('LOG_LEVEL')}")
    app.logger.info(f"  - Log Rotation Days: {app.config.get('LOG_ROTATION_DAYS')}")
    app.logger.info(f"  - LLM Backends: {len(app.config.get('llm_backends', []))} backend(s) configuré(s)")
    for backend in app.config.get('llm_backends', []):
        app.logger.info(f"    - Backend: {backend.get('name')}")
        app.logger.info(f"      - Type: {backend.get('type')}")
        app.logger.info(f"      - URL: {backend.get('base_url')}")
        app.logger.info(f"      - Default Model: {backend.get('default_model')}")
        app.logger.info(f"      - Auto Load Models: {backend.get('llm_auto_load')}")
    app.logger.info(f"  - Primary Backend: {app.config.get('primary_backend_name')}")
    app.logger.info(f"  - High Availability Strategy: {app.config.get('high_availability_strategy')}")
    app.logger.info(f"  - Rate Limit Default: {app.config.get('RATELIMIT_DEFAULT', 'non défini')}")
    app.logger.info(f"  - Rate Limit Storage: {app.config.get('RATELIMIT_STORAGE_URI', 'en mémoire')}")
    app.logger.info(f"  - System Admin Email: {app.config.get('SYSTEM_ADMIN_EMAIL', 'non défini')}")
    app.logger.info("="*50)

    # --- Initialisation des modules et extensions ---

    # Pré-calculer le dictionnaire de clés API pour des recherches rapides
    from .auth import _initialize_api_keys
    _initialize_api_keys(app)

    # Initialiser Flask-Caching
    flask_cache.init_app(app)

    # Initialiser Flask-Limiter
    # Les limites sont lues depuis la configuration de l'application (ex: RATELIMIT_DEFAULT)
    limiter.init_app(app)

    # Initialiser SocketIO (uniquement pour le serveur web)
    if init_socketio:
        # La configuration (message_queue, etc.) est lue depuis app.config
        socketio.init_app(
            app, 
            cors_allowed_origins="*" # Autorise toutes les origines
        )

    # Enregistrer les Blueprints
    from . import routes
    app.register_blueprint(routes.bp)

    # Enregistrer les gestionnaires d'événements SocketIO
    if init_socketio:
        from . import events  # noqa: F401 (force l'import pour enregistrer les handlers)

    return app
