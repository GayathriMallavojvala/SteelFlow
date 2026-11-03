"""Simple password-based demo authentication; not a substitute for plant SSO."""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta
from .models import now

ITERATIONS = 250_000

def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}'

def verify_password(password: str, encoded: str) -> bool:
    try:
        method, rounds, salt, digest = encoded.split('$')
        if method != 'pbkdf2_sha256': return False
        rounds = int(rounds)
        if rounds < 100_000 or rounds > 2_000_000: return False
        actual = hashlib.pbkdf2_hmac('sha256', password.encode(), base64.b64decode(salt), rounds)
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False

def new_token() -> str:
    return secrets.token_urlsafe(32)

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode('utf-8')).hexdigest()

def token_expiry():
    return now() + timedelta(hours=8)
