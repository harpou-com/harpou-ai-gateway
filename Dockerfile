# --- Étape 1: Build ---
# Utiliser une image complète pour installer les dépendances
FROM python:3.11-slim as builder

WORKDIR /app

# Installer PDM
RUN pip install pdm

# Copier les fichiers de projet et installer les dépendances de production
COPY pyproject.toml pdm.lock ./
# --no-editable est recommandé pour les installations de production
RUN pdm install --prod --no-lock --no-editable

# --- Étape 2: Runtime ---
# Utiliser une image slim pour la production
FROM python:3.11-slim

WORKDIR /app

# Copier l'environnement virtuel depuis l'étape de build
COPY --from=builder /app/__pypackages__/3.11 /app/__pypackages__/3.11

# Copier le code de l'application
COPY app ./app
COPY run.py celery_worker.py ./

# Ajouter le chemin des paquets au PYTHONPATH et le rendre non-bufferisé
ENV PYTHONPATH=/app/__pypackages__/3.11/lib
ENV PYTHONUNBUFFERED=1

# Installer gunicorn/eventlet pour le serveur de production
RUN /app/__pypackages__/3.11/bin/pip install gunicorn eventlet

EXPOSE 5000

# Commande par défaut pour démarrer le serveur gunicorn avec socketio
CMD ["/app/__pypackages__/3.11/bin/gunicorn", "--worker-class", "eventlet", "-w", "2", "--bind", "0.0.0.0:5000", "run:app"]