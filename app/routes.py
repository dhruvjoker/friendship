import logging
import secrets
from collections import defaultdict, deque
from datetime import datetime, timedelta
import random
import re
import time
import uuid

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for, g
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
import requests
import jwt

from app.content_safety import contains_blocked_contact_info, sanitize_message_content
from app.encryption import MessageEncryption, hash_data
from app.moderation import create_report, create_safety_events, record_user_ip, review_report, review_safety_event
from app.models import AbuseReport, Confession, Message, Problem, SafetyEvent, User, UserConnection, UserSession, db
from app.clerk import clerk_required

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)
main_bp = Blueprint('main', __name__)
chat_bp = Blueprint('chat', __name__)
match_bp = Blueprint('match', __name__)

# ── Rate limiting ─────────────────────────────────────────────────────────────
FAILED_LOGIN_ATTEMPTS: dict = defaultdict(deque)

USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_]{3,20}$')
EMAIL_PATTERN    = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
PASSWORD_MIN_LEN = 4


def _rate_cfg():
    limit  = current_app.config.get('LOGIN_RATE_LIMIT', 5)
    window = current_app.config.get('LOGIN_RATE_WINDOW', 900)
    return limit, window


def is_login_locked(ip):
    limit, window = _rate_cfg()
    now = time.time()
    attempts = FAILED_LOGIN_ATTEMPTS[ip]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    return len(attempts) >= limit


def record_failed_login(ip):
    FAILED_LOGIN_ATTEMPTS[ip].append(time.time())


def clear_failed_login(ip):
    FAILED_LOGIN_ATTEMPTS.pop(ip, None)


def can_access_conversation(user_id, other_user_id):
    return UserConnection.query.filter(
        (
            (UserConnection.user_id == user_id) &
            (UserConnection.matched_user_id == other_user_id)
        ) | (
            (UserConnection.user_id == other_user_id) &
            (UserConnection.matched_user_id == user_id)
        ),
        UserConnection.is_active.is_(True)
    ).first() is not None


def is_admin_user(user):
    admins = current_app.config.get('ADMIN_USERNAMES', [])
    if isinstance(admins, str):
        admins = [name.strip() for name in admins.split(',') if name.strip()]
    return bool(user and user.username in set(admins))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_or_render(template, context, error_msg, status=400):
    if request.is_json:
        return jsonify({'error': error_msg}), status
    return render_template(template, **context, error=error_msg)


# ==================== Authentication Routes ====================

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    problems = Problem.query.all()
    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = data.get('username', '').strip()
        email    = data.get('email', '').strip().lower()
        password = data.get('password', '')
        problems_selected = data.getlist('problems') if hasattr(data, 'getlist') else data.get('problems', [])

        ctx = {'problems': problems}

        if not username or not email or not password:
            return _json_or_render('register.html', ctx, 'Missing required fields')
        if not USERNAME_PATTERN.fullmatch(username):
            return _json_or_render('register.html', ctx, 'Username must be 3–20 characters, letters/numbers/underscores only')
        if not EMAIL_PATTERN.fullmatch(email):
            return _json_or_render('register.html', ctx, 'Please enter a valid email address')
        if len(password) < PASSWORD_MIN_LEN:
            return _json_or_render('register.html', ctx, f'Password must be at least {PASSWORD_MIN_LEN} characters')
        if User.query.filter_by(username=username).first():
            return _json_or_render('register.html', ctx, 'Username already taken')
        if User.query.filter_by(email=email).first():
            return _json_or_render('register.html', ctx, 'Email already registered')

        try:
            encryption_key  = MessageEncryption.generate_key().decode('utf-8')
            verify_token    = secrets.token_urlsafe(32)

            new_user = User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                encryption_key=encryption_key,
                email_verified=True,
                email_verify_token=verify_token,
                email_verify_sent_at=datetime.utcnow(),
            )
            if problems_selected:
                new_user.set_problems(problems_selected)

            db.session.add(new_user)
            db.session.commit()
            record_user_ip(new_user.id, source='register')

            # Send verification email (non-blocking — failure doesn't stop signup)
            try:
                from app.email_service import send_verification_email
                send_verification_email(email, verify_token)
            except Exception:
                logger.exception("Failed to send verification email to %s", email)

            if request.is_json:
                return jsonify({'success': True, 'message': 'Registration successful! Please check your email to verify your account.', 'redirect': url_for('auth.login')}), 201
            flash('Account created! Please check your email to verify your address before logging in.', 'success')
            return redirect(url_for('auth.login'))

        except Exception as e:
            db.session.rollback()
            logger.exception("Registration failed")
            return _json_or_render('register.html', ctx, f'Registration failed: {str(e)}', 500)

    return render_template('register.html', problems=problems)


