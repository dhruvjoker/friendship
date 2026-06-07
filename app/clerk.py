import time
import json
import logging
from typing import Dict, Any, Optional

import requests
import jwt
from flask import current_app, g, jsonify
from functools import wraps

logger = logging.getLogger(__name__)

# Simple in-memory cache for JWKS
_JWKS_CACHE: Optional[Dict[str, Any]] = None
_JWKS_FETCHED_AT: float = 0
_JWKS_TTL: int = 60 * 60  # 1 hour


def _fetch_jwks() -> Dict[str, Any]:
    global _JWKS_CACHE, _JWKS_FETCHED_AT
    now = time.time()
    if _JWKS_CACHE and now - _JWKS_FETCHED_AT < _JWKS_TTL:
        return _JWKS_CACHE

    url = current_app.config.get('CLERK_JWT_KEYS_URL')
    if not url:
        raise RuntimeError('CLERK_JWT_KEYS_URL not configured')

    resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    jwks = resp.json()
    _JWKS_CACHE = jwks
    _JWKS_FETCHED_AT = now
    logger.debug('Fetched JWKS from %s', url)
    return jwks


def _get_public_key_for_kid(kid: str):
    jwks = _fetch_jwks()
    keys = jwks.get('keys', [])
    for key in keys:
        if key.get('kid') == kid:
            # jwt library can accept a PEM key. Convert JWK to PEM using from_jwk
            jwk_json = json.dumps(key)
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(jwk_json)
            return public_key
    raise KeyError(f'No matching JWK found for kid={kid}')


def verify_clerk_jwt(token: str) -> Dict[str, Any]:
    """Verify a Clerk-issued JWT using the JWKS.

    Returns the decoded payload on success or raises an exception on failure.
    """
    if not token:
        raise ValueError('No token provided')

    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get('kid')
        if not kid:
            raise jwt.InvalidTokenError('Missing kid in token header')

        public_key = _get_public_key_for_kid(kid)

        # Verify token. We disable audience check by default; verify issuer if configured.
        issuer = current_app.config.get('CLERK_ISSUER') or None

        options = {'verify_aud': False}
        decoded = jwt.decode(
            token,
            public_key,
            algorithms=['RS256'],
            issuer=issuer,
            options=options,
        )
        return decoded

    except Exception as exc:
        logger.exception('Failed to verify Clerk JWT')
        raise


def clerk_required(f):
    """Flask decorator to require a valid Clerk JWT in the `Authorization: Bearer ...` header.

    On success the decoded payload is stored in `flask.g.clerk_token`.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import request

        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error': 'Missing Bearer token'}), 401

        token = auth.split(' ', 1)[1].strip()
        try:
            payload = verify_clerk_jwt(token)
        except Exception:
            return jsonify({'error': 'Invalid or expired token'}), 401

        g.clerk_token = payload
        return f(*args, **kwargs)

    return wrapper
