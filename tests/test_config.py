import os
import json
import unittest
import logging
from unittest.mock import patch, mock_open, MagicMock

from app import create_app, configure_logging

class ConfigTestCase(unittest.TestCase):

    def setUp(self):
        """
        Patche les I/O sur fichier et la config du logging avant chaque test.
        Ceci est CRUCIAL pour éviter les blocages sur les volumes réseau (CIFS/NFS)
        en simulant les appels système qui interagissent avec le filesystem.
        """
        # Patch pour `os.path.abspath` qui est appelé dans create_app
        self.abspath_patch = patch('os.path.abspath', return_value='/app')
        self.mock_abspath = self.abspath_patch.start()

        # Patch pour la fonction de configuration du logging
        self.configure_logging_patch = patch('app.configure_logging')
        self.mock_configure_logging = self.configure_logging_patch.start()

    def tearDown(self):
        """Arrête le patch et nettoie les handlers de logging après chaque test."""
        self.abspath_patch.stop()
        self.configure_logging_patch.stop()
        # Nettoyage supplémentaire pour s'assurer qu'aucun handler ne persiste
        for handler in logging.getLogger().handlers[:]:
            handler.close()
            logging.getLogger().removeHandler(handler)

    # Configuration simulée pour config.json, avec la nouvelle structure
    mock_config_data = json.dumps({
        "llm_backends": [
            {
                "name": "ollama_local",
                "type": "ollama",
                "base_url": "http://ollama-from-file:11434",
                "default_model": "llama3-from-file",
                "llm_auto_load": True
            }
        ],
        "primary_backend_name": "ollama_local",
        "high_availability_strategy": "failover",
        "CELERY_BROKER_URL": "redis://file-redis:6379/0",
        "FLASK_SECRET_KEY": "secret_from_file",
        "SEARXNG_BASE_URL": "http://searxng-from-file.com",
        "LOG_LEVEL": "INFO",
        "LOG_ROTATION_DAYS": "7"
    })

    # Utilise clear=True pour s'assurer que le test s'exécute dans un environnement propre,
    # sans hériter des variables du conteneur Docker.
    @patch.dict(os.environ, {}, clear=True)
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=mock_config_data)
    def test_load_from_file_with_new_structure(self, mock_file, mock_exists):
        """
        Valide le chargement correct depuis config.json avec la nouvelle structure,
        y compris la liste llm_backends et llm_auto_load.
        """
        app = create_app(init_socketio=False)
        # Vérifier la structure des backends LLM
        self.assertIn('llm_backends', app.config)
        self.assertEqual(len(app.config['llm_backends']), 1)
        backend = app.config['llm_backends'][0]
        self.assertEqual(backend['name'], 'ollama_local')
        self.assertEqual(backend['type'], 'ollama')
        self.assertEqual(backend['base_url'], 'http://ollama-from-file:11434')
        self.assertEqual(backend['default_model'], 'llama3-from-file')
        self.assertTrue(backend['llm_auto_load'])
        # Vérifier les autres paramètres de configuration du fichier
        self.assertEqual(app.config['primary_backend_name'], 'ollama_local')
        self.assertEqual(app.config['high_availability_strategy'], 'failover')
        self.assertEqual(app.config['CELERY_BROKER_URL'], 'redis://file-redis:6379/0')
        self.assertEqual(app.config['SECRET_KEY'], 'secret_from_file')
        self.assertEqual(app.config['SEARXNG_BASE_URL'], 'http://searxng-from-file.com')
        self.assertEqual(app.config['LOG_LEVEL'], 'INFO')
        self.assertEqual(app.config['LOG_ROTATION_DAYS'], '7')

    @patch.dict(os.environ, {
        # Variables pour le mode de surcharge simplifié
        'LLM_BACKEND_TYPE': 'openai_env',
        'LLM_BASE_URL': 'http://openai-from-env:8080',
        'LLM_DEFAULT_MODEL': 'gpt4-from-env',
        'LLM_API_KEY': 'key-from-env',
        'LLM_AUTO_LOAD': 'false' # Test de la conversion en booléen
    }, clear=True)
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=mock_config_data)
    def test_simplified_env_override_for_single_backend(self, mock_file, mock_exists):
        """
        Valide la surcharge par les variables d'environnement simplifiées.
        Vérifie que llm_backends est remplacé, que HA est désactivée,
        et que llm_auto_load est correctement interprété.
        """
        app = create_app(init_socketio=False)

        # Vérifie que la liste des backends a été entièrement remplacée
        self.assertEqual(len(app.config['llm_backends']), 1)
        backend = app.config['llm_backends'][0]
        self.assertEqual(backend['name'], 'default')
        self.assertEqual(backend['type'], 'openai_env')
        self.assertEqual(backend['base_url'], 'http://openai-from-env:8080')
        self.assertEqual(backend['default_model'], 'gpt4-from-env')
        self.assertEqual(backend['api_key'], 'key-from-env')
        self.assertFalse(backend['llm_auto_load']) # Doit être False

        # Vérifie que la stratégie HA a été surchargée
        self.assertEqual(app.config['primary_backend_name'], 'default')
        self.assertEqual(app.config['high_availability_strategy'], 'none')

        # Vérifie qu'une autre valeur du fichier (non surchargée) est toujours présente
        self.assertEqual(app.config['SECRET_KEY'], 'secret_from_file')

    @patch.dict(os.environ, {
        # Surcharger uniquement les variables de niveau supérieur
        'SEARXNG_BASE_URL': 'http://searxng-from-env.com',
        'LOG_LEVEL': 'DEBUG',
        'LOG_ROTATION_DAYS': '30',
        'CELERY_BROKER_URL': 'redis://env-redis:6379/1'
    }, clear=True)
    @patch('os.path.exists', return_value=True)
    @patch('builtins.open', new_callable=mock_open, read_data=mock_config_data)
    def test_toplevel_env_vars_override_file_config(self, mock_file, mock_exists):
        """
        Valide que les variables d'environnement de niveau supérieur
        (LOG_LEVEL, SEARXNG_BASE_URL, etc.) surchargent bien config.json,
        sans affecter la structure llm_backends.
        """
        app = create_app(init_socketio=False)

        # Vérifier que les valeurs ont été surchargées par les variables d'environnement
        self.assertEqual(app.config['SEARXNG_BASE_URL'], 'http://searxng-from-env.com')
        self.assertEqual(app.config['LOG_LEVEL'], 'DEBUG')
        self.assertEqual(app.config['LOG_ROTATION_DAYS'], '30')
        self.assertEqual(app.config['CELERY_BROKER_URL'], 'redis://env-redis:6379/1')

        # Vérifier que les valeurs du fichier non surchargées sont toujours là
        self.assertEqual(len(app.config['llm_backends']), 1)
        self.assertEqual(app.config['llm_backends'][0]['name'], 'ollama_local')
        self.assertEqual(app.config['primary_backend_name'], 'ollama_local')
        self.assertEqual(app.config['SECRET_KEY'], 'secret_from_file')

    @patch.dict(os.environ, {
        'FLASK_SECRET_KEY_FILE': '/run/secrets/my_secret',
    }, clear=True)
    @patch('os.path.exists')
    @patch('builtins.open')
    def test_docker_secret_has_highest_priority(self, mock_open_call, mock_exists):
        """Teste que la clé secrète est chargée depuis un secret Docker en priorité."""
        # Définir les chemins attendus (prévisibles grâce au mock de abspath)
        config_file_path = '/app/config/config.json'
        secret_file_path = '/run/secrets/my_secret'

        # Simuler que les deux fichiers existent
        mock_exists.side_effect = lambda path: path in [config_file_path, secret_file_path]

        # Configurer le mock pour retourner des contenus différents selon le fichier ouvert
        def open_side_effect(path, *args, **kwargs):
            if path == config_file_path:
                return mock_open(read_data=self.mock_config_data).return_value
            if path == secret_file_path:
                return mock_open(read_data='secret_from_docker_secret').return_value
            return mock_open().return_value  # Fallback

        mock_open_call.side_effect = open_side_effect

        app = create_app(init_socketio=False)

        # La clé doit provenir du fichier secret, pas de mock_config_data ('secret_from_file')
        self.assertEqual(app.config['SECRET_KEY'], 'secret_from_docker_secret')

    @patch('os.makedirs')
    @patch('logging.getLogger')
    @patch('app.TimedRotatingFileHandler')
    def test_logging_configuration(self, mock_timed_handler, mock_get_logger, mock_makedirs):
        """Vérifie que la journalisation est configurée avec rotation, de manière isolée."""
        # Ce test n'utilise pas les mocks de os.path.exists ou os.environ,
        # car nous fournissons une configuration simulée directement.

        # 1. Créer un objet 'app' simulé avec la configuration nécessaire.
        mock_app = MagicMock()
        # Simuler le dictionnaire de configuration
        mock_app.config = {
            'LOG_LEVEL': 'DEBUG',
            'LOG_ROTATION_DAYS': '14'
        }
        # Fournir un chemin racine plausible pour que os.path.join fonctionne
        mock_app.root_path = '/app/app'

        # 2. Simuler le logger racine qui sera retourné par getLogger()
        mock_root_logger = MagicMock()
        mock_get_logger.return_value = mock_root_logger

        # 3. Appeler la fonction à tester directement, en contournant create_app
        configure_logging(mock_app)

        # 4. Assertions
        # Vérifier que les fonctions I/O simulées ont été appelées
        self.mock_abspath.assert_called()
        mock_makedirs.assert_called_once()

        # Vérifier que le handler a été créé avec les bons paramètres
        mock_timed_handler.assert_called_once()
        args, kwargs = mock_timed_handler.call_args
        # Le chemin est dynamique, on vérifie juste la fin
        self.assertTrue(args[0].endswith(os.path.join('logs', 'app.log')))
        self.assertEqual(kwargs['when'], 'midnight')
        self.assertEqual(kwargs['backupCount'], 14) # Doit être un entier
        self.assertEqual(kwargs['encoding'], 'utf-8')

        # Vérifier que le logger racine a été configuré correctement
        mock_get_logger.assert_called_with() # Appelé sans argument pour le logger racine
        mock_root_logger.handlers.clear.assert_called_once()
        mock_root_logger.addHandler.assert_called_once_with(mock_timed_handler.return_value)
        mock_root_logger.setLevel.assert_called_once_with(logging.DEBUG)