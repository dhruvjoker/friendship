# Stripe → Razorpay Migration Guide

## 1. Install / uninstall dependencies

```bash
pip uninstall stripe
pip install razorpay
```

Update `requirements.txt`:
```
# remove:   stripe
# add:      razorpay>=1.4.1
```

---

## 2. Environment variables

Remove all `STRIPE_*` vars and add Razorpay ones:

```dotenv
# ── Remove ──────────────────────────────────────
# STRIPE_API_KEY=...
# STRIPE_PUBLISHABLE_KEY=...
# STRIPE_PRICE_ID=...
# STRIPE_WEBHOOK_SECRET=...

# ── Add ─────────────────────────────────────────
RAZORPAY_KEY_ID=rzp_live_XXXXXXXXXXXX
RAZORPAY_KEY_SECRET=<your_key_secret>
RAZORPAY_WEBHOOK_SECRET=<your_webhook_secret>
```

CLERK_API_KEY (already present) is now also used by the webhook handler
to write public_metadata back to Clerk — no new variable needed.

---

## 3. Changes to `app/routes.py`

### Remove these three route functions:

| Old route                                | Old function name               |
|------------------------------------------|---------------------------------|
| `POST /create-checkout-session`          | `create_checkout_session`       |
| `POST /create-checkout-session-token`    | `create_checkout_session_token` |
| `POST /api/billing/checkout`             | `api_billing_checkout`          |

### Remove the Stripe import at the top:
```python
# delete this line:
import stripe
```

### If you had a Stripe webhook handler anywhere, delete it entirely.
The new `billing_webhook.py` replaces it at a different URL.

---

## 4. Register the new blueprints in `app/__init__.py`

```python
# In create_app(), after existing blueprint registrations:

from app.billing_routes  import billing_bp
from app.billing_webhook import webhook_bp

app.register_blueprint(billing_bp)
app.register_blueprint(webhook_bp)
```

---

## 5. New endpoint reference

### `POST /api/billing/create-link`
Auth: `Authorization: Bearer <clerk_jwt>`

Request:
```json
{ "is_international": true }
```

| `is_international` | Currency | Amount | Razorpay unit |
|--------------------|----------|--------|---------------|
| `true`             | USD      | $4.99  | 499 cents     |
| `false`            | INR      | ₹20    | 2000 paise    |

Response `201`:
```json
{
  "payment_link_id": "plink_XXXXXXXXXXXX",
  "short_url":       "https://rzp.io/i/XXXXXXXX"
}
```

---

### `POST /api/billing/razorpay-webhook`
**Unprotected** — Razorpay calls this server-to-server.

On `payment_link.paid`:
1. Verifies `X-Razorpay-Signature` (HMAC-SHA256 with `RAZORPAY_WEBHOOK_SECRET`).
2. Reads `payload.payment_link.entity.notes.clerk_user_id`.
3. PATCHes `https://api.clerk.com/v1/users/{clerk_user_id}/metadata`:
   ```json
   { "public_metadata": { "entitlements": ["premium-access"] } }
   ```
   Uses `CLERK_API_KEY` as the Bearer token.
4. Always returns `200` so Razorpay does not retry.

---

## 6. Razorpay Dashboard — Webhook configuration

1. **Dashboard → Settings → Webhooks → Add New Webhook**
2. **URL:** `https://<your-domain>/api/billing/razorpay-webhook`
3. **Secret:** same value as `RAZORPAY_WEBHOOK_SECRET` in your env
4. **Active events:** tick **payment_link.paid**

---

## 7. Flutter / mobile — update the API call

```dart
// OLD (Stripe)
final resp = await http.post(
  Uri.parse('$baseUrl/create-checkout-session-token'),
  headers: {'Authorization': 'Bearer $clerkToken'},
  body: jsonEncode({'price_id': 'price_xxx'}),
);

// NEW (Razorpay)
final resp = await http.post(
  Uri.parse('$baseUrl/api/billing/create-link'),
  headers: {
    'Authorization': 'Bearer $clerkToken',
    'Content-Type': 'application/json',
  },
  body: jsonEncode({'is_international': isInternational}),
);

final data   = jsonDecode(resp.body);
final payUrl = data['short_url'];   // open in webview / external browser
```

## 8. Verifying premium status on the client

After a successful payment Clerk's `public_metadata` for the user will contain:

```json
{ "entitlements": ["premium-access"] }
```

Read it via `user.publicMetadata.entitlements` in the Clerk SDK (Flutter,
JS, etc.) or decode it from the JWT claims if you include public_metadata
in your session token template.
