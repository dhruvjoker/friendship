Testing Guide — Clerk sign-in, token protection, and billing flows

Prerequisites
- Flask backend running on host machine at port 5000 (default for run.py).
- Flutter emulator or device with app installed.
- Environment variables set on backend:
  - CLERK_JWT_KEYS_URL
  - CLERK_ISSUER
  - CLERK_API_KEY (optional; used for Clerk billing API)
  - STRIPE_API_KEY and STRIPE_PRICE_ID (for Stripe fallback)

1) Social sign-in flow (end-to-end)
- From the Flutter app, tap any social button (Google/Facebook/Apple). The buttons open your Clerk-hosted sign-in URL. Ensure you updated the sign-in base URL in `lib/login_page_widget.dart`.
- Complete sign-in in the browser; Clerk will redirect to `myapp://clerk-callback?token=<TOKEN>`.
- The Flutter app receives the deep link (cold start or background), stores the `token` in `SharedPreferences` and POSTs `{ "token": "..." }` to `POST /auth/clerk/callback` on the backend.
- Backend performs JWT verification using JWKS and logs in/creates the local user. On success the backend returns `200` and a `redirect` field.

2) Token-protected API test
- Use the saved token in `SharedPreferences` to call protected endpoints that accept Clerk Bearer tokens, such as `POST /create-checkout-session-token` or `POST /api/billing/checkout`.
- Example cURL (replace `<TOKEN>`):
  ```bash
  curl -X POST http://localhost:5000/create-checkout-session-token \
    -H "Authorization: Bearer <TOKEN>" \
    -H "Content-Type: application/json" \
    -d '{"price_id":"price_..."}'
  ```
- Expected: 200 and a JSON object containing Stripe session id and url.

3) Billing flow via Flutter
- In the Flutter app press the "Manage Billing / Upgrade" button.
- The app reads the stored `clerk_token` and POSTs to `POST /api/billing/checkout` with the token in the Authorization header.
- Backend attempts to create a Clerk billing portal session (if `CLERK_API_KEY` is set) by calling the Clerk billing API. If Clerk billing API isn't available, the backend falls back to creating a Stripe Checkout session using `STRIPE_API_KEY` and `STRIPE_PRICE_ID`.
- The backend returns JSON `{ "url": "<portal_or_checkout_url>" }`. The Flutter app opens the URL in the system browser.

Notes and troubleshooting
- Android emulator: the deeplink handler posts to `http://10.0.2.2:5000` (host machine). For physical devices replace with `http://<host-ip>:5000` or use ngrok.
- If Clerk server-side billing API returns unexpected fields, update `CLERK_BILLING_URL` in `config.py` or adjust response parsing in `app/routes.py`.
- If verification fails, confirm `CLERK_JWT_KEYS_URL` and `CLERK_ISSUER` are correct and reachable from the backend.

Files to review
- Backend: `app/clerk.py`, `app/routes.py` (auth & billing endpoints)
- Flutter: `lib/deeplink_handler.dart`, `lib/login_page_widget.dart` (sign-in buttons + Manage Billing button)

Next steps
- Add unit/integration tests for `app/clerk.py` and `/api/billing/checkout`.
- Implement redirect flow in the Flutter app to navigate to an authenticated area after successful backend login.
- Harden Clerk billing call error handling and response validation.
