# HARPOU AI Gateway : Intégration avec Open WebUI

Ce guide fournit les instructions détaillées pour connecter Open WebUI à votre instance du HARPOU AI Gateway. Cela vous permettra d'interagir avec les modèles de langage standards et les agents spécialisés servis par le Gateway.

## Table des matières

*   [Prérequis](#prérequis)
*   [1. Configuration pour les Modèles de Chat Standards](#1-configuration-pour-les-modèles-de-chat-standards)
    *   [Ajout de la connexion au Gateway](#ajout-de-la-connexion-au-gateway)
    *   [Ajout manuel d'un modèle](#ajout-manuel-dun-modèle)
*   [2. Configuration pour les Modèles Agentiques (Pipe)](#2-configuration-pour-les-modèles-agentiques-pipe)
    *   [Installation et configuration du Pipe](#installation-et-configuration-du-pipe)
    *   [Utilisation des modèles agentiques](#utilisation-des-modèles-agentiques)
*   [Dépannage](#dépannage)
*   [Contribuer](#contribuer)
*   [Licence](#licence)

## Prérequis

Avant de commencer, assurez-vous d'avoir :

*   Une instance du [**HARPOU AI Gateway**](https://github.com/harpou-com/harpou-ai-gateway) en cours d'exécution et accessible sur votre réseau.
*   Une instance d'**Open WebUI** installée et fonctionnelle.
*   L'URL de base de votre Gateway (par défaut : `http://ai-gateway-dev:5000`).

## Fonctionnalités

L'intégration via ce pipe offre les avantages suivants :

*   **Accès aux Agents Spécialisés** : Lancez des tâches complexes comme `deep-research` ou `image-generation` directement depuis le chat.
*   **Exécution Asynchrone** : Les tâches longues sont exécutées en arrière-plan sans bloquer l'interface utilisateur.
*   **Notifications en Temps Réel** : Recevez des mises à jour sur l'état d'avancement de vos tâches et le résultat final directement dans la conversation.
*   **Configuration Simple** : Les paramètres clés, comme l'URL du Gateway, sont facilement configurables via les réglages d'Open WebUI.
*   **Compatibilité OpenAI** : Utilisez le Gateway comme un backend OpenAI standard pour tous vos modèles de langage de base.

## 1. Configuration pour les Modèles de Chat Standards

Pour permettre à Open WebUI d'utiliser les modèles de langage servis par le Gateway (par exemple, Llama2 via Ollama), vous devez le configurer comme une source de modèle compatible OpenAI.

### Ajout de la connexion au Gateway

1.  **Accédez aux Paramètres :** Dans l'interface d'Open WebUI, cliquez sur votre profil en bas à gauche, puis sur "Settings".
2.  **Allez dans Connexions :** Dans le menu de gauche, sélectionnez "Connections".
3.  **Ajoutez une connexion OpenAI :**
    *   Cliquez sur "Connect to another OpenAI-compatible API".
    *   **API Base URL :** Entrez l'URL de votre Gateway : `http://ai-gateway-dev:5000`.
    *   **API Key :** Laissez ce champ vide, sauf si vous avez configuré une authentification sur le Gateway.
    *   Cliquez sur "Save".

> **Note :** À ce stade, la connexion est établie, mais les modèles ne s'afficheront pas automatiquement car la route `/v1/models` n'est pas encore implémentée dans le Gateway. Vous devez les ajouter manuellement.

### Ajout manuel d'un modèle

Pour utiliser un modèle via le Gateway, vous devez spécifier son identifiant exact dans l'interface de chat.

1.  **Retournez à l'interface de Chat :** Quittez les paramètres pour revenir à l'écran principal.
2.  **Sélectionnez un Modèle :** Cliquez sur le sélecteur de modèle en haut au centre (il peut afficher "Select a model").
3.  **Entrez l'ID du Modèle :** Dans le champ de recherche qui apparaît, tapez l'identifiant complet du modèle tel que configuré dans votre Gateway. Le format est `backend_name/model_name`.
    *   Par exemple, si votre `default_model` est `llama2` et qu'il est servi par le backend `ollama-local-1`, l'identifiant à utiliser est : `ollama-local-1/llama2`.

    > **Important :** L'identifiant exact dépend de la configuration de votre fichier `config.yaml` dans le Gateway.

4.  **Commencez à chatter :** Une fois l'identifiant entré, vous pouvez commencer à envoyer des messages. Open WebUI transmettra la requête au Gateway, qui la routera vers le bon backend LLM.

## 2. Configuration pour les Modèles Agentiques (Pipe)

Pour utiliser les capacités agentiques du HARPOU AI Gateway (par exemple, pour des tâches de recherche approfondie ou de génération d'images), vous devez installer un "Pipe" dans Open WebUI. Le pipe intercepte les requêtes pour des modèles spécifiques et les traite via un script personnalisé.

### Installation et Configuration du Pipe

1.  **Accédez aux Intégrations :** Dans les paramètres d'Open WebUI ("Settings"), allez dans "Integrations".
2.  **Ouvrez la page des Pipes :** Cliquez sur le bouton "Open Pipes".
3.  **Installez le Pipe :**
    *   Cliquez sur "Add a new pipe".
    *   Copiez l'intégralité du code du fichier `harpou_ai_gateway_pipe.py`.
    *   Vous pouvez trouver la version la plus récente du code **ici**.
    *   Collez le code dans l'éditeur qui s'affiche, puis cliquez sur **Save**.
4.  **Configurez le Pipe :** Une fois sauvegardé, les options du pipe apparaissent. Assurez-vous que le champ `GATEWAY_URL` correspond bien à l'URL de votre Gateway (`http://ai-gateway-dev:5000`). Les autres valeurs peuvent généralement être laissées par défaut.

### Utilisation des Modèles Agentiques

Une fois le pipe installé et configuré, les modèles agentiques apparaîtront dans la liste des modèles d'Open WebUI.

1.  **Sélectionnez un Modèle Agentique :** Dans l'interface de chat, cliquez sur le sélecteur de modèles. Vous devriez maintenant voir les modèles définis dans le pipe, par exemple :
    *   `harpou-agent/deep-research`
    *   `harpou-agent/image-generation`
2.  **Lancez une Tâche :** Posez une question ou donnez une instruction au modèle agentique sélectionné.
3.  **Suivez la Progression :** Le pipe gère la communication asynchrone avec le Gateway. Vous recevrez un premier message confirmant le lancement, des mises à jour de statut pour les tâches longues, et enfin le résultat final directement dans le chat.

## Dépannage

*   **Erreur de connexion au Gateway :**
    *   Vérifiez que l'URL (`http://ai-gateway-dev:5000`) est correcte et accessible depuis votre instance Open WebUI.
    *   Si vous utilisez Docker, assurez-vous que les deux conteneurs sont sur le même réseau Docker.
    *   Vérifiez les logs du conteneur du Gateway pour d'éventuelles erreurs au démarrage.

*   **Les modèles agentiques n'apparaissent pas :**
    *   Assurez-vous que le pipe a été correctement sauvegardé et qu'il n'y a pas d'erreurs de syntaxe.
    *   Rafraîchissez la page d'Open WebUI après avoir sauvegardé le pipe.
    *   Vérifiez que le préfixe dans les réglages du pipe (`AGENT_MODEL_PREFIX`) correspond à celui attendu.

*   **Les conversations avec les modèles standards échouent :**
    *   Vérifiez que l'identifiant du modèle (`backend_name/model_name`) est exact et correspond à votre `config.yaml`.
    *   Assurez-vous que le backend LLM (par ex. Ollama) est bien en cours d'exécution et que le Gateway peut y accéder.

## Contribuer

Les contributions sont les bienvenues ! Pour des modifications majeures, veuillez ouvrir une "issue" au préalable pour discuter de ce que vous souhaitez changer.

Veuillez vous assurer de mettre à jour les tests le cas échéant.

## Licence

MIT