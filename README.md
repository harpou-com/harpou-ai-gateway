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

4. Développement & Déploiement
Le projet suit une approche DevOps avec deux workflows distincts :

Développement (develop branch) : Utilise un montage de volume (bind mount) et le "hot-reloading" pour une boucle de développement ultra-rapide sans reconstruction d'image.

Production (main branch) : S'appuie sur des images Docker immuables construites via un Dockerfile, garantissant la stabilité et la reproductibilité. Le déploiement est déclenché via une pipeline CI/CD ou une commande à la demande.

5. Comment Contribuer
Ce projet est actuellement en développement actif. Pour toute suggestion ou contribution, veuillez ouvrir une "issue" ou une "pull request".

Ce projet est au cœur du Hub HARPOU, une initiative visant à créer un écosystème d'IA personnel, privé et puissant.
