from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import uuid

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """User model"""
    __tablename__ = 'users'

    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    username      = db.Column(db.String(50), unique=True, nullable=False)
    email         = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    # Email verification
    email_verified       = db.Column(db.Boolean, default=False)
    email_verify_token   = db.Column(db.String(128), unique=True)
    email_verify_sent_at = db.Column(db.DateTime)

    # Password reset
    password_reset_token   = db.Column(db.String(128), unique=True)
    password_reset_expires = db.Column(db.DateTime)

    # Ban
    is_banned  = db.Column(db.Boolean, default=False)
    banned_at  = db.Column(db.DateTime)
    ban_reason = db.Column(db.String(255))
    banned_by  = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)

    # Profile
    problems  = db.Column(db.Text)
    bio       = db.Column(db.Text)

    encryption_key = db.Column(db.String(255), nullable=False)

    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen        = db.Column(db.DateTime, default=datetime.utcnow)

    # Trial & Premium
    trial_started_at = db.Column(db.DateTime, nullable=True)   # set on first login
    is_premium       = db.Column(db.Boolean, default=False)
    premium_until    = db.Column(db.DateTime, nullable=True)
    preferred_region   = db.Column(db.String(64))
    preferred_timezone = db.Column(db.String(128))

    messages_sent     = db.relationship('Message', foreign_keys='Message.sender_id',   backref='sender',  lazy='dynamic')
    messages_received = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy='dynamic')
    connections       = db.relationship('UserConnection', foreign_keys='UserConnection.user_id', backref='user', lazy='dynamic')

    def __repr__(self):
        return f'<User {self.username}>'

    def set_problems(self, problems_list):
        self.problems = ','.join(problems_list) if isinstance(problems_list, list) else problems_list

    def get_problems(self):
        return [p.strip() for p in self.problems.split(',')] if self.problems else []

    def has_access(self):
        """True if user is within 3-day trial OR has active premium."""
        from datetime import datetime
        now = datetime.utcnow()
        # Active paid premium
        if self.is_premium:
            if self.premium_until is None or self.premium_until > now:
                return True
            # premium expired
            return False
        # Trial: 3 days from first login
        if self.trial_started_at:
            delta = now - self.trial_started_at
            return delta.days < 3
        # Trial not started yet (hasn't logged in) — allow
        return True


class UserConnection(db.Model):
    __tablename__ = 'user_connections'

    id              = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id         = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    matched_user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    common_problems = db.Column(db.Text)
    matched_at      = db.Column(db.DateTime, default=datetime.utcnow)
    is_active       = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<UserConnection {self.user_id} - {self.matched_user_id}>'


class UserIPLog(db.Model):
    __tablename__ = 'user_ip_logs'

    id           = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id      = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    ip_address   = db.Column(db.String(45), nullable=False)
    country      = db.Column(db.String(64))
    region       = db.Column(db.String(64))
    city         = db.Column(db.String(64))
    isp          = db.Column(db.String(128))
    asn          = db.Column(db.String(64))
    vpn_detected = db.Column(db.Boolean, default=False)
    user_agent   = db.Column(db.Text)
    source       = db.Column(db.String(32), nullable=False, default='request')
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)


class AbuseReport(db.Model):
    __tablename__ = 'abuse_reports'

    id             = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reporter_id    = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    target_user_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    message_id     = db.Column(db.String(36), db.ForeignKey('messages.id'))
    reason         = db.Column(db.String(64), nullable=False)
    details        = db.Column(db.Text)
    status         = db.Column(db.String(32), nullable=False, default='pending')
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at    = db.Column(db.DateTime)
    reviewed_by    = db.Column(db.String(36), db.ForeignKey('users.id'))
    resolution     = db.Column(db.Text)


class SafetyEvent(db.Model):
    __tablename__ = 'safety_events'

    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id       = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    event_type    = db.Column(db.String(32), nullable=False)
    severity      = db.Column(db.String(32), nullable=False, default='low')
    details       = db.Column(db.Text, nullable=False)
    message_id    = db.Column(db.String(36), db.ForeignKey('messages.id'))
    review_status = db.Column(db.String(32), nullable=False, default='pending')
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at   = db.Column(db.DateTime)
    reviewed_by   = db.Column(db.String(36), db.ForeignKey('users.id'))


class Message(db.Model):
    __tablename__ = 'messages'

    id                = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sender_id         = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    receiver_id       = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    encrypted_content = db.Column(db.Text, nullable=False)
    sent_at           = db.Column(db.DateTime, default=datetime.utcnow)
    is_read           = db.Column(db.Boolean, default=False)
    read_at           = db.Column(db.DateTime)

    def __repr__(self):
        return f'<Message from {self.sender_id} to {self.receiver_id}>'


class Problem(db.Model):
    __tablename__ = 'problems'

    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    category    = db.Column(db.String(50))

    def __repr__(self):
        return f'<Problem {self.name}>'


class UserSession(db.Model):
    __tablename__ = 'user_sessions'

    id            = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id       = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    session_token = db.Column(db.String(255), unique=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    last_activity = db.Column(db.DateTime, default=datetime.utcnow)
    is_active     = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f'<UserSession {self.user_id}>'


class Confession(db.Model):
    __tablename__ = 'confessions'

    id              = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    author_id       = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    content         = db.Column(db.Text, nullable=False)
    status          = db.Column(db.String(20), default='waiting')
    listener_id     = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=True)
    chat_session_id = db.Column(db.String(36), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    claimed_at      = db.Column(db.DateTime, nullable=True)

    author   = db.relationship('User', foreign_keys=[author_id],   backref='confessions_made')
    listener = db.relationship('User', foreign_keys=[listener_id], backref='confessions_heard')


class UserBlock(db.Model):
    __tablename__ = 'user_blocks'

    id         = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    blocker_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    blocked_id = db.Column(db.String(36), db.ForeignKey('users.id'), nullable=False)
    block_type = db.Column(db.String(16), nullable=False, default='block')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    blocker = db.relationship('User', foreign_keys=[blocker_id], backref='blocks_made')
    blocked = db.relationship('User', foreign_keys=[blocked_id], backref='blocks_received')

    __table_args__ = (
        db.UniqueConstraint('blocker_id', 'blocked_id', 'block_type', name='uq_user_block'),
    )


class MatchScore(db.Model):
    __tablename__ = 'match_scores'

    id               = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    connection_id    = db.Column(db.String(36), db.ForeignKey('user_connections.id'), nullable=False)
    interest_overlap = db.Column(db.Float, default=0.0)
    timezone_compat  = db.Column(db.Float, default=0.0)
    activity_score   = db.Column(db.Float, default=0.0)
    overall_score    = db.Column(db.Float, default=0.0)
    computed_at      = db.Column(db.DateTime, default=datetime.utcnow)


class MessageImage(db.Model):
    __tablename__ = 'message_images'

    id          = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id  = db.Column(db.String(36), db.ForeignKey('messages.id'), nullable=False)
    filename    = db.Column(db.String(255), nullable=False)
    mime_type   = db.Column(db.String(64), nullable=False)
    size_bytes  = db.Column(db.Integer)
    moderated   = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    message = db.relationship('Message', backref='images')
