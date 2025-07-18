from app import create_app, socketio

# Crée une instance de l'application en utilisant la factory.
# Le mode debug est souvent contrôlé par une variable d'environnement
# comme FLASK_ENV ou FLASK_DEBUG.
app = create_app(debug=True)

if __name__ == '__main__':
    # Utilise socketio.run() au lieu de app.run() pour démarrer le serveur.
    # Ceci est nécessaire pour que le serveur de développement supporte les WebSockets.
    # L'hôte 0.0.0.0 est nécessaire pour que l'application soit accessible
    # depuis l'extérieur du conteneur Docker.
    socketio.run(app, host='0.0.0.0', port=5000)