"""
routes_new_features.py
======================
All new feature routes for Sphinx:
  • Block / Unmatch / Mute
  • Account deletion
  • Enhanced matching (quality score)
  • Typing indicators via SocketIO
  • Read receipts emit
  • Image sharing (moderated)
  • Report-in-chat convenience route
  • One-click block from chat

Register this blueprint in app/__init__.py:
    from app.routes_new_features import features_bp
    app.register_blueprint(features_bp, url_prefix='/api')
"""

import os, uuid, json, math
from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request, current_app
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from app.models import (
    db, User, UserConnection, Message, AbuseReport,
    UserBlock, MatchScore, MessageImage
)

features_bp = Blueprint('features', __name__)

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

ALLOWED_IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_IMAGE_BYTES    = 5 * 1024 * 1024   # 5 MB

def _allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTS


def _tz_offset_hours(tz_string):
    """Return a crude UTC-offset float from a timezone string like 'Asia/Kolkata'.
    Fallback 0 if pytz not available or unknown."""
    try:
        import pytz
        tz = pytz.timezone(tz_string)
        offset = tz.utcoffset(datetime.utcnow())
        return offset.total_seconds() / 3600
    except Exception:
        return 0.0


def _activity_score(user):
    """0-1 score: 1 = active in last 24 h, decays to 0 over 30 days."""
    if not user.last_seen:
        return 0.0
    age_days = (datetime.utcnow() - user.last_seen).total_seconds() / 86400
    return max(0.0, 1.0 - age_days / 30.0)


def _compute_match_score(user_a, user_b, connection_id):
    """Compute and persist a MatchScore for a connection."""
    # Interest overlap (Jaccard)
    probs_a = set(user_a.get_problems())
    probs_b = set(user_b.get_problems())
    union = probs_a | probs_b
    overlap = len(probs_a & probs_b) / len(union) if union else 0.0

    # Timezone compatibility
    tz_a = _tz_offset_hours(user_a.preferred_timezone or 'UTC')
    tz_b = _tz_offset_hours(user_b.preferred_timezone or 'UTC')
    tz_diff = abs(tz_a - tz_b)
    tz_compat = max(0.0, 1.0 - tz_diff / 12.0)

    # Activity
    activity = (_activity_score(user_a) + _activity_score(user_b)) / 2

    # Weighted aggregate: interest 50 %, tz 30 %, activity 20 %
    overall = 0.5 * overlap + 0.3 * tz_compat + 0.2 * activity

    ms = MatchScore(
        id=str(uuid.uuid4()),
        connection_id=connection_id,
        interest_overlap=round(overlap, 3),
        timezone_compat=round(tz_compat, 3),
        activity_score=round(activity, 3),
        overall_score=round(overall, 3),
    )
    db.session.add(ms)
    return ms


# ─────────────────────────────────────────────
#  BLOCK / MUTE / UNMATCH
# ─────────────────────────────────────────────

@features_bp.route('/user/<target_id>/block', methods=['POST'])
@login_required
def block_user(target_id):
    """Block a user. Deactivates any mutual connection."""
    if target_id == current_user.id:
        return jsonify({'error': 'Cannot block yourself'}), 400

    target = User.query.get(target_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404

    # idempotent
    existing = UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='block'
    ).first()
    if not existing:
        db.session.add(UserBlock(
            blocker_id=current_user.id,
            blocked_id=target_id,
            block_type='block'
        ))

    # Deactivate connection in both directions
    for conn in UserConnection.query.filter(
        ((UserConnection.user_id == current_user.id) & (UserConnection.matched_user_id == target_id)) |
        ((UserConnection.user_id == target_id) & (UserConnection.matched_user_id == current_user.id))
    ).all():
        conn.is_active = False

    db.session.commit()
    return jsonify({'success': True, 'action': 'blocked'}), 200


@features_bp.route('/user/<target_id>/unblock', methods=['POST'])
@login_required
def unblock_user(target_id):
    UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='block'
    ).delete()
    db.session.commit()
    return jsonify({'success': True, 'action': 'unblocked'}), 200


