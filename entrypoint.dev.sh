#!/bin/sh
# Ce script gère l'initialisation de l'environnement de développement.

set -e # Arrête le script si une commande échoue.

# --- Étape 1: Préparation de l'environnement du conteneur (à chaque démarrage) ---
# Ces commandes sont rapides et garantissent que l'environnement est prêt,
# même si le conteneur est recréé à partir d'une image vierge.

echo "--- Vérification de l'environnement d'exécution ---"
# Installer gosu s'il est manquant
if ! command -v gosu &> /dev/null; then
    echo " -> 'gosu' non trouvé. Installation..."
    apt-get update && apt-get install -y --no-install-recommends gosu && rm -rf /var/lib/apt/lists/*
fi

# Installer PDM, qui est nécessaire pour exécuter la commande finale.
# C'est rapide si déjà installé.
pip install --no-cache-dir pdm

# Créer l'utilisateur et le groupe s'ils sont manquants (opération idempotente)
echo " -> Vérification de l'utilisateur 'appuser'..."
addgroup --system --gid 1000 appgroup 2>/dev/null || true
adduser --system --home /home/appuser --uid 1000 --ingroup appgroup appuser 2>/dev/null || true

# --- Étape 2: Installation des dépendances de l'application (une seule fois) ---
# Exécuter la configuration des dépendances uniquement si le fichier "drapeau" n'existe pas.
if [ ! -f "/app/setup_done.flag" ]; then
  echo "--- Première configuration détectée : Installation des dépendances ---"

  # Installer les paquets système nécessaires pour la compilation Python
  apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    procps \
    libxml2-dev \
    libxslt-dev && \
  rm -rf /var/lib/apt/lists/*

  # Installer les dépendances Python en tant que 'appuser'
  echo " -> Installation des paquets Python (peut prendre du temps)..."
  gosu appuser pdm install --no-lock --no-editable

  # Créer le fichier drapeau pour marquer la fin de l'installation
  echo " -> Installation terminée. Création du fichier de statut."
  touch /app/setup_done.flag
  chown appuser:appgroup /app/setup_done.flag
else
  echo "--- Dépendances déjà installées. Démarrage direct. ---"
fi

# --- Étape 3: Lancement de l'application ---
echo "--- Lancement de la commande : $@ ---"
exec gosu appuser "$@"