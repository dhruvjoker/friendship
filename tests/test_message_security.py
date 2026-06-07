import unittest

from app import create_app
from app.content_safety import sanitize_message_content
from app.encryption import MessageEncryption
from app.models import Message, UserConnection, User, db


class MessageSecurityTests(unittest.TestCase):
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
                encryption_key=self.user_a_key
            )
            self.user_b = User(
                id=self.user_b_id,
                username='bob',
                email='bob@example.com',
                password_hash='x',
                encryption_key=self.user_b_key
            )
            db.session.add_all([self.user_a, self.user_b])
            db.session.commit()

            self.connection = UserConnection(
                id='conn-1',
                user_id=self.user_a_id,
                matched_user_id=self.user_b_id,
                common_problems='chat'
            )
            db.session.add(self.connection)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_sanitize_message_content_strips_script_payload(self):
        self.assertEqual(
            sanitize_message_content('<script>alert(1)</script>Hello'),
            'Hello'
        )

    def test_get_messages_requires_active_connection(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_a_id
            session['_fresh'] = True

        response = client.get(f'/api/chat/messages/{self.user_b_id}')
        self.assertEqual(response.status_code, 200)

    def test_get_messages_denies_unknown_conversation(self):
        client = self.app.test_client()
        unknown_user = 'user-z'
        with client.session_transaction() as session:
            session['_user_id'] = self.user_a_id
            session['_fresh'] = True

        response = client.get(f'/api/chat/messages/{unknown_user}')
        self.assertEqual(response.status_code, 403)

    def test_get_messages_returns_decrypted_sender_content(self):
        encrypted = MessageEncryption(self.user_a_key.encode('utf-8')).encrypt_message('Hello from Alice')
        message = Message(
            id='msg-1',
            sender_id=self.user_a_id,
            receiver_id=self.user_b_id,
            encrypted_content=encrypted,
        )
        with self.app.app_context():
            db.session.add(message)
            db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_b_id
            session['_fresh'] = True

        response = client.get(f'/api/chat/messages/{self.user_a_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Hello from Alice', response.get_data(as_text=True))

    def test_admin_messages_page_renders_for_admin(self):
        encrypted = MessageEncryption(self.user_a_key.encode('utf-8')).encrypt_message('Admin view test')
        message = Message(
            id='msg-2',
            sender_id=self.user_a_id,
            receiver_id=self.user_b_id,
            encrypted_content=encrypted,
        )
        with self.app.app_context():
            db.session.add(message)
            db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_a_id
            session['_fresh'] = True

        response = client.get('/admin/messages')
        self.assertEqual(response.status_code, 200)
        self.assertIn('Admin view test', response.get_data(as_text=True))

    def test_admin_messages_page_denies_non_admin(self):
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = self.user_b_id
            session['_fresh'] = True

        response = client.get('/admin/messages')
        self.assertEqual(response.status_code, 403)


if __name__ == '__main__':
    unittest.main()