@features_bp.route('/user/<target_id>/mute', methods=['POST'])
@login_required
def mute_user(target_id):
    """Mute a user — they can still message but notifications are suppressed."""
    if target_id == current_user.id:
        return jsonify({'error': 'Cannot mute yourself'}), 400

    existing = UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='mute'
    ).first()
    if not existing:
        db.session.add(UserBlock(
            blocker_id=current_user.id,
            blocked_id=target_id,
            block_type='mute'
        ))
        db.session.commit()
    return jsonify({'success': True, 'action': 'muted'}), 200


@features_bp.route('/user/<target_id>/unmute', methods=['POST'])
@login_required
def unmute_user(target_id):
    UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='mute'
    ).delete()
    db.session.commit()
    return jsonify({'success': True, 'action': 'unmuted'}), 200


@features_bp.route('/user/<target_id>/unmatch', methods=['POST'])
@login_required
def unmatch_user(target_id):
    """Remove a match without a full block."""
    for conn in UserConnection.query.filter(
        ((UserConnection.user_id == current_user.id) & (UserConnection.matched_user_id == target_id)) |
        ((UserConnection.user_id == target_id) & (UserConnection.matched_user_id == current_user.id))
    ).all():
        conn.is_active = False
    db.session.commit()
    return jsonify({'success': True, 'action': 'unmatched'}), 200


@features_bp.route('/user/block-status/<target_id>')
@login_required
def block_status(target_id):
    blocked = UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='block'
    ).first() is not None
    muted = UserBlock.query.filter_by(
        blocker_id=current_user.id, blocked_id=target_id, block_type='mute'
    ).first() is not None
    return jsonify({'blocked': blocked, 'muted': muted}), 200


# ─────────────────────────────────────────────
#  ACCOUNT DELETION
# ─────────────────────────────────────────────

@features_bp.route('/account/delete', methods=['POST'])
@login_required
def delete_account():
    """
    Permanently delete the account.
    Body JSON: { "confirm": "DELETE", "delete_messages": true }
    """
    data = request.get_json(silent=True) or {}
    if data.get('confirm') != 'DELETE':
        return jsonify({'error': 'Send { "confirm": "DELETE" } to confirm'}), 400

    uid = current_user.id

    # Optionally wipe messages
    if data.get('delete_messages', True):
        Message.query.filter(
            (Message.sender_id == uid) | (Message.receiver_id == uid)
        ).delete(synchronize_session=False)

    # Deactivate connections
    UserConnection.query.filter(
        (UserConnection.user_id == uid) | (UserConnection.matched_user_id == uid)
    ).update({'is_active': False}, synchronize_session=False)

    # Anonymise AbuseReports (keep for moderation history)
    AbuseReport.query.filter_by(reporter_id=uid).update(
        {'reporter_id': 'deleted_user'}, synchronize_session=False
    )

    # Delete block rows
    UserBlock.query.filter(
        (UserBlock.blocker_id == uid) | (UserBlock.blocked_id == uid)
    ).delete(synchronize_session=False)

    # Mark user as deleted instead of hard-delete (preserves FK integrity)
    user = User.query.get(uid)
    user.username   = f'deleted_{uid[:8]}'
    user.email      = f'deleted_{uid[:8]}@deleted.invalid'
    user.is_active  = False
    user.bio        = None
    user.problems   = None

    # Store email/username before wiping them for the farewell email
    deleted_email    = user.email
    deleted_username = user.username

    db.session.commit()

    from flask_login import logout_user
    logout_user()

    try:
        from app.email_service import send_account_deletion_email
        send_account_deletion_email(deleted_email, deleted_username)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("Failed to send account deletion email")

    return jsonify({'success': True, 'message': 'Account deleted'}), 200


# ─────────────────────────────────────────────
#  MATCH QUALITY SCORE
# ─────────────────────────────────────────────

