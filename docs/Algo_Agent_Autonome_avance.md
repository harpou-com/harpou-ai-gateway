# Algorithme d'Agent Autonome avec Gestion des Tâches Longues

Ce document décrit un algorithme basé sur une boucle de raisonnement pour permettre à un agent IA de résoudre des problèmes complexes en plusieurs étapes, tout en gérant les tâches longues de manière non-bloquante.

## Principe Fondamental

Au lieu d'une chaîne d'actions prédéfinie, l'agent opère dans une boucle. Après chaque action, un **LLM Planificateur** (le "middleware") analyse l'état complet de la situation (question initiale, actions passées, résultats obtenus) et décide de la prochaine étape. Il est le seul à pouvoir mettre fin à la boucle pour passer à la synthèse finale.

## Gestion des Ressources et Tâches Longues

Pour garantir une bonne expérience utilisateur et éviter des attentes interminables, l'agent opère avec un "budget" de ressources pour chaque requête synchrone.

*   **Budget :** Un nombre maximum d'itérations (sauts, ex: 5) ou un temps d'exécution maximum (ex: 45 secondes).
*   **Décision Asynchrone :** Si le budget est dépassé, ou si le Planificateur anticipe une tâche longue (comme une recherche profonde), il peut prendre une nouvelle décision : `continue_in_background(reason)`.
*   **Action de l'Orchestrateur :**
    1.  L'Orchestrateur informe immédiatement l'utilisateur que sa demande est complexe et sera traitée en arrière-plan.
    2.  Il signale qu'un système de notification (futur) préviendra l'utilisateur lorsque le résultat sera prêt.
    3.  La tâche de fond (Celery) **continue sa boucle de raisonnement** jusqu'à ce que le Planificateur décide de `synthesize_answer`.

## Déroulement de la Boucle

### Étape 1 : Initialisation de la Boucle

1.  L'**Orchestrateur** reçoit la requête de l'utilisateur.
2.  Il prépare le contexte initial (uniquement la question de l'utilisateur) et entre dans la **Boucle de Raisonnement**.

### Étape 2 : Planification (Cœur de la Boucle)

1.  L'**Orchestrateur** vérifie si le budget (temps/itérations) est dépassé. Si oui, il peut forcer une décision `continue_in_background`.
2.  Il appelle le **LLM Planificateur** avec le contexte actuel.
3.  **Instruction au Planificateur :** "Étant donné l'objectif final et l'historique, quelle est la prochaine action la plus logique ? Tes choix sont :
    *   `call_tool(tool_name, parameters)` pour obtenir plus d'informations.
    *   `synthesize_answer(reason)` si tu estimes avoir toutes les informations nécessaires pour répondre à la question initiale.
    *   `continue_in_background(reason)` si tu estimes que la tâche est trop longue ou complexe pour une réponse immédiate."

### Étape 3 : Exécution de l'Action

1.  L'**Orchestrateur** reçoit la décision du Planificateur.
2.  **Si la décision est `call_tool`** :
    *   Il exécute l'outil spécifié (ex: `search_web`).
    *   Il ajoute le résultat de l'outil à l'historique du contexte.
    *   Il **retourne à l'Étape 2 (Planification)** avec le contexte mis à jour.
3.  **Si la décision est `continue_in_background`** :
    *   L'Orchestrateur retourne une réponse immédiate à l'utilisateur pour l'informer du traitement en arrière-plan.
    *   La boucle **continue immédiatement à l'Étape 2** pour que le Planificateur décide de la prochaine *vraie* action à exécuter.
3.  **Si la décision est `synthesize_answer`** :
    *   Il **sort de la boucle**.

### Étape 4 : Synthèse Finale (Post-Boucle)

1.  L'**Orchestrateur** appelle un **LLM de Synthèse** avec l'historique complet et finalisé.
2.  Le LLM de Synthèse rédige une réponse naturelle pour l'utilisateur en se basant sur toutes les informations collectées.

---

### Scénario 1 : Requête Simple
**Requête :** "Quelle est la température à Laval, QC sur MétéoMédia ?"
*   **Itération 1 :** `call_tool('search_web', ...)`
*   **Itération 2 :** `call_tool('read_webpage', ...)`
*   **Itération 3 :** `synthesize_answer(...)` -> Réponse directe à l'utilisateur.

### Scénario 2 : Recherche Profonde (Deep Research) et Passage en Asynchrone
**Requête :** "Trouve le meilleur prix au Canada pour la TV Samsung 80\" QN80C."

*   **Itération 1 :** `call_tool('search_web', {'query': 'prix TV Samsung 80" QN80C Canada'})`. L'outil retourne des liens vers Best Buy, Amazon, etc.
*   **Itération 2 :** `call_tool('read_webpage', {'url': 'https://www.bestbuy.ca/...'})`.
*   **Itération 3 :** Le Planificateur voit que le temps d'exécution est proche de la limite.
    *   **Décision :** `continue_in_background(reason='La recherche comparative des prix est longue, je continue en arrière-plan.')`.
    *   **Orchestrateur :** Renvoie immédiatement à l'utilisateur : "Votre recherche de prix est complexe. Je continue le travail et vous notifierai du résultat."
    *   **ET** la boucle continue. Le planificateur décide de sa prochaine action réelle.
    *   **Décision (interne) :** `call_tool('read_webpage', {'url': 'https://www.amazon.ca/...'})`.
*   **Itération 4 :** Le Planificateur a maintenant 2 prix, il les compare et décide qu'il a assez d'informations.
    *   **Décision :** `synthesize_answer(reason='Comparaison de prix terminée.')`.
    *   L'Orchestrateur sort de la boucle.
*   **Synthèse Finale (Asynchrone) :** Le résultat est envoyé au système de notification (futur) pour l'utilisateur.