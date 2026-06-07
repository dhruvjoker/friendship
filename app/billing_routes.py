"""
billing_routes.py
=================
Razorpay-backed billing endpoints.  Drop Stripe entirely.

Replaces:
  • POST /create-checkout-session          (Stripe, login_required)
  • POST /create-checkout-session-token    (Stripe, clerk_required)
  • POST /api/billing/checkout             (Stripe + Clerk fallback, clerk_required)

New endpoint:
  • POST /api/billing/create-link          (Razorpay, clerk_required)

Request body (JSON):
  {
    "is_international": true | false
  }

Response (JSON):
  {
    "payment_link_id": "plink_XXXX",
    "short_url":       "https://rzp.io/i/XXXX"
  }

Pricing:
  is_international=True  →  USD 4.99  (499 paise-equivalent: Razorpay uses smallest
                                         currency unit, but USD amounts are in cents)
  is_international=False →  INR 20    (2000 paise)

The Razorpay 'notes' dict carries 'clerk_user_id' so webhook handlers can
resolve the payment back to the correct Clerk identity.
"""

import logging

import razorpay
from flask import Blueprint, current_app, g, jsonify, request

from app.clerk import clerk_required

logger = logging.getLogger(__name__)

billing_bp = Blueprint("billing", __name__)

# ---------------------------------------------------------------------------
# Pricing constants
# ---------------------------------------------------------------------------
_USD_AMOUNT_CENTS = 499       # $4.99 — Razorpay represents USD in cents
_INR_AMOUNT_PAISE = 2000      # ₹20   — Razorpay represents INR in paise


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _razorpay_client() -> razorpay.Client:
    """Return an authenticated Razorpay client using config values."""
    key_id = current_app.config.get("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET")

    if not key_id or not key_secret:
        raise RuntimeError("Razorpay credentials not configured (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET)")

    return razorpay.Client(auth=(key_id, key_secret))


# ---------------------------------------------------------------------------
# New endpoint: POST /api/billing/create-link
# ---------------------------------------------------------------------------

@billing_bp.route("/api/billing/create-link", methods=["POST"])
@clerk_required
def create_payment_link():
    """Create a Razorpay Payment Link for the authenticated Clerk user.

    Body params (JSON):
        is_international (bool, required) — True → USD 4.99 / False → INR ₹20

    The Clerk user ID is embedded in Razorpay's `notes` dict so that the
    Razorpay webhook handler can match the payment to the correct account.
    """
    # ── 1. Parse & validate request ──────────────────────────────────────
    body = request.get_json(silent=True) or {}

    if "is_international" not in body:
        return jsonify({"error": "Missing required field: is_international"}), 400

    is_international: bool = bool(body["is_international"])

    # ── 2. Extract Clerk identity (set by @clerk_required decorator) ──────
    clerk_payload = g.get("clerk_token") or {}
    clerk_user_id: str = clerk_payload.get("sub", "")

    if not clerk_user_id:
        return jsonify({"error": "Cannot resolve Clerk user ID from token"}), 400

    # ── 3. Build Razorpay Payment Link payload ────────────────────────────
    if is_international:
        amount   = _USD_AMOUNT_CENTS
        currency = "USD"
        description = "Premium membership – $4.99"
    else:
        amount   = _INR_AMOUNT_PAISE
        currency = "INR"
        description = "Premium membership – ₹20"

    payload = {
        "amount":      amount,
        "currency":    currency,
        "description": description,
        # Embed the Clerk user ID here — critical for webhook reconciliation
        "notes": {
            "clerk_user_id": clerk_user_id,
        },
        # Accept only card payments; remove or expand as needed
        "accept_partial": False,
        "reference_id":   clerk_user_id,  # surfaced in Razorpay dashboard
    }

    # ── 4. Call Razorpay API ──────────────────────────────────────────────
    try:
        client = _razorpay_client()
        link = client.payment_link.create(payload)
    except RuntimeError as exc:
        # Config problem — don't leak internal details
        logger.error("Razorpay config error: %s", exc)
        return jsonify({"error": "Payment provider not configured"}), 500
    except razorpay.errors.BadRequestError as exc:
        logger.exception("Razorpay bad request")
        return jsonify({"error": f"Payment link creation failed: {exc}"}), 400
    except Exception:
        logger.exception("Unexpected error creating Razorpay payment link")
        return jsonify({"error": "Failed to create payment link"}), 500

    # ── 5. Return the link details ────────────────────────────────────────
    return jsonify({
        "payment_link_id": link.get("id"),
        "short_url":       link.get("short_url"),
    }), 201
