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

1.  **Variables d'environnement (recommandé pour la production)**
2.  Fichier `config/config.json` (pour le développement local)

### Variables d'environnement
Le Gateway peut être entièrement configuré via des variables d'environnement.

#### Authentification & Sécurité

-   **Mode Simple (1 clé API) :**
    -   `API_KEY`: La clé API que les clients utiliseront.
    -   `API_KEY_RATE_LIMIT`: (Optionnel) La limite de requêtes pour cette clé (ex: `"100/hour"`).
-   **Mode Avancé (multiples clés) :**
    -   `API_KEYS_JSON`: Une chaîne JSON contenant une liste d'objets de clés. A la priorité sur `API_KEY`.
-   **Clé secrète Flask :**
    -   `FLASK_SECRET_KEY`: Clé secrète pour signer les sessions.
    -   `FLASK_SECRET_KEY_FILE`: (Recommandé pour Docker) Chemin vers un fichier contenant la clé secrète. A la priorité sur `FLASK_SECRET_KEY`.

#### Backend LLM (Mode Simple)

-   **Mode Simple (1 backend) :**
    -   `LLM_BACKEND_TYPE`: Type de backend (`ollama`, `openai`).
    -   `LLM_BASE_URL`: URL de base de l'API du backend.
    -   `LLM_DEFAULT_MODEL`: Modèle à utiliser par défaut.
    -   `LLM_API_KEY`: (Optionnel) Clé API pour le backend LLM lui-même.
    -   `LLM_AUTO_LOAD`: (Optionnel, pour `ollama`) `true` pour charger automatiquement les modèles en mémoire. Par défaut : `false`.
-   **Mode Avancé (Haute Disponibilité) :**
    -   `PRIMARY_BACKEND_NAME`: Nom du backend principal à utiliser (doit correspondre à un nom dans `config.json`).
    -   `HIGH_AVAILABILITY_STRATEGY`: Stratégie de haute disponibilité (`none`, `failover`).

#### Services Externes

-   **Celery (Tâches asynchrones) :**
    -   `CELERY_BROKER_URL`: URL du broker Redis (ex: `redis://localhost:6379/0`).
    -   `CELERY_RESULT_BACKEND`: URL du backend de résultats Redis (ex: `redis://localhost:6379/0`).
-   **Recherche Web :**
    -   `SEARXNG_BASE_URL`: URL de base de votre instance SearXNG.

#### Journalisation (Logging)

-   `LOG_LEVEL`: Niveau de journalisation (`DEBUG`, `INFO`, `WARNING`, `ERROR`). Par défaut : `INFO`.
-   `LOG_ROTATION_DAYS`: Nombre de jours de rétention des fichiers de log. Par défaut : `7`.

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
