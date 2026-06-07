"""
socketio_events.py
==================
Real-time SocketIO events for Sphinx:
  • Typing indicators  (typing_start / typing_stop)
  • Read receipts      (messages_read)
  • Online presence    (user_online / user_offline)

Call register_socketio_events(socketio) from app/__init__.py
AFTER socketio.init_app(app).
"""

from flask_login import current_user
from flask_socketio import emit, join_room, leave_room
from flask import request


def register_socketio_events(socketio):

    @socketio.on('connect')
    def on_connect():
        if current_user.is_authenticated:
            # Each user joins their own private room keyed by user id
            join_room(f'user_{current_user.id}')
            # Broadcast online status to all matched contacts
            emit('user_online', {'user_id': current_user.id}, broadcast=True, include_self=False)

    @socketio.on('disconnect')
    def on_disconnect():
        if current_user.is_authenticated:
            emit('user_offline', {'user_id': current_user.id}, broadcast=True, include_self=False)

    # ── Typing ────────────────────────────────────────────────────────────────

    @socketio.on('typing_start')
    def on_typing_start(data):
        """
        Client emits:  { "to_user_id": "<uuid>" }
        Server forwards to recipient's room.
        """
        if not current_user.is_authenticated:
            return
        to_id = data.get('to_user_id')
        if to_id:
            emit(
                'typing_start',
                {'from_user_id': current_user.id},
                room=f'user_{to_id}'
            )

    @socketio.on('typing_stop')
    def on_typing_stop(data):
        if not current_user.is_authenticated:
            return
        to_id = data.get('to_user_id')
        if to_id:
            emit(
                'typing_stop',
                {'from_user_id': current_user.id},
                room=f'user_{to_id}'
            )

    # ── Read receipts ─────────────────────────────────────────────────────────

    @socketio.on('mark_read')
    def on_mark_read(data):
        """
        Client emits:  { "from_user_id": "<uuid>", "message_ids": ["<id>", ...] }
        Server updates DB and notifies sender.
        """
        if not current_user.is_authenticated:
            return

        from app.models import db, Message
        from datetime import datetime

        from_id = data.get('from_user_id')
        msg_ids = data.get('message_ids', [])

        if not from_id or not msg_ids:
            return

        updated_ids = []
        for mid in msg_ids[:100]:   # cap to prevent abuse
            msg = Message.query.get(mid)
            if msg and msg.receiver_id == current_user.id and not msg.is_read:
                msg.is_read = True
                msg.read_at = datetime.utcnow()
                updated_ids.append(mid)

        if updated_ids:
            db.session.commit()
            # Notify the original sender
            emit(
                'messages_read',
                {'by_user_id': current_user.id, 'message_ids': updated_ids},
                room=f'user_{from_id}'
            )

    # ── New message relay ─────────────────────────────────────────────────────

    @socketio.on('new_message_notify')
    def on_new_message_notify(data):
        """
        After REST /api/chat/send-message succeeds, client emits this to push
        a lightweight notification to the recipient so they can poll or update UI.
        { "to_user_id": "<uuid>", "message_id": "<uuid>", "sent_at": "ISO" }
        """
        if not current_user.is_authenticated:
            return
        to_id = data.get('to_user_id')
        if to_id:
            emit(
                'new_message',
                {
                    'from_user_id': current_user.id,
                    'message_id': data.get('message_id'),
                    'sent_at': data.get('sent_at'),
                },
                room=f'user_{to_id}'
            )
