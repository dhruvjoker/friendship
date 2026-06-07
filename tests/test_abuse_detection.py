import unittest

from app import create_app
from app.encryption import MessageEncryption
from app.models import AbuseReport, Message, SafetyEvent, User, UserConnection, db


class AbuseDetectionTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app('development')
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            WTF_CSRF_ENABLED=False,
            ADMIN_USERNAMES=['alice'],
        )

        with self.app.app_context():
            db.drop_all()
            db.create_all()

            self.user_a_id = 'user-a'
            self.user_b_id = 'user-b'
            self.user_a_key = MessageEncryption.generate_key().decode('utf-8')
            self.user_b_key = MessageEncryption.generate_key().decode('utf-8')

            self.user_a = User(
                id=self.user_a_id,
                username='alice',
                email='alice@example.com',
                password_hash='x',
                encryption_key=self.user_a_key,
            )
            self.user_b = User(
                id=self.user_b_id,
                username='bob',
                email='bob@example.com',
                password_hash='x',
                encryption_key=self.user_b_key,
            )
            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()

            self.connection = UserConnection(
                id='conn-1',
                user_id=self.user_a_id,
                matched_user_id=self.user_b_id,
                common_problems='chat',
            )
            db.session.add(self.connection)
            db.session.commit()

            self.message_id = 'msg-1'
            self.message = Message(
                id=self.message_id,
                sender_id=self.user_a_id,
                receiver_id=self.user_b_id,
                encrypted_content=MessageEncryption(self.user_a_key.encode('utf-8')).encrypt_message('hello'),
            )
            db.session.add(self.message)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_reporting_message_creates_pending_report(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_b_id
            session['_fresh'] = True

        response = client.post(
            '/api/moderation/report',
            json={
                'message_id': self.message_id,
                'target_user_id': self.user_a_id,
                'reason': 'harassment',
                'details': 'This message felt abusive.'
            },
        )

        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            report = AbuseReport.query.filter_by(message_id=self.message_id).first()
        self.assertIsNotNone(report)
        self.assertEqual(report.status, 'pending')

    def test_safety_event_is_recorded_for_keyword(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_a_id
            session['_fresh'] = True

        response = client.post(
            '/api/chat/send-message',
            json={
                'receiver_id': self.user_b_id,
                'content': 'I want to hurt someone',
            },
        )

        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            event = SafetyEvent.query.filter_by(event_type='keyword').first()
        self.assertIsNotNone(event)
        self.assertIn('hurt', event.details.lower())

    def test_admin_moderation_queue_lists_pending_reports(self):
        with self.app.app_context():
            report = AbuseReport(
                id='report-1',
                reporter_id=self.user_b_id,
                target_user_id=self.user_a_id,
                message_id=self.message_id,
                reason='spam',
                details='Repeated promotional message',
                status='pending',
            )
            db.session.add(report)
            db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_a_id
            session['_fresh'] = True

        response = client.get('/admin/moderation')
        self.assertEqual(response.status_code, 200)
        self.assertIn('spam', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
