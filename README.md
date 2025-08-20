# HARPOU AI Gateway
Le cerveau central et l'orchestrateur agentique du Hub Domestique d'IA HARPOU.

1. Vision : Un Agent Autonome pour la Maison
L'AI Gateway n'est pas un simple proxy. C'est le cerveau central du Hub HARPOU. Il agit comme un agent autonome qui opère sur un modèle fondamentalement asynchrone :

Réception & Compréhension : Il reçoit toutes les requêtes de l'interface utilisateur (Open WebUI) et en comprend l'intention profonde.

Décision & Délégation : Il décide d'utiliser un ou plusieurs outils externes (recherche web, contrôle domotique, génération d'images, etc.) pour accomplir la tâche demandée.

Exécution Asynchrone : Il lance l'exécution de ces outils en tant que tâches de fond sans jamais bloquer l'interface, garantissant une expérience utilisateur fluide et réactive.

Notification Proactive : Il notifie l'utilisateur de manière proactive via WebSockets lorsque les résultats d'une tâche longue sont prêts.

Synthèse & Réponse : Il formule une réponse finale cohérente en se basant sur les résultats des tâches exécutées.

Cette approche garantit que le système reste réactif et scalable, que la tâche soit une simple recherche web ou une complexe génération de vidéo.

2. Architecture d'un Coup d'Œil
Ce projet est conçu pour être modulaire, scalable et robuste, en s'appuyant sur une stack technologique moderne :

Framework Web : Flask & Flask-SocketIO pour le serveur API et la communication temps réel.

Traitement Asynchrone : Celery comme moteur de tâches et Redis comme file d'attente (message broker).

Conteneurisation : Docker & Docker Swarm pour le déploiement des services.

Stockage d'Artefacts : MinIO comme solution de stockage objet compatible S3.

Gestion des Dépendances : PDM pour un environnement Python propre et reproductible.

3. Feuille de Route de Développement
Le projet évoluera en suivant les étapes clés définies dans notre document d'architecture maîtresse :

✅ Étape 1 : Fondation Asynchrone

Mise en place de la structure du projet, de Redis, MinIO, Celery et des WebSockets.

Création d'un premier flux "ping-pong" pour valider la communication entre tous les composants.

⏳ Étape 2 : Intégration des Outils de Base

Intégration de la recherche web (SearXNG) et de la lecture de pages web comme des tâches Celery.

🗓️ Étape 3 : Ajout des Outils Avancés

Intégration du contrôle de Home Assistant.

Intégration du pilotage de ComfyUI pour la génération d'images.

Développement de la recherche sur des documents personnels (RAG).

🚀 Étape 4 : Vision à Long Terme

Intégration de modèles spécialisés (vidéo, 3D, audio) en tant que nouveaux outils.

4. Configuration
La configuration de l'AI Gateway est flexible et peut être gérée de plusieurs manières, avec la priorité suivante :

1.  **Variables d'environnement** : Idéal pour la production et les déploiements Docker/Swarm. Elles surchargent les valeurs du fichier de configuration.
2.  **Fichier `config/config.json`** : C'est la source de vérité principale pour la configuration, particulièrement pour le développement local et la définition de configurations complexes comme les backends multiples.

Un fichier `config/config.example.json` est fourni comme modèle.

### Variables d'environnement
Le Gateway peut être entièrement configuré via des variables d'environnement.

> **Note Importante sur la Cohérence :** Pour garantir un fonctionnement stable et prévisible, il est crucial que tous les services (`web`, `worker`, `beat`) partagent la même configuration. Les variables d'environnement qui définissent des connexions (comme `REDIS_URL`) ou le comportement du backend (`LLM_...`) doivent être appliquées de manière identique à tous les services dans votre configuration de déploiement (ex: `docker-compose.yml` ou `ai.yml`).


#### Authentification & Sécurité

-   **`API_KEY`**: La clé API que les clients utiliseront (mode simple).
    -   Peut être une valeur directe ou un chemin vers un fichier secret (ex: `/run/secrets/api_key`).
-   **`API_KEY_RATE_LIMIT`**: (Optionnel) La limite de requêtes pour la clé unique (ex: `"100/hour"`). Par défaut : `"100/hour"`.
-   **`API_KEYS_JSON`**: (Mode avancé) Une chaîne JSON contenant une liste d'objets de clés. A la priorité sur `API_KEY`.
-   **Clé secrète Flask :**
    -   `FLASK_SECRET_KEY`: Clé secrète pour signer les sessions.
    -   `FLASK_SECRET_KEY_FILE`: (Recommandé pour Docker) Chemin vers un fichier contenant la clé secrète. A la priorité sur `FLASK_SECRET_KEY`.

