"""
run.py — Application entry point.

Development:
    python run.py

Production (Render / Railway / Heroku / VPS):
    gunicorn --worker-class eventlet -w 1 run:app
    or use the Procfile.
"""
import os
from app import create_app, socketio

env  = os.environ.get('FLASK_ENV', 'development')
app  = create_app(env)

if __name__ == '__main__':
    debug = env == 'development'
    socketio.run(app, debug=debug, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
