# --- Étape 1: Préparation (Optionnelle mais bonne pratique) ---
# On utilise une étape pour installer PDM proprement.
FROM python:3.11-slim as pdm_installer

RUN pip install --no-cache-dir pdm

# --- Étape 2: Image finale de production ---
FROM python:3.11-slim

WORKDIR /app

# Créer un utilisateur et un groupe non-root pour la sécurité
RUN addgroup --system --gid 1000 appgroup && adduser --system --create-home --home /home/appuser --uid 1000 --ingroup appgroup appuser

# Copier PDM depuis l'étape précédente
COPY --from=pdm_installer /usr/local/bin/pdm /usr/local/bin/pdm

# Installer les dépendances système nécessaires pour la compilation ET l'exécution
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential python3-dev libxml2-dev libxslt1-dev procps && \
    rm -rf /var/lib/apt/lists/*

# Copier les fichiers de projet et installer les dépendances de production DANS l'étape finale
COPY pyproject.toml pdm.lock ./
RUN pdm install --prod --no-lock --no-editable --no-self && \
    apt-get purge -y --auto-remove build-essential python3-dev libxml2-dev libxslt1-dev && apt-get clean

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