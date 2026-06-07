# Pre-Launch Additions — Integration Guide

This folder contains all the files needed to address the pre-launch gaps
identified in the review. Here's exactly where each file goes and what
changes to make in your existing code.

---

## File Map

```
friendship_app_output/
├── app/
│   ├── templates/
│   │   ├── landing.html              → app/templates/landing.html
│   │   ├── privacy_policy.html       → app/templates/privacy_policy.html
│   │   ├── terms_of_service.html     → app/templates/terms_of_service.html
│   │   ├── community_guidelines.html → app/templates/community_guidelines.html
│   │   └── contact.html              → app/templates/contact.html
│   ├── analytics.py                  → app/analytics.py
│   └── routes_landing.py             → app/routes_landing.py
├── sitemap.xml                       → sitemap.xml  (project root)
└── robots.txt                        → robots.txt   (project root)
```

---

## Step 1 — Register the landing blueprint

In `app/__init__.py`, add after the existing blueprint registrations:

```python
from app.routes_landing import landing_bp
app.register_blueprint(landing_bp)
```

## Step 2 — Point root URL to landing page

In `app/routes.py`, update the `index()` route under `main_bp`:

```python
@main_bp.route('/dashboard')
@login_required
def dashboard():
    ...  # unchanged

# Change the root route:
# The root '/' is now handled by landing_bp in routes_landing.py
# Remove or comment out the existing main_bp index route:

# @main_bp.route('/')         ← DELETE or comment out
# def index():                ← DELETE or comment out
#     if current_user.is_authenticated:
#         return redirect(url_for('main.dashboard'))
#     return redirect(url_for('auth.login'))
```

The `landing_bp` already handles `'/'` and redirects authenticated users
to dashboard automatically.

## Step 3 — Initialise analytics

In `app/__init__.py`, add after `init_monitoring(app)`:

```python
from app.analytics import init_analytics
init_analytics(app)
```

## Step 4 — Set environment variables

Add to your `.env` file:

```
# Analytics (get from posthog.com — free self-hostable tier available)
POSTHOG_API_KEY=phc_your_key_here
POSTHOG_HOST=https://app.posthog.com

# Error tracking (get from sentry.io — free tier available)
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
```

## Step 5 — Install new dependencies

```bash
pip install posthog sentry-sdk[flask]
```

Add to `requirements.txt`:
```
posthog>=3.0.0
sentry-sdk[flask]>=1.40.0
```

## Step 6 — Wire analytics into key routes

Add tracking calls to the routes that matter most for your funnel.
Open `app/routes.py` and add to the relevant functions:

```python
from app.analytics import (
    track_signup_started, track_signup_completed,
    track_match_created, track_message_sent
)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        track_signup_started()   # ← ADD THIS
    ...
    # After successful registration:
    track_signup_completed(
        user_id_hash=hash_data(user.id),   # hash_data is already imported
        problems_count=len(problems)
    )

@match_bp.route('/find', methods=['POST'])
def find_match():
    ...
    # After match is created:
    track_match_created(common_problems_count=len(common_problems))

@chat_bp.route('/send', methods=['POST'])
def send_message():
    ...
    track_message_sent()
```

---

## SEO Checklist

- [ ] Update the domain in `sitemap.xml` from `friendshipcircle.app` to your actual domain
- [ ] Update the domain in `robots.txt` Sitemap line
- [ ] Update all `og:url` and canonical tags in `landing.html`
- [ ] Add `og-image.jpg` (1200×630px) to `app/static/`
- [ ] Submit `sitemap.xml` to Google Search Console after launch

## Legal Checklist

- [ ] Have a lawyer review Privacy Policy and Terms of Service before launch
- [ ] Replace placeholder email addresses with real ones
- [ ] Confirm your actual data retention practices match what's written
- [ ] Add cookie consent banner if serving EU/UK users (required by GDPR)

## Analytics Funnel to Monitor

Once live, watch these events in Posthog:

1. `$pageview` (path: `/`) → landing page traffic
2. `signup_started` → register page opens
3. `signup_completed` → account created
4. `match_created` → first match made
5. `match_accepted` → chat started
6. `message_sent` → engagement confirmed
7. `chat_session_ended` (engaged: true) → retained user

**Key conversion rates to track:**
- Landing → Register page: target >15%
- Register page → Account created: target >60%
- Account created → First match: target >70%
- First match → First message: target >80%
