#!/bin/sh
# Ce script gère l'initialisation de l'environnement de développement.

set -e # Arrête le script si une commande échoue.

echo "--- Vérification de l'environnement d'exécution ---"

# Étape 1: Installer les outils de base (gosu, pdm) sur CHAQUE conteneur.
# C'est rapide et idempotent.
if ! command -v gosu >/dev/null 2>&1 || ! command -v pdm >/dev/null 2>&1; then
    echo " -> Installation des outils de base (gosu, pdm)..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false
    apt-get install -y --no-install-recommends debian-archive-keyring
    apt-get update
    apt-get install -y --no-install-recommends gosu
    pip install --no-cache-dir pdm
    rm -rf /var/lib/apt/lists/*
fi

# Créer l'utilisateur et le groupe s'ils sont manquants (opération idempotente)
echo " -> Vérification de l'utilisateur 'appuser'..."
if ! getent group appgroup >/dev/null; then
    addgroup --system --gid 1000 appgroup
fi
if ! id -u appuser >/dev/null 2>&1; then
    adduser --system --home /home/appuser --uid 1000 --ingroup appgroup appuser
fi

# --- Fonction pour vérifier et réparer greenlet ---
# Cette fonction est essentielle car greenlet est une dépendance compilée
# et peut être corrompue si le volume /app est partagé entre des machines
# d'architectures différentes (ex: hôte Mac M1 ARM64 et conteneur AMD64).
check_and_repair_greenlet() {
    echo "[$(hostname)] -> Vérification de l'intégrité de greenlet..."
    if ! gosu appuser pdm run python -c "import greenlet._greenlet" > /dev/null 2>&1; then
        echo "[$(hostname)] AVERTISSEMENT: L'installation de 'greenlet' semble corrompue." >&2

        # Utiliser un verrou spécifique pour la réinstallation pour éviter les conflits
        local GREENLET_LOCK_DIR="/app/greenlet_repair.lock"
        if mkdir "$GREENLET_LOCK_DIR" 2>/dev/null; then
            echo "[$(hostname)] -> Verrou acquis. Tentative de réinstallation de greenlet..."
            # Si greenlet est corrompu, il est très probable que toutes les autres dépendances
            # compilées le soient aussi (ex: pydantic-core, lxml).
            # La solution la plus robuste est de supprimer tout l'environnement et de le recréer.
            echo "[$(hostname)] -> Suppression de l'environnement __pypackages__ pour forcer la réinstallation complète."
            # Utiliser 'mv' puis 'rm' en arrière-plan est plus robuste sur certains
            # systèmes de fichiers montés (comme les volumes Docker) qui peuvent avoir des problèmes de verrouillage.
            if [ -d "/app/__pypackages__" ]; then
                mv /app/__pypackages__ /app/__pypackages_old__ && rm -rf /app/__pypackages_old__ &
            fi
            
            echo "[$(hostname)] -> Lancement de 'pdm install' pour restaurer l'environnement..."
            gosu appuser pdm install --no-lock --no-editable
            rmdir "$GREENLET_LOCK_DIR" 2>/dev/null || true
        else
            echo "[$(hostname)] -> Un autre conteneur répare greenlet. En attente..."
            while [ -d "$GREENLET_LOCK_DIR" ]; do sleep 1; done
            echo "[$(hostname)] -> Réparation par un autre conteneur terminée."
        fi

        # Vérifier à nouveau après la tentative de réinstallation
        if ! gosu appuser pdm run python -c "import greenlet._greenlet" > /dev/null 2>&1; then
            echo "[$(hostname)] ERREUR FATALE: La réinstallation de 'greenlet' a échoué. Le conteneur va s'arrêter." >&2
            exit 1
        fi
        echo "[$(hostname)] -> L'intégrité de 'greenlet' est maintenant correcte."
    else
        echo "[$(hostname)] -> L'installation de 'greenlet' est correcte."
    fi
}

# --- Étape 2: Installation des dépendances (logique améliorée pour éviter les blocages) ---
if [ -f "/app/setup_done.flag" ]; then
  echo "[$(hostname)] --- Dépendances déjà installées. Démarrage direct. ---"
else
  LOCK_DIR="/app/setup.lock"

  if mkdir "$LOCK_DIR" 2>/dev/null; then
    # Le verrou est acquis.
    echo "[$(hostname)] a acquis le verrou et commence l'installation..."

    # Installer les paquets système nécessaires UNIQUEMENT pour la compilation des dépendances Python.
    echo "[$(hostname)] -> Installation des paquets de compilation (build-essential, etc.)..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get clean
    # Met à jour les listes de paquets en ignorant les dates de validité pour éviter les erreurs GPG dues à l'horloge
    apt-get update -o Acquire::Check-Valid-Until=false -o Acquire::Check-Date=false
    # Installe le porte-clés officiel pour s'assurer que les signatures sont valides
    apt-get install -y --no-install-recommends debian-archive-keyring
    apt-get update # Met à jour à nouveau avec les bonnes clés
    apt-get install -y --no-install-recommends build-essential python3-dev procps libxml2-dev libxslt-dev
    rm -rf /var/lib/apt/lists/*

    # Créer le dossier de logs et s'assurer qu'il appartient à appuser
    # C'est important pour Celery Beat qui doit écrire son fichier de schedule.
    echo "[$(hostname)] -> Préparation du dossier de logs..."
    mkdir -p /app/logs
    chown appuser:appgroup /app/logs

    # Installer les dépendances Python
    echo "[$(hostname)] -> Installation des paquets Python (peut prendre du temps)..."
    gosu appuser pdm install --no-lock --no-editable

    check_and_repair_greenlet

    # Marquer l'installation comme terminée
    echo "[$(hostname)] -> Installation terminée. Création du fichier de statut et libération du verrou."
    touch /app/setup_done.flag
    chown appuser:appgroup /app/setup_done.flag
    rmdir "$LOCK_DIR" 2>/dev/null || true
  else
    echo "[$(hostname)] -> Un autre service effectue l'installation. En attente..."



    while [ -d "$LOCK_DIR" ]; do
      sleep 2
    done
    echo "[$(hostname)] -> Installation terminée par l'autre service. Démarrage."
  fi
fi

# Vérification finale de greenlet avant l'exécution, pour tous les conteneurs.
check_and_repair_greenlet

# --- Étape 3: Lancement de l'application ---
echo "[$(hostname)] --- Toutes les dépendances sont prêtes. Lancement de la commande : $@ ---"
exec gosu appuser "$@"