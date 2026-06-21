import os
from flask import Flask
from flask_login import LoginManager
from flask_socketio import SocketIO
from config import config
from app.models import db, User

login_manager = LoginManager()
socketio      = SocketIO()


def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config[config_name])

    # Validate required env vars in production
    if config_name == 'production':
        try:
            config['production'].validate()
        except RuntimeError as e:
            raise SystemExit(f"[STARTUP ERROR] {e}") from e

    # Observability
    from app.monitoring import init_monitoring
    init_monitoring(app)

    # Extensions
    db.init_app(app)
    login_manager.init_app(app)

    # SocketIO — lock CORS to the app's domain in production
    allowed_origins = os.getenv('SOCKETIO_CORS_ORIGINS', '*')
    if config_name == 'production' and allowed_origins == '*':
        base_url = app.config.get('APP_BASE_URL', '')
        allowed_origins = [base_url] if base_url else '*'
    socketio.init_app(app, cors_allowed_origins=allowed_origins)

    from app.socketio_events import register_socketio_events
    register_socketio_events(socketio)

    login_manager.login_view    = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(user_id)

    # Blueprints
    from app.routes import auth_bp, main_bp, chat_bp, match_bp, confession_bp
    app.register_blueprint(auth_bp,        url_prefix='/auth')
    app.register_blueprint(main_bp)
    app.register_blueprint(chat_bp,        url_prefix='/api/chat')
    app.register_blueprint(match_bp,       url_prefix='/api/match')
    app.register_blueprint(confession_bp,  url_prefix='/confession')

    from app.oauth import google_bp, facebook_bp, oauth_bp
    app.register_blueprint(google_bp,   url_prefix='/auth/google')
    app.register_blueprint(facebook_bp, url_prefix='/auth/facebook')
    app.register_blueprint(oauth_bp,    url_prefix='/auth')

    from app.billing_routes  import billing_bp
    from app.billing_webhook import webhook_bp
    app.register_blueprint(billing_bp)
    app.register_blueprint(webhook_bp)

    from app.routes_new_features import features_bp
    app.register_blueprint(features_bp, url_prefix='/api')

    from app.routes_landing import landing_bp
    app.register_blueprint(landing_bp)

    # ── HTTPS enforcement (Render terminates TLS at its edge and forwards
    #    plain HTTP internally, so we check X-Forwarded-Proto rather than
    #    request.is_secure — avoids a redirect loop) ─────────────────────────
    @app.before_request
    def enforce_https():
        if config_name != 'production':
            return None
        from flask import request, redirect

        forwarded_proto = request.headers.get('X-Forwarded-Proto', 'https')
        if forwarded_proto == 'http':
            url = request.url.replace('http://', 'https://', 1)
            return redirect(url, code=301)
        return None

    # ── Security headers ──────────────────────────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        # Tighten CSP — no unsafe-inline for scripts
        csp_script = "'self'"
        # In production, add a nonce or hash instead of unsafe-inline
        if app.config.get('DEBUG'):
            csp_script = "'self' 'unsafe-inline'"

        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; "
            f"script-src {csp_script} https://checkout.razorpay.com; "
            f"style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            f"font-src 'self' https://fonts.gstatic.com; "
            f"img-src 'self' data: https:; "
            f"connect-src 'self' wss: https://checkout.razorpay.com; "
            f"frame-src https://api.razorpay.com https://checkout.razorpay.com; "
            f"frame-ancestors 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self' https://accounts.google.com https://www.facebook.com https://appleid.apple.com"
        )
        response.headers['X-Frame-Options']        = 'DENY'
        response.headers['X-Content-Type-Options']  = 'nosniff'
        response.headers['Referrer-Policy']         = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']      = 'geolocation=(), microphone=(), camera=()'

        if not app.config.get('DEBUG'):
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'

        return response

    # ── Database init ─────────────────────────────────────────────────────────
    with app.app_context():
        from app.models import Confession
        db.create_all()

        from app.models import Problem
        if Problem.query.count() == 0:
            defaults = [
                Problem(name='Loneliness',         category='Emotional',      description='Feeling isolated and alone'),
                Problem(name='Anxiety',            category='Mental Health',  description='Persistent worry and nervousness'),
                Problem(name='Depression',         category='Mental Health',  description='Persistent sadness and hopelessness'),
                Problem(name='Relationship Issues',category='Relationships',  description='Difficulties in relationships'),
                Problem(name='Career Stress',      category='Work',           description='Work-related stress and pressure'),
                Problem(name='Social Anxiety',     category='Mental Health',  description='Anxiety in social situations'),
                Problem(name='Low Self-Esteem',    category='Emotional',      description='Lack of confidence'),
                Problem(name='Grief',              category='Emotional',      description='Loss and grieving process'),
                Problem(name='Family Conflicts',   category='Relationships',  description='Issues within family'),
                Problem(name='Academic Pressure',  category='Education',      description='Stress from education'),
            ]
            for p in defaults:
                db.session.add(p)
            db.session.commit()

    # ── Error handlers ────────────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import request, jsonify
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return (
            '<html><body style="background:#0D0B1A;color:#F1EEF9;'
            'font-family:sans-serif;text-align:center;padding:80px 20px;">'
            '<h1>404</h1><p>Page not found.</p>'
            '<a href="/" style="color:#A855F7;">Go home</a></body></html>'
        ), 404

    @app.errorhandler(500)
    def server_error(e):
        from flask import request, jsonify
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return (
            '<html><body style="background:#0D0B1A;color:#F1EEF9;'
            'font-family:sans-serif;text-align:center;padding:80px 20px;">'
            '<h1>500</h1><p>Something went wrong on our end.</p>'
            '<a href="/" style="color:#A855F7;">Go home</a></body></html>'
        ), 500

    return app