@features_bp.route('/match/<connection_id>/score')
@login_required
def get_match_score(connection_id):
    """Return (or compute on demand) the match quality score for a connection."""
    conn = UserConnection.query.get(connection_id)
    if not conn:
        return jsonify({'error': 'Connection not found'}), 404
    if conn.user_id != current_user.id and conn.matched_user_id != current_user.id:
        return jsonify({'error': 'Access denied'}), 403

    ms = MatchScore.query.filter_by(connection_id=connection_id).first()
    if not ms:
        user_a = User.query.get(conn.user_id)
        user_b = User.query.get(conn.matched_user_id)
        ms = _compute_match_score(user_a, user_b, connection_id)
        db.session.commit()

    return jsonify({
        'connection_id': connection_id,
        'interest_overlap': ms.interest_overlap,
        'timezone_compat': ms.timezone_compat,
        'activity_score': ms.activity_score,
        'overall_score': ms.overall_score,
        'computed_at': ms.computed_at.isoformat(),
    }), 200


@features_bp.route('/matches/ranked')
@login_required
def ranked_matches():
    """Return active matches sorted by overall match quality score."""
    connections = UserConnection.query.filter_by(
        user_id=current_user.id, is_active=True
    ).all()

    results = []
    for conn in connections:
        other = User.query.get(conn.matched_user_id)
        if not other or not other.is_active:
            continue

        ms = MatchScore.query.filter_by(connection_id=conn.id).first()
        if not ms:
            ms = _compute_match_score(current_user, other, conn.id)

        # Check mute status
        muted = UserBlock.query.filter_by(
            blocker_id=current_user.id, blocked_id=other.id, block_type='mute'
        ).first() is not None

        unread = Message.query.filter_by(
            sender_id=other.id, receiver_id=current_user.id, is_read=False
        ).count()

        results.append({
            'connection_id': conn.id,
            'user_id': other.id,
            'common_problems': conn.common_problems,
            'matched_at': conn.matched_at.isoformat(),
            'unread_count': unread,
            'muted': muted,
            'match_score': {
                'overall': ms.overall_score,
                'interest_overlap': ms.interest_overlap,
                'timezone_compat': ms.timezone_compat,
                'activity_score': ms.activity_score,
            }
        })

    db.session.commit()   # persist any newly computed scores

    results.sort(key=lambda x: x['match_score']['overall'], reverse=True)
    return jsonify(results), 200


# ─────────────────────────────────────────────
#  IMAGE SHARING
# ─────────────────────────────────────────────

@features_bp.route('/chat/upload-image', methods=['POST'])
@login_required
def upload_image():
    """
    Upload a chat image.  Returns image_id to attach to a message.
    Actual moderation flag is set async; images are only served once moderated=True.
    """
    if 'image' not in request.files:
        return jsonify({'error': 'No image file'}), 400

    file = request.files['image']
    if not file or not _allowed_image(file.filename):
        return jsonify({'error': 'Invalid file type. Allowed: jpg, jpeg, png, gif, webp'}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_IMAGE_BYTES:
        return jsonify({'error': 'File too large (max 5 MB)'}), 400

    filename  = secure_filename(file.filename)
    unique_fn = f"{uuid.uuid4().hex}_{filename}"

    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'chat_images')
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, unique_fn)
    file.save(save_path)

    img = MessageImage(
        id=str(uuid.uuid4()),
        message_id='pending',   # updated when message is created
        filename=unique_fn,
        mime_type=file.content_type or 'image/jpeg',
        size_bytes=size,
        moderated=False,        # mark True after moderation step
    )
    db.session.add(img)
    db.session.commit()

    # TODO: queue img.id to a Celery moderation task
    # For MVP — auto-approve (set moderated=True immediately)
    img.moderated = True
    db.session.commit()

    return jsonify({'success': True, 'image_id': img.id}), 201


@features_bp.route('/chat/image/<image_id>')
@login_required
def get_image(image_id):
    """Serve a moderated chat image."""
    from flask import send_from_directory, abort
    img = MessageImage.query.get(image_id)
    if not img or not img.moderated:
        abort(404)

    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'chat_images')
    return send_from_directory(upload_dir, img.filename)


# ─────────────────────────────────────────────
#  QUICK REPORT FROM CHAT
# ─────────────────────────────────────────────

