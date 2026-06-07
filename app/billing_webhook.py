"""
app/billing_webhook.py
======================
Razorpay webhook receiver.  Replaces any previous Stripe webhook handler.

Registered route (unprotected — Razorpay calls it server-to-server):
    POST /api/billing/razorpay-webhook

Flow on payment_link.paid
--------------------------
1.  Validate the HMAC-SHA256 signature Razorpay sends in
    X-Razorpay-Signature against RAZORPAY_WEBHOOK_SECRET.
2.  Unwrap the event payload to reach notes.clerk_user_id.
3.  PATCH https://api.clerk.com/v1/users/{clerk_user_id}/metadata
    with { "public_metadata": { "entitlements": ["premium-access"] } }
    using CLERK_API_KEY as a Bearer token.
4.  Always return HTTP 200 so Razorpay does not retry.

Registration (app/__init__.py)
-------------------------------
    from app.billing_webhook import webhook_bp
    app.register_blueprint(webhook_bp)
"""

import hashlib
import hmac
import json
import logging

import requests as http_client
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

webhook_bp = Blueprint("billing_webhook", __name__)


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------

def _verify_signature(raw_body: bytes, received_sig: str, secret: str) -> bool:
    """
    Razorpay signs the raw request body with HMAC-SHA256 using the webhook
    secret configured in your dashboard.  The resulting hex digest is sent
    in the X-Razorpay-Signature header.

    Returns True only when the digest matches.  Uses hmac.compare_digest to
    prevent timing-based side-channel attacks.
    """
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, received_sig)


# ---------------------------------------------------------------------------
# Clerk metadata writer
# ---------------------------------------------------------------------------

def _grant_premium_via_clerk(clerk_user_id: str, clerk_api_key: str) -> None:
    """
    PATCH the Clerk user's public_metadata to mark them as premium.

    Clerk Backend API reference:
      PATCH /v1/users/{user_id}/metadata
      Body: { "public_metadata": { ... } }

    Clerk performs a *merge* on public_metadata, so existing keys that are
    not present in the PATCH body are preserved.
    """
    url = f"https://api.clerk.com/v1/users/{clerk_user_id}/metadata"
    headers = {
        "Authorization": f"Bearer {clerk_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "public_metadata": {
            "entitlements": ["premium-access"],
        }
    }

    response = http_client.patch(url, json=body, headers=headers, timeout=10)

    # Raise immediately so the caller can log a structured error.
    # 404 → Clerk user_id doesn't exist; 401/403 → bad API key.
    response.raise_for_status()

    logger.info(
        "Clerk metadata updated for user %s — entitlements: ['premium-access']",
        clerk_user_id,
    )


# ---------------------------------------------------------------------------
# Webhook endpoint
# ---------------------------------------------------------------------------

