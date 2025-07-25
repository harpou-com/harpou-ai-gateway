```mermaid
graph TD
    subgraph "Clients"
        A[Client WebUI] -- "Utilise" --> P[Pipe Open WebUI]
    end

    subgraph "HARPOU AI Gateway (Orchestrateur)"
        subgraph "Couche d'Accès API (app/routes.py)"
            RT(/v1/chat/completions)
            RM(/v1/models)
            RS(/v1/tasks/status/<task_id>)
        end

        subgraph "Sécurité & Observabilité"
            AUTH{Authentification & Rate Limiting}
            ALOG(Journalisation d'Audit)
            CLOG(Logs Applicatifs)
        end
        
        subgraph "Logique de Routage & Orchestration"
            RL(Routage Intelligent: `chat_completions`)
            OT(Tâche Orchestrateur: `orchestrator_task`)
        end

        subgraph "Connecteur LLM (app/llm_connector.py)"
            LLMC(LLM Connector: `get_chat_completion`)
        end

        subgraph "Tâches de Traitement (app/tasks.py)"
            DEC(Décision LLM: `get_llm_decision`)
            SW(Outil: `search_web_task`)
            SYN(Synthèse LLM: `synthesis_task`)
        end
    end

    subgraph "Services Externes & Infrastructures"
        %% Correction: Moved comment to its own line and used slashes for robustness
        EL{Backend LLM<br>Ollama / OpenAI / LM Studio} 
        SE((API SearXNG))
        REDIS((Redis<br>Broker/Backend))
    end

    %% Flux Principaux Client -> Gateway
    P -- "Requête Chat/Agentique" --> RT
    P -- "Découverte Modèles" --> RM
    P -- "Sondage Statut Tâche" --> RS

    %% Sécurité
    RT & RM & RS -- "Protégé par" --> AUTH

    %% Routage Intelligent (depuis /v1/chat/completions)
    RT -- "Traite Payload" --> RL
    RL -- "Si harpou-agent/<model>" --> OT
    RL -- "Si modèle standard" --> LLMC

    %% Flux Agentique (via Pipe)
    OT -- "Lance Tâche Celery<br>+ stocke SID" --> REDIS
    REDIS -- "Exécution par Worker" --> C(Worker Celery)
    C -- "Exécute `orchestrator_task`" --> DEC
    DEC -- "Appelle LLM<br>(via LLMC)" --> LLMC
    LLMC -- "Décision LLM" --> DEC
    DEC -- "Si Outil requis" --> OT
    OT -- "Lance Chaîne de Tâches<br>(search_web -> synthesis)" --> REDIS
    REDIS -- "Exécuté par Worker" --> C
    C -- "Exécute `search_web_task`" --> SW
    SW -- "Appelle" --> SE
    SE -- "Retourne Résultats" --> SW
    SW -- "Passe Résultats à" --> SYN
    SYN -- "Appelle LLM<br>(via LLMC)" --> LLMC
    LLMC -- "Réponse Synthèse" --> SYN
    SYN -- "Retourne Réponse Finale" --> OT
    
    %% Réponses Agentiques vers Pipe
    OT -- "Réponse Tâche ID (HTTP 202)" --> P
    RS -- "Interroge Statut (`AsyncResult`)" --> REDIS
    REDIS -- "Statut/Résultat Tâche" --> RS
    RS -- "Retourne Statut/Résultat" --> P
    P -- "Stream Résultat à l'UI" --> A

    %% Flux Standard (via Pipe)
    LLMC -- "Appelle API LLM" --> EL
    EL -- "Réponse LLM" --> LLMC
    LLMC -- "Réponse Directe/Stream HTTP" --> P
    P -- "Stream/Affiche Réponse" --> A

    %% Journalisation
    RT & RM & RS -- "Enregistre Requête/Réponse" --> ALOG(Journalisation d'Audit)
    OT & DEC & SW & SYN & LLMC -- "Génère Logs Applicatifs" --> CLOG(Logs Applicatifs)

    %% Infrastructure de Celery
    REDIS -- "Utilisé par" --> C
    REDIS -- "Utilisé par" --> AUTH

    %% Initialisation
    subgraph "Démarrage Application (app/__init__.py)"
        INIT(Factory `create_app`)
    end
    INIT -- "Charge Config (config/config.json)" --> config_obj(Objet Configuration)
    INIT -- "Configure Logs" --> CLOG
    INIT -- "Configure Audit Logs" --> ALOG
    INIT -- "Initialise Limiter" --> AUTH
    INIT -- "Initialise Celery" --> C
    INIT -- "Initialise SocketIO" --> socketio_obj(SocketIO)
    INIT -- "Enregistre Blueprints" --> RT & RM & RS
    INIT -- "Lie SocketIO" --> socketio_obj
    SYN -- "Utilise" --> socketio_obj

    %% Styles des composants (pour la lisibilité)
    style A fill:#DDF,stroke:#333,stroke-width:2px;
    style P fill:#FFE,stroke:#333,stroke-width:2px;

    style RT fill:#DDA,stroke:#333,stroke-width:2px;
    style RM fill:#DDA,stroke:#333,stroke-width:2px;
    style RS fill:#DDA,stroke:#333,stroke-width:2px;
    
    style AUTH fill:#FFC,stroke:#333,stroke-width:2px;
    style ALOG fill:#EEF,stroke:#333,stroke-width:2px;
    style CLOG fill:#EEF,stroke:#333,stroke-width:2px;
    
    style RL fill:#CFC,stroke:#333,stroke-width:2px;
    style OT fill:#FF9,stroke:#333,stroke-width:2px;
    style LLMC fill:#F9F,stroke:#333,stroke-width:2px;
    style DEC fill:#9FF,stroke:#333,stroke-width:2px;
    style SW fill:#CCF,stroke:#333,stroke-width:2px;
    style SYN fill:#CFF,stroke:#333,stroke-width:2px;
    
    style EL fill:#BBB,stroke:#333,stroke-width:2px;
    style SE fill:#BBB,stroke:#333,stroke-width:2px;
    style REDIS fill:#BBB,stroke:#333,stroke-width:2px;
    style C fill:#BBB,stroke:#333,stroke-width:2px;

    style INIT fill:#9FF,stroke:#333,stroke-width:2px;
    style config_obj fill:#DFF,stroke:#333,stroke-width:2px;
    style socketio_obj fill:#DFF,stroke:#333,stroke-width:2px;


 ```