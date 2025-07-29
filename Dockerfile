# Étape 1: Builder avec PDM
FROM python:3.11-slim as builder

# Ajout des outils de build essentiels pour compiler les dépendances C
# C'est la correction clé pour le problème de 'greenlet'
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Installer PDM
RUN pip install pdm

# Copier les fichiers du projet
COPY pyproject.toml pdm.lock README.md /app/
WORKDIR /app

# Installer les dépendances du projet, sans les dev-dependencies
RUN pdm install --prod --no-lock

# Étape 2: Image finale
FROM python:3.11-slim

# Variables d'environnement
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PATH="/app/__pypackages__/3.11/bin:$PATH"

# Créer un utilisateur non-root
RUN addgroup --gid 1000 appgroup && \
    adduser --uid 1000 --gid 1000 --ingroup appgroup --home /home/appuser --shell /bin/sh --disabled-password appuser

# Copier les dépendances depuis le builder
COPY --from=builder /app/__pypackages__ /app/__pypackages__

# Copier le reste de l'application
WORKDIR /app
COPY . /app

# S'assurer que les scripts sont exécutables
RUN chmod +x /app/entrypoint.dev.sh

# Changer le propriétaire des fichiers
RUN chown -R appuser:appgroup /app /home/appuser

# Passer à l'utilisateur non-root
USER appuser

# Exposer le port
EXPOSE 5000

# Lancer l'application
CMD ["pdm", "run", "start"]
