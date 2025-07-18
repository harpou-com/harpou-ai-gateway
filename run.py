from dotenv import load_dotenv

# Charger les variables d'environnement
load_dotenv()


from app import create_app
from app.extensions import socketio


# La variable 'app' doit être globale pour que Gunicorn puisse la trouver (run:app)
app = create_app(init_socketio=True)

# Note: Pour la production, vous utilisez Gunicorn (d'après votre Dockerfile),
# donc ce bloc n'est utilisé que pour le développement local.
if __name__ == '__main__':
    # Lancement du serveur avec SocketIO pour supporter WebSocket en dev
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
