import eventlet
eventlet.monkey_patch()

from app import create_app
from app.extensions import socketio

app = create_app()

if __name__ == "__main__":
    # Utiliser le reloader de socketio en mode debug, il est plus stable que celui de Flask.
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, use_reloader=True)