@auth_bp.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(email_verify_token=token).first()
    if not user:
        flash('Invalid or expired verification link.', 'error')
        return redirect(url_for('auth.login'))

    # Token expires after 24 hours
    if user.email_verify_sent_at and (datetime.utcnow() - user.email_verify_sent_at) > timedelta(hours=24):
        flash('Verification link expired. Please register again or contact support.', 'error')
        return redirect(url_for('auth.login'))

    user.email_verified       = True
    user.email_verify_token   = None
    user.email_verify_sent_at = None
    db.session.commit()

    # Send welcome email
    try:
        from app.email_service import send_welcome_email
        send_welcome_email(user.email, user.username)
    except Exception:
        logger.exception("Failed to send welcome email")

    login_user(user, remember=False)
    flash('Email verified! Welcome to Friendship Circle.', 'success')
    return redirect(url_for('main.dashboard'))


@auth_bp.route('/resend-verification', methods=['POST'])
def resend_verification():
    data  = request.get_json() if request.is_json else request.form
    email = data.get('email', '').strip().lower()
    user  = User.query.filter_by(email=email).first()
    # Always return success to avoid email enumeration
    if user and not user.email_verified:
        token = secrets.token_urlsafe(32)
        user.email_verify_token   = token
        user.email_verify_sent_at = datetime.utcnow()
        db.session.commit()
        try:
            from app.email_service import send_verification_email
            send_verification_email(email, token)
        except Exception:
            logger.exception("Failed to resend verification email")
    if request.is_json:
        return jsonify({'success': True, 'message': 'If that email is registered, a new verification link has been sent.'})
    flash('If that email is registered and unverified, a new link has been sent.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        data  = request.get_json() if request.is_json else request.form
        email = data.get('email', '').strip().lower()
        user  = User.query.filter_by(email=email).first()
        # Always respond the same to avoid enumeration
        if user and user.email_verified and not user.is_banned:
            token = secrets.token_urlsafe(32)
            user.password_reset_token   = token
            user.password_reset_expires = datetime.utcnow() + timedelta(hours=1)
            db.session.commit()
            try:
                from app.email_service import send_password_reset_email
                send_password_reset_email(email, token)
            except Exception:
                logger.exception("Failed to send password reset email")

        if request.is_json:
            return jsonify({'success': True, 'message': 'If that email is registered, a reset link has been sent.'})
        flash('If that email is registered, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))
    return render_template('forgot_password.html')


@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(password_reset_token=token).first()
    if not user or not user.password_reset_expires or datetime.utcnow() > user.password_reset_expires:
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('auth.forgot_password'))

    if request.method == 'POST':
        data     = request.get_json() if request.is_json else request.form
        password = data.get('password', '')
        if len(password) < PASSWORD_MIN_LEN:
            if request.is_json:
                return jsonify({'error': f'Password must be at least {PASSWORD_MIN_LEN} characters'}), 400
            return render_template('reset_password.html', token=token, error=f'Password must be at least {PASSWORD_MIN_LEN} characters')

        user.password_hash          = generate_password_hash(password)
        user.password_reset_token   = None
        user.password_reset_expires = None
        db.session.commit()

        if request.is_json:
            return jsonify({'success': True, 'message': 'Password reset. Please log in.'})
        flash('Password reset successfully. Please log in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data       = request.get_json() if request.is_json else request.form
        username   = data.get('username', '').strip()
        password   = data.get('password', '')
        client_ip  = request.headers.get('X-Forwarded-For', request.remote_addr or 'unknown').split(',')[0].strip()

        if is_login_locked(client_ip):
            message = 'Too many failed login attempts. Please wait 15 minutes and try again.'
            if request.is_json:
                return jsonify({'error': message}), 429
            return render_template('login.html', error=message)

        user = User.query.filter(
            (User.username == username) | (User.email == username)
        ).first()

        if user and check_password_hash(user.password_hash, password):
            # Ban check
            if user.is_banned:
                message = 'Your account has been suspended. Contact support@friendshipcircle.app to appeal.'
                if request.is_json:
                    return jsonify({'error': message}), 403
                return render_template('login.html', error=message)

            # Email verification check (skip for OAuth/Clerk users who have no verify token flow)
            if not user.email_verified:
                message = 'Please verify your email before logging in. Check your inbox or request a new link.'
                if request.is_json:
                    return jsonify({'error': message, 'needs_verification': True}), 403
                return render_template('login.html', error=message, show_resend=True, email=user.email)

            clear_failed_login(client_ip)
            session.clear()
            login_user(user, remember=False)
            user.last_seen = datetime.utcnow()
            db.session.commit()
            record_user_ip(user.id, source='login')

            next_page = request.args.get('next')
            redirect_to = next_page if next_page and next_page.startswith('/') else url_for('main.dashboard')
            if request.is_json:
                return jsonify({'success': True, 'redirect': redirect_to}), 200
            return redirect(redirect_to)

        record_failed_login(client_ip)
        logger.warning('Failed login: username=%s ip=%s', username, client_ip)

        message = 'Invalid username or password'
        if request.is_json:
            return jsonify({'error': message}), 401
        return render_template('login.html', error=message)

    return render_template('login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('main.index'))


@auth_bp.route('/auth/clerk/callback', methods=['POST'])
def clerk_callback():
    data = request.get_json() or {}

    token = data.get('token') or data.get('id_token') or data.get('session_token')
    if token:
        from app.clerk import verify_clerk_jwt
        try:
            payload = verify_clerk_jwt(token)
        except Exception as e:
            return jsonify({'error': 'Invalid Clerk token', 'details': str(e)}), 401

        clerk_user_id = payload.get('sub')
        email         = payload.get('email')
        username      = payload.get('username') or (email.split('@')[0] if email else None)

        if not clerk_user_id or not email:
            return jsonify({'error': 'Clerk token missing required user fields'}), 400

        user = User.query.filter_by(email=email).first()
        if not user:
            try:
                encryption_key = MessageEncryption.generate_key().decode('utf-8')
                user = User(
                    id=str(uuid.uuid4()),
                    username=username,
                    email=email,
                    password_hash=generate_password_hash(uuid.uuid4().hex),
                    encryption_key=encryption_key,
                    email_verified=True,  # Clerk already verified the email
                )
                db.session.add(user)
                db.session.commit()
                record_user_ip(user.id, source='clerk_register')
                try:
                    from app.email_service import send_welcome_email
                    send_welcome_email(email, user.username)
                except Exception:
                    pass
            except Exception as e:
                db.session.rollback()
                return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

        if user.is_banned:
            return jsonify({'error': 'Account suspended'}), 403

        session.clear()
        login_user(user, remember=False)
        user.last_seen = datetime.utcnow()
        db.session.commit()
        return jsonify({'success': True, 'redirect': url_for('main.dashboard')}), 200

    # Legacy payload fallback
    clerk_user_id = data.get('clerk_user_id')
    email         = data.get('email')
    username      = data.get('username') or (email.split('@')[0] if email else None)

    if not clerk_user_id or not email:
        return jsonify({'error': 'Missing clerk payload'}), 400

    user = User.query.filter_by(email=email).first()
    if not user:
        try:
            encryption_key = MessageEncryption.generate_key().decode('utf-8')
            user = User(
                id=str(uuid.uuid4()),
                username=username,
                email=email,
                password_hash=generate_password_hash(uuid.uuid4().hex),
                encryption_key=encryption_key,
                email_verified=True,
            )
            db.session.add(user)
            db.session.commit()
            record_user_ip(user.id, source='clerk_register')
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': f'Failed to create user: {str(e)}'}), 500

    if user.is_banned:
        return jsonify({'error': 'Account suspended'}), 403

    session.clear()
    login_user(user, remember=False)
    user.last_seen = datetime.utcnow()
    db.session.commit()
    return jsonify({'success': True, 'redirect': url_for('main.dashboard')}), 200


# ==================== Main Routes ====================

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@main_bp.route('/dashboard')
@login_required
def dashboard():
    current_user.last_seen = datetime.utcnow()
    db.session.commit()
    unread_count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
    connections  = UserConnection.query.filter_by(user_id=current_user.id, is_active=True).all()
    return render_template('dashboard_neon.html', unread_count=unread_count, connections=connections)


@main_bp.route('/profile')
@login_required
def profile():
    return render_template('profile_neon.html', user=current_user)


@main_bp.route('/premium')
@login_required
def premium():
    return render_template('premium_neon.html')


@main_bp.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    data = request.get_json() if request.is_json else request.form
    try:
        if 'bio' in data:
            current_user.bio = data.get('bio', '').strip()
        if 'problems' in data:
            problems = data.getlist('problems') if hasattr(data, 'getlist') else data.get('problems', [])
            current_user.set_problems(problems)
        if 'preferred_region' in data:
            current_user.preferred_region = data.get('preferred_region')
        if 'preferred_timezone' in data:
            current_user.preferred_timezone = data.get('preferred_timezone')
        db.session.commit()
        return jsonify({'success': True, 'message': 'Profile updated successfully!'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Update failed: {str(e)}'}), 500


# ==================== Admin Routes ====================

@main_bp.route('/admin/messages')
@login_required
def admin_messages():
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    messages = Message.query.order_by(Message.sent_at.desc()).all()
    visible_messages = []
    for msg in messages:
        sender   = User.query.get(msg.sender_id)
        receiver = User.query.get(msg.receiver_id)
        try:
            sender_key = sender.encryption_key.encode('utf-8') if sender else None
            content    = MessageEncryption(sender_key).decrypt_message(msg.encrypted_content) if sender_key else '[Unknown sender]'
        except Exception:
            content = '[Could not decrypt]'
        visible_messages.append({
            'id':            msg.id,
            'sender_name':   sender.username   if sender   else msg.sender_id,
            'receiver_name': receiver.username if receiver else msg.receiver_id,
            'sent_at':       msg.sent_at.isoformat() + 'Z',
            'is_read':       msg.is_read,
            'content':       sanitize_message_content(content),
        })
    return render_template('admin_messages.html', messages=visible_messages)


@main_bp.route('/admin/moderation')
@login_required
def admin_moderation():
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    pending_reports = AbuseReport.query.filter_by(status='pending').order_by(AbuseReport.created_at.desc()).all()
    pending_events  = SafetyEvent.query.filter_by(review_status='pending').order_by(SafetyEvent.created_at.desc()).all()

    report_rows = []
    for report in pending_reports:
        reporter = User.query.get(report.reporter_id)
        target   = User.query.get(report.target_user_id)
        message  = Message.query.get(report.message_id) if report.message_id else None
        report_rows.append({
            'report':         report,
            'reporter_name':  reporter.username if reporter else report.reporter_id,
            'target_name':    target.username   if target   else report.target_user_id,
            'message_exists': message is not None,
        })

    event_rows = []
    for event in pending_events:
        user = User.query.get(event.user_id)
        event_rows.append({'event': event, 'user_name': user.username if user else event.user_id})

    return render_template('admin_moderation_neon.html', reports=report_rows, safety_events=event_rows)


@main_bp.route('/admin/moderation/report/<report_id>', methods=['POST'])
@login_required
def review_admin_report(report_id):
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    decision   = request.form.get('decision', 'resolved')
    resolution = request.form.get('resolution', 'Reviewed')
    review_report(report_id, current_user.id, decision=decision, resolution=resolution)

    # Notify reporter if resolved
    if decision == 'resolved':
        report = AbuseReport.query.get(report_id)
        if report:
            reporter = User.query.get(report.reporter_id)
            if reporter and reporter.email:
                try:
                    from app.email_service import send_report_actioned_email
                    send_report_actioned_email(reporter.email)
                except Exception:
                    pass

    return redirect(url_for('main.admin_moderation'))


@main_bp.route('/admin/moderation/event/<event_id>', methods=['POST'])
@login_required
def review_admin_event(event_id):
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    decision = request.form.get('decision', 'reviewed')
    review_safety_event(event_id, current_user.id, decision=decision)
    return redirect(url_for('main.admin_moderation'))


@main_bp.route('/admin/ban/<user_id>', methods=['POST'])
@login_required
def ban_user(user_id):
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    data   = request.get_json() if request.is_json else request.form
    reason = data.get('reason', 'Violation of community guidelines').strip()

    target = User.query.get(user_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    if target.username in (current_app.config.get('ADMIN_USERNAMES') or []):
        return jsonify({'error': 'Cannot ban an admin'}), 400

    target.is_banned  = True
    target.banned_at  = datetime.utcnow()
    target.ban_reason = reason
    target.banned_by  = current_user.id
    db.session.commit()

    try:
        from app.email_service import send_ban_notification_email
        send_ban_notification_email(target.email, reason)
    except Exception:
        logger.exception("Failed to send ban email")

    if request.is_json:
        return jsonify({'success': True, 'message': f'User {target.username} banned'})
    return redirect(url_for('main.admin_moderation'))


@main_bp.route('/admin/unban/<user_id>', methods=['POST'])
@login_required
def unban_user(user_id):
    if not is_admin_user(current_user):
        return jsonify({'error': 'Forbidden'}), 403
    target = User.query.get(user_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404
    target.is_banned  = False
    target.banned_at  = None
    target.ban_reason = None
    target.banned_by  = None
    db.session.commit()
    if request.is_json:
        return jsonify({'success': True})
    return redirect(url_for('main.admin_moderation'))


# ==================== Chat report ====================

@chat_bp.route('/moderation/report', methods=['POST'])
@login_required
def report_conversation():
    data           = request.get_json() if request.is_json else request.form
    target_user_id = data.get('target_user_id', '').strip()
    reason         = data.get('reason', '').strip()
    details        = (data.get('details') or '').strip()
    message_id     = (data.get('message_id') or '').strip() or None

    if not target_user_id or not reason:
        return jsonify({'error': 'Missing target user or reason'}), 400
    if not User.query.get(target_user_id):
        return jsonify({'error': 'Target user not found'}), 404

    create_report(current_user.id, target_user_id, reason, details, message_id=message_id)
    record_user_ip(current_user.id, source='report')

    # Notify reporter
    try:
        from app.email_service import send_report_received_email
        send_report_received_email(current_user.email)
    except Exception:
        pass

    return jsonify({'success': True, 'message': 'Report submitted for review'}), 201


# ==================== Matching Routes ====================

@match_bp.route('/find-match', methods=['POST'])
@login_required
def find_match():
    try:
        user_problems = set(current_user.get_problems())
        req           = request.get_json(silent=True) or {}
        region_pref   = req.get('region') or current_user.preferred_region

        if not user_problems:
            return jsonify({'error': 'Please select your problems first'}), 400

        existing_connections = db.session.query(UserConnection.matched_user_id).filter_by(user_id=current_user.id).all()
        existing_ids = [conn[0] for conn in existing_connections] + [current_user.id]

        from app.models import UserBlock
        blocked_ids    = db.session.query(UserBlock.blocked_id).filter_by(blocker_id=current_user.id,  block_type='block').all()
        blocked_by_ids = db.session.query(UserBlock.blocker_id).filter_by(blocked_id=current_user.id, block_type='block').all()
        existing_ids  += [b[0] for b in blocked_ids] + [b[0] for b in blocked_by_ids]

        all_users = User.query.filter(~User.id.in_(existing_ids), User.is_active.is_(True), User.is_banned.is_(False)).all()

        region_candidates = []
        other_candidates  = []
        for user in all_users:
            user_probs = set(user.get_problems())
            common = user_probs.intersection(user_problems)
            if common:
                from app.routes_new_features import _tz_offset_hours, _activity_score
                tz_self  = _tz_offset_hours(current_user.preferred_timezone or 'UTC')
                tz_other = _tz_offset_hours(user.preferred_timezone or 'UTC')
                tz_bonus  = max(0.0, 1.0 - abs(tz_self - tz_other) / 12.0)
                act_bonus = _activity_score(user)
                composite = len(common) + tz_bonus + act_bonus * 0.5
                entry = {'user': user, 'common_problems': list(common), 'score': composite}
                if region_pref and getattr(user, 'preferred_region', None) == region_pref:
                    region_candidates.append(entry)
                else:
                    other_candidates.append(entry)

        candidates = region_candidates if region_candidates else other_candidates
        candidates.sort(key=lambda x: x['score'], reverse=True)

        if not candidates:
            return jsonify({'message': 'No matching users found at the moment. Try again later!'}), 200

        selected_match = random.choice(candidates[:5]) if len(candidates) >= 5 else candidates[0]

        connection = UserConnection(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            matched_user_id=selected_match['user'].id,
            common_problems=','.join(selected_match['common_problems'])
        )
        db.session.add(connection)
        db.session.commit()

        try:
            from app.routes_new_features import _compute_match_score
            _compute_match_score(current_user, selected_match['user'], connection.id)
            db.session.commit()
        except Exception:
            pass

        return jsonify({
            'success': True,
            'message': 'Match found!',
            'matched_user_id': selected_match['user'].id,
            'common_problems': selected_match['common_problems']
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Matching failed: {str(e)}'}), 500


@match_bp.route('/matches')
@login_required
def get_matches():
    connections = UserConnection.query.filter_by(user_id=current_user.id, is_active=True).all()
    matches = []
    for conn in connections:
        matched_user = User.query.get(conn.matched_user_id)
        if matched_user:
            unread_count = Message.query.filter_by(sender_id=matched_user.id, receiver_id=current_user.id, is_read=False).count()
            matches.append({
                'connection_id':   conn.id,
                'user_id':         matched_user.id,
                'common_problems': conn.common_problems,
                'matched_at':      conn.matched_at.isoformat(),
                'unread_count':    unread_count
            })
    return jsonify(matches), 200


# ==================== Chat Routes ====================

@chat_bp.route('/send-message', methods=['POST'])
@login_required
def send_message():
    data        = request.get_json() if request.is_json else request.form
    receiver_id = data.get('receiver_id', '').strip()
    content     = data.get('content', '').strip()

    if not receiver_id or not content:
        return jsonify({'error': 'Missing receiver or content'}), 400

    if contains_blocked_contact_info(content):
        logger.warning('Blocked message attempt by user=%s', current_user.id)
        return jsonify({'error': 'Your message contains contact info (phone, Instagram, etc.). Please remove it.'}), 400

    sanitized_content = sanitize_message_content(content)
    if not sanitized_content:
        return jsonify({'error': 'Message content is empty after sanitization'}), 400

    try:
        if not can_access_conversation(current_user.id, receiver_id):
            return jsonify({'error': 'User connection not found'}), 404

        encryption        = MessageEncryption(current_user.encryption_key.encode('utf-8'))
        encrypted_content = encryption.encrypt_message(sanitized_content)

        message = Message(
            id=str(uuid.uuid4()),
            sender_id=current_user.id,
            receiver_id=receiver_id,
            encrypted_content=encrypted_content
        )
        db.session.add(message)
        db.session.commit()
        record_user_ip(current_user.id, source='message')

        try:
            create_safety_events(current_user.id, sanitized_content, message.id)
        except Exception:
            logger.warning('Failed to create safety events for message=%s', message.id)

        return jsonify({'success': True, 'message_id': message.id, 'sent_at': message.sent_at.isoformat() + 'Z'}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Message send failed: {str(e)}'}), 500


@chat_bp.route('/messages/<receiver_id>')
@login_required
def get_messages(receiver_id):
    try:
        if not can_access_conversation(current_user.id, receiver_id):
            return jsonify({'error': 'Access denied'}), 403

        since    = request.args.get('since')
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
            except Exception:
                pass

        base_filter = (
            ((Message.sender_id == current_user.id) & (Message.receiver_id == receiver_id)) |
            ((Message.sender_id == receiver_id) & (Message.receiver_id == current_user.id))
        )
        q = Message.query.filter(base_filter)
        if since_dt:
            q = q.filter(Message.sent_at > since_dt)
        messages = q.order_by(Message.sent_at.asc()).all()

        unread_q = Message.query.filter_by(sender_id=receiver_id, receiver_id=current_user.id, is_read=False)
        if since_dt:
            unread_q = unread_q.filter(Message.sent_at > since_dt)
        for msg in unread_q.all():
            msg.is_read = True
            msg.read_at = datetime.utcnow()
        db.session.commit()

        message_list = []
        for msg in messages:
            sender     = User.query.get(msg.sender_id)
            sender_key = sender.encryption_key.encode('utf-8') if sender else None
            try:
                decryption      = MessageEncryption(sender_key) if sender_key else None
                decrypted       = decryption.decrypt_message(msg.encrypted_content) if decryption else '[Unknown sender]'
                safe_content    = sanitize_message_content(decrypted)
            except Exception:
                safe_content = '[Message could not be decrypted]'
            message_list.append({'id': msg.id, 'sender_id': msg.sender_id, 'content': safe_content, 'sent_at': msg.sent_at.isoformat() + 'Z', 'is_read': msg.is_read})

        return jsonify(message_list), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch messages: {str(e)}'}), 500


@chat_bp.route('/chat')
@login_required
def chat_home():
    conn     = UserConnection.query.filter_by(user_id=current_user.id, is_active=True).first()
    first_id = conn.matched_user_id if conn else ''
    return render_template('chat_neon.html', chat_user_id=first_id, preferred_timezone=(current_user.preferred_timezone or 'auto'))


@chat_bp.route('/chat/<user_id>')
@login_required
def chat_page(user_id):
    if not can_access_conversation(current_user.id, user_id):
        return redirect(url_for('main.dashboard'))
    return render_template('chat_neon.html', chat_user_id=user_id, preferred_timezone=(current_user.preferred_timezone or 'auto'))


# ==================== Confession (Cast into the Void) ====================

confession_bp = Blueprint('confession', __name__)


@confession_bp.route('/', methods=['GET'])
@login_required
def index():
    waiting_count  = Confession.query.filter_by(status='waiting').count()
    absolved_count = Confession.query.filter_by(status='absolved').count()
    return render_template('confession.html', waiting_count=waiting_count, absolved_count=absolved_count)


@confession_bp.route('/cast', methods=['POST'])
@login_required
def cast():
    data    = request.get_json() or {}
    content = (data.get('content') or '').strip()
    if not content or len(content) < 5:
        return jsonify({'error': 'Too short — say a little more.'}), 400
    if len(content) > 1000:
        return jsonify({'error': 'Keep it under 1000 characters.'}), 400
    c = Confession(id=str(uuid.uuid4()), author_id=current_user.id, content=content, status='waiting')
    db.session.add(c)
    db.session.commit()
    return jsonify({'success': True, 'confession_id': c.id})


@confession_bp.route('/listen', methods=['GET'])
@login_required
def listen():
    stale = Confession.query.filter_by(status='claimed', listener_id=current_user.id).all()
    for s in stale:
        s.status = 'waiting'; s.listener_id = None; s.claimed_at = None
    if stale:
        db.session.commit()

    c = (Confession.query.filter_by(status='waiting').filter(Confession.author_id != current_user.id).order_by(db.func.random()).first())
    if not c:
        return jsonify({'empty': True})

    c.status = 'claimed'; c.listener_id = current_user.id; c.claimed_at = datetime.utcnow()
    db.session.commit()
    return jsonify({'empty': False, 'confession_id': c.id, 'content': c.content, 'age': _time_ago(c.created_at)})


@confession_bp.route('/pass/<confession_id>', methods=['POST'])
@login_required
def pass_confession(confession_id):
    c = Confession.query.get(confession_id)
    if not c or c.listener_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404
    c.status = 'waiting'; c.listener_id = None; c.claimed_at = None
    db.session.commit()
    return jsonify({'success': True})


@confession_bp.route('/absolve/<confession_id>', methods=['POST'])
@login_required
def absolve(confession_id):
    c = Confession.query.get(confession_id)
    if not c or c.listener_id != current_user.id:
        return jsonify({'error': 'Not found'}), 404

    existing = UserConnection.query.filter(
        db.or_(
            db.and_(UserConnection.user_id == current_user.id, UserConnection.matched_user_id == c.author_id),
            db.and_(UserConnection.user_id == c.author_id, UserConnection.matched_user_id == current_user.id)
        )
    ).first()

    if not existing:
        conn = UserConnection(id=str(uuid.uuid4()), user_id=current_user.id, matched_user_id=c.author_id, common_problems='confession')
        db.session.add(conn)

    c.status = 'absolved'
    db.session.commit()
    return jsonify({'success': True, 'chat_user_id': c.author_id})


def _time_ago(dt):
    diff = datetime.utcnow() - dt
    s = int(diff.total_seconds())
    if s < 60:    return 'just now'
    if s < 3600:  return f'{s // 60}m ago'
    if s < 86400: return f'{s // 3600}h ago'
    return f'{s // 86400}d ago'


def _rate_cfg():
    limit  = current_app.config.get('LOGIN_RATE_LIMIT', 5)
    window = current_app.config.get('LOGIN_RATE_WINDOW', 900)
    return limit, window


def is_login_locked(ip):
    limit, window = _rate_cfg()
    now = time.time()
    attempts = FAILED_LOGIN_ATTEMPTS[ip]
    while attempts and now - attempts[0] > window:
        attempts.popleft()
    return len(attempts) >= limit


def record_failed_login(ip):
    FAILED_LOGIN_ATTEMPTS[ip].append(time.time())


def clear_failed_login(ip):
    FAILED_LOGIN_ATTEMPTS.pop(ip, None)


def can_access_conversation(user_id, other_user_id):
    return UserConnection.query.filter(
        (
            (UserConnection.user_id == user_id) &
            (UserConnection.matched_user_id == other_user_id)
        ) | (
            (UserConnection.user_id == other_user_id) &
            (UserConnection.matched_user_id == user_id)
        ),
        UserConnection.is_active.is_(True)
    ).first() is not None


def is_admin_user(user):
    admins = current_app.config.get('ADMIN_USERNAMES', [])
    if isinstance(admins, str):
        admins = [name.strip() for name in admins.split(',') if name.strip()]
    return bool(user and user.username in set(admins))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_or_render(template, context, error_msg, status=400):
    if request.is_json:
        return jsonify({'error': error_msg}), status
    return render_template(template, **context, error=error_msg)
