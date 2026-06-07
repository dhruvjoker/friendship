import unittest

from app.content_safety import contains_blocked_contact_info


class ContentSafetyTests(unittest.TestCase):
    def test_allows_normal_message(self):
        self.assertFalse(contains_blocked_contact_info('I am feeling okay today and want to chat.'))

    def test_blocks_instagram_handle(self):
        self.assertTrue(contains_blocked_contact_info('Reach me at @sophia_12'))

    def test_blocks_instagram_url(self):
        self.assertTrue(contains_blocked_contact_info('Check my instagram.com/sophia12'))

    def test_blocks_phone_number(self):
        self.assertTrue(contains_blocked_contact_info('My number is +91 98765 43210'))

    def test_blocks_platform_handle(self):
        self.assertTrue(contains_blocked_contact_info('Telegram: @supportbuddy'))

    def test_allows_email_address(self):
        self.assertFalse(contains_blocked_contact_info('Contact me at name@example.com'))


if __name__ == '__main__':
    unittest.main()
