# ============================================================================
# FICHIER : app/events.py
# ============================================================================
# Ce fichier contient les gestionnaires d'événements pour Flask-SocketIO.
# C'est ici que vous définirez comment le serveur réagit aux messages
# envoyés par les clients via WebSocket.
# ============================================================================

from . import socketio

# Exemple de gestionnaire d'événement
@socketio.on('connect')
def handle_connect():
    print('Client connected')