```mermaid
graph TD
    subgraph "Interface Utilisateur"
        A[Client WebUI]
    end

    subgraph "HARPOU AI Gateway (Orchestrateur)"
        B(Point d'Entrée: /chat)
        
        subgraph "Boîte à Outils (Tâches Celery)"
            C(Tâche Orchestrateur)
            G(Outil: search_web)
            I(Tâche: Synthèse)
        end
    end

    subgraph "Services Externes"
        D{"LLM Frontend - Décision"}
        J{"LLM Agent - Synthèse"}
        H((API SearXNG))
    end

    A -- "Requête Utilisateur" --> B;
    B -- "Lance" --> C;
    C -- "Consulte (avec catalogue d'outils)" --> D;
    D -- "Réponse Texte" --> C;
    C -- "Notifie Client" --> A;

    D -- "Demande d'outil 'search_web'" --> C;
    C -- "Construit et lance la chaîne de tâches" --> G;
    G -- "Appelle" --> H;
    H -- "Retourne résultats" --> G;
    G -- "Passe le résultat à" --> I;
    I -- "Consulte (avec résultats)" --> J;
    J -- "Retourne réponse finale" --> I;
    I -- "Notifie Client de la réponse finale" --> A;

 ```