@webhook_bp.route("/api/billing/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    """
    Unprotected POST endpoint for inbound Razorpay webhook events.

    Razorpay requires the endpoint to return 200 quickly; all heavy work is
    intentionally synchronous here (acceptable for a single metadata write),
    but if you add slow side-effects later consider pushing them to a task
    queue and still returning 200 immediately.
    """
    raw_body: bytes = request.get_data()

    # ── Step 1: HMAC-SHA256 signature check ──────────────────────────────
    webhook_secret: str = current_app.config.get("RAZORPAY_WEBHOOK_SECRET", "")
    received_sig: str   = request.headers.get("X-Razorpay-Signature", "")

    if webhook_secret:
        if not received_sig:
            logger.warning(
                "Razorpay webhook request missing X-Razorpay-Signature header — rejected"
            )
            # Return 200 anyway: returning 4xx causes Razorpay to keep retrying
            # a structurally invalid (possibly spoofed) request.  Log and drop.
            return jsonify({"status": "ignored", "reason": "missing signature"}), 200

        if not _verify_signature(raw_body, received_sig, webhook_secret):
            logger.warning(
                "Razorpay webhook signature mismatch — possible spoofed request, dropped"
            )
            return jsonify({"status": "ignored", "reason": "invalid signature"}), 200
    else:
        # Signature verification is skipped only when the secret is not yet
        # configured (e.g. local development).  Log loudly so this is never
        # silently skipped in production.
        logger.warning(
            "RAZORPAY_WEBHOOK_SECRET is not set — "
            "signature verification DISABLED (unsafe for production)"
        )

    # ── Step 2: Parse payload ─────────────────────────────────────────────
    try:
        event: dict = json.loads(raw_body)
    except (json.JSONDecodeError, ValueError):
        logger.error("Razorpay webhook: could not parse JSON body")
        return jsonify({"status": "ok"}), 200   # acknowledge so Razorpay stops retrying

    event_type: str = event.get("event", "")
    logger.info("Razorpay webhook received: event_type=%s", event_type)

    # ── Step 3: Handle payment_link.paid ─────────────────────────────────
    if event_type == "payment_link.paid":
        _handle_payment_link_paid(event)

    # All other event types are acknowledged silently — add handlers as needed.
    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# payment_link.paid handler
# ---------------------------------------------------------------------------

def _handle_payment_link_paid(event: dict) -> None:
    """
    Extract clerk_user_id from notes, then write premium entitlement to Clerk.

    Razorpay payment_link.paid payload shape (abbreviated):
    {
      "event": "payment_link.paid",
      "payload": {
        "payment_link": {
          "entity": {
            "id": "plink_XXXX",
            "notes": {
              "clerk_user_id": "user_XXXX"   ← embedded by /api/billing/create-link
            }
          }
        },
        "payment": {
          "entity": {
            "id": "pay_XXXX",
            "amount": 499,
            "currency": "USD"
          }
        }
      }
    }
    """
    # ── Extract clerk_user_id from notes ──────────────────────────────────
    try:
        payment_link_entity: dict = (
            event
            .get("payload", {})
            .get("payment_link", {})
            .get("entity", {})
        )
        notes: dict           = payment_link_entity.get("notes", {})
        clerk_user_id: str    = notes.get("clerk_user_id", "").strip()
    except (AttributeError, TypeError):
        logger.error(
            "payment_link.paid: unexpected payload structure — could not read notes"
        )
        return

    if not clerk_user_id:
        logger.error(
            "payment_link.paid: notes.clerk_user_id is empty or missing. "
            "Payment link ID: %s — cannot grant entitlement.",
            payment_link_entity.get("id", "unknown"),
        )
        return

    # Log supporting payment details for audit trail (no PII stored here)
    payment_entity: dict = (
        event
        .get("payload", {})
        .get("payment", {})
        .get("entity", {})
    )
    logger.info(
        "payment_link.paid: clerk_user_id=%s  payment_id=%s  amount=%s %s",
        clerk_user_id,
        payment_entity.get("id"),
        payment_entity.get("amount"),
        payment_entity.get("currency"),
    )

    # ── PATCH Clerk public_metadata via Backend API ───────────────────────
    from flask import current_app  # local import avoids circular reference at module load

    clerk_api_key: str = current_app.config.get("CLERK_API_KEY", "").strip()

    if not clerk_api_key:
        logger.error(
            "CLERK_API_KEY is not configured — cannot update entitlements "
            "for clerk_user_id=%s",
            clerk_user_id,
        )
        return

    try:
        _grant_premium_via_clerk(clerk_user_id, clerk_api_key)
    except http_client.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body   = exc.response.text if exc.response is not None else ""
        logger.error(
            "Clerk PATCH failed for clerk_user_id=%s: HTTP %s — %s",
            clerk_user_id, status, body,
        )
    except http_client.exceptions.RequestException:
        logger.exception(
            "Network error reaching Clerk API for clerk_user_id=%s", clerk_user_id
        )