#### Backend LLM (Surcharge en mode simple)

Ces variables permettent de surcharger la configuration `llm_backends` de `config.json` pour définir un unique backend par défaut. C'est utile pour des déploiements simples.

-   `LLM_BACKEND_TYPE`: Type de backend (`ollama`, `openai`).
-   `LLM_BASE_URL`: URL de base de l'API du backend.
-   `LLM_DEFAULT_MODEL`: Modèle à utiliser par défaut.
-   `LLM_API_KEY`: (Optionnel) Clé API pour le backend LLM lui-même.
-   `LLM_AUTO_LOAD`: (Optionnel) `true` pour découvrir automatiquement les modèles du backend. Par défaut : `false`.

Pour une configuration multi-backends ou de haute disponibilité, utilisez le fichier `config.json`.
-   `PRIMARY_BACKEND_NAME`: Nom du backend principal à utiliser (doit correspondre à un nom dans `config.json`).
-   `HIGH_AVAILABILITY_STRATEGY`: Stratégie de haute disponibilité (`none`, `failover`).

#### Services Externes

-   **Celery (Tâches asynchrones) :**
    -   `CELERY_BROKER_URL`: URL du broker Redis (ex: `redis://localhost:6379/0`).
    -   `CELERY_RESULT_BACKEND`: URL du backend de résultats Redis (ex: `redis://localhost:6379/0`).
-   **Recherche Web :**
    -   `SEARXNG_BASE_URL`: URL de base de votre instance SearXNG.

#### Journalisation & Performance

-   `LOG_LEVEL`: Niveau de journalisation (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Par défaut : `INFO`.
-   `LOG_ROTATION_DAYS`: Nombre de jours de rétention des fichiers de log. Par défaut : `7`.
-   `LLM_CACHE_MIN_UPDATE`: (Optionnel) Intervalle en minutes pour rafraîchir le cache de la liste des modèles. Par défaut : `5`.
-   `LLM_BACKEND_TIMEOUT`: (Optionnel) Délai d'attente en secondes pour les requêtes vers les backends LLM. Utile pour les modèles lents à charger. Par défaut : `300`.

#### Agent Autonome (Boucle de Raisonnement)

-   `REASONING_LOOP_BUDGET`: Nombre maximum d'itérations pour la boucle de raisonnement en mode synchrone. Par défaut : `5`.
-   `REASONING_TIME_BUDGET_SECONDS`: Temps maximum en secondes pour la boucle de raisonnement en mode synchrone. Par défaut : `45`.
-   `BACKGROUND_LOOP_BUDGET`: Nombre maximum d'itérations pour la boucle de raisonnement une fois passée en arrière-plan. Par défaut : `10`.
-   `FORCE_BACKGROUND_ON_BUDGET_EXCEEDED`: (`true`/`false`) Si `true`, la tâche notifiera l'utilisateur et continuera en arrière-plan lorsque le budget est épuisé. Par défaut : `true`.

#### Limitation de Débit (Rate Limiting)

-   `RATELIMIT_DEFAULT`: Limite de débit par défaut pour les routes non spécifiquement limitées (ex: `"200 per day;50 per hour"`).
-   `RATELIMIT_STORAGE_URI`: URI de stockage pour les limites (ex: `redis://localhost:6379/1`).

5. Développement & Déploiement
Le projet suit une approche DevOps avec deux workflows distincts :

Développement (develop branch) : Utilise un montage de volume (bind mount) et le "hot-reloading" pour une boucle de développement ultra-rapide sans reconstruction d'image.

Production (main branch) : S'appuie sur des images Docker immuables construites via un Dockerfile, garantissant la stabilité et la reproductibilité. Le déploiement est déclenché via une pipeline CI/CD ou une commande à la demande.

6. Comment Contribuer
Ce projet est actuellement en développement actif. Pour toute suggestion ou contribution, veuillez ouvrir une "issue" ou une "pull request".

Ce projet est au cœur du Hub HARPOU, une initiative visant à créer un écosystème d'IA personnel, privé et puissant.
