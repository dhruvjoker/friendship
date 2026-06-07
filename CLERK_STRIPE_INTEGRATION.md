Summary of changes and next steps for Clerk + Stripe integration

What I implemented (scaffolded):

- Backend (Python/Flask):
  - Added Clerk-related config variables in `config.py` (`CLERK_API_KEY`, `CLERK_JWT_KEYS_URL`, `CLERK_ISSUER`).
  - Added Stripe config variables in `config.py` (`STRIPE_API_KEY`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET`).
  - Added endpoint `POST /auth/clerk/callback` in `app/routes.py` to accept a Clerk-verified payload from the client. The endpoint finds or creates a local `User` by email and logs them in via Flask-Login.
  - Added endpoint `POST /create-checkout-session` in `app/routes.py` to create a Stripe Checkout session for the current user (uses `STRIPE_API_KEY` and `STRIPE_PRICE_ID`).
  - Added `stripe` and `PyJWT` to `requirements.txt`.

- Flutter (mobile):
  - Added a lightweight Clerk social sign-in helper `_loginWithClerk(provider)` to `lib/login_page_widget.dart` which opens a Clerk-hosted sign-in URL in the system browser.
  - Added three social buttons (Google, Facebook, Apple) to the existing `LoginPageWidget` that call the helper.

Why this approach:

- Clerk does not yet have an official first-class Flutter SDK, so a reliable pattern is to use Clerk-hosted sign-in pages (or the web SDK inside a WebView) and flow the resulting identity to your backend for verification and local session creation.

Next steps you must complete / configure:

1. Configure environment variables on your server:

- CLERK_API_KEY (server API key)
- CLERK_ISSUER (your Clerk issuer URL)
- STRIPE_API_KEY, STRIPE_PUBLISHABLE_KEY, STRIPE_PRICE_ID, STRIPE_WEBHOOK_SECRET

2. Replace the placeholder Clerk sign-in URL in `lib/login_page_widget.dart` with your Clerk organization's sign-in link and set the redirect URI to a deep link your app handles (e.g. `myapp://clerk-callback`).

3. Implement deep-link handling in your Flutter app so that when the user is redirected to `myapp://clerk-callback` you:
   - Parse the Clerk-provided parameters (or fetch the session info using the returned token).
   - POST a verified payload to `POST /auth/clerk/callback` on your backend with `{ token: <id_token|session_token> }` so the server can verify the JWT.
   - On success, navigate to your app's authenticated flow.

4. Replace the simple backend callback verification with real Clerk verification:
   - Verify Clerk session JWTs using Clerk's JWKS (`CLERK_JWT_KEYS_URL`) or call Clerk server APIs using `CLERK_API_KEY` to fetch session/user details.
   - Only create/login local users after successful verification.

5. Test Stripe flow:
   - Set `STRIPE_API_KEY` and `STRIPE_PRICE_ID` then call `POST /create-checkout-session` from the authenticated app to open Stripe Checkout.
   - Configure your Stripe webhook endpoint and `STRIPE_WEBHOOK_SECRET` to listen for subscription/payment events.

Security notes and caveats:

- The current `POST /auth/clerk/callback` is intentionally lightweight and trusts the client-provided payload; this is acceptable for early development but is NOT secure for production.
- Use Clerk JWT verification or server-side APIs to validate identity tokens before creating or logging a user in.

Deep-link implementation details added by scaffold:

- Added `uni_links` and `http` to `pubspec.yaml`.
- Added `lib/deeplink_handler.dart` which listens for cold-start and runtime deep links, extracts token parameters (looks for `token`, `id_token`, `session_token`, `clerk_token`, `code`) and POSTs `{ "token": "..." }` to the backend `http://10.0.2.2:5000/auth/clerk/callback`.
- Note: `10.0.2.2` is used for Android emulator to reach host; update the URL for real devices or production.

Platform config files created:

- [android/app/src/main/AndroidManifest.xml](android/app/src/main/AndroidManifest.xml) — intent-filter for `myapp://clerk-callback`.
- [ios/Runner/Info.plist](ios/Runner/Info.plist) — URL scheme `myapp` configured.

Testing deep links:

1. Android emulator (cold-start):

```bash
adb shell am start -a android.intent.action.VIEW -d "myapp://clerk-callback?token=REPLACE_WITH_TOKEN" com.example.friendship_app
```

2. iOS Simulator (open URL):

```bash
xcrun simctl openurl booted "myapp://clerk-callback?token=REPLACE_WITH_TOKEN"
```

3. On emulator, ensure backend URL in `lib/deeplink_handler.dart` points to `http://10.0.2.2:5000` (host machine). On physical devices, use your machine IP or a tunneling service (ngrok).

Would you like me to:
- Implement proper Clerk JWT verification on the backend (I can add PyJWT-based JWKS retrieval and validation)?
- Add a Flutter deep-link handler and automatic backend exchange flow for Clerk (I can scaffold using `uni_links`)?
- Add Stripe webhook handling stubs to handle subscription events?

If yes, tell me which of the above to implement next and I'll continue.