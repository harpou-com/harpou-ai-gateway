# --- Étape 1: Build ---
# Utiliser une image complète pour installer les dépendances
FROM python:3.11-slim as builder

WORKDIR /app

# Installer les dépendances système nécessaires pour construire certains paquets Python (comme greenlet)
# et PDM lui-même.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python3-dev procps && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir pdm

# Copier les fichiers de projet et installer les dépendances de production
COPY pyproject.toml pdm.lock ./
# --no-editable est recommandé pour les installations de production
RUN pdm install --prod --no-lock --no-editable --no-self

# --- Étape 2: Runtime ---
# Utiliser une image slim pour la production
FROM python:3.11-slim

WORKDIR /app

# Créer un utilisateur et un groupe non-root pour la sécurité
# La commande `adduser --system` est la méthode correcte pour les images basées sur Debian (comme python:slim)
RUN addgroup --system --gid 1000 appgroup && adduser --system --create-home --home /home/appuser --uid 1000 --ingroup appgroup appuser

# Copier l'environnement virtuel depuis l'étape de build
COPY --from=builder /app/__pypackages__/3.11 /app/__pypackages__/3.11

# Copier le code de l'application
COPY app ./app
COPY run.py celery_worker.py worker_launcher.py ./

# Ajouter le chemin des paquets au PYTHONPATH et le rendre non-bufferisé
ENV PYTHONPATH=/app/__pypackages__/3.11/lib
ENV PYTHONUNBUFFERED=1

# Changer le propriétaire du répertoire de l'application pour l'utilisateur non-root
RUN chown -R appuser:appgroup /app

# Basculer vers l'utilisateur non-privilégié
USER appuser

EXPOSE 5000

# Commande par défaut pour démarrer le serveur gunicorn avec socketio
CMD ["/app/__pypackages__/3.11/bin/gunicorn", "--worker-class", "eventlet", "-w", "2", "--bind", "0.0.0.0:5000", "run:app"]