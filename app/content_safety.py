import re
import html

PHONE_PATTERN = re.compile(
    r'(?<!\d)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}(?!\d)'
)
SOCIAL_HANDLE_PATTERN = re.compile(r'(?<![\w.!%+-])@([\w.]{2,30})(?![\w.-])')
SOCIAL_URL_PATTERN = re.compile(
    r'(?i)(?:https?://)?(?:www\.)?(?:instagram\.com|ig\.me|facebook\.com|fb\.com|twitter\.com|x\.com|tiktok\.com|snapchat\.com|telegram\.me|t\.me|linkedin\.com|discord\.gg|discordapp\.com|github\.com|reddit\.com|wa\.me|whatsapp\.com)[^\s]*'
)
PLATFORM_HANDLE_PATTERN = re.compile(
    r'(?i)\b(?:instagram|ig|facebook|fb|twitter|x|tiktok|snapchat|telegram|discord|linkedin|github|reddit|whatsapp|signal|youtube)\s*[:@]\s*[\w.-]{2,30}\b'
)
SCRIPT_TAG_PATTERN = re.compile(r'(?is)<(script|style)[^>]*>.*?</\1>')
EVENT_HANDLER_PATTERN = re.compile(r'\son[a-z]+\s*=\s*["\'][^"\']*["\']', re.IGNORECASE)
UNSAFE_SCHEME_PATTERN = re.compile(r'(?i)\b(?:javascript|data|vbscript):')

MODERATION_KEYWORDS = {
    'crisis': [
        'kill myself',
        'suicide',
        'end my life',
        'self harm',
        'hurt myself',
    ],
    'harassment': [
        'idiot',
        'stupid',
        'worthless',
        'hate you',
        'disgusting',
        'you are trash',
    ],
    'scam': [
        'bitcoin',
        'crypto',
        'cash app',
        'venmo',
        'paypal',
        'wire me',
        'send money',
    ],
    'spam': [
        'free money',
        'click here',
        'buy now',
        'limited time',
        'offer',
    ],
}


def sanitize_message_content(text):
    """Remove obvious script payloads and escape the remaining text for safe rendering."""
    if not text:
        return ''

    sanitized = SCRIPT_TAG_PATTERN.sub(' ', text)
    sanitized = EVENT_HANDLER_PATTERN.sub(' ', sanitized)
    sanitized = UNSAFE_SCHEME_PATTERN.sub(' ', sanitized)
    sanitized = sanitized.replace('<', ' ').replace('>', ' ')
    sanitized = ' '.join(sanitized.split())
    return html.escape(sanitized)


def detect_moderation_signals(text):
    """Return a list of moderation categories and matched phrases for a message."""
    if not text:
        return []

    lowered = text.lower()
    matches = []
    for category, terms in MODERATION_KEYWORDS.items():
        found = [term for term in terms if term in lowered]
        if found:
            matches.append((category, found))

    return matches


def contains_blocked_contact_info(text):
    """Return True if the text contains phone numbers or social handle patterns."""
    if not text:
        return False

    if SOCIAL_HANDLE_PATTERN.search(text):
        return True

    if SOCIAL_URL_PATTERN.search(text):
        return True

    if PLATFORM_HANDLE_PATTERN.search(text):
        return True

    phone_match = PHONE_PATTERN.search(text)
    if phone_match:
        digits = sum(char.isdigit() for char in phone_match.group())
        return digits >= 8

    return False
