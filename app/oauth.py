"""
OAuth social login — Google, Facebook, Apple
=============================================
SETUP REQUIRED before these buttons work:

1. GOOGLE
   - Go to https://console.cloud.google.com
   - Create project → APIs & Services → Credentials → OAuth 2.0 Client ID
   - Authorised redirect URI: http://localhost:5000/auth/google/authorized
   - Copy Client ID and Client Secret into your .env:
       GOOGLE_CLIENT_ID=...
       GOOGLE_CLIENT_SECRET=...

2. FACEBOOK
   - Go to https://developers.facebook.com
   - Create App → Facebook Login → Settings
   - Valid OAuth Redirect URI: http://localhost:5000/auth/facebook/authorized
   - Copy App ID and App Secret into your .env:
       FACEBOOK_CLIENT_ID=...
       FACEBOOK_CLIENT_SECRET=...

3. APPLE  (most complex — requires Apple Developer account $99/yr)
   - Go to https://developer.apple.com → Certificates, Identifiers & Profiles
   - Register a Services ID, enable "Sign in with Apple"
   - Redirect URL: https://yourdomain.com/auth/apple/authorized  (must be HTTPS)
   - Copy into your .env:
       APPLE_CLIENT_ID=...          (your Services ID, e.g. com.yourapp.signin)
       APPLE_TEAM_ID=...
       APPLE_KEY_ID=...
       APPLE_PRIVATE_KEY=...        (contents of the .p8 file, newlines as \\n)
   NOTE: Apple requires HTTPS even in dev. Use ngrok for local testing.
"""

import uuid
from flask import Blueprint, redirect, url_for, flash, request
from flask_dance.contrib.google   import make_google_blueprint,   google
from flask_dance.contrib.facebook import make_facebook_blueprint, facebook
from flask_login import login_user
from werkzeug.security import generate_password_hash
from app.models import User, db
from app.encryption import MessageEncryption
import os

# ── Google ──────────────────────────────────────────────────────────────────
google_bp = make_google_blueprint(
    client_id     = os.environ.get("GOOGLE_CLIENT_ID",     "PASTE_GOOGLE_CLIENT_ID_HERE"),
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "PASTE_GOOGLE_CLIENT_SECRET_HERE"),
    scope         = ["openid", "email", "profile"],
    redirect_url  = "/auth/google/authorized",
)

# ── Facebook ─────────────────────────────────────────────────────────────────
facebook_bp = make_facebook_blueprint(
    client_id     = os.environ.get("FACEBOOK_CLIENT_ID",     "PASTE_FACEBOOK_APP_ID_HERE"),
    client_secret = os.environ.get("FACEBOOK_CLIENT_SECRET", "PASTE_FACEBOOK_APP_SECRET_HERE"),
    scope         = ["email"],
    redirect_url  = "/auth/facebook/authorized",
)

# ── Shared helper ─────────────────────────────────────────────────────────────
def _get_or_create_user(email: str, username: str, provider: str) -> User:
    """Find existing user by email or create a new one from OAuth data."""
    user = User.query.filter_by(email=email).first()
    if not user:
        # Ensure username is unique
        base = username[:20]
        candidate = base
        i = 1
        while User.query.filter_by(username=candidate).first():
            candidate = f"{base[:18]}{i}"
            i += 1
        encryption_key = MessageEncryption.generate_key().decode("utf-8")
        user = User(
            id=str(uuid.uuid4()),
            username=candidate,
            email=email,
            # Random unusable password — they log in via OAuth only
            password_hash=generate_password_hash(str(uuid.uuid4())),
            encryption_key=encryption_key,
        )
        db.session.add(user)
        db.session.commit()
    return user


# ── Google callback ───────────────────────────────────────────────────────────
oauth_bp = Blueprint("oauth", __name__)

@oauth_bp.route("/google/authorized")
def google_authorized():
    if not google.authorized:
        flash("Google login failed — try again.", "error")
        return redirect(url_for("auth.login"))
    resp = google.get("/oauth2/v2/userinfo")
    if not resp.ok:
        flash("Could not fetch your Google profile.", "error")
        return redirect(url_for("auth.login"))
    info  = resp.json()
    email = info.get("email", "")
    name  = info.get("name", email.split("@")[0])
    if not email:
        flash("No email returned from Google.", "error")
        return redirect(url_for("auth.login"))
    user = _get_or_create_user(email, name, "google")
    login_user(user, remember=True)
    return redirect(url_for("main.dashboard"))


# ── Facebook callback ─────────────────────────────────────────────────────────
@oauth_bp.route("/facebook/authorized")
def facebook_authorized():
    if not facebook.authorized:
        flash("Facebook login failed — try again.", "error")
        return redirect(url_for("auth.login"))
    resp = facebook.get("/me?fields=id,name,email")
    if not resp.ok:
        flash("Could not fetch your Facebook profile.", "error")
        return redirect(url_for("auth.login"))
    info  = resp.json()
    email = info.get("email", f"fb_{info['id']}@facebook.invalid")
    name  = info.get("name", "user")
    user = _get_or_create_user(email, name, "facebook")
    login_user(user, remember=True)
    return redirect(url_for("main.dashboard"))


# ── Apple callback (stub — requires extra JWT work) ───────────────────────────
@oauth_bp.route("/apple/authorized", methods=["GET", "POST"])
def apple_authorized():
    """
    Apple sends a POST back. Full implementation needs PyJWT to verify the
    id_token. Set up once you have your Apple Developer credentials.
    See: https://developer.apple.com/documentation/sign_in_with_apple
    """
    flash("Apple Sign-In requires HTTPS and your Apple Developer credentials. "
          "See app/oauth.py for setup instructions.", "error")
    return redirect(url_for("auth.login"))
