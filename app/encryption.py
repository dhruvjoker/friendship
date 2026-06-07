from cryptography.fernet import Fernet
import base64
import hashlib

class MessageEncryption:
    """Handle message encryption and decryption"""
    
    def __init__(self, key=None):
        """Initialize encryption with a key"""
        if key is None:
            # Generate a key for demo - in production use secure key management
            key = Fernet.generate_key()
        self.cipher = Fernet(key)
        self.key = key
    
    @staticmethod
    def generate_key():
        """Generate a new encryption key"""
        return Fernet.generate_key()
    
    def encrypt_message(self, message):
        """Encrypt a message"""
        if isinstance(message, str):
            message = message.encode('utf-8')
        encrypted = self.cipher.encrypt(message)
        return encrypted.decode('utf-8')
    
    def decrypt_message(self, encrypted_message):
        """Decrypt a message"""
        if isinstance(encrypted_message, str):
            encrypted_message = encrypted_message.encode('utf-8')
        decrypted = self.cipher.decrypt(encrypted_message)
        return decrypted.decode('utf-8')

def hash_data(data):
    """Hash sensitive data for storage"""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()
