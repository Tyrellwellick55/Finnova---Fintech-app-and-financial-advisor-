# payments_core/services/encryption.py
import base64
import hashlib
import os
from django.conf import settings
from cryptography.fernet import Fernet

class EncryptionService:
    """Service for encryption and decryption operations"""
    
    @staticmethod
    def get_cipher():
        """Get encryption cipher using project secret key"""
        try:
            # Use first 32 chars of SECRET_KEY as base
            key = settings.SECRET_KEY.encode()
            # Hash to ensure 32 bytes
            hashed_key = hashlib.sha256(key).digest()
            # Encode for Fernet
            fernet_key = base64.urlsafe_b64encode(hashed_key)
            return Fernet(fernet_key)
        except Exception:
            # Fallback to a default key if SECRET_KEY is not available
            default_key = b'default-secret-key-for-development-only-32'
            fernet_key = base64.urlsafe_b64encode(default_key)
            return Fernet(fernet_key)
    
    @staticmethod
    def encrypt(data):
        """Encrypt string data"""
        if not data:
            return None
        try:
            cipher = EncryptionService.get_cipher()
            return cipher.encrypt(data.encode()).decode()
        except Exception:
            # Return original data if encryption fails
            return data
    
    @staticmethod
    def decrypt(encrypted_data):
        """Decrypt string data"""
        if not encrypted_data:
            return None
        try:
            cipher = EncryptionService.get_cipher()
            return cipher.decrypt(encrypted_data.encode()).decode()
        except Exception:
            # Return encrypted data if decryption fails
            return encrypted_data
    
    @staticmethod
    def hash_pin(pin):
        """Hash PIN for storage"""
        try:
            salt = os.urandom(32)
            key = hashlib.pbkdf2_hmac(
                'sha256',
                str(pin).encode(),
                salt,
                100000
            )
            return salt.hex() + key.hex()
        except Exception:
            # Simple hash fallback
            return hashlib.sha256(str(pin).encode()).hexdigest()
    
    @staticmethod
    def verify_pin(stored_hash, entered_pin):
        """Verify PIN against stored hash"""
        try:
            # Check if it's the new format (salt + key)
            if len(stored_hash) > 64:
                salt = bytes.fromhex(stored_hash[:64])
                stored_key = stored_hash[64:]
                
                key = hashlib.pbkdf2_hmac(
                    'sha256',
                    str(entered_pin).encode(),
                    salt,
                    100000
                )
                return key.hex() == stored_key
            else:
                # Old simple hash format
                entered_hash = hashlib.sha256(str(entered_pin).encode()).hexdigest()
                return entered_hash == stored_hash
        except Exception:
            return False