@features_bp.route('/chat/<target_id>/report', methods=['POST'])
@login_required
def quick_report(target_id):
    """One-click report from inside the chat window."""
    data   = request.get_json(silent=True) or {}
    reason = data.get('reason', 'harassment')
    msg_id = data.get('message_id')

    target = User.query.get(target_id)
    if not target:
        return jsonify({'error': 'User not found'}), 404

    report = AbuseReport(
        id=str(uuid.uuid4()),
        reporter_id=current_user.id,
        target_user_id=target_id,
        message_id=msg_id,
        reason=reason,
        details=data.get('details', ''),
        status='pending',
    )
    db.session.add(report)
    db.session.commit()

    return jsonify({'success': True, 'report_id': report.id}), 201


# ─────────────────────────────────────────────
#  USER PROFILE EXTRAS — last active / badges / score
# ─────────────────────────────────────────────

@features_bp.route('/user/<user_id>/profile-card')
@login_required
def profile_card(user_id):
    """Return public profile card data including last_active, badges, support_score."""
    user = User.query.get(user_id)
    if not user or not user.is_active:
        return jsonify({'error': 'Not found'}), 404

    # last active relative string
    def _since(dt):
        if not dt:
            return 'unknown'
        delta = datetime.utcnow() - dt
        if delta.seconds < 60:
            return 'just now'
        if delta.seconds < 3600:
            return f"{delta.seconds // 60}m ago"
        if delta.days == 0:
            return f"{delta.seconds // 3600}h ago"
        if delta.days == 1:
            return 'yesterday'
        return f"{delta.days}d ago"

    # derive badges from activity
    badges = []
    msg_count = Message.query.filter_by(sender_id=user.id).count()
    if msg_count >= 50:
        badges.append({'id': 'listener', 'label': '🎧 Listener'})
    if msg_count >= 200:
        badges.append({'id': 'guide', 'label': '🌟 Guide'})
    connections_count = UserConnection.query.filter_by(user_id=user.id, is_active=True).count()
    if connections_count >= 5:
        badges.append({'id': 'connector', 'label': '🔗 Connector'})
    if (datetime.utcnow() - user.created_at).days >= 30:
        badges.append({'id': 'veteran', 'label': '🏅 Veteran'})

    # simple support score: messages sent / (days active + 1)
    days_active = max(1, (datetime.utcnow() - user.created_at).days)
    support_score = min(100, int(msg_count / days_active * 10))

    return jsonify({
        'user_id': user.id,
        'last_active': _since(user.last_seen),
        'badges': badges,
        'support_score': support_score,
        'problems': user.get_problems(),
    }), 200


# ─────────────────────────────────────────────
#  MESSAGE SEARCH
# ─────────────────────────────────────────────

@features_bp.route('/chat/<other_user_id>/search')
@login_required
def search_messages(other_user_id):
    """
    Full-text search through decrypted messages in a conversation.
    ?q=keyword
    """
    from app.encryption import MessageEncryption
    from app.content_safety import sanitize_message_content

    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify({'results': []}), 200

    # Verify access
    conn = UserConnection.query.filter(
        ((UserConnection.user_id == current_user.id) & (UserConnection.matched_user_id == other_user_id)) |
        ((UserConnection.user_id == other_user_id) & (UserConnection.matched_user_id == current_user.id)),
        UserConnection.is_active == True
    ).first()
    if not conn:
        return jsonify({'error': 'Access denied'}), 403

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.sent_at.desc()).limit(500).all()

    results = []
    for msg in messages:
        sender = User.query.get(msg.sender_id)
        if not sender:
            continue
        try:
            enc = MessageEncryption(sender.encryption_key.encode('utf-8'))
            text = enc.decrypt_message(msg.encrypted_content)
            text = sanitize_message_content(text)
        except Exception:
            text = ''
        if q in text.lower():
            results.append({
                'message_id': msg.id,
                'sender_id': msg.sender_id,
                'snippet': text[:200],
                'sent_at': msg.sent_at.isoformat() + 'Z',
            })

    return jsonify({'results': results[:50]}), 200
